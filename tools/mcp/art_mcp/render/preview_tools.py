"""Preview tool: render_preview (adapter over ``preview_ops``)."""

import base64
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent

from art_mcp.marks import Mark
from art_mcp.render import preview_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE, Preview, Region
from art_mcp.render.session import RenderSession

__all__ = ["MAX_PREVIEW_SIZE", "PREVIEW_SIZE", "Preview", "Region", "register"]


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def render_preview(
        path: str,
        max_size: int = PREVIEW_SIZE,
        region: Region | None = None,
        inline: bool | None = None,
        output: str | None = None,
        overwrite: bool = False,
        marks: list[Mark] | None = None,
    ) -> Annotated[CallToolResult, Preview]:
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
        `warnings` says which."""
        with as_tool_errors():
            result = ops.render_preview(session, path, max_size, region, output, overwrite, marks)
        content: list[ContentBlock] = [TextContent(text=result.model_dump_json(exclude_defaults=True))]
        if inline if inline is not None else session.inline_previews:
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
