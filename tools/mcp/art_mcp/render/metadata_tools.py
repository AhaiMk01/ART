"""Metadata tool: inspect_image (adapter over ``metadata_ops``)."""

from mcp.server.mcpserver import MCPServer

from art_mcp.metadata import Metadata
from art_mcp.render import metadata_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.session import RenderSession


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def inspect_image(path: str, tags: list[str] | None = None) -> Metadata:
        """The image's metadata (read with ART's exiftool): make, model, lens,
        ISO, shutter, aperture, focal length, capture date, the pixel
        dimensions the file records (`width`, `height`) and orientation, each
        None when the file has no value, plus any extra exiftool `tags` named
        (by tag name, e.g. "Software") that it has. `frame_width` and
        `frame_height` are the size ART works in (after coarse rotation and
        the raw border), the space `crop` and `sample_spots` coordinates are
        in: use them, not `width` and `height`, to size a crop. Measured with
        art-cli the first time (about a second), null if that fails."""
        with as_tool_errors():
            return ops.inspect_image(session, path, tags)
