"""Save tools: save_sidecar, save_partial_profile (adapters over
``save_ops``; asking the user about a conflict is the MCP tool's part)."""

from pathlib import Path
from typing import Annotated

import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import NoBackChannelError
from mcp.types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel, Field

from art_mcp.render import save_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.save_ops import OnConflict, PartialProfileResult, SaveResult
from art_mcp.render.session import RenderSession

# The enum lists the values in the schema; a wrong one still gets out_of_range.
Baseline = Annotated[str, Field(json_schema_extra={"enum": list(ops.PARTIAL_BASELINES)})]


class ConflictChoice(BaseModel):
    choice: OnConflict


async def ask_user(
    ctx: Context, target: Path, theirs: list[str], ours: list[str]
) -> OnConflict | None:
    """The user's choice about a changed sidecar, or None if the client
    can't ask. Declining or dismissing the question is `cancel`."""
    asks = ClientCapabilities(elicitation=ElicitationCapability())
    if not ctx.request_context.session.check_client_capability(asks):
        return None
    try:
        answer = await ctx.elicit(
            f"{target.name} differs from what the agent loaded "
            f"(changed there: {', '.join(theirs) or 'unknown'}). The agent changed: "
            f"{', '.join(ours) or 'nothing'}. Merge = keep the sidecar's values and "
            "apply only the agent's changes; overwrite = replace the sidecar with "
            "the agent's profile (a backup is kept).",
            ConflictChoice,
        )
    except NoBackChannelError:
        return None  # newer protocol versions: a tool can't ask mid-call
    return answer.data.choice if answer.action == "accept" else "cancel"


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    async def save_sidecar(
        path: str, ctx: Context, on_conflict: OnConflict | None = None
    ) -> SaveResult:
        """Write the working profile to the image's sidecar (the only tool
        that writes it); the previous sidecar is kept as `<sidecar>.bak`.

        If the sidecar changed on disk since it was loaded, the user is asked
        (when the client supports it) whether to `merge` the agent's changes
        onto the current sidecar, `overwrite` it, or `cancel`; otherwise a
        `conflict` error lists the changed keys and the agent should ask the
        user, then call again with `on_conflict`.

        Refuses with `open_in_editor` while a running ART (started with
        --live-control) has the image open: ART would overwrite the sidecar
        with its own profile. Use the Live server to edit and save it then."""
        with as_tool_errors():
            await anyio.to_thread.run_sync(ops.check_not_in_editor, session, path)
            # Decide under the image lock, ask the user without it (the answer
            # can take minutes), then re-check and write under it again.
            plan = await anyio.to_thread.run_sync(ops.prepare_save, session, path)
            if plan.changed_on_disk and on_conflict is None:
                on_conflict = await ask_user(ctx, plan.target, plan.theirs, plan.ours)
                if on_conflict is None:
                    raise ops.conflict_error(plan)
            return await anyio.to_thread.run_sync(ops.commit_save, session, path, plan, on_conflict)

    @server.tool()
    def save_partial_profile(
        path: str,
        dest: str,
        overwrite: bool = False,
        exclude: list[str] = [],  # noqa: B006 - never mutated; the schema shows default []
        vs: Baseline = "opened",
        verbose: bool = False,
    ) -> PartialProfileResult:
        """Write a partial processing profile (.arp) to `dest`, that can be
        applied on top of other images. Refuses an existing `dest` unless
        `overwrite`. Nothing is written when there is nothing to write.

        The result's `keys` says how many keys were written to each `[Group]`
        and `total` how many in all; with `verbose` `keys` is instead the list
        of every `[Group] Key` written (about 80 per Color Correction region,
        so it can be long: read the file, or get_profile, to see values).

        `vs` is what the saved keys are measured against; the result's `vs`
        says which was used.
        `"opened"` (default): only the values the agent changed since the
        profile was loaded or last saved; keys the profile came with (from the
        sidecar, or from open_image's `profile`) are NOT in the file.
        `"default"`: every value that differs from ART's default profile for
        this image, so the file describes the whole work whatever the image
        was opened from: use it for a preset saved from an image opened from
        another preset (the base settings come along). Keys equal to ART's
        default and `[Version]` are not written; the first call per opened
        image runs art-cli to get the default (`render_failed` or `timeout`
        if that fails). Any other value is `out_of_range`.

        `exclude`: `"Group"` or `"Group/Key"` entries left out of the file
        (an unknown group or key is `unknown_key`). Settings that belong to
        one image (e.g. `Crop`) are usually excluded from a preset meant for
        other images.

        Step-by-step workflows (film negatives, faded slides): see the
        skills in tools/mcp/skills."""
        with as_tool_errors():
            return ops.save_partial_profile(session, path, dest, overwrite, exclude, vs, verbose)
