"""The Render server: open images and render previews headlessly via art-cli.

Edits live in a per-image *working profile* held in memory, seeded from the
image's sidecar (or ART's default profile) and never written back by renders.
"""

import argparse
import functools
import hashlib
import os
import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from art_mcp import artdir, keyfile
from art_mcp.preview import PreviewFolder, default_root
from art_mcp.profile import ProfileView, RawEdit, UnknownKey, WorkingChanges, read_format
from art_mcp.render.artcli import (
    ArtCli,
    ArtCliError,
    ArtCliTimeout,
    export_args,
    preview_args,
    resize_profile,
    resolve_profile_args,
)

PREVIEW_SIZE = 1024

ErrorCode = Literal[
    "not_open", "not_found", "unknown_key", "render_failed", "timeout", "exists", "out_of_range"
]

EXPORT_SUFFIXES = {"jpeg": ".jpg", "tiff": ".tif", "png": ".png"}


ProfileSource = Literal["sidecar", "default"]


@dataclass
class WorkingProfile:
    image: Path
    changes: WorkingChanges
    sidecar_hash: str | None
    """SHA-256 of the sidecar on disk when this working profile was loaded
    (whichever source it was loaded from), or None if there was none: the
    baseline for detecting that someone else changed the sidecar."""


class OpenedImage(BaseModel):
    path: str
    profile_from: ProfileSource
    art_version: str


class ResetResult(BaseModel):
    profile_from: ProfileSource


class EditResult(BaseModel):
    changed: list[RawEdit]
    """Each [Group] Key whose value this call changed, with its new value
    (re-setting a value is not a change)."""


class ExportResult(BaseModel):
    path: str
    """The exported image."""
    profile_path: str | None
    """The `.arp` written beside it, when `write_profile` was set."""


class Preview(BaseModel):
    path: str
    """JPEG file; open it to look at the preview."""
    max_size: int


def image_key(image: Path) -> str:
    """Identity of a resolved image path across calls (case-folded on
    Windows)."""
    return os.path.normcase(str(image))


def move_over(source: Path, target: Path) -> None:
    """Move ``source`` to ``target``, replacing it; works across drives."""
    try:
        os.replace(source, target)
    except OSError:
        shutil.copyfile(source, target)  # temp folder on another drive
        source.unlink()


def tool_error(code: ErrorCode, message: str) -> ToolError:
    return ToolError(f"{code}: {message}")


def build_server(cli: ArtCli, config_dir: Path, previews: PreviewFolder) -> MCPServer:
    working: dict[str, WorkingProfile] = {}

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

    def run(args: list[str], output: Path) -> None:
        try:
            cli.run(args)
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
        sidecar = artdir.sidecar_path(image, config_dir)
        sidecar_bytes = sidecar.read_bytes() if sidecar.is_file() else None
        if source == "sidecar" and sidecar_bytes is None:
            raise tool_error("not_found", f"{image.name} has no sidecar ({sidecar})")
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
                raise tool_error(
                    "render_failed",
                    "art-cli wrote no profile beside its output; turn off "
                    '"Embed processing parameters in metadata" in ART\'s preferences',
                )
            profile = keyfile.loads(arp.read_text(encoding="utf-8"))
        finally:
            output.unlink(missing_ok=True)
            arp.unlink(missing_ok=True)
            sidecar_copy.unlink(missing_ok=True)

        working[image_key(image)] = WorkingProfile(
            image=image,
            changes=WorkingChanges(profile),
            sidecar_hash=(
                hashlib.sha256(sidecar_bytes).hexdigest() if sidecar_bytes is not None else None
            ),
        )
        return source

    @server.tool()
    def open_image(path: str) -> OpenedImage:
        """Open an image and load its processing profile (from its sidecar,
        else ART's default profile) as the working profile."""
        image = Path(path).resolve()
        if not image.is_file():
            raise tool_error("not_found", f"{image} does not exist")
        source = load_working_profile(image, None)
        return OpenedImage(path=str(image), profile_from=source, art_version=art_version())

    @server.tool()
    def reset_profile(path: str, to: ProfileSource) -> ResetResult:
        """Discard working-profile changes: reload the profile from the
        image's sidecar, or from ART's default profile."""
        return ResetResult(profile_from=load_working_profile(opened(path).image, to))

    @server.tool()
    def render_preview(path: str) -> Preview:
        """Render the working profile as a JPEG (long edge 1024 px) and return
        its path."""
        wp = opened(path)
        profile = previews.new_file("profile", ".arp")
        resize = previews.new_file("resize", ".arp")
        output = previews.new_file("preview", ".jpg")
        try:
            profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
            resize.write_text(resize_profile(PREVIEW_SIZE), encoding="utf-8")
            run(preview_args(wp.image, output, profile, resize), output)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        finally:
            profile.unlink(missing_ok=True)
            resize.unlink(missing_ok=True)
        return Preview(path=str(output), max_size=PREVIEW_SIZE)

    @server.tool()
    def get_profile(path: str) -> ProfileView:
        """The image's working profile: curated tools under `adjustments`,
        every other `[Group] Key` as a string under `raw`."""
        return read_format(opened(path).changes.profile)

    @server.tool()
    def edit_profile(path: str, raw_edits: list[RawEdit] | None = None) -> EditResult:
        """Change values of the working profile. Each raw edit sets one
        `[Group] Key` (as shown by get_profile) to a string value; the group
        and key must already exist. All edits apply, or none do."""
        wp = opened(path)
        try:
            changed = wp.changes.apply(raw_edits or [])
        except UnknownKey as e:
            raise tool_error("unknown_key", str(e)) from e
        return EditResult(changed=changed)

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
            run(args, temp)
            if write_profile and not temp_arp.is_file():
                raise tool_error(
                    "render_failed",
                    "art-cli wrote no profile beside its output; turn off "
                    '"Embed processing parameters in metadata" in ART\'s preferences',
                )
            moves = [(temp, dest), (temp_arp, dest_arp)] if write_profile else [(temp, dest)]
            for source, target in moves:
                move_over(source, target)
        finally:
            for leftover in (profile, temp, temp_arp):
                leftover.unlink(missing_ok=True)
        return ExportResult(path=str(dest), profile_path=str(dest_arp) if write_profile else None)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(prog="art-mcp-render", description=__doc__)
    parser.add_argument("--art-dir", help="folder holding ART-cli (default: ART_DIR, PATH, newest install)")
    args = parser.parse_args()

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ART"
    folder = artdir.find_art_dir(args.art_dir, os.environ, program_files)
    cli_path = artdir.find_cli(folder) if folder else None
    if cli_path is None:
        sys.exit("art-mcp-render: ART-cli not found; pass --art-dir or set ART_DIR")

    server = build_server(
        ArtCli((str(cli_path),)),
        artdir.user_config_dir(os.environ),
        PreviewFolder(default_root()),
    )
    server.run()
