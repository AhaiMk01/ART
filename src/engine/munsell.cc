/*
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

#include "munsell.h"

#include "color.h"
#include "mytime.h"
#include "rt_math.h"
#include "settings.h"

namespace art { namespace engine {

extern const Settings *settings;

/*
 * Munsell Lch correction
 * Copyright (c) 2011  Jacques Desmis <jdesmis@gmail.com>
 */
// Munsell Lch LUTf : 195 LUT
// about 70% data are corrected with significative corrections
// almost all data are taken for BG, YR, G excepted a few extreme values with a
// slight correction No LUTf for BG and Y : low corrections Only between 5B and
// 5PB for L > 40 : under very low corrections for L < 40

LUTf Munsell::_4P10, Munsell::_4P20, Munsell::_4P30, Munsell::_4P40, Munsell::_4P50,
    Munsell::_4P60;
LUTf Munsell::_1P10, Munsell::_1P20, Munsell::_1P30, Munsell::_1P40, Munsell::_1P50,
    Munsell::_1P60;
LUTf Munsell::_10PB10, Munsell::_10PB20, Munsell::_10PB30, Munsell::_10PB40,
    Munsell::_10PB50, Munsell::_10PB60;
LUTf Munsell::_9PB10, Munsell::_9PB20, Munsell::_9PB30, Munsell::_9PB40, Munsell::_9PB50,
    Munsell::_9PB60, Munsell::_9PB70, Munsell::_9PB80;
LUTf Munsell::_75PB10, Munsell::_75PB20, Munsell::_75PB30, Munsell::_75PB40,
    Munsell::_75PB50, Munsell::_75PB60, Munsell::_75PB70, Munsell::_75PB80;
LUTf Munsell::_6PB10, Munsell::_6PB20, Munsell::_6PB30, Munsell::_6PB40, Munsell::_6PB50,
    Munsell::_6PB60, Munsell::_6PB70, Munsell::_6PB80;
LUTf Munsell::_45PB10, Munsell::_45PB20, Munsell::_45PB30, Munsell::_45PB40,
    Munsell::_45PB50, Munsell::_45PB60, Munsell::_45PB70, Munsell::_45PB80;
LUTf Munsell::_3PB10, Munsell::_3PB20, Munsell::_3PB30, Munsell::_3PB40, Munsell::_3PB50,
    Munsell::_3PB60, Munsell::_3PB70, Munsell::_3PB80;
LUTf Munsell::_15PB10, Munsell::_15PB20, Munsell::_15PB30, Munsell::_15PB40,
    Munsell::_15PB50, Munsell::_15PB60, Munsell::_15PB70, Munsell::_15PB80;
LUTf Munsell::_05PB40, Munsell::_05PB50, Munsell::_05PB60, Munsell::_05PB70,
    Munsell::_05PB80;
LUTf Munsell::_10B40, Munsell::_10B50, Munsell::_10B60, Munsell::_10B70, Munsell::_10B80;
LUTf Munsell::_9B40, Munsell::_9B50, Munsell::_9B60, Munsell::_9B70, Munsell::_9B80;
LUTf Munsell::_7B40, Munsell::_7B50, Munsell::_7B60, Munsell::_7B70, Munsell::_7B80;
LUTf Munsell::_5B40, Munsell::_5B50, Munsell::_5B60, Munsell::_5B70, Munsell::_5B80;
LUTf Munsell::_10YR20, Munsell::_10YR30, Munsell::_10YR40, Munsell::_10YR50,
    Munsell::_10YR60, Munsell::_10YR70, Munsell::_10YR80, Munsell::_10YR90;
LUTf Munsell::_85YR20, Munsell::_85YR30, Munsell::_85YR40, Munsell::_85YR50,
    Munsell::_85YR60, Munsell::_85YR70, Munsell::_85YR80, Munsell::_85YR90;
LUTf Munsell::_7YR30, Munsell::_7YR40, Munsell::_7YR50, Munsell::_7YR60, Munsell::_7YR70,
    Munsell::_7YR80;
LUTf Munsell::_55YR30, Munsell::_55YR40, Munsell::_55YR50, Munsell::_55YR60,
    Munsell::_55YR70, Munsell::_55YR80, Munsell::_55YR90;
LUTf Munsell::_4YR30, Munsell::_4YR40, Munsell::_4YR50, Munsell::_4YR60, Munsell::_4YR70,
    Munsell::_4YR80;
LUTf Munsell::_25YR30, Munsell::_25YR40, Munsell::_25YR50, Munsell::_25YR60,
    Munsell::_25YR70;
LUTf Munsell::_10R30, Munsell::_10R40, Munsell::_10R50, Munsell::_10R60, Munsell::_10R70;
LUTf Munsell::_9R30, Munsell::_9R40, Munsell::_9R50, Munsell::_9R60, Munsell::_9R70;
LUTf Munsell::_7R30, Munsell::_7R40, Munsell::_7R50, Munsell::_7R60, Munsell::_7R70;
LUTf Munsell::_5R10, Munsell::_5R20, Munsell::_5R30;
LUTf Munsell::_25R10, Munsell::_25R20, Munsell::_25R30;
LUTf Munsell::_10RP10, Munsell::_10RP20, Munsell::_10RP30;
LUTf Munsell::_7G30, Munsell::_7G40, Munsell::_7G50, Munsell::_7G60, Munsell::_7G70,
    Munsell::_7G80;
LUTf Munsell::_5G30, Munsell::_5G40, Munsell::_5G50, Munsell::_5G60, Munsell::_5G70,
    Munsell::_5G80;
LUTf Munsell::_25G30, Munsell::_25G40, Munsell::_25G50, Munsell::_25G60, Munsell::_25G70,
    Munsell::_25G80;
LUTf Munsell::_1G30, Munsell::_1G40, Munsell::_1G50, Munsell::_1G60, Munsell::_1G70,
    Munsell::_1G80;
LUTf Munsell::_10GY30, Munsell::_10GY40, Munsell::_10GY50, Munsell::_10GY60,
    Munsell::_10GY70, Munsell::_10GY80;
LUTf Munsell::_75GY30, Munsell::_75GY40, Munsell::_75GY50, Munsell::_75GY60,
    Munsell::_75GY70, Munsell::_75GY80;
LUTf Munsell::_5GY30, Munsell::_5GY40, Munsell::_5GY50, Munsell::_5GY60, Munsell::_5GY70,
    Munsell::_5GY80;

#ifdef _DEBUG
MunsellDebugInfo::MunsellDebugInfo() { reinitValues(); }
void MunsellDebugInfo::reinitValues()
{
    maxdhue[0] = maxdhue[1] = maxdhue[2] = maxdhue[3] = 0.0f;
    maxdhuelum[0] = maxdhuelum[1] = maxdhuelum[2] = maxdhuelum[3] = 0.0f;
    depass = depassLum = 0;
}
#endif

/*
 * AllMunsellLch correction
 * Copyright (c) 2012  Jacques Desmis <jdesmis@gmail.com>
 *
 * This function corrects the color (hue) for changes in chromaticity and
 * luminance to use in a "for" or "do while" statement
 *
 * Parameters:
 *    bool lumaMuns : true => luminance correction (for delta L > 10) and chroma
 * correction ; false : only chroma float Lprov1 , Loldd : luminance after and
 * before float HH: hue before float Chprov1, CC : chroma after and before float
 * coorectionHuechroma : correction Hue for chromaticity (saturation) float
 * correctlum : correction Hue for luminance (brigtness, contrast,...)
 *    MunsellDebugInfo* munsDbgInfo: (Debug target only) object to collect
 * information.
 */
#ifdef _DEBUG
void Munsell::AllMunsellLch(bool lumaMuns, float Lprov1, float Loldd, float HH,
                          float Chprov1, float CC, float &correctionHuechroma,
                          float &correctlum, MunsellDebugInfo *munsDbgInfo)
#else
void Munsell::AllMunsellLch(bool lumaMuns, float Lprov1, float Loldd, float HH,
                          float Chprov1, float CC, float &correctionHuechroma,
                          float &correctlum)
#endif
{

    bool contin1, contin2;
    float correctionHue = 0.0, correctionHueLum = 0.0;
    bool correctL;

    if (CC >= 6.0 && CC < 140) { // if C > 140 we say C=140 (only in Prophoto
                                 // ...with very large saturation)
        static const float huelimit[8] = {
            -2.48, -0.55, 0.44, 1.52, 1.87,
            3.09,  -0.27, 0.44}; // limits hue of blue-purple, red-yellow,
                                 // green-yellow, red-purple

        if (Chprov1 > 140.f) {
            Chprov1 = 139.f; // limits of LUTf
        }

        if (Chprov1 < 6.f) {
            Chprov1 = 6.f;
        }

        for (int zo = 1; zo <= 4; zo++) {
            if (HH > huelimit[2 * zo - 2] && HH < huelimit[2 * zo - 1]) {
                // zone=zo;
                contin1 = contin2 = false;
                correctL = false;
                MunsellLch(Lprov1, HH, Chprov1, CC, correctionHue, zo,
                           correctionHueLum,
                           correctL); // munsell chroma correction
#ifdef _DEBUG
                float absCorrectionHue = fabs(correctionHue);

                if (correctionHue != 0.0) {
                    int idx = zo - 1;
#ifdef _OPENMP
#pragma omp critical(maxdhue)
#endif
                    {
                        munsDbgInfo->maxdhue[idx] =
                            MAX(munsDbgInfo->maxdhue[idx], absCorrectionHue);
                    }
                }

                if (absCorrectionHue > 0.45)
#ifdef _OPENMP
#pragma omp atomic
#endif
                    munsDbgInfo->depass++; // verify if no bug in calculation

#endif
                correctionHuechroma = correctionHue; // preserve

                if (lumaMuns) {
                    float correctlumprov = 0.f;
                    float correctlumprov2 = 0.f;

                    if (correctL) {
                        // for Munsell luminance correction
                        correctlumprov = correctionHueLum;
                        contin1 = true;
                        correctL = false;
                    }

                    correctionHueLum = 0.0;
                    correctionHue = 0.0;

                    if (fabs(Lprov1 - Loldd) > 6.0) {
                        // correction if delta L significative..Munsell
                        // luminance
                        MunsellLch(Loldd, HH, Chprov1, Chprov1, correctionHue,
                                   zo, correctionHueLum, correctL);

                        if (correctL) {
                            correctlumprov2 = correctionHueLum;
                            contin2 = true;
                            correctL = false;
                        }

                        correctionHueLum = 0.0;

                        if (contin1 && contin2) {
                            correctlum = correctlumprov2 - correctlumprov;
                        }

#ifdef _DEBUG
                        float absCorrectLum = fabs(correctlum);

                        if (correctlum != 0.0) {
                            int idx = zo - 1;
#ifdef _OPENMP
#pragma omp critical(maxdhuelum)
#endif
                            {
                                munsDbgInfo->maxdhuelum[idx] =
                                    MAX(munsDbgInfo->maxdhuelum[idx],
                                        absCorrectLum);
                            }
                        }

                        if (absCorrectLum > 0.35)
#ifdef _OPENMP
#pragma omp atomic
#endif
                            munsDbgInfo->depassLum++; // verify if no bug in
                                                      // calculation

#endif
                    }
                }
            }
        }
    }

#ifdef _DEBUG

    if (correctlum < -0.35f) {
        correctlum = -0.35f;
    } else if (correctlum > 0.35f) {
        correctlum = 0.35f;
    }

    if (correctionHuechroma < -0.45f) {
        correctionHuechroma = -0.45f;
    } else if (correctionHuechroma > 0.45f) {
        correctionHuechroma = 0.45f;
    }

#endif
}

/*
 * AllMunsellLch correction
 * Copyright (c) 2012  Jacques Desmis <jdesmis@gmail.com>
 *
 * This function corrects the color (hue) for changes in chromaticity and
 * luminance to use in a "for" or "do while" statement
 *
 * Parameters:
 *    float Lprov1: luminance
 *    float HH: hue before
 *    float Chprov1, CC : chroma after and before
 *    float coorectionHuechroma : correction Hue for chromaticity (saturation)
 */
void Munsell::AllMunsellLch(float Lprov1, float HH, float Chprov1, float CC,
                          float &correctionHuechroma)
{

    float correctionHue = 0.f, correctionHueLum = 0.f;
    bool correctL;

    if (CC >= 6.f && CC < 140.f) { // if C > 140 we say C=140 (only in Prophoto
                                   // ...with very large saturation)
        static const float huelimit[8] = {
            -2.48f, -0.55f, 0.44f, 1.52f, 1.87f,
            3.09f,  -0.27f, 0.44f}; // limits hue of blue-purple, red-yellow,
                                    // green-yellow, red-purple

        if (Chprov1 > 140.f) {
            Chprov1 = 139.f; // limits of LUTf
        }

        Chprov1 = art::engine::max(Chprov1, 6.f);

        for (int zo = 1; zo <= 4; zo++) {
            if (HH > huelimit[2 * zo - 2] && HH < huelimit[2 * zo - 1]) {
                // zone=zo;
                correctL = false;
                MunsellLch(Lprov1, HH, Chprov1, CC, correctionHue, zo,
                           correctionHueLum,
                           correctL); // munsell chroma correction
                correctionHuechroma = correctionHue; // preserve
                break;
            }
        }
    }
}

/*
 * GamutLchonly correction
 * Copyright (c)2012  Jacques Desmis <jdesmis@gmail.com> and Jean-Christophe
 * Frisch <natureh@free.fr>
 *
 * This function puts the data (Lab) in the gamut of "working profile":
 * it returns the corrected values of the chromaticity and luminance
 *
 * float HH : hue
 * float Lprov1 : input luminance value, sent back corrected
 * float Chprov1: input chroma value, sent back corrected
 * float R,G,B : red, green and blue value of the corrected color
 * double wip : working profile
 * bool isHLEnabled : if "highlight reconstruction " is enabled
 * float coef : a float number between [0.95 ; 1.0[... the nearest it is
 * from 1.0, the more precise it will be... and the longer too as more iteration
 * will be necessary) bool neg and moreRGB : only in DEBUG mode to calculate
 * iterations for negatives values and > 65535
 */
#ifdef _DEBUG
void Munsell::gamutLchonly(float HH, float &Lprov1, float &Chprov1, float &R,
                         float &G, float &B, const double wip[3][3],
                         const bool isHLEnabled, const float lowerCoef,
                         const float higherCoef, bool &neg, bool &more_rgb)
#else
void Munsell::gamutLchonly(float HH, float &Lprov1, float &Chprov1, float &R,
                         float &G, float &B, const double wip[3][3],
                         const bool isHLEnabled, const float lowerCoef,
                         const float higherCoef)
#endif
{
    const float ClipLevel = 65535.0f;
    bool inGamut;
#ifdef _DEBUG
    neg = false, more_rgb = false;
#endif
    float2 sincosval = xsincosf(HH);

    do {
        inGamut = true;

        // Lprov1=LL;
        float aprov1 = Chprov1 * sincosval.y;
        float bprov1 = Chprov1 * sincosval.x;

        // conversion Lab RGB to limit Lab values - this conversion is useful
        // before Munsell correction
        float fy = (Color::c1By116 * Lprov1) + Color::c16By116;
        float fx = (0.002f * aprov1) + fy;
        float fz = fy - (0.005f * bprov1);

        float x_ = 65535.0f * Color::f2xyz(fx) * Color::D50x;
        // float y_ = 65535.0f * f2xyz(fy);
        float z_ = 65535.0f * Color::f2xyz(fz) * Color::D50z;
        float y_ = (Lprov1 > Color::epskap) ? 65535.0 * fy * fy * fy
                                     : 65535.0 * Lprov1 / Color::kappa;

        Color::xyz2rgb(x_, y_, z_, R, G, B, wip);

        // gamut control before saturation to put Lab values in future gamut,
        // but not RGB
        if (R < 0.0f || G < 0.0f || B < 0.0f) {
#ifdef _DEBUG
            neg = true;
#endif

            if (Lprov1 < 0.1f) {
                Lprov1 = 0.1f;
            }

            // gamut for L with ultra blue : we can improve the algorithm ...
            // thinner, and other color ???
            if (HH < -0.9f && HH > -1.55f) { // ultra blue
                if (Chprov1 > 160.f)
                    if (Lprov1 < 5.f) {
                        Lprov1 = 5.f; // very very very very high chroma
                    }

                if (Chprov1 > 140.f)
                    if (Lprov1 < 3.5f) {
                        Lprov1 = 3.5f;
                    }

                if (Chprov1 > 120.f)
                    if (Lprov1 < 2.f) {
                        Lprov1 = 2.f;
                    }

                if (Chprov1 > 105.f)
                    if (Lprov1 < 1.f) {
                        Lprov1 = 1.f;
                    }

                if (Chprov1 > 90.f)
                    if (Lprov1 < 0.7f) {
                        Lprov1 = 0.7f;
                    }

                if (Chprov1 > 50.f)
                    if (Lprov1 < 0.5f) {
                        Lprov1 = 0.5f;
                    }

                if (Chprov1 > 20.f)
                    if (Lprov1 < 0.4f) {
                        Lprov1 = 0.4f;
                    }
            }

            Chprov1 *= higherCoef; // decrease the chromaticity value

            if (Chprov1 <= 3.0f) {
                Lprov1 += lowerCoef;
            }

            inGamut = false;
        } else if (!isHLEnabled && art::engine::max(R, G, B) > ClipLevel &&
                   art::engine::min(R, G, B) <= ClipLevel) {

            // if "highlight reconstruction" is enabled or the point is
            // completely white (clipped, no color), don't control Gamut
#ifdef _DEBUG
            more_rgb = true;
#endif

            if (Lprov1 > 99.999f) {
                Lprov1 = 99.98f;
            }

            Chprov1 *= higherCoef;

            if (Chprov1 <= 3.0f) {
                Lprov1 -= lowerCoef;
            }

            inGamut = false;
        }
    } while (!inGamut);

    // end first gamut control
}

/*
 * GamutLchonly correction
 * Copyright (c)2012  Jacques Desmis <jdesmis@gmail.com> and Jean-Christophe
 * Frisch <natureh@free.fr>
 *
 * This function puts the data (Lab) in the gamut of "working profile":
 * it returns the corrected values of the chromaticity and luminance
 *
 * float HH : hue
 * float2 sincosval : sin and cos of HH
 * float Lprov1 : input luminance value, sent back corrected
 * float Chprov1: input chroma value, sent back corrected
 * float R,G,B : red, green and blue value of the corrected color
 * double wip : working profile
 * bool isHLEnabled : if "highlight reconstruction " is enabled
 * float coef : a float number between [0.95 ; 1.0[... the nearest it is
 * from 1.0, the more precise it will be... and the longer too as more iteration
 * will be necessary) bool neg and moreRGB : only in DEBUG mode to calculate
 * iterations for negatives values and > 65535
 */
#ifdef _DEBUG
void Munsell::gamutLchonly(float HH, float2 sincosval, float &Lprov1,
                         float &Chprov1, float &R, float &G, float &B,
                         const double wip[3][3], const bool isHLEnabled,
                         const float lowerCoef, const float higherCoef,
                         bool &neg, bool &more_rgb)
#else
void Munsell::gamutLchonly(float HH, float2 sincosval, float &Lprov1,
                         float &Chprov1, float &R, float &G, float &B,
                         const double wip[3][3], const bool isHLEnabled,
                         const float lowerCoef, const float higherCoef)
#endif
{
    constexpr float ClipLevel = 65535.0f;
    bool inGamut;
#ifdef _DEBUG
    neg = false, more_rgb = false;
#endif
    float ChprovSave = Chprov1;

    do {
        inGamut = true;

        float aprov1 = Chprov1 * sincosval.y;
        float bprov1 = Chprov1 * sincosval.x;

        // conversion Lab RGB to limit Lab values - this conversion is useful
        // before Munsell correction
        float fy = (Color::c1By116 * Lprov1) + Color::c16By116;
        float fx = (0.002f * aprov1) + fy;
        float fz = fy - (0.005f * bprov1);

        float x_ = 65535.0f * Color::f2xyz(fx) * Color::D50x;
        float z_ = 65535.0f * Color::f2xyz(fz) * Color::D50z;
        float y_ = (Lprov1 > Color::epskap) ? 65535.0f * fy * fy * fy
                                     : 65535.0f * Lprov1 / Color::kappa;

        Color::xyz2rgb(x_, y_, z_, R, G, B, wip);

        // gamut control before saturation to put Lab values in future gamut,
        // but not RGB
        if (R < 0.0f || G < 0.0f || B < 0.0f) {
#ifdef _DEBUG
            neg = true;
#endif

            if (std::isnan(HH)) {
                float atemp = ChprovSave * sincosval.y * 327.68;
                float btemp = ChprovSave * sincosval.x * 327.68;
                HH = xatan2f(btemp, atemp);
            }

            if (Lprov1 < 0.1f) {
                Lprov1 = 0.1f;
            }

            // gamut for L with ultra blue : we can improve the algorithm ...
            // thinner, and other color ???
            if (HH < -0.9f && HH > -1.55f) { // ultra blue
                if (Chprov1 > 160.f)
                    if (Lprov1 < 5.f) {
                        Lprov1 = 5.f; // very very very very high chroma
                    }

                if (Chprov1 > 140.f)
                    if (Lprov1 < 3.5f) {
                        Lprov1 = 3.5f;
                    }

                if (Chprov1 > 120.f)
                    if (Lprov1 < 2.f) {
                        Lprov1 = 2.f;
                    }

                if (Chprov1 > 105.f)
                    if (Lprov1 < 1.f) {
                        Lprov1 = 1.f;
                    }

                if (Chprov1 > 90.f)
                    if (Lprov1 < 0.7f) {
                        Lprov1 = 0.7f;
                    }

                if (Chprov1 > 50.f)
                    if (Lprov1 < 0.5f) {
                        Lprov1 = 0.5f;
                    }

                if (Chprov1 > 20.f)
                    if (Lprov1 < 0.4f) {
                        Lprov1 = 0.4f;
                    }
            }

            Chprov1 *= higherCoef; // decrease the chromaticity value

            if (Chprov1 <= 3.0f) {
                Lprov1 += lowerCoef;
            }

            inGamut = false;
        } else if (!isHLEnabled && art::engine::max(R, G, B) > ClipLevel &&
                   art::engine::min(R, G, B) <= ClipLevel) {

            // if "highlight reconstruction" is enabled or the point is
            // completely white (clipped, no color), don't control Gamut
#ifdef _DEBUG
            more_rgb = true;
#endif

            if (Lprov1 > 99.999f) {
                Lprov1 = 99.98f;
            }

            Chprov1 *= higherCoef;

            if (Chprov1 <= 3.0f) {
                Lprov1 -= lowerCoef;
            }

            inGamut = false;
        }
    } while (!inGamut);

    // end first gamut control
}

/*
 * GamutLchonly correction
 * Copyright (c)2012  Jacques Desmis <jdesmis@gmail.com> and Jean-Christophe
 * Frisch <natureh@free.fr>
 *
 * This function puts the data (Lab) in the gamut of "working profile":
 * it returns the corrected values of the chromaticity and luminance
 *
 * float HH : hue
 * float2 sincosval : sin and cos of HH
 * float Lprov1 : input luminance value, sent back corrected
 * float Chprov1: input chroma value, sent back corrected
 * float wip : working profile
 * bool isHLEnabled : if "highlight reconstruction " is enabled
 * float coef : a float number between [0.95 ; 1.0[... the nearest it is
 * from 1.0, the more precise it will be... and the longer too as more iteration
 * will be necessary)
 */
void Munsell::gamutLchonly(float HH, float2 sincosval, float &Lprov1,
                         float &Chprov1, float &saturation,
                         const float wip[3][3], const bool isHLEnabled,
                         const float lowerCoef, const float higherCoef)
{
    constexpr float ClipLevel = 1.f;
    bool inGamut;
    float R, G, B;

    do {
        inGamut = true;

        float aprov1 = Chprov1 * sincosval.y;
        float bprov1 = Chprov1 * sincosval.x;

        // conversion Lab RGB to limit Lab values - this conversion is useful
        // before Munsell correction
        float fy = Color::c1By116 * Lprov1 + Color::c16By116;
        float fx = 0.002f * aprov1 + fy;
        float fz = fy - 0.005f * bprov1;

        float x_ = Color::f2xyz(fx) * Color::D50x;
        float z_ = Color::f2xyz(fz) * Color::D50z;
        float y_ = (Lprov1 > Color::epskap) ? fy * fy * fy : Lprov1 / kappaf;

        Color::xyz2rgb(x_, y_, z_, R, G, B, wip);

        // gamut control before saturation to put Lab values in future gamut,
        // but not RGB
        if (art::engine::min(R, G, B) < 0.f) {

            Lprov1 = art::engine::max(Lprov1, 0.1f);

            // gamut for L with ultra blue : we can improve the algorithm ...
            // thinner, and other color ???
            if (HH < -0.9f && HH > -1.55f) { // ultra blue
                if (Chprov1 > 160.f)
                    if (Lprov1 < 5.f) {
                        Lprov1 = 5.f; // very very very very high chroma
                    }

                if (Chprov1 > 140.f)
                    if (Lprov1 < 3.5f) {
                        Lprov1 = 3.5f;
                    }

                if (Chprov1 > 120.f)
                    if (Lprov1 < 2.f) {
                        Lprov1 = 2.f;
                    }

                if (Chprov1 > 105.f)
                    if (Lprov1 < 1.f) {
                        Lprov1 = 1.f;
                    }

                if (Chprov1 > 90.f)
                    if (Lprov1 < 0.7f) {
                        Lprov1 = 0.7f;
                    }

                if (Chprov1 > 50.f)
                    if (Lprov1 < 0.5f) {
                        Lprov1 = 0.5f;
                    }

                if (Chprov1 > 20.f)
                    if (Lprov1 < 0.4f) {
                        Lprov1 = 0.4f;
                    }
            }

            Chprov1 *= higherCoef; // decrease the chromaticity value

            if (Chprov1 <= 3.f) {
                Lprov1 += lowerCoef;
            }

            inGamut = false;
        } else if (!isHLEnabled && art::engine::max(R, G, B) > ClipLevel &&
                   art::engine::min(R, G, B) <= ClipLevel) {

            // if "highlight reconstruction" is enabled or the point is
            // completely white (clipped, no color), don't control Gamut

            if (Lprov1 > 99.999f) {
                Lprov1 = 99.98f;
            }

            Chprov1 *= higherCoef;

            if (Chprov1 <= 3.f) {
                Lprov1 -= lowerCoef;
            }

            inGamut = false;
        }
    } while (!inGamut);

    saturation = 1.f - (art::engine::min(R, G, B) / art::engine::max(R, G, B));
    // end first gamut control
}

#ifdef _DEBUG
void Munsell::gamutLchonly(float2 sincosval, float &Lprov1, float &Chprov1,
                         const float wip[3][3], const bool isHLEnabled,
                         const float lowerCoef, const float higherCoef,
                         bool &neg, bool &more_rgb)
#else
void Munsell::gamutLchonly(float2 sincosval, float &Lprov1, float &Chprov1,
                         const float wip[3][3], const bool isHLEnabled,
                         const float lowerCoef, const float higherCoef)
#endif
{
    const float ClipLevel = 65535.0f;
    bool inGamut;
#ifdef _DEBUG
    neg = false, more_rgb = false;
#endif

    do {
        inGamut = true;

        // Lprov1=LL;
        float aprov1 = Chprov1 * sincosval.y;
        float bprov1 = Chprov1 * sincosval.x;

        // conversion Lab RGB to limit Lab values - this conversion is useful
        // before Munsell correction
        float fy = (Color::c1By116 * Lprov1) + Color::c16By116;
        float fx = (0.002f * aprov1) + fy;
        float fz = fy - (0.005f * bprov1);

        float x_ = 65535.0f * Color::f2xyz(fx) * Color::D50x;
        // float y_ = 65535.0f * f2xyz(fy);
        float z_ = 65535.0f * Color::f2xyz(fz) * Color::D50z;
        float y_ = (Lprov1 > Color::epskap) ? 65535.0 * fy * fy * fy
                                     : 65535.0 * Lprov1 / Color::kappa;

        float R, G, B;
        Color::xyz2rgb(x_, y_, z_, R, G, B, wip);

        // gamut control before saturation to put Lab values in future gamut,
        // but not RGB
        if (R < 0.0f || G < 0.0f || B < 0.0f) {
#ifdef _DEBUG
            neg = true;
#endif

            if (Lprov1 < 0.01f) {
                Lprov1 = 0.01f;
            }

            Chprov1 *= higherCoef; // decrease the chromaticity value

            if (Chprov1 <= 3.0f) {
                Lprov1 += lowerCoef;
            }

            inGamut = false;
        } else if (!isHLEnabled && art::engine::max(R, G, B) > ClipLevel &&
                   art::engine::min(R, G, B) <= ClipLevel) {

            // if "highlight reconstruction" is enabled or the point is
            // completely white (clipped, no color), don't control Gamut
#ifdef _DEBUG
            more_rgb = true;
#endif

            if (Lprov1 > 99.999f) {
                Lprov1 = 99.98f;
            }

            Chprov1 *= higherCoef;

            if (Chprov1 <= 3.0f) {
                Lprov1 -= lowerCoef;
            }

            inGamut = false;
        }
    } while (!inGamut);

    // end first gamut control
}

/*
 * LabGamutMunsell
 * Copyright (c) 2012  Jacques Desmis <jdesmis@gmail.com>
 *
 * This function is the overall Munsell's corrections, but only on global
 * statement: I think it's better to use local statement with AllMunsellLch not
 * for use in a "for" or "do while" loop they are named accordingly :
 * gamutLchonly and AllMunsellLch it can be used before and after treatment
 * (saturation, gamma, luminance, ...)
 *
 * Parameters:
 *    float *labL     :       RT Lab L channel data
 *    float *laba     :       RT Lab a channel data
 *    float *labb     :       RT Lab b channel data
 *    bool corMunsell :       performs Munsell correction
 *    bool lumaMuns   :       (used only if corMuns=true)
 *                            true:  apply luma + chroma Munsell correction if
 * delta L > 10; false: only chroma correction only bool gamut            :
 * performs gamutLch const double wip[3][3]: matrix for working profile bool
 * multiThread      : parallelize the loop
 */
void Munsell::LabGamutMunsell(float *labL, float *laba, float *labb, const int N,
                            bool corMunsell, bool lumaMuns, bool isHLEnabled,
                            bool gamut, const double wip[3][3])
{
#ifdef _DEBUG
    MyTime t1e, t2e;
    t1e.set();
    int negat = 0, moreRGB = 0;
    MunsellDebugInfo *MunsDebugInfo = nullptr;

    if (corMunsell) {
        MunsDebugInfo = new MunsellDebugInfo();
    }

#endif
    float correctlum = 0.f;
    float correctionHuechroma = 0.f;
#ifdef ART_SIMD
    // precalculate H and C using SSE
    float HHBuffer[N];
    float CCBuffer[N];
    __m128 c327d68v = _mm_set1_ps(327.68f);
    __m128 av, bv;
    int k;

    for (k = 0; k < N - 3; k += 4) {
        av = LVFU(laba[k]);
        bv = LVFU(labb[k]);
        _mm_storeu_ps(&HHBuffer[k], xatan2f(bv, av));
        _mm_storeu_ps(&CCBuffer[k], vsqrtf(SQRV(av) + SQRV(bv)) / c327d68v);
    }

    for (; k < N; k++) {
        HHBuffer[k] = xatan2f(labb[k], laba[k]);
        CCBuffer[k] = sqrt(SQR(laba[k]) + SQR(labb[k])) / 327.68f;
    }

#endif // ART_SIMD

    for (int j = 0; j < N; j++) {
#ifdef ART_SIMD
        float HH = HHBuffer[j];
        float Chprov1 = CCBuffer[j];
#else
        float HH = xatan2f(labb[j], laba[j]);
        float Chprov1 = sqrtf(SQR(laba[j]) + SQR(labb[j])) / 327.68f;
#endif
        float Lprov1 = labL[j] / 327.68f;
        float Loldd = Lprov1;
        float Coldd = Chprov1;
        float2 sincosval;

        if (gamut) {
#ifdef _DEBUG
            bool neg, more_rgb;
#endif
            // According to mathematical laws we can get the sin and cos of HH
            // by simple operations
            float R, G, B;

            if (Chprov1 == 0.f) {
                sincosval.y = 1.f;
                sincosval.x = 0.f;
            } else {
                sincosval.y = laba[j] / (Chprov1 * 327.68f);
                sincosval.x = labb[j] / (Chprov1 * 327.68f);
            }

            // gamut control : Lab values are in gamut
#ifdef _DEBUG
            gamutLchonly(HH, sincosval, Lprov1, Chprov1, R, G, B, wip,
                         isHLEnabled, 0.15f, 0.96f, neg, more_rgb);
#else
            gamutLchonly(HH, sincosval, Lprov1, Chprov1, R, G, B, wip,
                         isHLEnabled, 0.15f, 0.96f);
#endif

#ifdef _DEBUG

            if (neg) {
                negat++;
            }

            if (more_rgb) {
                moreRGB++;
            }

#endif
        }

        labL[j] = Lprov1 * 327.68f;
        correctionHuechroma = 0.f;
        correctlum = 0.f;

        if (corMunsell)
#ifdef _DEBUG
            AllMunsellLch(lumaMuns, Lprov1, Loldd, HH, Chprov1, Coldd,
                          correctionHuechroma, correctlum, MunsDebugInfo);

#else
            AllMunsellLch(lumaMuns, Lprov1, Loldd, HH, Chprov1, Coldd,
                          correctionHuechroma, correctlum);
#endif

        if (correctlum == 0.f && correctionHuechroma == 0.f) {
            if (!gamut) {
                if (Coldd == 0.f) {
                    sincosval.y = 1.f;
                    sincosval.x = 0.f;
                } else {
                    sincosval.y = laba[j] / (Coldd * 327.68f);
                    sincosval.x = labb[j] / (Coldd * 327.68f);
                }
            }

        } else {
            HH += correctlum; // hue Munsell luminance correction
            sincosval = xsincosf(HH + correctionHuechroma);
        }

        laba[j] = Chprov1 * sincosval.y * 327.68f;
        labb[j] = Chprov1 * sincosval.x * 327.68f;
    }

#ifdef _DEBUG
    t2e.set();

    if (settings->verbose > 1) {
        printf("Munsell::LabGamutMunsell (correction performed in %d usec):\n",
               t2e.etime(t1e));
        printf("   Gamut              : G1negat=%iiter G165535=%iiter \n",
               negat, moreRGB);

        if (MunsDebugInfo) {
            printf("   Munsell chrominance: MaxBP=%1.2frad  MaxRY=%1.2frad  "
                   "MaxGY=%1.2frad  MaxRP=%1.2frad  depass=%u\n",
                   MunsDebugInfo->maxdhue[0], MunsDebugInfo->maxdhue[1],
                   MunsDebugInfo->maxdhue[2], MunsDebugInfo->maxdhue[3],
                   MunsDebugInfo->depass);
            printf("   Munsell luminance  : MaxBP=%1.2frad  MaxRY=%1.2frad  "
                   "MaxGY=%1.2frad  MaxRP=%1.2frad  depass=%u\n",
                   MunsDebugInfo->maxdhuelum[0], MunsDebugInfo->maxdhuelum[1],
                   MunsDebugInfo->maxdhuelum[2], MunsDebugInfo->maxdhuelum[3],
                   MunsDebugInfo->depassLum);
        } else {
            printf("   Munsell correction wasn't requested\n");
        }
    }

    if (MunsDebugInfo) {
        delete MunsDebugInfo;
    }

#endif
}

/*
 * MunsellLch correction
 * Copyright (c) 2012  Jacques Desmis <jdesmis@gmail.com>
 *
 * Find the right LUT and calculate the correction
 */
void Munsell::MunsellLch(float lum, float hue, float chrom, float memChprov,
                       float &correction, int zone, float &lbe, bool &correctL)
{

    int x = int(memChprov);
    int y = int(chrom);

    // begin PB correction + sky
    if (zone == 1) {
        if (lum > 5.0) {
            if (lum < 15.0) {
                if ((hue >= (_15PB10[x] - 0.035)) &&
                    (hue < (_15PB10[x] + 0.052) && x <= 45)) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _15PB10[y] - _15PB10[x];
                    lbe = _15PB10[y];
                    correctL = true;
                } else if ((hue >= (_3PB10[x] - 0.052)) &&
                           (hue < (_45PB10[x] + _3PB10[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _3PB10[y] - _3PB10[x];
                    lbe = _3PB10[y];
                    correctL = true;
                } else if ((hue >= (_45PB10[x] + _3PB10[x]) / 2.0) &&
                           (hue < (_45PB10[x] + 0.052)) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _45PB10[y] - _45PB10[x];
                    lbe = _45PB10[y];
                    correctL = true;
                } else if ((hue >= (_6PB10[x] - 0.052) &&
                            (hue < (_6PB10[x] + _75PB10[x]) / 2.0))) {
                    correction = _6PB10[y] - _6PB10[x];
                    lbe = _6PB10[y];
                    correctL = true;
                } else if ((hue >= (_6PB10[x] + _75PB10[x]) / 2.0) &&
                           (hue < (_9PB10[x] + _75PB10[x]) / 2.0)) {
                    correction = _75PB10[y] - _75PB10[x];
                    lbe = _75PB10[y];
                    correctL = true;
                } else if ((hue >= (_9PB10[x] + _75PB10[x]) / 2.0) &&
                           (hue < (_9PB10[x] + _10PB10[x]) / 2.0)) {
                    correction = _9PB10[y] - _9PB10[x];
                    lbe = _9PB10[y];
                    correctL = true;
                } else if ((hue >= (_10PB10[x] + _9PB10[x]) / 2.0) &&
                           (hue < (_1P10[x] + _10PB10[x]) / 2.0)) {
                    correction = _10PB10[y] - _10PB10[x];
                    lbe = _10PB10[y];
                    correctL = true;
                } else if ((hue >= (_10PB10[x] + _1P10[x]) / 2.0) &&
                           (hue < (_1P10[x] + _4P10[x]) / 2.0)) {
                    correction = _1P10[y] - _1P10[x];
                    lbe = _1P10[y];
                    correctL = true;
                } else if ((hue >= (_1P10[x] + _4P10[x]) / 2.0) &&
                           (hue < (0.035 + _4P10[x]) / 2.0)) {
                    correction = _4P10[y] - _4P10[x];
                    lbe = _4P10[y];
                    correctL = true;
                }
            } else if (lum < 25.0) {
                if ((hue >= (_15PB20[x] - 0.035)) &&
                    (hue < (_15PB20[x] + _3PB20[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _15PB20[y] - _15PB20[x];
                    lbe = _15PB20[y];
                    correctL = true;
                } else if ((hue >= (_15PB20[x] + _3PB20[x]) / 2.0) &&
                           (hue < (_45PB20[x] + _3PB20[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _3PB20[y] - _3PB20[x];
                    lbe = _3PB20[y];
                    correctL = true;
                } else if ((hue >= (_45PB20[x] + _3PB20[x]) / 2.0) &&
                           (hue < (_45PB20[x] + 0.052)) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _45PB20[y] - _45PB20[x];
                    lbe = _45PB20[y];
                    correctL = true;
                } else if ((hue >= (_45PB20[x] + 0.052)) &&
                           (hue < (_6PB20[x] + _75PB20[x]) / 2.0)) {
                    correction = _6PB20[y] - _6PB20[x];
                    lbe = _6PB20[y];
                    correctL = true;
                } else if ((hue >= (_6PB20[x] + _75PB20[x]) / 2.0) &&
                           (hue < (_9PB20[x] + _75PB20[x]) / 2.0)) {
                    correction = _75PB20[y] - _75PB20[x];
                    lbe = _75PB20[y];
                    correctL = true;
                } else if ((hue >= (_9PB20[x] + _75PB20[x]) / 2.0) &&
                           (hue < (_9PB20[x] + _10PB20[x]) / 2.0)) {
                    correction = _9PB20[y] - _9PB20[x];
                    lbe = _9PB20[y];
                    correctL = true;
                } else if ((hue >= (_10PB20[x] + _9PB20[x]) / 2.0) &&
                           (hue < (_1P20[x] + _10PB20[x]) / 2.0)) {
                    correction = _10PB20[y] - _10PB20[x];
                    lbe = _10PB20[y];
                    correctL = true;
                } else if ((hue >= (_10PB20[x] + _1P20[x]) / 2.0) &&
                           (hue < (_1P20[x] + _4P20[x]) / 2.0)) {
                    correction = _1P20[y] - _1P20[x];
                    lbe = _1P20[y];
                    correctL = true;
                } else if ((hue >= (_1P20[x] + _4P20[x]) / 2.0) &&
                           (hue < (0.035 + _4P20[x]) / 2.0)) {
                    correction = _4P20[y] - _4P20[x];
                    lbe = _4P20[y];
                    correctL = true;
                }
            } else if (lum < 35.0) {
                if ((hue >= (_15PB30[x] - 0.035)) &&
                    (hue < (_15PB30[x] + _3PB30[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _15PB30[y] - _15PB30[x];
                    lbe = _15PB30[y];
                    correctL = true;
                } else if ((hue >= (_15PB30[x] + _3PB30[x]) / 2.0) &&
                           (hue < (_45PB30[x] + _3PB30[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _3PB30[y] - _3PB30[x];
                    lbe = _3PB30[y];
                    correctL = true;
                } else if ((hue >= (_45PB30[x] + _3PB30[x]) / 2.0) &&
                           (hue < (_45PB30[x] + 0.052)) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _45PB30[y] - _45PB30[x];
                    lbe = _45PB30[y];
                    correctL = true;
                } else if ((hue >= (_45PB30[x] + 0.052)) &&
                           (hue < (_6PB30[x] + _75PB30[x]) / 2.0)) {
                    correction = _6PB30[y] - _6PB30[x];
                    lbe = _6PB30[y];
                    correctL = true;
                } else if ((hue >= (_6PB30[x] + _75PB30[x]) / 2.0) &&
                           (hue < (_9PB30[x] + _75PB30[x]) / 2.0)) {
                    correction = _75PB30[y] - _75PB30[x];
                    lbe = _75PB30[y];
                    correctL = true;
                } else if ((hue >= (_9PB30[x] + _75PB30[x]) / 2.0) &&
                           (hue < (_9PB30[x] + _10PB30[x]) / 2.0)) {
                    correction = _9PB30[y] - _9PB30[x];
                    lbe = _9PB30[y];
                    correctL = true;
                } else if ((hue >= (_10PB30[x] + _9PB30[x]) / 2.0) &&
                           (hue < (_1P30[x] + _10PB30[x]) / 2.0)) {
                    correction = _10PB30[y] - _10PB30[x];
                    lbe = _10PB30[y];
                    correctL = true;
                } else if ((hue >= (_10PB30[x] + _1P30[x]) / 2.0) &&
                           (hue < (_1P30[x] + _4P30[x]) / 2.0)) {
                    correction = _1P30[y] - _1P30[x];
                    lbe = _1P30[y];
                    correctL = true;
                } else if ((hue >= (_1P30[x] + _4P30[x]) / 2.0) &&
                           (hue < (0.035 + _4P30[x]) / 2.0)) {
                    correction = _4P30[y] - _4P30[x];
                    lbe = _4P30[y];
                    correctL = true;
                }
            } else if (lum < 45.0) {
                if ((hue <= (_05PB40[x] + _15PB40[x]) / 2.0) &&
                    (hue > (_05PB40[x] + _10B40[x]) / 2.0) && x < 75) {
                    if (y > 75) {
                        y = 75;
                    }

                    correction = _05PB40[y] - _05PB40[x];
                    lbe = _05PB40[y];
                    correctL = true;
                } else if ((hue <= (_05PB40[x] + _10B40[x]) / 2.0) &&
                           (hue > (_10B40[x] + _9B40[x]) / 2.0) && x < 70) {
                    if (y > 70) {
                        y = 70;
                    }

                    correction = _10B40[y] - _10B40[x];
                    lbe = _10B40[y];
                    correctL = true;
                } else if ((hue <= (_10B40[x] + _9B40[x]) / 2.0) &&
                           (hue > (_9B40[x] + _7B40[x]) / 2.0) && x < 70) {
                    if (y > 70) {
                        y = 70;
                    }

                    correction = _9B40[y] - _9B40[x];
                    lbe = _9B40[y];
                    correctL = true;
                } else if ((hue <= (_9B40[x] + _7B40[x]) / 2.0) &&
                           (hue > (_5B40[x] + _7B40[x]) / 2.0) && x < 70) {
                    if (y > 70) {
                        y = 70;
                    }

                    correction = _7B40[y] - _7B40[x];
                    lbe = _7B40[y];
                    correctL = true;
                } else if ((hue <= (_5B40[x] + _7B40[x]) / 2.0) &&
                           (hue > (_5B40[x] - 0.035)) && x < 70) {
                    if (y > 70) {
                        y = 70; //
                    }

                    correction = _5B40[y] - _5B40[x];
                    lbe = _5B40[y];
                    correctL = true;
                }

                else if ((hue >= (_15PB40[x] - 0.035)) &&
                         (hue < (_15PB40[x] + _3PB40[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _15PB40[y] - _15PB40[x];
                    lbe = _15PB40[y];
                    correctL = true;
                } else if ((hue >= (_15PB40[x] + _3PB40[x]) / 2.0) &&
                           (hue < (_45PB40[x] + _3PB40[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _3PB40[y] - _3PB40[x];
                    lbe = _3PB40[y];
                    correctL = true;
                } else if ((hue >= (_45PB40[x] + _3PB40[x]) / 2.0) &&
                           (hue < (_45PB40[x] + 0.052)) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _45PB40[y] - _45PB40[x];
                    lbe = _45PB40[y];
                    correctL = true;
                } else if ((hue >= (_45PB40[x] + 0.052)) &&
                           (hue < (_6PB40[x] + _75PB40[x]) / 2.0)) {
                    correction = _6PB40[y] - _6PB40[x];
                    lbe = _6PB40[y];
                    correctL = true;
                } else if ((hue >= (_6PB40[x] + _75PB40[x]) / 2.0) &&
                           (hue < (_9PB40[x] + _75PB40[x]) / 2.0)) {
                    correction = _75PB40[y] - _75PB40[x];
                    lbe = _75PB40[y];
                    correctL = true;
                } else if ((hue >= (_9PB40[x] + _75PB40[x]) / 2.0) &&
                           (hue < (_9PB40[x] + _10PB40[x]) / 2.0)) {
                    correction = _9PB40[y] - _9PB40[x];
                    lbe = _9PB40[y];
                    correctL = true;
                } else if ((hue >= (_10PB40[x] + _9PB40[x]) / 2.0) &&
                           (hue < (_1P40[x] + _10PB40[x]) / 2.0)) {
                    correction = _10PB40[y] - _10PB40[x];
                    lbe = _10PB40[y];
                    correctL = true;
                } else if ((hue >= (_10PB40[x] + _1P40[x]) / 2.0) &&
                           (hue < (_1P40[x] + _4P40[x]) / 2.0)) {
                    correction = _1P40[y] - _1P40[x];
                    lbe = _1P40[y];
                    correctL = true;
                } else if ((hue >= (_1P40[x] + _4P40[x]) / 2.0) &&
                           (hue < (0.035 + _4P40[x]) / 2.0)) {
                    correction = _4P40[y] - _4P40[x];
                    lbe = _4P40[y];
                    correctL = true;
                }
            } else if (lum < 55.0) {
                if ((hue <= (_05PB50[x] + _15PB50[x]) / 2.0) &&
                    (hue > (_05PB50[x] + _10B50[x]) / 2.0) && x < 79) {
                    if (y > 79) {
                        y = 79;
                    }

                    correction = _05PB50[y] - _05PB50[x];
                    lbe = _05PB50[y];
                    correctL = true;
                } else if ((hue <= (_05PB50[x] + _10B50[x]) / 2.0) &&
                           (hue > (_10B50[x] + _9B50[x]) / 2.0) && x < 79) {
                    if (y > 79) {
                        y = 79;
                    }

                    correction = _10B50[y] - _10B50[x];
                    lbe = _10B50[y];
                    correctL = true;
                } else if ((hue <= (_10B50[x] + _9B50[x]) / 2.0) &&
                           (hue > (_9B50[x] + _7B50[x]) / 2.0) && x < 79) {
                    if (y > 79) {
                        y = 79;
                    }

                    correction = _9B50[y] - _9B50[x];
                    lbe = _9B50[y];
                    correctL = true;
                } else if ((hue <= (_9B50[x] + _7B50[x]) / 2.0) &&
                           (hue > (_5B50[x] + _7B50[x]) / 2.0) && x < 79) {
                    if (y > 79) {
                        y = 79;
                    }

                    correction = _7B50[y] - _7B50[x];
                    lbe = _7B50[y];
                    correctL = true;
                } else if ((hue <= (_5B50[x] + _7B50[x]) / 2.0) &&
                           (hue > (_5B50[x] - 0.035)) && x < 79) {
                    if (y > 79) {
                        y = 79; //
                    }

                    correction = _5B50[y] - _5B50[x];
                    lbe = _5B50[y];
                    correctL = true;
                }

                else if ((hue >= (_15PB50[x] - 0.035)) &&
                         (hue < (_15PB50[x] + _3PB50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _15PB50[y] - _15PB50[x];
                    lbe = _15PB50[y];
                    correctL = true;
                } else if ((hue >= (_15PB50[x] + _3PB50[x]) / 2.0) &&
                           (hue < (_45PB50[x] + _3PB50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _3PB50[y] - _3PB50[x];
                    lbe = _3PB50[y];
                    correctL = true;
                } else if ((hue >= (_45PB50[x] + _3PB50[x]) / 2.0) &&
                           (hue < (_6PB50[x] + _45PB50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _45PB50[y] - _45PB50[x];
                    lbe = _45PB50[y];
                    correctL = true;
                } else if ((hue >= (_6PB50[x] + _45PB50[x]) / 2.0) &&
                           (hue < (_6PB50[x] + _75PB50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _6PB50[y] - _6PB50[x];
                    lbe = _6PB50[y];
                    correctL = true;
                } else if ((hue >= (_6PB50[x] + _75PB50[x]) / 2.0) &&
                           (hue < (_9PB50[x] + _75PB50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _75PB50[y] - _75PB50[x];
                    lbe = _75PB50[y];
                    correctL = true;
                } else if ((hue >= (_9PB50[x] + _75PB50[x]) / 2.0) &&
                           (hue < (_9PB50[x] + _10PB50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _9PB50[y] - _9PB50[x];
                    lbe = _9PB50[y];
                    correctL = true;
                } else if ((hue >= (_10PB50[x] + _9PB50[x]) / 2.0) &&
                           (hue < (_1P50[x] + _10PB50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10PB50[y] - _10PB50[x];
                    lbe = _10PB50[y];
                    correctL = true;
                } else if ((hue >= (_10PB50[x] + _1P50[x]) / 2.0) &&
                           (hue < (_1P50[x] + _4P50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _1P50[y] - _1P50[x];
                    lbe = _1P50[y];
                    correctL = true;
                } else if ((hue >= (_1P50[x] + _4P50[x]) / 2.0) &&
                           (hue < (0.035 + _4P50[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _4P50[y] - _4P50[x];
                    lbe = _4P50[y];
                    correctL = true;
                }
            } else if (lum < 65.0) {
                if ((hue <= (_05PB60[x] + _15PB60[x]) / 2.0) &&
                    (hue > (_05PB60[x] + _10B60[x]) / 2.0) && x < 79) {
                    if (y > 79) {
                        y = 79;
                    }

                    correction = _05PB60[y] - _05PB60[x];
                    lbe = _05PB60[y];
                    correctL = true;
                } else if ((hue <= (_05PB60[x] + _10B60[x]) / 2.0) &&
                           (hue > (_10B60[x] + _9B60[x]) / 2.0) && x < 79) {
                    if (y > 79) {
                        y = 79;
                    }

                    correction = _10B60[y] - _10B60[x];
                    lbe = _10B60[y];
                    correctL = true;
                } else if ((hue <= (_10B60[x] + _9B60[x]) / 2.0) &&
                           (hue > (_9B60[x] + _7B60[x]) / 2.0) && x < 79) {
                    if (y > 79) {
                        y = 79;
                    }

                    correction = _9B60[y] - _9B60[x];
                    lbe = _9B60[y];
                    correctL = true;
                } else if ((hue <= (_9B60[x] + _7B60[x]) / 2.0) &&
                           (hue > (_5B60[x] + _7B60[x]) / 2.0) && x < 79) {
                    if (y > 79) {
                        y = 79;
                    }

                    correction = _7B60[y] - _7B60[x];
                    lbe = _7B60[y];
                    correctL = true;
                } else if ((hue <= (_5B60[x] + _7B60[x]) / 2.0) &&
                           (hue > (_5B60[x] - 0.035)) && x < 79) {
                    if (y > 79) {
                        y = 79; //
                    }

                    correction = _5B60[y] - _5B60[x];
                    lbe = _5B60[y];
                    correctL = true;
                }

                else if ((hue >= (_15PB60[x] - 0.035)) &&
                         (hue < (_15PB60[x] + _3PB60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _15PB60[y] - _15PB60[x];
                    lbe = _15PB60[y];
                    correctL = true;
                } else if ((hue >= (_15PB60[x] + _3PB60[x]) / 2.0) &&
                           (hue < (_45PB60[x] + _3PB60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _3PB60[y] - _3PB60[x];
                    lbe = _3PB60[y];
                    correctL = true;
                } else if ((hue >= (_45PB60[x] + _3PB60[x]) / 2.0) &&
                           (hue < (_6PB60[x] + _45PB60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _45PB60[y] - _45PB60[x];
                    lbe = _45PB60[y];
                    correctL = true;
                } else if ((hue >= (_6PB60[x] + _45PB60[x]) / 2.0) &&
                           (hue < (_6PB60[x] + _75PB60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _6PB60[y] - _6PB60[x];
                    lbe = _6PB60[y];
                    correctL = true;
                } else if ((hue >= (_6PB60[x] + _75PB60[x]) / 2.0) &&
                           (hue < (_9PB60[x] + _75PB60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _75PB60[y] - _75PB60[x];
                    lbe = _75PB60[y];
                    correctL = true;
                } else if ((hue >= (_9PB60[x] + _75PB60[x]) / 2.0) &&
                           (hue < (_9PB60[x] + _10PB60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _9PB60[y] - _9PB60[x];
                    lbe = _9PB60[y];
                    correctL = true;
                } else if ((hue >= (_10PB60[x] + _9PB60[x]) / 2.0) &&
                           (hue < (_1P60[x] + _10PB60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10PB60[y] - _10PB60[x];
                    lbe = _10PB60[y];
                    correctL = true;
                } else if ((hue >= (_10PB60[x] + _1P60[x]) / 2.0) &&
                           (hue < (_1P60[x] + _4P60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _1P60[y] - _1P60[x];
                    lbe = _1P60[y];
                    correctL = true;
                } else if ((hue >= (_1P60[x] + _4P60[x]) / 2.0) &&
                           (hue < (0.035 + _4P60[x]) / 2.0) && x <= 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _4P60[y] - _4P60[x];
                    lbe = _4P60[y];
                    correctL = true;
                }
            } else if (lum < 75.0) {
                if ((hue <= (_05PB70[x] + _15PB70[x]) / 2.0) &&
                    (hue > (_05PB70[x] + _10B70[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _05PB70[y] - _05PB70[x];
                    lbe = _05PB70[y];
                    correctL = true;
                } else if ((hue <= (_05PB70[x] + _10B70[x]) / 2.0) &&
                           (hue > (_10B70[x] + _9B70[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _10B70[y] - _10B70[x];
                    lbe = _10B70[y];
                    correctL = true;
                } else if ((hue <= (_10B70[x] + _9B70[x]) / 2.0) &&
                           (hue > (_9B70[x] + _7B70[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _9B70[y] - _9B70[x];
                    lbe = _9B70[y];
                    correctL = true;
                } else if ((hue <= (_9B70[x] + _7B70[x]) / 2.0) &&
                           (hue > (_5B70[x] + _7B70[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _7B70[y] - _7B70[x];
                    lbe = _7B70[y];
                    correctL = true;
                } else if ((hue <= (_5B70[x] + _7B70[x]) / 2.0) &&
                           (hue > (_5B70[x] - 0.035)) && x < 50) {
                    if (y > 49) {
                        y = 49; //
                    }

                    correction = _5B70[y] - _5B70[x];
                    lbe = _5B70[y];
                    correctL = true;
                }

                else if ((hue >= (_15PB70[x] - 0.035)) &&
                         (hue < (_15PB70[x] + _3PB70[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _15PB70[y] - _15PB70[x];
                    lbe = _15PB70[y];
                    correctL = true;
                } else if ((hue >= (_45PB70[x] + _3PB70[x]) / 2.0) &&
                           (hue < (_6PB70[x] + _45PB70[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _45PB70[y] - _45PB70[x];
                    lbe = _45PB70[y];
                    correctL = true;
                } else if ((hue >= (_6PB70[x] + _45PB70[x]) / 2.0) &&
                           (hue < (_6PB70[x] + _75PB70[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _6PB70[y] - _6PB70[x];
                    lbe = _6PB70[y];
                    correctL = true;
                } else if ((hue >= (_6PB70[x] + _75PB70[x]) / 2.0) &&
                           (hue < (_9PB70[x] + _75PB70[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _75PB70[y] - _75PB70[x];
                    lbe = _75PB70[y];
                    correctL = true;
                } else if ((hue >= (_9PB70[x] + _75PB70[x]) / 2.0) &&
                           (hue < (_9PB70[x] + 0.035)) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _9PB70[y] - _9PB70[x];
                    lbe = _9PB70[y];
                    correctL = true;
                }
            } else if (lum < 85.0) {
                if ((hue <= (_05PB80[x] + _15PB80[x]) / 2.0) &&
                    (hue > (_05PB80[x] + _10B80[x]) / 2.0) && x < 40) {
                    if (y > 39) {
                        y = 39;
                    }

                    correction = _05PB80[y] - _05PB80[x];
                    lbe = _05PB80[y];
                    correctL = true;
                } else if ((hue <= (_05PB80[x] + _10B80[x]) / 2.0) &&
                           (hue > (_10B80[x] + _9B80[x]) / 2.0) && x < 40) {
                    if (y > 39) {
                        y = 39;
                    }

                    correction = _10B80[y] - _10B80[x];
                    lbe = _10B80[y];
                    correctL = true;
                } else if ((hue <= (_10B80[x] + _9B80[x]) / 2.0) &&
                           (hue > (_9B80[x] + _7B80[x]) / 2.0) && x < 40) {
                    if (y > 39) {
                        y = 39;
                    }

                    correction = _9B80[y] - _9B80[x];
                    lbe = _9B80[y];
                    correctL = true;
                } else if ((hue <= (_9B80[x] + _7B80[x]) / 2.0) &&
                           (hue > (_5B80[x] + _7B80[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _7B80[y] - _7B80[x];
                    lbe = _7B80[y];
                    correctL = true;
                } else if ((hue <= (_5B80[x] + _7B80[x]) / 2.0) &&
                           (hue > (_5B80[x] - 0.035)) && x < 50) {
                    if (y > 49) {
                        y = 49; //
                    }

                    correction = _5B80[y] - _5B80[x];
                    lbe = _5B80[y];
                    correctL = true;
                }

                else if ((hue >= (_15PB80[x] - 0.035)) &&
                         (hue < (_15PB80[x] + _3PB80[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _15PB80[y] - _15PB80[x];
                    lbe = _15PB80[y];
                    correctL = true;
                } else if ((hue >= (_45PB80[x] + _3PB80[x]) / 2.0) &&
                           (hue < (_6PB80[x] + _45PB80[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _45PB80[y] - _45PB80[x];
                    lbe = _45PB80[y];
                    correctL = true;
                } else if ((hue >= (_6PB80[x] + _45PB80[x]) / 2.0) &&
                           (hue < (_6PB80[x] + _75PB80[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _6PB80[y] - _6PB80[x];
                    lbe = _6PB80[y];
                    correctL = true;
                } else if ((hue >= (_6PB80[x] + _75PB80[x]) / 2.0) &&
                           (hue < (_9PB80[x] + _75PB80[x]) / 2.0) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _75PB80[y] - _75PB80[x];
                    lbe = _75PB80[y];
                    correctL = true;
                } else if ((hue >= (_9PB80[x] + _75PB80[x]) / 2.0) &&
                           (hue < (_9PB80[x] + 0.035)) && x < 50) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _9PB80[y] - _9PB80[x];
                    lbe = _9PB80[y];
                    correctL = true;
                }
            }
        }
    }
    // end PB correction

    // red yellow correction
    else if (zone == 2) {
        if (lum > 15.0) {
            if (lum < 25.0) {
                if ((hue <= (_10YR20[x] + 0.035)) &&
                    (hue > (_10YR20[x] + _85YR20[x]) / 2.0) && x <= 45) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _10YR20[y] - _10YR20[x];
                    lbe = _10YR20[y];
                    correctL = true;
                } else if ((hue <= (_85YR20[x] + _10YR20[x]) / 2.0) &&
                           (hue > (_85YR20[x] + 0.035) && x <= 45)) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _85YR20[y] - _85YR20[x];
                    lbe = _85YR20[y];
                    correctL = true;
                }
            } else if (lum < 35.0) {
                if ((hue <= (_10YR30[x] + 0.035)) &&
                    (hue > (_10YR30[x] + _85YR30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10YR30[y] - _10YR30[x];
                    lbe = _10YR30[y];
                    correctL = true;
                } else if ((hue <= (_10YR30[x] + _85YR30[x]) / 2.0) &&
                           (hue > (_85YR30[x] + _7YR30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _85YR30[y] - _85YR30[x];
                    lbe = _85YR30[y];
                    correctL = true;
                } else if ((hue <= (_85YR30[x] + _7YR30[x]) / 2.0) &&
                           (hue > (_7YR30[x] + _55YR30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7YR30[y] - _7YR30[x];
                    lbe = _7YR30[y];
                    correctL = true;
                } else if ((hue <= (_7YR30[x] + _55YR30[x]) / 2.0) &&
                           (hue > (_55YR30[x] + _4YR30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _55YR30[y] - _55YR30[x];
                    lbe = _55YR30[y];
                    correctL = true;
                } else if ((hue <= (_55YR30[x] + _4YR30[x]) / 2.0) &&
                           (hue > (_4YR30[x] + _25YR30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _4YR30[y] - _4YR30[x];
                    lbe = _4YR30[y];
                    correctL = true;
                } else if ((hue <= (_4YR30[x] + _25YR30[x]) / 2.0) &&
                           (hue > (_25YR30[x] + _10R30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _25YR30[y] - _25YR30[x];
                    lbe = _25YR30[y];
                    correctL = true;
                } else if ((hue <= (_25YR30[x] + _10R30[x]) / 2.0) &&
                           (hue > (_10R30[x] + _9R30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10R30[y] - _10R30[x];
                    lbe = _10R30[y];
                    correctL = true;
                } else if ((hue <= (_10R30[x] + _9R30[x]) / 2.0) &&
                           (hue > (_9R30[x] + _7R30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _9R30[y] - _9R30[x];
                    lbe = _9R30[y];
                    correctL = true;
                } else if ((hue <= (_9R30[x] + _7R30[x]) / 2.0) &&
                           (hue > (_7R30[x] - 0.035)) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7R30[y] - _7R30[x];
                    lbe = _7R30[y];
                    correctL = true;
                }
            } else if (lum < 45.0) {
                if ((hue <= (_10YR40[x] + 0.035)) &&
                    (hue > (_10YR40[x] + _85YR40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10YR40[y] - _10YR40[x];
                    lbe = _10YR40[y];
                    correctL = true;
                } else if ((hue <= (_10YR40[x] + _85YR40[x]) / 2.0) &&
                           (hue > (_85YR40[x] + _7YR40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _85YR40[y] - _85YR40[x];
                    lbe = _85YR40[y];
                    correctL = true;
                } else if ((hue <= (_85YR40[x] + _7YR40[x]) / 2.0) &&
                           (hue > (_7YR40[x] + _55YR40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7YR40[y] - _7YR40[x];
                    lbe = _7YR40[y];
                    correctL = true;
                } else if ((hue <= (_7YR40[x] + _55YR40[x]) / 2.0) &&
                           (hue > (_55YR40[x] + _4YR40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _55YR40[y] - _55YR40[x];
                    lbe = _55YR40[y];
                    correctL = true;
                } else if ((hue <= (_55YR40[x] + _4YR40[x]) / 2.0) &&
                           (hue > (_4YR40[x] + _25YR40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _4YR40[y] - _4YR40[x];
                    lbe = _4YR40[y];
                    correctL = true;
                } else if ((hue <= (_4YR40[x] + _25YR40[x]) / 2.0) &&
                           (hue > (_25YR40[x] + _10R40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _25YR40[y] - _25YR40[x];
                    lbe = _25YR40[y];
                    correctL = true;
                } else if ((hue <= (_25YR40[x] + _10R40[x]) / 2.0) &&
                           (hue > (_10R40[x] + _9R40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10R40[y] - _10R40[x];
                    lbe = _10R40[y];
                    correctL = true;
                } else if ((hue <= (_10R40[x] + _9R40[x]) / 2.0) &&
                           (hue > (_9R40[x] + _7R40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _9R40[y] - _9R40[x];
                    lbe = _9R40[y];
                    correctL = true;
                } else if ((hue <= (_9R40[x] + _7R40[x]) / 2.0) &&
                           (hue > (_7R40[x] - 0.035)) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7R40[y] - _7R40[x];
                    lbe = _7R40[y];
                    correctL = true;
                }
            } else if (lum < 55.0) {
                if ((hue <= (_10YR50[x] + 0.035)) &&
                    (hue > (_10YR50[x] + _85YR50[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10YR50[y] - _10YR50[x];
                    lbe = _10YR50[y];
                    correctL = true;
                } else if ((hue <= (_10YR50[x] + _85YR50[x]) / 2.0) &&
                           (hue > (_85YR50[x] + _7YR50[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _85YR50[y] - _85YR50[x];
                    lbe = _85YR50[y];
                    correctL = true;
                } else if ((hue <= (_85YR50[x] + _7YR50[x]) / 2.0) &&
                           (hue > (_7YR50[x] + _55YR50[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7YR50[y] - _7YR50[x];
                    lbe = _7YR50[y];
                    correctL = true;
                } else if ((hue <= (_7YR50[x] + _55YR50[x]) / 2.0) &&
                           (hue > (_55YR50[x] + _4YR50[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _55YR50[y] - _55YR50[x];
                    lbe = _55YR50[y];
                    correctL = true;
                } else if ((hue <= (_55YR50[x] + _4YR50[x]) / 2.0) &&
                           (hue > (_4YR50[x] + _25YR50[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _4YR50[y] - _4YR50[x];
                    lbe = _4YR50[y];
                    correctL = true;
                } else if ((hue <= (_4YR50[x] + _25YR50[x]) / 2.0) &&
                           (hue > (_25YR50[x] + _10R50[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _25YR50[y] - _25YR50[x];
                    lbe = _25YR50[y];
                    correctL = true;
                } else if ((hue <= (_25YR50[x] + _10R50[x]) / 2.0) &&
                           (hue > (_10R50[x] + _9R50[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10R50[y] - _10R50[x];
                    lbe = _10R50[y];
                    correctL = true;
                } else if ((hue <= (_10R50[x] + _9R50[x]) / 2.0) &&
                           (hue > (_9R50[x] + _7R50[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _9R50[y] - _9R50[x];
                    lbe = _9R50[y];
                    correctL = true;
                } else if ((hue <= (_9R50[x] + _7R50[x]) / 2.0) &&
                           (hue > (_7R50[x] - 0.035)) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7R50[y] - _7R50[x];
                    lbe = _7R50[y];
                    correctL = true;
                }
            } else if (lum < 65.0) {
                if ((hue <= (_10YR60[x] + 0.035)) &&
                    (hue > (_10YR60[x] + _85YR60[x]) / 2.0)) {
                    ;
                    correction = _10YR60[y] - _10YR60[x];
                    lbe = _10YR60[y];
                    correctL = true;
                } else if ((hue <= (_10YR60[x] + _85YR60[x]) / 2.0) &&
                           (hue > (_85YR60[x] + _7YR60[x]) / 2.0)) {
                    ;
                    correction = _85YR60[y] - _85YR60[x];
                    lbe = _85YR60[y];
                    correctL = true;
                } else if ((hue <= (_85YR60[x] + _7YR60[x]) / 2.0) &&
                           (hue > (_7YR60[x] + _55YR60[x]) / 2.0)) {
                    correction = _7YR60[y] - _7YR60[x];
                    lbe = _7YR60[y];
                    correctL = true;
                } else if ((hue <= (_7YR60[x] + _55YR60[x]) / 2.0) &&
                           (hue > (_55YR60[x] + _4YR60[x]) / 2.0)) {
                    correction = _55YR60[y] - _55YR60[x];
                    lbe = _55YR60[y];
                    correctL = true;
                } else if ((hue <= (_55YR60[x] + _4YR60[x]) / 2.0) &&
                           (hue > (_4YR60[x] + _25YR60[x]) / 2.0)) {
                    correction = _4YR60[y] - _4YR60[x];
                    lbe = _4YR60[y];
                    correctL = true;
                } else if ((hue <= (_4YR60[x] + _25YR60[x]) / 2.0) &&
                           (hue > (_25YR60[x] + _10R60[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _25YR60[y] - _25YR60[x];
                    lbe = _25YR60[y];
                    correctL = true;
                } else if ((hue <= (_25YR60[x] + _10R60[x]) / 2.0) &&
                           (hue > (_10R60[x] + _9R60[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10R60[y] - _10R60[x];
                    lbe = _10R60[y];
                    correctL = true;
                } else if ((hue <= (_10R60[x] + _9R60[x]) / 2.0) &&
                           (hue > (_9R60[x] + _7R60[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _9R60[y] - _9R60[x];
                    lbe = _9R60[y];
                    correctL = true;
                } else if ((hue <= (_9R60[x] + _7R60[x]) / 2.0) &&
                           (hue > (_7R60[x] - 0.035)) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7R60[y] - _7R60[x];
                    lbe = _7R60[y];
                    correctL = true;
                }
            } else if (lum < 75.0) {
                if ((hue <= (_10YR70[x] + 0.035)) &&
                    (hue > (_10YR70[x] + _85YR70[x]) / 2.0)) {
                    correction = _10YR70[y] - _10YR70[x];
                    lbe = _10YR70[y];
                    correctL = true;
                } else if ((hue <= (_10YR70[x] + _85YR70[x]) / 2.0) &&
                           (hue > (_85YR70[x] + _7YR70[x]) / 2.0)) {
                    correction = _85YR70[y] - _85YR70[x];
                    lbe = _85YR70[y];
                    correctL = true;
                }

                if ((hue <= (_85YR70[x] + _7YR70[x]) / 2.0) &&
                    (hue > (_7YR70[x] + _55YR70[x]) / 2.0)) {
                    correction = _7YR70[y] - _7YR70[x];
                    lbe = _7YR70[y];
                    correctL = true;
                } else if ((hue <= (_7YR70[x] + _55YR70[x]) / 2.0) &&
                           (hue > (_55YR70[x] + _4YR70[x]) / 2.0)) {
                    correction = _55YR70[y] - _55YR70[x];
                    lbe = _55YR70[y];
                    correctL = true;
                } else if ((hue <= (_55YR70[x] + _4YR70[x]) / 2.0) &&
                           (hue > (_4YR70[x] + _25YR70[x]) / 2.0)) {
                    correction = _4YR70[y] - _4YR70[x];
                    lbe = _4YR70[y];
                    correctL = true;
                } else if ((hue <= (_4YR70[x] + _25YR70[x]) / 2.0) &&
                           (hue > (_25YR70[x] + _10R70[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _25YR70[y] - _25YR70[x];
                    lbe = _25YR70[y];
                    correctL = true;
                } else if ((hue <= (_25YR70[x] + _10R70[x]) / 2.0) &&
                           (hue > (_10R70[x] + _9R70[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10R70[y] - _10R70[x];
                    lbe = _10R70[y];
                    correctL = true;
                } else if ((hue <= (_10R70[x] + _9R70[x]) / 2.0) &&
                           (hue > (_9R70[x] + _7R70[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _9R70[y] - _9R70[x];
                    lbe = _9R70[y];
                    correctL = true;
                } else if ((hue <= (_9R70[x] + _7R70[x]) / 2.0) &&
                           (hue > (_7R70[x] - 0.035)) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7R70[y] - _7R70[x];
                    lbe = _7R70[y];
                    correctL = true;
                }
            } else if (lum < 85.0) {
                if ((hue <= (_10YR80[x] + 0.035)) &&
                    (hue > (_10YR80[x] + _85YR80[x]) / 2.0)) {
                    correction = _10YR80[y] - _10YR80[x];
                    lbe = _10YR80[y];
                    correctL = true;
                } else if ((hue <= (_10YR80[x] + _85YR80[x]) / 2.0) &&
                           (hue > (_85YR80[x] + _7YR80[x]) / 2.0)) {
                    correction = _85YR80[y] - _85YR80[x];
                    lbe = _85YR80[y];
                } else if ((hue <= (_85YR80[x] + _7YR80[x]) / 2.0) &&
                           (hue > (_7YR80[x] + _55YR80[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _7YR80[y] - _7YR80[x];
                    lbe = _7YR80[y];
                    correctL = true;
                } else if ((hue <= (_7YR80[x] + _55YR80[x]) / 2.0) &&
                           (hue > (_55YR80[x] + _4YR80[x]) / 2.0) && x < 45) {
                    correction = _55YR80[y] - _55YR80[x];
                    lbe = _55YR80[y];
                    correctL = true;
                } else if ((hue <= (_55YR80[x] + _4YR80[x]) / 2.0) &&
                           (hue > (_4YR80[x] - 0.035) && x < 45)) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _4YR80[y] - _4YR80[x];
                    lbe = _4YR80[y];
                    correctL = true;
                }
            } else if (lum < 95.0) {
                if ((hue <= (_10YR90[x] + 0.035)) &&
                    (hue > (_10YR90[x] - 0.035) && x < 85)) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10YR90[y] - _10YR90[x];
                    lbe = _10YR90[y];
                    correctL = true;
                } else if (hue <= (_85YR90[x] + 0.035) &&
                           hue > (_85YR90[x] - 0.035) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _85YR90[y] - _85YR90[x];
                    lbe = _85YR90[y];
                    correctL = true;
                } else if ((hue <= (_55YR90[x] + 0.035) &&
                            (hue > (_55YR90[x] - 0.035) && x < 45))) {
                    if (y > 49) {
                        y = 49;
                    }

                    correction = _55YR90[y] - _55YR90[x];
                    lbe = _55YR90[y];
                    correctL = true;
                }
            }
        }
    }
    // end red yellow

    // Green yellow correction
    else if (zone == 3) {
        if (lum >= 25.0) {
            if (lum < 35.0) {
                if ((hue <= (_7G30[x] + 0.035)) &&
                    (hue > (_7G30[x] + _5G30[x]) / 2.0)) {
                    correction = _7G30[y] - _7G30[x];
                    lbe = _7G30[y];
                    correctL = true;
                } else if ((hue <= (_7G30[x] + _5G30[x]) / 2.0) &&
                           (hue > (_5G30[x] + _25G30[x]) / 2.0)) {
                    correction = _5G30[y] - _5G30[x];
                    lbe = _5G30[y];
                    correctL = true;
                } else if ((hue <= (_25G30[x] + _5G30[x]) / 2.0) &&
                           (hue > (_25G30[x] + _1G30[x]) / 2.0)) {
                    correction = _25G30[y] - _25G30[x];
                    lbe = _25G30[y];
                    correctL = true;
                } else if ((hue <= (_1G30[x] + _25G30[x]) / 2.0) &&
                           (hue > (_1G30[x] + _10GY30[x]) / 2.0)) {
                    correction = _1G30[y] - _1G30[x];
                    lbe = _1G30[y];
                    correctL = true;
                } else if ((hue <= (_1G30[x] + _10GY30[x]) / 2.0) &&
                           (hue > (_10GY30[x] + _75GY30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10GY30[y] - _10GY30[x];
                    lbe = _10GY30[y];
                    correctL = true;
                } else if ((hue <= (_10GY30[x] + _75GY30[x]) / 2.0) &&
                           (hue > (_75GY30[x] + _5GY30[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _75GY30[y] - _75GY30[x];
                    lbe = _75GY30[y];
                    correctL = true;
                } else if ((hue <= (_5GY30[x] + _75GY30[x]) / 2.0) &&
                           (hue > (_5GY30[x] - 0.035)) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _5GY30[y] - _5GY30[x];
                    lbe = _5GY30[y];
                    correctL = true;
                }
            } else if (lum < 45.0) {
                if ((hue <= (_7G40[x] + 0.035)) &&
                    (hue > (_7G40[x] + _5G40[x]) / 2.0)) {
                    correction = _7G40[y] - _7G40[x];
                    lbe = _7G40[y];
                    correctL = true;
                } else if ((hue <= (_7G40[x] + _5G40[x]) / 2.0) &&
                           (hue > (_5G40[x] + _25G40[x]) / 2.0)) {
                    correction = _5G40[y] - _5G40[x];
                    lbe = _5G40[y];
                    correctL = true;
                } else if ((hue <= (_25G40[x] + _5G40[x]) / 2.0) &&
                           (hue > (_25G40[x] + _1G40[x]) / 2.0)) {
                    correction = _25G40[y] - _25G40[x];
                    lbe = _25G40[y];
                    correctL = true;
                } else if ((hue <= (_1G40[x] + _25G40[x]) / 2.0) &&
                           (hue > (_1G40[x] + _10GY40[x]) / 2.0)) {
                    correction = _1G40[y] - _1G40[x];
                    lbe = _1G40[y];
                    correctL = true;
                } else if ((hue <= (_1G40[x] + _10GY40[x]) / 2.0) &&
                           (hue > (_10GY40[x] + _75GY40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _10GY40[y] - _10GY40[x];
                    lbe = _10GY40[y];
                    correctL = true;
                } else if ((hue <= (_10GY40[x] + _75GY40[x]) / 2.0) &&
                           (hue > (_75GY40[x] + _5GY40[x]) / 2.0) && x < 85) {
                    if (y > 89) {
                        y = 89;
                    }

                    correction = _75GY40[y] - _75GY40[x];
                    lbe = _75GY40[y];
                    correctL = true;
                } else if ((hue <= (_5GY40[x] + _75GY40[x]) / 2.0) &&
                           (hue > (_5GY40[x] - 0.035)) && x < 85) {
                    if (y > 89) {
                        y = 89; //
                    }

                    correction = _5GY40[y] - _5GY40[x];
                    lbe = _5GY40[y];
                    correctL = true;
                }
            } else if (lum < 55.0) {
                if ((hue <= (_7G50[x] + 0.035)) &&
                    (hue > (_7G50[x] + _5G50[x]) / 2.0)) {
                    correction = _7G50[y] - _7G50[x];
                    lbe = _7G50[y];
                    correctL = true;
                } else if ((hue <= (_7G50[x] + _5G50[x]) / 2.0) &&
                           (hue > (_5G50[x] + _25G50[x]) / 2.0)) {
                    correction = _5G50[y] - _5G50[x];
                    lbe = _5G50[y];
                    correctL = true;
                } else if ((hue <= (_25G50[x] + _5G50[x]) / 2.0) &&
                           (hue > (_25G50[x] + _1G50[x]) / 2.0)) {
                    correction = _25G50[y] - _25G50[x];
                    lbe = _25G50[y];
                    correctL = true;
                } else if ((hue <= (_1G50[x] + _25G50[x]) / 2.0) &&
                           (hue > (_1G50[x] + _10GY50[x]) / 2.0)) {
                    correction = _1G50[y] - _1G50[x];
                    lbe = _1G50[y];
                    correctL = true;
                } else if ((hue <= (_1G50[x] + _10GY50[x]) / 2.0) &&
                           (hue > (_10GY50[x] + _75GY50[x]) / 2.0)) {
                    correction = _10GY50[y] - _10GY50[x];
                    lbe = _10GY50[y];
                    correctL = true;
                } else if ((hue <= (_10GY50[x] + _75GY50[x]) / 2.0) &&
                           (hue > (_75GY50[x] + _5GY50[x]) / 2.0)) {
                    correction = _75GY50[y] - _75GY50[x];
                    lbe = _75GY50[y];
                    correctL = true;
                } else if ((hue <= (_5GY50[x] + _75GY50[x]) / 2.0) &&
                           (hue > (_5GY50[x] - 0.035))) {
                    correction = _5GY50[y] - _5GY50[x];
                    lbe = _5GY50[y];
                    correctL = true;
                }
            } else if (lum < 65.0) {
                if ((hue <= (_7G60[x] + 0.035)) &&
                    (hue > (_7G60[x] + _5G60[x]) / 2.0)) {
                    correction = _7G60[y] - _7G60[x];
                    lbe = _7G60[y];
                    correctL = true;
                } else if ((hue <= (_7G60[x] + _5G60[x]) / 2.0) &&
                           (hue > (_5G60[x] + _25G60[x]) / 2.0)) {
                    correction = _5G60[y] - _5G60[x];
                    lbe = _5G60[y];
                    correctL = true;
                } else if ((hue <= (_25G60[x] + _5G60[x]) / 2.0) &&
                           (hue > (_25G60[x] + _1G60[x]) / 2.0)) {
                    correction = _25G60[y] - _25G60[x];
                    lbe = _25G60[y];
                    correctL = true;
                } else if ((hue <= (_1G60[x] + _25G60[x]) / 2.0) &&
                           (hue > (_1G60[x] + _10GY60[x]) / 2.0)) {
                    correction = _1G60[y] - _1G60[x];
                    lbe = _1G60[y];
                    correctL = true;
                } else if ((hue <= (_1G60[x] + _10GY60[x]) / 2.0) &&
                           (hue > (_10GY60[x] + _75GY60[x]) / 2.0)) {
                    correction = _10GY60[y] - _10GY60[x];
                    lbe = _10GY60[y];
                    correctL = true;
                } else if ((hue <= (_10GY60[x] + _75GY60[x]) / 2.0) &&
                           (hue > (_75GY60[x] + _5GY60[x]) / 2.0)) {
                    correction = _75GY60[y] - _75GY60[x];
                    lbe = _75GY60[y];
                    correctL = true;
                } else if ((hue <= (_5GY60[x] + _75GY60[x]) / 2.0) &&
                           (hue > (_5GY60[x] - 0.035))) {
                    correction = _5GY60[y] - _5GY60[x];
                    lbe = _5GY60[y];
                    correctL = true;
                }
            } else if (lum < 75.0) {
                if ((hue <= (_7G70[x] + 0.035)) &&
                    (hue > (_7G70[x] + _5G70[x]) / 2.0)) {
                    correction = _7G70[y] - _7G70[x];
                    lbe = _7G70[y];
                    correctL = true;
                } else if ((hue <= (_7G70[x] + _5G70[x]) / 2.0) &&
                           (hue > (_5G70[x] + _25G70[x]) / 2.0)) {
                    correction = _5G70[y] - _5G70[x];
                    lbe = _5G70[y];
                    correctL = true;
                } else if ((hue <= (_25G70[x] + _5G70[x]) / 2.0) &&
                           (hue > (_25G70[x] + _1G70[x]) / 2.0)) {
                    correction = _25G70[y] - _25G70[x];
                    lbe = _25G70[y];
                    correctL = true;
                } else if ((hue <= (_1G70[x] + _25G70[x]) / 2.0) &&
                           (hue > (_1G70[x] + _10GY70[x]) / 2.0)) {
                    correction = _1G70[y] - _1G70[x];
                    lbe = _1G70[y];
                    correctL = true;
                } else if ((hue <= (_1G70[x] + _10GY70[x]) / 2.0) &&
                           (hue > (_10GY70[x] + _75GY70[x]) / 2.0)) {
                    correction = _10GY70[y] - _10GY70[x];
                    lbe = _10GY70[y];
                    correctL = true;
                } else if ((hue <= (_10GY70[x] + _75GY70[x]) / 2.0) &&
                           (hue > (_75GY70[x] + _5GY70[x]) / 2.0)) {
                    correction = _75GY70[y] - _75GY70[x];
                    lbe = _75GY70[y];
                    correctL = true;
                } else if ((hue <= (_5GY70[x] + _75GY70[x]) / 2.0) &&
                           (hue > (_5GY70[x] - 0.035))) {
                    correction = _5GY70[y] - _5GY70[x];
                    lbe = _5GY70[y];
                    correctL = true;
                }
            } else if (lum < 85.0) {
                if ((hue <= (_7G80[x] + 0.035)) &&
                    (hue > (_7G80[x] + _5G80[x]) / 2.0)) {
                    correction = _7G80[y] - _7G80[x];
                    lbe = _7G80[y];
                    correctL = true;
                } else if ((hue <= (_7G80[x] + _5G80[x]) / 2.0) &&
                           (hue > (_5G80[x] + _25G80[x]) / 2.0)) {
                    correction = _5G80[y] - _5G80[x];
                    lbe = _5G80[y];
                    correctL = true;
                } else if ((hue <= (_25G80[x] + _5G80[x]) / 2.0) &&
                           (hue > (_25G80[x] + _1G80[x]) / 2.0)) {
                    correction = _25G80[y] - _25G80[x];
                    lbe = _25G80[y];
                    correctL = true;
                } else if ((hue <= (_1G80[x] + _25G80[x]) / 2.0) &&
                           (hue > (_1G80[x] + _10GY80[x]) / 2.0)) {
                    correction = _1G80[y] - _1G80[x];
                    lbe = _1G80[y];
                    correctL = true;
                } else if ((hue <= (_1G80[x] + _10GY80[x]) / 2.0) &&
                           (hue > (_10GY80[x] + _75GY80[x]) / 2.0)) {
                    correction = _10GY80[y] - _10GY80[x];
                    lbe = _10GY80[y];
                    correctL = true;
                } else if ((hue <= (_10GY80[x] + _75GY80[x]) / 2.0) &&
                           (hue > (_75GY80[x] + _5GY80[x]) / 2.0)) {
                    correction = _75GY80[y] - _75GY80[x];
                    lbe = _75GY80[y];
                    correctL = true;
                } else if ((hue <= (_5GY80[x] + _75GY80[x]) / 2.0) &&
                           (hue > (_5GY80[x] - 0.035))) {
                    correction = _5GY80[y] - _5GY80[x];
                    lbe = _5GY80[y];
                    correctL = true;
                }
            }
        }
    }
    // end green yellow

    // Red purple correction : only for L < 30
    else if (zone == 4) {
        if (lum > 5.0) {
            if (lum < 15.0) {
                if ((hue <= (_5R10[x] + 0.035)) && (hue > (_5R10[x] - 0.043)) &&
                    x < 45) {
                    if (y > 44) {
                        y = 44;
                    }

                    correction = _5R10[y] - _5R10[x];
                    lbe = _5R10[y];
                    correctL = true;
                } else if ((hue <= (_25R10[x] + 0.043)) &&
                           (hue > (_25R10[x] + _10RP10[x]) / 2.0) && x < 45) {
                    if (y > 44) {
                        y = 44;
                    }

                    correction = _25R10[y] - _25R10[x];
                    lbe = _25R10[y];
                    correctL = true;
                } else if ((hue <= (_25R10[x] + _10RP10[x]) / 2.0) &&
                           (hue > (_10RP10[x] - 0.035)) && x < 45) {
                    if (y > 44) {
                        y = 44;
                    }

                    correction = _10RP10[y] - _10RP10[x];
                    lbe = _10RP10[y];
                    correctL = true;
                }
            } else if (lum < 25.0) {
                if ((hue <= (_5R20[x] + 0.035)) &&
                    (hue > (_5R20[x] + _25R20[x]) / 2.0) && x < 70) {
                    if (y > 70) {
                        y = 70;
                    }

                    correction = _5R20[y] - _5R20[x];
                    lbe = _5R20[y];
                    correctL = true;
                } else if ((hue <= (_5R20[x] + _25R20[x]) / 2.0) &&
                           (hue > (_10RP20[x] + _25R20[x]) / 2.0) && x < 70) {
                    if (y > 70) {
                        y = 70;
                    }

                    correction = _25R20[y] - _25R20[x];
                    lbe = _25R20[y];
                    correctL = true;
                } else if ((hue <= (_10RP20[x] + _25R20[x]) / 2.0) &&
                           (hue > (_10RP20[x] - 0.035)) && x < 70) {
                    if (y > 70) {
                        y = 70;
                    }

                    correction = _10RP20[y] - _10RP20[x];
                    lbe = _10RP20[y];
                    correctL = true;
                }
            } else if (lum < 35.0) {
                if ((hue <= (_5R30[x] + 0.035)) &&
                    (hue > (_5R30[x] + _25R30[x]) / 2.0) && x < 85) {
                    if (y > 85) {
                        y = 85;
                    }

                    correction = _5R30[y] - _5R30[x];
                    lbe = _5R30[y];
                    correctL = true;
                } else if ((hue <= (_5R30[x] + _25R30[x]) / 2.0) &&
                           (hue > (_10RP30[x] + _25R30[x]) / 2.0) && x < 85) {
                    if (y > 85) {
                        y = 85;
                    }

                    correction = _25R30[y] - _25R30[x];
                    lbe = _25R30[y];
                    correctL = true;
                } else if ((hue <= (_10RP30[x] + _25R30[x]) / 2.0) &&
                           (hue > (_10RP30[x] - 0.035)) && x < 85) {
                    if (y > 85) {
                        y = 85;
                    }

                    correction = _10RP30[y] - _10RP30[x];
                    lbe = _10RP30[y];
                    correctL = true;
                }
            }
        }
    }

    // end red purple
}

/*
 * Munsell Lch correction
 * Copyright (c) 2011  Jacques Desmis <jdesmis@gmail.com>
 *
 * data (Munsell ==> Lab) obtained with WallKillcolor and
 * http://www.cis.rit.edu/research/mcsl2/online/munsell.php each LUT give Hue in
 * function of C, for each color Munsell and Luminance eg: _6PB20 : color
 * Munsell 6PB for L=20 c=5 c=45 c=85 c=125..139 when possible: interpolation
 * betwwen values no value for C<5  (gray) low memory footprint -- maximum: 195
 * LUTf * 140 values errors due to small number of samples in LUT and
 * linearization are very low (1 to 2%) errors due to a different illuminant
 * "Daylight" than "C" are low, about 10%. For example, a theoretical correction
 * of 0.1 radian will be made with a real correction of 0.09 or 0.11 depending
 * on the color illuminant D50 errors due to the use of a very different
 * illuminant "C", for example illuminant "A" (tungsten) are higher, about 20%.
 * Theoretical correction of 0.52 radians will be made with a real correction of
 * 0.42
 */
void Munsell::init()
{
#ifdef _DEBUG
    MyTime t1e, t2e;
    t1e.set();
#endif

    const int maxInd = 140;
    const int maxInd2 = 90;
    const int maxInd3 = 50;

    // blue for sky
    _5B40(maxInd2);
    _5B40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _5B40[i] = -2.3 + 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5B40[i] = -2.2 + 0.00 * (i - 45);
        }
    }

    // printf("5B %1.2f  %1.2f\n",_5B40[44],_5B40[89]);
    _5B50(maxInd2);
    _5B50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _5B50[i] = -2.34 + 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5B50[i] = -2.24 + 0.0003 * (i - 45);
        }
    }

    // printf("5B %1.2f  %1.2f\n",_5B50[44],_5B50[89]);
    _5B60(maxInd2);
    _5B60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _5B60[i] = -2.4 + 0.003 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5B60[i] = -2.28 + 0.0005 * (i - 45);
        }
    }

    // printf("5B %1.2f  %1.2f\n",_5B60[44],_5B60[89]);
    _5B70(maxInd2);
    _5B70.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _5B70[i] = -2.41 + 0.00275 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5B70[i] = -2.30 + 0.00025 * (i - 45);
        }
    }

    // printf("5B %1.2f  %1.2f\n",_5B70[44],_5B70[89]);
    _5B80(maxInd3);
    _5B80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _5B80[i] = -2.45 + 0.003 * (i - 5);
        }
    }

    // printf("5B %1.2f\n",_5B80[49]);

    _7B40(maxInd2);
    _7B40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7B40[i] = -2.15 + 0.0027 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7B40[i] = -2.04 + 0.00 * (i - 45);
        }
    }

    // printf("7B %1.2f  %1.2f\n",_7B40[44],_7B40[89]);
    _7B50(maxInd2);
    _7B50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7B50[i] = -2.20 + 0.003 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7B50[i] = -2.08 + 0.001 * (i - 45);
        }
    }

    // printf("7B %1.2f  %1.2f\n",_7B50[44],_7B50[79]);
    _7B60(maxInd2);
    _7B60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7B60[i] = -2.26 + 0.0035 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7B60[i] = -2.12 + 0.001 * (i - 45);
        }
    }

    // printf("7B %1.2f  %1.2f\n",_7B60[44],_7B60[79]);
    _7B70(maxInd2);
    _7B70.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7B70[i] = -2.28 + 0.003 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7B70[i] = -2.16 + 0.0015 * (i - 45);
        }
    }

    // printf("7B %1.2f  %1.2f\n",_7B70[44],_7B70[64]);
    _7B80(maxInd3);
    _7B80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _7B80[i] = -2.30 + 0.0028 * (i - 5);
        }
    }

    // printf("5B %1.2f\n",_7B80[49]);

    _9B40(maxInd2);
    _9B40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9B40[i] = -1.99 + 0.0022 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9B40[i] = -1.90 + 0.0008 * (i - 45);
        }
    }

    // printf("9B %1.2f  %1.2f\n",_9B40[44],_9B40[69]);
    _9B50(maxInd2);
    _9B50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9B50[i] = -2.04 + 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9B50[i] = -1.94 + 0.0013 * (i - 45);
        }
    }

    // printf("9B %1.2f  %1.2f\n",_9B50[44],_9B50[77]);
    _9B60(maxInd2);
    _9B60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9B60[i] = -2.10 + 0.0033 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9B60[i] = -1.97 + 0.001 * (i - 45);
        }
    }

    // printf("9B %1.2f  %1.2f\n",_9B60[44],_9B60[79]);
    _9B70(maxInd2);
    _9B70.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9B70[i] = -2.12 + 0.003 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9B70[i] = -2.00 + 0.001 * (i - 45);
        }
    }

    // printf("9B %1.2f  %1.2f\n",_9B70[44],_9B70[54]);
    _9B80(maxInd3);
    _9B80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _9B80[i] = -2.16 + 0.0025 * (i - 5);
        }
    }

    // printf("9B %1.2f\n",_9B80[49]);

    _10B40(maxInd2);
    _10B40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10B40[i] = -1.92 + 0.0022 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10B40[i] = -1.83 + 0.0012 * (i - 45);
        }
    }

    // printf("10B %1.2f  %1.2f\n",_10B40[44],_10B40[76]);
    _10B50(maxInd2);
    _10B50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10B50[i] = -1.95 + 0.0022 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10B50[i] = -1.86 + 0.0008 * (i - 45);
        }
    }

    // printf("10B %1.2f  %1.2f\n",_10B50[44],_10B50[85]);
    _10B60(maxInd2);
    _10B60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10B60[i] = -2.01 + 0.0027 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10B60[i] = -1.90 + 0.0012 * (i - 45);
        }
    }

    // printf("10B %1.2f  %1.2f\n",_10B60[44],_10B60[70]);
    _10B70(maxInd3);
    _10B70.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _10B70[i] = -2.03 + 0.0025 * (i - 5);
        }
    }

    // printf("10B %1.2f\n",_10B70[49]);
    _10B80(maxInd3);
    _10B80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _10B80[i] = -2.08 + 0.0032 * (i - 5);
        }
    }

    // printf("10B %1.2f\n",_10B80[39]);

    _05PB40(maxInd2);
    _05PB40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _05PB40[i] = -1.87 + 0.0022 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _05PB40[i] = -1.78 + 0.0015 * (i - 45);
        }
    }

    // printf("05PB %1.2f  %1.2f\n",_05PB40[44],_05PB40[74]);
    _05PB50(maxInd2);
    _05PB50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _05PB50[i] = -1.91 + 0.0022 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _05PB50[i] = -1.82 + 0.001 * (i - 45);
        }
    }

    // printf("05PB %1.2f  %1.2f\n",_05PB50[44],_05PB50[85]);
    _05PB60(maxInd2);
    _05PB60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _05PB60[i] = -1.96 + 0.0027 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _05PB60[i] = -1.85 + 0.0013 * (i - 45);
        }
    }

    // printf("05PB %1.2f  %1.2f\n",_05PB60[44],_05PB60[70]);
    _05PB70(maxInd2);
    _05PB70.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _05PB70[i] = -1.99 + 0.0027 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _05PB70[i] = -1.88 + 0.001 * (i - 45);
        }
    }

    // printf("05PB %1.2f  %1.2f\n",_05PB70[44],_05PB70[54]);
    _05PB80(maxInd3);
    _05PB80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _05PB80[i] = -2.03 + 0.003 * (i - 5);
        }
    }

    // printf("05PB %1.2f\n",_05PB80[39]);

    // blue purple correction
    // between 15PB to 4P
    // maximum deviation 75PB

    // 15PB
    _15PB10(maxInd3);
    _15PB10.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _15PB10[i] = -1.66 + 0.0035 * (i - 5);
        }
    }

    // printf("15 %1.2f\n",_15PB10[49]);
    _15PB20(maxInd2);
    _15PB20.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _15PB20[i] = -1.71 + 0.00275 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _15PB20[i] = -1.60 + 0.0012 * (i - 45);
        }
    }

    // printf("15 %1.2f  %1.2f\n",_15PB20[44],_15PB20[89]);

    _15PB30(maxInd2);
    _15PB30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _15PB30[i] = -1.75 + 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _15PB30[i] = -1.65 + 0.002 * (i - 45);
        }
    }

    // printf("15 %1.2f  %1.2f\n",_15PB30[44],_15PB30[89]);

    _15PB40(maxInd2);
    _15PB40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _15PB40[i] = -1.79 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _15PB40[i] = -1.71 + 0.002 * (i - 45);
        }
    }

    // printf("15 %1.2f  %1.2f\n",_15PB40[44],_15PB40[89]);

    _15PB50(maxInd2);
    _15PB50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _15PB50[i] = -1.82 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _15PB50[i] = -1.74 + 0.0011 * (i - 45);
        }
    }

    // printf("15 %1.2f  %1.2f\n",_15PB50[44],_15PB50[89]);

    _15PB60(maxInd2);
    _15PB60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _15PB60[i] = -1.87 + 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _15PB60[i] = -1.77 + 0.001 * (i - 45);
        }
    }

    // printf("15 %1.2f  %1.2f\n",_15PB60[44],_15PB60[89]);
    _15PB70(maxInd3);
    _15PB70.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _15PB70[i] = -1.90 + 0.0027 * (i - 5);
        }
    }

    //    printf("15 %1.2f\n",_15PB70[49]);
    _15PB80(maxInd3);
    _15PB80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _15PB80[i] = -1.93 + 0.0027 * (i - 5);
        }
    }

    // printf("15 %1.2f %1.2f\n",_15PB80[38], _15PB80[49]);

    // 3PB
    _3PB10(maxInd2);
    _3PB10.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _3PB10[i] = -1.56 + 0.005 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _3PB10[i] = -1.36 + 0.001 * (i - 45);
        }
    }

    // printf("30 %1.2f  %1.2f\n",_3PB10[44],_3PB10[89]);

    _3PB20(maxInd2);
    _3PB20.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _3PB20[i] = -1.59 + 0.00275 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _3PB20[i] = -1.48 + 0.003 * (i - 45);
        }
    }

    // printf("30 %1.2f  %1.2f\n",_3PB20[44],_3PB20[89]);

    _3PB30(maxInd2);
    _3PB30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _3PB30[i] = -1.62 + 0.00225 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _3PB30[i] = -1.53 + 0.0032 * (i - 45);
        }
    }

    // printf("30 %1.2f  %1.2f\n",_3PB30[44],_3PB30[89]);

    _3PB40(maxInd2);
    _3PB40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _3PB40[i] = -1.64 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _3PB40[i] = -1.58 + 0.0025 * (i - 45);
        }
    }

    // printf("30 %1.2f  %1.2f\n",_3PB40[44],_3PB40[89]);

    _3PB50(maxInd2);
    _3PB50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _3PB50[i] = -1.69 + 0.00175 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _3PB50[i] = -1.62 + 0.002 * (i - 45);
        }
    }

    // printf("30 %1.2f  %1.2f\n",_3PB50[44],_3PB50[89]);

    _3PB60(maxInd2);
    _3PB60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _3PB60[i] = -1.73 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _3PB60[i] = -1.65 + 0.0012 * (i - 45);
        }
    }

    // printf("30 %1.2f  %1.2f\n",_3PB60[44],_3PB60[89]);
    _3PB70(maxInd3);
    _3PB70.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _3PB70[i] = -1.76 + 0.002 * (i - 5);
        }
    }

    // printf("30 %1.2f\n",_3PB70[49]);
    _3PB80(maxInd3);
    _3PB80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _3PB80[i] = -1.78 + 0.0025 * (i - 5);
        }
    }

    // printf("30 %1.2f %1.2f\n",_3PB80[38], _3PB80[49]);

    // 45PB
    _45PB10(maxInd2);
    _45PB10.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _45PB10[i] = -1.46 + 0.0045 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _45PB10[i] = -1.28 + 0.0025 * (i - 45);
        }
    }

    // printf("45 %1.2f  %1.2f\n",_45PB10[44],_45PB10[89]);

    _45PB20(maxInd2);
    _45PB20.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _45PB20[i] = -1.48 + 0.00275 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _45PB20[i] = -1.37 + 0.0025 * (i - 45);
        }
    }

    // printf("45 %1.2f  %1.2f\n",_45PB20[44],_45PB20[89]);

    _45PB30(maxInd2);
    _45PB30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _45PB30[i] = -1.51 + 0.00175 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _45PB30[i] = -1.44 + 0.0035 * (i - 45);
        }
    }

    // printf("45 %1.2f  %1.2f\n",_45PB30[44],_45PB30[89]);

    _45PB40(maxInd2);
    _45PB40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _45PB40[i] = -1.52 + 0.001 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _45PB40[i] = -1.48 + 0.003 * (i - 45);
        }
    }

    // printf("45 %1.2f  %1.2f\n",_45PB40[44],_45PB40[89]);

    _45PB50(maxInd2);
    _45PB50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _45PB50[i] = -1.55 + 0.001 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _45PB50[i] = -1.51 + 0.0022 * (i - 45);
        }
    }

    // printf("45 %1.2f  %1.2f\n",_45PB50[44],_45PB50[89]);

    _45PB60(maxInd2);
    _45PB60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _45PB60[i] = -1.6 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _45PB60[i] = -1.54 + 0.001 * (i - 45);
        }
    }

    // printf("45 %1.2f  %1.2f\n",_45PB60[44],_45PB60[89]);
    _45PB70(maxInd3);
    _45PB70.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _45PB70[i] = -1.63 + 0.0017 * (i - 5);
        }
    }

    // printf("45 %1.2f\n",_45PB70[49]);
    _45PB80(maxInd3);
    _45PB80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _45PB80[i] = -1.67 + 0.0025 * (i - 5);
        }
    }

    // printf("45 %1.2f %1.2f\n",_45PB80[38], _45PB80[49]);

    //_6PB
    _6PB10(maxInd);
    _6PB10.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _6PB10[i] = -1.33 + 0.005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _6PB10[i] = -1.13 + 0.0045 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _6PB10[i] = -0.95 + 0.0015 * (i - 85);
        }
    }

    // printf("60 %1.2f  %1.2f %1.2f\n",_6PB10[44],_6PB10[84],_6PB10[139]);

    _6PB20(maxInd);
    _6PB20.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _6PB20[i] = -1.36 + 0.004 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _6PB20[i] = -1.20 + 0.00375 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _6PB20[i] = -1.05 + 0.0017 * (i - 85);
        }
    }

    // printf("60 %1.2f  %1.2f %1.2f\n",_6PB20[44],_6PB20[84],_6PB20[139]);

    _6PB30(maxInd);
    _6PB30.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _6PB30[i] = -1.38 + 0.00225 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _6PB30[i] = -1.29 + 0.00375 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _6PB30[i] = -1.14 + 0.002 * (i - 85);
        }
    }

    // printf("60 %1.2f  %1.2f %1.2f\n",_6PB30[44],_6PB30[84],_6PB30[139]);

    _6PB40(maxInd);
    _6PB40.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _6PB40[i] = -1.39 + 0.00125 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _6PB40[i] = -1.34 + 0.00275 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _6PB40[i] = -1.23 + 0.002 * (i - 85);
        }
    }

    // printf("60 %1.2f  %1.2f %1.2f\n",_6PB40[44],_6PB40[84],_6PB40[139]);

    _6PB50(maxInd2); // limits  -1.3   -1.11
    _6PB50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _6PB50[i] = -1.43 + 0.00125 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _6PB50[i] = -1.38 + 0.00225 * (i - 45);
        }
    }

    // printf("60 %1.2f  %1.2f \n",_6PB50[44],_6PB50[89]);

    _6PB60(maxInd2); // limits  -1.3   -1.11
    _6PB60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _6PB60[i] = -1.46 + 0.0012 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _6PB60[i] = -1.40 + 0.000875 * (i - 45);
        }
    }

    // printf("60 %1.2f  %1.2f\n",_6PB60[44],_6PB60[89]);
    _6PB70(maxInd3);
    _6PB70.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _6PB70[i] = -1.49 + 0.0018 * (i - 5);
        }
    }

    // printf("6 %1.2f\n",_6PB70[49]);
    _6PB80(maxInd3);
    _6PB80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _6PB80[i] = -1.52 + 0.0022 * (i - 5);
        }
    }

    // printf("6 %1.2f %1.2f\n",_6PB80[38], _6PB80[49]);

    //_75PB : notation Munsell for maximum deviation blue purple
    _75PB10(maxInd); // limits hue -1.23  -0.71  _75PBx   x=Luminance  eg_75PB10
                     // for L >5 and L<=15
    _75PB10.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _75PB10[i] = -1.23 + 0.0065 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _75PB10[i] = -0.97 + 0.00375 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _75PB10[i] = -0.82 + 0.0015 * (i - 85);
        }
    }

    // printf("75 %1.2f  %1.2f %1.2f\n",_75PB10[44],_75PB10[84],_75PB10[139]);

    _75PB20(maxInd); // limits -1.24  -0.79  for L>15 <=25
    _75PB20.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75PB20[i] = -1.24 + 0.004 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _75PB20[i] = -1.08 + 0.00425 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _75PB20[i] = -0.91 + 0.0017 * (i - 85);
        }
    }

    // printf("75 %1.2f  %1.2f %1.2f\n",_75PB20[44],_75PB20[84],_75PB20[139]);

    _75PB30(maxInd); // limits -1.25  -0.85
    _75PB30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75PB30[i] = -1.25 + 0.00275 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _75PB30[i] = -1.14 + 0.004 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _75PB30[i] = -0.98 + 0.0015 * (i - 85);
        }
    }

    // printf("75 %1.2f  %1.2f %1.2f\n",_75PB30[44],_75PB30[84],_75PB30[139]);

    _75PB40(maxInd); // limits  -1.27  -0.92
    _75PB40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75PB40[i] = -1.27 + 0.002 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _75PB40[i] = -1.19 + 0.003 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _75PB40[i] = -1.07 + 0.0022 * (i - 85);
        }
    }

    // printf("75 %1.2f  %1.2f %1.2f\n",_75PB40[44],_75PB40[84],_75PB40[139]);

    _75PB50(maxInd2); // limits  -1.3   -1.11
    _75PB50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _75PB50[i] = -1.3 + 0.00175 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _75PB50[i] = -1.23 + 0.0025 * (i - 45);
        }
    }

    // printf("75 %1.2f  %1.2f\n",_75PB50[44],_75PB50[89]);

    _75PB60(maxInd2);
    _75PB60.clear();

    for (int i = 0; i < maxInd2; i++) { // limits -1.32  -1.17
        if (i < 45 && i > 5) {
            _75PB60[i] = -1.32 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _75PB60[i] = -1.26 + 0.002 * (i - 45);
        }
    }

    // printf("75 %1.2f  %1.2f \n",_75PB60[44],_75PB60[89]);

    _75PB70(maxInd3);
    _75PB70.clear();

    for (int i = 0; i < maxInd3; i++) { // limits  -1.34  -1.27
        if (i < 50 && i > 5) {
            _75PB70[i] = -1.34 + 0.002 * (i - 5);
        }
    }

    _75PB80(maxInd3);
    _75PB80.clear();

    for (int i = 0; i < maxInd3; i++) { // limits -1.35  -1.29
        if (i < 50 && i > 5) {
            _75PB80[i] = -1.35 + 0.00125 * (i - 5);
        }
    }

    _9PB10(maxInd);
    _9PB10.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _9PB10[i] = -1.09 + 0.00475 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _9PB10[i] = -0.9 + 0.003 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _9PB10[i] = -0.78 + 0.0013 * (i - 85);
        }
    }

    // printf("90 %1.2f  %1.2f %1.2f\n",_9PB10[44],_9PB10[84],_9PB10[139]);

    _9PB20(maxInd);
    _9PB20.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _9PB20[i] = -1.12 + 0.0035 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _9PB20[i] = -0.98 + 0.00325 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _9PB20[i] = -0.85 + 0.0015 * (i - 85);
        }
    }

    // printf("90 %1.2f  %1.2f %1.2f\n",_9PB20[44],_9PB20[84],_9PB20[139]);

    _9PB30(maxInd);
    _9PB30.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _9PB30[i] = -1.14 + 0.0028 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _9PB30[i] = -1.03 + 0.003 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _9PB30[i] = -0.91 + 0.0017 * (i - 85);
        }
    }

    // printf("90 %1.2f  %1.2f %1.2f\n",_9PB30[44],_9PB30[84],_9PB30[139]);

    _9PB40(maxInd);
    _9PB40.clear();

    for (int i = 0; i < maxInd; i++) { // i = chromaticity  0==>140
        if (i < 45 && i > 5) {
            _9PB40[i] = -1.16 + 0.002 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _9PB40[i] = -1.08 + 0.00275 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _9PB40[i] = -0.97 + 0.0016 * (i - 85);
        }
    }

    // printf("90 %1.2f  %1.2f %1.2f\n",_9PB40[44],_9PB40[84],_9PB40[139]);

    _9PB50(maxInd2);
    _9PB50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9PB50[i] = -1.19 + 0.00175 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9PB50[i] = -1.12 + 0.00225 * (i - 45);
        }
    }

    // printf("90 %1.2f  %1.2f \n",_9PB50[44],_9PB50[84]);

    _9PB60(maxInd2);
    _9PB60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9PB60[i] = -1.21 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9PB60[i] = -1.15 + 0.002 * (i - 45);
        }
    }

    // printf("90 %1.2f  %1.2f \n",_9PB60[44],_9PB60[89]);
    _9PB70(maxInd3);
    _9PB70.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _9PB70[i] = -1.23 + 0.0018 * (i - 5);
        }
    }

    // printf("9 %1.2f\n",_9PB70[49]);
    _9PB80(maxInd3);
    _9PB80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _9PB80[i] = -1.24 + 0.002 * (i - 5);
        }
    }

    // printf("9 %1.2f %1.2f\n",_9PB80[38], _9PB80[49]);

    // 10PB
    _10PB10(maxInd);
    _10PB10.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10PB10[i] = -1.02 + 0.00425 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10PB10[i] = -0.85 + 0.0025 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10PB10[i] = -0.75 + 0.0012 * (i - 85);
        }
    }

    // printf("10 %1.2f  %1.2f %1.2f\n",_10PB10[44],_10PB10[84],_10PB10[139]);

    _10PB20(maxInd);
    _10PB20.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10PB20[i] = -1.05 + 0.00325 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10PB20[i] = -0.92 + 0.00275 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10PB20[i] = -0.81 + 0.0014 * (i - 85);
        }
    }

    // printf("10 %1.2f  %1.2f %1.2f\n",_10PB20[44],_10PB20[84],_10PB20[139]);

    _10PB30(maxInd);
    _10PB30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10PB30[i] = -1.07 + 0.00275 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10PB30[i] = -0.96 + 0.0025 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10PB30[i] = -0.86 + 0.0015 * (i - 85);
        }
    }

    // printf("10 %1.2f  %1.2f %1.2f\n",_10PB30[44],_10PB30[84],_10PB30[139]);

    _10PB40(maxInd);
    _10PB40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10PB40[i] = -1.09 + 0.002 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10PB40[i] = -1.01 + 0.00225 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10PB40[i] = -0.92 + 0.0016 * (i - 85);
        }
    }

    // printf("10 %1.2f  %1.2f %1.2f\n",_10PB40[44],_10PB40[84],_10PB40[139]);

    _10PB50(maxInd2);
    _10PB50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10PB50[i] = -1.12 + 0.00175 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10PB50[i] = -1.05 + 0.00225 * (i - 45);
        }
    }

    // printf("10 %1.2f  %1.2f\n",_10PB50[44],_10PB50[84]);

    _10PB60(maxInd2);
    _10PB60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10PB60[i] = -1.14 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10PB60[i] = -1.08 + 0.00225 * (i - 45);
        }
    }

    // printf("10 %1.2f  %1.2f\n",_10PB60[44],_10PB60[89]);

    // 1P
    _1P10(maxInd);
    _1P10.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1P10[i] = -0.96 + 0.00375 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1P10[i] = -0.81 + 0.00225 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1P10[i] = -0.72 + 0.001 * (i - 85);
        }
    }

    // printf("1P %1.2f  %1.2f %1.2f\n",_1P10[44],_1P10[84],_1P10[139]);

    _1P20(maxInd);
    _1P20.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1P20[i] = -1.0 + 0.00325 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1P20[i] = -0.87 + 0.0025 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1P20[i] = -0.77 + 0.0012 * (i - 85);
        }
    }

    // printf("1P %1.2f  %1.2f %1.2f\n",_1P20[44],_1P20[84],_1P20[139]);

    _1P30(maxInd);
    _1P30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1P30[i] = -1.02 + 0.00275 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1P30[i] = -0.91 + 0.00225 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1P30[i] = -0.82 + 0.0011 * (i - 85);
        }
    }

    // printf("1P %1.2f  %1.2f %1.2f\n",_1P30[44],_1P30[84],_1P30[139]);

    _1P40(maxInd);
    _1P40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1P40[i] = -1.04 + 0.00225 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1P40[i] = -0.95 + 0.00225 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1P40[i] = -0.86 + 0.0015 * (i - 85);
        }
    }

    // printf("1P %1.2f  %1.2f %1.2f\n",_1P40[44],_1P40[84],_1P40[139]);

    _1P50(maxInd2);
    _1P50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _1P50[i] = -1.06 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _1P50[i] = -0.98 + 0.00175 * (i - 45);
        }
    }

    // printf("1P %1.2f  %1.2f \n",_1P50[44],_1P50[89]);

    _1P60(maxInd2);
    _1P60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _1P60[i] = -1.07 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _1P60[i] = -1.01 + 0.00175 * (i - 45);
        }
    }

    // printf("1P %1.2f  %1.2f \n",_1P60[44],_1P60[84],_1P60[139]);

    // 4P
    _4P10(maxInd);
    _4P10.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _4P10[i] = -0.78 + 0.002 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _4P10[i] = -0.7 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _4P10[i] = -0.65 + 0.001 * (i - 85);
        }
    }

    // printf("4P %1.2f  %1.2f %1.2f\n",_4P10[44],_4P10[84],_4P10[139]);

    _4P20(maxInd);
    _4P20.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _4P20[i] = -0.84 + 0.0025 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _4P20[i] = -0.74 + 0.00175 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _4P20[i] = -0.67 + 0.00085 * (i - 85);
        }
    }

    // printf("4P %1.2f  %1.2f %1.2f\n",_4P20[44],_4P20[84],_4P20[139]);

    _4P30(maxInd);
    _4P30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _4P30[i] = -0.85 + 0.00225 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _4P30[i] = -0.76 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _4P30[i] = -0.71 + 0.001 * (i - 85);
        }
    }

    // printf("4P %1.2f  %1.2f %1.2f\n",_4P30[44],_4P30[84],_4P30[139]);

    _4P40(maxInd);
    _4P40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _4P40[i] = -0.87 + 0.00175 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _4P40[i] = -0.8 + 0.00175 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _4P40[i] = -0.73 + 0.00075 * (i - 85);
        }
    }

    // printf("4P %1.2f  %1.2f %1.2f\n",_4P40[44],_4P40[84],_4P40[139]);

    _4P50(maxInd2);
    _4P50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _4P50[i] = -0.88 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _4P50[i] = -0.82 + 0.0015 * (i - 45);
        }
    }

    // printf("4P %1.2f  %1.2f \n",_4P50[44],_4P50[89]);

    _4P60(maxInd2);
    _4P60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _4P60[i] = -0.89 + 0.00125 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _4P60[i] = -0.84 + 0.00125 * (i - 45);
        }
    }

    // printf("4P %1.2f  %1.2f\n",_4P60[44],_4P60[89]);

    // red yellow correction
    _10YR20(maxInd2);
    _10YR20.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10YR20[i] = 1.22 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10YR20[i] = 1.30 + 0.006 * (i - 45);
        }
    }

    // printf("10YR  %1.2f  %1.2f\n",_10YR20[44],_10YR20[56]);
    _10YR30(maxInd2);
    _10YR30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10YR30[i] = 1.27 + 0.00175 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10YR30[i] = 1.34 + 0.0017 * (i - 45);
        }
    }

    // printf("10YR  %1.2f  %1.2f\n",_10YR30[44],_10YR30[75]);
    _10YR40(maxInd2);
    _10YR40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10YR40[i] = 1.32 + 0.00025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10YR40[i] = 1.33 + 0.0015 * (i - 45);
        }
    }

    // printf("10YR  %1.2f  %1.2f\n",_10YR40[44],_10YR40[85]);
    _10YR50(maxInd2);
    _10YR50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10YR50[i] = 1.35 + 0.000 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10YR50[i] = 1.35 + 0.0012 * (i - 45);
        }
    }

    // printf("10YR  %1.2f  %1.2f\n",_10YR50[44],_10YR50[80]);
    _10YR60(maxInd);
    _10YR60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10YR60[i] = 1.38 - 0.00025 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10YR60[i] = 1.37 + 0.0005 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10YR60[i] = 1.39 + 0.0013 * (i - 85);
        }
    }

    // printf("10YR  %1.2f  %1.2f %1.2f\n",_10YR60[44],_10YR60[85],_10YR60[139]
    // );
    _10YR70(maxInd);
    _10YR70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10YR70[i] = 1.41 - 0.0005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10YR70[i] = 1.39 + 0.000 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10YR70[i] = 1.39 + 0.0013 * (i - 85);
        }
    }

    // printf("10YR  %1.2f  %1.2f %1.2f\n",_10YR70[44],_10YR70[85],_10YR70[139]
    // );
    _10YR80(maxInd);
    _10YR80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10YR80[i] = 1.45 - 0.00125 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10YR80[i] = 1.40 + 0.000 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10YR80[i] = 1.40 + 0.00072 * (i - 85); // 1.436
        }
    }

    // printf("10YR  %1.2f  %1.2f %1.2f\n",_10YR80[44],_10YR80[84],_10YR80[139]
    // );
    _10YR90(maxInd2);
    _10YR90.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10YR90[i] = 1.48 - 0.001 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10YR90[i] = 1.44 - 0.0009 * (i - 45);
        }
    }

    // printf("10YR  %1.2f  %1.2f\n",_10YR90[45],_10YR90[80]);
    _85YR20(maxInd3);
    _85YR20.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _85YR20[i] = 1.12 + 0.004 * (i - 5);
        }
    }

    // printf("85YR  %1.2f \n",_85YR20[44]);
    _85YR30(maxInd2);
    _85YR30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _85YR30[i] = 1.16 + 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _85YR30[i] = 1.26 + 0.0028 * (i - 45);
        }
    }

    // printf("85YR  %1.2f  %1.2f\n",_85YR30[44],_85YR30[75]);
    _85YR40(maxInd2);
    _85YR40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _85YR40[i] = 1.20 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _85YR40[i] = 1.26 + 0.0024 * (i - 45);
        }
    }

    // printf("85YR  %1.2f  %1.2f\n",_85YR40[44],_85YR40[75]);
    _85YR50(maxInd);
    _85YR50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _85YR50[i] = 1.24 + 0.0005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _85YR50[i] = 1.26 + 0.002 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _85YR50[i] = 1.34 + 0.0015 * (i - 85);
        }
    }

    // printf("85YR  %1.2f  %1.2f %1.2f\n",_85YR50[44],_85YR50[85],_85YR50[110]
    // );
    _85YR60(maxInd);
    _85YR60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _85YR60[i] = 1.27 + 0.00025 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _85YR60[i] = 1.28 + 0.0015 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _85YR60[i] = 1.34 + 0.0012 * (i - 85);
        }
    }

    // printf("85YR  %1.2f  %1.2f %1.2f\n",_85YR60[44],_85YR60[85],_85YR60[139]
    // );

    _85YR70(maxInd);
    _85YR70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _85YR70[i] = 1.31 - 0.00025 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _85YR70[i] = 1.30 + 0.0005 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _85YR70[i] = 1.32 + 0.0012 * (i - 85);
        }
    }

    // printf("85YR  %1.2f  %1.2f %1.2f\n",_85YR70[44],_85YR70[85],_85YR70[139]
    // );
    _85YR80(maxInd);
    _85YR80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _85YR80[i] = 1.35 - 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _85YR80[i] = 1.32 + 0.00025 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _85YR80[i] = 1.33 + 0.00125 * (i - 85);
        }
    }

    // printf("85YR  %1.2f  %1.2f %1.2f\n",_85YR80[44],_85YR80[85],_85YR80[139]
    // );
    _85YR90(maxInd2);
    _85YR90.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _85YR90[i] = 1.39 - 0.00125 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _85YR90[i] = 1.34 + 0.00 * (i - 45);
        }
    }

    // printf("85YR  %1.2f  %1.2f\n",_85YR90[44],_85YR90[85]);

    // 7YR
    _7YR30(maxInd2);
    _7YR30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7YR30[i] = 1.06 + 0.0028 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7YR30[i] = 1.17 + 0.0045 * (i - 45);
        }
    }

    // printf("7YR  %1.2f  %1.2f\n",_7YR30[44],_7YR30[66]);
    _7YR40(maxInd2);
    _7YR40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7YR40[i] = 1.10 + 0.0018 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7YR40[i] = 1.17 + 0.0035 * (i - 45);
        }
    }

    // printf("7YR  %1.2f  %1.2f\n",_7YR40[44],_7YR40[89]);
    _7YR50(maxInd2);
    _7YR50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7YR50[i] = 1.14 + 0.00125 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7YR50[i] = 1.19 + 0.002 * (i - 45);
        }
    }

    // printf("7YR  %1.2f  %1.2f\n",_7YR50[44],_7YR50[89] );
    _7YR60(maxInd);
    _7YR60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7YR60[i] = 1.17 + 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7YR60[i] = 1.20 + 0.00175 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7YR60[i] = 1.27 + 0.002 * (i - 85);
        }
    }

    // printf("7YR  %1.2f  %1.2f %1.2f\n",_7YR60[44],_7YR60[84],_7YR60[125] );

    _7YR70(maxInd);
    _7YR70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7YR70[i] = 1.20 + 0.0005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7YR70[i] = 1.22 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7YR70[i] = 1.27 + 0.0015 * (i - 85);
        }
    }

    // printf("7YR  %1.2f  %1.2f %1.2f\n",_7YR70[44],_7YR70[84],_7YR70[125] );
    _7YR80(maxInd3);
    _7YR80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _7YR80[i] = 1.29 - 0.0008 * (i - 5);
        }
    }

    // printf("7YR  %1.2f \n",_7YR80[44] );
    _55YR30(maxInd3);
    _55YR30.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _55YR30[i] = 0.96 + 0.0038 * (i - 5);
        }
    }

    // printf("55YR  %1.2f \n",_55YR30[44] );
    _55YR40(maxInd2);
    _55YR40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _55YR40[i] = 1.01 + 0.0022 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _55YR40[i] = 1.10 + 0.0037 * (i - 45);
        }
    }

    // printf("55YR  %1.2f  %1.2f\n",_55YR40[44],_55YR40[89] );
    _55YR50(maxInd);
    _55YR50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _55YR50[i] = 1.06 + 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _55YR50[i] = 1.12 + 0.00225 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _55YR50[i] = 1.21 + 0.0015 * (i - 85);
        }
    }

    // printf("55YR  %1.2f  %1.2f %1.2f\n",_55YR50[44],_55YR50[84],_55YR50[125]
    // );
    _55YR60(maxInd);
    _55YR60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _55YR60[i] = 1.08 + 0.0012 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _55YR60[i] = 1.13 + 0.0018 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _55YR60[i] = 1.20 + 0.0025 * (i - 85);
        }
    }

    // printf("55YR  %1.2f  %1.2f %1.2f\n",_55YR60[44],_55YR60[84],_55YR60[125]
    // );
    _55YR70(maxInd);
    _55YR70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _55YR70[i] = 1.11 + 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _55YR70[i] = 1.14 + 0.0012 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _55YR70[i] = 1.19 + 0.00225 * (i - 85);
        }
    }

    // printf("55YR  %1.2f  %1.2f %1.2f\n",_55YR70[44],_55YR70[84],_55YR70[125]
    // );
    _55YR80(maxInd);
    _55YR80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _55YR80[i] = 1.16 + 0.00 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _55YR80[i] = 1.16 + 0.00075 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _55YR80[i] = 1.19 + 0.00175 * (i - 85);
        }
    }

    // printf("55YR  %1.2f  %1.2f %1.2f\n",_55YR80[44],_55YR80[84],_55YR80[125]
    // );
    _55YR90(maxInd3);
    _55YR90.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _55YR90[i] = 1.19 - 0.0005 * (i - 5);
        }
    }

    // printf("55YR  %1.2f \n",_55YR90[44] );

    _4YR30(maxInd2);
    _4YR30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _4YR30[i] = 0.87 + 0.0035 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _4YR30[i] = 1.01 + 0.0043 * (i - 45);
        }
    }

    // printf("4YR  %1.2f  %1.2f\n",_4YR30[44],_4YR30[78] );
    _4YR40(maxInd2);
    _4YR40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _4YR40[i] = 0.92 + 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _4YR40[i] = 1.02 + 0.0033 * (i - 45);
        }
    }

    // printf("4YR  %1.2f  %1.2f\n",_4YR40[44],_4YR40[74] );
    _4YR50(maxInd2);
    _4YR50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _4YR50[i] = 0.97 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _4YR50[i] = 1.03 + 0.0025 * (i - 45);
        }
    }

    // printf("4YR  %1.2f  %1.2f\n",_4YR50[44],_4YR50[85] );
    _4YR60(maxInd);
    _4YR60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _4YR60[i] = 0.99 + 0.00125 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _4YR60[i] = 1.04 + 0.002 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _4YR60[i] = 1.12 + 0.003 * (i - 85);
        }
    }

    // printf("4YR  %1.2f  %1.2f %1.2f\n",_4YR60[44],_4YR60[84],_4YR60[125] );
    _4YR70(maxInd);
    _4YR70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _4YR70[i] = 1.02 + 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _4YR70[i] = 1.05 + 0.00175 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _4YR70[i] = 1.12 + 0.002 * (i - 85);
        }
    }

    // printf("4YR  %1.2f  %1.2f %1.2f\n",_4YR70[44],_4YR70[84],_4YR70[125] );
    _4YR80(maxInd3);
    _4YR80.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 50 && i > 5) {
            _4YR80[i] = 1.09 - 0.0002 * (i - 5);
        }
    }

    // printf("4YR  %1.2f \n",_4YR80[41] );

    _25YR30(maxInd2);
    _25YR30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _25YR30[i] = 0.77 + 0.004 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _25YR30[i] = 0.94 + 0.004 * (i - 45);
        }
    }

    // printf("25YR  %1.2f  %1.2f\n",_25YR30[44],_25YR30[74] );
    _25YR40(maxInd2);
    _25YR40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _25YR40[i] = 0.82 + 0.003 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _25YR40[i] = 0.94 + 0.002 * (i - 45);
        }
    }

    // printf("25YR  %1.2f  %1.2f\n",_25YR40[44],_25YR40[84] );
    _25YR50(maxInd2);
    _25YR50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _25YR50[i] = 0.87 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _25YR50[i] = 0.95 + 0.003 * (i - 45);
        }
    }

    // printf("25YR  %1.2f  %1.2f\n",_25YR50[44],_25YR50[84] );
    _25YR60(maxInd2);
    _25YR60.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _25YR60[i] = 0.89 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _25YR60[i] = 0.95 + 0.004 * (i - 45);
        }
    }

    // printf("25YR  %1.2f  %1.2f\n",_25YR60[44],_25YR60[84] );
    _25YR70(maxInd2);
    _25YR70.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _25YR70[i] = 0.92 + 0.001 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _25YR70[i] = 0.96 + 0.003 * (i - 45);
        }
    }

    // printf("25YR  %1.2f  %1.2f\n",_25YR70[44],_25YR70[84] );

    _10R30(maxInd2);
    _10R30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10R30[i] = 0.62 + 0.00225 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10R30[i] = 0.71 + 0.003 * (i - 45);
        }
    }

    // printf("10R  %1.2f  %1.2f\n",_10R30[44],_10R30[84] );
    _10R40(maxInd2);
    _10R40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10R40[i] = 0.66 + 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10R40[i] = 0.76 + 0.0035 * (i - 45);
        }
    }

    // printf("10R  %1.2f  %1.2f\n",_10R40[44],_10R40[84] );
    _10R50(maxInd2);
    _10R50.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10R50[i] = 0.71 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10R50[i] = 0.79 + 0.0043 * (i - 45);
        }
    }

    // printf("10R  %1.2f  %1.2f\n",_10R50[44],_10R50[84] );
    _10R60(maxInd);
    _10R60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10R60[i] = 0.73 + 0.00175 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10R60[i] = 0.80 + 0.0033 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10R60[i] = 0.93 + 0.0018 * (i - 85);
        }
    }

    // printf("10R  %1.2f  %1.2f %1.2f\n",_10R60[44],_10R60[84],_10R60[125] );
    _10R70(maxInd);
    _10R70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10R70[i] = 0.75 + 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10R70[i] = 0.81 + 0.0017 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10R70[i] = 0.88 + 0.0025 * (i - 85);
        }
    }

    // printf("10R  %1.2f  %1.2f %1.2f\n",_10R70[44],_10R70[84],_10R70[125] );

    _9R30(maxInd2);
    _9R30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9R30[i] = 0.57 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9R30[i] = 0.65 + 0.0018 * (i - 45);
        }
    }

    // printf("9R  %1.2f  %1.2f\n",_9R30[44],_9R30[84] );
    _9R40(maxInd2);
    _9R40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9R40[i] = 0.61 + 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9R40[i] = 0.69 + 0.0025 * (i - 45);
        }
    }

    // printf("9R  %1.2f  %1.2f\n",_9R40[44],_9R40[84] );
    _9R50(maxInd);
    _9R50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _9R50[i] = 0.66 + 0.00175 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _9R50[i] = 0.73 + 0.0025 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _9R50[i] = 0.83 + 0.0035 * (i - 85);
        }
    }

    // printf("9R  %1.2f  %1.2f %1.2f\n",_9R50[44],_9R50[84],_9R50[125] );
    _9R60(maxInd);
    _9R60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _9R60[i] = 0.68 + 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _9R60[i] = 0.74 + 0.0022 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _9R60[i] = 0.93 + 0.0022 * (i - 85);
        }
    }

    // printf("9R  %1.2f  %1.2f %1.2f\n",_9R60[44],_9R60[84],_9R60[125] );
    _9R70(maxInd2);
    _9R70.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _9R70[i] = 0.70 + 0.0012 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _9R70[i] = 0.75 + 0.0013 * (i - 45);
        }
    }

    // printf("9R  %1.2f  %1.2f\n",_9R70[44],_9R70[84] );

    _7R30(maxInd2);
    _7R30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7R30[i] = 0.48 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7R30[i] = 0.54 - 0.0005 * (i - 45);
        }
    }

    // printf("7R  %1.2f  %1.2f\n",_7R30[44],_7R30[84] );
    _7R40(maxInd2);
    _7R40.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7R40[i] = 0.51 + 0.0015 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7R40[i] = 0.57 + 0.0005 * (i - 45);
        }
    }

    // printf("7R  %1.2f  %1.2f\n",_7R40[44],_7R40[84] );
    _7R50(maxInd);
    _7R50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7R50[i] = 0.54 + 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7R50[i] = 0.60 + 0.0005 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7R50[i] = 0.62 + 0.0025 * (i - 85);
        }
    }

    // printf("7R  %1.2f  %1.2f %1.2f\n",_7R50[44],_7R50[84],_7R50[125] );
    _7R60(maxInd);
    _7R60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7R60[i] = 0.58 + 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7R60[i] = 0.61 + 0.00075 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7R60[i] = 0.64 + 0.001 * (i - 85);
        }
    }

    // printf("7R  %1.2f  %1.2f %1.2f\n",_7R60[44],_7R60[84],_7R60[107] );
    _7R70(maxInd2);
    _7R70.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _7R70[i] = 0.59 + 0.00075 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _7R70[i] = 0.62 + 0.00075 * (i - 45);
        }
    }

    // printf("7R  %1.2f  %1.2f\n",_7R70[44],_7R70[84] );

    // 5R 1 2 3

    // 5R
    _5R10(maxInd2);
    _5R10.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _5R10[i] = 0.10 - 0.0018 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5R10[i] = 0.035 - 0.003 * (i - 45);
        }
    }

    // printf("5R  %1.2f  %1.2f\n",_5R10[44],_5R10[51] );
    _5R20(maxInd2);
    _5R20.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _5R20[i] = 0.26 - 0.00075 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5R20[i] = 0.023 - 0.0002 * (i - 45);
        }
    }

    // printf("5R  %1.2f  %1.2f\n",_5R20[44],_5R20[70] );
    _5R30(maxInd2);
    _5R30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _5R30[i] = 0.39 + 0.00075 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5R30[i] = 0.42 - 0.0007 * (i - 45);
        }
    }

    // printf("5R  %1.2f  %1.2f\n",_5R30[44],_5R30[85] );

    // 25R
    _25R10(maxInd3);
    _25R10.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 45 && i > 5) {
            _25R10[i] = -0.03 - 0.002 * (i - 5);
        }
    }

    // printf("25R  %1.2f \n",_25R10[44]);
    _25R20(maxInd2);
    _25R20.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _25R20[i] = 0.13 - 0.0012 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _25R20[i] = 0.08 - 0.002 * (i - 45);
        }
    }

    // printf("25R  %1.2f  %1.2f\n",_25R20[44],_25R20[69] );
    // 25R30: 0.28, 0.26, 0.22
    _25R30(maxInd2);
    _25R30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _25R30[i] = 0.28 - 0.0005 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _25R30[i] = 0.26 - 0.0009 * (i - 45);
        }
    }

    // printf("25R  %1.2f  %1.2f\n",_25R30[44],_25R30[85] );

    _10RP10(maxInd3);
    _10RP10.clear();

    for (int i = 0; i < maxInd3; i++) {
        if (i < 45 && i > 5) {
            _10RP10[i] = -0.16 - 0.0017 * (i - 5);
        }
    }

    // printf("10RP  %1.2f \n",_10RP10[44]);
    _10RP20(maxInd2);
    _10RP20.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10RP20[i] = 0.0 - 0.0018 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10RP20[i] = -0.07 - 0.0012 * (i - 45);
        }
    }

    // printf("10RP  %1.2f  %1.2f\n",_10RP20[44],_10RP20[69] );
    _10RP30(maxInd2);
    _10RP30.clear();

    for (int i = 0; i < maxInd2; i++) {
        if (i < 45 && i > 5) {
            _10RP30[i] = 0.15 - 0.001 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _10RP30[i] = 0.11 - 0.0012 * (i - 45);
        }
    }

    // printf("10RP  %1.2f  %1.2f\n",_10RP30[44],_10RP30[85] );

    // 7G
    _7G30(maxInd);
    _7G30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7G30[i] = 2.90 + 0.0027 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7G30[i] = 3.01 + 0.0005 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7G30[i] = 3.03 + 0.00075 * (i - 85);
        }
    }

    // printf("7G  %1.2f  %1.2f %1.2f\n",_7G30[44],_7G30[84],_7G30[125] );
    _7G40(maxInd);
    _7G40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7G40[i] = 2.89 + 0.00125 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7G40[i] = 2.94 + 0.0015 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7G40[i] = 3.0 + 0.001 * (i - 85);
        }
    }

    // printf("7G  %1.2f  %1.2f %1.2f\n",_7G40[44],_7G40[84],_7G40[125] );
    _7G50(maxInd);
    _7G50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7G50[i] = 2.87 + 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7G50[i] = 2.93 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7G50[i] = 2.98 + 0.001 * (i - 85);
        }
    }

    // printf("7G  %1.2f  %1.2f %1.2f\n",_7G50[44],_7G50[84],_7G50[125] );
    _7G60(maxInd);
    _7G60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7G60[i] = 2.86 + 0.00125 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7G60[i] = 2.91 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7G60[i] = 2.96 + 0.00075 * (i - 85);
        }
    }

    // printf("7G  %1.2f  %1.2f %1.2f\n",_7G60[44],_7G60[84],_7G60[125] );
    _7G70(maxInd);
    _7G70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7G70[i] = 2.85 + 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7G70[i] = 2.89 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7G70[i] = 2.94 + 0.00075 * (i - 85);
        }
    }

    // printf("7G  %1.2f  %1.2f %1.2f\n",_7G70[44],_7G70[84],_7G70[125] );
    _7G80(maxInd);
    _7G80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _7G80[i] = 2.84 + 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _7G80[i] = 2.88 + 0.001 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _7G80[i] = 2.92 + 0.001 * (i - 85);
        }
    }

    // printf("7G  %1.2f  %1.2f %1.2f\n",_7G80[44],_7G80[84],_7G80[125] );

    // 5G
    _5G30(maxInd);
    _5G30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5G30[i] = 2.82 + 0.00175 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5G30[i] = 2.89 + 0.0018 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5G30[i] = 2.96 + 0.0012 * (i - 85);
        }
    }

    // printf("5G  %1.2f  %1.2f %1.2f\n",_5G30[44],_5G30[84],_5G30[125] );
    _5G40(maxInd);
    _5G40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5G40[i] = 2.80 + 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5G40[i] = 2.86 + 0.00175 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5G40[i] = 2.93 + 0.00125 * (i - 85);
        }
    }

    // printf("5G  %1.2f  %1.2f %1.2f\n",_5G40[44],_5G40[84],_5G40[125] );
    _5G50(maxInd);
    _5G50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5G50[i] = 2.79 + 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5G50[i] = 2.84 + 0.0015 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5G50[i] = 2.90 + 0.0015 * (i - 85);
        }
    }

    // printf("5G  %1.2f  %1.2f %1.2f\n",_5G50[44],_5G50[84],_5G50[125] );
    _5G60(maxInd);
    _5G60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5G60[i] = 2.78 + 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5G60[i] = 2.82 + 0.00175 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5G60[i] = 2.89 + 0.001 * (i - 85);
        }
    }

    // printf("5G  %1.2f  %1.2f %1.2f\n",_5G60[44],_5G60[84],_5G60[125] );
    _5G70(maxInd);
    _5G70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5G70[i] = 2.77 + 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5G70[i] = 2.81 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5G70[i] = 2.86 + 0.00125 * (i - 85);
        }
    }

    // printf("5G  %1.2f  %1.2f %1.2f\n",_5G70[44],_5G70[84],_5G70[125] );
    _5G80(maxInd);
    _5G80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5G80[i] = 2.76 + 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5G80[i] = 2.8 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5G80[i] = 2.85 + 0.00125 * (i - 85);
        }
    }

    // printf("5G  %1.2f  %1.2f %1.2f\n",_5G80[44],_5G80[84],_5G80[125] );

    // 25G
    _25G30(maxInd);
    _25G30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _25G30[i] = 2.68 + 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _25G30[i] = 2.74 + 0.0018 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _25G30[i] = 2.81 + 0.002 * (i - 85);
        }
    }

    // printf("25G  %1.2f  %1.2f %1.2f\n",_25G30[44],_25G30[84],_25G30[125] );
    _25G40(maxInd);
    _25G40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _25G40[i] = 2.68 + 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _25G40[i] = 2.71 + 0.0015 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _25G40[i] = 2.77 + 0.00125 * (i - 85);
        }
    }

    // printf("25G  %1.2f  %1.2f %1.2f\n",_25G40[44],_25G40[84],_25G40[125] );
    _25G50(maxInd);
    _25G50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _25G50[i] = 2.65 + 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _25G50[i] = 2.68 + 0.00125 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _25G50[i] = 2.73 + 0.00125 * (i - 85);
        }
    }

    // printf("25G  %1.2f  %1.2f %1.2f\n",_25G50[44],_25G50[84],_25G50[125] );
    _25G60(maxInd);
    _25G60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _25G60[i] = 2.64 + 0.0005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _25G60[i] = 2.66 + 0.001 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _25G60[i] = 2.70 + 0.001 * (i - 85);
        }
    }

    // printf("25G  %1.2f  %1.2f %1.2f\n",_25G60[44],_25G60[84],_25G60[125] );
    _25G70(maxInd);
    _25G70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _25G70[i] = 2.64 + 0.00 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _25G70[i] = 2.64 + 0.00075 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _25G70[i] = 2.67 + 0.001 * (i - 85);
        }
    }

    // printf("25G  %1.2f  %1.2f %1.2f\n",_25G70[44],_25G70[84],_25G70[125] );
    _25G80(maxInd);
    _25G80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _25G80[i] = 2.63 + 0.00 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _25G80[i] = 2.63 + 0.0005 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _25G80[i] = 2.65 + 0.0005 * (i - 85);
        }
    }

    // printf("25G  %1.2f  %1.2f %1.2f\n",_25G80[44],_25G80[84],_25G80[125] );

    // 1G
    _1G30(maxInd);
    _1G30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1G30[i] = 2.58 + 0.00025 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1G30[i] = 2.59 + 0.001 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1G30[i] = 2.63 + 0.00125 * (i - 85);
        }
    }

    // printf("1G  %1.2f  %1.2f %1.2f\n",_1G30[44],_1G30[84],_1G30[125] );
    _1G40(maxInd);
    _1G40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1G40[i] = 2.56 - 0.00025 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1G40[i] = 2.55 + 0.0005 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1G40[i] = 2.57 + 0.0005 * (i - 85);
        }
    }

    // printf("1G  %1.2f  %1.2f %1.2f\n",_1G40[44],_1G40[84],_1G40[125] );
    _1G50(maxInd);
    _1G50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1G50[i] = 2.55 - 0.00025 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1G50[i] = 2.54 + 0.00025 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1G50[i] = 2.55 + 0.0005 * (i - 85);
        }
    }

    // printf("1G  %1.2f  %1.2f %1.2f\n",_1G50[44],_1G50[84],_1G50[125] );
    _1G60(maxInd);
    _1G60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1G60[i] = 2.54 - 0.0005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1G60[i] = 2.52 + 0.00025 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1G60[i] = 2.53 + 0.00025 * (i - 85);
        }
    }

    // printf("1G  %1.2f  %1.2f %1.2f\n",_1G60[44],_1G60[84],_1G60[125] );
    _1G70(maxInd);
    _1G70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1G70[i] = 2.53 - 0.0005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1G70[i] = 2.51 + 0.0 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1G70[i] = 2.51 + 0.00025 * (i - 85);
        }
    }

    // printf("1G  %1.2f  %1.2f %1.2f\n",_1G70[44],_1G70[84],_1G70[125] );
    _1G80(maxInd);
    _1G80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _1G80[i] = 2.52 - 0.0005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _1G80[i] = 2.50 + 0.00 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _1G80[i] = 2.50 + 0.00 * (i - 85);
        }
    }

    // printf("1G  %1.2f  %1.2f %1.2f\n",_1G80[44],_1G80[84],_1G80[125] );

    // 10GY
    _10GY30(maxInd);
    _10GY30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10GY30[i] = 2.52 - 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10GY30[i] = 2.48 - 0.002 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10GY30[i] = 2.40 + 0.0025 * (i - 85);
        }
    }

    // printf("10GY  %1.2f  %1.2f %1.2f\n",_10GY30[44],_10GY30[84],_10GY30[125]
    // );
    _10GY40(maxInd);
    _10GY40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10GY40[i] = 2.48 - 0.0005 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10GY40[i] = 2.46 - 0.0005 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10GY40[i] = 2.44 - 0.0015 * (i - 85);
        }
    }

    // printf("10GY  %1.2f  %1.2f %1.2f\n",_10GY40[44],_10GY40[84],_10GY40[125]
    // );
    _10GY50(maxInd);
    _10GY50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10GY50[i] = 2.48 - 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10GY50[i] = 2.45 - 0.00075 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10GY50[i] = 2.42 - 0.00175 * (i - 85);
        }
    }

    // printf("10GY  %1.2f  %1.2f %1.2f\n",_10GY50[44],_10GY50[84],_10GY50[125]
    // );
    _10GY60(maxInd);
    _10GY60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10GY60[i] = 2.47 - 0.00125 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10GY60[i] = 2.42 - 0.00025 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10GY60[i] = 2.41 - 0.0005 * (i - 85);
        }
    }

    // printf("10GY  %1.2f  %1.2f %1.2f\n",_10GY60[44],_10GY60[84],_10GY60[125]
    // );
    _10GY70(maxInd);
    _10GY70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10GY70[i] = 2.46 - 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10GY70[i] = 2.42 + 0.0 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10GY70[i] = 2.42 - 0.001 * (i - 85);
        }
    }

    // printf("10GY %1.2f  %1.2f %1.2f\n",_10GY70[44],_10GY70[84],_10GY70[125]
    // );
    _10GY80(maxInd);
    _10GY80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _10GY80[i] = 2.45 - 0.00075 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _10GY80[i] = 2.42 - 0.0005 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _10GY80[i] = 2.40 - 0.0005 * (i - 85);
        }
    }

    // printf("10GY  %1.2f  %1.2f %1.2f\n",_10GY80[44],_10GY80[84],_10GY80[125]
    // );

    // 75GY
    _75GY30(maxInd2);
    _75GY30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75GY30[i] = 2.36 - 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _75GY30[i] = 2.26 - 0.00175 * (i - 45);
        }
    }

    // printf("75GY  %1.2f  %1.2f\n",_75GY30[44],_75GY30[84] );
    _75GY40(maxInd2);
    _75GY40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75GY40[i] = 2.34 - 0.00175 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _75GY40[i] = 2.27 - 0.00225 * (i - 45);
        }
    }

    // printf("75GY  %1.2f  %1.2f \n",_75GY40[44],_75GY40[84] );
    _75GY50(maxInd);
    _75GY50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75GY50[i] = 2.32 - 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _75GY50[i] = 2.26 - 0.00175 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _75GY50[i] = 2.19 - 0.00325 * (i - 85);
        }
    }

    // printf("75GY  %1.2f  %1.2f %1.2f
    // %1.2f\n",_75GY50[44],_75GY50[84],_75GY50[125],_75GY50[139] );
    _75GY60(maxInd);
    _75GY60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75GY60[i] = 2.30 - 0.00125 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _75GY60[i] = 2.25 - 0.001 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _75GY60[i] = 2.21 - 0.0027 * (i - 85);
        }
    }

    // printf("75GY  %1.2f  %1.2f %1.2f\n",_75GY60[44],_75GY60[84],_75GY60[125]
    // );
    _75GY70(maxInd);
    _75GY70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75GY70[i] = 2.29 - 0.00125 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _75GY70[i] = 2.24 - 0.0015 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _75GY70[i] = 2.18 - 0.00175 * (i - 85);
        }
    }

    // printf("75GY %1.2f  %1.2f %1.2f\n",_75GY70[44],_75GY70[84],_75GY70[125]
    // );
    _75GY80(maxInd);
    _75GY80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _75GY80[i] = 2.27 - 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _75GY80[i] = 2.23 - 0.001 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _75GY80[i] = 2.19 - 0.00175 * (i - 85);
        }
    }

    // printf("75GY  %1.2f  %1.2f %1.2f\n",_75GY80[44],_75GY80[84],_75GY80[125]
    // );

    // 55GY
    _5GY30(maxInd2);
    _5GY30.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5GY30[i] = 2.16 - 0.002 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5GY30[i] = 2.07 - 0.0025 * (i - 45);
        }
    }

    // printf("5GY  %1.2f  %1.2f\n",_5GY30[44],_5GY30[84] );

    // 5GY4: 2.14,2.04, 1.96, 1.91 //95

    _5GY40(maxInd2);
    _5GY40.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5GY40[i] = 2.14 - 0.0025 * (i - 5);
        } else if (i < 90 && i >= 45) {
            _5GY40[i] = 2.04 - 0.003 * (i - 45);
        }
    }

    // printf("5GY  %1.2f  %1.2f \n",_5GY40[44],_5GY40[84] );
    _5GY50(maxInd);
    _5GY50.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5GY50[i] = 2.13 - 0.00175 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5GY50[i] = 2.06 - 0.002 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5GY50[i] = 1.98 - 0.00225 * (i - 85);
        }
    }

    // printf("5GY  %1.2f  %1.2f %1.2f\n",_5GY50[44],_5GY50[84],_5GY50[125] );
    _5GY60(maxInd);
    _5GY60.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5GY60[i] = 2.11 - 0.0015 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5GY60[i] = 2.05 - 0.002 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5GY60[i] = 1.97 - 0.00275 * (i - 85);
        }
    }

    // printf("5GY  %1.2f  %1.2f %1.2f\n",_5GY60[44],_5GY60[84],_5GY60[125] );
    _5GY70(maxInd);
    _5GY70.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5GY70[i] = 2.09 - 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5GY70[i] = 2.05 - 0.00175 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5GY70[i] = 1.98 - 0.002 * (i - 85);
        }
    }

    // printf("5GY %1.2f  %1.2f %1.2f\n",_5GY70[44],_5GY70[84],_5GY70[125] );
    _5GY80(maxInd);
    _5GY80.clear();

    for (int i = 0; i < maxInd; i++) {
        if (i < 45 && i > 5) {
            _5GY80[i] = 2.07 - 0.001 * (i - 5);
        } else if (i < 85 && i >= 45) {
            _5GY80[i] = 2.03 - 0.00075 * (i - 45);
        } else if (i < 140 && i >= 85) {
            _5GY80[i] = 2.0 - 0.002 * (i - 85);
        }
    }

    // printf("5GY  %1.2f  %1.2f %1.2f\n",_5GY80[44],_5GY80[84],_5GY80[125] );

#ifdef _DEBUG
    t2e.set();

    if (settings->verbose > 1) {
        printf("Lutf Munsell  %d usec\n", t2e.etime(t1e));
    }

#endif
}

}} // namespace art::engine
