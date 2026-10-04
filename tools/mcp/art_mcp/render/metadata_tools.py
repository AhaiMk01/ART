"""Metadata tools: inspect_image, and the summary open_image returns."""

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from art_mcp.metadata import Metadata, MetadataProblem, read_metadata
from art_mcp.render.session import RenderSession, tool_error


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


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def inspect_image(path: str, tags: list[str] | None = None) -> Metadata:
        """The image's metadata (read with ART's exiftool): make, model, lens,
        ISO, shutter, aperture, focal length, capture date, pixel dimensions
        and orientation, each None when the file has no value, plus any extra
        exiftool `tags` named (by tag name, e.g. "Software") that it has."""
        with session.image(path) as wp:
            image = wp.image
        try:
            return read_metadata(session.exiftool, image, tags or [])
        except MetadataProblem as e:
            raise tool_error(e.code, e.message) from e  # type: ignore[arg-type]
