"""Working-profile tools: open_image, reset_profile, get_profile,
edit_profile, describe_adjustments."""

from pathlib import Path

from mcp.server.mcpserver import MCPServer
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
from art_mcp.render.metadata_tools import MetadataSummary, summarize
from art_mcp.render.session import ProfileSource, RenderSession, tool_error
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


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def open_image(path: str) -> OpenedImage:
        """Open an image and load its processing profile (from its sidecar,
        else ART's default profile) as the working profile."""
        image = Path(path).resolve()
        if not image.is_file():
            raise tool_error("not_found", f"{image} does not exist")
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

    @server.tool()
    def reset_profile(path: str, to: ProfileSource) -> ResetResult:
        """Discard working-profile changes: reload the profile from the
        image's sidecar, or from ART's default profile."""
        return ResetResult(profile_from=session.reset(path, to))

    @server.tool()
    def get_profile(path: str) -> ProfileView:
        """The image's working profile: curated tools under `adjustments`,
        every other `[Group] Key` as a string under `raw`."""
        with session.image(path) as wp:
            return read_format(wp.changes.profile)

    @server.tool()
    def edit_profile(
        path: str,
        adjustments: AdjustmentsArg = None,
        raw_edits: list[RawEdit] | None = None,
    ) -> EditResult:
        """Change values of the working profile, with typed `adjustments` of
        curated tools (range-checked; see describe_adjustments) and/or
        `raw_edits`, each setting one `[Group] Key` (as shown by get_profile)
        to a string value; the group and key must already exist. All changes
        apply, or none do. An adjustment and a raw edit may not set the same
        key. Adjusting a disabled tool also enables it (listed under
        `implied`)."""
        with session.image(path) as wp:
            try:
                parsed = parse_adjustments(adjustments) if adjustments else None
                if parsed is not None and parsed.crop is not None:
                    session.check_crop(wp, parsed.crop)
                outcome = wp.changes.edit(parsed, raw_edits or [])
            except AdjustmentError as e:
                raise tool_error(e.code, str(e)) from e
            except UnknownKey as e:
                raise tool_error("unknown_key", str(e)) from e
            except EditConflict as e:
                raise tool_error("conflict", str(e)) from e
            warnings = edit_warnings(parsed, wp.changes.profile)
        return EditResult(changed=outcome.changed, implied=outcome.implied, warnings=warnings)

    @server.tool()
    def describe_adjustments() -> AdjustmentsDescription:
        """The curated adjustments `edit_profile` accepts: each tool's fields
        with type, range, unit and the `[Group] Key` it sets. Carries a
        warning if an open image's ART profile version is newer than the
        schema's."""
        description = schema_description()
        for ppversion in session.open_ppversions():
            for warning in version_warnings(ppversion):
                if warning not in description.warnings:
                    description.warnings.append(warning)
        return description
