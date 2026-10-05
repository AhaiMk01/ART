# Film negative reference

Film Negative per channel (ART): `out_c = RefOutput_c * (in_c / RefInput_c)^e_c`
with exponents `e = (-G*RedRatio, -G, -G*BlueRatio)`, `G` = `GreenExponent`
(1.5); clipped at 65535. Inputs are the
`sample_spots` values (the negative's, linear 0..65535).

## Fitting RedRatio and BlueRatio

Over the neutral spots (`avg` r, g, b): least squares slope of ln r against
ln g is `1/RedRatio`; same for ln b: `1/BlueRatio`. Fit, list the residuals,
drop the spots with large ones (more than ~2x the median absolute residual,
and any that is a coloured object), refit. Neutral spots must span a range of
green (dark and light parts), else the slope is meaningless.

```python
import math
# spots: list of (r, g, b) avg values of neutral spots (all spots sampled)
spots = [...]
def lsq(xs, ys):                       # slope, intercept
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return slope, my - slope * mx
L = [[math.log(v) for v in s] for s in spots]          # ln r, ln g, ln b
keep = list(range(len(L)))
for _ in range(4):
    lg = [L[i][1] for i in keep]
    fits = {c: lsq(lg, [L[i][c] for i in keep]) for c in (0, 2)}
    res = {i: max(abs(L[i][c] - (fits[c][1] + fits[c][0] * L[i][1])) for c in (0, 2))
           for i in range(len(L))}                     # residual of EVERY spot
    med = sorted(res[i] for i in keep)[len(keep) // 2]
    new = [i for i in range(len(L)) if res[i] <= max(3 * med, 0.02)]
    if new == keep: break
    keep = new
red, blue = 1 / fits[0][0], 1 / fits[2][0]
print(red, blue, "kept", keep, "dropped", [i for i in range(len(L)) if i not in keep])
```

## Choosing neutral references

Choose by material, not by how grey a spot looks.

- Good: white paint (trim, coping, signs), bare/galvanised metal (flues,
  poles), concrete, white trainers, overcast sky.
- Risky: natural stone (one "grey" paving was buff sandstone/bluestone and
  pulled a frame 0.4 too cold), black fabric (dyes aren't neutral: hoodie and
  trousers disagreed with white paint by ~0.2), glass/windows (reflections),
  foliage, painted machinery.
- Agreement only counts between INDEPENDENT materials: three slabs of the same
  stone agreeing prove nothing; white paint + metal + concrete agreeing does.

## Roll exponents: pooled fit

A single frame spans too little tonal range: one frame's whites-only fit gave
RedRatio 1.575, a pooled fit (25 reliable spots in 8 frames) gave 1.334 and
BlueRatio 0.737. With wrong exponents a per-frame white balance can make only
one brightness neutral (whites neutral, mid-tones yellow).

Pooled fit: each frame gets its own intercept, all frames share one slope
(within-frame regression). For channel c (r or b) against green, with
`x = ln g`, `y = ln c` and per-frame means `xm_f`, `ym_f`:

    slope = sum_f sum_i (x_fi - xm_f)(y_fi - ym_f) / sum_f sum_i (x_fi - xm_f)^2

`RedRatio = 1/slope_r`, `BlueRatio = 1/slope_b`. Use only each frame's reliable
neutrals (independent materials, small residuals; drop outliers, refit). The
per-frame intercepts are then that frame's `ir`, `ib` below.

## Reference point on the neutral line

For a fixed roll ratio, neutrals lie on
`ln r = ir + ln g / RedRatio`, `ln b = ib + ln g / BlueRatio`.
`ir`, `ib` = mean of `ln r - ln g/RedRatio` and `ln b - ln g/BlueRatio` over
the frame's agreeing neutrals (those whose own intercepts are close to the
mean). Pick a green `g0` (a typical neutral's `g`), then
`RefInput = (exp(ir + ln g0/RedRatio), g0, exp(ib + ln g0/BlueRatio))`.
Frames in other light have different `ir`, `ib` on the same slopes.

## Changing white balance without changing brightness

ART's picker rule, which `edit_profile` applies itself when a request sets
`film_negative.ref_input` without `ref_output` (the computed `ref_output` is
listed under `implied`; this is the formula behind it). With `e = (-G*RedRatio,
-G, -G*BlueRatio)` as stored now and the current
`mult_c = RefOutput_c / RefInput_c^e_c` (an unset reference: ART's medians and
65535/24 grey, estimated by sampling, with a warning):

1. `out_c = mult_c * newRefInput_c^e_c` (what the new reference spot gets now);
2. `L = 0.2126729*out_r + 0.7151521*out_g + 0.0721750*out_b`;
3. `RefOutput = "L;L;L"`, `RefInput = newRefInput`. (Output channels clip at
   65535 first.)

For an absolute level instead, `L` = intended reflectance x 65535.

## Taste goes in RefOutput

Measurement stays in `RefInput` (the measured neutral). To make a frame
warmer or cooler without touching it, set
`RefOutput = k * (e^(0.035 s), 1, e^(-0.07 s))` with `s` = steps (negative =
cooler) and `k` chosen so the luminance
`0.2126729 r + 0.7151521 g + 0.0721750 b` equals the neutral's `L`. `L;L;L` =
the measured neutral. Offer the user a few variants side by side (e.g. Cool 2
.. Warm 2, plus the previous one): users judged by skin tones and sky (warm
shifts turn blue sky violet-grey).

## Output level

`clipped_high` of `image_stats` is the guide: raise `L` while it is about 0,
stop when highlights begin to clip. Curve x/y are sRGB-encoded 0..1 (about
`image_stats` value / 255), so a black point at `lum` percentile 0.1 of 60
becomes `x = 60/255 = 0.235`.

## Per-channel black point

Under bluish light (hangar lamps, shade) the inverted shadows can sit blue
while mid-tones are neutral: the channels' black levels differ, which
`ref_input` can't fix (it moves the whole line). Lower that channel's black
with `color_correction`: one region, RGB mode, an `offset` on that channel
only (e.g. `b` -0.1), no mask. It works in linear values before the tone
curve, so set it before the curve's black point, then re-check `image_stats`
per channel: the channel's percentile 0.1 should come down to the others'.

## Changing L after the black adjustments

The colour-correction offset and the curve's black point are fixed amounts,
but changing `L` scales the linear image. Lowering `L` on one frame (a
low-key frame) with the roll's offset and black point unchanged crushed it
(62% of blue at 0). With `k = L_new / L_old`:

- offset: `offset * k` (linear);
- black point: `x0_new = (x0^2.2 * k)^(1/2.2)` (curve x is sRGB-encoded).

Example: L 34000 -> 17000, offset -0.1 -> -0.05, x0 0.25 -> ~0.18. Then
re-check `clipped_low`.

## Mixed light

With several light sources in a frame (lamps plus daylight, coloured
spotlights), no single balance is right everywhere: balance on the subject's
neutrals (white paint on the aircraft, not the floor under another lamp) and
leave the rest. Keep a cast that is the real colour of the light (a warm lamp
lighting a bomb bay): neutralising it looks wrong. Say which frames you left
warm or cool, and why.
