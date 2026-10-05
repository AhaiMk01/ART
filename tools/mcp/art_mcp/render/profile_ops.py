"""Working-profile operations: open_image, reset_profile, get_profile,
edit_profile, describe_adjustments.

Plain functions: the session first, then the tool's arguments; they return
the tool's result model and raise ``RenderError``. ``profile_tools.py`` wraps
them as MCP tools.
"""

from pathlib import Path

from pydantic import BaseModel

from art_mcp.metadata import ExiftoolError
from art_mcp.profile import Conflict as EditConflict
from art_mcp.profile import (
    ProfileView,
    RawEdit,
    UnknownKey,
    edit_warnings,
    read_format,
    version_warnings,
)
from art_mcp.render.errors import render_error
from art_mcp.render.metadata_ops import MetadataSummary, summarize
from art_mcp.render.session import ProfileSource, RenderSession
from art_mcp.schema import (
    AdjustmentError,
    AdjustmentsArg,
    AdjustmentsDescription,
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
            outcome = wp.changes.edit(parsed, raw_edits or [])
        except AdjustmentError as e:
            raise render_error(e.code, str(e)) from e
        except UnknownKey as e:
            raise render_error("unknown_key", str(e)) from e
        except EditConflict as e:
            raise render_error("conflict", str(e)) from e
        session.commit(wp)
        warnings = edit_warnings(parsed, wp.changes.profile)
    return EditResult(changed=outcome.changed, implied=outcome.implied, warnings=warnings)


def describe_adjustments(session: RenderSession) -> AdjustmentsDescription:
    description = schema_description()
    for ppversion in session.open_ppversions():
        for warning in version_warnings(ppversion):
            if warning not in description.warnings:
                description.warnings.append(warning)
    return description
