---
name: film-negative
description: Convert camera-captured colour-negative frames or rolls in ART, with or without visible film base. Use shared capture conditions to estimate conversion, adapt individual scenes and assess the rendered result; also handle print rendering, Cineon handoff or existing power-law profiles.
---

# Converting colour negatives

Use the existing `art-render` tools. The aim is a coherent, plausible positive that preserves the recorded scene, not merely a recognizable inversion. Without capture/film characterization, describe colour recovery as an estimate and distinguish observations from assumptions.

For a new conversion, use NamiColor in a declared working RGB basis. Preserve existing Density or power-law conversions unless migration was requested. Keep source images and sidecars unchanged unless the user asks to save them. Consult "NamiColor and the processing basis" in [reference.md](reference.md) before selecting its controls.

## Establish usable evidence

Understand the requested result, available profiles and capture conditions before choosing adjustments. A roll normally shares its digitization setup; individual frame exposure, placement and scene lighting can still differ. Separate evidence of a changed setup from ordinary scene variation.

Confirm that previews arrive as viewable images before using them as evidence. Restore image delivery if a view cannot be inspected; a saved path or unreadable bytes are not a visual review. For ART image transport, consult "Viewing previews" in [reference.md](reference.md).

Inspect each frame's orientation and picture boundaries before using its content for estimation. Derive geometry from that frame, not from another frame's position on the sensor. Verify the resulting positive's orientation, edges and corners at a readable size before treating its geometry as settled; preserve scene content when correcting borders. For coordinate mapping and ART-specific constraints, consult "Per-frame geometry" in [reference.md](reference.md).

Establish input colour management and the working RGB basis before inversion; camera profiles are approximations when capture characterization is unavailable. Save a viewable initial positive without a print LUT or endpoint stretch. ART's default raw profile turns on the tone curve's histogram matching, which fits a curve to the camera's embedded preview of the negative: set `tone_curve.histogram_matching` false before judging the positive. Keep the diagnostic viewing response consistent during fitting. The basis is settled when its settings and processing order are known and the actual preview is usable, not when the image merely becomes recognizable.

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

Correct a negative's defects before inversion, a positive's after it. Lens-profile vignetting (lensfun, LCP, EXIF; raw only) and a raw flat-field act before inversion and are the right correction. The manual Vignetting Correction tool acts on the inverted positive and is wrong for negatives (see "Processing order and domains" in [reference.md](reference.md)); scans have no pre-inversion vignetting path. Denoise runs before inversion by default on new profiles (`denoise_before_inversion`); sidecars below version 1059 keep the old order; strength settings need retuning after switching order (check a 1:1 crop of the darkest positive areas). Veiling light (`flare`, density and NamiColor only) is an estimate, never a measurement. Grading order: scene-linear gains (exposure, white balance) and printer-light offsets are domain-independent; non-linear tools before the print LUT are looks; the print LUT or paper curve is the tone curve.

## Adapt scenes and finish the positive

Separate shared conversion from scene-specific exposure and illumination. Preserve genuine warm light, cool shadows and low-key scenes rather than forcing every frame to the same histogram or neutral appearance.

For a new scene-referred conversion, place scene adjustments before the print response. Confirm the retained profile's LUT position before editing: older conversions can deliberately keep their original order. Changing that order is a separate comparison, not a reason to refit the inversion.

Assess final presentation separately from the initial inversion. Freeze the supported conversion while comparing display contrast or a requested print response. Judge shadow detail, midtone separation, highlight gradation and colour changes; a stronger curve is not automatically better. Cineon codes follow one convention: 95 is linear zero and 685 is 90% diffuse white (`cineon_reference_white` 0.9 on new profiles; 1 on sidecars below version 1058 without the key; 18% grey encodes near 480.8, a check and not 470 as an anchor). Do not mix three things: the encoding convention (constants and W), endpoint estimation from this picture (black, gain, shift, FitBase, using `sample_spots` on evidence that excludes rebate, off-film areas, dust, speculars, emitters and unfounded neutrals, never raw minimum or maximum), and aesthetic grading. Without a film base and calibration, make no absolute density claim. For Cineon handoff, the Dmin-to-95 and white-to-685 recipe, or print LUTs, consult "Cineon handoff and print LUTs" in [reference.md](reference.md) before changing the viewing path.

Before using a print LUT, write its contract (file, sha256, size/domain, input and output transfer and primaries, white point, stage, W), tagging each item DOCUMENTED with its source, VERIFIED with its evidence, or ASSUMED; done when no item is untagged and an identity-cube render separates conversion error from the print look. Follow "LUT contract procedure" in [reference.md](reference.md). The record lives in your evidence notes, not in the sidecar.

Review the roll for continuity and each frame for its own defects. Use enlarged views where a contact sheet cannot answer the question. Correct visible, actionable problems before delivery; explain actual evidence limits rather than treating unfinished work as uncertainty.

## Verify and hand off

Use the existing tools to render, compare, sample and inspect relevant profile groups. Read current adjustment contracts when needed. Four different things can be observed and must be labelled with their stage: `sample_spots` `stage` source (pre-inversion, camera or working space), `converted` (recovered linear working-space RGB, 0..65535, before LUT/exposure/grading) and `cineon` (those pixels as Cineon codes with W); `image_stats` `stage` converted / cineon (Render: per-channel statistics and histograms of the same data) or display (8-bit rendered output, never a Cineon scope). See reference.md, "Observing each stage". A tool success or statistic alone does not replace inspection of the pictures. Keep calculations task-local; the workflow does not require new helper or mechanical acceptance scripts.

Match exports and saved profiles to the user's requested handoff. `export_image` with `write_profile` names the profile `<output>.arp` (`IMG.jpg.arp`); `profile_name: "source"` names it as ART's sidecar for the image instead. Keep shared conversion separate from per-frame geometry and scene adjustments in reusable presets. Reload saved settings on representative or unusually adjusted frames and compare geometry, colour and tone under comparable viewing conditions. Deliver the requested display image as well as any intermediate, and state which operations its saved profile can reproduce. If processing fails, retain the error and distinguish any explicitly identified intermediate-based comparison from an ART re-render.

For an unprinted intermediate, preserve and declare its processing basis. Distinguish the stored numerical range from its display rendering; use the handoff contract in [reference.md](reference.md) rather than inferring preservation from a floating-point file extension.

Report what was compared, why the chosen conversion was retained, the exact output paths and what remains uncertain. Confirm source preservation. Treat measured calibration, scene-based endpoint estimates and aesthetic presentation as separate claims.
