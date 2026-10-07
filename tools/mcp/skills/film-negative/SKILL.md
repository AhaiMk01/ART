---
name: film-negative
description: Invert a camera-scanned colour-negative roll or frame in ART with the density method (rebate, Dmax, reference white, then a print or Cineon handoff). Also a print curve, a Cineon TIFF, or an old power-law sidecar left unchanged.
---

# Inverting colour negatives

Needs the `art-render` MCP server, and an ART build whose `art-cli` supports `sample_spots`. Formulas are in [reference.md](reference.md), section "Density method". Power-law sections there apply only when an old sidecar stays on `power_law`.

A new inversion sets `method: "density"`. A missing `Method` is `power_law`.

After every step, look. One frame: `render_preview(inline=true)`. A roll: `contact_sheet(images, record=false)` for a working look, and a recorded `contact_sheet(images, folder=<work folder>, label=...)` when the step changed the roll. The step is done when the picture matches its criterion. When it does not, move that step's own control and look again.

Edits stay in memory until `save_sidecar`. Previews and exports never write the sidecar. Write one only when asked.

## One frame

1. **Known state.** `open_image`. `profile_from: "sidecar"` means old edits came along. `reset_profile(to="default")` before a new inversion. Done when the frame is open from the default profile, not from a leftover sidecar.

2. **Linearize and invert.** One `edit_profile`:
   - `exposure` `{enabled: false, hl_recovery: "Off"}` in the same request.
   - `tone_curve` `{mode: "Standard", histogram_matching: false, curve1: {type: "linear"}, curve2: {type: "linear"}}`. These curves stay linear. They are not the black or the white.
   - `sharpening` `{enabled: false}`.
   - `film_negative` `{enabled: true, method: "density", film_type: "negative", color_space: "working", input_gamma: 1, density_gamma: 1, density_dmax: 2.5, channel_gamma: [1, 1, 1], matrix_preset: "identity", target_mode: "linear"}`.
   - `raw_edits`: `[RAW Bayer] Method=amaze`, `[RAW] CAEnabled=false`. The input profile is the camera profile for the scan light; working profile `Rec2020` unless the ask names another. `sample_spots` uses `space="working"`.
   Done when `get_profile(groups=["Film Negative"])` shows `Method=density`, the preview is a positive, and the tool result has no film-negative error. An orange negative means the contract failed: read the error and fix that control. The uninverted scan is not a picture to grade.

3. **Crop the holder.** Measure the border with `sample_spots` along each side, then `crop` `{enabled: true, fixed_ratio: false, x, y, w, h}` inside the jumps, leaving rebate in frame so it can be sampled. Coordinates are frame pixels (`x = px * frame_width / preview_width` on an uncropped preview). Done when the preview has no holder and no picture cut off.

4. **Clear end.** Sample unexposed rebate (the gap between frames), before inversion. One `edit_profile` with `film_base_sample` set to that spot's `avg`. Send the sample, not `rgb_gains`. Done when the result sets all three `RGBGains` and the rebate is black in all three channels, while picture shadows are still separated from it. A refused pick (a gain outside -3..3, or a bad sample) changes nothing: report it and stop that frame. Reversal has no rebate pick.

5. **Dense end.** `density_dmax` is `-log10(T)` of a fully exposed patch of this roll, or the stock value `2.5` when no such patch exists. `T` is the patch's `sample_spots` average divided by 65535. A lamp or the darkest pixel of a normal frame is not that patch. Done when subject highlights are open and a specular is brighter than the subject white.

6. **Reference white.** A diffuse white (paint, paper, concrete), not a lamp or a specular. Compute its post-inversion linear value with the Density method formula in [reference.md](reference.md) and set `cineon_reference_white` to it. No such patch: leave `1`. Done when that white, not a specular, is the anchor. Linear `1` encodes to Cineon 685; the rebate at `1e-4` encodes to 95.

7. **Matrix.** `identity` unless a calibration measured in this basis is in hand. A custom matrix needs `matrix_preset: "custom"`, nine coefficients, and `matrix_basis` (`v`, `color_space`, `profile`, `input_gamma`, `source` from `inspect_image`, and `content` when the profile file has one). A mismatch fails the render. Status M is DiVERE's empirical reference, not a measurement of this scan: select it only when the ask names it, bind `matrix_basis`, and say so. Done when a residual orange mask is either gone or reported as unmeasured. Rebind if the profile changes.

## A roll

Do each shared thing once, on a representative, then spread it. Per-frame values go in one `edit_profile(items=[...])`. The same value for many frames is `paths=[...]`. Measure with one `image_stats(paths=[...], detail="compact")` or one contact sheet, then one items call, then look again.

`inspect_images` runs only after `open_image` has returned. Read every frame's `shutter_seconds`, `iso`, and `aperture`. Those are the scanning camera's. The same values mean one scan setup, not one scene light. A null aperture uses shutter and ISO only.

0. **Open.** `open_image(paths=[...])`, 10 to 15 frames a call. Reset any frame whose `profile_from` is `sidecar`. Done when every frame is open from the default profile.

1. **Representative.** One frame per scan-exposure group, with visible rebate, a diffuse white, real shadow and highlight, and not only lamps. A flat frame is a bad representative. Run "One frame" on it, looking after each step. Record `contact_sheet(..., label=identity)` after the first positive, and `label=ends` after the rebate, Dmax, and reference white.

2. **Preset.** `save_partial_profile(path, dest="<roll>.arp", vs="default", exclude=["Coarse Transformation", "Crop"])`. `vs="default"` writes every key that differs from ART's default, so the base settings travel with it. When scan exposures differ, also exclude `Film Negative/RGBGains` and re-pick the rebate per exposure group. Read the returned `keys`. Done when the file holds `Method=density`, the matrix, `Dmax`, and the linear curves, and does not hold the representative's rotation or crop.

3. **The other frames.** `apply_preset(paths=[...], profile="<roll>.arp")` in one call. Then, per frame and in one `items` call where the values differ: rotation (look first), crop (one common crop when the holder barely moves; look that no frame keeps a holder or loses picture), a rebate pick when that frame's scan exposure differs, and a reference white when its diffuse white disagrees with the representative. Scene light does not refit the inversion. Done when a recorded contact sheet shows every frame inverted, rebate black, and holder gone. `compare_passes` against the identity pass for any frame that still looks like the orange scan or a flat grey.

4. **Grade only the view.** A print ask: `target_mode: "paper"`, a `paper_curve` (Kodak 2383, 2393, Ektacolor Edge, Endura Premier, Portra, Supra, Ultra Endura, Ilford MGFB 00 and 0 through 5), and `paper_basis` as `working|<profile>` or `input|<profile>`. Ilford curves stay shared RGB. Look at a `label=print` sheet and change the curve id, not the rebate. No print ask: leave `target_mode: "linear"`. A Cineon print LUT is `cineon_lut` plus `cineon_lut_sha256` of those bytes, and not `paper` at the same time. `output_black_offset` (0 to 0.05) applies after a LUT is decoded.

5. **Handoff, only when asked.** A DI handoff is `target_mode: "cineon"`, no print LUT, and `export_image` / `export_batch` as 16-bit integer TIFF. JPEG and PNG do not encode. `cineon_primaries` empty means the working profile. To keep each frame's settings beside an export, `write_profile: true, profile_name: "source"`. The image's own sidecar is never written. Export 10 to 15 frames a call when the client timeout is short.

## An old sidecar

`Method` missing or `power_law`, and the ask is not a new inversion: leave the method. The ratio fit, `ref_input`, and `ref_output` are in [reference.md](reference.md), "Power-law". Those spots are not density gains. Converting that sidecar is a new inversion: reset to default and start at "One frame".

## Pitfalls

- `sample_spots` reads the negative, before inversion, in frame pixels. It ignores the crop origin. A cropped preview: `x = crop.x + px * crop.w / preview_w`.
- `image_stats` and the preview are an 8-bit view. They can show a coloured rebate or a clipped lamp. They cannot show linear `1e-4`. The pick result is the measurement.
- `image_stats` before the crop counts the holder.
- A whole `get_profile` is about 15k tokens. Ask for `groups: ["Film Negative", "Crop", "Color Management", "ToneCurve"]`.
- `film_base_sample` applies only to density, negative, with a bound matrix or identity. A mismatched basis fails the render.
- `input_gamma` stays 1 on RAW and on a profiled scan. Any other value fails the render and leaves the scan uninverted.
