"""Preview tool: render_preview (adapter over ``preview_ops``)."""

import base64
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent

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
    ) -> Annotated[CallToolResult, Preview]:
        """Render the working profile as a JPEG (long edge `max_size` px, 1 to
        2576) and return its path. `region` {x, y, w, h}, as fractions of the
        image, renders just that area at 1:1 (shrunk only to fit `max_size`).
        `inline` also returns the image itself (default: the server's
        --inline-previews setting)."""
        with as_tool_errors():
            result = ops.render_preview(session, path, max_size, region)
        content: list[ContentBlock] = [TextContent(text=result.model_dump_json())]
        if inline if inline is not None else session.inline_previews:
            content.append(
                ImageContent(
                    data=base64.b64encode(Path(result.path).read_bytes()).decode("ascii"),
                    mime_type="image/jpeg",
                )
            )
        # Returning the result object (rather than the model) is what lets a
        # tool carry content blocks next to its structured output.
        return CallToolResult(content=content, structured_content=result.model_dump(mode="json"))
