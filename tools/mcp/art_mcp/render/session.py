"""The Render server's state and the operations its tools share.

A ``RenderSession`` owns the per-image locks and the plumbing the operations
share; the working profiles and the frame-size cache live in its
``ProfileStore`` (in memory unless another is given). A working profile is only reachable through
``image(path)`` (or ``open``/``reset``), which hold that image's lock, so a
tool can't read or change one without it.
"""

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from art_mcp import artdir, keyfile, sidecar
from art_mcp.concurrency import ImageLocks, image_key
from art_mcp.keyfile import KeyFile
from art_mcp.metadata import Exiftool
from art_mcp.preview import PreviewFolder
from art_mcp.profile import WorkingChanges, crop_problem, crop_rect, ppversion_of
from art_mcp.render.artcli import (
    ArtCli,
    ArtCliError,
    ArtCliTimeout,
    Rect,
    frame_probe_layer,
    layer_profile_args,
    png_size,
    probe_args,
    resolve_profile_args,
)
from art_mcp.render.defaults import resolve_default_profile
from art_mcp.render.errors import no_profile_written, render_error
from art_mcp.render.store import MemoryStore, ProfileStore, WorkingProfile
from art_mcp.schema import Crop as CropAdjustment

ProfileSource = Literal["sidecar", "default"]
OpenSource = Literal["sidecar", "default", "profile"]
"""Where ``open`` took the working profile from; ``profile`` is the file given
to it."""


class RenderSession:
    def __init__(
        self,
        cli: ArtCli,
        config_dir: Path,
        previews: PreviewFolder,
        exiftool: Exiftool | None,
        inline_previews: bool,
        store: ProfileStore | None = None,
    ) -> None:
        self.cli = cli
        self.config_dir = config_dir
        self.previews = previews
        self.exiftool = exiftool
        self.inline_previews = inline_previews
        self.store: ProfileStore = store if store is not None else MemoryStore()
        self._locks = ImageLocks()
        self._art_version: str | None = None
        self._version_guard = threading.Lock()
        self.last_export_folder: Path | None = None
        """Where the last ``export_batch`` that exported something wrote, the
        default home of contact sheets."""

    # -- the locking path ------------------------------------------------

    @contextmanager
    def image(self, path: str | Path) -> Iterator[WorkingProfile]:
        """Hold the lock of the open image at ``path`` and yield its working
        profile; ``not_open`` if it isn't open. Everything that reads or
        changes a working profile, or renders it, runs inside this."""
        with self._locks.hold(path):
            yield self._opened(path)

    @contextmanager
    def locked_folder(self, folder: Path) -> Iterator[None]:
        """Hold the lock of ``folder``, for writing a numbered file into it
        without two calls taking the same number. Never taken while an
        image's lock is held."""
        with self._locks.hold(folder):
            yield

    def open(self, image: Path, profile: Path | None = None) -> OpenSource:
        """Load ``image``'s profile (its sidecar, else ART's default) as its
        working profile, replacing any it had. With ``profile`` (an ``.arp``,
        full or partial) it is that file over ART's default profile instead,
        and the image's own sidecar is not read."""
        with self._locks.hold(image):
            return self._load(image, None, profile)

    def reset(self, path: str, to: ProfileSource) -> ProfileSource:
        """Reload the open image's working profile from ``to``."""
        with self.image(path) as wp:
            self._load(wp.image, to)
        return to

    def open_ppversions(self) -> list[int | None]:
        """The profile versions of the open images. Not locked: it reads one
        value from each and must not wait for a long render or export."""
        return [ppversion_of(wp.changes.profile) for wp in self.store.all()]

    def _opened(self, path: str | Path) -> WorkingProfile:
        wp = self.store.get(Path(path).resolve())
        if wp is None:
            raise render_error("not_open", f"{path} is not open; call open_image first")
        return wp

    def _load(
        self, image: Path, source: ProfileSource | None, preset: Path | None = None
    ) -> OpenSource:
        """Resolve ``image``'s complete processing profile with one art-cli
        run and make it the working profile. ``source`` None means the sidecar
        if there is one, else ART's default profile; ``preset`` (an ``.arp``)
        means that file over ART's default profile, without looking at the
        sidecar (so none is the baseline for saving). Caller holds the lock."""
        sidecar_bytes = None
        origin: OpenSource = "profile"
        if preset is None:
            sidecar_file = artdir.sidecar_path(image, self.config_dir)
            sidecar_bytes = sidecar.read(sidecar_file)
            if source == "sidecar" and sidecar_bytes is None:
                raise render_error("not_found", f"{image.name} has no sidecar ({sidecar_file})")
            origin = source or ("sidecar" if sidecar_bytes is not None else "default")

        output = self.previews.new_file("resolve", ".jpg")
        arp = Path(str(output) + ".arp")
        # art-cli reads a copy of exactly the bytes that are hashed, so a
        # sidecar changing meanwhile can't make the two disagree.
        sidecar_copy = self.previews.new_file("sidecar", ".arp")
        try:
            base = None
            if origin == "sidecar" and sidecar_bytes is not None:
                sidecar_copy.write_bytes(sidecar_bytes)
                base = sidecar_copy
            self.run(resolve_profile_args(image, output, base, preset), output)
            if not arp.is_file():
                raise no_profile_written()
            profile = keyfile.loads(arp.read_text(encoding="utf-8"))
        finally:
            output.unlink(missing_ok=True)
            arp.unlink(missing_ok=True)
            sidecar_copy.unlink(missing_ok=True)

        self.store.put(
            WorkingProfile(
                image=image,
                changes=WorkingChanges(profile),
                sidecar_keys=sidecar.parse(sidecar_bytes),
                sidecar_hash=sidecar.hash_or_none(sidecar_bytes),
                token=uuid.uuid4().hex,
            )
        )
        return origin

    def layered_profile(self, wp: WorkingProfile, preset: Path) -> KeyFile:
        """``wp``'s working profile with ``preset`` (an ``.arp``, full or
        partial) laid over it, as art-cli loads ``-p <working> -p <preset>``
        and writes the complete result: the preset's keys win and the loader's
        own rules apply, every other key stays. Doesn't change ``wp``; call
        with the image's lock held."""
        working = self.previews.new_file("working", ".arp")
        output = self.previews.new_file("layer", ".jpg")
        arp = Path(str(output) + ".arp")
        try:
            working.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
            self.run(layer_profile_args(wp.image, output, [working, preset]), output)
            if not arp.is_file():
                raise no_profile_written()
            try:
                return keyfile.loads(arp.read_text(encoding="utf-8"))
            except ValueError as e:
                raise render_error("render_failed", f"art-cli wrote a profile that does not parse: {e}") from e
        finally:
            for leftover in (working, output, arp):
                leftover.unlink(missing_ok=True)

    def commit(self, wp: WorkingProfile) -> None:
        """Hand a working profile back to the store after changing it (call
        with the image's lock held)."""
        self.store.put(wp)

    def default_profile(self, wp: WorkingProfile) -> KeyFile:
        """ART's default profile for the open image, resolved with art-cli the
        first time and kept with its working profile after that (call with
        the image's lock held)."""
        if wp.default is None:
            wp.default = resolve_default_profile(self.cli, self.previews, wp.image)
            self.commit(wp)
        return wp.default

    # -- art-cli ---------------------------------------------------------

    def art_version(self) -> str:
        with self._version_guard:
            if self._art_version is None:
                self._art_version = self.cli.version()
            return self._art_version

    def run(self, args: list[str], output: Path, timeout: float | None = None) -> None:
        """Run art-cli, mapping its failures to tool errors; ``output`` must
        exist afterwards."""
        try:
            self.cli.run(args, timeout=timeout)
        except ArtCliTimeout as e:
            raise render_error("timeout", str(e)) from e
        except ArtCliError as e:
            raise render_error("render_failed", str(e)) from e
        if not output.is_file():
            raise render_error("render_failed", f"art-cli wrote no output to {output}")

    # -- the frame (call with the image's lock held) -----------------------

    def frame_of(self, wp: WorkingProfile) -> Rect:
        """The area, in the pixels ART's ``[Crop]`` addresses, that a region's
        fractions refer to: the working profile's crop if it has one (so a
        region is a fraction of the image as previewed), else the whole frame.

        The frame is the raw image after coarse rotation and the raw border,
        and nothing in a profile or file header reports it cheaply, so it is
        measured: art-cli clamps an oversized crop to the frame, so rendering
        a 1 px strip with a huge crop yields a PNG as wide (then as tall) as
        the frame (~0.5 s each on a 24 MP raw, no full render). The result is
        cached per image file and per frame-defining profile groups.
        """
        profile = wp.changes.profile
        x, y, w, h = crop_rect(profile)
        if profile.get("Crop", {}).get("Enabled") == "true" and x >= 0 and y >= 0 and w > 0 and h > 0:
            return Rect(x, y, w, h)

        return self.whole_frame(wp)

    def check_crop(self, wp: WorkingProfile, crop: CropAdjustment) -> None:
        """Reject a crop rectangle that doesn't fit the image's frame; fields
        not in the request keep the working profile's values."""
        def frame() -> tuple[int, int]:
            whole = self.whole_frame(wp)
            return whole.w, whole.h

        problem = crop_problem(wp.changes.profile, crop, frame)
        if problem:
            raise render_error("out_of_range", problem)

    def whole_frame(self, wp: WorkingProfile) -> Rect:
        """The whole frame ART's ``[Crop]`` addresses, measured (see
        ``frame_of``) and cached."""
        profile = wp.changes.profile
        stat = wp.image.stat()
        row = frame_probe_layer(profile, strip="row")
        key = (image_key(wp.image), stat.st_mtime_ns, stat.st_size, row)
        frame = self.store.get_frame(key)
        if frame is None:
            width, _ = self.probe_size(wp.image, row)
            _, height = self.probe_size(wp.image, frame_probe_layer(profile, strip="column"))
            frame = Rect(0, 0, width, height)
            self.store.put_frame(key, frame)
        return frame

    def probe_size(self, image: Path, layer_text: str) -> tuple[int, int]:
        layer = self.previews.new_file("probe", ".arp")
        output = self.previews.new_file("probe", ".png")
        try:
            layer.write_text(layer_text, encoding="utf-8")
            self.run(probe_args(image, output, layer), output)
            return png_size(output)
        except ArtCliError as e:
            raise render_error("render_failed", str(e)) from e
        finally:
            layer.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
