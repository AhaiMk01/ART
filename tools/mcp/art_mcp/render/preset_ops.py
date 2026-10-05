"""apply_preset: lay an ``.arp`` over the working profiles of open images."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import BaseModel

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
    items: list[PresetItemResult]
    """One per requested path, in request order."""
    applied: int
    failed: int


def apply_one(session: RenderSession, path: str, preset: Path) -> PresetItemResult:
    """Lay ``preset`` over the open image's working profile: art-cli resolves
    the two layers (``-p <working profile> -p <preset>``, no default profile
    under them) and the result replaces the working profile, its differences
    recorded as the agent's changes like an edit's. The sidecar baseline is
    left as it is. The image's lock is held throughout, so nothing changes
    the profile between the copy art-cli reads and the result put back."""
    with session.image(path) as wp:
        changed = wp.changes.layer(session.layered_profile(wp, preset))
        session.commit(wp)
    return PresetItemResult(
        path=path, keys_changed=len(changed), groups=list(dict.fromkeys(group for group, _ in changed)), error=None
    )


def apply_preset(
    session: RenderSession,
    paths: list[str],
    profile: str,
    on_progress: Callable[[int, int], None] | None = None,
) -> PresetResult:
    """Apply the ``.arp`` at ``profile`` to every open image in ``paths``. A
    problem with the call (no paths, no such file) fails it before anything
    runs; a problem with one image is that image's result and the others
    still run, up to ``session.cli.max_processes`` at once."""
    if not paths:
        raise render_error("out_of_range", "paths is empty")
    preset = Path(profile).resolve()
    if not preset.is_file():
        raise render_error("not_found", f"profile {preset} does not exist")
    try:
        preset.read_bytes()
    except OSError as e:
        raise render_error("not_found", f"profile {preset} can't be read: {e}") from e

    results = [PresetItemResult(path=p, keys_changed=None, groups=[], error=None) for p in paths]
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = {pool.submit(apply_one, session, p, preset): i for i, p in enumerate(paths)}
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

    failed = sum(r.error is not None for r in results)
    return PresetResult(profile=str(preset), items=results, applied=len(results) - failed, failed=failed)
