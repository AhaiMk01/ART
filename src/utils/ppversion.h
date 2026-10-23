/* -*- C++ -*-
 *
 *  This file is part of ART.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
 *  Copyright (c) 2017-2026 Alberto Griggio <alberto.griggio@gmail.com>
 *
 *  ART is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  ART is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with ART.  If not, see <http://www.gnu.org/licenses/>.
 */

#pragma once

namespace art { namespace utils {


// This number has to be incremented whenever the ARP file format is modified or
// the behaviour of a tool changes
#define PPVERSION 1063

/*
  Log of version changes
  1063  2026-10-23
        upstream 1047: adjusted coarseness coefficient for Grain ISO and
        Smoothing in NOISE mode (renumbered: fork versions 1046-1061 predate
        it)
  1062  2026-10-23
        upstream 1046: renamed FattalToneMapping to DynamicRangeCompression
        (renumbered; the group is looked up by name, so upstream 1046/1047
        sidecars still load)
  1061  2026-10-12
        film negative: the print LUT (CineonLUT* keys, LegacyInputLUT), the
        paper target (PaperCurve, PaperBasis) and the Cineon TIFF export
        (TargetMode, CineonPrimaries) are removed. Old keys are ignored, so
        such sidecars render and export the linear positive. PreserveRange
        is removed too: Exposure clamps NamiColor's negative RGB at zero, as
        for every other source. DenoiseBeforeInversion is removed: Denoise
        runs on the inverted positive again, as before 1059
  1060  2026-10-11
        film negative: TransmissionFloor, the lowest transmission taken
        before the log in Density and NamiColor (new profiles 1/65535;
        sidecars before 1060 keep 1e-10)
  1059  2026-10-10
        film negative: DenoiseBeforeInversion (new profiles denoise the
        camera-linear negative before the film conversion; sidecars before
        1059 keep denoising the inverted positive) and Flare, a per-channel
        veiling-light transmission subtracted before the log (absent = 0)
  1058  2026-10-09
        film negative: CineonReferenceWhite defaults to 0.9 (code 685 = 90%
        diffuse white); NamiColor FitBase anchors the film base to code 95
        (saved NamiColorFitBaseAnchor=legacy|code95). Older profiles without
        the keys load W = 1.0 and the legacy 93/1023 lift
  1057  2026-10-09
        film negative: preserve NamiColor exposure and print-LUT RGB range;
        reject clipped integer Cineon handoffs; old profiles retain zero floors
  1056  2026-10-09
        film negative: print LUT after scene grading by default; older LUT
        profiles retain their pre-grading and input-domain rendering order
  1055  2026-10-07
        film negative: optional NamiColor density-domain digital mask before
        channel alignment; older NamiColor profiles retain identity rendering
  1054  2026-10-09
        film negative: NamiColor conversion and selectable print LUT input
        transfer; print LUT applied after conversion to working primaries
  1053  2026-10-07
        film negative: LUT hash recorded by the panel, black offset after
        a print LUT, wrong-length arrays fail load, disabled Cineon target
        does not encode
  1052  2026-10-07
        film negative: basis binding includes input gamma and source id;
        a missing or mismatched binding, unknown identifier, or changed
        Cineon LUT fails the render instead of continuing
  1051  2026-10-07
        film negative: Method, FilmType, MatrixPreset and TargetMode stored as
        text ids. Integer sidecars still load. Unknown tokens are not substituted
  1050  2026-10-07
        film negative: managed Cineon print LUT (#54)
  1049  2026-10-07
        film negative: row-major density matrix, basis binding, calibration note
  1048  2026-10-07
        film negative: paper target mode and reference print curves
  1047  2026-10-07
        film negative: Cineon target, primaries and reference white
        film negative: output black offset subtracted in normalized linear
        film negative: InputGamma scanner source-transfer override (#48)
  1046  2026-10-07
        film negative: core density inversion engine and parameters
  1045  2026-05-25
        improve feathering formula for external masks
  1044  2025-11-11
        added option to apply DCP look early in the pipeline
  1043  2025-02-25
        added color mode to film grain
  1042  2024-12-30
        added gamma to color/tone correction in HSL mode
  1041  2023-12-09
        changed format of LUT parameter values
  1040  2023-08-30
        changed position of the film simulation tool in the pipeline
        (with "after_tone_curve" param to keep backwards compatibility)
  1039  2022-11-19
        new film negative tool ported from RT5.9
  1038  2022-08-12
        brush mask: changed "hardness" and "transparency" to "opacity"
  1037  2022-07-23
        log encoding saturation control
  1036  2022-05-01
        color correction: changed behaviour of hueshift in HSL mode
  1035  2022-04-30
        changed behaviour of the compression slider in color correction
  1034  2022-04-09
        changed behaviour of the tone curve contrast slider
  1033  2022-02-23
        added compression sliders to the color correction tool
  1032  2022-02-17
        added noise option to the smoothing tool
  1031  2022-01-27
        added option to use CAT for standard matrix input profiles
  1030  2022-01-25
        changed balanced highlight recovery value from ColorBlend to Balanced
  1029  2021-12-07
        color correction power inversion
  1028  2021-12-04
        color correction wheel rescaling
  1027  2021-11-09
        white balance multipliers stored in camera space
  1026  2021-07-06
        tone curve mode refactoring/simplification
  1025  2021-06-10
        finer-grained control of tone curve contrast with logenc enabled
  1024  2021-05-06
        log encoding -> source gray changed to EV gain (in log2 scale)
  1023  2021-04-15
        changed scale of the chromaticity curve mask
  1022  2020-12-18
        brush strokes adaptation for better interaction with drawing tablets
  1021  2020-11-10
        output sharpening always applied if enabled
  1020  2020-09-28
        streamlined tone equaliser regularization
  1019  2020-08-08
        binary encoding of brush mask strokes
  1018  2020-07-24
        color correction: added output saturation
  1017  2020-06-11
        store filenames as URIs
  1016  2020-05-31
        renamed GuidedSmoothing to Smoothing, added gaussian mode
  1015  2020-05-13
        added AreaMask::per_shape_feather, Shape::feather and Shape:::blur
  parameters 1014  2020-05-07 added support of Polygon shape for masks,
  Rectangle are now saved with an additional Type parameter 1013  2020-04-21 do
  not use exposure compensation when computing auto settings for logenc 1012
  2020-04-11 new defaults for metadata 1011  2020-03-31 new film negative 1010
  2020-03-28 dehaze, changed strength from integer to (luminance) curve 1009
  2020-03-26 texture boost, renamed edgeStopping to detailThreshold 1008
  2020-02-19 parametric masks reorganization 1007  2020-01-17 added HSL mode to
  color correction 1006  2019-12-26 logenc: changed detail to
  preserveLocalContrast 1005  2019-12-24 added individual channel sliders for
  slope,offset,power in ColorCorrectionParams 1004  2019-11-28 added PPI and
  Unit to ResizeParams 1003  2019-11-25 increased sensitivity of
  ColorCorrectionParams.Offset 1002  2019-10-20 ToneEqualizer.Detail -->
  ToneEqualizer.Regularization 1001  2019-10-06 AreaMaskInverted -->
  MaskInverted 1000  2019-07-29 Bumped to 1000 for ART 350  2019-07-07 split
  ToneCurveParams into ExposureParams, BrightnessContrastSaturationParams and
  ToneCurveParams 349  2019-01-14 changed logenc.base to logenc.targetGray 348
  2018-12-30 local smoothing color correction separate from color toning 347
  2018-12-13 masks in CBDL 346  2018-12-07 new denoise parameters 345 2018-10-21
        dual demosaic auto contrast threshold
   344  2018-10-04
        added Lab/RGB color space selection for shadows/highlights
   343  2018-09-06
        raw auto ca correction avoid colour shift
   342  2018-09-05
        raw auto ca correction iterations
   341  2018-07-22
        [ICM] enhanced custom output profile
   340  2018-07-08
        store whether curve is from histogram matching
   339  2018-07-04
        added allowUpscaling to ResizeParams
   338  2018-06-15
        increased precision for the channel mixer
   337  2018-06-13
        new scales for the LabGrid color toning parameters
   336  2018-06-01
        new demosaic method combobox for pixelshift
   335  2018-05-30
        new contrast adjuster in Bayer process tool
   334  2018-05-13
        new contrast threshold adjuster in Microcontrast tool
   333  2018-04-26
        new Shadows/Highlights tool
   332  2018-04-18
        changed pixelShiftEperIso calculation
   331  2018-02-14
        changed wavelet.Lmethod to int
   330  2018-01-20
        Added 'Auto-matched Tone Curve' button, performing histogram matching
   329  2017-09-12
        Added 'Enabled' flag for Channel Mixer, RGB Curves, HSV Equalizer and
  L*a*b* Adjustments 328  2017-11-22 Fix wrong type of ff_clipControl 327
  2017-09-15 [Profiled Lens Correction] Added Lensfun 326  2015-07-26 [Exposure]
  Added 'Perceptual' tone curve mode 325  2015-07-23 [Exposure] [RGB Curves]
  [B&W] Normalized RGB pipeline curve gammas to sRGB (before it was a mix
  between sRGB and 1.0 and depended on file format) 323  2015-10-05 [Exposure]
  Added 'Luminance' tone curve mode 322  2015-01-31 [Wavelet] new tool using
  wavelet levels 321  2014-08-17 [Film Simulation] new  tool using HALDCLUT
  files 320  2014-07-02  (yes, same version number... this is an error due to a
  wrong version number set in comment of previous change) New [RAW Bayer] and
  [RAW X-Trans] sections, with some parameters transferred from [RAW] to [RAW
  Bayer] 320  2014-03-29 [ColorToning] new tool for color toning 319  2014-02-11
        Hue skin for Contrast by detail levels
   318  2014-02-10
        Vignetting Correction bug makes hard transitions for positive Amount
  values, Issue 2241 317  2014-01-19 changes to behaviour of LC curve, Issue
  2209 315  2013-12-12 add LH et HH curve to lab mode 313  2013-11-19 add CL
  curve to lab mode 312  2013-11-08 added numerous changes to [channel mixer]
   311  2013-11-07
        [Gradient] new tool (gradient/graduated filter
        [PCVignette] new tool (vignette filter)
   310  2013-09-16
        Defringing /Threshold - changed calculation, issue 1801
   307  2013-03-16
        [Perspective] Horizontal and Vertical changed from int to double
        added  [Directional Pyramid Denoising] Method, Redchro, Bluechro
        added [RGB Curves] LumaMode
 */


} } // namespace art::utils
