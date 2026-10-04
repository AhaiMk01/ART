"""The Render server: open images and render previews headlessly via art-cli.

Edits live in a per-image *working profile* held in memory, seeded from the
image's sidecar (or ART's default profile) and never written back by renders.
"""

import argparse
import base64
import functools
import os
import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import NoBackChannelError
from mcp.types import (
    CallToolResult,
    ClientCapabilities,
    ContentBlock,
    ElicitationCapability,
    ImageContent,
    TextContent,
)
from pydantic import BaseModel, WithJsonSchema

from art_mcp import artdir, keyfile, sidecar
from art_mcp.concurrency import ImageLocks, image_key
from art_mcp.keyfile import KeyFile
from art_mcp.metadata import Exiftool, ExiftoolError, ExiftoolTimeout, InvalidTag, Metadata
from art_mcp.preview import PreviewFolder, default_root, sweep_stale
from art_mcp.profile import Conflict as EditConflict
from art_mcp.profile import (
    ProfileView,
    RawEdit,
    UnknownKey,
    WorkingChanges,
    ppversion_of,
    read_format,
    version_warnings,
)
from art_mcp.schema import (
    AdjustmentError,
    AdjustmentsDescription,
    adjustments_json_schema,
    parse_adjustments,
)
from art_mcp.schema import describe_adjustments as schema_description
from art_mcp.render.artcli import (
    ArtCli,
    ArtCliError,
    ArtCliTimeout,
    export_args,
    Rect,
    crop_profile,
    frame_probe_layer,
    png_size,
    preview_args,
    probe_args,
    region_rect,
    resize_profile,
    resolve_profile_args,
)

PREVIEW_SIZE = 1024
MAX_PREVIEW_SIZE = 2576
"""Claude downscales images with a longer edge above this."""

ErrorCode = Literal[
    "not_open", "not_found", "unknown_key", "render_failed", "timeout",
    "conflict", "exists", "out_of_range",
    "metadata_unavailable", "metadata_failed", "invalid_tag",
]

EXPORT_SUFFIXES = {"jpeg": ".jpg", "tiff": ".tif", "png": ".png"}

# Validated by hand (parse_adjustments) so a bad value is reported as
# out_of_range rather than as a generic schema error; the published input
# schema is still the typed one.
AdjustmentsArg = Annotated[
    dict[str, Any] | None,
    WithJsonSchema({"anyOf": [adjustments_json_schema(), {"type": "null"}]}),
]


ProfileSource = Literal["sidecar", "default"]


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


class MetadataSummary(BaseModel):
    camera: str | None
    """Make and model, e.g. "SONY ILCE-7M3"."""
    lens: str | None
    capture_date: str | None
    width: int | None
    height: int | None


def summarize(m: Metadata) -> MetadataSummary:
    camera = " ".join(part for part in (m.make, m.model) if part)
    return MetadataSummary(
        camera=camera or None,
        lens=m.lens,
        capture_date=m.capture_date,
        width=m.width,
        height=m.height,
    )


class OpenedImage(BaseModel):
    path: str
    profile_from: ProfileSource
    art_version: str
    metadata: MetadataSummary | None = None
    """None when exiftool is unavailable or couldn't read the file; call
    inspect_image for the reason."""


class ResetResult(BaseModel):
    profile_from: ProfileSource


class EditResult(BaseModel):
    changed: list[RawEdit]
    """Each [Group] Key whose value this call changed, with its new value
    (re-setting a value is not a change)."""
    implied: list[RawEdit]
    """The part of `changed` that was not asked for: a disabled tool enabled
    because it was adjusted, White Balance switched to CustomTemp."""
    warnings: list[str]


class ExportResult(BaseModel):
    path: str
    """The exported image."""
    profile_path: str | None
    """The `.arp` written beside it, when `write_profile` was set."""


OnConflict = Literal["merge", "overwrite", "cancel"]
SaveHow = Literal["written", "merged", "overwritten", "cancelled"]


class ConflictChoice(BaseModel):
    choice: OnConflict


class SaveResult(BaseModel):
    saved: bool
    path: str
    """The sidecar file."""
    how: SaveHow
    """`written` (nothing had changed there), `merged`, `overwritten` or
    `cancelled` (nothing saved)."""


class PartialProfileResult(BaseModel):
    written: bool
    """False when the agent has changed nothing: no file is written."""
    path: str
    keys: list[str]
    """The `[Group] Key` entries written."""


class Region(BaseModel):
    """An area of the image as fractions (0 to 1) of its width and height."""

    x: float
    y: float
    w: float
    h: float

    def inside_image(self) -> bool:
        eps = 1e-9
        return (
            self.x >= 0 and self.y >= 0 and self.w > 0 and self.h > 0
            and self.x + self.w <= 1 + eps and self.y + self.h <= 1 + eps
        )  # fmt: skip


class Preview(BaseModel):
    path: str
    """JPEG file; open it to look at the preview."""
    max_size: int


def move_over(source: Path, target: Path) -> None:
    """Move ``source`` to ``target``, replacing it; works across drives."""
    try:
        os.replace(source, target)
    except OSError:
        shutil.copyfile(source, target)  # temp folder on another drive
        source.unlink()


def no_profile_written() -> ToolError:
    return tool_error(
        "render_failed",
        "art-cli wrote no profile beside its output; turn off "
        '"Embed processing parameters in metadata" in ART\'s preferences',
    )


def tool_error(code: ErrorCode, message: str) -> ToolError:
    return ToolError(f"{code}: {message}")


def build_server(
    cli: ArtCli,
    config_dir: Path,
    previews: PreviewFolder,
    *,
    exiftool: Exiftool | None = None,
    inline_previews: bool = False,
) -> MCPServer:
    working: dict[str, WorkingProfile] = {}
    locks = ImageLocks()
    frames: dict[tuple[str, int, int, str], Rect] = {}

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            previews.remove()

    server = MCPServer(
        "art-render",
        instructions=(
            "Process raw images with ART without its editor. Call open_image "
            "first; render_preview returns a JPEG path to open and look at."
        ),
        lifespan=lifespan,
    )

    @functools.cache
    def art_version() -> str:
        return cli.version()

    def run(args: list[str], output: Path, timeout: float | None = None) -> None:
        try:
            cli.run(args, timeout=timeout)
        except ArtCliTimeout as e:
            raise tool_error("timeout", str(e)) from e
        except ArtCliError as e:
            raise tool_error("render_failed", str(e)) from e
        if not output.is_file():
            raise tool_error("render_failed", f"art-cli wrote no output to {output}")

    def opened(path: str) -> WorkingProfile:
        wp = working.get(image_key(Path(path).resolve()))
        if wp is None:
            raise tool_error("not_open", f"{path} is not open; call open_image first")
        return wp

    def load_working_profile(image: Path, source: ProfileSource | None) -> ProfileSource:
        """Resolve ``image``'s complete processing profile with one art-cli
        run and make it the working profile. ``source`` None means the sidecar
        if there is one, else ART's default profile."""
        sidecar_file = artdir.sidecar_path(image, config_dir)
        sidecar_bytes = sidecar.read(sidecar_file)
        if source == "sidecar" and sidecar_bytes is None:
            raise tool_error("not_found", f"{image.name} has no sidecar ({sidecar_file})")
        source = source or ("sidecar" if sidecar_bytes is not None else "default")

        output = previews.new_file("resolve", ".jpg")
        arp = Path(str(output) + ".arp")
        # art-cli reads a copy of exactly the bytes that are hashed, so a
        # sidecar changing meanwhile can't make the two disagree.
        sidecar_copy = previews.new_file("sidecar", ".arp")
        try:
            base = None
            if source == "sidecar" and sidecar_bytes is not None:
                sidecar_copy.write_bytes(sidecar_bytes)
                base = sidecar_copy
            run(resolve_profile_args(image, output, base), output)
            if not arp.is_file():
                raise no_profile_written()
            profile = keyfile.loads(arp.read_text(encoding="utf-8"))
        finally:
            output.unlink(missing_ok=True)
            arp.unlink(missing_ok=True)
            sidecar_copy.unlink(missing_ok=True)

        working[image_key(image)] = WorkingProfile(
            image=image,
            changes=WorkingChanges(profile),
            sidecar_keys=sidecar.parse(sidecar_bytes),
            sidecar_hash=sidecar.hash_or_none(sidecar_bytes),
        )
        return source

    async def ask_user(
        ctx: Context, target: Path, theirs: list[str], ours: list[str]
    ) -> OnConflict | None:
        """The user's choice about a changed sidecar, or None if the client
        can't ask. Declining or dismissing the question is `cancel`."""
        asks = ClientCapabilities(elicitation=ElicitationCapability())
        if not ctx.request_context.session.check_client_capability(asks):
            return None
        try:
            answer = await ctx.elicit(
                f"{target.name} was changed since the agent loaded it "
                f"(changed there: {', '.join(theirs) or 'unknown'}). The agent changed: "
                f"{', '.join(ours) or 'nothing'}. Merge = keep the sidecar's values and "
                "apply only the agent's changes; overwrite = replace the sidecar with "
                "the agent's profile (a backup is kept).",
                ConflictChoice,
            )
        except NoBackChannelError:
            return None  # newer protocol versions: a tool can't ask mid-call
        return answer.data.choice if answer.action == "accept" else "cancel"

    @server.tool()
    def open_image(path: str) -> OpenedImage:
        """Open an image and load its processing profile (from its sidecar,
        else ART's default profile) as the working profile."""
        image = Path(path).resolve()
        if not image.is_file():
            raise tool_error("not_found", f"{image} does not exist")
        with locks.hold(image):
            source = load_working_profile(image, None)
        summary = None
        if exiftool is not None:
            try:
                summary = summarize(exiftool.read(image))
            except ExiftoolError:
                pass  # opening still works; inspect_image reports the reason
        return OpenedImage(
            path=str(image), profile_from=source, art_version=art_version(), metadata=summary
        )

    @server.tool()
    def reset_profile(path: str, to: ProfileSource) -> ResetResult:
        """Discard working-profile changes: reload the profile from the
        image's sidecar, or from ART's default profile."""
        with locks.hold(path):
            return ResetResult(profile_from=load_working_profile(opened(path).image, to))

    def probe_size(image: Path, layer_text: str) -> tuple[int, int]:
        layer = previews.new_file("probe", ".arp")
        output = previews.new_file("probe", ".png")
        try:
            layer.write_text(layer_text, encoding="utf-8")
            run(probe_args(image, output, layer), output)
            return png_size(output)
        except ArtCliError as e:
            raise tool_error("render_failed", str(e)) from e
        finally:
            layer.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    def frame_of(wp: WorkingProfile) -> Rect:
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
        crop = profile.get("Crop", {})
        try:
            x, y, w, h = (int(crop[k]) for k in ("X", "Y", "W", "H"))
        except (KeyError, ValueError):
            pass
        else:
            if crop.get("Enabled") == "true" and x >= 0 and y >= 0 and w > 0 and h > 0:
                return Rect(x, y, w, h)

        stat = wp.image.stat()
        row = frame_probe_layer(profile, strip="row")
        key = (image_key(wp.image), stat.st_mtime_ns, stat.st_size, row)
        if key not in frames:
            width, _ = probe_size(wp.image, row)
            _, height = probe_size(wp.image, frame_probe_layer(profile, strip="column"))
            frames[key] = Rect(0, 0, width, height)
        return frames[key]

    @server.tool()
    def render_preview(
        path: str,
        max_size: int = PREVIEW_SIZE,
        region: Region | None = None,
        inline: bool | None = None,
    ) -> Annotated[CallToolResult, Preview]:
        """Render the working profile as a JPEG (long edge `max_size` px, 1 to
        2576) and return its path. `region` {x, y, w, h}, as fractions of the
        image, renders just that area at 1:1 (shrunk only to fit `max_size`).
        `inline` also returns the image itself (default: the server's
        --inline-previews setting)."""
        if not 1 <= max_size <= MAX_PREVIEW_SIZE:
            raise tool_error("out_of_range", f"max_size must be 1 to {MAX_PREVIEW_SIZE}")
        if region is not None and not region.inside_image():
            raise tool_error(
                "out_of_range",
                "region x, y, w, h are fractions of the image: x, y >= 0, w, h > 0, "
                "x + w <= 1 and y + h <= 1",
            )
        with locks.hold(path):
            wp = opened(path)
            # -f resizes before processing, which approximates sharpening and
            # local effects: only worth it for a whole-image preview that fits the
            # user's fast-export box (-f would shrink anything larger into it).
            fast = region is None and max_size <= artdir.fast_export_box(config_dir)
            profile = previews.new_file("profile", ".arp")
            crop = previews.new_file("crop", ".arp")
            resize = previews.new_file("resize", ".arp")
            output = previews.new_file("preview", ".jpg")
            try:
                profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
                if region is not None:
                    rect = region_rect(frame_of(wp), x=region.x, y=region.y, w=region.w, h=region.h)
                    crop.write_text(crop_profile(rect), encoding="utf-8")
                resize.write_text(resize_profile(max_size), encoding="utf-8")
                run(
                    preview_args(
                        wp.image, output, profile, resize, fast=fast,
                        crop=crop if region is not None else None,
                    ),
                    output,
                )  # fmt: skip
            except BaseException:
                output.unlink(missing_ok=True)
                raise
            finally:
                for temporary in (profile, crop, resize):
                    temporary.unlink(missing_ok=True)
        result = Preview(path=str(output), max_size=max_size)
        content: list[ContentBlock] = [TextContent(text=result.model_dump_json())]
        if inline if inline is not None else inline_previews:
            content.append(
                ImageContent(
                    data=base64.b64encode(output.read_bytes()).decode("ascii"),
                    mime_type="image/jpeg",
                )
            )
        # Returning the result object (rather than the model) is what lets a
        # tool carry content blocks next to its structured output.
        return CallToolResult(content=content, structured_content=result.model_dump(mode="json"))

    @server.tool()
    def get_profile(path: str) -> ProfileView:
        """The image's working profile: curated tools under `adjustments`,
        every other `[Group] Key` as a string under `raw`."""
        with locks.hold(path):
            return read_format(opened(path).changes.profile)

    @server.tool()
    def edit_profile(
        path: str,
        adjustments: AdjustmentsArg = None,
        raw_edits: list[RawEdit] | None = None,
    ) -> EditResult:
        """Change values of the working profile, with typed `adjustments` of
        curated tools (range-checked; see describe_adjustments) and/or
        `raw_edits`, each setting one `[Group] Key` (as shown by get_profile)
        to a string value; the group and key must already exist. All changes
        apply, or none do. An adjustment and a raw edit may not set the same
        key. Adjusting a disabled tool also enables it (listed under
        `implied`)."""
        with locks.hold(path):
            wp = opened(path)
            try:
                parsed = parse_adjustments(adjustments) if adjustments else None
                outcome = wp.changes.edit(parsed, raw_edits or [])
            except AdjustmentError as e:
                raise tool_error(e.code, str(e)) from e
            except UnknownKey as e:
                raise tool_error("unknown_key", str(e)) from e
            except EditConflict as e:
                raise tool_error("conflict", str(e)) from e
        return EditResult(
            changed=outcome.changed,
            implied=outcome.implied,
            warnings=version_warnings(ppversion_of(wp.changes.profile)),
        )

    @server.tool()
    def describe_adjustments() -> AdjustmentsDescription:
        """The curated adjustments `edit_profile` accepts: each tool's fields
        with type, range, unit and the `[Group] Key` it sets. Carries a
        warning if an open image's ART profile version is newer than the
        schema's."""
        description = schema_description()
        for wp in list(working.values()):
            for warning in version_warnings(ppversion_of(wp.changes.profile)):
                if warning not in description.warnings:
                    description.warnings.append(warning)
        return description

    @server.tool()
    def export_image(
        path: str,
        output: str,
        format: str,
        quality: int | None = None,
        bit_depth: str | None = None,
        write_profile: bool = False,
        overwrite: bool = False,
    ) -> ExportResult:
        """Render the working profile (saved or not) at full size to `output`.
        `quality` (1..100) is for jpeg; `bit_depth` is 8 for jpeg, 8|16 for
        png, 8|16|16f|32 for tiff (default: ART's). An existing `output` (or
        `.arp`) is refused with `exists` unless `overwrite`. With
        `write_profile`, the working profile is also saved as `<output>.arp`;
        otherwise no `.arp` is written. The folder of `output` must exist."""
        with locks.hold(path):
            wp = opened(path)
            dest = Path(output).resolve()
            dest_arp = Path(str(dest) + ".arp")
            profile = previews.new_file("profile", ".arp")
            temp = previews.new_file("export", EXPORT_SUFFIXES.get(format, ".out"))
            temp_arp = Path(str(temp) + ".arp")
            try:
                args = export_args(wp.image, temp, profile, format, quality, bit_depth, write_profile)
            except ValueError as e:
                raise tool_error("out_of_range", str(e)) from e
            if not dest.parent.is_dir():
                raise tool_error("not_found", f"folder {dest.parent} does not exist")
            targets = [dest, dest_arp] if write_profile else [dest]
            if not overwrite:
                for target in targets:
                    if target.exists():
                        raise tool_error("exists", f"{target} already exists; pass overwrite=true to replace it")
            try:
                profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
                run(args, temp, timeout=cli.export_timeout)
                if write_profile and not temp_arp.is_file():
                    raise no_profile_written()
                moves = [(temp, dest), (temp_arp, dest_arp)] if write_profile else [(temp, dest)]
                for source, target in moves:
                    move_over(source, target)
            finally:
                for leftover in (profile, temp, temp_arp):
                    leftover.unlink(missing_ok=True)
            return ExportResult(path=str(dest), profile_path=str(dest_arp) if write_profile else None)

    @server.tool()
    async def save_sidecar(
        path: str, ctx: Context, on_conflict: OnConflict | None = None
    ) -> SaveResult:
        """Write the working profile to the image's sidecar (the only tool
        that writes it); the previous sidecar is kept as `<sidecar>.bak`.

        If the sidecar changed on disk since it was loaded, the user is asked
        (when the client supports it) whether to `merge` the agent's changes
        onto the current sidecar, `overwrite` it, or `cancel`; otherwise a
        `conflict` error lists the changed keys and the agent should ask the
        user, then call again with `on_conflict`."""
        # Decide under the image lock, ask the user without it (the answer
        # can take minutes), then re-check and write under it again.
        with locks.hold(path):
            wp = opened(path)
            target = artdir.sidecar_path(wp.image, config_dir)
            current = sidecar.read(target)
            changed_on_disk = sidecar.hash_or_none(current) != wp.sidecar_hash
            if changed_on_disk:
                theirs = sidecar.changed_keys(wp.sidecar_keys, sidecar.parse(current))
                ours = sidecar.changed_keys({}, wp.changes.partial_profile())
        if changed_on_disk and on_conflict is None:
            on_conflict = await ask_user(ctx, target, theirs, ours)
            if on_conflict is None:
                raise tool_error(
                    "conflict",
                    "the sidecar changed since it was loaded. Changed in the sidecar: "
                    f"{', '.join(theirs) or '(nothing that parses)'}. Changed by the agent: "
                    f"{', '.join(ours) or '(nothing)'}. Ask the user, then call again with "
                    "on_conflict: merge (agent's changes onto the current sidecar), "
                    "overwrite, or cancel.",
                )
        if changed_on_disk and on_conflict == "cancel":
            return SaveResult(saved=False, path=str(target), how="cancelled")

        with locks.hold(path):
            if working.get(image_key(wp.image)) is not wp:
                raise tool_error(
                    "conflict", "the image was reopened or reset while saving; save again"
                )
            if sidecar.hash_or_none(sidecar.read(target)) != sidecar.hash_or_none(current):
                raise tool_error(
                    "conflict",
                    "the sidecar changed again while saving; call save_sidecar again",
                )
            # Read the working profile only now, so edits made while the user
            # was answering are saved too.
            profile = wp.changes.profile
            how: SaveHow = "written"
            if changed_on_disk and on_conflict == "merge" and current is not None:
                merged = sidecar.merge(sidecar.parse(current), wp.changes.partial_profile())
                # The working profile follows the file, so later saves and
                # renders include what the user changed there.
                profile = sidecar.merge(profile, merged)
                how = "merged"
                text = keyfile.dumps(merged)
            else:
                how = "overwritten" if changed_on_disk else "written"
                text = keyfile.dumps(profile)
            data = text.encode("utf-8")
            sidecar.write_with_backup(target, text)
            wp.changes = WorkingChanges(profile)
            wp.sidecar_hash = sidecar.file_hash(data)
            wp.sidecar_keys = sidecar.parse(data)
        return SaveResult(saved=True, path=str(target), how=how)

    @server.tool()
    def save_partial_profile(
        path: str, dest: str, overwrite: bool = False
    ) -> PartialProfileResult:
        """Write only the values the agent changed since the profile was
        loaded or last saved to `dest`, as a partial processing profile
        (.arp) that can be applied on top of other images. Refuses an
        existing `dest` unless `overwrite`. Nothing is written when nothing
        changed."""
        with locks.hold(path):
            partial = opened(path).changes.partial_profile()
            target = Path(dest).resolve()
            if not target.parent.is_dir():
                raise tool_error("not_found", f"folder {target.parent} does not exist")
            if target.exists() and not overwrite:
                raise tool_error("exists", f"{target} exists; pass overwrite=true to replace it")
            if not partial:
                return PartialProfileResult(written=False, path=str(target), keys=[])
            sidecar.write_atomic(target, keyfile.dumps(partial))
            return PartialProfileResult(
                written=True, path=str(target), keys=sidecar.changed_keys({}, partial)
            )

    @server.tool()
    def inspect_image(path: str, tags: list[str] | None = None) -> Metadata:
        """The image's metadata (read with ART's exiftool): make, model, lens,
        ISO, shutter, aperture, focal length, capture date, pixel dimensions
        and orientation, each None when the file has no value, plus any extra
        exiftool `tags` named (by tag name, e.g. "Software") that it has."""
        with locks.hold(path):
            image = opened(path).image
        if exiftool is None:
            raise tool_error("metadata_unavailable", "exiftool was not found beside ART-cli")
        try:
            return exiftool.read(image, tags or [])
        except InvalidTag as e:
            raise tool_error("invalid_tag", str(e)) from e
        except ExiftoolTimeout as e:
            raise tool_error("timeout", str(e)) from e
        except ExiftoolError as e:
            raise tool_error("metadata_failed", str(e)) from e

    return server


def main() -> None:
    parser = argparse.ArgumentParser(prog="art-mcp-render", description=__doc__)
    parser.add_argument("--art-dir", help="folder holding ART-cli (default: ART_DIR, PATH, newest install)")
    parser.add_argument(
        "--preview-timeout", type=float, default=60.0, metavar="SECONDS",
        help="kill art-cli and report `timeout` when a preview render takes longer (default 60)",
    )  # fmt: skip
    parser.add_argument(
        "--export-timeout", type=float, default=120.0, metavar="SECONDS",
        help="the same for exports (default 120)",
    )  # fmt: skip
    parser.add_argument(
        "--inline-previews",
        action="store_true",
        help="return preview images inline (base64) as well as by path; "
        "render_preview's `inline` argument overrides this per call",
    )
    args = parser.parse_args()

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ART"
    folder = artdir.find_art_dir(args.art_dir, os.environ, program_files)
    cli_path = artdir.find_cli(folder) if folder else None
    if cli_path is None:
        sys.exit("art-mcp-render: ART-cli not found; pass --art-dir or set ART_DIR")

    sweep_stale()
    exiftool_path = artdir.find_exiftool(folder) if folder else None
    server = build_server(
        ArtCli((str(cli_path),), timeout=args.preview_timeout, export_timeout=args.export_timeout),
        artdir.user_config_dir(os.environ),
        PreviewFolder(default_root()),
        exiftool=Exiftool((str(exiftool_path),)) if exiftool_path else None,
        inline_previews=args.inline_previews,
    )
    server.run()
