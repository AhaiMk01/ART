"""ART diagonal curves as agents write and read them.

ART stores a curve as ``<type code>;x1;y1;x2;y2;...;`` (codes from
``src/utils/curvetypes.h``; ``0;`` is the identity). Agents give a curve as
explicit points or as ``linear``. Everything about curves lives in this
module: validation, encoding and decoding.
"""

import bisect
import functools
import math
import struct
from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, Tag, field_validator
from pydantic.json_schema import SkipJsonSchema

from art_mcp.compactschema import CompactModel

CURVE_CODES = {"spline": 1, "nurbs": 3, "catmull_rom": 4}
"""``type`` -> ART's DiagonalCurveType code (parametric, 2, is read-only)."""

MIN_POINTS = 2
MAX_POINTS = 32

Point = tuple[float, float]


def format_number(x: float) -> str:
    """Compact text for one coordinate: ten significant digits, the same
    format ``profile`` uses for every other float it writes."""
    return f"{x:.10g}"


def _points_problem(points: list[Point]) -> str | None:
    if not MIN_POINTS <= len(points) <= MAX_POINTS:
        return f"needs {MIN_POINTS} to {MAX_POINTS} points, got {len(points)}"
    for i, (x, y) in enumerate(points, 1):
        if not (0 <= x <= 1 and 0 <= y <= 1):
            return f"point {i} (x={x!r}, y={y!r}) is outside 0..1"
    for i in range(1, len(points)):
        if not points[i][0] > points[i - 1][0]:
            return (
                f"x must be strictly increasing: point {i + 1} has x={points[i][0]!r} "
                f"after point {i} with x={points[i - 1][0]!r}"
            )
    return None


class PointCurve(CompactModel):
    """A curve through explicit points."""

    type: Literal["spline", "catmull_rom", "nurbs"]
    points: list[Point] = Field(description="[x, y] pairs in 0..1, x strictly increasing")
    drawn: SkipJsonSchema[list[list[float]] | None] = Field(
        default=None, exclude=True,
        description="Read-only: the line ART draws, as get_profile reports it; ignored if sent back",
    )  # fmt: skip

    @field_validator("points")
    @classmethod
    def _check_points(cls, points: list[Point]) -> list[Point]:
        problem = _points_problem(points)
        if problem:
            raise ValueError(problem)
        return points


class LinearCurve(CompactModel):
    """The identity curve."""

    type: Literal["linear"]
    drawn: SkipJsonSchema[list[list[float]] | None] = Field(
        default=None, exclude=True, description="Read-only; ignored if sent back"
    )


def _curve_kind(value: Any) -> str:
    if isinstance(value, LinearCurve) or (isinstance(value, dict) and value.get("type") == "linear"):
        return "linear"
    return "points"


CurveSpec = Annotated[
    Annotated[PointCurve, Tag("points")] | Annotated[LinearCurve, Tag("linear")],
    Discriminator(_curve_kind),
]
"""A curve as an agent gives it: points or ``linear``."""


def encode(curve: PointCurve | LinearCurve) -> str:
    """ART's text for a curve."""
    if isinstance(curve, LinearCurve):
        return "0;"
    return f"{CURVE_CODES[curve.type]};" + "".join(
        f"{format_number(x)};{format_number(y)};" for x, y in curve.points
    )


def _snap(v: float) -> float:
    """Pull a value within 1e-9 outside 0..1 back onto the edge."""
    if -1e-9 <= v < 0:
        return 0.0
    if 1 < v <= 1 + 1e-9:
        return 1.0
    return v


def decode(stored: str) -> dict[str, Any] | None:
    """A stored curve as ``{"type", "points"}`` (identity: ``{"type":
    "linear"}``), or None when it isn't one an agent could have written:
    parametric, empty, unparseable or out of the 0..1 / increasing-x rules."""
    tokens = [t.strip() for t in stored.strip().split(";")]
    if tokens and tokens[-1] == "":
        tokens.pop()
    if not tokens:
        return None
    if tokens == ["0"]:
        return {"type": "linear"}
    names = {code: name for name, code in CURVE_CODES.items()}
    try:
        name = names.get(int(tokens[0]))
        numbers = [float(t) for t in tokens[1:]]
    except ValueError:
        return None
    if name is None or len(numbers) % 2:
        return None
    # ART writes doubles, so 1 can come back as 1.0000000000000002.
    numbers = [_snap(v) for v in numbers]
    points = list(zip(numbers[0::2], numbers[1::2], strict=True))
    if _points_problem(points):
        return None
    return {"type": name, "points": [[x, y] for x, y in points]}


# ---------------------------------------------------------------------------
# What ART draws: a port of ``DiagonalCurve`` (src/engine/diagonalcurves.cc)
# ---------------------------------------------------------------------------

_POLY_POINTS = 1000
"""``CURVES_MIN_POLY_POINTS``, the ppn ART's tone curve uses (the default)."""

DRAWN_XS = [i / 8 for i in range(9)]
SCAN_STEPS = 1000
"""The curve is scanned at ``SCAN_STEPS + 1`` evenly spaced x for warnings."""


def _f32(v: float) -> float:
    """ART assigns float literals (``0.01f``) to doubles."""
    return float(struct.unpack("f", struct.pack("f", v))[0])


def _catmull_rom_tj(ti: float, xi: float, yi: float, xj: float, yj: float) -> float:
    return float(math.sqrt((xj - xi) ** 2 + (yj - yi) ** 2) ** 0.375) + ti


def _catmull_rom_segment(
    n_points: int,
    p0: Point, p1: Point, p2: Point, p3: Point,
    res_x: list[float], res_y: list[float],
) -> None:  # fmt: skip
    p0_x, p0_y = p0
    p1_x, p1_y = p1
    p2_x, p2_y = p2
    p3_x, p3_y = p3
    t0 = 0.0
    t1 = _catmull_rom_tj(t0, p0_x, p0_y, p1_x, p1_y)
    t2 = _catmull_rom_tj(t1, p1_x, p1_y, p2_x, p2_y)
    t3 = _catmull_rom_tj(t2, p2_x, p2_y, p3_x, p3_y)
    space = (t2 - t1) / n_points
    res_x.append(p1_x)
    res_y.append(p1_y)
    if p1_y == p2_y and (p1_y == 0 or p1_y == 1):
        # a segment at 0 or 1 is computed exactly
        for i in range(1, n_points - 1):
            t = p1_x + space * i
            if t >= p2_x:
                break
            res_x.append(t)
            res_y.append(p1_y)
    else:
        for i in range(1, n_points - 1):
            t = t1 + space * i
            c = (t1 - t) / (t1 - t0)
            d = (t - t0) / (t1 - t0)
            a1_x, a1_y = c * p0_x + d * p1_x, c * p0_y + d * p1_y
            c = (t2 - t) / (t2 - t1)
            d = (t - t1) / (t2 - t1)
            a2_x, a2_y = c * p1_x + d * p2_x, c * p1_y + d * p2_y
            c = (t3 - t) / (t3 - t2)
            d = (t - t2) / (t3 - t2)
            a3_x, a3_y = c * p2_x + d * p3_x, c * p2_y + d * p3_y
            c = (t2 - t) / (t2 - t0)
            d = (t - t0) / (t2 - t0)
            b1_x, b1_y = c * a1_x + d * a2_x, c * a1_y + d * a2_y
            c = (t3 - t) / (t3 - t1)
            d = (t - t1) / (t3 - t1)
            b2_x, b2_y = c * a2_x + d * a3_x, c * a2_y + d * a3_y
            c = (t2 - t) / (t2 - t1)
            d = (t - t1) / (t2 - t1)
            res_x.append(c * b1_x + d * b2_x)
            res_y.append(c * b1_y + d * b2_y)
    res_x.append(p2_x)
    res_y.append(p2_y)


def _catmull_rom_reflect(px: float, py: float, cx: float, cy: float) -> Point:
    dx = px - cx
    dy = py - cy
    rx = cx - dx * 0.01
    ry = (dy / dx) * (rx - cx) + cy if dx > 1e-5 else cy
    return rx, ry


def _catmull_rom_polyline(
    n_points: int, x: list[float], y: list[float]
) -> tuple[list[float], list[float]]:
    n_cp = len(x)
    first = _catmull_rom_reflect(x[1], y[1], x[0], y[0])
    last = _catmull_rom_reflect(x[n_cp - 2], y[n_cp - 2], x[n_cp - 1], y[n_cp - 1])
    res_x: list[float] = []
    res_y: list[float] = []
    segments = n_cp - 1
    for i in range(segments):
        n = max(int(n_points * (x[i + 1] - x[i]) + 0.5), 2)
        _catmull_rom_segment(
            n,
            first if i == 0 else (x[i - 1], y[i - 1]),
            (x[i], y[i]),
            (x[i + 1], y[i + 1]),
            last if i == segments - 1 else (x[i + 2], y[i + 2]),
            res_x, res_y,
        )  # fmt: skip
    return res_x, res_y


def _spline_second_derivatives(x: list[float], y: list[float]) -> list[float]:
    n = len(x)
    ypp = [0.0] * n
    u = [0.0] * (n - 1)
    for i in range(1, n - 1):
        sig = (x[i] - x[i - 1]) / (x[i + 1] - x[i - 1])
        p = sig * ypp[i - 1] + 2.0
        ypp[i] = (sig - 1.0) / p
        u[i] = (y[i + 1] - y[i]) / (x[i + 1] - x[i]) - (y[i] - y[i - 1]) / (x[i] - x[i - 1])
        u[i] = (6.0 * u[i] / (x[i + 1] - x[i - 1]) - sig * u[i - 1]) / p
    ypp[n - 1] = 0.0
    for k in range(n - 2, -1, -1):
        ypp[k] = ypp[k] * ypp[k + 1] + u[k]
    return ypp


class DrawnCurve:
    """ART's ``DiagonalCurve`` for a spline, Catmull-Rom or linear curve (and
    for a NURBS with two points, which ART draws as a line). ``value`` is
    ``getVal``; ``raw`` is the same before ART's ``CLIPD`` (the lower clamp at
    0; ART has no upper clamp)."""

    def __init__(self, type_: str, points: list[Point]) -> None:
        self._kind = "linear"
        self._x = [p[0] for p in points]
        self._y = [p[1] for p in points]
        n = len(points)
        identity = all(abs(a - b) < 0.000009 for a, b in points)
        if self._x[0] != 0.0 or self._x[-1] != 1.0:
            identity = False
        if self._x[0] == 0.0 and self._x[1] == 0.0:
            self._x[1] = _f32(0.01)
        if self._x[0] == 1.0 and self._x[1] == 1.0:
            self._x[0] = _f32(0.99)
        self._ypp: list[float] = []
        self._poly_x: list[float] = []
        self._poly_y: list[float] = []
        if identity:
            self._kind = "empty"
        elif type_ == "spline" and n > 2:
            self._kind = "spline"
            self._ypp = _spline_second_derivatives(self._x, self._y)
        elif type_ == "catmull_rom" and n > 2:
            self._kind = "catmull_rom"
            self._poly_x, self._poly_y = _catmull_rom_polyline(
                max(_POLY_POINTS * 65, 65000), self._x, self._y
            )

    def raw(self, t: float) -> float:
        """``getVal`` without ``CLIPD``."""
        return self._eval(t, False)

    def value(self, t: float) -> float:
        return self._eval(t, True)

    def _eval(self, t: float, clip: bool) -> float:
        x, y = self._x, self._y
        n = len(x)
        if self._kind == "empty":
            return t
        if self._kind == "catmull_rom":
            px, py = self._poly_x, self._poly_y
            d = bisect.bisect_left(px, t)
            if d == len(px):
                return py[-1]
            if d + 1 < len(px) and t - px[d] > px[d + 1] - t:
                d += 1
            return max(py[d], 0.0) if clip else py[d]
        if t > x[n - 1]:
            return y[n - 1]
        if t < x[0]:
            return y[0]
        lo, hi = 0, n - 1
        while hi > 1 + lo:
            k = (hi + lo) // 2
            if x[k] > t:
                hi = k
            else:
                lo = k
        h = x[hi] - x[lo]
        if self._kind == "linear":
            return y[lo] + (t - x[lo]) * (y[hi] - y[lo]) / h
        a = (x[hi] - t) / h
        b = (t - x[lo]) / h
        r = (
            a * y[lo] + b * y[hi]
            + ((a * a * a - a) * self._ypp[lo] + (b * b * b - b) * self._ypp[hi])
            * (h * h) * 0.1666666666666666666666666666666
        )  # fmt: skip
        return max(r, 0.0) if clip else r


@functools.lru_cache(maxsize=64)
def _drawn_curve(type_: str, points: tuple[Point, ...]) -> DrawnCurve | None:
    if type_ == "nurbs" and len(points) > 2:
        # ART's NURBS polyline isn't ported.
        return None
    return DrawnCurve(type_, list(points))


def drawn_curve(curve: dict[str, Any] | PointCurve | LinearCurve) -> DrawnCurve | None:
    """The line ART draws for ``curve`` (a decoded dict or a model), or None
    for a NURBS with three or more points, which isn't computed. ``linear``
    is the identity."""
    if isinstance(curve, dict):
        type_ = curve["type"]
        points = [(float(x), float(y)) for x, y in curve.get("points", [])]
    else:
        type_ = curve.type
        points = [(float(x), float(y)) for x, y in curve.points] if isinstance(curve, PointCurve) else []
    if type_ == "linear":
        return DrawnCurve("linear", [(0.0, 0.0), (1.0, 1.0)])
    return _drawn_curve(type_, tuple(points))


def drawn_points(curve: dict[str, Any] | PointCurve | LinearCurve) -> list[list[float]] | None:
    """``[x, y]`` at x = 0, 0.125, ..., 1 (y rounded to 4 decimals; ART's own
    value, so a Catmull-Rom or spline overshoot above 1 shows), or None when
    not computed (NURBS with three or more points). ``linear`` is the identity."""
    drawn = drawn_curve(curve)
    if drawn is None:
        return None
    return [[x, round(drawn.value(x), 4)] for x in DRAWN_XS]


def _ranges(xs: list[float], flags: list[bool]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    start: int | None = None
    for i, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            out.append((xs[start], xs[i - 1]))
            start = None
    return out


def _span(lo: float, hi: float) -> str:
    return f"x {lo:.3g}" if lo == hi else f"x {lo:.3g}-{hi:.3g}"


def curve_warnings(name: str, curve: dict[str, Any] | PointCurve | LinearCurve) -> list[str]:
    """Problems with the line ART draws for a curve the agent set: where it
    clips to 0, goes above 1 (ART doesn't clamp there) or runs backwards."""
    if isinstance(curve, LinearCurve) or (isinstance(curve, dict) and curve["type"] == "linear"):
        return []
    drawn = drawn_curve(curve)
    if drawn is None:
        return [
            f"{name} is a NURBS curve; ART's drawn line for it isn't computed here, "
            "so clipping and reversal aren't checked"
        ]
    xs = [i / SCAN_STEPS for i in range(SCAN_STEPS + 1)]
    raw = [drawn.raw(x) for x in xs]
    val = [drawn.value(x) for x in xs]
    warnings = []
    for lo, hi in _ranges(xs, [r < 0 for r in raw]):
        warnings.append(f"{name} clips to 0 for {_span(lo, hi)}")
    for lo, hi in _ranges(xs, [r > 1 + 1e-9 for r in raw]):
        warnings.append(f"{name} goes above 1 for {_span(lo, hi)}")
    falling = [False] + [val[i] < val[i - 1] - 1e-9 for i in range(1, len(val))]
    for lo, hi in _ranges(xs, falling):
        # the fall starts at the sample before the first lower one
        warnings.append(f"{name} reverses for {_span(max(lo - 1 / SCAN_STEPS, 0.0), hi)}")
    return warnings
