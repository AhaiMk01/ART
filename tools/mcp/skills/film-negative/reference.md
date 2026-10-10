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
-> [print LUT, legacy before_grade only]
-> scene exposure, colour and tonal adjustments in the declared working basis
-> print LUT (after_grade, the default for new conversions)
-> output colour management and display export; integer Cineon export re-encodes with W
```

Three kinds of setting act in this chain; keep them apart when reasoning
and when reporting:

- encoding convention: the constants 95 and 685, `b`, and
  `cineon_reference_white` (W). They define what a code means and are shared
  by the decode, the print-LUT input encode and the integer Cineon export.
  They do not look at the picture;
- endpoint estimation: `namicolor_black`, `namicolor_gain`,
  `namicolor_shift`, the master terms, `namicolor_input_gain` and FitBase
  place the film base and a chosen white on codes, per image or per roll,
  from picture evidence (sample_spots, luminance, inspection);
- aesthetic grading: scene exposure, curves, colour correction and the
  print LUT. These are choices about the look, not measurements.

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
remain separate; its paper target and film-base picker do not become NamiColor
controls.

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
calibration from a neutral patch or a more pleasing print LUT result.


## Luminance and endpoint evidence

Inspect an ungraded positive before selecting near-black or diffuse-white
references. Decode the transfer before computing linear luminance:
`Y = m_YR*R + m_YG*G + m_YB*B`, using the declared RGB-to-XYZ matrix's
Y row. A grayscale view can encode that Y with the fixed diagnostic display
curve. It is neither an RGB average nor a weighted sum of Cineon code values.
Label clipping introduced by the view; inspect the linear or log data where
the display hides highlight or shadow differences.

Use existing image/data facilities to make a temporary diagnostic view from
a declared linear or Cineon export. Leave the retained conversion unchanged.
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
LUT result for lost shadow structure, flattened highlights and colour
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
- Denoise: `denoise_before_inversion` (default true on new profiles; false on a sidecar below version 1059 without the key, where denoise ran after inversion). It applies to full-resolution output and 1:1 crops; the preview has no denoise. An explicit value always wins. Strength settings do not carry over between the two orders: measured on a real negative at the same Luminance/Chrominance, denoising before inversion left about 3x more noise in the darkest positive areas (thin, bright negative) and about half in midtones. Retune strength by checking a 1:1 crop of the darkest and a midtone area after switching; do not copy denoise values from a profile with the other order.
- Flare: `flare` = r;g;b, a linear transmission fraction 0..0.5 per channel subtracted from the normalised scan before the log (density and NamiColor only, not power-law; absent = 0). To estimate it, `sample_spots(stage=source)` on a fully OPAQUE area (film holder, blocked mask) in the same frame and lighting. Do not use the film base or rebate: that is Dmin, not flare. The result is an estimate; subtracting too much clips dense negative areas, so check the shadows after changing it.
- Grading: scene-linear gains (exposure, white balance) and printer-light offsets are domain-independent. Non-linear tools placed before the print LUT are looks. The print LUT or paper curve is the tone curve.

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
by `10^0.1` before a paper curve or black offset.

Status M rows, not transposed: `(1.0197, 0.0317, 0.0091)`,
`(-0.0052, 0.8933, 0.0521)`, `(0.0131, -0.0011, 0.9712)`.

Film-base pick, negative only: sample before inversion, set
`RGBGains = C - 4.0` on all three channels, so the rebate maps to linear
`1e-4` before paper, LUT, and black offset. Out of -3..3, or a bad sample:
no channel changes.

Paper, after `C` and before the exponential: `R = log10(65536)`,
`u = 1 - clamp(C / R, 0, 1)`, `v = interp(u)`, `C = R * (1 - v)`. Shared
curve, then per-channel. Endpoint clamp. Unknown id is an error.

Black offset: `L = max(0, L - offset)` on the linear result. With a print
LUT, that means after the LUT is decoded, not before it is applied.

## Cineon handoff and print LUTs

Cineon specifies a transfer encoding, not RGB primaries. Declare both the
gamut and the transfer at each handoff. Let `W = CineonReferenceWhite` and
`b = 10^((95 - 685) / 300)`. ART's signed NamiColor encode/decode is:

```
q = (95 + 300/ln(10) * ln(1 + (L/W)*(1-b)/b)) / 1023
L = W*b * expm1((1023*q - 95)/300 * ln(10)) / (1-b)
```

The logarithm requires a positive argument. Density's unsigned encode
instead uses `(685 + 300*log10(max(0,L/W)*(1-b)+b))/1023`.

The convention is: code 95 is linear zero, and code 685 is 90% diffuse
white, which is linear `W`. New profiles default to `W = 0.9`, so a linear
scale where 1.0 is 100% reflectance puts a perfect diffuse white at 0.9.
A sidecar below version 1058 without a `CineonReferenceWhite` key loads with
`W = 1`, so it renders unchanged; an explicit value always wins, and a
partial profile without the key does not change W. W is one shared scale for
NamiColor's decode, the print-LUT input encode and the integer Cineon
export; there is no separate value for each. Selecting W does not establish
that the photograph's linear scale represents 100%.

| linear L | code at W=0.9 | note |
| --- | --- | --- |
| 0 | 95 | convention (linear zero) |
| 0.9 W (= 0.81) | 685 | convention (90% diffuse white) |
| 0.18 | 480.8 | a check, not an anchor |
| 1.0 | 698.6 | 100% white, 13.6 codes above 685 |
| 13.52 W (= 12.17) | 1023 | top of the 10-bit range |

(With W=1: 0.18 maps to 467.8, and code 1023 is linear 13.52.) The common
"18% grey at 470" is not an anchor: with 300 codes/decade, a pure log
model puts 0.18 at 685 - 300*log10(0.9/0.18) = 685 - 209.7 = 475.3 codes,
against the nominal 215-code gap (470). The black offset `b` lifts the actual
encode to 480.8, about 11 codes (about 0.13 stop) from 470. Code 470 at W=0.9
corresponds to linear 0.165. Treat
that as the model's tolerance; do not distort W or the endpoints to hit 470.

`namicolor_input_gain` stays 1 by default. That is a contrast and look
choice, not a part of the convention: with it, NamiColor's capture-density
slope is about 0.29 D per decade of exposure against the nominal 0.6 gamma
of Cineon-encoded film. Change it as a look decision and re-estimate the
endpoints afterwards, since the relative slopes scale with it.

NamiColor uses W in both its internal Cineon decode and subsequent export
or LUT encode. Changing it alone largely cancels in an otherwise unchanged
decode/encode pair; intervening processing can still change pixels. It is
not an independent Dmin or white-alignment control. Dmin to 95 and the
chosen white to 685 are per-image endpoint estimates (below), not encoding
constants and not automatic minimum/maximum.

### Endpoint recipe: Dmin to 95, chosen white to 685

Use existing parameters and `sample_spots`; no new helper is needed. The
result is a scene estimate, not a calibration. Without a film-base patch
and without capture calibration, make no absolute density claim: say that
the near-black and white proxies are assumptions and report their
uncertainty.

1. Pick a Dmin candidate and a white candidate from evidence. Inspect the
   ungraded positive and luminance at readable size, then take samples whose
   whole footprint fits inside the material. Prefer clear film base (Dmin
   including fog) for the dark end and a diffuse, evenly lit material for the
   white. Exclude rebate and other off-film areas, dust and scratches,
   speculars, emitters and light sources, text and edges, and "neutrals" that
   have no independent reason to be neutral. Never take a raw image
   minimum/maximum or a percentile as an endpoint. If no film base is visible,
   call the dark reference a near-black proxy.
2. Sample both with `sample_spots` in the declared space (it returns linear
   0..65535, white-balanced, before inversion). `T_D,c` and `T_W,c` are
   `avg_c/65535` for the dark and white candidates. With a custom digital
   mask, mix the densities `-log10(T)` through it first and use the mixed
   values.
3. Targets are `q_D = 95/1023` and `q_W = 685/1023` with FitBase off; with
   FitBase `code95` they are `q_D = 0` and `q_W = 590/928` before the remap.
   With `g = namicolor_input_gain`, `q0 = 1 - g*log10(16*T)`:

   ```
   den_c   = (q0_W,c - q0_D,c) / (q_W - q_D)
           = g * log10(T_D,c / T_W,c) / (q_W - q_D)
   shift_c = q_D * den_c - q0_D,c - master_shift - black_c
   gain_c  = 1 - master_gain + black_c - den_c
   ```

   Each channel then maps its Dmin sample to `q_D` and its white sample to
   `q_W`. Within the parameter ranges (`gain` -1..1, `black` -0.5..0.5,
   `master_gain` -0.5..0.5) `den_c` is limited to roughly 0..3; if a
   channel falls outside, lower `g`, which scales every `den_c`, or use
   `black`. Equal `T_D,c/T_W,c` ratios give equal slopes; unequal ones are
   exactly the relative slopes of the estimate.
4. Apply with the existing `edit_profile`, read the profile back, render, and
   inspect the images. Sample the unconverted source again for independent
   materials and other frames to check transfer. Check that 18% grey sits near
   480.8, not 470, and keep the baseline if the endpoints over-stretch the
   scene. A white chosen as 685 is "90% diffuse white" only if the material
   really is one; the scene may deliberately hold brighter values.

A managed Cineon handoff requires 16-bit integer TIFF, a linear output
basis before encoding, and explicit Cineon primaries. Stored values are
`round(q*65535)`, not left-shifted 10-bit packing; scopes can report
`sample*1023/65535`. With NamiColor range preservation enabled, ART rejects
an integer handoff if the rounded value falls outside 0..65535 rather than
silently clipping. Legacy range policy clamps these values. Ordinary
previews remain display images.
This is a positive-oriented log intermediate: higher codes mean brighter
recovered scene values. The export is taken at the processed output stage,
not a direct dump immediately after the inversion operator. Identify any
intervening processing and endpoint uncertainty when handing it off.

If `open_image` rejects a Cineon-target sidecar while initializing an ordinary
render, open its linear-target baseline instead, set the Cineon target in
that working session, and export integer TIFF. Restore the linear target and
display output profile before requesting an ordinary preview. Verify the
handoff from its actual encoded data, not a claimed display-preview reload.

For a LUT, read its header/documentation and record the actual file/hash,
input primaries/transfer and output primaries/transfer. The sequence is
linear working RGB -> linear LUT-input RGB -> required input encoding
-> cube -> decode output transfer -> working/output colour management.
Convert primaries in linear RGB, not by relabelling log values. ART's `sRGB`
matrix profile has Rec.709 primaries; the explicit transfer field determines
whether those values use Cineon, sRGB or gamma 2.4.

For new conversions, use `cineon_lut_stage=after_grade`: ART applies the
film LUT at the end of its shared processing stage 3, after scene adjustments
and before output sharpening and colour management. The active LUT receives
RGB even when a preceding tool used Lab internally. This is not Resolve's HDR
palette; each ART tool retains its own processing semantics.

`before_grade` preserves the former LUT-before-adjustments order. Profiles
older than version 1056 carrying `CineonLUT` without `CineonLUTStage` load in
that mode; a partial omitting both keys preserves the active position.
The older Density/input-domain compatibility route also remains effective
only in `before_grade`. Switching to `after_grade` is an explicit change of
rendering order, not a sidecar upgrade that should silently change the look.
Compare with fixed conversion parameters and read back the saved position.

A no-LUT export still passes through the selected scene adjustments and
output conversion; it is not a direct dump of NamiColor's internal buffer.
Disable the print LUT when handing off an unprinted scene intermediate.

NamiColor's `preserve_range` retains finite signed values in scene Exposure
and in the working RGB returned from the print LUT. New conversions enable
it; conversions loaded from profiles older than version 1057 retain the
previous zero floors unless explicitly changed. Unrelated partial profiles
do not change this policy. Compare an explicit opt-in under the same viewing
conditions, and save the chosen policy with the conversion.

This is not a global bypass of ART's mappings: other tone tools retain their
own semantics, LUT inputs are still bounded by the cube's domain, and output
colour management can map or clip values. For an unprinted linear handoff,
disable the print LUT and export 32-bit float TIFF with output profile
`(none)`: ART writes working-space RGB with its linear working ICC profile.
Finite signed and over-white values survive this storage path; integer TIFF
and display previews are not equivalent evidence. Half-float has reduced
precision and range. If an integer Cineon handoff fails, inspect the affected
scene adjustments and encoded range, or use the linear float handoff; do not
silently switch back to clipping and claim the same numerical result.

A named 2383 LUT is a print/look response, not a neutral calibration.
The name or a D65 output white does not establish its input gamut or promise
neutral shadows. Declare an assumed input gamut when the documentation is
incomplete. Freeze conversion, exposure and viewing conditions while
comparing LUT/no-LUT; retain a supported baseline instead of automatically
correcting every LUT-induced hue change in the inversion.

### LUT contract procedure

Before using a print `.cube`, write a contract with one row per item and tag
every row. DOCUMENTED names its source (header line, vendor page), VERIFIED
names the evidence (a command, a probe render), ASSUMED says it is a
convention or guess. Items: file path; sha256 (of the bytes ART will read; `edit_profile` records
it when `cineon_lut` names a new file without `cineon_lut_sha256`, and keeps the
stored hash when the same path is named again: give the hash, or clear and
re-set the path, after replacing a file's contents);
LUT size and domain; input transfer; input primaries; output transfer; output
primaries; white point; stage (`after_grade` or `before_grade`); `W`. A name,
a folder name or a D65 white point is not gamut evidence. Keep the table in
your evidence notes; ART stores only the executable fields, not the tags.
Set `cineon_reference_white` explicitly (0.9 unless a comparison needs 1).
ART refuses a cube with a 1D section (`LUT_1D_SIZE`, `LUT_1D_INPUT_RANGE`),
a video-range key (`LUT_IN_VIDEO_RANGE`, `LUT_OUT_VIDEO_RANGE`), a `DOMAIN_MIN` /
`DOMAIN_MAX` with fewer than three numbers, a non-increasing domain, or a header
that declares a log output transfer (for example `# OUTPUT_TRANSFER: ARRI LogC3`).
It honours `LUT_3D_INPUT_RANGE` / `DOMAIN_MIN` / `DOMAIN_MAX` as the
encoded-input domain, so a range other than 0..1 changes the render. `TITLE` and
unknown keys are ignored: check them yourself.

A legacy input-space print LUT (density, input colour space, `before_grade`,
`LegacyInputLUT` true, as migrated from a pre-1054 sidecar, with a LUT set) cannot use LUT
primaries: ART refuses to render it with `cineon_lut_input_primaries` or
`cineon_lut_output_primaries` set, and the edit is refused. Clear the primaries,
or use `after_grade` or the working colour space.

Chain order: linear primaries map (working -> LUT input) -> input encode ->
cube -> output decode -> linear primaries map (LUT output -> working). ART
builds both maps from ICC colorants, which are D50-relative, so chromatic
adaptation is implicit in the profiles and the cube's D65 label is not used.
It only matters for a non-Rec.709 working space. `gamma_2_4` is a pure power
(`y^2.4`), not BT.1886 with black. Empty `cineon_lut_output_primaries` means
the same as the input primaries; both empty means no primaries map.

Verified contract for `Rec709-Kodak-2383-D65.cube`
(`E:/mcp_tmp/film03295-density-r2/results/2383-comparison/`):

| item | value | tag |
| --- | --- | --- |
| sha256 | `d315680d7c6c84a941dc41c8c9fea7afe0007c58811bc6f008edc56c15057b60` | VERIFIED (sha256sum; matches the sidecar and provenance.json) |
| size / domain | 3D, `LUT_3D_SIZE 33`, `LUT_3D_INPUT_RANGE 0.0 1.0` | DOCUMENTED (header; ART applies it) |
| input transfer | Cineon log | DOCUMENTED (header "Input: Cineon Log") |
| input primaries | Rec.709 (`sRGB` matrix profile) | ASSUMED (Resolve convention; header silent) |
| output transfer | Gamma 2.4 | DOCUMENTED (header "Display: ITU-Rec.709, Gamma 2.4"); pure power vs BT.1886 not stated; not verified by probing |
| output primaries | Rec.709 | DOCUMENTED (header); not verified by probing |
| white point | D65 | DOCUMENTED (header); not gamut evidence |
| stage | `after_grade` | chosen, saved in the sidecar |
| W | 0.9 (685 = 90% diffuse white) | ASSUMED (step convention; header silent). W=1 is a comparison run only |
| upstream | `imnz730/LUTs`, `Film Looks/Rec709 Kodak 2383 D65.cube` | DOCUMENTED (provenance.json); byte identity with Resolve's bundled copy not checked |

Separating conversion error from print look, with fixed conversion
parameters and the same frame: (1) render with no LUT; (2) render with an
identity cube (`out = in`, any size) and the same declared transfers,
primaries and W, so only the encode/decode and primaries chain acts; the
difference from (1) is conversion error (here the Cineon-to-gamma-2.4
display mapping), not look; (3) render with the real cube; the difference
from (2) is the print look alone. Repeat at the other stage if the order is
in question. Call the result a print-look experiment, not film calibration.

`image_stats` with the default `stage: "display"` describes display-encoded
output, not Cineon density. The Cineon distribution is `image_stats`
`stage: "cineon"` (Render server), which reads the actual encoded data; see
"Observing each stage". Use luminance for locating regions and per-channel
statistics for channel differences; neither certifies original colour.

## Observing each stage

One film conversion has four observable stages. Name the stage, space,
transfer and unit with every number you quote.

| What | Tool and stage | Space / transfer | Unit |
|---|---|---|---|
| Pre-inversion samples | `sample_spots` `stage: "source"` (default), `space` working or input | working space or camera space, linear, white-balanced | linear 0..65535 |
| Recovered light | `sample_spots` / `image_stats` `stage: "converted"` | working space (the profile's), linear, right after film + colour conversion, before LUT, exposure and grading | linear 0..65535; may be negative or above 65535 |
| Cineon encoding | `sample_spots` / `image_stats` `stage: "cineon"` | the converted pixels, encoded per pixel to Cineon codes with the profile's reference white W (`w` in the result) | `cineon_code` 0..1023; may fall outside |
| Display statistics | `image_stats` `stage: "display"` (default) | the 8-bit output after the whole pipeline and output profile | 0..255; not Cineon, not linear |

- Source and converted/cineon spots come from the same pixels: for a
  uniform patch the cineon `avg` equals the Cineon encode of the converted
  `avg` (685 + 300 log10(x/W (1 - s) + s), x = converted/65535, s = 10^(-590/300)).
  `space` applies to `source` only; asking for `input` with another stage is
  refused. If Film Negative is off the result says `film: "disabled"`: the
  stages are then the plain image, not a conversion.
- `image_stats` with a stage returns per channel (r, g, b) `min`, `max`,
  `mean`, `p01`, `p50`, `p99`, `below` / `above` (pixels outside the fixed
  `range`: converted [-6553.5, 131070], cineon [-100, 1100]), `nonfinite`
  and, with `histogram`, `bins` counts (2..1024, default 256) over that range.
  Percentiles are exact (nearest rank over every finite value, out-of-range
  ones included), not read from the bins. `histogram_image`
  draws R / G / B over the range with the Cineon axis marked at 95 (black),
  470 (nominal 18% grey) and 685 (linear W, 90% diffuse white by
  convention). The marks are fixed codes: linear 0.18 lands at 480.8 with
  W = 0.9 and at 467.8 with W = 1, so 470 is a check, not an anchor.
- Crop, region and downscale: the frame is the cropped frame (the working
  profile's crop applies). `region` is fractions of that cropped frame.
  `max_size` box-downscales the frame by averaging in linear light *before*
  the Cineon encode, so a downscaled cineon distribution is of averaged
  light and is narrower than the full-size one (0 = full size; large raws are
  slow). The `width`/`height` of the result are the measured size,
  `source_width`/`source_height` the cropped frame. Read spots, not
  downscaled histograms, to check an exact code.
- The Live server has no full-resolution stage tap: `image_stats` there
  measures the 8-bit preview only and refuses a stage; use the Render server.
  Live `sample_spots` does accept `stage`.
- Display statistics (percentiles, clipping, `lum`) are encoded output
  values after tone, LUT and output profile. They show what the picture
  looks like, not whether the Cineon codes sit at 95..685; do not quote them
  as a Cineon scope.

Strong endpoint stretches can fail ART's finite-value checks during
inversion. Preserve the failure and original parameters; clipping or
zeroing invalid pixels is not a successful conversion. If an explicitly
labelled comparison is made from a valid exported intermediate, process
both baseline and candidate through that same route, inspect the results,
and state that it is not an ART re-render or a reproducible ART sidecar.

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
paper/LUT/black offset, and therefore its output when those settings stay fixed.
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

### Density-specific reduction

For identity matrix, negative film and no paper/LUT/black offset, the equations
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
These reductions do not describe a nonidentity matrix or a rendered paper/LUT
response; use the full equations for those paths.

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
   input sample. This preserves the old reference output before paper/LUT;
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

Choose by material, not by how grey a spot looks.

- Candidate materials: matte white paint, sign backgrounds, concrete and
  uncoloured metal. Inspect their actual finish, weathering, illumination and
  reflection before treating them as neutral.
- Black ink on a white sign can constrain relative channel behaviour under
  common light, but neither material certifies Dmin or diffuse-white reflectance.
- Ambiguous materials include natural stone, dyed fabric, glass, foliage and
  painted machinery. Sky and clouds are illumination-dependent, especially at
  twilight; apparent brightness or low saturation does not make them references.
- Use independent materials and reserved frames to validate a fit. Repeated
  patches on one material check uniformity, not independent colour accuracy.

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
the same roll gave BlueRatio 1.45 from `suggest_neutrals` candidates alone and
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
