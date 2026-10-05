"""Neutral finder tool: suggest_neutrals (adapter over ``neutrals_ops``)."""

from mcp.server.mcpserver import MCPServer

from art_mcp.neutrals import DEFAULT_COUNT, SUGGEST_NEUTRALS_DOC, NeutralCandidates
from art_mcp.render import neutrals_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.session import RenderSession
from art_mcp.sampling import DEFAULT_SIZE


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool(description=SUGGEST_NEUTRALS_DOC)
    def suggest_neutrals(
        path: str, count: int = DEFAULT_COUNT, size: int = DEFAULT_SIZE
    ) -> NeutralCandidates:
        with as_tool_errors():
            return ops.suggest_neutrals(session, path, count, size)
