"""What the MCP tools add to an operation: errors as MCP tool errors."""

from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.mcpserver.exceptions import ToolError

from art_mcp.render.errors import RenderError


@contextmanager
def as_tool_errors() -> Iterator[None]:
    """Run an operation, turning its ``RenderError`` into the ``ToolError``
    whose text starts with the error code."""
    try:
        yield
    except RenderError as e:
        raise ToolError(str(e)) from e
