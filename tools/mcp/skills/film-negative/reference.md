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
  poles), concrete, white trainers, midday overcast sky.
- Risky: natural stone (one "grey" paving was buff sandstone/bluestone and
  pulled a frame 0.4 too cold), black fabric (dyes aren't neutral: hoodie and
  trousers disagreed with white paint by ~0.2), glass/windows (reflections),
  foliage, painted machinery, sky at dusk or twilight (bluer than the ground:
  with the dusk-sky spots in, one roll's blue slope fitted 0.857 against 0.934
  without them). If dusk-sky spots disagree with the ground neutrals on the
  intercepts (`ir`, `ib`, below), drop the sky.
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

```python
import math
# frames: {name: [(r, g, b), ...]}, avg values of each frame's neutral spots
frames = {...}
def med(v): return sorted(v)[len(v) // 2]
pts = [(f, math.log(g), math.log(r), math.log(b))        # (frame, ln g, ln r, ln b)
       for f, sp in frames.items() for r, g, b in sp]
keep = set(range(len(pts)))
for _ in range(6):
    slope, icpt = {}, {}
    for c in (2, 3):                                     # ln r, then ln b, against ln g
        num = den = 0.0
        for f in frames:                                 # within-frame: frame means removed
            idx = [i for i in keep if pts[i][0] == f]
            if len(idx) < 2: continue                    # one spot says nothing about a slope
            xm = sum(pts[i][1] for i in idx) / len(idx)
            ym = sum(pts[i][c] for i in idx) / len(idx)
            num += sum((pts[i][1] - xm) * (pts[i][c] - ym) for i in idx)
            den += sum((pts[i][1] - xm) ** 2 for i in idx)
        slope[c] = num / den                             # one slope for all frames
        for f in frames:                                 # median: an outlier can't pull the frame's line
            v = [pts[i][c] - slope[c] * pts[i][1] for i in keep if pts[i][0] == f]
            if v: icpt[c, f] = med(v)
    res = [max(abs(p[c] - icpt[c, p[0]] - slope[c] * p[1]) for c in (2, 3)) if (2, p[0]) in icpt else 9
           for p in pts]                                 # residual of EVERY spot
    new = {i for i in range(len(pts)) if res[i] <= max(3 * med([res[j] for j in keep]), 0.02)}
    if new == keep: break
    keep = new
red, blue = 1 / slope[2], 1 / slope[3]
print(red, blue, "dropped", sorted(set(range(len(pts))) - keep))
# per-frame ir, ib: icpt[2, f], icpt[3, f]
```

Tested as printed on synthetic frames (RedRatio 1.37, BlueRatio 0.93, another
intercept per frame, noise 0.005 in ln, 4 planted outliers of 0.12 to 0.3 in ln
among ~40 spots, 300 random draws): 99% of the planted outliers are dropped and
the ratios come back within 1% in 96% of the draws (median error 0.3% red,
0.2% blue, worst 1.5%). The draws over 1% are the same with the outliers
removed by hand: sampling noise of frames with a narrow green range.

## Reference point on the neutral line

For a fixed roll ratio, neutrals lie on
`ln r = ir + ln g / RedRatio`, `ln b = ib + ln g / BlueRatio`.
`ir`, `ib` = mean of `ln r - ln g/RedRatio` and `ln b - ln g/BlueRatio` over
the frame's agreeing neutrals (those whose own intercepts are close to the
mean). Pick a green `g0` (a typical neutral's `g`), then
`RefInput = (exp(ir + ln g0/RedRatio), g0, exp(ib + ln g0/BlueRatio))`.
Frames in other light have different `ir`, `ib` on the same slopes.

**Scan exposure moves `ir`, `ib` too.** Scale all of a frame's linear values
by `s` (longer shutter, higher ISO, wider aperture) and its line shifts:
`ir' = ir + ln(s) (1 - 1/RedRatio)`, `ib' = ib + ln(s) (1 - 1/BlueRatio)`
(the slopes stay, so the ratios and the pooled fit are unaffected). So
normalise the intercepts to one scan exposure before comparing frames or
judging whether a frame fits a group: `ir_norm = ir - ln(s) (1 - 1/RedRatio)`,
likewise `ib`, with `s = (t * iso / aperture^2) / (t0 * iso0 / aperture0^2)`
against the reference frame (`inspect_image`, or `inspect_images` for the
roll in one call, gives `shutter_seconds`, `iso`, `aperture`; if only the
shutter varies, `s = t / t0`). These EXIF values are the digitising camera's
(the one that photographed the negative on the light table), and that is what
matters here: they are what scales the scan's linear values. The film's
original exposure is not in the file and is not needed. A manual lens records
aperture 0, which the tools report as null: then use shutter and ISO only,
`s = (t * iso) / (t0 * iso0)`. Example, RedRatio 1.37,
BlueRatio 0.90: a frame at 0.625 s against 0.5 s (`s` = 1.25) has `ir` higher
by 0.060 and `ib` lower by 0.025 in the same light, and its measured `ib` of
-1.45 is -1.425 at 0.5 s. This assumes the scans' camera settings are the only
exposure difference (same backlight and white balance, nothing clipped). The
~0.03 threshold in "Lighting groups" applies to the normalised values.

**One `g0` per lighting group.** `L` of `RefOutput` is what the `RefInput`
point is rendered as, so the same `L` gives two frames the same brightness
only if their `g0` is the same green at the reference exposure. Choose `g0`
once per group (a typical neutral's green) and use it on every frame of the
group, scaled for the scan exposure: `g0_frame = s * g0`, with `RefInput` on
that frame's own (measured) line at `g0_frame`, which is `s` times the point
on the normalised line at `g0`. Unscaled, the `s` = 1.25 frame above comes out
at 1.25^-1.5 = 0.72 of the group's brightness (-0.48 EV); in general a `g0`
off by a factor `c` changes the brightness by `c^1.5`.

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

`L` is also the ceiling: the film negative clips its output at 65535, and
nothing later recovers it. Tested on one frame: `L` 34000 with exposure -1 EV
matched `L` 17000 exactly in shadows and mid-tones (percentiles 0.1-50
identical) but its highlights, clipped by the film negative, came out as
flat cream at ~194 instead of white. So per lighting group, set `L` at the
group's brightest frame's no-clip level in the preset, and per frame only
brighten with exposure compensation (+EV; the film negative's values then
stay the group's). A frame that needs to go darker than the preset gets a
lower `L`, not -EV. Either way, scale the black adjustments with the total
factor (`k = 2^EV` or `L_new/L_old`; "Changing L after the black
adjustments"). Brightness (Lab adjustments, after the tone curve) is for
taste in the mid-tones, not for exposure.

`clipped_high` of `image_stats` is the guide: raise `L` while it is about 0,
stop when highlights begin to clip. Curve x/y are sRGB-encoded 0..1 (about
`image_stats` value / 255), so a black point at `lum` percentile 0.1 of 60
becomes `x = 60/255 = 0.235`.

Lamps and speculars in a lit interior clip 0.4 to 1% whatever `L` is, and that
is fine: judge `clipped_high` without the lamps (`image_stats(lum_max=...)`,
or a `region` away from them) or accept it; do not lower `L` for them. A bright
sky clipping one channel (blue first) is a trade-off against the level: lean
to accepting a little when the sky is not the subject (a dusk frame kept 1.4%
of blue clipped in the sky; clearing it would have taken a much lower `L` for
the whole frame), and lower `L` when it is.

## Per-channel black point

Under bluish light (hangar lamps, shade) the inverted shadows can sit blue
while mid-tones are neutral: the channels' black levels differ, which
`ref_input` can't fix (it moves the whole line). Lower that channel's black
with `color_correction`: one region, RGB mode, an `offset` on that channel
only (e.g. `b` -0.1), no mask. It works in linear working-space values (0..1
= 0..65535) before the tone curve, so set it before the curve's black point,
then re-check `image_stats` per channel: the channel's percentile 0.1 should
come down to the others'.

The offset is stored halved: ART computes `v = v*slope + offset/2` per channel.
To lower a channel's black by the linear amount `D`, set `offset = -2 D` (the
`b` -0.1 above is `D` = 0.05). It comes off every pixel of that channel, not
only the shadows: a mid-tone neutral loses the same `D` (an 18% grey, sRGB 117,
went to `b` 98 with `D` = 0.05, a yellow cast). Keep `D` as small as the black
needs; if the mid-tones then drift, compensate with a `RefOutput` tint (it
moves that channel's highlights too: check them) or re-pick `RefInput`.
To size `D` from `image_stats` (sRGB values): the default working space
(Rec2020) is wider than sRGB, so a working-space `D` moves the linear output by
about `k D`, `k` = 1.66 for `r`, 1.13 for `g`, 1.12 for `b`. So
`D = ((v_c/255)^2.2 - (v_t/255)^2.2) / k`, with `v_c` the channel's percentile
0.1 before the curve and `v_t` the level to match. Example: `b` 53 against `r`
49 gives `D` = 0.0050 / 1.12 = 0.0045 and `offset` = -0.009 (the 53 came out
as 49). Then re-check, as above.

## Changing L after the black adjustments

The colour-correction offset and the curve's black point are fixed amounts,
but changing `L` (or EV) scales the linear image. Lowering `L` on one frame (a
low-key frame) with the roll's offset and black point unchanged crushed it
(62% of blue at 0). With `k = L_new / L_old` (`k = 2^EV` for an EV change):

- offset: `offset * k` (the stored value; its shift `offset/2` scales alike);
- black point: scale the black the rule measured (`x0 + 5/255`) through the
  sRGB curve, `x0_new = enc(k * dec(x0 + 5/255)) - 5/255`, with `dec(e) =
  ((e + 0.055) / 1.055)^2.4` and `enc(v) = 1.055 v^(1/2.4) - 0.055` (curve x
  is sRGB-encoded). Not `x0 * k^(1/2.2)`: near black the sRGB curve rises
  like `k^0.55`, not `k^0.45`, so that rule leaves the blacks too high after
  a brightening (and clips a little after a darkening).

Measured on FILM07489 (real art-cli, `image_stats` percentile 0.1, `L` 8000
unless noted): the black before the curve is r37 g37 b42; at EV +0.8
(`k` 1.74) r50 g50 b57, x1.35 = `k^0.54` (the 2.2 rule predicts 47); `L`
16000 gives 54, `L` 4000 gives 24. With `x0` 0.125 the blacks after the curve
are r7 g7 b4. At EV +0.8 they become r24 g24 b34 with the same `x0`, r13 g13
b23 with the 2.2 rule (0.161), r7 g7 b18 with the formula (0.177): blue stays
higher, its black was already above the others (its own offset, scaled by
`k`). With a red -0.006 and blue -0.016 offset as well, the blacks at EV 0 are
r5 g14 b0 and after EV +0.8 (offsets x `k`) r13 g23 b14 by the rule, r6 g18 b8
by the formula. A better first estimate, not exact: `clipped_low` per channel
decides.

Direction, which is easy to get backwards: raising `x0` makes the blacks
DARKER (more of the shadows map to 0), lowering it lifts them (x0 0.10, 0.125,
0.15 gave blacks r14, r7, r0, with 0.4% of red clipped at 0.15).

Example: L 34000 -> 17000, offset -0.1 -> -0.05, x0 0.25 -> ~0.17. Then
re-check `clipped_low`.

## Mixed light

With several light sources in a frame (lamps plus daylight, coloured
spotlights), no single balance is right everywhere: balance on the subject's
neutrals (white paint on the aircraft, not the floor under another lamp) and
leave the rest. Keep a cast that is the real colour of the light (a warm lamp
lighting a bomb bay): neutralising it looks wrong. If a cast looks odd next to
neighbouring frames of the same place, it is cheap to re-check the reference
spot and the black offsets, but it may well be the lamp. Say which frames you
left warm, cool or tinted, and why.

## Lighting groups

One roll often mixes light: outdoor daylight, dusk, and several kinds of
indoor lamps. A single "indoor" balance left one hangar frame visibly green.
Group by looking, not by clustering numbers:

1. Make a contact sheet of the whole roll after a first inversion (roll
   ratios, one rough reference; `contact_sheet`, which keeps each pass) and
   look at it: sort the frames by the light
   you can see (sun, overcast, dusk, tungsten, fluorescent/LED, mixed, a
   single coloured lamp). Casts that differ between frames of the same scene
   point at different light even when the place is the same.
2. Per group, take the representative with good contrast (shadows and
   highlights both present) and neutral objects of independent materials;
   tune it fully (white balance, output level, per-channel black offset,
   black point) and save it as the group's preset. The preset carries the
   ratios, `RefOutput` L, the black offset and black point, not the white
   balance: that is `RefInput`, per frame, so leave it out of the preset.
   Fix the group's `g0` here together with `L` (see "Reference point on the
   neutral line"): every frame of the group takes its `RefInput` at this `g0`,
   scaled for its scan exposure, or `L` means a different brightness on each
   frame.
3. Apply the preset to the group and look at the sheet again (a preset applied
   again after step 4 overwrites each frame's own curve, level, EV and black
   offset unless `apply_preset` gets an `exclude` for them). A frame that
   still stands out (a cast its neighbours don't have) gets its neutrals
   sampled: if they sit off the group's line (intercepts `ir`, `ib`, above,
   normalised to one scan exposure first, differing by more than ~0.03), it is
   in other light; move it or give it its own reference.
4. Per frame, check `image_stats` and adjust `L` (scaling the black
   adjustments, above).
5. Frames that fit no group (a single warm lamp, mixed light) get their own
   settings; say which and why.

The numbers confirm a doubt from looking; they don't replace it. The ~0.03
is a guide, not a cut-off: in a mixed hangar the intercepts spread by more
inside one group (about 0.1 in two hangar groups of one roll), which is why
the split rests on looking first.
