"""Preview operation: render_preview."""

from pathlib import Path

from pydantic import BaseModel

from art_mcp import artdir, keyfile
from art_mcp.render.artcli import crop_profile, preview_args, region_rect, resize_profile
from art_mcp.render.errors import render_error
from art_mcp.render.session import RenderSession

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


def render_jpeg(
    session: RenderSession,
    image: Path,
    profile_text: str,
    max_size: int,
    *,
    fast: bool,
    crop_text: str | None = None,
) -> Path:
    """Render ``image`` with the complete profile ``profile_text`` (and the
    optional ``crop_text`` layer) to a new JPEG in the previews folder, its
    long edge at most ``max_size``; the caller removes the file. The ``fast``
    flag makes art-cli resize before processing."""
    previews = session.previews
    profile = previews.new_file("profile", ".arp")
    crop = previews.new_file("crop", ".arp")
    resize = previews.new_file("resize", ".arp")
    output = previews.new_file("preview", ".jpg")
    try:
        profile.write_text(profile_text, encoding="utf-8")
        if crop_text is not None:
            crop.write_text(crop_text, encoding="utf-8")
        resize.write_text(resize_profile(max_size), encoding="utf-8")
        session.run(
            preview_args(
                image, output, profile, resize, fast=fast,
                crop=crop if crop_text is not None else None,
            ),
            output,
        )  # fmt: skip
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    finally:
        for temporary in (profile, crop, resize):
            temporary.unlink(missing_ok=True)
    return output


def render_preview(
    session: RenderSession,
    path: str,
    max_size: int = PREVIEW_SIZE,
    region: Region | None = None,
) -> Preview:
    if not 1 <= max_size <= MAX_PREVIEW_SIZE:
        raise render_error("out_of_range", f"max_size must be 1 to {MAX_PREVIEW_SIZE}")
    if region is not None and not region.inside_image():
        raise render_error(
            "out_of_range",
            "region x, y, w, h are fractions of the image: x, y >= 0, w, h > 0, "
            "x + w <= 1 and y + h <= 1",
        )
    with session.image(path) as wp:
        # -f resizes before processing, which approximates sharpening and
        # local effects: only worth it for a whole-image preview that fits the
        # user's fast-export box (-f would shrink anything larger into it).
        fast = region is None and max_size <= artdir.fast_export_box(session.config_dir)
        crop_text = None
        if region is not None:
            rect = region_rect(session.frame_of(wp), x=region.x, y=region.y, w=region.w, h=region.h)
            crop_text = crop_profile(rect)
        output = render_jpeg(
            session, wp.image, keyfile.dumps(wp.changes.profile), max_size, fast=fast, crop_text=crop_text
        )
    return Preview(path=str(output), max_size=max_size)
