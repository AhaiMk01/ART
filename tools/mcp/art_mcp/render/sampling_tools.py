"""Sampling tools: sample_spots and image_stats (adapters over
``sampling_ops``)."""

from mcp.server.mcpserver import MCPServer

from art_mcp.render import sampling_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.preview_ops import PREVIEW_SIZE
from art_mcp.render.session import RenderSession
from art_mcp.sampling import (
    DEFAULT_SIZE,
    IMAGE_STATS_DOC,
    SAMPLE_SPOTS_DOC,
    ImageStats,
    Spot,
    SpotSamples,
)


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool(description=SAMPLE_SPOTS_DOC)
    def sample_spots(
        path: str, spots: list[Spot], size: int = DEFAULT_SIZE, space: str = "working"
    ) -> SpotSamples:
        with as_tool_errors():
            return ops.sample_spots(session, path, spots, size, space)

    @server.tool(
        description=(
            "Statistics of the working profile as rendered: an 8-bit output image, crop "
            "applied (like a whole-image render_preview). "
            + IMAGE_STATS_DOC
            + " Downscaling hides clipping in tiny highlights: raise `max_size` to see more."
        )
    )
    def image_stats(
        path: str, max_size: int = PREVIEW_SIZE, histogram: bool = False
    ) -> ImageStats:
        with as_tool_errors():
            return ops.image_stats(session, path, max_size, histogram)
