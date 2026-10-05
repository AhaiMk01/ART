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
        record: bool = True,
    ) -> SheetResult:
        """To just look at several frames pass `record=false`: one image to
        read instead of a preview and a read per frame (details at the end).
        Without it the call renders the open `images` (paths, or a folder
        standing for the open images in it) from their working profiles as
        thumbnails (long edge `thumb_size` px, 32 to 1024), composes them into
        a grid with the file name under each frame (`columns` per row, default
        6) and saves it as
        the next numbered pass, `<folder>/sheets/pass-NN[-label].jpg`, with
        `pass-NN[-label].json` beside it: the images, the label, the time and
        per image `changes`, every profile value that differs from the last
        pass it was in (numbers shown with at most 7 significant digits; a
        number that is the same 32-bit float as before, `6450.7` and
        `6450.7001953125`, or a list with or without its final `;`, is no
        change; null the first time). The result does not
        repeat those lists: per image `changed` (how many values differ; null
        the first time) and `changes`, what changed since the last pass
        grouped by identical change, `{group, key, before, after, images}`
        with the file names of the frames it was made on, the most shared
        first (at most 25, `more` counts the rest and the JSON has every
        change per frame; `changes` is null when no image had an earlier
        pass, as in the first). Earlier passes are never
        overwritten. `folder` is where the `sheets` subfolder is created: any
        existing folder you choose, for example your work folder. Do not use
        the exports folder, the passes would mix with the exports. Without
        `folder` the call is `out_of_range`, unless an earlier contact_sheet
        call in this session used one: that is then the default. Open
        the returned `path` to look at the sheet. One failing image
        (`not_open`, a render error) is reported in its entry and shown as a
        placeholder; the others still render. Working profiles are copied when
        the call starts. Progress is reported per finished image.

        `record=false` makes the same sheet (same thumbnails, grid and labels;
        `label` goes in its title) as a quick look and saves nothing as a
        pass: no number, JSON or bookkeeping, no comparison with earlier passes
        (`index`, `json_path` and `changes` are null), and `folder` is not
        used. The JPEG is a new file in the server's own temp folder
        (`art-mcp-<pid>`, removed when the server exits), like render_preview's.
        `columns` then defaults to a grid about as wide as high (2 for 2 to 4
        frames, 3 for 5 to 9, as far as the width stays within the 2576 px
        Claude shows), so 2 to 6 frames at `thumb_size` 700 to 1000 are one
        readable image; set `thumb_size` large to judge colour and detail."""

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> SheetResult:
            with as_tool_errors():
                return ops.contact_sheet(
                    session, images, folder, label, columns, thumb_size, on_progress=progress, record=record
                )

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
        frame rendered in both passes). `folder` is the folder that holds the
        `sheets` subfolder, the one given to contact_sheet (not `sheets`
        itself); default: the folder the last contact_sheet call in this
        session used, else `out_of_range`. Open the returned `path` to look
        at it."""
        with as_tool_errors():
            return ops.compare_passes(session, first, second, folder, images, columns)
