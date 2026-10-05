"""apply_preset: lay an ``.arp`` over the working profiles of open images."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import BaseModel

from art_mcp import keyfile
from art_mcp.profile import UnknownKey, check_exclusions, drop_excluded
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.session import RenderSession


class PresetItemResult(BaseModel):
    path: str
    keys_changed: int | None
    """How many profile values the preset changed in this image's working
    profile (0: it already had them all); null when this item failed."""
    groups: list[str]
    """The `[Group]`s those values are in."""
    error: str | None
    """`<code>: <message>` when this item failed; its profile is then untouched
    and the others still run."""


class PresetResult(BaseModel):
    profile: str
    """The preset that was applied."""
    excluded: dict[str, int] = {}
    """The `exclude` entries that were left out of the preset before it was
    laid over the frames, each with how many of the preset's keys it took out
    (0: the preset had none of that); empty without `exclude`."""
    items: list[PresetItemResult]
    """One per requested path, in request order."""
    applied: int
    failed: int


def apply_one(
    session: RenderSession, path: str, preset: Path, not_in_preset: list[str] | None = None
) -> PresetItemResult:
    """Lay ``preset`` over the open image's working profile: art-cli resolves
    the two layers (``-p <working profile> -p <preset>``, no default profile
    under them) and the result replaces the working profile, its differences
    recorded as the agent's changes like an edit's. The sidecar baseline is
    left as it is. The image's lock is held throughout, so nothing changes
    the profile between the copy art-cli reads and the result put back.
    ``not_in_preset``: exclusions that took nothing out of the preset; each
    must at least name something of this image's profile, else it is a typo
    (``unknown_key``)."""
    with session.image(path) as wp:
        try:
            check_exclusions(wp.changes.profile, not_in_preset or [])
        except UnknownKey as e:
            raise render_error("unknown_key", f"{e}, nor in the preset") from e
        changed = wp.changes.layer(session.layered_profile(wp, preset))
        session.commit(wp)
    return PresetItemResult(
        path=path, keys_changed=len(changed), groups=list(dict.fromkeys(group for group, _ in changed)), error=None
    )


def without_excluded(session: RenderSession, preset: Path, exclude: list[str]) -> tuple[Path, dict[str, int]]:
    """A copy of ``preset`` (in the preview folder; the caller deletes it) with
    the ``exclude`` entries left out (``save_partial_profile``'s: `Group` or
    `Group/Key`), and what each took out. The preset file is not touched."""
    try:
        keys = keyfile.loads(preset.read_text(encoding="utf-8"))
    except ValueError as e:
        raise render_error("out_of_range", f"profile {preset} is not a processing profile (.arp): {e}") from e
    excluded = drop_excluded(keys, exclude)
    copy = session.previews.new_file("preset", ".arp")
    copy.write_text(keyfile.dumps(keys), encoding="utf-8")
    return copy, excluded


def apply_preset(
    session: RenderSession,
    paths: list[str],
    profile: str,
    exclude: list[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> PresetResult:
    """Apply the ``.arp`` at ``profile`` to every open image in ``paths``, less
    what ``exclude`` names (`Group` or `Group/Key` entries, dropped from the
    preset before it is layered). A problem with the call (no paths, no such
    file, a preset that does not parse) fails it before anything runs; a
    problem with one image is that image's result and the others still run, up
    to ``session.cli.max_processes`` at once."""
    if not paths:
        raise render_error("out_of_range", "paths is empty")
    preset = Path(profile).resolve()
    if not preset.is_file():
        raise render_error("not_found", f"profile {preset} does not exist")
    try:
        preset.read_bytes()
    except OSError as e:
        raise render_error("not_found", f"profile {preset} can't be read: {e}") from e

    layer, excluded = preset, {}
    if exclude:
        layer, excluded = without_excluded(session, preset, exclude)
    not_in_preset = [entry for entry, dropped in excluded.items() if dropped == 0]

    results = [PresetItemResult(path=p, keys_changed=None, groups=[], error=None) for p in paths]
    done = 0
    try:
        with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
            futures = {pool.submit(apply_one, session, p, layer, not_in_preset): i for i, p in enumerate(paths)}
            for future in as_completed(futures):
                i = futures[future]
                try:
                    results[i] = future.result()
                except RenderError as e:
                    results[i].error = str(e)
                except OSError as e:
                    results[i].error = f"render_failed: {e}"
                done += 1
                if on_progress:
                    on_progress(done, len(paths))
    finally:
        if layer != preset:
            layer.unlink(missing_ok=True)

    failed = sum(r.error is not None for r in results)
    return PresetResult(
        profile=str(preset), excluded=excluded, items=results, applied=len(results) - failed, failed=failed
    )
