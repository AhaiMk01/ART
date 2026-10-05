"""Preset tool: apply_preset (adapter over ``preset_ops``)."""

import anyio
import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer

from art_mcp.render import preset_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.preset_ops import PresetResult
from art_mcp.render.session import RenderSession


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    async def apply_preset(paths: list[str], profile: str, ctx: Context) -> PresetResult:
        """Lay a preset, an `.arp` file (partial or complete), over the
        working profile of each image in `paths` (open them first; one that
        isn't open is that image's error and the others still run). The
        file's keys win; every other value of the frame (crop, reference
        spot, rotation, what you set before) stays. ART loads the file, so
        its own rules for one apply (a file that turns a tool off can switch
        related values off too). A complete profile sets every key it has,
        the crop included: for a group's settings use a preset saved with
        save_partial_profile. Unlike open_image's `profile`, which starts the
        working profile over from the file, nothing is lost. The changes
        count as yours, like edit_profile's (save_sidecar and
        save_partial_profile see them). Per image: `keys_changed` and the
        `groups` they are in, or an `error`; the values themselves are not
        listed (get_profile reads them)."""

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> PresetResult:
            with as_tool_errors():
                return ops.apply_preset(session, paths, profile, on_progress=progress)

        return await anyio.to_thread.run_sync(run)
