"""Spot sampling and image statistics, shared by both servers.

Pure code: spot validation, the spots result models, parsing of art-cli's
``ART-SPOTS`` line, and the statistics of an 8-bit PNG (with the models and the
tool result that carry them). Running art-cli or talking to ART stays in the
servers.
"""

import io
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Protocol

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, ValidationError, model_serializer

from art_mcp.render.artcli import Rect, region_rect

SPACES = ("working", "input")
MIN_SIZE, MAX_SIZE = 2, 256
MAX_SPOTS = 16
"""The most spots one run takes (art-cli's ``-x``, the control channel's ``sample_spots`` op)."""
MAX_SPOTS_PER_CALL = 64
"""The most the ``sample_spots`` tool takes in one call: the servers run them in runs of ``MAX_SPOTS``."""
DEFAULT_SIZE = 32
SPOTS_PREFIX = "ART-SPOTS "

UNSUPPORTED_SPOTS = (
    "needs an ART build with spot sampling (the fork); point --art-dir/ART_DIR at it"
)

SKILLS_POINTER = (
    "Step-by-step workflows (film negatives, faded slides): see the skills in "
    "tools/mcp/skills."
)

SAMPLE_SPOTS_DOC = """Read what ART's own pickers read: linear values of square spots of the image.

`spots`: 1 to 64 spots per call, each {x, y} in whole pixels of the frame (the
raw image after coarse rotation and the raw border; the same coordinates as
[Crop]), the centre of a `size` x `size` square (2 to 256). Outside the frame
is out_of_range. More than 16 are sampled in several runs but come back as one
result, in request order; if a run fails, so does the call (no partial result)
and the error says which spots it covered. `space`: "working" = the working
profile's working space, "input" = camera space.

Mapping a preview pixel (px, py) to the frame: a Render whole-image preview
shows the crop when one is enabled, so x = crop.x + px * crop.w / preview_w
(no crop: px * frame_w / preview_w; same for y); a Live preview always shows
the whole frame. To see where spots sit instead, `render_preview(marks=[...])`
draws them on a preview.

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
    if not 1 <= len(spots) <= MAX_SPOTS_PER_CALL:
        return f"give 1 to {MAX_SPOTS_PER_CALL} spots, not {len(spots)}"
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


def spot_runs(count: int) -> list[range]:
    """Which of ``count`` spots go in each run: consecutive index ranges of at
    most ``MAX_SPOTS``, in request order."""
    return [range(start, min(start + MAX_SPOTS, count)) for start in range(0, count, MAX_SPOTS)]


def merge_samples(parts: list[SpotSamples]) -> SpotSamples:
    """One result from the runs' results, in run order: the first one's frame,
    space and size, every run's spots."""
    return parts[0].model_copy(update={"spots": [spot for part in parts for spot in part.spots]})


def covering(run: range, count: int) -> str:
    """Which spots (numbered from 1, as the caller counts them) a failed run
    covered, for the end of its error message."""
    return f"spots {run.start + 1} to {run.stop} of {count}; no result returned"


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
values): `clipped_high` / `clipped_low` (fraction of pixels at 255 / 0) and
`percentiles`. `detail`: "compact" (percentiles 0.1, 50, 99.9 %; about 450
characters), "standard" (default for one `path`: adds `mean` and percentiles 1,
5, 95, 99; about 700), "full" (adds `std`, `min` / `max` (lowest / highest value
that occurs) and `mode` (most frequent value, the lowest on a tie)). `bins` (8,
16, 32 or 64) adds per channel `bins`: the fraction of pixels in that many equal
groups of values, dark to light; 16 shows what the percentiles don't (a clipped
shoulder, a second hump, a flat toe). `histogram` adds the 256 raw counts. A
field with nothing to say (`bins`, `histogram`, `region`) is left out. `paths`
(1 to 50, instead of `path`): many images in one call, the other arguments the
same for all; returns `items` (`{path, stats}` or `{path, error}` per image, in
request order; one that can't be measured doesn't stop the others) and `failed`;
`detail` then defaults to "compact". Result shape: with `path` the statistics are
the result's top level (`r`, `g`, `b`, `lum`, `width`, `height`, ...); with `paths`
they are under `items[i].stats` (each item `{path, stats}` or `{path, error}`).
`width`/`height`: the whole rendered image.
`lum_min` / `lum_max` (0 to 255, the scale of `lum`; either alone is fine) limit all
of it to the pixels whose `lum` lies in that band, ends included: `lum_max` leaves
out lamps and speculars so `clipped_high` judges the rest, `lum_min` leaves out
a black border, and a band of the shadows or the mid-tones shows the colour cast
of just that range. `in_band` is the fraction of the pixels measured (the region
or the whole image) that the band holds, so a thin band shows; at least 16 pixels
are needed, else out_of_range.
`max_size`: long edge, 1 to 2576. Anything the image shows counts, including a
border, a mount or bright lamps: crop first (Render applies the working
profile's crop; Live's preview is uncropped), or give `region` {x, y, w, h},
fractions 0 to 1 of the image as this tool shows it (x, y the top-left corner;
the same rectangle as Render's render_preview `region`): all of the above is then
of that part only, and the result's `region` is its pixel rectangle {x, y, w, h}
in the `width` x `height` image. The region is cut from the same render, so a
small one has few pixels (at least 16 are needed, else out_of_range): raise
`max_size` for more. """ + SKILLS_POINTER

PERCENTILES = ("0.1", "1", "5", "50", "95", "99", "99.9")
COMPACT_PERCENTILES = ("0.1", "50", "99.9")
_PERMILLE = {p: round(float(p) * 10) for p in PERCENTILES}
LUMA = (0.2126, 0.7152, 0.0722)
BIN_COUNTS = (8, 16, 32, 64)
"""The `bins` that divide the 256 values evenly."""
DETAILS = ("compact", "standard", "full")
Detail = Annotated[str, Field(json_schema_extra={"enum": list(DETAILS)})]
"""The enum lists the values in the schema; a wrong one still gets out_of_range."""
MAX_STATS_PATHS = 50
"""The most images one image_stats call takes."""
MIN_REGION_PIXELS = 16
REGION_OUTSIDE = (
    "region x, y, w, h are fractions of the image: x, y >= 0, w, h > 0, "
    "x + w <= 1 and y + h <= 1"
)
"""What a region must satisfy; render_preview's refusal has the same words."""


class RegionFractions(Protocol):
    """A region as render_preview takes it (``Region`` in render/preview_ops.py)."""

    x: float
    y: float
    w: float
    h: float

    def inside_image(self) -> bool: ...


class RegionTooSmall(ValueError):
    """A region that covers too few pixels of the rendered image to measure."""


class BandTooSmall(RegionTooSmall):
    """A luminance band that holds too few pixels of the measured part to
    measure (none at all, for a band between two values nothing has)."""


def check_stats_band(lum_min: int | None, lum_max: int | None, error: Callable[[Any, str], Exception]) -> None:
    """Raise ``error("out_of_range", ...)`` unless the limits of a luminance
    band are None or values 0 to 255 with ``lum_min`` not above ``lum_max``."""
    for name, value in (("lum_min", lum_min), ("lum_max", lum_max)):
        if value is not None and not 0 <= value <= 255:
            raise error("out_of_range", f"{name} is a luminance from 0 to 255, not {value}")
    if lum_min is not None and lum_max is not None and lum_min > lum_max:
        raise error("out_of_range", f"lum_min is above lum_max ({lum_min} > {lum_max}): the band is empty")


def check_stats_region(region: RegionFractions | None, error: Callable[[Any, str], Exception]) -> None:
    """Raise ``error("out_of_range", ...)`` for a region outside the image
    (render_preview's rule, same words)."""
    if region is not None and not region.inside_image():
        raise error("out_of_range", REGION_OUTSIDE)


def check_stats_bins(bins: int | None, error: Callable[[Any, str], Exception]) -> None:
    """Raise ``error("out_of_range", ...)`` unless ``bins`` is None or one of
    ``BIN_COUNTS``."""
    if bins is not None and bins not in BIN_COUNTS:
        raise error("out_of_range", "bins must be 8, 16, 32 or 64")


def check_stats_detail(detail: str | None, error: Callable[[Any, str], Exception]) -> None:
    """Raise ``error("out_of_range", ...)`` unless ``detail`` is None (the
    default) or one of ``DETAILS``."""
    if detail is not None and detail not in DETAILS:
        raise error("out_of_range", "detail must be compact, standard or full")


def check_stats_paths(
    path: str | None, paths: list[str] | None, error: Callable[[Any, str], Exception]
) -> None:
    """Raise ``error("out_of_range", ...)`` unless exactly one of ``path`` and
    ``paths`` is given, and ``paths`` holds 1 to ``MAX_STATS_PATHS`` entries."""
    if (path is None) == (paths is None):
        raise error("out_of_range", "give path or paths" + (", not both" if path is not None else ""))
    if paths is not None and not paths:
        raise error("out_of_range", "paths is empty")
    if paths is not None and len(paths) > MAX_STATS_PATHS:
        raise error(
            "out_of_range", f"paths has {len(paths)} entries; the most one call takes is {MAX_STATS_PATHS}"
        )


def check_stats_call(
    path: str | None,
    paths: list[str] | None,
    max_size: int,
    limit: int,
    region: RegionFractions | None,
    bins: int | None,
    detail: str | None,
    lum_min: int | None,
    lum_max: int | None,
    error: Callable[[Any, str], Exception],
) -> None:
    """Every check of an image_stats call that needs no image, for both
    servers (``limit``: the largest ``max_size``): raise ``error("out_of_range",
    ...)`` for the first that fails."""
    check_stats_paths(path, paths, error)
    check_stats_size(max_size, limit, error)
    check_stats_region(region, error)
    check_stats_bins(bins, error)
    check_stats_detail(detail, error)
    check_stats_band(lum_min, lum_max, error)


def stats_detail(detail: str | None, several: bool) -> str:
    """The detail to measure at: the caller's, else "standard" for one image
    and "compact" for several (``paths``)."""
    if detail is not None:
        return detail
    return "compact" if several else "standard"


class OmitNone(BaseModel):
    """A model whose serialised form (``model_dump``, JSON, a tool's structured
    output and the text made of it) leaves out the fields that are None: they
    carry nothing. They stay optional in the JSON schema, as their defaults say."""

    @model_serializer(mode="wrap")
    def _without_none(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return {name: value for name, value in handler(self).items() if value is not None}


class ChannelStats(OmitNone):
    mean: float | None = None
    """Mean of the 8-bit values (0..255), 2 decimals; not at `compact`."""
    std: float | None = None
    """Standard deviation of the values, 2 decimals; `full` only."""
    min: int | None = None
    """Lowest value that occurs; `full` only."""
    max: int | None = None
    """Highest value that occurs; `full` only."""
    mode: int | None = None
    """Most frequent value (the lowest on a tie); `full` only."""
    clipped_high: float
    """Fraction of pixels at 255."""
    clipped_low: float
    """Fraction of pixels at 0."""
    percentiles: dict[str, int]
    """Value (0..255) at 0.1, 1, 5, 50, 95, 99, 99.9 % (nearest rank); at
    `compact` only 0.1, 50 and 99.9."""
    histogram: list[int] | None = None
    """256 counts, only when asked."""
    bins: list[float] | None = None
    """Fractions of pixels (4 decimals) in `bins` equal groups of values, dark
    to light, only when asked."""


class PixelRegion(BaseModel):
    """A rectangle of the rendered image, in its pixels."""

    x: int
    y: int
    w: int
    h: int


class ImageStats(OmitNone):
    width: int
    height: int
    """The whole rendered image's size, also when a region was measured."""
    region: PixelRegion | None = None
    """The part measured, in the pixels of `width` x `height`; left out for
    the whole image."""
    r: ChannelStats
    g: ChannelStats
    b: ChannelStats
    lum: ChannelStats
    """0.2126 R + 0.7152 G + 0.0722 B per pixel, rounded to the nearest 8-bit
    value (so it bins like the other channels)."""
    in_band: float | None = None
    """With `lum_min` / `lum_max`: the fraction of the pixels measured (the
    region, else the whole image) whose `lum` is in the band; every number
    above is of those pixels. Left out without a band."""


class StatsItem(OmitNone):
    path: str
    """The path as requested."""
    stats: ImageStats | None = None
    """As image_stats returns it for one image; left out when this image failed."""
    error: str | None = None
    """`<code>: <message>` when this image failed (the others still come
    back); left out otherwise."""


class StatsBatch(OmitNone):
    items: list[StatsItem]
    """One per requested path, in request order."""
    failed: int


class ImageStatsResult(OmitNone):
    """With `path`: `width` to `lum` of that image; with `paths`: `items` and `failed`."""

    # Only the published shape of the result: the tools build theirs from
    # ``ImageStats`` or ``StatsBatch``, and this one lets the schema allow both.
    width: int | None = None
    height: int | None = None
    region: PixelRegion | None = None
    r: ChannelStats | None = None
    g: ChannelStats | None = None
    b: ChannelStats | None = None
    lum: ChannelStats | None = None
    in_band: float | None = None
    items: list[StatsItem] | None = None
    failed: int | None = None


def stats_result(stats: ImageStats | StatsBatch) -> CallToolResult:
    """The tool result for ``stats``: compact JSON as text and the same as
    structured content, neither with the fields that are None."""
    return CallToolResult(
        content=[TextContent(text=stats.model_dump_json())], structured_content=stats.model_dump(mode="json")
    )


def channel_stats(
    counts: list[int], histogram: bool, bins: int | None = None, detail: str = "standard"
) -> ChannelStats:
    """Statistics from a 256-bin histogram. A percentile is the smallest value
    whose cumulative count reaches ceil(p/100 * N) (nearest rank). ``bins``
    (one of ``BIN_COUNTS``) adds the fractions of pixels in that many equal
    groups of values; ``detail`` (one of ``DETAILS``) says which of the other
    numbers are given."""
    total = sum(counts)
    percentiles: dict[str, int] = {}
    for name in COMPACT_PERCENTILES if detail == "compact" else PERCENTILES:
        rank = max(1, -(-_PERMILLE[name] * total // 1000))
        running = 0
        for value, n in enumerate(counts):
            running += n
            if running >= rank:
                percentiles[name] = value
                break
    mean = sum(v * n for v, n in enumerate(counts)) / total
    spread: dict[str, float | int] = {}
    if detail == "full":
        present = [v for v, n in enumerate(counts) if n]
        spread = {
            "std": round(math.sqrt(sum(n * (v - mean) ** 2 for v, n in enumerate(counts)) / total), 2),
            "min": present[0],
            "max": present[-1],
            "mode": counts.index(max(counts)),  # the first of equals: the lowest
        }
    group = 256 // bins if bins else 0
    return ChannelStats(
        mean=None if detail == "compact" else round(mean, 2),
        **spread,
        clipped_high=round(counts[255] / total, 6),
        clipped_low=round(counts[0] / total, 6),
        percentiles=percentiles,
        histogram=counts if histogram else None,
        bins=[round(sum(counts[i : i + group]) / total, 4) for i in range(0, 256, group)] if bins else None,
    )


def image_stats(
    png: Path | bytes,
    histogram: bool = False,
    region: RegionFractions | None = None,
    bins: int | None = None,
    detail: str = "standard",
    lum_min: int | None = None,
    lum_max: int | None = None,
) -> ImageStats:
    """Statistics of an 8-bit image file (any mode Pillow can turn into RGB),
    of the part ``region`` selects when given (fractions of the image, cut like
    render_preview's region) and of the pixels whose luminance is between
    ``lum_min`` and ``lum_max`` (ends included; None: no limit), at the
    ``detail`` (one of ``DETAILS``). Raises ValueError if it can't be read, has
    no pixels or ``detail`` is not one, and ``RegionTooSmall`` (a ValueError)
    if the region, or the band within it, has fewer than ``MIN_REGION_PIXELS``."""
    from PIL import Image

    if detail not in DETAILS:
        raise ValueError(f"detail must be compact, standard or full, not {detail!r}")
    try:
        with Image.open(io.BytesIO(png) if isinstance(png, bytes) else png) as opened:
            rgb = opened.convert("RGB")
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read the rendered image: {e}") from e
    width, height = rgb.size
    if width * height == 0:
        raise ValueError("the rendered image has no pixels")
    part = None
    if region is not None:
        rect = region_rect(Rect(0, 0, width, height), x=region.x, y=region.y, w=region.w, h=region.h)
        if rect.w * rect.h < MIN_REGION_PIXELS:
            raise RegionTooSmall(
                f"the region covers only {rect.w} x {rect.h} pixels of the {width} x {height} image; "
                f"it needs at least {MIN_REGION_PIXELS} pixels: widen it, or raise max_size"
            )
        rgb = rgb.crop((rect.x, rect.y, rect.x + rect.w, rect.y + rect.h))
        part = PixelRegion(x=rect.x, y=rect.y, w=rect.w, h=rect.h)
    luma = rgb.convert("L", (*LUMA, 0))
    mask = in_band = None
    if lum_min is not None or lum_max is not None:
        low, high = 0 if lum_min is None else lum_min, 255 if lum_max is None else lum_max
        mask = luma.point([255 if low <= value <= high else 0 for value in range(256)])
        inside = mask.histogram()[255]
        if inside < MIN_REGION_PIXELS:
            raise BandTooSmall(
                f"only {inside} of the {luma.width * luma.height} pixels measured lie in the band "
                f"lum_min {low} to lum_max {high}; it needs at least {MIN_REGION_PIXELS} pixels: "
                "widen the band, or raise max_size"
            )
        in_band = round(inside / (luma.width * luma.height), 6)
    counts = rgb.histogram(mask)
    lum = luma.histogram(mask)
    r, g, b = (channel_stats(counts[i * 256 : (i + 1) * 256], histogram, bins, detail) for i in range(3))
    return ImageStats(
        width=width,
        height=height,
        region=part,
        r=r,
        g=g,
        b=b,
        lum=channel_stats(lum, histogram, bins, detail),
        in_band=in_band,
    )
