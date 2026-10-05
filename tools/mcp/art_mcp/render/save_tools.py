"""Save tools: save_sidecar, save_partial_profile."""

from pathlib import Path
from typing import Literal

import anyio.to_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import NoBackChannelError
from mcp.types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel

from art_mcp import artdir, keyfile, sidecar
from art_mcp.concurrency import image_key
from art_mcp.live.channel import ArtNotRunning, ChannelError, ChannelTimeout, ControlChannel
from art_mcp.profile import WorkingChanges
from art_mcp.render.session import RenderSession, tool_error

OnConflict = Literal["merge", "overwrite", "cancel"]
SaveHow = Literal["written", "merged", "overwritten", "cancelled"]


class ConflictChoice(BaseModel):
    choice: OnConflict


class SaveResult(BaseModel):
    saved: bool
    path: str
    """The sidecar file."""
    how: SaveHow
    """`written` (nothing had changed there), `merged`, `overwritten` or
    `cancelled` (nothing saved)."""


class PartialProfileResult(BaseModel):
    written: bool
    """False when the agent has changed nothing: no file is written."""
    path: str
    keys: list[str]
    """The `[Group] Key` entries written."""


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
            f"{target.name} was changed since the agent loaded it "
            f"(changed there: {', '.join(theirs) or 'unknown'}). The agent changed: "
            f"{', '.join(ours) or 'nothing'}. Merge = keep the sidecar's values and "
            "apply only the agent's changes; overwrite = replace the sidecar with "
            "the agent's profile (a backup is kept).",
            ConflictChoice,
        )
    except NoBackChannelError:
        return None  # newer protocol versions: a tool can't ask mid-call
    return answer.data.choice if answer.action == "accept" else "cancel"


GUARD_TIMEOUT = 5.0
"""How long save_sidecar waits for a running ART to say what it has open."""


def open_in_art(image: Path, config_dir: Path) -> bool:
    """Whether a control-enabled ART reports ``image`` open in its editor.
    False when none runs or it doesn't answer: then it can't be told."""
    try:
        status = ControlChannel(config_dir, timeout=GUARD_TIMEOUT).request("status")
    except (ArtNotRunning, ChannelTimeout, ChannelError):
        return False
    images = status.get("images") if isinstance(status, dict) else None
    if not isinstance(images, list):
        return False
    key = image_key(image)
    return any(
        isinstance(i, dict) and isinstance(i.get("path"), str) and image_key(Path(i["path"]).resolve()) == key
        for i in images
    )


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
        with session.image(path) as wp:
            image = wp.image
        if await anyio.to_thread.run_sync(open_in_art, image, session.config_dir):
            raise tool_error(
                "open_in_editor",
                f"{image} is open in ART's editor, which doesn't reload sidecars and "
                "would overwrite this one when it saves; edit and save it with the "
                "Live server (art-live: edit_profile, save_sidecar), or close it in "
                "ART first",
            )
        # Decide under the image lock, ask the user without it (the answer
        # can take minutes), then re-check and write under it again.
        with session.image(path) as wp:
            target = artdir.sidecar_path(wp.image, session.config_dir)
            current = sidecar.read(target)
            changed_on_disk = sidecar.hash_or_none(current) != wp.sidecar_hash
            if changed_on_disk:
                theirs = sidecar.changed_keys(wp.sidecar_keys, sidecar.parse(current))
                ours = sidecar.changed_keys({}, wp.changes.partial_profile())
        if changed_on_disk and on_conflict is None:
            on_conflict = await ask_user(ctx, target, theirs, ours)
            if on_conflict is None:
                raise tool_error(
                    "conflict",
                    "the sidecar changed since it was loaded. Changed in the sidecar: "
                    f"{', '.join(theirs) or '(nothing that parses)'}. Changed by the agent: "
                    f"{', '.join(ours) or '(nothing)'}. Ask the user, then call again with "
                    "on_conflict: merge (agent's changes onto the current sidecar), "
                    "overwrite, or cancel.",
                )
        if changed_on_disk and on_conflict == "cancel":
            return SaveResult(saved=False, path=str(target), how="cancelled")

        with session.image(path) as now:
            if now is not wp:
                raise tool_error(
                    "conflict", "the image was reopened or reset while saving; save again"
                )
            if sidecar.hash_or_none(sidecar.read(target)) != sidecar.hash_or_none(current):
                raise tool_error(
                    "conflict",
                    "the sidecar changed again while saving; call save_sidecar again",
                )
            # Read the working profile only now, so edits made while the user
            # was answering are saved too.
            profile = wp.changes.profile
            how: SaveHow = "written"
            if changed_on_disk and on_conflict == "merge" and current is not None:
                merged = sidecar.merge(sidecar.parse(current), wp.changes.partial_profile())
                # The working profile follows the file, so later saves and
                # renders include what the user changed there.
                profile = sidecar.merge(profile, merged)
                how = "merged"
                text = keyfile.dumps(merged)
            else:
                how = "overwritten" if changed_on_disk else "written"
                text = keyfile.dumps(profile)
            data = text.encode("utf-8")
            sidecar.write_with_backup(target, text)
            wp.changes = WorkingChanges(profile)
            wp.sidecar_hash = sidecar.file_hash(data)
            wp.sidecar_keys = sidecar.parse(data)
        return SaveResult(saved=True, path=str(target), how=how)

    @server.tool()
    def save_partial_profile(
        path: str, dest: str, overwrite: bool = False, exclude: list[str] = []
    ) -> PartialProfileResult:
        """Write only the values the agent changed since the profile was
        loaded or last saved to `dest`, as a partial processing profile
        (.arp) that can be applied on top of other images. Refuses an
        existing `dest` unless `overwrite`. Nothing is written when nothing
        changed.

        `exclude`: `"Group"` or `"Group/Key"` entries left out of the file
        (an unknown group or key is `unknown_key`). For a roll preset exclude
        the per-frame settings: `Coarse Transformation`, `Crop`,
        `Film Negative/RefInput` (and `Film Negative/RefOutput` if set per
        frame)."""
        with session.image(path) as wp:
            profile = wp.changes.profile
            for entry in exclude:
                group, _, key = entry.partition("/")
                if group not in profile or (key and key not in profile[group]):
                    raise tool_error(
                        "unknown_key",
                        f"exclude {entry!r}: not in this image's processing profile",
                    )
            partial = wp.changes.partial_profile()
            for entry in exclude:
                group, _, key = entry.partition("/")
                if key:
                    partial.get(group, {}).pop(key, None)
                else:
                    partial.pop(group, None)
            partial = {g: k for g, k in partial.items() if k}
            target = Path(dest).resolve()
            if not target.parent.is_dir():
                raise tool_error("not_found", f"folder {target.parent} does not exist")
            if target.exists() and not overwrite:
                raise tool_error("exists", f"{target} exists; pass overwrite=true to replace it")
            if not partial:
                return PartialProfileResult(written=False, path=str(target), keys=[])
            sidecar.write_atomic(target, keyfile.dumps(partial))
            return PartialProfileResult(
                written=True, path=str(target), keys=sidecar.changed_keys({}, partial)
            )
