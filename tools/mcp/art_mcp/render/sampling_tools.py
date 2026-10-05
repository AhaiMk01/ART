"""Sampling tools: sample_spots and image_stats (adapters over
``sampling_ops``)."""

from typing import Annotated

import anyio
import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult

from art_mcp.render import sampling_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.preview_ops import PREVIEW_SIZE, Region
from art_mcp.render.session import RenderSession
from art_mcp.sampling import (
    DEFAULT_SIZE,
    IMAGE_STATS_DOC,
    SAMPLE_SPOTS_DOC,
    Detail,
    ImageStatsResult,
    Spot,
    SpotSamples,
    stats_result,
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
            + " Downscaling hides clipping in tiny highlights: raise `max_size` to see more. "
            "Several images are rendered two at a time, with progress per image."
        )
    )
    async def image_stats(
        ctx: Context,
        path: str | None = None,
        paths: list[str] | None = None,
        max_size: int = PREVIEW_SIZE,
        histogram: bool = False,
        detail: Detail | None = None,
        region: Region | None = None,
        bins: int | None = None,
    ) -> Annotated[CallToolResult, ImageStatsResult]:
        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> CallToolResult:
            with as_tool_errors():
                return stats_result(
                    ops.image_stats(session, path, paths, max_size, histogram, region, bins, detail, progress)
                )

        return await anyio.to_thread.run_sync(run)
