"""The Render server's state and the operations its tools share.

A ``RenderSession`` owns the per-image working profiles, the per-image locks
and the frame-size cache. A working profile is only reachable through
``image(path)`` (or ``open``/``reset``), which hold that image's lock, so a
tool can't read or change one without it.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError

from art_mcp import artdir, keyfile, sidecar
from art_mcp.concurrency import ImageLocks, image_key
from art_mcp.keyfile import KeyFile
from art_mcp.metadata import Exiftool
from art_mcp.preview import PreviewFolder
from art_mcp.profile import WorkingChanges, crop_rect, ppversion_of
from art_mcp.render.artcli import (
    ArtCli,
    ArtCliError,
    ArtCliTimeout,
    Rect,
    frame_probe_layer,
    png_size,
    probe_args,
    resolve_profile_args,
)
from art_mcp.schema import Crop as CropAdjustment
from art_mcp.schema import crop_bounds_problem

ErrorCode = Literal[
    "not_open", "not_found", "unknown_key", "render_failed", "timeout",
    "conflict", "exists", "out_of_range",
    "metadata_unavailable", "metadata_failed", "invalid_tag",
]

ProfileSource = Literal["sidecar", "default"]


def tool_error(code: ErrorCode, message: str) -> ToolError:
    return ToolError(f"{code}: {message}")


def no_profile_written() -> ToolError:
    return tool_error(
        "render_failed",
        "art-cli wrote no profile beside its output; turn off "
        '"Embed processing parameters in metadata" in ART\'s preferences',
    )


@dataclass
class WorkingProfile:
    image: Path
    changes: WorkingChanges
    sidecar_hash: str | None
    """SHA-256 of the sidecar on disk when this working profile was loaded
    (whichever source it was loaded from), or None if there was none: the
    baseline for detecting that someone else changed the sidecar."""
    sidecar_keys: KeyFile
    """That sidecar's content, to tell what someone else changed in it."""


class RenderSession:
    def __init__(
        self,
        cli: ArtCli,
        config_dir: Path,
        previews: PreviewFolder,
        exiftool: Exiftool | None,
        inline_previews: bool,
    ) -> None:
        self.cli = cli
        self.config_dir = config_dir
        self.previews = previews
        self.exiftool = exiftool
        self.inline_previews = inline_previews
        self._working: dict[str, WorkingProfile] = {}
        self._locks = ImageLocks()
        self._frames: dict[tuple[str, int, int, str], Rect] = {}
        self._art_version: str | None = None
        self._version_guard = threading.Lock()

    # -- the locking path ------------------------------------------------

    @contextmanager
    def image(self, path: str | Path) -> Iterator[WorkingProfile]:
        """Hold the lock of the open image at ``path`` and yield its working
        profile; ``not_open`` if it isn't open. Everything that reads or
        changes a working profile, or renders it, runs inside this."""
        with self._locks.hold(path):
            yield self._opened(path)

    def open(self, image: Path) -> ProfileSource:
        """Load ``image``'s profile (its sidecar, else ART's default) as its
        working profile, replacing any it had."""
        with self._locks.hold(image):
            return self._load(image, None)

    def reset(self, path: str, to: ProfileSource) -> ProfileSource:
        """Reload the open image's working profile from ``to``."""
        with self.image(path) as wp:
            return self._load(wp.image, to)

    def open_ppversions(self) -> list[int | None]:
        """The profile versions of the open images. Not locked: it reads one
        value from each and must not wait for a long render or export."""
        return [ppversion_of(wp.changes.profile) for wp in list(self._working.values())]

    def _opened(self, path: str | Path) -> WorkingProfile:
        wp = self._working.get(image_key(Path(path).resolve()))
        if wp is None:
            raise tool_error("not_open", f"{path} is not open; call open_image first")
        return wp

    def _load(self, image: Path, source: ProfileSource | None) -> ProfileSource:
        """Resolve ``image``'s complete processing profile with one art-cli
        run and make it the working profile. ``source`` None means the sidecar
        if there is one, else ART's default profile. Caller holds the lock."""
        sidecar_file = artdir.sidecar_path(image, self.config_dir)
        sidecar_bytes = sidecar.read(sidecar_file)
        if source == "sidecar" and sidecar_bytes is None:
            raise tool_error("not_found", f"{image.name} has no sidecar ({sidecar_file})")
        source = source or ("sidecar" if sidecar_bytes is not None else "default")

        output = self.previews.new_file("resolve", ".jpg")
        arp = Path(str(output) + ".arp")
        # art-cli reads a copy of exactly the bytes that are hashed, so a
        # sidecar changing meanwhile can't make the two disagree.
        sidecar_copy = self.previews.new_file("sidecar", ".arp")
        try:
            base = None
            if source == "sidecar" and sidecar_bytes is not None:
                sidecar_copy.write_bytes(sidecar_bytes)
                base = sidecar_copy
            self.run(resolve_profile_args(image, output, base), output)
            if not arp.is_file():
                raise no_profile_written()
            profile = keyfile.loads(arp.read_text(encoding="utf-8"))
        finally:
            output.unlink(missing_ok=True)
            arp.unlink(missing_ok=True)
            sidecar_copy.unlink(missing_ok=True)

        self._working[image_key(image)] = WorkingProfile(
            image=image,
            changes=WorkingChanges(profile),
            sidecar_keys=sidecar.parse(sidecar_bytes),
            sidecar_hash=sidecar.hash_or_none(sidecar_bytes),
        )
        return source

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
            raise tool_error("timeout", str(e)) from e
        except ArtCliError as e:
            raise tool_error("render_failed", str(e)) from e
        if not output.is_file():
            raise tool_error("render_failed", f"art-cli wrote no output to {output}")

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
        given = (crop.x, crop.y, crop.w, crop.h)
        if all(v is None for v in given):
            return
        current = crop_rect(wp.changes.profile)
        if any(v is None and c < 0 for v, c in zip(given, current)):
            raise tool_error(
                "out_of_range",
                "the image has no crop rectangle yet: give x, y, w and h together",
            )
        x, y, w, h = (v if v is not None else c for v, c in zip(given, current))
        frame = self.whole_frame(wp)
        problem = crop_bounds_problem(x, y, w, h, frame_w=frame.w, frame_h=frame.h)
        if problem:
            raise tool_error("out_of_range", problem)

    def whole_frame(self, wp: WorkingProfile) -> Rect:
        """The whole frame ART's ``[Crop]`` addresses, measured (see
        ``frame_of``) and cached."""
        profile = wp.changes.profile
        stat = wp.image.stat()
        row = frame_probe_layer(profile, strip="row")
        key = (image_key(wp.image), stat.st_mtime_ns, stat.st_size, row)
        if key not in self._frames:
            width, _ = self.probe_size(wp.image, row)
            _, height = self.probe_size(wp.image, frame_probe_layer(profile, strip="column"))
            self._frames[key] = Rect(0, 0, width, height)
        return self._frames[key]

    def probe_size(self, image: Path, layer_text: str) -> tuple[int, int]:
        layer = self.previews.new_file("probe", ".arp")
        output = self.previews.new_file("probe", ".png")
        try:
            layer.write_text(layer_text, encoding="utf-8")
            self.run(probe_args(image, output, layer), output)
            return png_size(output)
        except ArtCliError as e:
            raise tool_error("render_failed", str(e)) from e
        finally:
            layer.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
