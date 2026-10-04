"""Preview tool: render_preview."""

import base64
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent
from pydantic import BaseModel

from art_mcp import artdir, keyfile
from art_mcp.render.artcli import crop_profile, preview_args, region_rect, resize_profile
from art_mcp.render.session import RenderSession, tool_error

PREVIEW_SIZE = 1024
MAX_PREVIEW_SIZE = 2576
"""Claude downscales images with a longer edge above this."""


class Region(BaseModel):
    """An area of the image as fractions (0 to 1) of its width and height."""

    x: float
    y: float
    w: float
    h: float

    def inside_image(self) -> bool:
        eps = 1e-9
        return (
            self.x >= 0 and self.y >= 0 and self.w > 0 and self.h > 0
            and self.x + self.w <= 1 + eps and self.y + self.h <= 1 + eps
        )  # fmt: skip


class Preview(BaseModel):
    path: str
    """JPEG file; open it to look at the preview."""
    max_size: int


def register(server: MCPServer, session: RenderSession) -> None:
    previews = session.previews

    @server.tool()
    def render_preview(
        path: str,
        max_size: int = PREVIEW_SIZE,
        region: Region | None = None,
        inline: bool | None = None,
    ) -> Annotated[CallToolResult, Preview]:
        """Render the working profile as a JPEG (long edge `max_size` px, 1 to
        2576) and return its path. `region` {x, y, w, h}, as fractions of the
        image, renders just that area at 1:1 (shrunk only to fit `max_size`).
        `inline` also returns the image itself (default: the server's
        --inline-previews setting)."""
        if not 1 <= max_size <= MAX_PREVIEW_SIZE:
            raise tool_error("out_of_range", f"max_size must be 1 to {MAX_PREVIEW_SIZE}")
        if region is not None and not region.inside_image():
            raise tool_error(
                "out_of_range",
                "region x, y, w, h are fractions of the image: x, y >= 0, w, h > 0, "
                "x + w <= 1 and y + h <= 1",
            )
        with session.image(path) as wp:
            # -f resizes before processing, which approximates sharpening and
            # local effects: only worth it for a whole-image preview that fits the
            # user's fast-export box (-f would shrink anything larger into it).
            fast = region is None and max_size <= artdir.fast_export_box(session.config_dir)
            profile = previews.new_file("profile", ".arp")
            crop = previews.new_file("crop", ".arp")
            resize = previews.new_file("resize", ".arp")
            output = previews.new_file("preview", ".jpg")
            try:
                profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
                if region is not None:
                    rect = region_rect(
                        session.frame_of(wp), x=region.x, y=region.y, w=region.w, h=region.h
                    )
                    crop.write_text(crop_profile(rect), encoding="utf-8")
                resize.write_text(resize_profile(max_size), encoding="utf-8")
                session.run(
                    preview_args(
                        wp.image, output, profile, resize, fast=fast,
                        crop=crop if region is not None else None,
                    ),
                    output,
                )  # fmt: skip
            except BaseException:
                output.unlink(missing_ok=True)
                raise
            finally:
                for temporary in (profile, crop, resize):
                    temporary.unlink(missing_ok=True)
        result = Preview(path=str(output), max_size=max_size)
        content: list[ContentBlock] = [TextContent(text=result.model_dump_json())]
        if inline if inline is not None else session.inline_previews:
            content.append(
                ImageContent(
                    data=base64.b64encode(output.read_bytes()).decode("ascii"),
                    mime_type="image/jpeg",
                )
            )
        # Returning the result object (rather than the model) is what lets a
        # tool carry content blocks next to its structured output.
        return CallToolResult(content=content, structured_content=result.model_dump(mode="json"))
