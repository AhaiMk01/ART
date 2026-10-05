"""Numbered boxes drawn on a preview, at frame-pixel positions, so a caller can
see where the spots it is about to sample (or that ``suggest_neutrals``
proposed) sit in the picture.

Pure Pillow, no ART and no MCP: both servers' ``render_preview`` and the
Render server's ``suggest_neutrals`` draw with this.

A mark is the square ``sample_spots`` would read (``size`` frame pixels, centred
on ``x``, ``y``). It is drawn as a ring of light pixels just outside the square
and a ring of dark ones outside that, so it shows on dark and on light content
and leaves the pixels it marks as they are, and a tab with the label (the
number in request order, or the caller's ``label``) in a dark fill with a light
edge, on its top left corner. The square is as many preview pixels as its
frame pixels come to (at least one), so its centre is where the spot is,
however small the preview.
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO, Any

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict

from art_mcp.compactschema import compact_model_schema
from art_mcp.render.artcli import Rect
from art_mcp.sampling import DEFAULT_SIZE, MAX_SIZE, MIN_SIZE

MAX_MARKS = 64
MAX_LABEL = 4
"""Characters in a label."""

LIGHT = (255, 255, 255)
DARK = (0, 0, 0)
JPEG_QUALITY = 92
"""Of a marked picture: it was a JPEG (or PNG) already, so keep what is left."""
SHAPE_TOLERANCE = 0.02
"""How far the scale of the picture may differ between its width and its
height before the shape is called wrong (rounding to whole pixels is always
allowed for)."""


class Mark(BaseModel):
    """A box on the preview around the `size` x `size` square of frame pixels centred on `x`, `y`."""

    model_config = ConfigDict(json_schema_extra=compact_model_schema, coerce_numbers_to_str=True)

    x: int
    y: int
    size: int = DEFAULT_SIZE
    """Frame pixels, 2 to 256: the square `sample_spots` reads."""
    label: str | None = None
    """At most 4 characters; the number in request order when not given."""


def check_marks(marks: Sequence[Mark], frame: tuple[int, int] | None, error: Callable[[Any, str], Exception]) -> None:
    """Raise ``error("out_of_range", why)`` when the request is out of range:
    more than ``MAX_MARKS``, a ``size`` or ``label`` outside what a mark takes,
    and, when the ``frame`` size is known, a centre outside it. Call once
    without the frame for the cheap checks, then again with it."""
    if len(marks) > MAX_MARKS:
        raise error("out_of_range", f"give at most {MAX_MARKS} marks, not {len(marks)}")
    for number, mark in enumerate(marks, 1):
        if not MIN_SIZE <= mark.size <= MAX_SIZE:
            raise error("out_of_range", f"mark {number}: size must be {MIN_SIZE} to {MAX_SIZE}, not {mark.size}")
        if mark.label is not None and len(mark.label) > MAX_LABEL:
            raise error("out_of_range", f"mark {number}: a label is at most {MAX_LABEL} characters")
        if frame is not None and not (0 <= mark.x < frame[0] and 0 <= mark.y < frame[1]):
            raise error(
                "out_of_range", f"mark {number} ({mark.x}, {mark.y}) is outside the {frame[0]} x {frame[1]} frame"
            )


def labels_of(marks: Sequence[Mark]) -> list[str]:
    """What each mark's tab says: its ``label``, else its number (1..n in request order)."""
    return [mark.label or str(number) for number, mark in enumerate(marks, 1)]


def scaled(twice: int, pixels: int, extent: int) -> int:
    """``twice / 2`` frame pixels in a picture of ``pixels`` for ``extent`` frame pixels,
    rounded to the nearest whole pixel (a half rounds up), in integers."""
    return (twice * pixels + extent) // (2 * extent)


def square_in(mark: Mark, area: Rect, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """The mark's square as pixels [left, right) x [top, bottom) of a picture of
    ``size`` showing ``area`` of the frame, at least one pixel each way; None
    when no part of the square is in the area."""
    width, height = size
    left, top = 2 * (mark.x - area.x) - mark.size, 2 * (mark.y - area.y) - mark.size
    if left + 2 * mark.size <= 0 or left >= 2 * area.w or top + 2 * mark.size <= 0 or top >= 2 * area.h:
        return None
    x0, y0 = scaled(left, width, area.w), scaled(top, height, area.h)
    x1 = max(x0 + 1, scaled(left + 2 * mark.size, width, area.w))
    y1 = max(y0 + 1, scaled(top + 2 * mark.size, height, area.h))
    return x0, x1, y0, y1


def shape_warning(size: tuple[int, int], area: Rect) -> str | None:
    """A warning when a picture of ``size`` cannot be the ``area`` of the
    frame (the scale across differs from the scale down), else None."""
    width, height = size
    across, down = width / area.w, height / area.h
    if abs(across - down) / max(across, down) > max(SHAPE_TOLERANCE, 1 / min(width, height)):
        return (
            f"the picture ({width} x {height}) is not the shape of the area it should show ({area.w} x {area.h} "
            "frame pixels): the marks may be misplaced"
        )
    return None


def draw_marks(image: Image.Image, marks: Sequence[Mark], area: Rect) -> list[str]:
    """Draw ``marks`` on ``image`` (RGB, changed in place), which shows
    ``area`` = (x, y, w, h) of the frame. A mark whose square lies wholly
    outside the area is not drawn; the warnings say so (and if the picture is
    not the area's shape)."""
    width, height = image.size
    longest = max(width, height)
    ring = max(1, int(longest / 1000 + 0.5))
    font_size = min(24, max(11, round(longest / 80)))
    padding = max(2, font_size // 5)
    font = ImageFont.load_default(size=font_size)
    draw = ImageDraw.Draw(image)

    squares = [square_in(mark, area, image.size) for mark in marks]
    for x0, x1, y0, y1 in filter(None, squares):
        draw.rectangle((x0 - ring, y0 - ring, x1 - 1 + ring, y1 - 1 + ring), outline=LIGHT, width=ring)
        draw.rectangle((x0 - 2 * ring, y0 - 2 * ring, x1 - 1 + 2 * ring, y1 - 1 + 2 * ring), outline=DARK, width=ring)
    for box, label in zip(squares, labels_of(marks), strict=True):
        if box is None:
            continue
        x0, x1, y0, y1 = box
        ink = draw.textbbox((0, 0), label, font=font)
        tab_w, tab_h = ink[2] - ink[0] + 2 * padding + 2, ink[3] - ink[1] + 2 * padding + 2
        tab_x = max(0, min(x0 - 2 * ring, width - tab_w))
        # on the box's top left corner, else below it, else inside it
        tab_y = y0 - 2 * ring - tab_h
        if tab_y < 0:
            tab_y = y1 + 2 * ring
            if tab_y + tab_h > height:
                tab_y = max(0, y0)
        draw.rectangle((tab_x, tab_y, tab_x + tab_w - 1, tab_y + tab_h - 1), fill=DARK, outline=LIGHT)
        draw.text((tab_x + 1 + padding - ink[0], tab_y + 1 + padding - ink[1]), label, fill=LIGHT, font=font)

    warnings = []
    outside = [number for number, box in enumerate(squares, 1) if box is None]
    if outside:
        many = len(outside) != 1
        warnings.append(
            f"{len(outside)} of {len(marks)} mark{'s' if len(marks) != 1 else ''} ({', '.join(map(str, outside))} "
            f"in request order) {'lie' if many else 'lies'} outside the previewed area (x {area.x}, y {area.y}, "
            f"w {area.w}, h {area.h} in frame pixels) and {'are' if many else 'is'} not drawn"
        )
    shape = shape_warning(image.size, area)
    if shape:
        warnings.append(shape)
    return warnings


def save_jpeg(image: Image.Image, dest: Path | IO[bytes]) -> None:
    """``image`` as a JPEG (no chroma subsampling, so the thin rings stay
    clean), with its colour profile if it had one."""
    image.save(dest, "JPEG", quality=JPEG_QUALITY, subsampling=0, icc_profile=image.info.get("icc_profile"))


def mark_file(path: Path, marks: Sequence[Mark], area: Rect) -> list[str]:
    """Draw ``marks`` on the image file ``path`` (a preview of ``area`` of the
    frame), which is replaced by a JPEG of the same size; returns the warnings
    of ``draw_marks``. ValueError, and the file untouched, if it can't be read
    as an image."""
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise ValueError(f"cannot read the image: {e}") from e
    warnings = draw_marks(image, marks, area)
    save_jpeg(image, path)
    return warnings
