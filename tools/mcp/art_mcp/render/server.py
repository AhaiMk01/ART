"""The Render server: open images and render previews headlessly via art-cli.

Edits live in a per-image *working profile* held in memory, seeded from the
image's sidecar (or ART's default profile) and never written back by renders.

This module only wires things up: ``RenderSession`` (session.py) holds the
state and the shared operations, and each feature module registers its tools
against it.
"""

import argparse
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from art_mcp import artdir
from art_mcp.metadata import Exiftool
from art_mcp.preview import PreviewFolder, default_root, sweep_stale
from art_mcp.render import (
    export_tools,
    metadata_tools,
    neutrals_tools,
    preset_tools,
    preview_tools,
    profile_tools,
    sampling_tools,
    save_tools,
    sheet_tools,
)
from art_mcp.render.artcli import ArtCli
from art_mcp.render.session import RenderSession


def build_server(
    cli: ArtCli,
    config_dir: Path,
    previews: PreviewFolder,
    *,
    exiftool: Exiftool | None = None,
    inline_previews: bool = False,
) -> MCPServer:
    session = RenderSession(cli, config_dir, previews, exiftool, inline_previews)

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
            "first; render_preview returns a JPEG path to open and look at. To look at several "
            "frames at once, contact_sheet(record=false) renders them into one image."
        ),
        lifespan=lifespan,
    )
    for feature in (
        profile_tools, preset_tools, preview_tools, export_tools, save_tools, metadata_tools, sampling_tools,
        neutrals_tools, sheet_tools,
    ):
        feature.register(server, session)
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

    program_files = artdir.windows_install_root(os.environ)
    folder = artdir.find_art_dir(args.art_dir, os.environ, program_files)
    cli_path = artdir.find_cli(folder) if folder else None
    if cli_path is None:
        sys.exit("art-mcp-render: ART-cli not found; pass --art-dir or set ART_DIR")

    sweep_stale()
    exiftool_path = artdir.locate_exiftool(folder, os.environ, program_files)
    server = build_server(
        ArtCli((str(cli_path),), timeout=args.preview_timeout, export_timeout=args.export_timeout),
        artdir.user_config_dir(os.environ, art_dir=folder),
        PreviewFolder(default_root()),
        exiftool=Exiftool((str(exiftool_path),)) if exiftool_path else None,
        inline_previews=args.inline_previews,
    )
    server.run()
