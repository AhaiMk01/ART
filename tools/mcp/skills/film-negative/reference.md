# Film negative reference

The skill gives the procedure; this file gives method equations and evidence limits. New conversions use NamiColor. Density and power-law sections support explicitly selected methods and retained profiles; their controls are not interchangeable.

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
   clockwise and added to the camera's orientation tag. Render to confirm. Render that orientation before
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
-> endpoint terms: namicolor_input_gain, black, gain, shift, master terms
-> FitBase (fit_base_anchor)
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
- endpoint estimation: `namicolor_black`, `namicolor_gain`,
  `namicolor_shift`, the master terms, `namicolor_input_gain` and FitBase
  place the film base and a chosen white on codes, per image or per roll,
  from picture evidence (sample_spots, luminance, inspection);
- aesthetic grading: scene exposure, curves and colour correction. These
  are choices about the look, not measurements.

Use `method=namicolor`, `film_type=negative`, `color_space=working` for this
path. Select and record the actual input and working profiles; no RGB gamut
is implied by the word Cineon. A camera-supplied profile does not characterize
the backlight, flare, illumination uniformity or film dyes. A linear TIFF
handoff is optional, not a prerequisite for inversion inside ART.

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
`q=0` is code 0, `q=1` is code 1023). Optional FitBase (`namicolor_fit_base`)
remaps it, and `fit_base_anchor` says how:

- `code95` (default for profiles saved at version 1058 or later):
  `q' = (95 + 928*q)/1023`. Normalized 0 lands exactly on code 95 (linear
  zero) and 1 stays on code 1023; the map is linear in `q`;
- `legacy`: `q' = (q + 93/1023)/(1 + 93/1023)`, which sends `q=0` to about
  code 85.25. A sidecar below version 1058 without `NamiColorFitBaseAnchor` loads as
  `legacy` so it renders as before; an explicit value always wins. The MCP
  refuses to enable `namicolor_fit_base` on such a sidecar unless
  `fit_base_anchor` is given, since the meaning differs: re-save it in ART
  first, or set the anchor explicitly.

ART then decodes this normalized Cineon coordinate to signed linear RGB. These coordinates are an effective capture
model, not measured optical density or a camera/film calibration.

With master and black terms fixed, relative slopes are proportional to
`NamiColorInputGain / den_c`. Hold one channel's slope fixed while estimating
the relative slopes. For a declared source anchor `T_anchor,c` and desired
coordinate `q_anchor,c`, initialize the channel shift as
`q_anchor,c * den_c - q0_anchor,c - MasterShift - Black_c` when FitBase is
off; undo FitBase first when it is on (for `code95`,
`q = (1023*q' - 95)/928`). Re-evaluate the same anchor after
changing slopes. The chosen output coordinate is an assumption, not a
reflectance measurement. Use dark and bright evidence together, then check
unfitted materials and frames; multiple spots on one object only check local
consistency.

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

The fixed pivot 0.7 is a numerical density anchor, not measured film Dmin.
This is an effective capture model in the declared RGB basis, not a measured
spectral dye separation. Density's matrix order and printer-light controls
remain separate; its film-base picker does not become a NamiColor control.

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
After changing it, recompute any source anchors through the mask and refit
channel alignment; compare tonal levels, unfitted materials and reserved
frames with the same diagnostic viewing response. Do not infer a measured
calibration from a neutral patch or a more pleasing print look.


## Luminance and endpoint evidence

Inspect an ungraded positive before selecting near-black or diffuse-white
references. Decode the transfer before computing linear luminance:
`Y = m_YR*R + m_YG*G + m_YB*B`, using the declared RGB-to-XYZ matrix's
Y row. A grayscale view can encode that Y with the fixed diagnostic display
curve. It is neither an RGB average nor a weighted sum of Cineon code values.
Label clipping introduced by the view; inspect the linear or log data where
the display hides highlight or shadow differences.

Use existing image/data facilities to make a temporary diagnostic view from
a declared linear export. Leave the retained conversion unchanged.
For the stage you want to look at, use the matching tool and `stage` (see
"Observing each stage" below); previews and `image_stats` with the default
`stage` read display-encoded output, which is a different stage.

Use luminance to locate broad dark regions, then inspect their native-size
material, edges, texture and reflections. A dark pole interior or a shadowed
recess can be a candidate, not a universal reference. Check its RGB and
pre-inversion samples; select footprints that fit cleanly inside the region.
Dust, grain outliers, coloured dark material and black borders can be darker
than meaningful scene content.

Dmin is the film's minimum optical density, including base and fog. In a
negative it corresponds to the clearest, highest-transmission end and low
original-scene exposure. A credible unexposed film patch can constrain it;
a black object with finite reflected light does not establish it. If no
such patch or characterization exists, call the chosen scene reference a
near-black proxy and retain uncertainty. Luminance cannot determine the
three channel-specific density zero points by itself.

Likewise, a visually white material does not certify 90% reflectance or a
known illumination. Use comparable lighting and material evidence to select
a diffuse-white proxy. Verify candidates against other tonal levels and
independent materials before assigning endpoints. An image minimum,
percentile, neutral-looking pixel or a scope that fills its scale is not a
physical endpoint measurement.

Keep a baseline when testing proxy endpoints. A common affine mapping in
Cineon code space, `C_new = a*C_old + b`, can preserve the existing neutral
axis while changing the common span; identify the reference points and
whether the mapping precedes or follows a gamut conversion. Inspect the
result for lost shadow structure, flattened highlights and colour
changes. Return to the baseline if the selected proxies over-stretch the
scene rather than interpreting the loss as proof of calibration.

## Power-law

Schema summary: `out = ref_output * (in/ref_input)^exp`, clipped at 65535,
with `exp = -(green_exponent * (red_ratio, 1, blue_ratio))` and
`mult_c = ref_output_c / ref_input_c^exp_c`; `in` is the negative's linear
value (higher is a darker scene part). Unset references (`ref_input` 0;0;0)
are estimated by ART from the channel medians of the central 60% of the
frame and mapped to 65535/24 (grey, about 4% of full scale); the look then
depends on the image. When a request changes `ref_input` without `ref_output`
and both the current and the requested method are power_law, the server sets
`ref_output` to the grey `(L, L, L)` that keeps brightness, L being the
Rec.709 luminance (0.2126729, 0.7151521, 0.0721750) of what the profile
renders the new `ref_input` as (listed under `implied`). With an unset
reference it first estimates the medians by sampling a grid of 64 spots
(a warning says so); without sampling `ref_output` becomes grey 65535/24 and
a warning says brightness may change. Density and NamiColor infer no
references.


Film Negative per channel (ART): `out_c = RefOutput_c * (in_c / RefInput_c)^e_c`
with exponents `e = (-G*RedRatio, -G, -G*BlueRatio)`, `G` = `GreenExponent`
(1.5); clipped at 65535. Inputs are the
`sample_spots` values (the negative's, linear 0..65535).

## Processing order and domains

ART order for a film negative: pre-inversion corrections, inversion, then positive-domain tools.
- Vignetting: lens-profile correction (lensfun, LCP, EXIF; raw only, applied pre-inversion) and a raw flat-field are the right tools. The manual Vignetting Correction acts on the inverted positive, so it is wrong for a negative. Measured on a synthetic negative with a 30% corner falloff: the positive's edge/centre was 1.45; Amount +50 worsened it to 1.91. The falloff also adds a colour cast that no neutral post-inversion gain can remove. Scans (TIFF) have no pre-inversion vignetting path in ART; ART warns when the manual tool is non-zero with film negative enabled.
- Denoise: ART denoises the inverted positive (sidecars before version 1061 could denoise the negative first; that option is gone and such sidecars may need their strength retuned). It applies to full-resolution output and 1:1 crops; the preview has no denoise. Check the darkest and a midtone area at 1:1.
- Flare: `flare` = r;g;b, a linear transmission fraction 0..0.5 per channel subtracted from the normalised scan before the log (density and NamiColor only, not power-law; absent = 0). To estimate it, `sample_spots(stage=source)` on a fully OPAQUE area (film holder, blocked mask) in the same frame and lighting. Do not use the film base or rebate: that is Dmin, not flare. The result is an estimate; subtracting too much clips dense negative areas, so check the shadows after changing it.
- Grading: scene-linear gains (exposure, white balance) and printer-light offsets are domain-independent.

## Density method

Normalized source signal `x_c = I_c / 65535`. For a permitted unprofiled
non-RAW input override, `x_c = sign(x_c) * abs(x_c)^InputGamma`.
Then `T_c = max(x_c, 1e-10)`, `D_c = -log10(T_c)`, pivot `p = 0.7`.
For camera captures, this is an effective density coordinate, not calibrated
absolute optical density. RAW and profiled inputs require InputGamma 1.

Negative: `A_c = Dmax - p - DensityGamma * (D_c - p)`. With unit slopes, zero
gains, identity matrix and a linear target, `L_c = 10^(-Dmax) / T_c`.
`Dmax` 2.5 and `T` 0.01, 0.1, 1 give about 0.316228, 0.031623, 0.003162.

Reversal: `A_c = p + DensityGamma * (D_c - p)`. `Dmax` is unused. Identity
reproduces the input aside from the floor.

Anchor `P = 4.1 - Dmax` (negative) or `0.7` (reversal). Row-major matrix `M`:
`B_i = P + sum_j M_ij * (A_j - P)`, then
`C_i = P + h_i * (B_i - P) - RGBGains_i`. Linear target: `L_c = 10^(-C_c)`,
written back as `65535 * L_c`. A gain of `+0.1` multiplies that linear value
by `10^0.1` before the black offset.

Status M rows, not transposed: `(1.0197, 0.0317, 0.0091)`,
`(-0.0052, 0.8933, 0.0521)`, `(0.0131, -0.0011, 0.9712)`.

Film-base pick, negative only: sample before inversion, set
`RGBGains = C - 4.0` on all three channels, so the rebate maps to linear
`1e-4` before the black offset. Out of -3..3, or a bad sample:
no channel changes.

Black offset: `L = max(0, L - offset)` on the linear result.

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

Strong endpoint stretches can fail ART's finite-value checks during
inversion. Preserve the failure and original parameters; clipping or
zeroing invalid pixels is not a successful conversion.

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
- Density negative, InputGamma 1 and fixed slopes/matrix:

```
RGBGains_frame,i = RGBGains_ref,i
                 + DensityGamma * h_i * log10(s) * sum_j M_ij
```

For identity, the row sum is 1. A 0.4s frame against a 0.8s reference has
`s = 0.5`, hence gain changes of `-DensityGamma * h_i * log10(2)`.
The channel differences here are predicted by the shared model, not separately
fitted shutter-group colour balances. Add scene/output gains separately.
Recompute capture compensation after changing slopes or matrix.

The method-specific compensation preserves the inversion coordinate before
the black offset, and therefore its output when that setting stays fixed.
Floor-clamped source samples are outside
the derivation. Normalize the samples for fitting and compensate the original
input in the profile; applying both corrections to the processing input would
double-count capture exposure.

## Estimation without film base

Missing film base leaves the density zero point unknown. Under a linear,
black-level-corrected capture with constant illumination and negligible flare,
`D_1 - D_2 = -log10(I_1 / I_2)` within a channel still measures a relative
density difference. Clipping, residual black level, illumination gradients and
additive flare can invalidate this interpretation.

NamiColor's shifts and relative slopes can be estimated without a base sample;
use its declared-anchor equations above, then validate unfitted materials.
For two candidates in the same illumination, bright `B` and dark `K`, choose the
linear values they should decode to (`L_B > L_K`, assumptions) and their codes
`c = 685 + 300*log10(b + (1-b)*L/W)`, `b = 10^(-590/300)`. The target coordinate
gap is `dq = (c_B - c_K)/1023` with FitBase off, `(c_B - c_K)/928` with `code95`.
Then per channel `den_c = NamiColorInputGain * log10(T_K,c/T_B,c) / dq` (the
denominator must be positive), so `NamiColorGain_c = 1 - NamiColorMasterGain +
NamiColorBlack_c - den_c` with the black and master terms held; place the shift from one anchor as above and
re-check the other. Hold one channel's `den_c` (or the input gain) as the common
contrast and compare relative slopes against a third material.
That fit determines neither physical Dmin nor absolute scene reflectance.

### Pooled roll fit (NamiColor)

A roll shares film and digitization, so its channel slopes are common; each
frame adds its own offset (scene light, printer light). Fit them together
(as Fuji's roll-pooled grey axis, US 6665434: `Dg = a*Dr + b`).

1. Evidence: the table from "Choosing neutral references". Fit `material`
   rows only; read `uncertain` rows against the fit; `C` rows only describe
   the light.
2. One observation per object per frame (average its squares).
   `D = -log10(avg/65535)`, `sd_D = sd / (avg * ln10) / sqrt(min(N, 64))`,
   `var = sd_c^2 + k^2 sd_G^2 + 0.008^2`.
3. Fit per channel `D_c = k_c * D_G + o_cf`: one slope, one offset per
   frame. Demean within frames, start from within-frame Theil-Sen slopes,
   iterate Huber weights (c 1.345) on studentized residuals; then give every
   frame its offset from the shared slope.
4. Trust the slope only when several frames carry it. Leave each frame out
   and bootstrap whole frames. The slope is not set when fewer than three
   frames have `material` rows at two levels well apart in D_G, when one
   frame moves it on its own, when it jumps between values as single rows
   change basis, or when several `uncertain` rows disagree with it in the
   same direction against `material` rows of their own frames. A narrow
   interval does not show it is set. A frame whose neutrals split
   by light (seen, and beyond tolerance) gives an offset but no slope. When
   the slope is not set, take it from a preset for the same film and setup
   and fit only the offsets.
5. Shrink each frame's offset toward its light group (frames under one kind
   of light: daylight, one interior; never a roll mean across lights; a
   frame whose light no other frame shares, such as a lamp-lit room among
   window-lit ones, is a group of its own and keeps its fitted offset):
   `o_final = mean + lam * (o_fit - mean)`, `lam = tau^2 / (tau^2 + SE^2)`,
   SE from the frame's weights times the robust scale, `tau^2` the spread of
   offsets around their group mean minus the mean SE^2 (R and B pooled),
   `mean` weighted by `1/(tau^2 + SE^2)`. Count a frame as weak when one
   material sets its offset, or only neutrals brighter than the D_G range
   where the slope was checked (neutral there, mid-tones can be off).
6. Fold into NamiColor (input gain 1, master and black 0), keeping green's
   `den_G` and `s_G`, `a = 1 - log10(16)`: `den_c = k_c * den_G`,
   `gain_c = 1 - den_c`, `shift_c = k_c * (a + s_G) - a - o_final,cf`.

Report each frame's offset and lam in plain terms (warm late sun, shop
light). Removing a real warm or cool light is a choice: a frame whose light
the user wants can take part of its correction (`alpha * lam`, alpha < 1).
Sunlit neutrals also carry skylight, so a daylight frame corrected to them
in full can look warm: keep some of the cool, judged on the render and
reported.
An automatic white balance is a cross-check, never the prior.

### Density-specific reduction

For identity matrix, negative film and no black offset, the equations
reduce to `L_c = K_c * T_c^(-k_c)`, where:

```
g = DensityGamma
h_c = ChannelGamma_c
k_c = g * h_c
P = 4.1 - Dmax
a_c = P + h_c * (Dmax - p + g*p - P)
K_c = 10^(RGBGains_c - a_c)
```

The engine already exposes the required offset and slope controls; no film-base
sample is required. A common gain increase of `log10(2)` doubles linear output
before rendering. Relative gains balance channels. With unit slopes and `g = 1`,
`L_c = 10^(RGBGains_c - Dmax) / T_c`: changing Dmax and all gains equally
leaves this result unchanged. Fix Dmax as a model anchor while estimating gains.
Only products `g*h_c` determine these identity-path slopes; use common g first
and hold one channel slope fixed when estimating relative channel slopes.
These reductions do not describe a nonidentity matrix; use the full equations
for that path.

For a credible pair of neutral candidates in the same illumination, a desired
linear ratio `r = L_bright/L_dark > 1` gives the candidate channel slope
`k_c = log10(r) / log10(T_dark,c/T_bright,c)`, when the denominator is positive.
The chosen output ratio and the neutral interpretation are assumptions, not
measurements of scene reflectance. Fit several candidates/frames; a single
pair does not establish calibration. Weak or contradictory evidence keeps
shared slopes and lowers confidence.

A base pick is only an optional anchor. With identity, using current slopes
and the picked gains yields `L_c = 1e-4 * (T_base,c/T_c)^k_c` before rendering.
Changing slopes requires recalculating the anchor if it is to be retained.
That mapping does not determine useful output exposure, exact Cineon black,
or the film's characteristic curve.

Use a fixed input/working basis and viewing response when comparing candidates.
Common film/capture parameters transfer across frames; scene exposure and
illumination may need separate gain/local-colour adjustments. Validate on
frames outside the fitting set. Percentiles, apparent white objects and low
saturation are candidate constraints, not fabricated film base or certified
black/white patches. Without characterization, scene colour recovery remains
an estimate; no visual fit establishes a camera-specific density matrix.

### Refitting slopes and diagnosing crossover

Repeated highlight/shadow colour separation across unrelated scenes is a shared
fit warning, not evidence of several digitization setups. Diagnose in order:

1. **Isolate the view.** Preserve the baseline and freeze inversion, input basis
   and capture compensation. Compare the same positive curve in `Standard`
   and `Luminance` modes; `Standard` applies a nonlinear curve per channel and
   can change colour balance or clip one channel first. Also inspect a gentle
   monotone view without a hard black cutoff. Compare at similar brightness
   and contrast. A residual that survives is not explained by the view alone.
   Choose and freeze the diagnostic view before comparing inversion candidates.
2. **Refit jointly.** Use credible candidates across tonal levels and frames,
   separating original-scene illumination where evidence supports it. Compare
   bounded common slopes, then relative slopes with one channel held fixed.
   At each candidate, initialize offsets from a declared reference and refine
   them against the retained multi-point constraints. For NamiColor, use the
   anchor-preserving shift initialization in "NamiColor and the processing
   basis". For Density with a fixed Dmax anchor:

   ```
   C_anchor,i = P + h_i * (B_anchor,i - P) - G_i
   G_new,i = P + h_new,i * (B_new_anchor,i - P) - C_anchor,i
   ```

   `B_new_anchor` uses the candidate gamma/matrix and the same exposure-normalized
   input sample. This preserves the old reference output before the black offset;
   it is an offset initialization, not proof that the reference is neutral.
   A chosen grey level is a viewing assumption, not measured reflectance.
   Recompute frame exposure compensation after every slope/matrix change.
   A rejected candidate establishes only that this fit/view failed, not that
   channel-slope correction is impossible.
   Record each trial's method-specific slopes and offsets, anchor location and
   confidence, per-frame capture multipliers and compensation,
   fixed viewing response, and residuals in fit and reserved frames. A trial
   that reuses old gains or assigns the same gains to different capture
   exposures without their predicted compensation is invalid: correct that
   experiment before accepting or rejecting the model.
3. **Check transfer and explanation.** Render reserved frames and inspect their
   residuals by tonal level before adding scene grades. Retain the simplest
   candidate with supported cross-frame improvement; a global cast must not
   be hidden by local corrections. Assign a remaining cast to original-scene
   lighting/material only with evidence independent of the fitted output:
   comparable objects, credible illumination cues or known scene information.
   Input channel ratios evaluated through this same model cannot prove its
   output hue is the original hue. Otherwise record unresolved conversion error.

Likewise, the density span of arbitrary scene content does not establish a
film's full density range, additive flare or an optimal conversion gamma.

## Power-law: fitting RedRatio and BlueRatio

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

Choose by material, found by looking at the picture, never by how grey a
spot reads or by whether it agrees with a fit (that is circular).

Principles:

- Neutral by material: paint (white, grey, black), tyre rubber, dry
  asphalt, deep shadow on such a surface. Not stone, concrete (most
  sidewalks and paths), gravel,
  brick, roofs, bare metal, foliage, fabric or anything coloured; an
  unlisted material (vinyl, plastic, cardboard) is `uncertain`.
- One light: surfaces lit by the frame's main light (a subject wholly in
  shade or indoors: that light). Undersides, back-lit faces and shadows on
  grass take the colour of what lights them.
- Measurable: well inside one material, away from edges, text and detail.
  Thin or small objects on a contrasting surround read diluted; dark
  surfaces at a grazing angle carry sheen. Where neutrals are few, still sample
  every candidate; only squares beyond doubt are `material`.
- Independent: several objects, dark, mid and bright, dark and bright in the
  same frame where possible. Squares on one object are one observation.
- Searched: every object, background and ground included, for its darkest
  and brightest large neutral areas (tyre sidewalls, shadow under a car,
  large painted panels, sign backgrounds, road). Move a failing square
  before giving up on it.

Steps:

1. Render each frame at about 1600 px; write one sentence on its content and
   light; list candidate areas.
2. Place squares on every candidate area: ten or more per frame on four or
   more objects across the bands, doubtful ones included (they become
   `uncertain`, not omitted); a missed neutral costs more than a sampled
   one. Leave a margin of the same material around each.
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

## Power-law: pooled roll exponents

A single frame spans too little tonal range: one frame's whites-only fit gave
RedRatio 1.575, a pooled fit (25 reliable spots in 8 frames) gave 1.334 and
BlueRatio 0.737. With wrong exponents a per-frame white balance can make only
one brightness neutral (whites neutral, mid-tones yellow).

The ratios are not fixed numbers, and BlueRatio need not be below 1. ART's
defaults (1.36 and 0.86) and the examples here (0.737, 0.857, 0.934) come from
rolls shot partly or wholly outdoors; a roll shot entirely indoors under
lamps fitted RedRatio 1.43 and BlueRatio 1.2 (69 spots in 5 frames, stable
residuals), and the hand-tuned values on hangar frames of another roll were
1.06 to 1.2. Judge a fit by its residuals and by whether neutrals stay neutral
from dark to light, not by the default. What decides it is which spots go in:
the same roll gave BlueRatio 1.45 from flat, low-saturation patches alone and
1.20 once bright white objects (airframe paint, white missile bodies) were
added. Fit with bright and dark neutrals both, refit when the slope changes a
lot after adding the other end, and trust the fit only when it is stable.

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

## Power-law: reference point on the neutral line

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
original exposure is not in the file and is not needed. With a manual lens's
unrecorded aperture, assume it stayed fixed and use shutter and ISO,
`s = (t * iso) / (t0 * iso0)`; record the assumption. Example, RedRatio 1.37,
BlueRatio 0.90: a frame at 0.625 s against 0.5 s (`s` = 1.25) has `ir` higher
by 0.060 and `ib` lower by 0.025 in the same light, and its measured `ib` of
-1.45 is -1.425 at 0.5 s. This assumes the scans' settings are the only signal
scale difference (same backlight and white balance, nothing clipped); ISO
scaling may be camera-dependent. The ~0.03 guide in "Lighting groups" applies
after normalization and is not evidence by itself of changed digitization.

**One `g0` per lighting group.** `L` of `RefOutput` is what the `RefInput`
point is rendered as, so the same `L` gives two frames the same brightness
only if their `g0` is the same green at the reference exposure. Choose `g0`
once per group (a typical neutral's green) and use it on every frame of the
group, scaled for the scan exposure: `g0_frame = s * g0`, with `RefInput` on
that frame's own (measured) line at `g0_frame`, which is `s` times the point
on the normalised line at `g0`. Unscaled, the `s` = 1.25 frame above comes out
at 1.25^-1.5 = 0.72 of the group's brightness (-0.48 EV); in general a `g0`
off by a factor `c` changes the brightness by `c^1.5`.

## Power-law: changing white balance without changing brightness

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

## Power-law: taste in RefOutput

Measurement stays in `RefInput` (the measured neutral). To make a frame
warmer or cooler without touching it, set
`RefOutput = k * (e^(0.035 s), 1, e^(-0.07 s))` with `s` = steps (negative =
cooler) and `k` chosen so the luminance
`0.2126729 r + 0.7151521 g + 0.0721750 b` equals the neutral's `L`. `L;L;L` =
the measured neutral. Offer the user a few variants side by side (e.g. Cool 2
.. Warm 2, plus the previous one): users judged by skin tones and sky (warm
shifts turn blue sky violet-grey).

## Power-law: output level

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

## Power-law: per-channel black point

These offsets grade a retained power-law positive. They do not measure film density endpoints; use the selected inversion method's anchor controls and evidence when estimating those.

Under bluish light (hangar lamps, shade) the inverted shadows can sit blue while mid-tones are neutral: the channels' black levels differ, which
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

## Power-law: changing L after black adjustments

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

## Power-law: mixed light

With several light sources in a frame (lamps plus daylight, coloured
spotlights), no single balance is right everywhere: balance on the subject's
neutrals (white paint on the aircraft, not the floor under another lamp) and
leave the rest. Keep a cast that is the real colour of the light (a warm lamp
lighting a bomb bay): neutralising it looks wrong. If a cast looks odd next to
neighbouring frames of the same place, it is cheap to re-check the reference
spot and the black offsets, but it may well be the lamp. Say which frames you
left warm, cool or tinted, and why.

## Power-law: lighting groups

These are original-scene adaptation groups for retained power-law profiles,
not independent digitization or film models. Keep the roll exponents shared,
normalize capture exposure first, and apply the skill's shared-setup policy.
Outdoor daylight, dusk and indoor lamps can need different balances even when
all frames were digitized identically. Group by visual scene evidence:

1. Make a contact sheet after a first inversion (shared roll ratios and one
   rough reference; record the pass). Identify scene illumination such as sun,
   overcast, dusk, tungsten, fluorescent/LED, mixed or a coloured lamp. A cast
   change is a candidate for checking lighting, references and capture
   normalization, not proof of changed hardware.
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
   offset unless `apply_preset` gets an `exclude` for them). Sample credible
   neutrals in an outlier. Normalized intercept differences above ~0.03 prompt
   checking material, mixed illumination and sampling first; supported scene
   differences get a scene-specific reference while keeping roll ratios.
4. Per frame, check `image_stats` and adjust `L` (scaling the black
   adjustments, above).
5. Frames that fit no group (a single warm lamp, mixed light) get their own
   settings; say which and why.

The numbers confirm a doubt from looking; they don't replace it. The ~0.03
is a guide, not a cut-off: in a mixed hangar the intercepts spread by more
inside one group (about 0.1 in two hangar groups of one roll), which is why
the split rests on looking first.
