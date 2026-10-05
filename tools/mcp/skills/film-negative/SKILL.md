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
     curve2: {type: "linear"}}`; `sharpening` `{enabled: false}`.
   - `raw_edits` (a LIST of `{group, key, value}`, value always a string; the
     group and key must already exist): `[RAW Bayer] Method=amaze`,
     `[RAW] CAEnabled=false`, `[Film Negative] Enabled=true`,
     `[Film Negative] ColorSpace=1` (1 = working space; `sample_spots` must
     use `space="working"`). Below, `[Group] Key=value` means one such item,
     e.g. `{"group": "RAW Bayer", "key": "Method", "value": "amaze"}`.
   - If an edit is refused with `unknown_key`, call `get_profile` and use the
     name it shows.
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
   frame pixels, several calls (aim for 20+ candidates). Candidates: stone,
   paving, concrete, grey clothing, white paint. NOT sky, foliage, painted or
   coloured objects. Values are the NEGATIVE's (transmitted light): higher =
   darker scene part. Use `avg`. Spread the spots over dark and light areas;
   the fit needs a range of green values.
6. **Fit** (reference.md): `RedRatio = 1/slope` of ln r vs ln g, `BlueRatio`
   likewise with b, least squares over the neutrals; drop spots with large
   residuals (coloured objects: foliage showed up in blue), refit. Real
   example: 11 neutrals gave RedRatio 1.335, BlueRatio 0.759; any two spots
   alone gave 1.17..1.48 depending on the pair, so fit, don't pair. Set
   `[Film Negative] RedRatio` and `BlueRatio`;
   `GreenExponent` stays 1.5.
7. **Reference spot** (white balance and level): `[Film Negative] RefInput` = a neutral spot's
   `avg` as `"r;g;b"` (or a point on the fitted line, reference.md);
   `RefOutput` = `"L;L;L"` with `L` = intended reflectance x 65535 (18% grey
   about 11800, light stone ~0.3 about 19700). Without `RefInput` ART
   estimates from channel medians (20% border cut); ART's default
   RefOutput 65535/24 (about 2731) is that median case.
8. **Check**: `image_stats` (crop is applied). Raise `L` in steps (11800 ->
   15000 -> ...) until `clipped_high` is about 0 in every channel (a bright
   blue sky may clip a little in `b` first: stay under ~0.05%); `lum` p99.9
   of 220-245 is typical. Then `render_preview` and look. Colour cast:
   re-pick `RefInput` on another neutral, or change white balance WITHOUT
   changing brightness with the rule in reference.md.
9. **Black point and contrast** (`tone_curve`, sRGB-encoded 0..1, roughly
   `image_stats` value / 255): take the lowest of the three channels'
   percentile 0.1 (the lum one hides a channel that sits lower), subtract
   ~5, divide by 255 -> `x0`; set `curve1`
   `{type: "spline", points: [[x0,0],[0.6,0.6],[1,1]]}` (e.g. x0 = 0.24).
   Then `image_stats`: `clipped_low` should stay under ~0.5% per channel
   (a larger one means x0 is too high). Read the result's `drawn` and
   `warnings` (clips, reversals). For an S-curve use `tone_curve.contrast`
   (e.g. 20), not curve points. Setting a curve turns `histogram_matching`
   off (listed under `implied`), which can change brightness a lot: re-run
   `image_stats` after every tone change.
10. `export_image(path, output, format, ...)` and/or `save_sidecar(path)`.

## A whole roll

Ratios are a property of the film and development: fit once, reuse.

1. Do the single-frame steps on one representative frame (rotation, crop,
   RefInput/RefOutput included).
2. `save_partial_profile(path, dest="<roll>.arp", exclude=["Coarse
   Transformation", "Crop", "Film Negative/RefInput", "Film Negative/RefOutput"])`:
   the roll preset. It holds only keys whose value you CHANGED from the
   opened profile (a key already at the wanted value, e.g. `ColorSpace=1`,
   is not in it), and it carries this frame's black point and `contrast`;
   read the returned `keys` and the file. Use it with `art-cli -p` / ART's
   profile loading, or re-apply the same edits per frame.
3. Each other frame: `open_image`, base settings and the roll's ratios (same
   `edit_profile` as step 2 and 6 above), then per frame: rotation (preview
   first), crop, `RefInput`/`RefOutput` from that frame's own neutrals (a few
   spots; `RefInput` = a neutral's `avg` or a point on the roll's line),
   output level and black point re-checked with `image_stats`.
4. A frame in different light (greenhouse, indoor, flash) needs its own white
   balance: sample neutrals in that frame, keep only spots that agree on the
   intercepts against the roll's line (reference.md), set `RefInput` on the
   line and `RefOutput` by the brightness-preserving rule. Do not refit the
   ratios unless the frame is another film or development.
5. Check each frame with `image_stats` and a preview.

## Pitfalls

- `sample_spots` coordinates are frame pixels, not preview pixels, and ignore
  the crop's origin: they are the same system as `[Crop]`.
- `image_stats` before cropping is dominated by the holder.
- A tone curve implies `histogram_matching` false; a changed brightness after
  setting a curve is that.
- Edits are in memory until `save_sidecar`; previews and exports never write
  the sidecar.
