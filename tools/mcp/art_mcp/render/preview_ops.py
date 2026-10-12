"""Preview operation: render_preview."""

import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from art_mcp import artdir, keyfile
from art_mcp.concurrency import image_key
from art_mcp.marks import Mark, check_marks, draw_marks, labels_of, mark_file, save_jpeg
from art_mcp.render.artcli import (
    ArtCliError,
    ArtCliTimeout,
    Rect,
    crop_profile,
    looks_like_help,
    preview_args,
    region_rect,
    resize_profile,
    stage_stats_args,
)
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.export_ops import move_over
from art_mcp.render.session import RenderSession
from art_mcp.sampling import UNSUPPORTED_STAGE

PREVIEW_STAGES = ("display", "converted")

PREVIEW_SIZE = 1024
MAX_PREVIEW_SIZE = 2576
"""Claude downscales images with a longer edge above this."""
OUTPUT_SUFFIXES = (".jpg", ".jpeg")
MAX_PREVIEW_PATHS = 16
"""The most images one render_preview call takes: with ``inline`` each is an
image in the reply, about a thousand tokens each at the default size."""


class Region(BaseModel):
    """Image fractions (0 to 1)."""

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


class ZoomTile(BaseModel):
    # label: the mark's label or number; window: the frame pixels the tile
    # shows; left, top, size: the tile's place in the JPEG (size px square).
    label: str
    window: dict[str, int]
    left: int
    top: int
    size: int


class FramePreview(BaseModel):
    path: str
    """JPEG file; open it to look at the preview."""
    max_size: int
    width: int | None = None
    height: int | None = None
    # The JPEG's size in pixels; `shown` the frame pixels it shows.
    shown: dict[str, int] | None = None
    warnings: list[str] = []
    """Which marks were not drawn, and why a mark may be misplaced."""


class Preview(FramePreview):
    tiles: list[ZoomTile] | None = None
    # With zoom: one tile per mark, in request order.


class PreviewItem(BaseModel):
    path: str
    """The image's path as requested."""
    preview_path: str | None = None
    """JPEG file of its preview; left out when this image failed."""
    width: int | None = None
    height: int | None = None
    shown: dict[str, int] | None = None
    error: str | None = None
    """`<code>: <message>` when this image failed (the others still render);
    left out otherwise."""


class PreviewBatch(BaseModel):
    items: list[PreviewItem]
    """One per requested path, in request order."""
    failed: int


class PreviewOutput(BaseModel):
    """With `path`: `path`, `max_size` and `warnings` of that preview; with
    `paths`: `items` and `failed`."""

    # Only the published shape of the result: the tool builds its own from
    # ``Preview`` or ``PreviewBatch``, and this one lets the schema allow both.
    path: str | None = None
    max_size: int | None = None
    width: int | None = None
    height: int | None = None
    shown: dict[str, int] | None = None
    tiles: list[dict[str, Any]] | None = None  # as `Preview.tiles`, left loose to keep the schema small
    warnings: list[str] | None = None
    items: list[PreviewItem] | None = None
    failed: int | None = None


def check_preview_call(
    path: str | None,
    paths: list[str] | None,
    output: str | None,
    overwrite: bool,
    marks: list[Mark] | None,
) -> None:
    """The checks of a render_preview call that need no image: exactly one of
    ``path`` and ``paths`` (1 to ``MAX_PREVIEW_PATHS`` entries), and nothing
    that only fits one image (``marks``, ``output``, ``overwrite``) with
    ``paths``."""
    if (path is None) == (paths is None):
        raise render_error("out_of_range", "give path or paths" + (", not both" if path is not None else ""))
    if paths is None:
        return
    if not paths:
        raise render_error("out_of_range", "paths is empty")
    if len(paths) > MAX_PREVIEW_PATHS:
        raise render_error(
            "out_of_range", f"paths has {len(paths)} entries; the most one call takes is {MAX_PREVIEW_PATHS}"
        )
    for name, given in (("marks", marks), ("output", output), ("overwrite", overwrite or None)):
        if given:
            raise render_error(
                "out_of_range", f"{name} goes with one `path`, not `paths` (a batch has no single {name})"
            )


def render_previews(
    session: RenderSession,
    paths: list[str],
    max_size: int = PREVIEW_SIZE,
    region: Region | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> PreviewBatch:
    """A preview of each of ``paths`` (the call is already checked by
    ``check_preview_call``), up to ``session.cli.max_processes`` at once;
    ``on_progress(done, total)`` is called as each finishes. An image that
    can't be rendered (not open, a render error) is its item's error and the
    others still come back; a ``max_size`` or ``region`` that is wrong fails
    the call before anything renders."""
    check_size_and_region(max_size, region)
    items = [PreviewItem(path=p) for p in paths]

    def run(item: PreviewItem) -> None:
        done = render_preview(session, item.path, max_size, region)
        item.preview_path, item.width, item.height, item.shown = done.path, done.width, done.height, done.shown

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = {pool.submit(run, item): item for item in items}
        for future in as_completed(futures):
            try:
                future.result()
            except RenderError as e:
                futures[future].error = str(e)
            except OSError as e:
                futures[future].error = f"render_failed: {e}"
            done += 1
            if on_progress:
                on_progress(done, len(items))
    return PreviewBatch(items=items, failed=sum(item.error is not None for item in items))


def check_size_and_region(max_size: int, region: Region | None) -> None:
    """``out_of_range`` for a ``max_size`` outside 1 to ``MAX_PREVIEW_SIZE``
    or a region outside the image."""
    if not 1 <= max_size <= MAX_PREVIEW_SIZE:
        raise render_error("out_of_range", f"max_size must be 1 to {MAX_PREVIEW_SIZE}")
    if region is not None and not region.inside_image():
        raise render_error(
            "out_of_range",
            "region x, y, w, h are fractions of the image: x, y >= 0, w, h > 0, "
            "x + w <= 1 and y + h <= 1",
        )


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
    stage: str = "display",
    zoom: bool = False,
) -> Preview:
    check_size_and_region(max_size, region)
    marks = marks or []
    if zoom and (not marks or stage != "display" or region is not None):
        raise render_error("out_of_range", "zoom needs marks, stage display and no region, with one `path`")
    if stage not in PREVIEW_STAGES:
        raise render_error("out_of_range", f"stage must be one of {', '.join(PREVIEW_STAGES)}")
    if stage != "display":
        if marks:
            raise render_error("out_of_range", "marks go with stage display")
        return render_stage_view(session, path, stage, max_size, region, output, overwrite)
    check_marks(marks, None, render_error)
    dest = check_output(output, Path(path), overwrite) if output is not None else None
    warnings: list[str] = []
    tiles: list[ZoomTile] | None = None
    with session.image(path) as wp:
        # -f resizes before processing, which approximates sharpening and
        # local effects: only worth it for a whole-image preview that fits the
        # user's fast-export box (-f would shrink anything larger into it).
        fast = region is None and max_size <= artdir.fast_export_box(session.config_dir)
        crop_text = None
        shown = session.frame_of(wp)
        if region is not None:
            shown = region_rect(shown, x=region.x, y=region.y, w=region.w, h=region.h)
            crop_text = crop_profile(shown)
        if marks:
            whole = session.whole_frame(wp)
            check_marks(marks, (whole.w, whole.h), render_error)
        if zoom:
            rendered = render_jpeg(
                session, wp.image, keyfile.dumps(wp.changes.profile), max(shown.w, shown.h), fast=False
            )
            tiles = zoom_rendering(rendered, marks, shown)
        else:
            rendered = render_jpeg(
                session, wp.image, keyfile.dumps(wp.changes.profile), max_size, fast=fast, crop_text=crop_text
            )
            if marks:
                warnings = mark_rendering(rendered, marks, shown)
    if dest is not None:
        place_output(rendered, dest, overwrite)
        rendered = dest
    width, height = jpeg_size(rendered)
    return Preview(
        path=str(rendered), max_size=max_size, width=width, height=height,
        shown=None if zoom else shown_of(shown), tiles=tiles, warnings=warnings,
    )  # fmt: skip


def render_stage_view(
    session: RenderSession,
    path: str,
    stage: str,
    max_size: int,
    region: Region | None,
    output: str | None,
    overwrite: bool,
) -> Preview:
    """The film pipeline's own data at ``stage`` as a JPEG (art-cli ``-X``
    with an output file): converted through the sRGB curve, no colour
    management, crop applied; ``region`` is a fraction of the cropped frame."""
    dest = check_output(output, Path(path), overwrite) if output is not None else None
    box = None if region is None else (region.x, region.y, min(region.x + region.w, 1.0), min(region.y + region.h, 1.0))
    with session.image(path) as wp:
        shown = session.frame_of(wp)
        if region is not None:
            shown = region_rect(shown, x=region.x, y=region.y, w=region.w, h=region.h)
        profile = session.previews.new_file("profile", ".arp")
        rendered = session.previews.new_file("stage", ".jpg")
        try:
            profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
            args = stage_stats_args(wp.image, profile, stage, 2, max_size, box)
            at = args.index("-c")
            args[at:at] = ["-o", str(rendered)]
            try:
                session.cli.run(args)
            except ArtCliTimeout as e:
                raise render_error("timeout", str(e)) from e
            except ArtCliError as e:
                if e.returncode == -1 and looks_like_help(str(e)):
                    raise render_error("unsupported", UNSUPPORTED_STAGE) from e
                raise render_error("render_failed", str(e)) from e
            if not rendered.exists():
                raise render_error("unsupported", UNSUPPORTED_STAGE)
        except BaseException:
            rendered.unlink(missing_ok=True)
            raise
        finally:
            profile.unlink(missing_ok=True)
    if dest is not None:
        place_output(rendered, dest, overwrite)
        rendered = dest
    width, height = jpeg_size(rendered)
    return Preview(path=str(rendered), max_size=max_size, width=width, height=height, shown=shown_of(shown))


def shown_of(area: Rect) -> dict[str, int]:
    """``area`` as the {x, y, w, h} a result carries (a plain object keeps the schema small)."""
    return {"x": area.x, "y": area.y, "w": area.w, "h": area.h}


def jpeg_size(path: Path) -> tuple[int | None, int | None]:
    """The pixel size of the JPEG ``path``; (None, None) if it can't be read
    (art-cli writes a decodable JPEG; a stand-in that doesn't has no size)."""
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None, None


ZOOM_TILE = 320
"""Side in pixels of one tile of a zoom sheet."""
ZOOM_COLUMNS = 4
ZOOM_GAP = 6
ZOOM_CAPTION = 20
ZOOM_MIN_WINDOW = 160
ZOOM_WINDOW_PER_SIZE = 8


def zoom_window(mark: Mark, area: Rect) -> Rect:
    """The frame pixels a mark's tile shows: a square of about
    ``max(8 * size, 160)`` centred on the mark, moved (then cut) to lie in
    ``area``."""
    side = min(max(ZOOM_WINDOW_PER_SIZE * mark.size, ZOOM_MIN_WINDOW), area.w, area.h)
    x = min(max(mark.x - side // 2, area.x), area.x + area.w - side)
    y = min(max(mark.y - side // 2, area.y), area.y + area.h - side)
    return Rect(x, y, side, side)


def zoom_rendering(rendered: Path, marks: list[Mark], area: Rect) -> list[ZoomTile]:
    """Replace the full-size render ``rendered`` of ``area`` by a sheet of
    tiles, one per mark in request order, each an enlarged window around the
    mark with its square drawn and a caption under it (upscaled with nearest
    neighbour so single pixels stay visible); the tiles' places. A mark centre
    outside ``area`` is ``out_of_range``; an unreadable render is
    ``render_failed``; the file is removed on either."""
    for number, mark in enumerate(marks, 1):
        if not (area.x <= mark.x < area.x + area.w and area.y <= mark.y < area.y + area.h):
            rendered.unlink(missing_ok=True)
            raise render_error(
                "out_of_range",
                f"mark {number} ({mark.x}, {mark.y}) is outside the previewed area "
                f"(x {area.x}, y {area.y}, w {area.w}, h {area.h} in frame pixels)",
            )
    try:
        with Image.open(rendered) as opened:
            source = opened.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        rendered.unlink(missing_ok=True)
        raise render_error("render_failed", f"cannot read the image: {e}") from e
    across, down = source.width / area.w, source.height / area.h
    columns = min(ZOOM_COLUMNS, len(marks))
    rows = -(-len(marks) // columns)
    cell_h = ZOOM_TILE + ZOOM_CAPTION
    sheet = Image.new(
        "RGB",
        (columns * ZOOM_TILE + (columns + 1) * ZOOM_GAP, rows * cell_h + (rows + 1) * ZOOM_GAP),
        (40, 40, 40),
    )
    font = ImageFont.load_default(size=14)
    draw = ImageDraw.Draw(sheet)
    tiles: list[ZoomTile] = []
    for index, (mark, label) in enumerate(zip(marks, labels_of(marks), strict=True)):
        window = zoom_window(mark, area)
        box = (
            round((window.x - area.x) * across), round((window.y - area.y) * down),
            round((window.x - area.x + window.w) * across), round((window.y - area.y + window.h) * down),
        )  # fmt: skip
        piece = source.crop(box)
        grow = ZOOM_TILE > piece.width
        piece = piece.resize((ZOOM_TILE, ZOOM_TILE), Image.NEAREST if grow else Image.BOX)
        draw_marks(piece, [mark.model_copy(update={"label": label})], window)
        left = ZOOM_GAP + (index % columns) * (ZOOM_TILE + ZOOM_GAP)
        top = ZOOM_GAP + (index // columns) * (cell_h + ZOOM_GAP)
        sheet.paste(piece, (left, top))
        draw.text(
            (left, top + ZOOM_TILE + 2),
            f"{label}: ({mark.x},{mark.y}) {mark.size}px  x{window.x} y{window.y} w{window.w}",
            fill=(255, 255, 255), font=font,
        )  # fmt: skip
        tiles.append(ZoomTile(label=label, window=shown_of(window), left=left, top=top, size=ZOOM_TILE))
    try:
        save_jpeg(sheet, rendered)
    except OSError as e:
        rendered.unlink(missing_ok=True)
        raise render_error("render_failed", str(e)) from e
    return tiles


def mark_rendering(rendered: Path, marks: list[Mark], shown: Rect) -> list[str]:
    """Draw ``marks`` on the rendered preview ``rendered``, which shows the
    ``shown`` area of the frame; its warnings. A rendering that can't be read
    or marked is ``render_failed`` and the file is removed."""
    try:
        return mark_file(rendered, marks, shown)
    except (ValueError, OSError) as e:
        rendered.unlink(missing_ok=True)
        raise render_error("render_failed", str(e)) from e
