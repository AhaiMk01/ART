"""Export tools: export_image, export_batch (adapters over ``export_ops``)."""

from typing import Annotated

import anyio
import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from art_mcp.render import export_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.export_ops import BatchItem, BatchResult, ExportResult
from art_mcp.render.session import RenderSession

# The enum lists the values in the schema; a wrong one still gets out_of_range.
Format = Annotated[str, Field(json_schema_extra={"enum": ["jpeg", "tiff", "png"]})]


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def export_image(
        path: str,
        output: str,
        format: Format,
        quality: int | None = None,
        bit_depth: int | str | None = None,
        write_profile: bool = False,
        overwrite: bool = False,
    ) -> ExportResult:
        """Render the working profile (saved or not) at full size to `output`.
        `quality` (1..100) is for jpeg; `bit_depth` is 8 for jpeg, 8|16 for
        png, 8|16|"16f"|32 for tiff (default: ART's). An existing `output` (or
        `.arp`) is refused with `exists` unless `overwrite`. With
        `write_profile`, the working profile is also saved as `<output>.arp`;
        otherwise no `.arp` is written. The folder of `output` must exist."""
        with as_tool_errors():
            return ops.export_image(
                session, path, output, format, quality, bit_depth, write_profile, overwrite
            )

    @server.tool()
    async def export_batch(
        items: list[BatchItem],
        folder: str,
        format: Format,
        ctx: Context,
        quality: int | None = None,
        bit_depth: int | str | None = None,
        name: str = "{stem}",
        write_profile: bool = False,
        overwrite: bool = False,
    ) -> BatchResult:
        """Export many images at full size into `folder` (it must exist), as
        `<name><suffix>` with `{stem}` = the image's file name without
        extension. Each item exports its working profile (open it first), or
        with `profiles` the given `.arp` files layered over ART's default
        profile (e.g. a roll preset then the frame's partial profile; no need
        to open it). Format, `quality`, `bit_depth`, `write_profile` and
        `overwrite` as in export_image. One failing item (not open, `exists`,
        a render error) is reported in its result and the others still run;
        names that collide fail the whole call before anything renders.
        Working profiles are copied when the call starts. Progress is
        reported per finished image."""

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> BatchResult:
            with as_tool_errors():
                return ops.export_batch(
                    session, items, folder, format, quality, bit_depth, name,
                    write_profile, overwrite, on_progress=progress,
                )  # fmt: skip

        return await anyio.to_thread.run_sync(run)
