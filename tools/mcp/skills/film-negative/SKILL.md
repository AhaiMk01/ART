---
name: film-negative
description: Invert camera-scanned colour negative film (photographed or scanned negatives with an orange mask, C-41, a roll of negatives) into positives with ART's Film Negative tool, using the art-render MCP tools (sample_spots, edit_profile, image_stats, render_preview). Use when asked to invert, convert or colour-correct negative scans, balance a negative's colours, or batch a roll.
---

# Inverting colour negatives with ART

Needs the `art-render` MCP server (and an ART build whose `art-cli` supports
`sample_spots`; otherwise that tool says `unsupported`). The fit and
white-balance formulas are in [reference.md](reference.md) (with a Python
snippet for the fit).

ART's Film Negative tool needs no film-base sample: ratios come from neutral
spots in the picture. A frame without any film base visible is fine.

## Single frame

1. `open_image(path)`.
2. **Base settings**, one `edit_profile`:
   - `adjustments`: `exposure` `{enabled: false}`; `tone_curve`
     `{mode: "Standard", histogram_matching: false, curve1: {type: "linear"},
     curve2: {type: "linear"}}`; `sharpening` `{enabled: false}`;
     `film_negative` `{enabled: true, color_space: "working"}` (`sample_spots`
     must use `space="working"`; with `color_space: "input"` use
     `space="input"`).
   - `raw_edits` (a LIST of `{group, key, value}`, value always a string; the
     group and key must already exist): `[RAW Bayer] Method=amaze`,
     `[RAW] CAEnabled=false`. Below, `[Group] Key=value` means one such item,
     e.g. `{"group": "RAW Bayer", "key": "Method", "value": "amaze"}`.
   - If an edit is refused with `unknown_key`, call `get_profile` with
     `groups: [<the group>]` and use the name it shows.
   - The result lists only what changed, as `{Group: {Key: value}}`:
     `changed` (what you set; a value already there is not listed), `implied`
     (what the server did on its own), `drawn` (curves), `warnings`. It is
     the check that the edit did what you meant; no `get_profile` is needed.
3. **Orientation.** Coarse rotation is per frame (frames of one roll differed:
   90 vs 270). `render_preview(max_size=1024)`, look at it (Read the JPEG).
   If wrong, set `[Coarse Transformation] Rotate=90` (0, 90, 180, 270) and preview again.
4. **Crop off the film holder/border** with `adjustments.crop` `{x, y, w, h}`
   in frame pixels (after coarse rotation). Do this BEFORE `image_stats`: the
   white holder dominated clipping (32% `clipped_high` uncropped). Preview px
   to frame px: `scale = frame_width / preview_width`, with the frame size
   from any `sample_spots` result (`width`, `height`); the preview of an
   uncropped image shows the whole frame, so `x = px * scale`. Re-preview.
5. **Sample neutrals** with `sample_spots(spots, size=32..64)`, 16 per call, in
   frame pixels, several calls (aim for 20+ candidates). Choose neutrals by
   MATERIAL, not by how grey they look (list in reference.md): white paint,
   bare/galvanised metal, concrete, white trainers, overcast sky are good;
   natural stone, black fabric, glass, foliage, painted machinery are risky.
   Agreement only counts between INDEPENDENT materials. Values are the
   NEGATIVE's (transmitted light): higher = darker scene part. Use `avg`.
   Spread the spots over dark and light areas; the fit needs a range of green
   values. To map a preview pixel to frame pixels, see Pitfalls.
6. **Fit** (reference.md): `RedRatio = 1/slope` of ln r vs ln g, `BlueRatio`
   likewise with b, least squares over the neutrals; drop spots with large
   residuals (coloured objects: foliage showed up in blue), refit. Real
   example: 11 neutrals gave RedRatio 1.335, BlueRatio 0.759; any two spots
   alone gave 1.17..1.48 depending on the pair, so fit, don't pair (a pair:
   `RedRatio = log(clear.r/dense.r) / log(clear.g/dense.g)`, `clear` = the
   higher green; `BlueRatio` likewise). For a roll, fit the exponents pooled
   over several frames (reference.md): one frame spans too little tonal
   range. Set `film_negative` `red_ratio` and `blue_ratio`; `green_exponent`
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
8. **Check**: `image_stats` (crop is applied). Raise `L` in steps (11800 ->
   15000 -> ...) until `clipped_high` is about 0 in every channel (a bright
   blue sky may clip a little in `b` first: stay under ~0.05%; raise `L`
   until highlights just don't clip); `lum` p99.9
   of 220-245 is typical. Then `render_preview` and look. Colour cast:
   re-pick `ref_input` on another neutral and leave `ref_output` out: the
   server applies the brightness-preserving rule (reference.md).
9. **Black point and contrast** (`tone_curve`, sRGB-encoded 0..1, roughly
   `image_stats` value / 255): take the lowest of the three channels'
   percentile 0.1 (the lum one hides a channel that sits lower), subtract
   ~5, divide by 255 -> `x0`; set `curve1`
   `{type: "spline", points: [[x0,0],[0.6,0.6],[1,1]]}` (e.g. x0 = 0.24).
   Then `image_stats`: `clipped_low` should stay under ~0.5% per channel
   (a larger one means x0 is too high). Read the `edit_profile` result's
   `drawn` (the line ART draws through the points) and `warnings` (clips,
   reversals). For an S-curve use `tone_curve.contrast`
   (e.g. 20), not curve points. Setting a curve turns `histogram_matching`
   off (listed under `implied`), which can change brightness a lot: re-run
   `image_stats` after every tone change.
10. `export_image(path, output, format, ...)` and/or `save_sidecar(path)`.

## A whole roll

Ratios are a property of the film and development: fit once, reuse.

Keep a record with `contact_sheet(images, folder=<the roll's output folder>,
label=...)`: one call per pass over the open frames (after the first
inversion, after the group presets, after per-frame white balance, after the
black-point fixes), each saved as `sheets/pass-NN-<label>.jpg` with a JSON of
the profile keys that changed since the last pass; earlier passes are kept.
Open the returned `path` and look. `compare_passes(first, second)` shows the
same frames of two passes side by side (a few frames: `images`).

0. Group the frames by light, by looking at a contact sheet of a first
   inversion (reference.md, "Lighting groups"): daylight, overcast, dusk,
   each kind of indoor lamp. One preset per group; a frame that fits no
   group is handled on its own. Look at the sheet again after applying the
   presets; sample neutrals in any frame that still stands out.
   Brightness per frame: the preset's `L` fits the group's brightest frame;
   darker frames get +EV (exposure), never -EV (reference.md, "Output
   level").
1. Pick a representative per group: good contrast, real shadows AND
   highlights, and neutral objects of independent materials (white paint,
   metal, concrete). A flat or low-key frame, or one without neutrals, makes
   a bad reference. Do the single-frame steps on it (rotation, crop,
   `ref_input`/`ref_output` included).
2. `save_partial_profile(path, dest="<roll>.arp", exclude=["Coarse
   Transformation", "Crop", "Film Negative/RefInput", "Film Negative/RefOutput"])`:
   the roll preset. Exclude the per-frame settings: rotation, crop and the
   reference spot (`RefOutput` too if you set it per frame). It holds only keys whose value you CHANGED from the
   opened profile (a key already at the wanted value, e.g. `ColorSpace=1`,
   is not in it), and it carries this frame's black point and `contrast`;
   read the returned `keys` and the file. Open each frame from it (step 3), or use
   it with `art-cli -p` / ART's profile loading.
3. Each other frame: `open_image(path, profile="<group preset>.arp")` starts
   its working profile from the preset (laid over ART's default profile; the
   frame's own sidecar is not read, so an old one doesn't leak in), which
   carries the base settings, the roll's ratios and the black point: no need
   to repeat those `edit_profile`s. Then per frame: rotation (preview
   first), crop, `ref_input`/`ref_output` from that frame's own neutrals (a few
   spots; `ref_input` = a neutral's `avg` or a point on the roll's line),
   output level and black point re-checked with `image_stats`.
4. Every frame needs its own white balance, even in one roll: the exponents
   carry over, the light does not (blue offsets ranged +0.04..+0.39 across one
   roll: morning, afternoon, shade, greenhouse). Sample neutrals in the frame,
   check that its reliable ones lie on the roll's line (reference.md), keep
   only spots that agree on the intercepts, set `ref_input` on the line and
   leave `ref_output` to the brightness-preserving rule (or give it). Do not refit the ratios
   unless the frame is another film or development; fit them pooled over
   frames (reference.md), never from one frame.
5. Check each frame with `image_stats` and a preview, and the roll with a
   last `contact_sheet` pass (compare it with the first inversion's).
   Export the roll with one `export_batch`: `source` = the roll's folder
   (`pattern` for one group's frames) exports each frame's working profile,
   so every frame in it must be open; or `items`, each with its working
   profile or `profiles: [<group preset>.arp, <frame>.arp]`. `source` with
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
   subject (reference.md).

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
- Edits are in memory until `save_sidecar`; previews and exports never write
  the sidecar.
- A whole `get_profile` is about 15k tokens: over a roll, never read it
  whole. `get_profile(path, groups: ["Film Negative", "Crop", "Coarse
  Transformation", "ToneCurve"])` shows a frame's settings,
  `get_profile(path, changed_only: true)` everything that differs from ART's
  default profile (the frame's whole state: what the sidecar and your edits
  changed), and `edit_profile`'s own result already says what it changed (`full:
  true` echoes the groups it touched, rarely needed).
