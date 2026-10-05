"""Neutral finder tool: suggest_neutrals (adapter over ``neutrals_ops``)."""

import base64
import json
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent

from art_mcp.neutrals import DEFAULT_COUNT, SUGGEST_NEUTRALS_DOC, NeutralCandidates
from art_mcp.render import neutrals_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.session import RenderSession
from art_mcp.sampling import DEFAULT_SIZE


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool(description=SUGGEST_NEUTRALS_DOC)
    def suggest_neutrals(
        path: str, count: int = DEFAULT_COUNT, size: int = DEFAULT_SIZE, preview: bool = False
    ) -> Annotated[CallToolResult, NeutralCandidates]:
        with as_tool_errors():
            result = ops.suggest_neutrals(session, path, count, size, preview)
        # Without `preview` the result is what it was: no preview_path, not even a null.
        data = result.model_dump(mode="json", exclude_none=True)
        content: list[ContentBlock] = [TextContent(text=json.dumps(data, separators=(",", ":")))]
        if result.preview_path and session.inline_previews:
            content.append(
                ImageContent(
                    data=base64.b64encode(Path(result.preview_path).read_bytes()).decode("ascii"),
                    mime_type="image/jpeg",
                )
            )
        return CallToolResult(content=content, structured_content=data)
