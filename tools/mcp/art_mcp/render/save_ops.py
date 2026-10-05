"""Save operations: save_sidecar, save_partial_profile.

``save_sidecar`` is split into steps so a front end that can ask the user
about a conflict (the MCP tool, by elicitation) can do so between them,
without the image's lock held: ``check_not_in_editor``, ``prepare_save``,
``conflict_error`` / ``commit_save``. A front end that can't ask (the CLI)
calls ``save_sidecar``, which does all of it and fails with ``conflict``
unless ``on_conflict`` is given.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from art_mcp import artdir, keyfile, sidecar
from art_mcp.concurrency import image_key
from art_mcp.live.channel import ArtNotRunning, ChannelError, ChannelTimeout, ControlChannel
from art_mcp.profile import WorkingChanges, partial_vs_default
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.session import RenderSession

OnConflict = Literal["merge", "overwrite", "cancel"]
SaveHow = Literal["written", "merged", "overwritten", "cancelled"]


class SaveResult(BaseModel):
    saved: bool
    path: str
    """The sidecar file."""
    how: SaveHow
    """`written` (nothing had changed there), `merged`, `overwritten` or
    `cancelled` (nothing saved)."""


PartialBaseline = Literal["opened", "default"]
PARTIAL_BASELINES = ("opened", "default")
"""What ``save_partial_profile`` measures the saved keys against: the profile
as loaded (or last saved), or ART's default profile for the image."""


class PartialProfileResult(BaseModel):
    written: bool
    """False when there is nothing to write (no file then): the agent has
    changed nothing since the profile was loaded or last saved, or with `vs`
    `default` nothing differs from ART's default profile."""
    path: str
    keys: list[str]
    """The `[Group] Key` entries written: the values that differ from the
    `vs` baseline (and weren't excluded), in the working profile's order. A
    Color Correction region key brings every region key along."""
    vs: PartialBaseline
    """The baseline the keys were measured against: `opened` (the values the
    agent changed since the profile was loaded or last saved) or `default`
    (ART's default profile for the image)."""


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


@dataclass
class SavePlan:
    """What ``prepare_save`` found: enough to decide, and later to write
    only if nothing moved meanwhile."""

    token: str
    """The working profile's load (``WorkingProfile.token``) that was checked."""
    target: Path
    current: bytes | None
    """The sidecar's bytes when checked."""
    changed_on_disk: bool
    theirs: list[str]
    """Keys changed in the sidecar since it was loaded (when it changed)."""
    ours: list[str]
    """Keys the agent changed (when the sidecar changed)."""


def check_not_in_editor(session: RenderSession, path: str) -> None:
    """``open_in_editor`` while a running ART has the image open (it would
    overwrite the sidecar with its own profile); ``not_open`` if the image
    isn't open here. Talks to ART, so it may take a few seconds."""
    with session.image(path) as wp:
        image = wp.image
    if open_in_art(image, session.config_dir):
        raise render_error(
            "open_in_editor",
            f"{image} is open in ART's editor, which doesn't reload sidecars and "
            "would overwrite this one when it saves; edit and save it with the "
            "Live server (art-live: edit_profile, save_sidecar), or close it in "
            "ART first",
        )


def prepare_save(session: RenderSession, path: str) -> SavePlan:
    """Compare the sidecar on disk with the one the working profile was
    loaded against."""
    with session.image(path) as wp:
        target = artdir.sidecar_path(wp.image, session.config_dir)
        current = sidecar.read(target)
        changed_on_disk = sidecar.hash_or_none(current) != wp.sidecar_hash
        theirs: list[str] = []
        ours: list[str] = []
        if changed_on_disk:
            theirs = sidecar.changed_keys(wp.sidecar_keys, sidecar.parse(current))
            ours = sidecar.changed_keys({}, wp.changes.partial_profile())
        return SavePlan(wp.token, target, current, changed_on_disk, theirs, ours)


def conflict_error(plan: SavePlan) -> RenderError:
    return render_error(
        "conflict",
        "the sidecar is not the one the working profile was loaded against (it changed "
        "since, or the profile came from open_image's `profile`, which doesn't read it). "
        "Changed in the sidecar: "
        f"{', '.join(plan.theirs) or '(nothing that parses)'}. Changed by the agent: "
        f"{', '.join(plan.ours) or '(nothing)'}. Ask the user, then call again with "
        "on_conflict: merge (agent's changes onto the current sidecar), "
        "overwrite, or cancel.",
    )


def commit_save(
    session: RenderSession, path: str, plan: SavePlan, on_conflict: OnConflict | None
) -> SaveResult:
    """Write the sidecar as ``plan`` and ``on_conflict`` say (``on_conflict``
    is needed when the sidecar changed on disk)."""
    if plan.changed_on_disk and on_conflict == "cancel":
        return SaveResult(saved=False, path=str(plan.target), how="cancelled")
    if plan.changed_on_disk and on_conflict is None:
        raise conflict_error(plan)
    target = plan.target
    with session.image(path) as wp:
        if wp.token != plan.token:
            raise render_error(
                "conflict", "the image was reopened or reset while saving; save again"
            )
        if sidecar.hash_or_none(sidecar.read(target)) != sidecar.hash_or_none(plan.current):
            raise render_error(
                "conflict",
                "the sidecar changed again while saving; call save_sidecar again",
            )
        # Read the working profile only now, so edits made while the user
        # was answering are saved too.
        profile = wp.changes.profile
        how: SaveHow = "written"
        if plan.changed_on_disk and on_conflict == "merge" and plan.current is not None:
            merged = sidecar.merge(sidecar.parse(plan.current), wp.changes.partial_profile())
            # The working profile follows the file, so later saves and
            # renders include what the user changed there.
            profile = sidecar.merge(profile, merged)
            how = "merged"
            text = keyfile.dumps(merged)
        else:
            how = "overwritten" if plan.changed_on_disk else "written"
            text = keyfile.dumps(profile)
        data = text.encode("utf-8")
        sidecar.write_with_backup(target, text)
        wp.changes = WorkingChanges(profile)
        wp.sidecar_hash = sidecar.file_hash(data)
        wp.sidecar_keys = sidecar.parse(data)
        session.commit(wp)
    return SaveResult(saved=True, path=str(target), how=how)


def save_sidecar(
    session: RenderSession, path: str, on_conflict: OnConflict | None = None
) -> SaveResult:
    """The whole save for a front end that can't ask the user: a sidecar
    that changed on disk is a ``conflict`` unless ``on_conflict`` is given."""
    check_not_in_editor(session, path)
    plan = prepare_save(session, path)
    return commit_save(session, path, plan, on_conflict)


def save_partial_profile(
    session: RenderSession,
    path: str,
    dest: str,
    overwrite: bool = False,
    exclude: list[str] | None = None,
    vs: str = "opened",
) -> PartialProfileResult:
    exclude = exclude or []
    if vs not in PARTIAL_BASELINES:
        raise render_error(
            "out_of_range", f"vs must be one of {', '.join(PARTIAL_BASELINES)}, not {vs!r}"
        )
    baseline: PartialBaseline = "default" if vs == "default" else "opened"
    with session.image(path) as wp:
        profile = wp.changes.profile
        for entry in exclude:
            group, _, key = entry.partition("/")
            if group not in profile or (key and key not in profile[group]):
                raise render_error(
                    "unknown_key",
                    f"exclude {entry!r}: not in this image's processing profile",
                )
        target = Path(dest).resolve()
        if not target.parent.is_dir():
            raise render_error("not_found", f"folder {target.parent} does not exist")
        if target.exists() and not overwrite:
            raise render_error("exists", f"{target} exists; pass overwrite=true to replace it")
        if baseline == "default":
            # The first time for this image this runs art-cli (and may fail).
            partial = partial_vs_default(profile, session.default_profile(wp))
        else:
            partial = wp.changes.partial_profile()
        for entry in exclude:
            group, _, key = entry.partition("/")
            if key:
                partial.get(group, {}).pop(key, None)
            else:
                partial.pop(group, None)
        partial = {g: k for g, k in partial.items() if k}
        if not partial:
            return PartialProfileResult(written=False, path=str(target), keys=[], vs=baseline)
        sidecar.write_atomic(target, keyfile.dumps(partial))
        return PartialProfileResult(
            written=True, path=str(target), keys=sidecar.changed_keys({}, partial), vs=baseline
        )
