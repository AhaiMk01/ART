"""Contact-sheet tools: contact_sheet, compare_passes (adapters over ``sheet_ops``)."""

import anyio
import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer

from art_mcp.render import sheet_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.session import RenderSession
from art_mcp.render.sheet_ops import Comparison, SheetResult


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    async def contact_sheet(
        images: list[str],
        ctx: Context,
        folder: str | None = None,
        label: str | None = None,
        columns: int | None = None,
        thumb_size: int = ops.DEFAULT_THUMB_SIZE,
    ) -> SheetResult:
        """Render the open `images` (paths, or a folder standing for the open
        images in it) from their working profiles as thumbnails (long edge
        `thumb_size` px, 32 to 1024), compose them into a grid with the file
        name under each frame (`columns` per row, default 6) and save it as
        the next numbered pass, `<folder>/sheets/pass-NN[-label].jpg`, with
        `pass-NN[-label].json` beside it: the images, the label, the time and
        per image the profile keys that changed since the last pass it was in
        (`changes`; null the first time). Earlier passes are never
        overwritten. `folder` (it must exist) is the roll's output folder, not
        the source images' (default: the folder of the last export_batch). Open
        the returned `path` to look at the sheet. One failing image
        (`not_open`, a render error) is reported in its entry and shown as a
        placeholder; the others still render. Working profiles are copied when
        the call starts. Progress is reported per finished image."""

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> SheetResult:
            with as_tool_errors():
                return ops.contact_sheet(session, images, folder, label, columns, thumb_size, on_progress=progress)

        return await anyio.to_thread.run_sync(run)

    @server.tool()
    def compare_passes(
        first: int,
        second: int,
        folder: str | None = None,
        images: list[str] | None = None,
        columns: int = ops.DEFAULT_PAIR_COLUMNS,
    ) -> Comparison:
        """Put the same frames of two contact-sheet passes side by side
        (pass `first` left, `second` right; `columns` pairs per row, default
        2) and save that as `compare-NN-MM.jpg` in the sheets folder, next to
        the passes; nothing is overwritten (a repeat gets `-2`, `-3`).
        `images`: paths or file names of the frames to show (default: every
        frame rendered in both passes). `folder` as in contact_sheet. Open the
        returned `path` to look at it."""
        with as_tool_errors():
            return ops.compare_passes(session, first, second, folder, images, columns)
