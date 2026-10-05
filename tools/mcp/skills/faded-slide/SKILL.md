---
name: faded-slide
description: Restore a faded colour slide or other positive (Ektachrome-style dye fading, a blue/magenta/yellow cast, scans where the cast differs between shadows and highlights so white balance can't fix it) with the ART MCP tools (art-mcp-render). Use when asked to fix, restore or colour-correct a faded slide scan, or when image_stats shows a per-channel cast that changes with brightness.
---

# Restoring a faded slide with ART

Uses the `art-render` MCP tools (`open_image`, `image_stats`, `sample_spots`,
`edit_profile`, `render_preview`, `get_profile`, `save_sidecar`). Formulas, worked numbers and a
fitting script: [reference.md](reference.md).

## Why white balance fails

Fading changes each dye's density, which scales it as a **power law in linear
light**: `green = A * channel^k`. Blue and red (k != 1) then differ from green by a
ratio that changes with brightness. ART's `color_correction` applies exactly that
(slope, then power) per channel, so fit and apply it. Each slide needs its **own** fit
(fading differed between slides of one roll: k 2.0 vs 1.6); never reuse one.

## Steps

1. **Open and diagnose.** `open_image`, then `image_stats` (crop first if the scan
   includes the mount, see step 5). Compare channel percentiles at p1 and p99. If the
   ratio between channels differs (e.g. blue 67 vs red 23 at p1 but 238 vs 201 at p99),
   it is not a plain cast: continue. If the ratios match, `white_balance` is enough.
   Keep these numbers for the before/after report.
2. **Sample neutrals.** `render_preview`, look at it, pick 14 to 16 spots that should be
   neutral grey across the whole tonal range. Choose by material, not by how grey
   it looks: white paint, bare/galvanised metal, concrete, overcast sky or haze are
   good; natural stone, black fabric (dyes aren't neutral), glass, foliage, wood,
   brick, red plates and painted machinery are risky (a "blue" snowplough really
   was painted grey-blue). Agreement only counts between INDEPENDENT materials:
   several spots of the same stone agreeing prove nothing. Convert preview
   pixels to frame pixels (`sample_spots` takes frame coordinates; with no crop,
   `x = px * frame_w / preview_w`, frame size is in the `sample_spots` result; with a
   crop, `x = crop.x + px * crop.w / preview_w`). Call `sample_spots` (max 16 per call; values are linear 0..65535,
   white-balanced, before any film negative tool; size 32 default; use a small `size` on small objects) and use `avg`.
3. **Fit.** For each channel `c` in {r, b} against green, least squares of
   `ln(g/65535) = a + k * ln(c/65535)` over the spots (script in reference.md). Then
   set `power = 1/k` and `slope = exp(a)^(1/k)` (NOT `exp(a)`: slope acts before the
   power; using `exp(a)` over-boosted blue by 19%). Green stays untouched. Typical:
   blue k 1.6 to 2.1, red about 1. Check stability by refitting with each spot left out:
   if k barely moves (e.g. 2.06 to 2.15) keep all spots; don't apply a fixed residual
   threshold (one wrongly dropped 6 of 14 good spots). A spot with a large single
   residual is usually a painted surface: drop only those, and say so.
   A CDL `offset` term helped on none of three slides: add it only if the darkest
   neutrals share a systematic residual.
4. **Apply** with the typed adjustment (regions[0] = ART's region 1):
   ```
   edit_profile(path, adjustments={"color_correction": {"regions": [
     {"r": {"slope": S_r, "power": P_r}, "b": {"slope": S_b, "power": P_b}}]}})
   ```
   Slope range 0.01..10, power 0.1..4 (out of range is an error, nothing is clamped).
   Re-run `image_stats` and `render_preview`: p99 of r, g, b should now agree
   within a few levels (p1 too once the mount is cropped, step 6). Fix a remaining uniform tint with `white_balance` last.
5. **Spatial faults (edge fading).** If the preview still has bands or corners with a
   different cast, add region 2 with a mask: see "Spatial faults" in reference.md.
6. **Crop the mount** (`crop` adjustment: `x, y, w, h` in frame pixels, all four
   together; give `fixed_ratio: false` for a free rectangle (ART's default keeps a
   fixed ratio in the editor's crop tool); the mount edge in the preview
   is at preview px x frame_w / preview_w, add a small margin). Render and check the
   edges: a thin yellow line at the top means start the crop lower. Then re-run
   `image_stats`: the mount dominated p0.1..p5 before (blue p1 was 4 after the colour
   fix, 25 once cropped), so judge the black point and channel agreement only now.
7. **Tone.** On the cropped `image_stats` (lum). If p1 is below about 25, only set
   `tone_curve.contrast` (10 to 20): it keeps histogram matching on, and on the test
   slide `contrast 20` took p1 20 to 9 with median 92 to 78. If you need a black point
   or a midtone lift, set `tone_curve.curve1`: that turns `histogram_matching` off
   (listed in `implied`) and the image gets much darker (median 92 to 51, p99 217
   to 145 with no curve). Recipe: with matching off and `curve1` linear, read the lum
   percentiles p1, p50, p99 (value / 255 = the curve's x), then add points mapping
   them to the levels you want (p1 to about 10, p50 to the old median, p99 to the old
   p99), e.g. `[[0,0],[0.035,0.04],[0.2,0.36],[0.57,0.85],[1,1]]`, and check
   `image_stats` again (result: p1 10, median 85, p99 218).
8. **Finish.** Edits live only in the server's working profile until saved. `render_preview` of the whole image and a 1:1 `region`, then
   `save_sidecar` if the user wants the result kept, or `export_image`.

## Rules of thumb

- Never trust one spot pair; always fit many.
- Re-measure after every change, including places that must not change.
- Report fitted `k`, `slope`, `power` per channel and the before/after percentiles.
