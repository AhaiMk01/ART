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

from art_mcp import artdir, keyfile
from art_mcp.live.channel import ArtNotRunning, ChannelError, ChannelTimeout, ControlChannel
from art_mcp.metadata import Exiftool, Metadata, MetadataProblem, read_metadata
from art_mcp.profile import ProfileView, read_format
from art_mcp.schema import AdjustmentsDescription
from art_mcp.schema import describe_adjustments as schema_description


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


class LiveProfile(ProfileView):
    history_position: int | None
    """The selected row of ART's History panel (0 = the oldest entry); null
    if no row is selected."""


class Status(BaseModel):
    art_version: str
    images: list[OpenImage]
    """The images open in ART's editor."""


def art_path(path: str) -> str:
    """How to name an image to ART: absolute, but with links, junctions and
    subst drives left as they are, since ART keeps the name it opened the
    file under (it compares case-insensitively on Windows itself)."""
    return os.path.abspath(path)


def same_image(a: str, b: str) -> bool:
    """Whether two paths name the same file, by the rule ART uses."""
    return os.path.normcase(art_path(a)) == os.path.normcase(art_path(b))


def build_server(channel: ControlChannel, *, exiftool: Exiftool | None = None) -> MCPServer:
    server = MCPServer(
        "art-live",
        instructions=(
            "Work with the images open in a running ART editor (started with "
            "--live-control). Call status to see which images are open."
        ),
    )

    def call(op: str, args: dict[str, str] | None = None) -> object:
        try:
            return channel.request(op, args)
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

    @server.tool()
    def get_profile(path: str) -> LiveProfile:
        """The processing profile of an image open in ART's editor, as the
        editor has it now: curated tools typed under `adjustments`, every
        other `[Group] Key` as a string under `raw`, plus the selected
        History row. Fails with not_open if ART doesn't have it open."""
        result = call("get_profile", {"path": art_path(path)})
        try:
            if not isinstance(result, dict):
                raise TypeError("not an object")
            view = read_format(keyfile.loads(result["profile"]))
            position = result["history_position"]
            if not isinstance(position, int):
                raise TypeError("history_position is not a number")
            return LiveProfile(**view.model_dump(), history_position=position if position >= 0 else None)
        except (KeyError, TypeError, ValueError) as e:
            raise tool_error("bad_reply", f"unexpected get_profile reply from ART: {result!r:.300}") from e

    @server.tool()
    def describe_adjustments() -> AdjustmentsDescription:
        """The curated adjustments: each tool's fields with type, range,
        unit and the `[Group] Key` it sets (the same schema as the Render
        server's)."""
        return schema_description()

    @server.tool()
    def inspect_image(path: str, tags: list[str] | None = None) -> Metadata:
        """The metadata of an image open in ART (read with ART's exiftool):
        make, model, lens, ISO, shutter, aperture, focal length, capture
        date, pixel dimensions and orientation, plus any extra exiftool
        `tags` named. Fails with not_open if ART doesn't have it open."""
        result = call("status")
        images = result.get("images", []) if isinstance(result, dict) else []
        if not any(isinstance(i, dict) and same_image(str(i.get("path", "")), path) for i in images):
            raise tool_error("not_open", f"{path} is not open in ART")
        try:
            return read_metadata(exiftool, Path(art_path(path)), tags or [])
        except MetadataProblem as e:
            raise tool_error(e.code, e.message) from e

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
    exiftool_path = artdir.find_exiftool(art_dir) if art_dir else None
    build_server(channel, exiftool=Exiftool((str(exiftool_path),)) if exiftool_path else None).run()
