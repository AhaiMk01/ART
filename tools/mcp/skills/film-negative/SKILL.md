---
name: film-negative
description: Invert camera-scanned colour negative film (photographed or scanned negatives with an orange mask, C-41, a roll of negatives) into positives with ART's Film Negative tool, using the art-render MCP tools (sample_spots, edit_profile, image_stats, render_preview). Use when asked to invert, convert or colour-correct negative scans, balance a negative's colours, or batch a roll.
---

# Inverting colour negatives with ART

Needs the `art-render` MCP server (and an ART build whose `art-cli` supports
`sample_spots`; otherwise that tool says `unsupported`). The fit and
white-balance formulas are in [reference.md](reference.md) (with Python
snippets for the single-frame and the pooled fit).

ART's Film Negative tool needs no film-base sample: ratios come from neutral
spots in the picture. A frame without any film base visible is fine.

## Single frame

1. `open_image(path)` and look at `profile_from`: `"sidecar"` means the frame
   loaded the user's OLD sidecar and its edits (7 of 12 frames of a test roll
   did), which would leak into everything below. Start from a known state:
   `reset_profile(path, to="default")` (or `open_image(path, profile=<base
   preset>)`), then step 2.
2. **Base settings**, one `edit_profile`:
   - `adjustments`: `exposure` `{enabled: false, hl_recovery: "Off"}`;
     `tone_curve` `{mode: "Standard", histogram_matching: false, curve1:
     {type: "linear"}, curve2: {type: "linear"}}`; `sharpening`
     `{enabled: false}`; `film_negative` `{enabled: true, color_space:
     "working"}` (`sample_spots` must use `space="working"`; with
     `color_space: "input"` use `space="input"`).
   - `hl_recovery: "Off"` goes in the SAME request as `enabled: false`: a
     preset file with `[Exposure] Enabled=false` loads with highlight recovery
     Off, a typed `enabled: false` leaves the default `Balanced`, so a frame
     edited from default and one opened from a preset would differ in a key
     nobody set. (A typed `exposure` field sent alone on the disabled tool
     re-enables it, listed under `implied`.)
   - `raw_edits` (a LIST of `{group, key, value}`, value always a string; the
     group and key must already exist): `[RAW Bayer] Method=amaze`,
     `[RAW] CAEnabled=false`. Below, `[Group] Key=value` means one such item,
     e.g. `{"group": "RAW Bayer", "key": "Method", "value": "amaze"}`.
   - If an edit is refused with `unknown_key`, call `get_profile` with
     `groups: [<the group>]` and use the name it shows.
   - The result lists only what changed, as `{Group: {Key: value}}`:
     `changed` (what you set; a value already there is not listed), `implied`
     (what the server did on its own), `drawn` (curves), `warnings`; `created`
     names a new `color_correction` region or mask shape (the keys ART fills
     in at their defaults are counted there, not listed). It is
     the check that the edit did what you meant (with `paths` or `items`, each
     image's `changed` is only a COUNT, to keep a reply for 37 frames small;
     `implied` and `warnings` are still listed: to see which keys, edit one
     image with `path`, or `get_profile`), with one blind spot: a value
     already at its default never shows (a linear tone curve, `exposure`
     disabled on a profile that has it disabled). To confirm a base edit took,
     `get_profile(path, groups=["Exposure", "ToneCurve", "Film Negative"])` or
     the per-group `keys` counts of the preset you save from it
     (`save_partial_profile`) say so.
3. **Orientation.** Coarse rotation is per frame (frames of one roll differed:
   90 vs 270). `render_preview(max_size=1024, inline=true)` returns the image
   in the result, nothing to read (without `inline` it returns a JPEG path: Read it).
   For several frames, one `contact_sheet(images, record=false, thumb_size=700)`
   and one read show them all (see Pitfalls).
   If wrong, set `[Coarse Transformation] Rotate=90` (0, 90, 180, 270) and preview again.
4. **Crop off the film holder/border** with `adjustments.crop` `{enabled: true,
   fixed_ratio: false, x, y, w, h}` in frame pixels (after coarse rotation).
   Do this BEFORE `image_stats`: the white holder dominated clipping (32%
   `clipped_high` uncropped). Find the edge by eye on a preview or measure it:
   `sample_spots` along each of the 4 sides (a few spots per side, a small
   `size`, one call) shows where the holder level (about `g` < 200 in the
   negative's linear values on one roll's scans) jumps to picture level (above
   about 600); crop inside the four jumps with a margin, then preview and look
   (no holder left, no picture cut off). Preview px to frame px: `scale =
   frame_width / preview_width`, with the frame size from any `sample_spots`
   result (`width`, `height`); the preview of an uncropped image shows the
   whole frame, so `x = px * scale`.
5. **Sample neutrals** with `sample_spots(spots, size=32..64)`: up to 64 spots
   per call (more is refused), in frame pixels, so a frame's 20+ candidates go
   in one call. Choose neutrals by
   MATERIAL, not by how grey they look (list in reference.md): white paint,
   bare/galvanised metal, concrete, white trainers, midday overcast sky are good;
   natural stone, black fabric, glass, foliage, painted machinery, and sky at
   dusk or twilight (bluer than the ground, it biased a blue slope) are risky:
   if dusk-sky spots disagree with the ground neutrals on the intercepts, drop the sky.
   Agreement only counts between INDEPENDENT materials. Values are the
   NEGATIVE's (transmitted light): higher = darker scene part. Use `avg`.
   Spread the spots over dark and light areas; the fit needs a range of green
   values. To map a preview pixel to frame pixels, see Pitfalls.
   To find candidates faster, run `suggest_neutrals(path)` once the inversion
   and the crop are set: it proposes flat, low-saturation cells spread from
   dark to light, in the frame pixels `sample_spots` takes (hand its
   candidates over unchanged; on the test roll
   about twice the hit rate of a regular grid, on frames from other rolls only
   slightly better). It narrows where to look and cannot
   tell the material: look at the preview, drop what is not white paint, metal
   or concrete, and fit only from what `sample_spots` shows agreeing across
   independent materials (in mixed light its candidates can agree with each
   other and still be off the frame's line). Before fitting from candidates
   or spots, look at where they sit: `render_preview(marks=[...])` draws
   numbered boxes at frame-pixel spots, and `suggest_neutrals(preview=true)`
   returns the picture with its candidates marked.
6. **Fit** (reference.md): `RedRatio = 1/slope` of ln r vs ln g, `BlueRatio`
   likewise with b, least squares over the neutrals; drop spots with large
   residuals (coloured objects: foliage showed up in blue), refit. Real
   example: 11 neutrals gave RedRatio 1.335, BlueRatio 0.759; any two spots
   alone gave 1.17..1.48 depending on the pair, so fit, don't pair (a pair:
   `RedRatio = log(clear.r/dense.r) / log(clear.g/dense.g)`, `clear` = the
   higher green; `BlueRatio` likewise). For a roll, fit the exponents pooled
   over several frames (reference.md, with a snippet): one frame spans too
   little tonal range. Set `film_negative` `red_ratio` and `blue_ratio`; `green_exponent`
   stays 1.5. A profile with a legacy Film Negative (`BackCompat` in its
   `raw` group, `RedBase`) is not typed: use raw edits for it.
7. **Reference spot** (white balance and level): `film_negative.ref_input` = a
   neutral spot's `avg` as `[r, g, b]` (or a point on the fitted line,
   reference.md); `ref_output` = `[L, L, L]` with `L` = the spot's intended
   reflectance x 65535 (18% grey about 11800, a light stone ~0.3 about
   19700); it is the linear output level (0..65535, before the tone curve)
   that spot gets. Without a `ref_input` ART estimates from channel medians
   (20% border cut); ART's default output 65535/24 (about 2731) matches the
   image median, not a chosen spot. Taste (warmer/cooler) goes in
   `ref_output`, measurement in `ref_input` (reference.md). Giving only
   `ref_input` keeps the image's brightness: `edit_profile` sets
   `ref_output = (L, L, L)` itself (ART's picker rule, listed under
   `implied`; with an unset current reference it first estimates ART's
   medians by sampling and warns). Give `ref_output` too when you want a
   level.
8. **Check**: `image_stats` (crop is applied; `paths` takes a whole roll in one
   call, and `detail="compact"` keeps just clipping and the percentiles 0.1, 50,
   99.9). The shapes differ: with `path` the statistics are the result's top
   level, with `paths` they are under `items[i].stats`. Raise `L` in steps
   (11800 -> 15000 -> ...) until `clipped_high` is about 0 in every channel;
   `lum` p99.9 of 220-245 is typical. Lamps and speculars in a lit interior clip 0.4 to 1%
   at any `L`, and that is fine: judge `clipped_high` without them, with
   `lum_max` (say 245: the statistics of the pixels at or below it, `in_band`
   says how many that is) or on a `region` away from them (`{x, y, w, h}`,
   fractions of the image as in `render_preview`), or accept it. A band of
   the shadows (`lum_max` about 60) or the mid-tones (70 to 190) gives the
   colour cast of that range alone. A bright sky clipping one channel (blue first) is a trade-off
   against the level: accept a little when the sky is not the subject, lower
   `L` when it is (reference.md, "Output level"). `bins=16` shows the shape
   of the distribution (is the shadow end clipped, is there a second hump),
   which the percentiles alone do not. Then `render_preview` and look. Colour cast:
   re-pick `ref_input` on another neutral and leave `ref_output` out: the
   server applies the brightness-preserving rule (reference.md).
9. **Black point and contrast** (`tone_curve`, sRGB-encoded 0..1, roughly
   `image_stats` value / 255): take the lowest of the three channels'
   percentile 0.1 (the lum one hides a channel that sits lower), subtract
   ~5, divide by 255 -> `x0`; set `curve1`
   `{type: "spline", points: [[x0,0],[0.6,0.6],[1,1]]}` (e.g. x0 = 0.24).
   Then `image_stats`: `clipped_low` should stay under ~0.5% per channel
   (a larger one means x0 is too high), and the lowest channel's percentile 0.1
   should now be small (about 5 to 10): `clipped_low` cannot see the opposite
   error, a frame whose blacks stay at 20 or more is hazy, often tinted, and
   needs a higher `x0` (frames brightened with +EV after their black point was
   set were the ones left like that on one roll). Direction: raising `x0` makes the
   blacks DARKER (more of the shadows map to 0), lowering it lifts them (one
   frame: x0 0.10 / 0.125 / 0.15 gave blacks 14 / 7 / 0). After an EV or `L`
   change, measure the blacks again: scaling `x0` by `k^(1/2.2)` leaves them
   too high (reference.md, "Changing L after the black adjustments"). The
   rule is a first estimate: a black measured before the curve (or before a
   later offset, EV or `L` change) can
   land elsewhere after it (one frame: pre-curve r49 g52 b53 became r7 g0 b13,
   green clipping 0.9%; with x0 = 0.173 the curve alone gives 49 -> 7, 53 ->
   13), so `clipped_low` per channel after the curve decides. The channel with
   the lowest black clips first: when one channel clips more than the others,
   set x0 lower than the rule gives. Read the `edit_profile` result's
   `drawn` (the line ART draws through the points) and `warnings` (clips,
   reversals). For an S-curve use `tone_curve.contrast`
   (e.g. 20), not curve points. Setting a curve turns `histogram_matching`
   off (listed under `implied`), which can change brightness a lot: re-run
   `image_stats` after every tone change.
10. `export_image(path, output, format, ...)` and/or `save_sidecar(path)`.

## A whole roll

Ratios are a property of the film and development: fit once, reuse.

Do each thing once, not per frame: the base settings are identical for every
frame, the ratios for the whole roll once fitted, and a group's output level
and black adjustments within the group. So reset any frame that loaded a
sidecar (step 3; a preset sets only the keys it holds, old ones would stay),
in one call, `reset_profile(paths=[...], to="default")` (likewise
`open_image(paths=[...], profile=...)` for opening), and after the first
frame's base edit `save_partial_profile(path,
dest="base.arp", vs="default")` and give it to the others in one call,
`apply_preset(paths=[the rest], profile="base.arp")` (one identical one-off
edit: `edit_profile(paths=[...], adjustments=...)`); after the fit, apply the
ratios the same way. What stays per frame: rotation, crop, `RefInput` (the
white balance, on that frame's own neutral line) and fine tuning.
`apply_preset(..., exclude=[...])` drops groups or `Group/Key` entries of the
preset first: use it when a group preset must not overwrite what a frame
already has of its own (step 3 below lists the keys).

The per-frame values (white balance `ref_input`, `L`, black offsets, black
point, EV, crop) differ from frame to frame: send them with ONE
`edit_profile(items=[{path, adjustments, raw_edits}, ...])`, each image its
own edit, not one call per frame and value (one roll run made about 140
`edit_profile` calls, mostly per-frame values); the same edit for many frames is
`paths=[...]`. Measure with one `image_stats(paths=[...])`, set the new
values with one `items` call, and repeat.

Keep a record with `contact_sheet(images, folder=<a work folder for the roll,
not the exports folder>, label=...)` (it creates `sheets/` in `folder`): one
call per pass over the open frames (after the first
inversion, after the group presets, after per-frame white balance, after the
black-point fixes), each saved as `sheets/pass-NN-<label>.jpg` with a JSON of
the profile keys that changed since the last pass; earlier passes are kept.
Open the returned `path` and look. `compare_passes(first, second)` shows the
same frames of two passes side by side (a few frames: `images`).

0. Group the frames by light, by looking at a contact sheet of a first
   inversion (reference.md, "Lighting groups"): daylight, overcast, dusk,
   each kind of indoor lamp. One preset per group; a frame that fits no
   group is handled on its own. The intercept spread inside a group can
   exceed 0.03 in a mixed hangar (about 0.1 in two hangar groups of one roll):
   split by LOOKING first, use the numbers only to confirm. Look at the sheet
   again after applying the presets; sample neutrals in any frame that still
   stands out. Compare
   frames only after normalising their intercepts to one scan exposure
   (reference.md, "Reference point on the neutral line"); the numbers are the
   scanning camera's `shutter_seconds`, `iso` and `aperture`, for the whole
   roll in one `inspect_images` call, made once `open_image` has returned (it
   reads open images: issued in the same turn as `open_image`, 31 of 37 frames
   came back `not_open`). Read every frame's values rather than assuming the
   roll shares them. They describe the SCAN: the same on every frame only
   means one scanning setup, and says nothing about how the negatives were
   exposed.
   Brightness per frame: the preset's `L` fits the group's brightest frame;
   darker frames get +EV (exposure), never -EV (reference.md, "Output
   level").
1. Pick a representative per group: good contrast, real shadows AND
   highlights, and neutral objects of independent materials (white paint,
   metal, concrete). A flat or low-key frame, or one without neutrals, makes
   a bad reference. Do the single-frame steps on it (rotation, crop,
   `ref_input`/`ref_output` included).
2. `save_partial_profile(path, dest="<group>.arp", vs="default", exclude=["Coarse
   Transformation", "Crop", "Film Negative/RefInput"])`: the group's preset
   (the roll's, when the light is one). `vs="default"` writes every key that
   differs from ART's default profile, so the preset is complete whatever the
   frame was opened from; with the default `vs="opened"` it would hold only
   what you changed since opening and lack the base settings of a frame opened
   from another preset. It carries the base settings, the roll's ratios, the
   group's output level (`RefOutput` L), the per-channel black offset and
   black point, `contrast` and `hl_recovery`. It cannot carry the white
   balance, which is per frame: `RefInput` on the frame's own neutral line at
   the group's reference green (step 4; reference.md, "Reference point on the
   neutral line"). So exclude `RefInput`, rotation and crop; the
   representative's EV (`Exposure/Compensation`) is in it too, exclude it when
   frames get their own. Its curve, black offset and `RefOutput` are the
   group's STARTING values: a frame tunes its own (step 3), and a preset
   applied after that overwrites them. Read the returned `keys` (per-group
   counts; `verbose=true` lists them) and the file. Open each
   frame from it (step 3), or use it with `art-cli -p` / ART's profile loading.
3. Each other frame: look at `profile_from` of every `open_image` result:
   `"sidecar"` means the user's old edits came along. Start every frame of the
   roll from the same known state: `open_image(path, profile="<group
   preset>.arp")` starts its working profile from the preset (laid over ART's
   default profile; the frame's own sidecar is not read, so an old one doesn't
   leak in), or `reset_profile(path, to="default")` on a frame that did load a
   sidecar, never whatever was lying there. The preset carries the base
   settings, the roll's ratios, the group's output level and the black
   adjustments: no need to repeat those `edit_profile`s. Then per frame:
   rotation (preview first), crop (when the holder moves only a little between
   frames, one common conservative crop inside every frame's border does for the
   roll, `edit_profile(paths=[...], adjustments={"crop": ...})`; on one roll the
   left border ranged 170 to 270 px and the top 150 to 180), `ref_input` from
   that frame's own neutrals (a few spots; a neutral's `avg` or a point on the
   roll's line) with `ref_output = [L, L, L]` of the group in the same request
   (`ref_input` alone re-derives the level from the frame's current look, not the group's
   `L`), output level and black point re-checked with `image_stats`. To give a
   frame its group's settings without losing its crop and reference spot
   (frames already open and set up, a preset changed since), use
   `apply_preset(paths=[...], profile="<group preset>.arp", exclude=[...])` on
   the open frames, in one call for the whole group, rather than reopening
   them: the preset's keys win and everything else of the frame stays. The
   preset's keys include the ones a frame tuned for itself, and without
   `exclude` they overwrite its own curve (black point), level and EV: exclude
   what is per frame, e.g. `["ToneCurve", "Exposure/Compensation", "Film
   Negative/RefOutput", "ColorCorrection"]` (the black offset), less what the
   frames did not tune.
4. Every frame needs its own white balance, even in one roll: the exponents
   carry over, the light does not (blue offsets ranged +0.04..+0.39 across one
   roll: morning, afternoon, shade, greenhouse). Sample neutrals in the frame,
   check that its reliable ones lie on the roll's line (reference.md), keep
   only spots that agree on the intercepts, set `ref_input` on the line (at
   the group's reference green) and give the group's `ref_output` (a frame
   outside any group: leave it to the brightness-preserving rule). Judge
   the intercepts after normalising to one scan exposure (reference.md,
   "Reference point on the neutral line"; shutter, ISO and aperture of the
   scanning camera, from `inspect_images`). Do not refit the ratios
   unless the frame is another film or development; fit them pooled over
   frames (reference.md), never from one frame.
5. Check each frame with `image_stats` and a preview, and the roll with a
   last `contact_sheet` pass (compare it with the first inversion's). Its
   result lists what changed since the last pass grouped by change; the JSON
   has it per frame.
   Export the roll with `export_batch` (a render takes about a second per
   frame: if the client's tool timeout is short, 30 s say, export 10 to 15
   frames per call, by `pattern` or `items`): `source` = the roll's folder, with
   a `pattern` limiting it to the frames of the roll (or of one group; without
   one, every image of the folder is exported) exports each frame's working
   profile, so every frame it matches must be open; `items` is for an explicit
   list, each with its working profile or `profiles: [<group preset>.arp,
   <frame>.arp]`. `source` with
   `profiles: [<group preset>.arp]` renders every frame from the preset
   alone, without per-frame rotation, crop or reference spot. To keep each
   frame's settings with its export, add `write_profile: true,
   profile_name: "source"`: the output folder then holds `<raw name>.arp`
   next to every JPEG, ready to copy beside the raws; their own sidecars are
   never touched.
6. Blue (or another channel's) shadows with neutral mid-tones: a per-channel
   black offset in `color_correction`. When a frame's `L` differs from the
   frame the offset and black point were set on, scale both (reference.md,
   "Changing L after the black adjustments"). Mixed light: balance on the
   subject (reference.md, "Mixed light"; a real lamp colour is kept).

## Pitfalls

- `sample_spots` coordinates are frame pixels, not preview pixels, and ignore
  the crop's origin: they are the same system as `[Crop]`. A Render
  whole-image preview shows the crop when one is enabled, so
  `x = crop.x + px * crop.w / preview_w` (no crop: `px * frame_w /
  preview_w`; same for y); a Live preview always shows the whole frame.
- `sample_spots` returns values before the film negative tool, so on a negative
  they are the negative's; ratios and the formulas here are unaffected.
- `image_stats` before cropping is dominated by the holder/border (Render
  applies the working profile's crop; Live's preview is uncropped).
- `crop` needs `fixed_ratio: false` for a free rectangle (ART's default keeps
  a fixed ratio in the editor's crop tool).
- A tone curve implies `histogram_matching` false; a changed brightness after
  setting a curve is that.
- The neutral-line intercepts `ir`, `ib` move with scan exposure (shutter,
  ISO, aperture) as well as with the light: normalise them to one exposure
  before comparing frames. Those settings are the DIGITISING camera's, read
  from the raw's EXIF (`inspect_image` / `inspect_images`), not the film's
  original exposure, which the file does not carry and which is not needed;
  a null aperture (manual lens) means use shutter and ISO only. Use one reference green `g0` per lighting group,
  scaled for each frame's exposure, or one `L` is a different brightness on
  each frame (reference.md, "Reference point on the neutral line").
- A `color_correction` offset is stored halved (lowering a black by the linear
  amount `D` needs `offset = -2 D`) and comes off every pixel of the channel,
  mid-tones included (reference.md, "Per-channel black point").
- A preview plus a file read per frame adds up (a roll took 28 previews and 32
  reads). `render_preview(inline=true)` saves the read. To look at several
  frames, one `contact_sheet(images, record=false,
  thumb_size=700)` is one labelled image and one read; 2 to 6 frames at 700 to
  1000 px stay readable, and nothing is recorded as a pass.
- Edits are in memory until `save_sidecar`; previews and exports never write
  the sidecar.
- A whole `get_profile` is about 15k tokens: over a roll, never read it
  whole. `get_profile(path, groups: ["Film Negative", "Crop", "Coarse
  Transformation", "ToneCurve"])` shows a frame's settings,
  `get_profile(path, changed_only: true)` everything that differs from ART's
  default profile (the frame's whole state: what the sidecar and your edits
  changed), and `edit_profile`'s own result already says what it changed (`full:
  true` echoes the groups it touched, rarely needed).
