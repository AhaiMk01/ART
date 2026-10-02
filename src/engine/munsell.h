/* -*- C++ -*-
 *  
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
 *  Copyright (c) 2011 Jacques Desmis <jdesmis@gmail.com>  (Munsell correction)
 *
 *  RawTherapee is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  RawTherapee is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with RawTherapee.  If not, see <http://www.gnu.org/licenses/>.
 */

/*
 * Munsell colour correction, formerly part of Color.
 *
 * None of this is currently used by the pipeline, but it is kept for possible
 * future use. init() has to be called once before MunsellLch(),
 * AllMunsellLch() or LabGamutMunsell() (it fills the lookup tables below);
 * nothing calls it at the moment.
 */

#pragma once

#include "LUT.h"
#include "color.h"
#include "sleef.h"

namespace art { namespace engine {

#ifdef _DEBUG

class MunsellDebugInfo {
public:
    float maxdhuelum[4];
    float maxdhue[4];
    unsigned int depass;
    unsigned int depassLum;

    MunsellDebugInfo();
    void reinitValues();
};

#endif

class Munsell {
public:
    /** Fill the lookup tables used by the correction. Call once, before any
     * of the functions below. */
    static void init();

    /**
     * @brief Corrects the color (hue) depending on chromaticity and luminance
     * changes
     *
     * To use in a "for" or "do while" statement.
     *
     * @param lumaMuns true => luminance correction (for delta L > 10) and
     * chroma correction ; false => only chroma
     * @param Lprov1 luminance after [0 ; 100]
     * @param Loldd luminance before [0 ; 100]
     * @param HH hue before [-PI ; +PI]
     * @param Chprov1 chroma after [0 ; 180 (can be superior)]
     * @param CC chroma before [0 ; 180]
     * @param corectionHuechroma hue correction depending on chromaticity
     * (saturation), in radians [0 ; 0.45] (return value)
     * @param correctlum hue correction depending on luminance (brightness,
     * contrast,...), in radians [0 ; 0.45] (return value)
     * @param munsDbgInfo (Debug target only) object to collect information
     */

#ifdef _DEBUG
    static void AllMunsellLch(bool lumaMuns, float Lprov1, float Loldd,
                              float HH, float Chprov1, float CC,
                              float &correctionHueChroma, float &correctlum,
                              MunsellDebugInfo *munsDbgInfo);
#else
    static void AllMunsellLch(bool lumaMuns, float Lprov1, float Loldd,
                              float HH, float Chprov1, float CC,
                              float &correctionHueChroma, float &correctlum);
#endif
    static void AllMunsellLch(float Lprov1, float HH, float Chprov1, float CC,
                              float &correctionHueChroma);

    /**
     * @brief Correct chromaticity and luminance so that the color stays in the
     * working profile's gamut
     *
     * This function puts the data (Lab) in the gamut of "working profile":
     * it returns the corrected values of the chromaticity and luminance
     *
     * @param HH : hue, in radians [-PI ; +PI]
     * @param Lprov1 : input luminance value, sent back corrected [0 ; 100]
     * (input & output value)
     * @param Chprov1: input chroma value, sent back corrected [0 ; 180 (can be
     * superior)]  (input & output value)
     * @param R red value of the corrected color [0 ; 65535 but can be negative
     * or superior to 65535] (return value)
     * @param G green value of the corrected color [0 ; 65535 but can be
     * negative or superior to 65535] (return value)
     * @param B blue value of the corrected color [0 ; 65535 but can be negative
     * or superior to 65535] (return value)
     * @param wip working profile
     * @param isHLEnabled true if "Highlight Reconstruction " is enabled
     * @param lowerCoef a float number between [0.95 ; 1.0[
     *                  The nearest it is from 1.0, the more precise it will be,
     * and the longer too as more iteration will be necessary
     * @param higherCoef a float number between [0.95 ; 1.0[
     *                   The nearest it is from 1.0, the more precise it will
     * be, and the longer too as more iteration will be necessary
     * @param neg (Debug target only) to calculate iterations for negatives
     * values
     * @param moreRGB (Debug target only) to calculate iterations for values
     * >65535
     */
#ifdef _DEBUG
    static void gamutLchonly(float HH, float &Lprov1, float &Chprov1, float &R,
                             float &G, float &B, const double wip[3][3],
                             const bool isHLEnabled, const float lowerCoef,
                             const float higherCoef, bool &neg, bool &more_rgb);
    static void gamutLchonly(float HH, float2 sincosval, float &Lprov1,
                             float &Chprov1, float &R, float &G, float &B,
                             const double wip[3][3], const bool isHLEnabled,
                             const float lowerCoef, const float higherCoef,
                             bool &neg, bool &more_rgb);
    static void gamutLchonly(float2 sincosval, float &Lprov1, float &Chprov1,
                             const float wip[3][3], const bool isHLEnabled,
                             const float lowerCoef, const float higherCoef,
                             bool &neg, bool &more_rgb);
#else
    static void gamutLchonly(float HH, float &Lprov1, float &Chprov1, float &R,
                             float &G, float &B, const double wip[3][3],
                             const bool isHLEnabled, const float lowerCoef,
                             const float higherCoef);
    static void gamutLchonly(float HH, float2 sincosval, float &Lprov1,
                             float &Chprov1, float &R, float &G, float &B,
                             const double wip[3][3], const bool isHLEnabled,
                             const float lowerCoef, const float higherCoef);
    static void gamutLchonly(float2 sincosval, float &Lprov1, float &Chprov1,
                             const float wip[3][3], const bool isHLEnabled,
                             const float lowerCoef, const float higherCoef);
#endif
    static void gamutLchonly(float HH, float2 sincosval, float &Lprov1,
                             float &Chprov1, float &saturation,
                             const float wip[3][3], const bool isHLEnabled,
                             const float lowerCoef, const float higherCoef);

    /**
     * @brief Munsell gamut correction
     *
     * This function is the overall Munsell's corrections, but only on global
     * statement. It may be better to use local statement with AllMunsellLch.
     * They are named accordingly :  gamutLchonly and AllMunsellLch
     * It can be used before and after treatment (saturation, gamma, luminance,
     * ...)
     *
     * @param labL L channel input and output image
     *            L channel's usual range is [0 ; 100], but values can be
     * negative or >100
     * @param laba a channel input and output image
     * @param labb b channel input and output image
     *            a and b channel's range is usually [-128 ; +128], but values
     * can be >128
     * @param N Number of pixels to process
     * @param corMunsell performs Munsell correction
     * @param lumaMuns whether to apply luma correction or not (used only if
     * corMuns=true) true:  apply luma + chroma Munsell correction if delta L >
     * 10; false: leaves luma untouched
     * @param gamut performs gamutLch
     * @param wip matrix for working profile
     * @param multiThread whether to parallelize the loop or not
     */
    static void LabGamutMunsell(float *labL, float *laba, float *labb,
                                const int N, bool corMunsell, bool lumaMuns,
                                bool isHLEnabled, bool gamut,
                                const double wip[3][3]);

    /**
     * @brief Munsell Lch correction
     * Find the right LUT and calculate the correction
     * @param lum luma value [0 ; 100]
     * @param hue hue value [-PI ; +PI]
     * @param chrom chroma value [0 ; 180]
     * @param memChprov store chroma [0 ; 180]
     * @param correction correction value, in radians [0 ; 0.45]
     * @param lbe hue in function of chroma, in radian [-PI ; +PI]
     * @param zone  [1 ; 4]  1=PB correction + sky  2=red yellow correction
     * 3=Green yellow correction  4=Red purple correction
     * @param correctL true=enable the Luminance correction
     */
    static void MunsellLch(float lum, float hue, float chrom, float memChprov,
                           float &correction, int zone, float &lbe,
                           bool &correctL);

private:
    constexpr static float kappaf = Color::kappa;

    // Jacques' 195 LUTf for Munsell Lch correction
    static LUTf _4P10, _4P20, _4P30, _4P40, _4P50, _4P60;
    static LUTf _1P10, _1P20, _1P30, _1P40, _1P50, _1P60;
    static LUTf _5B40, _5B50, _5B60, _5B70, _5B80;
    static LUTf _7B40, _7B50, _7B60, _7B70, _7B80;
    static LUTf _9B40, _9B50, _9B60, _9B70, _9B80;
    static LUTf _10B40, _10B50, _10B60, _10B70, _10B80;
    static LUTf _05PB40, _05PB50, _05PB60, _05PB70, _05PB80;
    static LUTf _10PB10, _10PB20, _10PB30, _10PB40, _10PB50, _10PB60;
    static LUTf _9PB10, _9PB20, _9PB30, _9PB40, _9PB50, _9PB60, _9PB70, _9PB80;
    static LUTf _75PB10, _75PB20, _75PB30, _75PB40, _75PB50, _75PB60, _75PB70,
        _75PB80;
    static LUTf _6PB10, _6PB20, _6PB30, _6PB40, _6PB50, _6PB60, _6PB70, _6PB80;
    static LUTf _45PB10, _45PB20, _45PB30, _45PB40, _45PB50, _45PB60, _45PB70,
        _45PB80;
    static LUTf _3PB10, _3PB20, _3PB30, _3PB40, _3PB50, _3PB60, _3PB70, _3PB80;
    static LUTf _15PB10, _15PB20, _15PB30, _15PB40, _15PB50, _15PB60, _15PB70,
        _15PB80;
    static LUTf _10YR20, _10YR30, _10YR40, _10YR50, _10YR60, _10YR70, _10YR80,
        _10YR90;
    static LUTf _85YR20, _85YR30, _85YR40, _85YR50, _85YR60, _85YR70, _85YR80,
        _85YR90;
    static LUTf _7YR30, _7YR40, _7YR50, _7YR60, _7YR70, _7YR80;
    static LUTf _55YR30, _55YR40, _55YR50, _55YR60, _55YR70, _55YR80, _55YR90;
    static LUTf _4YR30, _4YR40, _4YR50, _4YR60, _4YR70, _4YR80;
    static LUTf _25YR30, _25YR40, _25YR50, _25YR60, _25YR70;
    static LUTf _10R30, _10R40, _10R50, _10R60, _10R70;
    static LUTf _9R30, _9R40, _9R50, _9R60, _9R70;
    static LUTf _7R30, _7R40, _7R50, _7R60, _7R70;
    static LUTf _5R10, _5R20, _5R30;
    static LUTf _25R10, _25R20, _25R30;
    static LUTf _10RP10, _10RP20, _10RP30;
    static LUTf _7G30, _7G40, _7G50, _7G60, _7G70, _7G80;
    static LUTf _5G30, _5G40, _5G50, _5G60, _5G70, _5G80;
    static LUTf _25G30, _25G40, _25G50, _25G60, _25G70, _25G80;
    static LUTf _1G30, _1G40, _1G50, _1G60, _1G70, _1G80;
    static LUTf _10GY30, _10GY40, _10GY50, _10GY60, _10GY70, _10GY80;
    static LUTf _75GY30, _75GY40, _75GY50, _75GY60, _75GY70, _75GY80;
    static LUTf _5GY30, _5GY40, _5GY50, _5GY60, _5GY70, _5GY80;

    // Separated from init() to keep the code clear
};

}} // namespace art::engine
