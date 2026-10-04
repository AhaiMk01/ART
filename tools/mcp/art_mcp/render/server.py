"""The Render server: open images and render previews headlessly via art-cli.

Edits live in a per-image *working profile* held in memory, seeded from the
image's sidecar (or ART's default profile) and never written back by renders.
"""

import argparse
import functools
import hashlib
import os
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
from art_mcp.keyfile import KeyFile
from art_mcp.preview import PreviewFolder, default_root
from art_mcp.render.artcli import (
    ArtCli,
    ArtCliError,
    ArtCliTimeout,
    preview_args,
    resize_profile,
    resolve_profile_args,
)

PREVIEW_SIZE = 1024

ErrorCode = Literal["not_open", "not_found", "render_failed", "timeout"]


@dataclass
class WorkingProfile:
    image: Path
    profile: KeyFile
    sidecar_hash: str | None
    """SHA-256 of the sidecar as loaded, or None if there was none."""


class OpenedImage(BaseModel):
    path: str
    profile_from: Literal["sidecar", "default"]
    art_version: str


class Preview(BaseModel):
    path: str
    """JPEG file; open it to look at the preview."""
    max_size: int


def image_key(image: Path) -> str:
    """Identity of a resolved image path across calls (case-folded on
    Windows)."""
    return os.path.normcase(str(image))


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

    @server.tool()
    def open_image(path: str) -> OpenedImage:
        """Open an image and load its processing profile (from its sidecar,
        else ART's default profile) as the working profile."""
        image = Path(path).resolve()
        if not image.is_file():
            raise tool_error("not_found", f"{image} does not exist")
        sidecar = artdir.sidecar_path(image, config_dir)
        sidecar_bytes = sidecar.read_bytes() if sidecar.is_file() else None
        has_sidecar = sidecar_bytes is not None

        output = previews.new_file("resolve", ".jpg")
        arp = Path(str(output) + ".arp")
        try:
            run(resolve_profile_args(image, output, sidecar if has_sidecar else None), output)
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

        working[image_key(image)] = WorkingProfile(
            image=image,
            profile=profile,
            sidecar_hash=(
                hashlib.sha256(sidecar_bytes).hexdigest() if sidecar_bytes is not None else None
            ),
        )
        return OpenedImage(
            path=str(image),
            profile_from="sidecar" if has_sidecar else "default",
            art_version=art_version(),
        )

    @server.tool()
    def render_preview(path: str) -> Preview:
        """Render the working profile as a JPEG (long edge 1024 px) and return
        its path."""
        wp = opened(path)
        profile = previews.new_file("profile", ".arp")
        resize = previews.new_file("resize", ".arp")
        output = previews.new_file("preview", ".jpg")
        try:
            profile.write_text(keyfile.dumps(wp.profile), encoding="utf-8")
            resize.write_text(resize_profile(PREVIEW_SIZE), encoding="utf-8")
            run(preview_args(wp.image, output, profile, resize), output)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        finally:
            profile.unlink(missing_ok=True)
            resize.unlink(missing_ok=True)
        return Preview(path=str(output), max_size=PREVIEW_SIZE)

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
