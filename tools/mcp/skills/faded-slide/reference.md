# Faded slide reference

## Maths

ART Color Correction (RGB mode), per channel on linear working-space values 0..1:

```
v = v * slope + offset / 2
v = (v / pivot) ^ (1 / power) * pivot        (pivot 1)
```

The slope acts BEFORE the power, and stored `power` = 1 / exponent.

Fading model: neutral target green `g` relates to a faded channel `c` as
`g = A * c^k` (linear, 0..1). Corrected channel must be `A * c^k`. With ART's
order that is `(c * slope)^(1/power)` = `slope^k * c^k` when `power = 1/k`, so
`slope^k = A`, i.e. `slope = A^(1/k) = exp(a)^(1/k)` where `a = ln A`.
Using `slope = A` boosts too much when k > 1 (19% too much blue on the test slide).

Fit: for N neutral spots with avg values (65535 scale), `y = ln(g/65535)`,
`x = ln(c/65535)`; ordinary least squares `y = a + k x`.

```python
import math
def fit(c, g):                     # lists of avg values for one channel and green
    x = [math.log(v / 65535) for v in c]
    y = [math.log(v / 65535) for v in g]
    n = len(x); mx = sum(x) / n; my = sum(y) / n
    k = sum((a - mx) * (b - my) for a, b in zip(x, y)) / sum((a - mx) ** 2 for a in x)
    a = my - k * mx
    res = [b - (a + k * u) for u, b in zip(x, y)]
    return k, a, math.exp(a) ** (1 / k), 1 / k, res   # k, a, slope, power, residuals

def loo(c, g):                     # k with each spot left out
    return [fit(c[:i] + c[i+1:], g[:i] + g[i+1:])[0] for i in range(len(c))]
```

Clean pure Python is enough (no numpy needed). Judge `loo` spread, not a residual
threshold.

Worked numbers (three real slides): blue k 2.0 / 1.6 / 2.08 (power 0.50 / 0.63 / 0.48,
slope about 1.09 on one), red k about 1 (power about 0.96, slope about 1.29 on one).
Percentiles on the first: blue 67 vs red 23 at p1 but 238 vs 201 at p99 before.

## Spatial faults

Edge fading leaves bands or corners with a different cast. Measure a grid on a render
that does NOT yet include the region 2 correction: `render_preview`/`image_stats`
give no per-patch values, so use `sample_spots` (up to 64 spots a call, `size` 20) on a
grid (e.g. 11 columns x 10 rows, 20 x 20 px patches on a 1024 px preview, converted to
frame pixels) and compare the channel difference that shows the fault (b - r, after
region 1). Identify the geometry from where the difference is non-zero. Example slide:
two side bands on the lower half only, the right stronger, plus the bottom-left corner.

Region 2 = same RGB mode, only the faulty channel(s) given a slope (e.g. `b.slope` 0.30),
with a mask composed from shapes:

```
edit_profile(path, adjustments={"color_correction": {"regions": [null, {
  "b": {"slope": 0.30},
  "mask": {"feather": 0, "blur": 0, "shapes": [
    {"type": "gradient", "angle": -90, "x": -80, "strength_start": 0, "strength_end": 60, "feather": 15},
    {"type": "gradient", "angle": 90, "x": 76, "strength_start": 0, "strength_end": 100, "feather": 18, "mode": "add"},
    {"type": "gradient", "angle": 0, "y": 18, "strength_start": 0, "strength_end": 100, "feather": 5, "mode": "intersect"},
    {"type": "rectangle", "roundness": 100, "x": -100, "y": 100, "width": 18, "height": 20, "feather": 40, "mode": "add"}
  ]}}]}})
```

(`null` keeps region 1; shapes are matched by position, so re-sending with changed
numbers edits them in place.) Check `describe_adjustments` for exact shape defaults and
how `strength_start`/`strength_end` run.

Mask coordinates: position -100..100 edge to edge (0 = centre); width/height are % of
the full image; gradient `feather` is % of the image diagonal; angle 0 runs the
gradient top to bottom, -90 points its end to the left, +90 to the right.

Re-measure the WHOLE grid after each change, including places that must not change
(sky, centre). A single inverted full-width ellipse fixed the bottom corners but turned
the top corners yellow and missed mid-height edges: compose from shapes instead.
