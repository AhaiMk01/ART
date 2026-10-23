# Film negative reference

The skill gives the procedure; this file gives method equations and evidence limits. The skill converts with NamiColor only; a profile saved with another method (power-law) is not converted here.

## Viewing previews

ART can return previews as native MCP image blocks, so a client need not decode a
JPEG file through its file reader. `render_preview(inline=true)` does this for a
call; starting `art-mcp-render` with `--inline-previews` also returns contact
sheets and pass comparisons as images. Restart or reload the MCP server after
changing its launch options.

Use a successfully displayed image for visual decisions. If a file reader
returns JPEG bytes as text, use the native image response to restore viewing
before continuing. An image block confirms delivery, not correct interpretation:
check the visible content, and use larger or smaller-group views when a sheet
does not resolve the question.

## Per-frame geometry

A shared camera/light/input basis is a radiometric assumption, not registration.
Film transport can change position, scale and angle relative to the sensor.
Inspect each frame's picture boundaries and orientation before using its content
for estimation. An uninverted or temporary positive view can clarify uncertain
edges; choose the view from the question being investigated. RAW decoding and
input colour management still influence the view and the samples.
For each frame:

1. Inspect its uncropped view and locate all four picture boundaries. A common
   film format is only an aspect-ratio hint. Automatic thresholds propose a
   boundary; bright sky, white walls and dark scene edges can defeat them.
2. Set upright coarse orientation first; use people, readable text and gravity
   or building lines where available, rather than the sensor's aspect ratio.
   Apply coarse rotation in a separate edit before the crop request: crop
   bounds are checked against the active frame. Coarse rotation is the raw edit
   `[Coarse Transformation] Rotate` = `0`, `90`, `180` or `270`, in degrees
   clockwise and added to the camera's orientation tag. Render to confirm that orientation before
   measuring the rectangle.
   Identify the crop in that resulting frame. If alignment needs fine rotation,
   inspect the transformed result.
   Choose any inward margin from that frame's edge uncertainty, not a fixed
   pixel inset copied across the roll.
3. Apply the measured rectangle per frame with `items`. Check `failed` and
   each item's `error`, then confirm the stored rotation and crop with
   `get_profile`; a returned batch result alone does not mean the edits applied.
   Inspect all four edges and corners at adequate preview size. Correct white strips,
   holder or rebate; preserve actual scene content. Check rounded picture
   corners as well as the straight edges: a border can survive a side midpoint
   check. A representative crop, aspect ratio, numerical edge test or small
   whole-roll thumbnails cannot certify the other frames.
4. Keep enough geometry evidence to explain the chosen framing and revisit an
   uncertain edge. After inversion, inspect any newly visible borders and correct
   the geometry before trusting content-derived adjustments.
5. Revisit sampling locations when geometry changes; locate references separately
   in each frame. Refresh cropped statistics and neutral proposals, and refit
   adjustments derived from excluded borders. Interior pre-inversion samples
   remain usable when their material and full-frame coordinates are still valid.

For an unwarped cropped preview in the same coarse-rotated frame as the picker:

```
x = crop.x + px * crop.w / preview_w
y = crop.y + py * crop.h / preview_h
```

Use that frame's crop and actual preview dimensions. Fine rotation or perspective
warps invalidate this simple mapping; use an unwarped sampling view instead.
`sample_spots` ignores crop, so a verified base patch may be sampled outside the
final crop without leaving an unwanted border in the delivered picture.

## NamiColor and the processing basis

Keep input characterization, inversion and display rendering separate:

```
RAW decode and preprocessing
-> input-profile conversion to declared working RGB
-> input_gamma (unprofiled non-RAW scans only)
-> optional digital mask in effective log-transmission density
-> channel terms: namicolor_input_gain, gain, shift (black and master terms 0)
-> FitBase (off)
-> Cineon decode with W (cineon_reference_white) into ART's signed linear RGB
-> scene exposure, colour and tonal adjustments in the declared working basis
-> output colour management and display export
```

Three kinds of setting act in this chain; keep them apart when reasoning
and when reporting:

- encoding convention: the constants 95 and 685, `b`, and
  `cineon_reference_white` (W). They define what a code means inside
  NamiColor's decode.
  They do not look at the picture;
- channel alignment: `namicolor_gain` and `namicolor_shift` (and
  `namicolor_input_gain`) come only from `scripts/pooled_fit.py`. Master and
  black terms stay 0 and FitBase stays off (`namicolor_fit_base` false; the
  script's fold assumes it);
- aesthetic grading: scene exposure and the tone curve (brightness goes
  here, never into master or black). These are choices about the look, not
  measurements.

Use `method=namicolor`, `film_type=negative`, `color_space=working` for this
path. Select and record the actual input and working profiles; no RGB gamut
is implied by the word Cineon. A camera-supplied profile does not characterize
the backlight, flare, illumination uniformity or film dyes. A linear TIFF
handoff is optional, not a prerequisite for inversion inside ART.

With `color_space=working` the input profile acts before the inversion, on
the light through the negative, not on scene colour. A DCP's hue/saturation
map and look table are colour-appearance corrections for scene light on the
sensor and have no meaning for film densities: turn them off before fitting
(raw edits `[Color Management] ApplyHueSatMap=false` and
`ApplyLookTable=false`) and keep them off for the roll. The matrix part of
the profile is still only an approximation of the film channels.

Keep capture white balance consistent, or account for its change before
sharing conversion parameters. A per-frame camera white balance can alter
the input channels even when the physical digitization setup is unchanged.

With normalized linear input `x_c = I_c / 65535`,
`T_c = max(x_c, 1e-10)`. RAW and profile-linearized inputs require
`input_gamma=1`; a source-transfer override is only for an explicitly
unprofiled non-RAW scan. With the default Identity mask, negative film uses:

```
q0_c = 1 - NamiColorInputGain * log10(16 * T_c)
den_c = 1 - NamiColorGain_c - NamiColorMasterGain + NamiColorBlack_c
q_c = (q0_c + NamiColorShift_c + NamiColorMasterShift + NamiColorBlack_c) / den_c
```

`den_c` must be positive. `q_c` is the normalized Cineon code (`q = code/1023`;
`q=0` is code 0, `q=1` is code 1023). FitBase (`namicolor_fit_base`) stays
off; a sidecar saved below version 1058 without `NamiColorFitBaseAnchor`
loads its FitBase anchor as `legacy`, so leave an old profile's FitBase
alone and do not enable it on one.

ART then decodes this normalized Cineon coordinate to signed linear RGB. These coordinates are an effective capture
model, not measured optical density or a camera/film calibration.

With master and black terms 0, relative slopes are proportional to
`NamiColorInputGain / den_c`. Never set slopes or shifts by hand; the fold of
the pooled fit ("Pooled roll fit", step 7) gives them. The coordinates are not
a reflectance measurement.

### Optional NamiColor digital mask

Identity is the default and preserves the original channel-wise arithmetic.
For a nonidentity preset, after any permitted source-transfer decode, ART forms
effective input density and applies the row-major matrix before log-input slope
and per-channel denominator, shift, black terms and FitBase:

```
D_c = -log10(max(decoded_source_c / 65535, 1e-10))
Dmask = 0.7 + M * (D - 0.7)
q0_c = 1 + NamiColorInputGain * (Dmask_c - log10(16))  # negative
q0_c = 0.8 - NamiColorInputGain * Dmask_c             # reversal
```

The fixed pivot 0.7 is a numerical density anchor, not a measured film property.
This is an effective capture model in the declared RGB basis, not a measured
spectral dye separation.

Use `matrix_preset=custom` to edit the nine finite `matrix` coefficients.
Every nonidentity preset requires `matrix_basis`, versioned JSON containing
`v=1`, `color_space`, `profile`, `input_gamma` (a string), and `source`.
When the profile has ICC content, retain its `content` digest as captured by
ART's binding workflow; missing or different content is also a mismatch.
Use the actual source identity and processing settings, not invented labels.
Missing or mismatched bindings fail processing; changing space, profile,
transfer or capture source requires reconsidering the calibration, not merely
rewriting a binding to silence the error. Identity ignores retained matrix
and binding data. Existing NamiColor sidecars older than version 1055 reset an
explicit formerly dormant preset to Identity while retaining its coefficients,
binding and calibration note.
Explicit typed nonidentity matrix/preset/binding edits opt an older working
profile into version 1055; unrelated edits leave its version unchanged.

Status M reference rows are an uncalibrated reference, not a universal digital
mask or a substitute for capture characterization. A custom mask adds colour
coupling that can trade off against input characterization and channel slopes.
A pair of neutral patches can constrain channel alignment, but cannot identify
a unique 3×3 colour-coupling matrix.
Fit it only with enough independent evidence and record film, illumination,
capture conditions, processing basis and limitations in `calibration_note`.
After changing it, refit the pooled fit through the mask (`--matrix`, the same nine values); compare tonal levels, unfitted materials and reserved
frames with the same diagnostic viewing response. Do not infer a measured
calibration from a neutral patch or a more pleasing print look.


## Processing order and domains

ART order for a film negative: pre-inversion corrections, inversion, then positive-domain tools.
- Vignetting: lens-profile correction (lensfun, LCP, EXIF; raw only, applied pre-inversion) and a raw flat-field are the right tools. The manual Vignetting Correction acts on the inverted positive, so it is wrong for a negative. Measured on a synthetic negative with a 30% corner falloff: the positive's edge/centre was 1.45; Amount +50 worsened it to 1.91. The falloff also adds a colour cast that no neutral post-inversion gain can remove. Scans (TIFF) have no pre-inversion vignetting path in ART; ART warns when the manual tool is non-zero with film negative enabled.
- Denoise: ART denoises the inverted positive (a sidecar before version 1061 may need its strength retuned). It applies to full-resolution output and 1:1 crops; the preview has no denoise. Check the darkest and a midtone area at 1:1.
- Flare: `flare` = r;g;b, a linear transmission fraction 0..0.5 per channel subtracted from the normalised scan before the log (absent = 0). To estimate it, `sample_spots(stage=source)` on a fully OPAQUE area (film holder, blocked mask) in the same frame and lighting. Do not use the film base or rebate: that is not flare. The result is an estimate; subtracting too much clips dense negative areas, so check the shadows after changing it.

## NamiColor's internal Cineon decode

NamiColor works in Cineon code space internally and decodes to linear RGB
before the rest of ART. Let `W = CineonReferenceWhite` and
`b = 10^((95 - 685) / 300)`; the decode is
`L = W*b * expm1((1023*q - 95)/300 * ln(10)) / (1-b)`. Code 95 is linear
zero and code 685 is linear `W`; every 300 codes is a factor of 10 in linear
light. New profiles default to `W = 0.9`; a sidecar below version 1058
without the key loads `W = 1`. W only scales the decoded positive.

ART has no print LUT, paper curve or Cineon export (removed in version
1061; old keys are ignored). For a print-film look, run NamiColor and the
Cineon LUT in DaVinci Resolve. For a linear handoff, export 32-bit float TIFF
with output profile `(none)`: ART writes working-space RGB with its linear
working ICC profile, and over-white values survive. Scene Exposure clamps
negative RGB at zero, as for any other source.

Profiles from version 1060 floor transmission at one 16-bit code
(`TransmissionFloor`, 1/65535) before the log, so raw values at black (dense
lamps, emitters) decode to large but finite values; sidecars before 1060 keep
1e-10 and can fail with "non-finite sample" where a steep fit meets them.

### Shadow black

The `- 1` in the decode (the `expm1`) subtracts `c0 = W*b/(1-b)` (0.0098 at
W 0.9, 6.5 stops below W) from every channel. Without it the decode is the
pure power law of the densities, where a density error is a constant colour
ratio at every level. With it, an exact neutral stays neutral, but any
residual grows as the values approach `c0`: a 0.25-stop density error becomes
a cast of more than a stop in deep shadow. On six Hawaii frames, the median
red/green and blue/green ratios over the darkest 10% of pixels were
+0.5..+1.5 and +1.0..+2.6 stops (purple shadows); with the black taken off
luminance they were +0.06..+0.28 and +0.3..+0.6, about the same at every
level.

`scripts/black_curve.py --ev EV [--w W]` prints the stock-tool recipe:
- `exposure.black` = `-c0 * 2^EV * 65535 / 2000`. ART's exposure computes
  `v * 2^EV - black * 2000`, so a negative black adds `c0` back to every
  channel: the pure power law.
- curve 1 in Luminance mode: `Y -> max(Y - c0 * 2^EV, 0)`, given as
  sRGB-gamma-encoded points. ART scales R, G and B by the new/old luminance
  ratio, so black depth is unchanged and the shadow keeps its hue.

ART applies the tone curve tool's parts in the order contrast, curve 1,
curve 2. The black has to act before any look, so `contrast` stays 0 and the
look goes on curve 2 (`mode2`, Neutral). On 03319 the ART render matched a
NumPy computation of the same recipe to 0.000 stops of luminance. The
recipe assumes `[ToneCurve] WhitePoint` 1: the Luminance curve clips channels
above 1.0, so set exposure so that highlights with detail stay below it, and
check clipping as usual. What is left after the black is the real density
residual (the fit, flare or the basis), now at its true size.

## Observing each stage

One film conversion has three observable stages. Name the stage, space,
transfer and unit with every number you quote.

| What | Tool and stage | Space / transfer | Unit |
|---|---|---|---|
| Pre-inversion samples | `sample_spots` `stage: "source"` (default), `space` working or input | working space or camera space, linear, white-balanced | linear 0..65535 |
| Recovered light | `sample_spots` / `image_stats` / `render_preview` `stage: "converted"` | working space (the profile's), linear, right after film + colour conversion, before exposure and grading | linear 0..65535; may be negative or above 65535 |
| Display statistics | `image_stats` `stage: "display"` (default) | the 8-bit output after the whole pipeline and output profile | 0..255; not linear |

- `render_preview` with `stage` converted shows those pixels through the
  sRGB curve (no colour management, crop applied, no marks): a look at the
  data, not a rendering.
- Source and converted spots come from the same pixels. `space` applies to
  `source` only; asking for `input` with another stage is refused. If Film
  Negative is off the result says `film: "disabled"`: the stage is then the
  plain image, not a conversion.
- `image_stats` with a stage returns per channel (r, g, b) `min`, `max`,
  `mean`, `p01`, `p50`, `p99`, `below` / `above` (pixels outside the fixed
  `range` [-6553.5, 131070]), `nonfinite` and, with `histogram`, `bins`
  counts (2..1024, default 256) over that range. Percentiles are exact
  (nearest rank over every finite value, out-of-range ones included), not
  read from the bins.
- Crop, region and downscale: the frame is the cropped frame (the working
  profile's crop applies). `region` is fractions of that cropped frame.
  `max_size` box-downscales the frame by averaging in linear light, so a
  downscaled distribution is narrower than the full-size one (0 = full size;
  large raws are slow). The `width`/`height` of the result are the measured
  size, `source_width`/`source_height` the cropped frame. Read spots, not
  downscaled histograms, to check an exact value.
- The Live server has no full-resolution stage tap: `image_stats` there
  measures the 8-bit preview only and refuses a stage; use the Render server.
  Live `sample_spots` does accept `stage`.
- Display statistics (percentiles, clipping, `lum`) are encoded output
  values after tone and output profile. They show what the picture looks
  like; do not quote them as linear values.

Clipping check on a final render: `image_stats` (Render, stage `display`)
gives per-channel `clipped_high` and `clipped_low`; judge them without
emitters and speculars (`lum_max`, or a `region` away from them), and look at
the picture where they sit. Tone-curve points are sRGB-encoded 0..1 (about
`image_stats` value / 255). Raising a curve black point darkens the blacks;
lowering it lifts them.

A steep fit can fail ART's finite-value checks during inversion. Preserve
the failure and the original parameters; clipping or zeroing invalid pixels
is not a successful conversion.

## Capture exposure normalization

The shared capture assumption and its exceptions are described in the skill.
For linear, black-level-corrected, unclipped input under that assumption,
model a frame's capture signal as `I_frame = s * I_reference`. Estimate:

```
s = (t_frame * ISO_frame / N_frame^2) / (t_ref * ISO_ref / N_ref^2)
```

`t` is capture shutter time and `N` the f-number. This is a signal-scaling
estimate, not a measurement of original film exposure; ISO scaling may be
camera-dependent. If aperture is unrecorded, a shutter/ISO ratio is conditional
on fixed aperture, not automatic compensation. Corroborate the shared light,
aperture and camera response before applying it; record remaining assumptions.
Auto exposure does not establish equal capture signals or equal original-scene
exposure. Black offsets, flare, clipping or changed illumination invalidate
a simple multiplier.

Use `I_frame / s` for joint fitting when the capture multiplier is supported.
Apply profile compensation to the unnormalized processing input once:

- NamiColor negative, InputGamma 1: with the denominator, master and black
  terms fixed, use
  `NamiColorShift_frame,c = NamiColorShift_ref,c + NamiColorInputGain*log10(s)`.
  This preserves q, including a fixed FitBase; compensate capture separately
  from scene exposure and final presentation.
Recompute capture compensation after changing slopes. The channel differences
here are predicted by the shared model, not separately fitted shutter-group
colour balances.

The compensation preserves the inversion coordinate. Floor-clamped source samples are outside
the derivation. Normalize the samples for fitting and compensate the original
input in the profile; applying both corrections to the processing input would
double-count capture exposure.

## Pooled roll fit (NamiColor)

A roll shares film and digitization, so its channel slopes are common; each
frame adds its own offset (scene light, printer light). Fit them together
(as Fuji's roll-pooled grey axis, US 6665434: `Dg = a*Dr + b`).

`scripts/pooled_fit.py` (run with `uv run`; input format in its docstring)
does steps 2 to 7 and prints the slope checks, the D_G range the slope was
checked over, each frame's shrinkage and how far its offset lies from the
rest of its light group. Use it rather than writing a fit, for any number
of frames, one included: where the picks cannot set the slope it takes the
prior and marks what is weak. The judgement (picks, basis, light groups,
what a deviation means) stays yours.

1. Evidence: the table from "Choosing neutral references". Fit `material`
   rows only; read `uncertain` rows against the fit (a frame with no
   `material` row takes its weak offset from them); `C` rows only describe
   the light.
2. One observation per object per frame (average its squares).
   `D = -log10(avg/65535)`, `sd_D = sd / (avg * ln10) / sqrt(min(N, 64))`,
   `var = sd_c^2 + k^2 sd_G^2 + 0.008^2`.
3. Fit per channel `D_c = k_c * D_G + o_cf`: one slope, one offset per
   frame. Demean within frames, start from within-frame Theil-Sen slopes,
   iterate Huber weights (c 1.345) on studentized residuals; then give every
   frame its offset from the shared slope.
4. Check that the neutral axis is straight: with `material` rows spanning
   about 0.5 D_G or more, add a term `q_c * (D_G - 1.2)^2` to step 3. A
   significant `q` (beyond about 2.5 standard errors) that a positive
   offset in that channel removes is an additive offset in the scan
   (scanner flare or a pedestal): subtract the offset that brings `q` to
   zero from the samples, set it as NamiColor `Flare` (offset / 65535)
   and refit. A bend that no positive offset removes is not an offset;
   report it.
5. Trust the slope only when several frames carry it. Leave each frame out
   and bootstrap whole frames. The slope is not set when fewer than three
   frames have `material` rows at two levels well apart in D_G, when one
   frame moves it on its own, when it jumps between values as single rows
   change basis, or when `uncertain` rows in three or more frames disagree with it
   beyond tolerance, all in one direction, against `material` rows of
   their own frames. A narrow
   interval does not show it is set. A frame whose neutrals split
   by light (seen, and beyond tolerance) gives an offset but no slope. An
   unset slope on a roll of many frames usually means the search was thin,
   not that the roll lacks evidence: a wrong slope pushes highlights and
   shadows opposite ways on every frame, which no offset fixes. Before
   falling back, search the frames without `material` rows again for a
   light and a dark neutral each, under one light (white paint and a tyre,
   asphalt), mark each such frame `"searches": 2` in the picks (the
   script lists them and prints no NamiColor settings until then) and refit. When
   the slope is still not set, take it from a preset (an entry of the slope
   record below for the same film and setup) and fit only the offsets.
   Without one, never pick a value by hand: give
   the script a prior (`--prior`): the slopes of the nearest entry for the
   same camera, light and basis (another stock if need be; used only as a
   prior, not as a preset), or `1,1,0.15` when nothing matches; the roll's
   own evidence moves it as far as it supports. A
   preset is a slope a roll set; another frame's prior-weighted or weak
   result is not one. Report
   the prior, its spread and the result. Slopes belong to the processing
   basis they were fitted in (colour space, input profile and its options,
   input gamma): a preset from another basis does not transfer, refit it
   there.
6. Shrink each frame's offset toward its light group (frames under one kind
   of light: daylight, one interior; never a roll mean across lights; a
   frame whose light no other frame shares, such as a lamp-lit room among
   window-lit ones, is a group of its own and keeps its fitted offset):
   `o_final = mean + lam * (o_fit - mean)`, `lam = tau^2 / (tau^2 + SE^2)`,
   SE from the frame's weights times the robust scale, `tau^2` the spread of
   offsets around their group mean minus the mean SE^2 (R and B pooled),
   `mean` weighted by `1/(tau^2 + SE^2)`. Groups follow the frame's main
   light (sun, overcast sky, one interior), not where a few of its
   neutrals happen to sit: a sunlit or overcast frame with neutrals in
   shade is still a daylight frame, and a skylight-shade group's mean
   warms any frame lit otherwise. Never group by a capture setting
   (shutter, session, frame order): the capture difference is removed by exposure normalization, which predicts
   no colour. Split off a capture subset only on evidence independent of
   scene content (unexposed film, one reference seen in both subsets), not
   because a few of its frames' offsets differ; that difference is part of
   the spread `tau` measures. A frame without neutrals takes the mean of
   its light group over the whole roll. Count a frame as weak when one
   material sets its offset, or only neutrals brighter than the D_G range
   where the slope was checked (neutral there, mid-tones can be off).
7. Fold into NamiColor (input gain `g`, master and black 0), keeping
   green's `den_G` and `s_G`, `a = 1 - g * log10(16)`: `den_c = k_c * den_G`,
   `gain_c = 1 - den_c`, `shift_c = k_c * (a + s_G) - a - g * o_final,cf`,
   plus `g * log10(s)` on every channel for the frame's capture exposure.
   Master and black stay 0 after the fold: they are divided by each
   channel's `den_c`, so with unequal slopes they shift colour as well as
   level. Set brightness with exposure and the tone curve.
   The overall contrast is `e = 1023/300 * g / den_G` (linear light =
   `10^(e*D)`); keep `g / den_G = 500/1023 = 0.489` (the script's default):
   Cineon spacing, a scene-linear positive. ART's default input gain 1 with
   `den_G` 1 doubles `e`: blown highlights, crushed shadows, exaggerated
   colour. Print-like contrast comes from the tone curve, never from `g`.
   Anchor green with `--base`: the script sets `s_G` so the film base
   decodes to code 95, Cineon black, and everything on the film to 0 or
   above. A guessed `s_G` can put real detail below code 95: it decodes
   negative, and exposure clamps it to 0 where no later step recovers it.
   It warns when a neutral is thinner than the anchor. After applying,
   check `image_stats(stage=converted)` per channel for values below 0
   on the picture area. Its JSON holds every setting of the fold (input
   gain, gains, shifts, master, black, FitBase, flare): apply all of them.

Report each frame's offset and lam in plain terms (warm late sun, shop
light). The sidecar takes the slopes and offsets as the script prints them.
Keeping a real warm or cool light is the user's choice ("Adapt scenes" in the
skill): to leave the roll's daylight conversion unadjusted, a frame takes its
light group's mean offset (the script's group mean) in place of its own.
Never nudge a channel's offset or slope by eye after
the fit: a render that still looks off is evidence about the picks, the
basis or the light groups; go back there, or report it. Exposure and the
curve are per-frame tonal choices, set against the clipping check ("Observing each stage"). Sunlit neutrals also
carry skylight, so a daylight frame corrected to them in full can look
warm; that is the light, reported, not a reason to nudge.
An automatic white balance is a cross-check, never the prior.

### Slope record

Presets and priors come from `film-slopes.json`, kept beside the rolls (the
roll's folder or a parent; look for it before fitting). It lists slopes that
rolls set, never prior-weighted results:

```json
[{"roll": "FILM011", "film": "Kodak UltraMax 400",
  "camera": "Sony A7III", "light": "white LED panel",
  "basis": {"input_profile": "(cameraICC)", "working": "Rec2020",
            "namicolor_colorspace": 1, "input_gamma": 1},
  "kR": 0.781, "kB": 1.030,
  "kR_boot90": [0.772, 0.789], "kB_boot90": [1.012, 1.051]}]
```

An entry with the same film, camera, light and basis is a preset
(`--slopes`). Otherwise the nearest entries with the same camera, light and
basis give the prior (`--prior kR,kB,sd`): one entry gives its slopes and
the script's default sd; several give their mean and their spread when it
is wider. Name the entries used in the report. When the user has no record,
use the `1,1,0.15` prior. When a roll sets its slope, offer to add its
entry; do not add it without the user's agreement.

## Choosing neutral references

Choose by material, found by looking at the picture, never by how grey a
spot reads, by whether it agrees with a fit (that is circular), or by what
the basis makes the script do.

Principles:

- Clean frame: before picking, look at the whole frame at readable size
  for contamination, and judge it by kind, not by distance from the squares.
  Light that spreads (light leaks, haze or flare bands, veiling glare, glass
  in front of the lens such as a windscreen) fogs the whole frame, also
  where it looks clean: such a frame does not help set the slopes; at most
  it gives its own offset, at lower confidence. Local marks (scratches,
  fibres, dust) only spoil what they cover: keep squares well away from
  them. Report what you saw either way.
- Neutral by material: paint (white, grey, black), tyre rubber, dry
  asphalt, and deep shadow under an object on such a surface in a frame
  without direct sun (in a sunlit frame it is lit by the sky: `uncertain`
  or `C`). Never `material`: stone, concrete (most sidewalks and paths), gravel, brick, roofs, bare metal,
  foliage, fabric or anything coloured. An unlisted material (vinyl,
  plastic, cardboard, plaster or whitewash walls) is `uncertain`. White
  means white: cream, ivory, beige and pastel paint are coloured, and
  building facades often are. On an uncorrected render they look alike,
  so a paint's whiteness is a claim to check, not a reason to doubt every
  white. Demote a white on evidence: its frame's offset stands apart from
  the rest of its light, or it reads tinted beside a sure neutral in the
  same frame. Without such evidence it stays `material`; demoting good
  whites leaves the frame to a borrowed offset. Natural surfaces (rock,
  soil, bark, sand) take their colour from their kind and weathering:
  `uncertain` only when their kind is a grey one (grey rock); other natural
  surfaces are not sampled.
- One light: surfaces lit by the frame's main light (a subject wholly in
  shade or indoors: that light). Undersides, back-lit faces and shadows on
  grass take the colour of what lights them; in a sunlit frame a cast
  shadow is lit by the sky, another light, so it is not `material`. Distant surfaces (hills, far
  buildings) are seen through air that adds its own light: not neutral
  evidence.
- Measurable: well inside one material, away from edges, text and detail.
  Thin or small objects on a contrasting surround read diluted; dark
  surfaces at a grazing angle and glossy black paint carry sheen or sky
  reflections (`uncertain`). Where neutrals are few, still sample
  every candidate; only squares beyond doubt are `material`.
- Independent: several objects, dark, mid and bright, dark and bright in the
  same frame where possible. Squares on one object are one observation.
- Searched: every object, background and ground included, for its darkest
  and brightest large neutral areas (tyre sidewalls, shadow under a car,
  large painted panels, sign backgrounds, road; a shadow only without direct sun). Move a failing square
  before giving up on it.

Steps:

1. Render each frame at about 1600 px; write one sentence on its content,
   light and any contamination (see Clean frame); list candidate areas.
2. Place squares on every candidate area: ten or more per frame on four or
   more objects across the bands, doubtful ones included (they become
   `uncertain`, not omitted); a missed neutral costs more than a sampled
   one. A frame with no candidate gets none: record the gap and never
   fill it with excluded materials. Leave a margin of the same material
   around each.
3. Zoom check (`render_preview`, `marks`, `zoom: true`); move squares that
   touch anything else.
4. Sample (`sample_spots`, stage source, per-spot `size`); sample again after
   every move. Same-frame checks, `D = -log10(avg/65535)`:
   - sd above about twice that of similar squares: move or drop;
   - a black more than about 0.08 D_G lighter than the frame's largest
     black: diluted;
   - per channel, one material within about 15 mD, different materials at
     similar D_G within about 25 mD.
5. Record per square: frame, material, `object_id` (one per object; a
   separately painted part or a tyre is its own), x, y, size, avg, sd, D_G,
   basis (`material` or `uncertain`) and reason. Sky, clouds and surfaces
   under another light may be `C` rows, to read the light. Note empty bands.
   Show the picks: one preview per frame with every square marked by its
   basis and number (`M1`, `U1`, `C1`), given to the user with the table,
   and again after step 6 if the basis changed.
6. After the pooled fit, revise the basis and refit until nothing changes;
   decide each round from one fit and log each change with its reason.
   - A disagreement is two rows of a frame beyond the step 4 tolerance in a
     channel, at the fitted slope, over a D_G gap that channel can compare
     (half the slope interval times the gap well below the tolerance). Low
     robust weight only says where to look.
   - Look at both sides; demote each side with a visible reason (second
     light, reflection, uncertain material), and apply that reason to every
     row in the roll that shares it. No visible reason: change nothing.
   - Promote `uncertain` only when its own doubt is cleared: a closer look
     for material or light, a larger clean square (replacing the old one)
     for measurability. Agreement supports but does not clear; lying on the
     fitted line never counts. A demoted row stays demoted.
