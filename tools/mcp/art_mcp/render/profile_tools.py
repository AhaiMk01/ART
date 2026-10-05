"""Working-profile tools: open_image, reset_profile, get_profile,
edit_profile, describe_adjustments (adapters over ``profile_ops``)."""

from mcp.server.mcpserver import MCPServer

from art_mcp.profile import EditResult, ProfileView
from art_mcp.render import profile_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.profile_ops import OpenedImage, ResetResult
from art_mcp.render.session import ProfileSource, RenderSession
from art_mcp.schema import AdjustmentsArg, AdjustmentsDescription, RawEdit


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def open_image(path: str, profile: str | None = None) -> OpenedImage:
        """Open an image and load its processing profile (from its sidecar,
        else ART's default profile) as the working profile. With `profile`, an
        `.arp` file (a complete profile or a partial one), the working profile
        is that file laid over ART's default profile instead (as art-cli's
        `-d -p`) and the image's own sidecar is neither read nor written;
        `profile_from` says which source was used."""
        with as_tool_errors():
            return ops.open_image(session, path, profile)

    @server.tool()
    def reset_profile(path: str, to: ProfileSource) -> ResetResult:
        """Discard working-profile changes: reload the profile from the
        image's sidecar, or from ART's default profile."""
        with as_tool_errors():
            return ops.reset_profile(session, path, to)

    @server.tool()
    def get_profile(path: str, groups: list[str] | None = None, changed_only: bool = False) -> ProfileView:
        """The image's working profile: curated tools under `adjustments`,
        every other `[Group] Key` as a string under `raw`. A whole profile is
        large (about 15k tokens): `groups` (`[Group]` names as in `raw`, e.g.
        `["Film Negative", "ToneCurve"]`; an unknown one is unknown_key and
        lists the valid ones) reads only those groups, and `changed_only`
        only the values that differ from ART's default profile for the image
        (whatever is not listed equals it)."""
        with as_tool_errors():
            return ops.get_profile(session, path, groups, changed_only)

    @server.tool()
    def edit_profile(
        path: str,
        adjustments: AdjustmentsArg = None,
        raw_edits: list[RawEdit] | None = None,
        full: bool = False,
    ) -> EditResult:
        """Change values of the working profile, with typed `adjustments` of
        curated tools (range-checked; see describe_adjustments) and/or
        `raw_edits`, each setting one `[Group] Key` (as shown by get_profile)
        to a string value; the group and key must already exist. All changes
        apply, or none do. An adjustment and a raw edit may not set the same
        key. Adjusting a disabled tool also enables it.

        Returns only what changed: `changed` ([Group] -> Key -> new value),
        `implied` (changes you did not ask for, such as that enabling, in the
        same shape), `drawn` (the line ART draws for a tone curve you set) and
        `warnings`. `full` also returns the groups touched, as get_profile
        reads them."""
        with as_tool_errors():
            return ops.edit_profile(session, path, adjustments, raw_edits, full)

    @server.tool()
    def describe_adjustments() -> AdjustmentsDescription:
        """The curated adjustments `edit_profile` accepts: each tool's fields
        with type, range, unit and the `[Group] Key` it sets. Carries a
        warning if an open image's ART profile version is newer than the
        schema's."""
        with as_tool_errors():
            return ops.describe_adjustments(session)
