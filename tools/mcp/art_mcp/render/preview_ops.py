"""Preview operation: render_preview."""

import shutil
from pathlib import Path

from pydantic import BaseModel

from art_mcp import artdir, keyfile
from art_mcp.concurrency import image_key
from art_mcp.marks import Mark, check_marks, mark_file
from art_mcp.render.artcli import Rect, crop_profile, preview_args, region_rect, resize_profile
from art_mcp.render.errors import render_error
from art_mcp.render.export_ops import move_over
from art_mcp.render.session import RenderSession

PREVIEW_SIZE = 1024
MAX_PREVIEW_SIZE = 2576
"""Claude downscales images with a longer edge above this."""
OUTPUT_SUFFIXES = (".jpg", ".jpeg")


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
    warnings: list[str] = []
    """Which marks were not drawn, and why a mark may be misplaced."""


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


def check_output(output: str, image: Path, overwrite: bool) -> Path:
    """The file a preview is to be written to: ``output`` must be an absolute
    path naming a ``.jpg`` in a folder that exists (``out_of_range``,
    ``not_found``), must not be ``image`` itself, and must not exist yet unless
    ``overwrite`` (``exists``). Checked before anything renders."""
    given = Path(output)
    if not given.is_absolute():
        raise render_error("out_of_range", f"output must be an absolute path to a .jpg file, not {output!r}")
    if given.suffix.lower() not in OUTPUT_SUFFIXES:
        raise render_error("out_of_range", f"output must be a .jpg file, not {given.name!r}")
    dest = given.resolve()
    if not dest.parent.is_dir():
        raise render_error("not_found", f"folder {dest.parent} does not exist")
    if image_key(dest) == image_key(image.resolve()):
        raise render_error("exists", f"{dest} is the image itself; write the preview to another file")
    if dest.exists() and not overwrite:
        raise render_error("exists", f"{dest} already exists; pass overwrite=true to replace it")
    return dest


def place_output(rendered: Path, dest: Path, overwrite: bool) -> None:
    """Move the rendered preview ``rendered`` to ``dest`` (``check_output``'s
    answer) and leave nothing of it in the previews folder. Without
    ``overwrite`` the file is created exclusively, so a file that appeared
    since the check is not replaced either (``exists``)."""
    try:
        if overwrite:
            move_over(rendered, dest)
        else:
            try:
                target = dest.open("xb")
            except FileExistsError as e:
                raise render_error("exists", f"{dest} already exists; pass overwrite=true to replace it") from e
            try:
                with target, rendered.open("rb") as source:
                    shutil.copyfileobj(source, target)
            except BaseException:
                dest.unlink(missing_ok=True)  # no half a file is left behind
                raise
    except OSError as e:
        raise render_error("render_failed", f"cannot write {dest}: {e}") from e
    finally:
        rendered.unlink(missing_ok=True)


def render_preview(
    session: RenderSession,
    path: str,
    max_size: int = PREVIEW_SIZE,
    region: Region | None = None,
    output: str | None = None,
    overwrite: bool = False,
    marks: list[Mark] | None = None,
) -> Preview:
    if not 1 <= max_size <= MAX_PREVIEW_SIZE:
        raise render_error("out_of_range", f"max_size must be 1 to {MAX_PREVIEW_SIZE}")
    if region is not None and not region.inside_image():
        raise render_error(
            "out_of_range",
            "region x, y, w, h are fractions of the image: x, y >= 0, w, h > 0, "
            "x + w <= 1 and y + h <= 1",
        )
    marks = marks or []
    check_marks(marks, None, render_error)
    dest = check_output(output, Path(path), overwrite) if output is not None else None
    warnings: list[str] = []
    with session.image(path) as wp:
        # -f resizes before processing, which approximates sharpening and
        # local effects: only worth it for a whole-image preview that fits the
        # user's fast-export box (-f would shrink anything larger into it).
        fast = region is None and max_size <= artdir.fast_export_box(session.config_dir)
        crop_text = None
        shown = session.frame_of(wp) if region is not None or marks else None
        if region is not None:
            shown = region_rect(shown, x=region.x, y=region.y, w=region.w, h=region.h)
            crop_text = crop_profile(shown)
        if marks:
            whole = session.whole_frame(wp)
            check_marks(marks, (whole.w, whole.h), render_error)
        rendered = render_jpeg(
            session, wp.image, keyfile.dumps(wp.changes.profile), max_size, fast=fast, crop_text=crop_text
        )
        if marks:
            warnings = mark_rendering(rendered, marks, shown)
    if dest is not None:
        place_output(rendered, dest, overwrite)
        rendered = dest
    return Preview(path=str(rendered), max_size=max_size, warnings=warnings)


def mark_rendering(rendered: Path, marks: list[Mark], shown: Rect) -> list[str]:
    """Draw ``marks`` on the rendered preview ``rendered``, which shows the
    ``shown`` area of the frame; its warnings. A rendering that can't be read
    or marked is ``render_failed`` and the file is removed."""
    try:
        return mark_file(rendered, marks, shown)
    except (ValueError, OSError) as e:
        rendered.unlink(missing_ok=True)
        raise render_error("render_failed", str(e)) from e
