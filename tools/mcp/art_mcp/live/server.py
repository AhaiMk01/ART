"""The Live server: read and change the images open in a running ART editor.

ART must have been started with ``--live-control``; the Live server never
launches ART.
"""

import argparse
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from art_mcp import artdir
from art_mcp.live.channel import ArtNotRunning, ChannelError, ChannelTimeout, ControlChannel


def tool_error(code: str, message: str) -> ToolError:
    """``code`` is art_not_running, timeout, bad_reply, or an error code ART
    itself returned."""
    return ToolError(f"{code}: {message}")


class OpenImage(BaseModel):
    path: str
    active: bool
    """The editor the user is looking at."""
    width: int | None
    height: int | None
    """The image's size as the editor processes it (before cropping); null
    until ART has computed its first preview."""


class Status(BaseModel):
    art_version: str
    images: list[OpenImage]
    """The images open in ART's editor."""


def build_server(channel: ControlChannel) -> MCPServer:
    server = MCPServer(
        "art-live",
        instructions=(
            "Work with the images open in a running ART editor (started with "
            "--live-control). Call status to see which images are open."
        ),
    )

    def call(op: str) -> object:
        try:
            return channel.request(op)
        except ArtNotRunning as e:
            raise tool_error("art_not_running", str(e)) from e
        except ChannelTimeout as e:
            raise tool_error("timeout", str(e)) from e
        except ChannelError as e:
            raise tool_error(e.code, e.message) from e

    @server.tool()
    def status() -> Status:
        """Whether a control-enabled ART is running, its version, and the
        images open in its editor (absolute paths and sizes). Fails with
        art_not_running when there is none."""
        result = call("status")
        try:
            if not isinstance(result, dict):
                raise TypeError("not an object")
            return Status.model_validate({"art_version": result["version"], "images": result["images"]})
        except (KeyError, TypeError, ValueError) as e:
            raise tool_error("bad_reply", f"unexpected status from ART: {result!r}") from e

    return server


def main() -> None:
    parser = argparse.ArgumentParser(prog="art-mcp-live", description=__doc__)
    parser.add_argument(
        "--timeout", type=float, default=30.0, metavar="SECONDS",
        help="how long to wait for ART to answer a request (default 30)",
    )  # fmt: skip
    parser.add_argument(
        "--art-dir",
        help="ART's install folder, only to find the settings of a portable "
        "(MultiUser=false) install (default: ART_DIR, PATH, newest install)",
    )
    args = parser.parse_args()
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ART"
    art_dir = artdir.find_art_dir(args.art_dir, os.environ, program_files)
    channel = ControlChannel(artdir.user_config_dir(os.environ, art_dir=art_dir), timeout=args.timeout)
    build_server(channel).run()
