"""Export tools: export_image, export_batch (adapters over ``export_ops``)."""

from typing import Annotated

import anyio
import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from art_mcp.render import export_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.export_ops import BatchItem, BatchResult, ExportResult
from art_mcp.render.session import RenderSession

# The enum lists the values in the schema; a wrong one still gets out_of_range.
Format = Annotated[str, Field(json_schema_extra={"enum": ["jpeg", "tiff", "png"]})]
ProfileName = Annotated[str, Field(json_schema_extra={"enum": list(ops.PROFILE_NAMES)})]


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def export_image(
        path: str,
        output: str,
        format: Format,
        quality: int | None = None,
        bit_depth: int | str | None = None,
        write_profile: bool = False,
        profile_name: ProfileName = "output",
        overwrite: bool = False,
    ) -> ExportResult:
        """Render the working profile (saved or not) at full size to `output`.
        `quality` (1..100) is for jpeg; `bit_depth` is 8 for jpeg, 8|16 for
        png, 8|16|"16f"|32 for tiff (default: ART's). An existing `output` (or
        `.arp`) is refused with `exists` unless `overwrite`. With
        `write_profile`, the working profile is also saved as `<output>.arp`;
        otherwise no `.arp` is written. `profile_name: "source"` (needs
        `write_profile`) names it after the image instead, as ART would its
        sidecar (`IMG.ARW.arp`, or `IMG.arp` with ART's strip-extension
        option), in the folder of `output`, ready to use beside a copy of the
        image; the image's own sidecar is never written (an `output` in the
        image's own folder is `out_of_range`, even with `overwrite`). The
        folder of `output` must exist."""
        with as_tool_errors():
            return ops.export_image(
                session, path, output, format, quality, bit_depth, write_profile, profile_name, overwrite
            )

    @server.tool()
    async def export_batch(
        folder: str,
        format: Format,
        ctx: Context,
        items: list[BatchItem] | None = None,
        source: str | None = None,
        pattern: str | None = None,
        profiles: list[str] | None = None,
        quality: int | None = None,
        bit_depth: int | str | None = None,
        name: str = "{stem}",
        write_profile: bool = False,
        profile_name: ProfileName = "output",
        overwrite: bool = False,
    ) -> BatchResult:
        """Export many images at full size into `folder` (it must exist), as
        `<name><suffix>` with `{stem}` = the image's file name without
        extension. Give `items`, or `source`: a folder (not its subfolders)
        whose raw, jpeg and tiff images are all exported, in file name order,
        optionally only those whose name matches `pattern` (a glob, any
        case, e.g. `IMG_01*`). Each item exports its working profile (open it
        first), or with `profiles` the given `.arp` files layered over ART's
        default profile (e.g. a set-wide preset, then the image's own partial profile;
        no need to open it). With `source`, the top-level `profiles` do the
        same for every image, else each is exported with its working profile.
        Format, `quality`, `bit_depth`, `write_profile`, `profile_name`
        (`"source"` leaves each image's `.arp` in `folder` under its sidecar
        name, a ready-to-use set) and `overwrite` as in export_image. One
        failing image (not open, `exists`, an image whose own folder is
        `folder` with `profile_name: "source"`, a render error) is reported in
        its result and the others still run; names that collide fail the
        whole call before anything renders; an image is never exported over
        itself. Working profiles are copied when the call starts. Progress is
        reported per finished image. A full-size render takes about a second
        (24 MP, test machine), so dozens of images in one call run for tens of
        seconds: where the client's tool timeout is short (37 images hit a 30 s
        one), export 10 to 15 images per call. A call the client gave up on
        keeps running and still writes its files."""

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> BatchResult:
            with as_tool_errors():
                return ops.export_batch(
                    session, items, folder, format, quality, bit_depth, name,
                    write_profile, profile_name, overwrite, source, pattern, profiles, on_progress=progress,
                )  # fmt: skip

        return await anyio.to_thread.run_sync(run)
