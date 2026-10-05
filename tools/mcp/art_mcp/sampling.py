"""Spot sampling and image statistics, shared by both servers.

Pure code: spot validation, the spots result models, parsing of art-cli's
``ART-SPOTS`` line, and the statistics of an 8-bit PNG. Running art-cli or
talking to ART stays in the servers.
"""

import io
import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

SPACES = ("working", "input")
MIN_SIZE, MAX_SIZE = 2, 256
MAX_SPOTS = 16
DEFAULT_SIZE = 32
SPOTS_PREFIX = "ART-SPOTS "

UNSUPPORTED_SPOTS = (
    "needs an ART build with spot sampling (the fork); point --art-dir/ART_DIR at it"
)

SKILLS_POINTER = (
    "Workflows for film scans: see the film-negative and faded-slide skills "
    "(tools/mcp/skills)."
)

SAMPLE_SPOTS_DOC = """Read what ART's own pickers read: linear values of square spots of the image.

`spots`: 1 to 16 {x, y} in whole pixels of the frame (the raw image after
coarse rotation and the raw border; the same coordinates as [Crop]), each
the centre of a `size` x `size` square (2 to 256). Outside the frame is
out_of_range. `space`: "working" = the working profile's working space,
"input" = camera space.

Mapping a preview pixel (px, py) to the frame: a Render whole-image preview
shows the crop when one is enabled, so x = crop.x + px * crop.w / preview_w
(no crop: px * frame_w / preview_w; same for y); a Live preview always shows
the whole frame.

Returns the frame `width`/`height` and per spot `avg` and `max` as [r, g, b]:
linear, 0..65535, white-balanced, taken before any film inversion.

Render server: needs an ART build with spot sampling (else `unsupported`).
Live server: samples the open editor's profile, unsaved edits included.

""" + SKILLS_POINTER


def _spot_problem(
    spots: list[tuple[int, int]], size: int, space: str, frame: tuple[int, int] | None
) -> str | None:
    """Why this request is out of range, or None. ``frame`` is the frame size
    when known."""
    if not MIN_SIZE <= size <= MAX_SIZE:
        return f"size must be {MIN_SIZE} to {MAX_SIZE}"
    if space not in SPACES:
        return f"space must be one of {', '.join(SPACES)}, not {space!r}"
    if not 1 <= len(spots) <= MAX_SPOTS:
        return f"give 1 to {MAX_SPOTS} spots, not {len(spots)}"
    if frame is not None:
        for x, y in spots:
            if not (0 <= x < frame[0] and 0 <= y < frame[1]):
                return f"spot ({x}, {y}) is outside the {frame[0]} x {frame[1]} frame"
    return None


def check_spots(
    spots: list[tuple[int, int]],
    size: int,
    space: str,
    frame: tuple[int, int] | None,
    error: Callable[[Any, str], Exception],
) -> None:
    """Raise ``error("out_of_range", why)`` when the request is out of range.
    ``frame`` is the frame size when known; call once without it for the cheap
    checks, then again with it."""
    problem = _spot_problem(spots, size, space, frame)
    if problem:
        raise error("out_of_range", problem)


def check_stats_size(max_size: int, limit: int, error: Callable[[Any, str], Exception]) -> None:
    """Raise ``error("out_of_range", ...)`` unless ``max_size`` is 1 to ``limit``."""
    if not 1 <= max_size <= limit:
        raise error("out_of_range", f"max_size must be 1 to {limit}")


class Spot(BaseModel):
    """A whole pixel of the frame."""

    x: int
    y: int


class SpotValues(BaseModel):
    x: int
    y: int
    avg: list[float]
    """[r, g, b], linear 0..65535."""
    max: list[float]
    """[r, g, b], the largest value in the square."""


class SpotSamples(BaseModel):
    width: int
    height: int
    """The frame's size, the pixels `x`/`y` address."""
    space: str
    size: int
    spots: list[SpotValues]


def parse_spots_output(text: str, size: int, space: str) -> SpotSamples | None:
    """The result from art-cli's output: None when it has no ``ART-SPOTS``
    line (a build without spot sampling); ValueError when the line is
    malformed."""
    for line in text.splitlines():
        if line.startswith(SPOTS_PREFIX):
            try:
                data = json.loads(line[len(SPOTS_PREFIX):])
                return SpotSamples.model_validate({"space": space, "size": size, **data})
            except (ValueError, TypeError, ValidationError) as e:
                raise ValueError(f"malformed {SPOTS_PREFIX.strip()} line: {line[:200]!r}") from e
    return None


def parse_spots_reply(reply: Any, size: int, space: str) -> SpotSamples:
    """The result from the control channel's reply; ValueError if it isn't
    the documented shape."""
    if not isinstance(reply, dict):
        raise ValueError("not an object")
    try:
        return SpotSamples.model_validate({"space": space, "size": size, **reply})
    except ValidationError as e:
        raise ValueError(str(e)) from e


# -- statistics ---------------------------------------------------------------

IMAGE_STATS_DOC = """Per channel r, g, b and lum (0.2126 R + 0.7152 G + 0.0722 B of the 8-bit
values): `mean`, `clipped_high` / `clipped_low` (fraction of pixels at 255 /
0), `percentiles` (0.1, 1, 5, 50, 95, 99, 99.9 %), and with `histogram` the
256 counts; plus the width/height analysed. `max_size`: long edge, 1 to 2576.
Anything the image shows counts, including a scanner holder or border: crop
first (Render applies the working profile's crop; Live's preview is
uncropped). """ + SKILLS_POINTER

PERCENTILES = ("0.1", "1", "5", "50", "95", "99", "99.9")
_PERMILLE = {p: round(float(p) * 10) for p in PERCENTILES}
LUMA = (0.2126, 0.7152, 0.0722)


class ChannelStats(BaseModel):
    mean: float
    """Mean of the 8-bit values (0..255), 2 decimals."""
    clipped_high: float
    """Fraction of pixels at 255."""
    clipped_low: float
    """Fraction of pixels at 0."""
    percentiles: dict[str, int]
    """Value (0..255) at 0.1, 1, 5, 50, 95, 99, 99.9 % (nearest rank)."""
    histogram: list[int] | None = None
    """256 counts, only when asked."""


class ImageStats(BaseModel):
    width: int
    height: int
    """The rendered image's size."""
    r: ChannelStats
    g: ChannelStats
    b: ChannelStats
    lum: ChannelStats
    """0.2126 R + 0.7152 G + 0.0722 B per pixel, rounded to the nearest 8-bit
    value (so it bins like the other channels)."""


def channel_stats(counts: list[int], histogram: bool) -> ChannelStats:
    """Statistics from a 256-bin histogram. A percentile is the smallest value
    whose cumulative count reaches ceil(p/100 * N) (nearest rank)."""
    total = sum(counts)
    percentiles: dict[str, int] = {}
    for name, permille in _PERMILLE.items():
        rank = max(1, -(-permille * total // 1000))
        running = 0
        for value, n in enumerate(counts):
            running += n
            if running >= rank:
                percentiles[name] = value
                break
    return ChannelStats(
        mean=round(sum(v * n for v, n in enumerate(counts)) / total, 2),
        clipped_high=counts[255] / total,
        clipped_low=counts[0] / total,
        percentiles=percentiles,
        histogram=counts if histogram else None,
    )


def image_stats(png: Path | bytes, histogram: bool = False) -> ImageStats:
    """Statistics of an 8-bit image file (any mode Pillow can turn into RGB).
    Raises ValueError if it can't be read or has no pixels."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(png) if isinstance(png, bytes) else png) as opened:
            rgb = opened.convert("RGB")
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read the rendered image: {e}") from e
    width, height = rgb.size
    if width * height == 0:
        raise ValueError("the rendered image has no pixels")
    counts = rgb.histogram()
    lum = rgb.convert("L", (*LUMA, 0)).histogram()
    r, g, b = (channel_stats(counts[i * 256 : (i + 1) * 256], histogram) for i in range(3))
    return ImageStats(
        width=width, height=height, r=r, g=g, b=b, lum=channel_stats(lum, histogram)
    )

