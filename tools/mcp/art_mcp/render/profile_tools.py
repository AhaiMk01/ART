"""Working-profile tools: open_image, reset_profile, get_profile,
edit_profile, describe_adjustments (adapters over ``profile_ops``)."""

import anyio
import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer

from art_mcp.profile import EditOutput, ProfileView
from art_mcp.render import profile_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.profile_ops import OpenBatch, OpenedImage, OpenOutput, ResetBatch, ResetOutput, ResetResult
from art_mcp.render.session import ProfileSource, RenderSession
from art_mcp.schema import AdjustmentsArg, AdjustmentsDescription, EditItem, RawEdit


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    async def open_image(
        ctx: Context, path: str | None = None, profile: str | None = None, paths: list[str] | None = None
    ) -> OpenOutput:
        """Open an image and load its processing profile (from its sidecar,
        else ART's default profile) as the working profile. With `profile`, an
        `.arp` file (a complete profile or a partial one), the working profile
        is that file laid over ART's default profile instead (as art-cli's
        `-d -p`) and the image's own sidecar is neither read nor written;
        `profile_from` says which source was used.

        `paths` (1 to 50 images; give `path` or `paths`) opens each one the
        same way (the same `profile` for all), up to two at a time, with
        progress per image. The result is `{items, failed}`: per image, in
        request order, `{path, profile_from, metadata}` as above (`path` as
        you gave it; `metadata` left out when there is none) or `{path,
        error}` (`not_found`, a render failure), the others still open. A
        `profile` that is no file fails the call before any image opens."""

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> OpenedImage | OpenBatch:
            with as_tool_errors():
                return ops.open_image(session, path, profile, paths, on_progress=progress)

        return OpenOutput(await anyio.to_thread.run_sync(run))

    @server.tool()
    async def reset_profile(
        to: ProfileSource, ctx: Context, path: str | None = None, paths: list[str] | None = None
    ) -> ResetOutput:
        """Discard working-profile changes: reload the profile from the
        image's sidecar, or from ART's default profile. `path` is one open
        image; `paths` (1 to 50 open images; give one of the two) resets each
        the same way, up to two at a time, with progress per image, and the
        result is `{items, failed}`: per image, in request order, `{path,
        profile_from}` or `{path, error}` (`not_open`; `not_found` when `to`
        is `sidecar` and it has none), the others still reset."""

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> ResetResult | ResetBatch:
            with as_tool_errors():
                return ops.reset_profile(session, to, path, paths, on_progress=progress)

        return ResetOutput(await anyio.to_thread.run_sync(run))

    @server.tool()
    def get_profile(path: str, groups: list[str] | None = None, changed_only: bool = False) -> ProfileView:
        """The image's working profile: curated tools under `adjustments`,
        every other `[Group] Key` as a string under `raw`. A whole profile is
        large (about 15k tokens): `groups` (`[Group]` names as in `raw`, e.g.
        `["Exposure", "ToneCurve"]`; an unknown one is unknown_key and
        lists the valid ones) reads only those groups, and `changed_only`
        only the values that differ from ART's default profile for the image
        (whatever is not listed equals it)."""
        with as_tool_errors():
            return ops.get_profile(session, path, groups, changed_only)

    @server.tool()
    def edit_profile(
        path: str | None = None,
        adjustments: AdjustmentsArg = None,
        raw_edits: list[RawEdit] | None = None,
        full: bool = False,
        paths: list[str] | None = None,
        items: list[EditItem] | None = None,
    ) -> EditOutput:
        """Change values of the working profile of an image (`path`), or the
        same change to several images at once (`paths`: 1 to 50 open images),
        or a different change to each (`items`: 1 to 50 entries `{path,
        adjustments?, raw_edits?}`, each image getting its own; give one of
        the three), with typed `adjustments` of curated tools
        (range-checked; see describe_adjustments) and/or `raw_edits`, each
        setting one `[Group] Key` (as shown by get_profile) to a string
        value; the group and key must already exist. All changes apply, or
        none do (per image with `paths` or `items`). An adjustment and a raw
        edit may not set the same key. Adjusting a disabled tool also enables
        it.

        Returns only what changed: `changed` ([Group] -> Key -> new value),
        `implied` (changes you did not ask for, such as that enabling, in the
        same shape), `created` (a new Color Correction region or mask shape:
        its keys at ART's defaults are counted, not listed), `drawn` (the line
        ART draws for a tone curve you set) and `warnings`. `full` also
        returns the groups touched, as get_profile reads them.

        With `paths` or `items` the result is `{items, failed}` instead: per
        image, in request order, `{path, changed, implied, warnings, error}`,
        where `changed` is how many values the edit changed in that image (0:
        it had them already; the values are not listed) and `implied` as
        above. A problem with one image (not open, a key it lacks, a crop
        outside its frame) is that image's `error`, `<code>: <message>`, and
        the others still change. With `items`, `adjustments` and `raw_edits`
        go in each item, not beside them; two items for one image are applied
        in order, each as its own change. `full` is for one image only."""
        with as_tool_errors():
            return EditOutput(ops.edit_profile(session, path, adjustments, raw_edits, full, paths, items))

    @server.tool()
    def describe_adjustments() -> AdjustmentsDescription:
        """The curated adjustments `edit_profile` accepts: each tool's fields
        with type, range, unit and the `[Group] Key` it sets. Carries a
        warning if an open image's ART profile version is newer than the
        schema's."""
        with as_tool_errors():
            return ops.describe_adjustments(session)
