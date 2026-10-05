"""Preview tool: render_preview (adapter over ``preview_ops``)."""

import base64
from pathlib import Path
from typing import Annotated

import anyio
import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent

from art_mcp.marks import Mark
from art_mcp.render import preview_ops as ops
from art_mcp.render.adapter import as_tool_errors, result_with_images
from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE, Preview, PreviewOutput, Region
from art_mcp.render.session import RenderSession

__all__ = ["MAX_PREVIEW_SIZE", "PREVIEW_SIZE", "Preview", "Region", "register"]


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    async def render_preview(
        ctx: Context,
        path: str | None = None,
        max_size: int = PREVIEW_SIZE,
        region: Region | None = None,
        inline: bool | None = None,
        output: str | None = None,
        overwrite: bool = False,
        marks: list[Mark] | None = None,
        paths: list[str] | None = None,
    ) -> Annotated[CallToolResult, PreviewOutput]:
        """Render the working profile as a JPEG (long edge `max_size` px, 1 to
        2576) and return its path. `region` {x, y, w, h}, as fractions of the
        image, renders just that area at 1:1 (shrunk only to fit `max_size`).
        The JPEG is a new file in the server's own temp folder
        (`art-mcp-<pid>`, removed when the server exits); `output` (an
        absolute path to a `.jpg`, its folder must exist) writes it there
        instead and returns that path: `exists` if the file is there, unless
        `overwrite`. `inline`: true also returns the image itself in the
        result, which you see without opening the file; false returns the
        path only. Default: the server's --inline-previews setting, which is
        off unless the server was started with that flag, so normally you get
        a path and must open the file to look. To look at several frames at
        once, `contact_sheet(record=false, thumb_size=...)` renders them into
        one image, so one file read instead of a preview and a read each.
        `marks` (up to 64) [{x, y, size?, label?}] draws a box on the preview
        at each FRAME-pixel position (the coordinates `sample_spots`,
        `suggest_neutrals` and `crop` use; `size`, default 32, is the square
        `sample_spots` reads), numbered 1..n in request order unless a `label`
        (at most 4 characters) is given: give it the spots you are about to
        sample, or `suggest_neutrals` candidates as they are, to see what each
        sits on. A mark outside the frame is `out_of_range`; one outside what
        the preview shows (the `region`, or the crop) is not drawn, and
        `warnings` says which.

        `paths` (1 to 16 images, instead of `path`) renders each one the same
        way (the same `max_size`, `region` and `inline`), two at a time with
        progress per image, and returns `{items, failed}`: per image, in
        request order, `{path, preview_path}` or `{path, error}` (`not_open`,
        a render failure) while the others still render; with `inline` each
        image that rendered also comes back as an image, in that order.
        `marks`, `output` and `overwrite` go with one `path` and are
        `out_of_range` with `paths`. For a look at many frames at once
        `contact_sheet(record=false)` is one image; `paths` is for the few
        frames that need a closer look."""
        show = inline if inline is not None else session.inline_previews
        if paths is not None or path is None:
            return await render_batch(ctx, path, paths, max_size, region, output, overwrite, marks, show)
        def render_one() -> Preview:
            with as_tool_errors():
                return ops.render_preview(session, path, max_size, region, output, overwrite, marks)

        result = await anyio.to_thread.run_sync(render_one)
        content: list[ContentBlock] = [TextContent(text=result.model_dump_json(exclude_defaults=True))]
        if show:
            content.append(
                ImageContent(
                    data=base64.b64encode(Path(result.path).read_bytes()).decode("ascii"),
                    mime_type="image/jpeg",
                )
            )
        # Returning the result object (rather than the model) is what lets a
        # tool carry content blocks next to its structured output.
        return CallToolResult(
            content=content, structured_content=result.model_dump(mode="json", exclude_defaults=True)
        )

    async def render_batch(
        ctx: Context,
        path: str | None,
        paths: list[str] | None,
        max_size: int,
        region: Region | None,
        output: str | None,
        overwrite: bool,
        marks: list[Mark] | None,
        show: bool,
    ) -> CallToolResult:
        """The ``paths`` form of render_preview (or the refusal of a call that
        gave neither or both)."""
        with as_tool_errors():
            ops.check_preview_call(path, paths, output, overwrite, marks)
        assert paths is not None  # check_preview_call: path is then None

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> ops.PreviewBatch:
            with as_tool_errors():
                return ops.render_previews(session, paths, max_size, region, on_progress=progress)

        batch = await anyio.to_thread.run_sync(run)
        rendered = [item.preview_path for item in batch.items if item.preview_path]
        return result_with_images(batch.model_dump(mode="json", exclude_none=True), rendered, show)
