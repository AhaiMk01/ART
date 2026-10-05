"""Metadata tools: inspect_image, inspect_images (adapters over ``metadata_ops``)."""

import anyio
import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer

from art_mcp.metadata import ImagesMetadata, Metadata
from art_mcp.render import metadata_ops as ops
from art_mcp.render.adapter import as_tool_errors
from art_mcp.render.session import RenderSession


def register(server: MCPServer, session: RenderSession) -> None:
    @server.tool()
    def inspect_image(path: str, tags: list[str] | None = None) -> Metadata:
        """The image's metadata (read with ART's exiftool): make, model, lens,
        ISO, shutter, aperture, focal length, capture date, the pixel
        dimensions the file records (`width`, `height`) and orientation, each
        None when the file has no value, plus any extra exiftool `tags` named
        (by tag name, e.g. "Software") that it has. ISO, shutter, aperture
        and focal length are those of the camera that took THIS file: for a
        re-photographed original (a negative or slide on a light table, a
        print) the digitising camera, not the original's own exposure (the
        file does not carry that); aperture is null for a manual lens.
        `frame_width` and `frame_height` are the size ART works in (after
        coarse rotation and the raw border), the space `crop` and
        `sample_spots` coordinates are in: use them, not `width` and
        `height`, to size a crop. Measured with art-cli the first time (about
        a second), null if that fails."""
        with as_tool_errors():
            return ops.inspect_image(session, path, tags)

    @server.tool()
    async def inspect_images(
        paths: list[str], ctx: Context, tags: list[str] | None = None, frame: bool = False
    ) -> ImagesMetadata:
        """inspect_image for many images in one call: `paths` (1 to 100, each
        an opened image: wait for `open_image` to return, or the ones not yet
        open come back `not_open`), exiftool run once for all of them. One result per
        path, in request order: `{path, metadata, error}`, `metadata` as
        inspect_image returns it, or an `error` (`not_open`, a read failure)
        while the others still come back. ISO, shutter and aperture are those
        of the camera that took THIS file: for a re-photographed original (a negative or slide on a light table, a
        print) the digitising camera, not the original's own exposure; aperture is null
        for a manual lens. `frame_width` and `frame_height` cost an art-cli
        run per image the first time (about a second each, two at once,
        progress per image), so they are measured only with `frame: true`,
        else null."""

        def progress(done: int, total: int) -> None:
            anyio.from_thread.run(ctx.report_progress, done, total)

        def run() -> ImagesMetadata:
            with as_tool_errors():
                return ops.inspect_images(session, paths, tags, frame, on_progress=progress)

        return await anyio.to_thread.run_sync(run)
