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
        ISO, shutter, aperture, focal length, capture date, pixel dimensions
        and orientation, each None when the file has no value, plus any extra
        exiftool `tags` named (by tag name, e.g. "Software") that it has."""
        with as_tool_errors():
            return ops.inspect_image(session, path, tags)
