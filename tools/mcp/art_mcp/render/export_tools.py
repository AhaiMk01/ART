"""Export tool: export_image (adapter over ``export_ops``)."""

from mcp.server.mcpserver import MCPServer

from art_mcp.render import export_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.export_ops import ExportResult
from art_mcp.render.session import RenderSession


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def export_image(
        path: str,
        output: str,
        format: str,
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
