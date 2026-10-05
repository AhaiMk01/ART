"""Metadata operation: inspect_image, and the summary open_image returns."""

from pydantic import BaseModel

from art_mcp.metadata import Metadata, MetadataProblem, read_metadata
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.session import RenderSession


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


def inspect_image(session: RenderSession, path: str, tags: list[str] | None = None) -> Metadata:
    with session.image(path) as wp:
        image = wp.image
        try:
            frame = session.whole_frame(wp)
        except RenderError:
            frame = None  # the metadata is still worth returning
    try:
        metadata = read_metadata(session.exiftool, image, tags or [])
    except MetadataProblem as e:
        raise render_error(e.code, e.message) from e  # type: ignore[arg-type]
    if frame is not None:
        metadata.frame_width, metadata.frame_height = frame.w, frame.h
    return metadata
