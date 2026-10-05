"""Composing a contact sheet: thumbnails in a labelled grid.

Pure Pillow, no ART and no MCP: the Render server's ``contact_sheet`` renders
the thumbnails and builds on this.
"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BACKGROUND = (38, 38, 38)
"""Neutral dark grey, so it doesn't colour the judgement of the frames."""
TEXT = (210, 210, 210)
MISSING = (70, 52, 52)
PAD = 8
FONT_SIZE = 14
LABEL_HEIGHT = FONT_SIZE + 8
HEADER_HEIGHT = FONT_SIZE + 2 * PAD


@dataclass(frozen=True)
class Cell:
    label: str
    """Shown under the frame (the file name)."""
    thumbnail: Path | Image.Image | None
    """The frame, as a file or an image; None draws a placeholder with ``note``."""
    note: str = ""


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int


def fit_text(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, text: str, width: int) -> str:
    """``text`` shortened with an ellipsis to fit ``width`` pixels."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def load(thumbnail: Path | Image.Image) -> Image.Image:
    """A copy of the frame as RGB."""
    if isinstance(thumbnail, Image.Image):
        return thumbnail.convert("RGB")
    with Image.open(thumbnail) as opened:
        return opened.convert("RGB")


def side_by_side(left: Image.Image, right: Image.Image, size: int) -> Image.Image:
    """Two frames, each fitted into a ``size`` square and centred, with a gap
    between: one frame for ``compose`` to place in a cell ``2 * size + PAD``
    wide."""
    fitted = [load(frame) for frame in (left, right)]
    for frame in fitted:
        frame.thumbnail((size, size))
    height = max(frame.height for frame in fitted)
    pair = Image.new("RGB", (2 * size + PAD, height), BACKGROUND)
    for i, frame in enumerate(fitted):
        pair.paste(frame, (i * (size + PAD) + (size - frame.width) // 2, (height - frame.height) // 2))
    return pair


def compose(
    cells: list[Cell],
    columns: int,
    thumb_size: int,
    title: str = "",
    cell_width: int | None = None,
) -> tuple[Image.Image, list[Box | None]]:
    """The sheet and, per cell, where its frame sits on it (None for a
    placeholder). A frame is fitted into ``cell_width`` (default
    ``thumb_size``) by ``thumb_size`` and centred in its cell, which is as
    high as the tallest frame, with its label underneath; ``columns`` cells
    per row (fewer when there are fewer cells), and ``title`` on a line above
    the grid."""
    font = ImageFont.load_default(size=FONT_SIZE)
    cell_w = cell_width or thumb_size
    frames = [load(cell.thumbnail) if cell.thumbnail is not None else None for cell in cells]
    for frame in frames:
        if frame is not None:
            frame.thumbnail((cell_w, thumb_size))
    frame_h = max((frame.height for frame in frames if frame is not None), default=thumb_size)
    columns = max(1, min(columns, len(cells)))
    rows = -(-len(cells) // columns)
    header = HEADER_HEIGHT if title else 0
    cell_h = frame_h + LABEL_HEIGHT
    sheet = Image.new(
        "RGB",
        (PAD + columns * (cell_w + PAD), header + PAD + rows * (cell_h + PAD)),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(sheet)
    if title:
        draw.text((PAD, PAD), fit_text(draw, font, title, sheet.width - 2 * PAD), fill=TEXT, font=font)

    boxes: list[Box | None] = []
    for i, (cell, frame) in enumerate(zip(cells, frames, strict=True)):
        x0 = PAD + (i % columns) * (cell_w + PAD)
        y0 = header + PAD + (i // columns) * (cell_h + PAD)
        box = None
        if frame is not None:
            box = Box(x0 + (cell_w - frame.width) // 2, y0 + (frame_h - frame.height) // 2, *frame.size)
            sheet.paste(frame, (box.x, box.y))
        else:
            draw.rectangle((x0, y0, x0 + cell_w - 1, y0 + frame_h - 1), fill=MISSING)
            note = fit_text(draw, font, cell.note, cell_w - 2 * PAD)
            draw.text((x0 + cell_w // 2, y0 + frame_h // 2), note, fill=TEXT, font=font, anchor="mm")
        draw.text((x0, y0 + frame_h + 4), fit_text(draw, font, cell.label, cell_w), fill=TEXT, font=font)
        boxes.append(box)
    return sheet, boxes
