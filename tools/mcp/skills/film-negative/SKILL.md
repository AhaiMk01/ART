---
name: film-negative
description: Convert camera-captured colour-negative frames or rolls in ART, with or without visible film base. Use shared capture conditions to estimate conversion, adapt individual scenes and assess the rendered result; also handle existing Density or power-law profiles.
---

# Converting colour negatives

Use the existing `art-render` tools. The aim is a coherent, plausible positive that preserves the recorded scene, not merely a recognizable inversion. Without capture/film characterization, describe colour recovery as an estimate and distinguish observations from assumptions.

For a new conversion, use NamiColor in a declared working RGB basis. Preserve existing Density or power-law conversions unless migration was requested. Keep source images and sidecars unchanged unless the user asks to save them. Consult "NamiColor and the processing basis" in [reference.md](reference.md) before selecting its controls.

## Establish usable evidence

Understand the requested result, available profiles and capture conditions before choosing adjustments. A roll normally shares its digitization setup; individual frame exposure, placement and scene lighting can still differ. Separate evidence of a changed setup from ordinary scene variation.

Confirm that previews arrive as viewable images before using them as evidence. Restore image delivery if a view cannot be inspected; a saved path or unreadable bytes are not a visual review. For ART image transport, consult "Viewing previews" in [reference.md](reference.md).

Inspect each frame's orientation and picture boundaries before using its content for estimation. Derive geometry from that frame, not from another frame's position on the sensor. Verify the resulting positive's orientation, edges and corners at a readable size before treating its geometry as settled; preserve scene content when correcting borders. For coordinate mapping and ART-specific constraints, consult "Per-frame geometry" in [reference.md](reference.md).

Establish input colour management and the working RGB basis before inversion; camera profiles are approximations when capture characterization is unavailable, and a camera profile's hue/saturation map and look table do not apply to film densities (turn them off before inversion). Save a viewable initial positive without an endpoint stretch. ART's default raw profile turns on the tone curve's histogram matching, which fits a curve to the camera's embedded preview of the negative: set `tone_curve.histogram_matching` false before judging the positive. Keep the diagnostic viewing response consistent during fitting. The basis is settled when its settings and processing order are known and the actual preview is usable, not when the image merely becomes recognizable.

## Convert to a finished positive

ART renders a finished positive; it has no print LUT, paper curve or Cineon export. For a print-film look (a Cineon LUT such as 2383), use NamiColor and the LUT in DaVinci Resolve instead, outside this workflow.

1. Align the channels with a pooled roll fit: pick neutral squares in every frame by the steps of "Choosing neutral references" in [reference.md](reference.md) (a clean frame first, neutral by material, one light, measurable squares, independent objects and tones, an active search; zoom and numeric checks; a basis per square); fit one robust set of channel slopes for the roll with one offset per frame, and shrink each frame's offset toward its light group by its evidence. Use "Pooled roll fit" in [reference.md](reference.md); keep the slopes moderate rather than steepening them for contrast, and take the slope from a preset fitted in the same processing basis when too few frames carry it. Done when every frame's graded neutrals decode neutral at the `converted` stage within a stated tolerance, the slope's frame-bootstrap interval is reported, the per-frame offsets and their shrinkage are explained by the scene light, and the remaining cast at each tonal level is reported.
2. Digital mask: only if saturated colours show coupling the slopes cannot fix, try a Custom mask (ART applies it before the alignment terms), then refit step 1 and recheck reserved materials. Done when the mask is Identity, or bound and its effect on reserved materials is shown.
3. Contrast: the converted positive is scene-linear and flatter than a photographic print, which has steeper midtones and shadows and a shoulder that compresses the highlights. Recover it after the conversion with `tone_curve.contrast` (pivots on scene middle grey) together with an S-curve or point curve that rolls off the highlights; the contrast slider alone stays flatter than a print in the midtones. Judge the result by its shadow, midtone and highlight separation at a readable size, not by the overall histogram. Done when the midtones read with print-like separation, shadows and highlights hold structure across the roll at the same curve, and the curve is stated in the report.

## Estimate jointly, reason from the result

Choose complementary representative frames and keep other frames for checking transfer. Use the shared setup to constrain common conversion parameters; treat capture-exposure differences separately from original-scene exposure and illumination. Consult "Capture exposure normalization" in [reference.md](reference.md) when those differences matter.

Use image content and samples together. Inspect the full sampling footprint at readable size and keep it inside the intended material, clear of dust, text, edges and reflections. A plausible neutral, dark object or diffuse highlight is a candidate constraint whose confidence depends on the scene, not a known reflectance. A credible film-base patch is optional evidence; its absence does not block estimation. Reference-poor frames can inherit a supported shared conversion with appropriately lower confidence.

Before assigning black or white endpoints, inspect luminance from the ungraded positive. Use it to find dark regions with interpretable material and retained structure, then check their RGB and pre-inversion samples in the declared basis. Keep candidate near-black scene content distinct from measured film Dmin. Consult "Luminance and endpoint evidence" in [reference.md](reference.md); proceed with endpoint estimates only when their evidence and uncertainty are explicit.

Balance credible bright and dark candidates jointly. A white-only alignment can leave shadow colour separation; use independent materials and reserved frames to test the relative channel slopes. Keep a declared anchor stable when changing common contrast or relative slopes, and judge the actual renders rather than parameter magnitude. Consult "Estimation without film base" and the selected method's equations in [reference.md](reference.md).

Iterate from an observed problem:
- State what is wrong in the rendered image and where it occurs.
- Distinguish geometry, capture limitations, shared conversion, scene lighting and final presentation as possible causes.
- Choose a comparison that separates the plausible explanations. Change only what that comparison needs, keep the viewing basis comparable and account for coupled parameter changes.
- Read back the applied settings and inspect the actual images. Judge improvement and regressions across tonal levels and other scenes, not one favourable patch or statistic.
- Retain the simplest explanation supported by transfer; revise the hypothesis when the comparison contradicts it.

For persistent highlight/shadow colour separation, consult "Refitting slopes and diagnosing crossover" in [reference.md](reference.md). Calculations support a comparison; they do not establish visual quality or the original scene's true colour. When the evidence cannot distinguish input characterization, conversion error and scene illumination, retain that uncertainty rather than grading it away.

An optional digital mask can mix NamiColor's effective input densities before channel alignment. Start from Identity; introduce a Custom matrix only when evidence supports colour coupling beyond relative slopes, then refit alignment and check reserved materials and frames. Bind it to the actual processing space, profile, input transfer and source, and record capture/calibration limits. The fixed density pivot 0.7 is numerical, not measured Dmin; Status M reference rows are uncalibrated, not a universal mask. Consult "Optional NamiColor digital mask" in [reference.md](reference.md).

## Processing order and domains

Correct a negative's defects before inversion, a positive's after it. Lens-profile vignetting (lensfun, LCP, EXIF; raw only) and a raw flat-field act before inversion and are the right correction. The manual Vignetting Correction tool acts on the inverted positive and is wrong for negatives (see "Processing order and domains" in [reference.md](reference.md)); scans have no pre-inversion vignetting path. Denoise runs on the inverted positive; check its strength on a 1:1 crop of the darkest positive areas. Veiling light (`flare`, density and NamiColor only) is an estimate, never a measurement. Grading order: scene-linear gains (exposure, white balance) and printer-light offsets are domain-independent.

## Adapt scenes and finish the positive

Separate shared conversion from scene-specific exposure and illumination. Preserve genuine warm light, cool shadows and low-key scenes rather than forcing every frame to the same histogram or neutral appearance.

Assess final presentation separately from the initial inversion. Freeze the supported conversion while comparing display contrast or a requested print response. Judge shadow detail, midtone separation, highlight gradation and colour changes; a stronger curve is not automatically better. Do not mix three things: NamiColor's internal encoding convention (codes 95 and 685, `cineon_reference_white` W), endpoint estimation from this picture (black, gain, shift, FitBase, using `sample_spots` on evidence that excludes rebate, off-film areas, dust, speculars, emitters and unfounded neutrals, never raw minimum or maximum), and aesthetic grading. Without a film base and calibration, make no absolute density claim. Sidecars from before version 1061 with a print LUT, paper target or Cineon export target now render and export the linear positive.

Review the roll for continuity and each frame for its own defects. Use enlarged views where a contact sheet cannot answer the question. Correct visible, actionable problems before delivery; explain actual evidence limits rather than treating unfinished work as uncertainty.

## Verify and hand off

Use the existing tools to render, compare, sample and inspect relevant profile groups. Read current adjustment contracts when needed. Three different things can be observed and must be labelled with their stage: `sample_spots` `stage` source (pre-inversion, camera or working space) and `converted` (recovered linear working-space RGB, 0..65535, before exposure/grading); `image_stats` `stage` converted (Render: per-channel statistics and histograms of the same data) or display (8-bit rendered output, neither linear nor Cineon). See reference.md, "Observing each stage". A tool success or statistic alone does not replace inspection of the pictures. Keep calculations task-local; the workflow does not require new helper or mechanical acceptance scripts.

Match exports and saved profiles to the user's requested handoff. Every display export embeds its output ICC profile: sRGB (`RTv2_sRGB`, ART's default) unless the user asks for Adobe RGB (`RTv2_Medium`) or ProPhoto (`RTv4_Large`), set with the raw edit `[Color Management] OutputProfile`; a wide-gamut export is better as 16-bit TIFF than 8-bit JPEG. Check that the exported files carry the profile and name it in the report. `export_image` with `write_profile` names the profile `<output>.arp` (`IMG.jpg.arp`); `profile_name: "source"` names it as ART's sidecar for the image instead. Keep shared conversion separate from per-frame geometry and scene adjustments in reusable presets. Reload saved settings on representative or unusually adjusted frames and compare geometry, colour and tone under comparable viewing conditions. Deliver the requested display image as well as any intermediate, and state which operations its saved profile can reproduce. If processing fails, retain the error and distinguish any explicitly identified intermediate-based comparison from an ART re-render.

For a linear intermediate, export 32-bit float TIFF with output profile `(none)` and declare its processing basis. Distinguish the stored numerical range from its display rendering rather than inferring preservation from a floating-point file extension.

Report what was compared, why the chosen conversion was retained, the exact output paths and what remains uncertain. Confirm source preservation. Treat measured calibration, scene-based endpoint estimates and aesthetic presentation as separate claims.
