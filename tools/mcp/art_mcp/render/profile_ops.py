"""Working-profile operations: open_image, reset_profile, get_profile,
edit_profile, describe_adjustments.

Plain functions: the session first, then the tool's arguments; they return
the tool's result model and raise ``RenderError``. ``profile_tools.py`` wraps
them as MCP tools.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

from art_mcp.filmnegative import Estimate, SamplingUnsupported, estimate_for
from art_mcp.metadata import ExiftoolError
from art_mcp.profile import Conflict as EditConflict
from art_mcp.profile import (
    EditBatch,
    EditResult,
    ImageEdit,
    ProfileView,
    UnknownKey,
    check_edit_targets,
    check_groups,
    edit_item,
    edit_result,
    edit_warnings,
    failed_edit,
    read_format,
    version_warnings,
)
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.metadata_ops import MetadataSummary, summarize
from art_mcp.render.sampling_ops import sample_working_profile
from art_mcp.render.session import OpenSource, ProfileSource, RenderSession
from art_mcp.render.store import WorkingProfile
from art_mcp.sampling import SpotSamples
from art_mcp.schema import (
    AdjustmentError,
    Adjustments,
    AdjustmentsArg,
    AdjustmentsDescription,
    RawEdit,
    parse_adjustments,
)
from art_mcp.schema import describe_adjustments as schema_description


class OpenedImage(BaseModel):
    path: str
    profile_from: OpenSource
    """Where the working profile came from: the image's `sidecar`, ART's
    `default` profile, or the `profile` file given (over ART's default)."""
    art_version: str
    metadata: MetadataSummary | None = None
    """None when exiftool is unavailable or couldn't read the file; call
    inspect_image for the reason."""


class ResetResult(BaseModel):
    profile_from: ProfileSource


def open_image(session: RenderSession, path: str, profile: str | None = None) -> OpenedImage:
    image = Path(path).resolve()
    if not image.is_file():
        raise render_error("not_found", f"{image} does not exist")
    preset = None
    if profile is not None:
        preset = Path(profile).resolve()
        if not preset.is_file():
            raise render_error("not_found", f"profile {preset} does not exist")
    source = session.open(image, preset)
    summary = None
    if session.exiftool is not None:
        try:
            summary = summarize(session.exiftool.read(image))
        except ExiftoolError:
            pass  # opening still works; inspect_image reports the reason
    return OpenedImage(
        path=str(image), profile_from=source, art_version=session.art_version(), metadata=summary
    )


def reset_profile(session: RenderSession, path: str, to: ProfileSource) -> ResetResult:
    return ResetResult(profile_from=session.reset(path, to))


def get_profile(
    session: RenderSession, path: str, groups: list[str] | None = None, changed_only: bool = False
) -> ProfileView:
    with session.image(path) as wp:
        profile = wp.changes.profile
        try:
            if groups is not None:
                check_groups(profile, groups)  # before art-cli is asked for the default
            default = session.default_profile(wp) if changed_only else None
            return read_format(profile, groups=groups, default=default)
        except UnknownKey as e:
            raise render_error("unknown_key", str(e)) from e


def film_estimate(
    session: RenderSession, wp: WorkingProfile, adjustments: Adjustments | None
) -> Estimate | None:
    """ART's current Film Negative medians, sampled with art-cli ``-x`` from
    the working profile as it is before the edit, when the edit needs them."""

    def frame() -> tuple[int, int] | None:
        whole = session.whole_frame(wp)
        return whole.w, whole.h

    def fetch(spots: list[tuple[int, int]], size: int, space: str) -> SpotSamples:
        try:
            return sample_working_profile(session, wp, spots, size, space)
        except RenderError as e:
            if e.code == "unsupported":
                raise SamplingUnsupported(e.message) from e
            raise

    return estimate_for(adjustments, wp.changes.profile, frame, fetch)


def edit_profile(
    session: RenderSession,
    path: str | None = None,
    adjustments: AdjustmentsArg = None,
    raw_edits: list[RawEdit] | None = None,
    full: bool = False,
    paths: list[str] | None = None,
) -> EditResult | EditBatch:
    """Edit the working profile of the open image ``path``, or the same edit
    of every open image in ``paths`` (exactly one of the two): the single
    image's change set, or an ``EditBatch``. With ``paths`` a problem with one
    image is that image's ``error`` and the others still change, whatever it
    is (not open, a key it lacks, a crop outside its frame); a problem with the
    call (``check_edit_targets``) fails it before anything changes."""
    targets = check_edit_targets(path, paths, full, render_error)
    if targets is None:
        assert path is not None
        return edit_one(session, path, adjustments, raw_edits, full)
    return edit_many(session, targets, adjustments, raw_edits)


def edit_many(
    session: RenderSession, paths: list[str], adjustments: AdjustmentsArg, raw_edits: list[RawEdit] | None
) -> EditBatch:
    """The same edit of each image in ``paths``, up to
    ``session.cli.max_processes`` at once (an edit may need art-cli to measure
    the frame or sample the picture); each image is edited under its own lock."""

    def edit(path: str) -> ImageEdit:
        try:
            return edit_item(path, edit_one(session, path, adjustments, raw_edits, False))
        except RenderError as e:
            return failed_edit(path, str(e))
        except OSError as e:
            return failed_edit(path, f"render_failed: {e}")

    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        items = list(pool.map(edit, paths))  # in request order
    return EditBatch(items=items, failed=sum(i.error is not None for i in items))


def edit_one(
    session: RenderSession,
    path: str,
    adjustments: AdjustmentsArg,
    raw_edits: list[RawEdit] | None,
    full: bool,
) -> EditResult:
    with session.image(path) as wp:
        try:
            parsed = parse_adjustments(adjustments) if adjustments else None
            if parsed is not None and parsed.crop is not None:
                session.check_crop(wp, parsed.crop)
            outcome = wp.changes.edit(parsed, raw_edits or [], film_estimate(session, wp, parsed))
        except AdjustmentError as e:
            raise render_error(e.code, str(e)) from e
        except UnknownKey as e:
            raise render_error("unknown_key", str(e)) from e
        except EditConflict as e:
            raise render_error("conflict", str(e)) from e
        session.commit(wp)
        warnings = edit_warnings(parsed, wp.changes.profile) + outcome.warnings
        return edit_result(outcome, wp.changes.profile, parsed, raw_edits or [], warnings, full=full)


def describe_adjustments(session: RenderSession) -> AdjustmentsDescription:
    description = schema_description()
    for ppversion in session.open_ppversions():
        for warning in version_warnings(ppversion):
            if warning not in description.warnings:
                description.warnings.append(warning)
    return description
