"""Candidate spots for neutral (grey/white) references of any image, for
``suggest_neutrals``.

Pure code: the scoring and selection of cells of a rendered image, and the
result models. Rendering the preview and mapping it to the frame stays in
``render/neutrals_ops.py``.

The rule (spec 4.3): the area (the crop, else the whole frame) is cut into
square cells of about ``size`` frame pixels; a cell is scored on the 8-bit
rendering of the working profile by

- ``flatness``: the standard deviation of its luminance over the mean;
- ``saturation``: HSV saturation (max - min over max) of its mean colour;

and ``cost = saturation + flatness`` (both are unit-less fractions, lower is
better). Cells that are near black or near clipped, too textured or too
coloured, or in the outer border are never suggested. Of the rest, ``count``
are taken so that they spread over the luminance range (bands, the best of
each first) and over the frame (a minimum distance), returned dark to light.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from operator import mul
from typing import Any

from PIL import Image
from pydantic import BaseModel

from art_mcp.sampling import LUMA, MAX_SIZE, MAX_SPOTS, MIN_SIZE

SUGGEST_NEUTRALS_DOC = """Propose flat, low-saturation, mid-level patches of the current rendering of the image, as
candidates for white balance, colour calibration or ratio fitting. A PRE-FILTER, not an oracle: whether a patch is
really neutral (grey/white) depends on its MATERIAL (white paint, bare metal, concrete: yes; natural stone, dyed
fabric, foliage, glass: no), which only looking can tell. This narrows where to look; you still choose by material
and check with `sample_spots`.

It renders the working profile (a mid-size preview, crop applied) and cuts the crop (else the whole frame) into
cells of about `size` frame pixels. A cell is a candidate when it is flat (`flatness`: the standard deviation of
its luminance over its mean, lower is flatter), little coloured in the rendering (`saturation`: HSV, lower is
more neutral), neither near black nor near clipped, and away from the border. Saturation only means something
once the rendering is roughly colour-correct (neutral things look grey): make it so first, else the result is
approximate. Without a crop the outer 10% is skipped and a warning says a border or mount of the picture may
still be in the frame: crop first.

Returns up to `count` (1 to 16) candidates, spread over the luminance range and over the frame, sorted dark to
light: `x`, `y` (the centre, whole pixels of the frame: the coordinates `sample_spots` and `crop` use, and
the candidates go to `sample_spots` as its `spots` unchanged), `level` (the cell's luminance, 0..255),
`saturation`, `flatness`, `why`. Also the analysed `area` [x, y, w, h], the `size` to sample with, the `cell` side
(larger than `size` when a big frame and a small `size` would give cells of a pixel or two) and `warnings`.

Workflows that use it: see the skills (tools/mcp/skills)."""

DEFAULT_COUNT = 16
MAX_COUNT = MAX_SPOTS
"""What one ``sample_spots`` call takes."""
ANALYSIS_SIZE = 1600
"""Long edge, in pixels, of the preview that is analysed."""
MIN_CELL_PX = 4
"""A cell is at least this many preview pixels wide: its texture is measured
over a few pixels, so a small ``size`` on a big frame is enlarged."""

LEVEL_MIN, LEVEL_MAX = 16, 240
"""A usable cell: its mean level in every channel (8-bit) lies in this range,
i.e. it is not near black and not near clipped."""
FLAT_MAX = 0.06
SATURATION_MAX = 0.10
"""A usable cell is no more textured / coloured than this: about twice what
still counts as neutral (a 5% difference between channels is a saturation of
0.05); the ranking by ``cost`` does the rest."""

BAND_SLOTS = 2
"""Candidates taken from each luminance band (the band count is
``count // BAND_SLOTS``), best ``cost`` first."""
SEPARATION = 0.10
"""Minimum distance between two candidates, as a fraction of the area's
longer side; halved (then quartered, then dropped) when too few cells would
otherwise be left."""
BORDER_CROPPED = 0.03
BORDER_UNCROPPED = 0.10
"""Cells whose centre lies in this outer fraction of the area are left out:
a little inside a crop, more when there is none (a border or mount of the
picture is then in the frame)."""


@dataclass(frozen=True)
class Cell:
    col: int
    row: int
    level: float
    """Mean luminance, 0..255 (the rendering's 8-bit values)."""
    low: float
    high: float
    """The smallest and the largest of the mean r, g, b."""
    saturation: float
    flatness: float


def saturation_of(r: float, g: float, b: float) -> float:
    """HSV saturation, 0 (grey) .. 1."""
    high = max(r, g, b)
    return 0.0 if high <= 0 else (high - min(r, g, b)) / high


def cost(cell: Cell) -> float:
    """What the ranking minimises: ``saturation + flatness``."""
    return cell.saturation + cell.flatness


def describe(cell: Cell) -> str:
    """The short ``why`` of a candidate: flatness, tint, tone."""
    texture = "flat" if cell.flatness <= 0.04 else "some texture"
    tint = "neutral" if cell.saturation <= 0.04 else "near-neutral" if cell.saturation <= 0.12 else "tinted"
    tone = "dark" if cell.level < 85 else "mid" if cell.level < 170 else "light"
    return f"{texture}, {tint}, {tone}"


def measure_cells(image: Image.Image, area_w: int, area_h: int, cell: int) -> tuple[int, int, list[Cell]]:
    """Cut a rendering of an ``area_w`` x ``area_h`` area of the frame into
    squares of ``cell`` frame pixels from its top left corner (the strip that
    doesn't fill a square is not analysed) and measure each. Returns the
    columns, rows and the cells. ValueError if not one square fits."""
    cols, rows = area_w // cell, area_h // cell
    if cols < 1 or rows < 1:
        raise ValueError(f"size {cell} does not fit the {area_w} x {area_h} area")
    width, height = image.size
    scale_x, scale_y = width / area_w, height / area_h
    side = max(2, round(cell * min(scale_x, scale_y)))
    # Resampled so that a cell is exactly `side` x `side` pixels.
    box = (0, 0, min(width, cols * cell * scale_x), min(height, rows * cell * scale_y))
    work = image.convert("RGB").resize((cols * side, rows * side), Image.Resampling.BOX, box=box)
    luma = work.convert("L", (*LUMA, 0)).tobytes()
    colours = work.resize((cols, rows), Image.Resampling.BOX).tobytes()

    line_width, count = cols * side, side * side
    cells: list[Cell] = []
    for row in range(rows):
        total = [0] * cols
        squares = [0] * cols
        for y in range(row * side, (row + 1) * side):
            line = luma[y * line_width : (y + 1) * line_width]
            for col in range(cols):
                part = line[col * side : (col + 1) * side]
                total[col] += sum(part)
                squares[col] += sum(map(mul, part, part))
        for col in range(cols):
            mean = total[col] / count
            deviation = math.sqrt(max(0.0, squares[col] / count - mean * mean))
            at = 3 * (row * cols + col)
            r, g, b = colours[at], colours[at + 1], colours[at + 2]
            cells.append(
                Cell(col, row, mean, min(r, g, b), max(r, g, b), saturation_of(r, g, b), deviation / max(mean, 1.0))
            )
    return cols, rows, cells


def usable(cell: Cell, cols: int, rows: int, margin: float) -> bool:
    """Not in the border, not near black or clipped, flat and not strongly
    coloured enough to be worth a look."""
    x, y = (cell.col + 0.5) / cols, (cell.row + 0.5) / rows
    return (
        margin <= x <= 1 - margin and margin <= y <= 1 - margin
        and LEVEL_MIN <= cell.low and cell.high <= LEVEL_MAX
        and cell.flatness <= FLAT_MAX and cell.saturation <= SATURATION_MAX
    )  # fmt: skip


def choose_cells(cells: list[Cell], cols: int, rows: int, count: int, margin: float) -> list[Cell]:
    """Up to ``count`` usable cells, in the order picked: the best (lowest
    ``cost``, then top to bottom, left to right) cell of each luminance band
    that keeps ``SEPARATION`` from those already picked, a second round, then
    the best of the rest; the separation is relaxed if that leaves too few."""
    pool = sorted((c for c in cells if usable(c, cols, rows, margin)), key=lambda c: (cost(c), c.row, c.col))
    if not pool or count < 1:
        return []
    low, high = min(c.level for c in pool), max(c.level for c in pool)
    bands = max(1, count // BAND_SLOTS)

    def band(c: Cell) -> int:
        return 0 if high <= low else min(bands - 1, int((c.level - low) / (high - low) * bands))

    by_band: list[list[Cell]] = [[] for _ in range(bands)]
    for c in pool:
        by_band[band(c)].append(c)

    chosen: list[Cell] = []
    taken: set[tuple[int, int]] = set()
    for relax in (1.0, 0.5, 0.25, 0.0):
        gap = (SEPARATION * relax * max(cols, rows)) ** 2

        def pick(candidates: list[Cell], gap: float = gap) -> bool:
            for c in candidates:
                if (c.col, c.row) not in taken and all(
                    (c.col - o.col) ** 2 + (c.row - o.row) ** 2 >= gap for o in chosen
                ):
                    chosen.append(c)
                    taken.add((c.col, c.row))
                    return True
            return False

        for _ in range(BAND_SLOTS):
            for members in by_band:
                if len(chosen) < count:
                    pick(members)
        while len(chosen) < count and pick(pool):
            pass
        if len(chosen) == count:
            break
    return chosen


class NeutralCandidate(BaseModel):
    x: int
    y: int
    """The centre, whole pixels of the frame (what `sample_spots` takes)."""
    level: int
    """The cell's luminance in the rendering, 0..255."""
    saturation: float
    """HSV saturation of the cell's mean colour in the rendering; 0 is grey,
    lower is more neutral."""
    flatness: float
    """Standard deviation of the cell's luminance over its mean; 0 is
    perfectly flat, lower is flatter."""
    why: str


@dataclass(frozen=True)
class Suggestion:
    cell: int
    """The side of the analysed cells, in frame pixels (``size``, or more)."""
    usable: int
    """How many cells were candidates at all."""
    candidates: list[NeutralCandidate]


def suggest_candidates(
    image: Image.Image, area: tuple[int, int, int, int], size: int, count: int, margin: float
) -> Suggestion:
    """The candidates of a rendering ``image`` of ``area`` = (x, y, w, h), in
    frame pixels, of the frame; sorted by ``level``, then ``y``, ``x``.
    ValueError if ``size`` does not fit the area."""
    left, top, width, height = area
    scale = min(image.width / width, image.height / height)
    cell = max(size, math.ceil(MIN_CELL_PX / scale - 1e-9))
    cols, rows, cells = measure_cells(image, width, height, cell)
    chosen = choose_cells(cells, cols, rows, count, margin)
    candidates = [
        NeutralCandidate(
            x=left + c.col * cell + cell // 2,
            y=top + c.row * cell + cell // 2,
            level=round(c.level),
            saturation=round(c.saturation, 3),
            flatness=round(c.flatness, 3),
            why=describe(c),
        )
        for c in chosen
    ]
    candidates.sort(key=lambda c: (c.level, c.y, c.x))
    return Suggestion(cell, sum(1 for c in cells if usable(c, cols, rows, margin)), candidates)


class NeutralCandidates(BaseModel):
    area: list[int]
    """[x, y, w, h] of what was analysed, in frame pixels: the working
    profile's crop, else the whole frame."""
    size: int
    """The spot size to sample the candidates with."""
    cell: int
    """The side of the analysed cells, in frame pixels."""
    candidates: list[NeutralCandidate]
    warnings: list[str] = []


def check_request(count: int, size: int, error: Callable[[Any, str], Exception]) -> None:
    """Raise ``error("out_of_range", ...)`` unless ``count`` is 1 to
    ``MAX_COUNT`` and ``size`` is what ``sample_spots`` takes."""
    if not 1 <= count <= MAX_COUNT:
        raise error("out_of_range", f"count must be 1 to {MAX_COUNT}")
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise error("out_of_range", f"size must be {MIN_SIZE} to {MAX_SIZE}")


def result_warnings(*, cropped: bool, found: int, count: int) -> list[str]:
    """What weakens a result: no crop, too few cells."""
    warnings = []
    if not cropped:
        warnings.append(
            f"no crop: the outer {BORDER_UNCROPPED:.0%} is skipped, but a border or mount of the picture may "
            "still be in the frame; crop first"
        )
    if found < count:
        warnings.append(
            f"only {found} of {count} candidates found: the rest of the area is textured, coloured, too dark or "
            "too light"
        )
    return warnings
