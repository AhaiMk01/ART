"""Working-profile operations: open_image, reset_profile, get_profile,
edit_profile, describe_adjustments.

Plain functions: the session first, then the tool's arguments; they return
the tool's result model and raise ``RenderError``. ``profile_tools.py`` wraps
them as MCP tools.
"""

from pathlib import Path

from pydantic import BaseModel

from art_mcp.filmnegative import Estimate, SamplingUnsupported, estimate_for
from art_mcp.sampling import SpotSamples
from art_mcp.metadata import ExiftoolError
from art_mcp.profile import Conflict as EditConflict
from art_mcp.profile import (
    ProfileView,
    UnknownKey,
    edit_warnings,
    read_format,
    version_warnings,
)
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.metadata_ops import MetadataSummary, summarize
from art_mcp.render.sampling_ops import sample_working_profile
from art_mcp.render.session import ProfileSource, RenderSession
from art_mcp.render.store import WorkingProfile
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
    profile_from: ProfileSource
    art_version: str
    metadata: MetadataSummary | None = None
    """None when exiftool is unavailable or couldn't read the file; call
    inspect_image for the reason."""


class ResetResult(BaseModel):
    profile_from: ProfileSource


class EditResult(BaseModel):
    changed: list[RawEdit]
    """Each [Group] Key whose value this call changed, with its new value
    (re-setting a value is not a change)."""
    implied: list[RawEdit]
    """The part of `changed` that was not asked for: a disabled tool enabled
    because it was adjusted, White Balance switched to CustomTemp."""
    warnings: list[str]


def open_image(session: RenderSession, path: str) -> OpenedImage:
    image = Path(path).resolve()
    if not image.is_file():
        raise render_error("not_found", f"{image} does not exist")
    source = session.open(image)
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


def get_profile(session: RenderSession, path: str) -> ProfileView:
    with session.image(path) as wp:
        return read_format(wp.changes.profile)


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
    path: str,
    adjustments: AdjustmentsArg = None,
    raw_edits: list[RawEdit] | None = None,
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
    return EditResult(changed=outcome.changed, implied=outcome.implied, warnings=warnings)


def describe_adjustments(session: RenderSession) -> AdjustmentsDescription:
    description = schema_description()
    for ppversion in session.open_ppversions():
        for warning in version_warnings(ppversion):
            if warning not in description.warnings:
                description.warnings.append(warning)
    return description
