"""What the MCP tools add to an operation: errors as MCP tool errors, an
image beside the structured result."""

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent

from art_mcp.render.errors import RenderError


@contextmanager
def as_tool_errors() -> Iterator[None]:
    """Run an operation, turning its ``RenderError`` into the ``ToolError``
    whose text starts with the error code."""
    try:
        yield
    except RenderError as e:
        raise ToolError(str(e)) from e


def result_with_images(data: dict[str, Any], images: list[str], inline: bool) -> CallToolResult:
    """A tool result: ``data`` as the structured content and, as compact JSON,
    the text; with ``inline`` (the server's ``--inline-previews``) also each
    JPEG of ``images`` as an image block, in order, for a client that cannot
    open the files."""
    content: list[ContentBlock] = [TextContent(text=json.dumps(data, separators=(",", ":")))]
    if inline:
        for image in images:
            content.append(
                ImageContent(
                    data=base64.b64encode(Path(image).read_bytes()).decode("ascii"), mime_type="image/jpeg"
                )
            )
    return CallToolResult(content=content, structured_content=data)


def result_with_image(data: dict[str, Any], image: str | None, inline: bool) -> CallToolResult:
    """``result_with_images`` for one image (None: there is none)."""
    return result_with_images(data, [image] if image else [], inline)
