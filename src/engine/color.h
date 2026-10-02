/* -*- C++ -*-
 *
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
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

#pragma once

#include <array>
#include <glibmm.h>

#include "LUT.h"
#include "iccmatrices.h"
#include "labimage.h"
#include "lcms2.h"
#include "rt_math.h"
#include "sleef.h"

namespace art { namespace engine {

typedef std::array<double, 7> LMCSToneCurveParams;

class Color {
private:
    static double hue2rgb(double p, double q, double t);
#ifdef ART_SIMD
    static vfloat hue2rgb(vfloat p, vfloat q, vfloat t);
#endif

    static float computeXYZ2Lab(float f);
    static float computeXYZ2LabY(float f);

    static LUTf jzazbz_pq_;
    static LUTf jzazbz_pq_inv_;

public:

    /* Upper bound of the jzazbz_pq_inv_ table's domain.
     *
     * PQ() maps [0,1] -- the whole normal XYZ range -- onto [0, 0.0397], so
     * jzazbz2xyz only ever feeds PQ_inv values in that band.  Indexing the
     * table over [0,1] therefore used just 2603 of its 65536 entries; it is
     * indexed over [0, jzazbzPQInvMax()] instead, which is the same table size
     * at ~25x the resolution.  Inputs above the bound (XYZ beyond 1.0, i.e.
     * specular highlights) fall back to evaluating PQ_inv directly. */
    static float jzazbzPQInvMax() { return 0.04f; }


    // Wikipedia sRGB: Unlike most other RGB color spaces, the sRGB gamma cannot
    // be expressed as a single numerical value. The overall gamma is
    // approximately 2.2, consisting of a linear (gamma 1.0) section near black,
    // and a non-linear section elsewhere involving a 2.4 exponent and a gamma
    // (slope of log output versus log input) changing from 1.0 through
    // about 2.3.
    constexpr static double sRGBGamma = 2.2;
    constexpr static double sRGBGammaCurve = 2.4;

    constexpr static double eps = 216.0 / 24389.0;   // 0.008856
    constexpr static double eps_max = MAXVALF * eps; // 580.40756;
    constexpr static double kappa = 24389.0 / 27.0;  // 903.29630;
    constexpr static double kappaInv = 27.0 / 24389.0;
    constexpr static double epsilonExpInv3 = 6.0 / 29.0;

    constexpr static float kappaInvf = kappaInv;
    constexpr static float epsilonExpInv3f = epsilonExpInv3;

    constexpr static float D50x = 0.9642f; // 0.96422;
    constexpr static float D50z = 0.8249f; // 0.82521;
    constexpr static double u0 = 4.0 * D50x / (D50x + 15 + 3 * D50z);
    constexpr static double v0 = 9.0 / (D50x + 15 + 3 * D50z);
    constexpr static double epskap = 8.0;

    constexpr static float c1By116 = 1.0 / 116.0;
    constexpr static float c16By116 = 16.0 / 116.0;


    static LUTf cachef;
    static LUTf cachefy;
    static LUTf gamma2curve;

    // look-up tables for the standard srgb gamma and its inverse (filled by
    // init())
    static LUTf igammatab_srgb;
    static LUTf igammatab_srgb1;
    static LUTf gammatab_srgb;
    static LUTf gammatab_srgb1;

    static LUTf denoiseGammaTab;
    static LUTf denoiseIGammaTab;

    static LUTf igammatab_24_17;
    static LUTf gammatab_24_17a;

    // look-up tables for the simple exponential gamma
    static LUTf gammatab;
    static LUTuc gammatabThumb; // for thumbnails

    static void init();

    /**
     * @brief Extract luminance "sRGB" from red/green/blue values
     * The range of the r, g and b channel has no importance ([0 ; 1] or [0 ;
     * 65535]...) ; r,g,b can be negatives or > max, but must be in "sRGB"
     * @param r red channel
     * @param g green channel
     * @param b blue channel
     * @return luminance value
     */
    // xyz_sRGBD65 : conversion matrix from XYZ to sRGB for D65 illuminant: we
    // use diagonal values
    static float rgbLuminance(float r, float g, float b)
    {
        // WArning: The sum of xyz_sRGBd65[1][] is > 1.0 (i.e. 1.0000001), so we
        // use our own adapted values) 0.2126729,  0.7151521,  0.0721750
        return r * 0.2126729f + g * 0.7151521f + b * 0.0721750f;
    }
    static double rgbLuminance(double r, double g, double b)
    {
        return r * 0.2126729 + g * 0.7151521 + b * 0.0721750;
    }

    template <class T>
    static float rgbLuminance(float r, float g, float b,
                              const T workingspace[3][3])
    {
        return r * workingspace[1][0] + g * workingspace[1][1] +
               b * workingspace[1][2];
    }

#ifdef ART_SIMD
    static vfloat rgbLuminance(vfloat r, vfloat g, vfloat b,
                               const vfloat workingspace[3][3])
    {
        return r * workingspace[1][0] + g * workingspace[1][1] +
               b * workingspace[1][2];
    }
#endif

    /**
     * @brief Convert red/green/blue to L*a*b
     * @brief Convert red/green/blue to hue/saturation/luminance
     * @param profile output profile name
     * @param profileW working profile name
     * @param r red channel [0 ; 1]
     * @param g green channel [0 ; 1]
     * @param b blue channel [0 ; 1]
     * @param L Lab L channel [0 ; 1] (return value)
     * @param a Lab a channel [0 ; 1] (return value)
     * @param b Lab b channel [0; 1] (return value)
     * @param workingSpace true: compute the Lab value using the Working color
     * space ; false: use the Output color space
     */
    // do not use this function in a loop. It really eats processing time caused
    // by Glib::ustring comparisons
    static void rgb2lab01(const Glib::ustring &profile,
                          const Glib::ustring &profileW, float r, float g,
                          float b, float &LAB_l, float &LAB_a, float &LAB_b,
                          bool workingSpace);

    static void lab2lch01(float L, float a, float b, float &l, float &c,
                          float &h);

    /**
     * @brief Convert red/green/blue to hue/saturation/luminance
     * @param r red channel [0 ; 65535]
     * @param g green channel [0 ; 65535]
     * @param b blue channel [0 ; 65535]
     * @param h hue channel [0 ; 1] (return value)
     * @param s saturation channel [0 ; 1] (return value)
     * @param l luminance channel [0; 1] (return value)
     */
    static void rgb2hsl(float r, float g, float b, float &h, float &s,
                        float &l);


    static inline void rgb2hslfloat(float r, float g, float b, float &h,
                                    float &s, float &l)
    {

        float m = min(r, g, b);
        float M = max(r, g, b);
        float C = M - m;

        l = (M + m) * 7.6295109e-6f; // (0.5f / 65535.f)

        if (C < 0.65535f) { // 0.00001f * 65535.f
            h = 0.f;
            s = 0.f;
        } else {

            if (l <= 0.5f) {
                s = C / (M + m);
            } else {
                s = C / (131070.f - (M + m)); // 131070.f = 2.f * 65535.f
            }

            if (r == M) {
                h = (g - b);
            } else if (g == M) {
                h = (2.f * C) + (b - r);
            } else {
                h = (4.f * C) + (r - g);
            }

            h /= (6.f * C);

            if (h < 0.f) {
                h += 1.f;
            }
        }
    }

#ifdef ART_SIMD
    static void rgb2hsl(vfloat r, vfloat g, vfloat b, vfloat &h, vfloat &s,
                        vfloat &l);
#endif

    /**
     * @brief Convert hue/saturation/luminance in red/green/blue
     * @param h hue channel [0 ; 1]
     * @param s saturation channel [0 ; 1]
     * @param l luminance channel [0 ; 1]
     * @param r red channel [0 ; 65535] (return value)
     * @param g green channel [0 ; 65535] (return value)
     * @param b blue channel [0 ; 65535] (return value)
     */
    static void hsl2rgb(float h, float s, float l, float &r, float &g,
                        float &b);


#ifdef ART_SIMD
    static void hsl2rgb(vfloat h, vfloat s, vfloat l, vfloat &r, vfloat &g,
                        vfloat &b);
#endif


    /**
     * @brief Convert red green blue to hue saturation value
     * @param r red channel [0 ; 65535]
     * @param g green channel [0 ; 65535]
     * @param b blue channel [0 ; 65535]
     * @param h hue channel [0 ; 1] (return value)
     * @param s saturation channel [0 ; 1] (return value)
     * @param v value channel [0 ; 1] (return value)
     */
    static void rgb2hsv(float r, float g, float b, float &h, float &s,
                        float &v);


    static inline float
    rgb2s(float r, float g,
          float b) // fast version if only saturation is needed
    {
        float var_Min = min(r, g, b);
        float var_Max = max(r, g, b);
        float del_Max = var_Max - var_Min;

        return del_Max / (var_Max == 0.f ? 1.f : var_Max);
    }

    static inline bool rgb2hsvdcp(float r, float g, float b, float &h, float &s,
                                  float &v)
    {

        float var_Min = min(r, g, b);

        if (var_Min < 0.f) {
            return false;
        } else {
            float var_Max = max(r, g, b);
            float del_Max = var_Max - var_Min;
            v = var_Max / 65535.f;

            if (fabsf(del_Max) < 0.00001f) {
                h = 0.f;
                s = 0.f;
            } else {
                s = del_Max / var_Max;

                if (r == var_Max) {
                    h = (g - b) / del_Max;
                } else if (g == var_Max) {
                    h = 2.f + (b - r) / del_Max;
                } else { /*if ( b == var_Max ) */
                    h = 4.f + (r - g) / del_Max;
                }

                if (h < 0.f) {
                    h += 6.f;
                } else if (h > 6.f) {
                    h -= 6.f;
                }
            }

            return true;
        }
    }

    static inline void rgb2hsvtc(float r, float g, float b, float &h, float &s,
                                 float &v)
    {
        const float var_Min = min(r, g, b);
        const float var_Max = max(r, g, b);
        const float del_Max = var_Max - var_Min;

        v = var_Max / 65535.f;

        if (del_Max < 0.00001f) {
            h = 0.f;
            s = 0.f;
        } else {
            s = del_Max / var_Max;

            if (r == var_Max) {
                h = (g < b ? 6.f : 0.f) + (g - b) / del_Max;
            } else if (g == var_Max) {
                h = 2.f + (b - r) / del_Max;
            } else { /*if ( b == var_Max ) */
                h = 4.f + (r - g) / del_Max;
            }
        }
    }

    /**
     * @brief Convert hue saturation value in red green blue
     * @param h hue channel [0 ; 1]
     * @param s saturation channel [0 ; 1]
     * @param v value channel [0 ; 1]
     * @param r red channel [0 ; 65535] (return value)
     * @param g green channel [0 ; 65535] (return value)
     * @param b blue channel [0 ; 65535] (return value)
     */
    static void hsv2rgb(float h, float s, float v, float &r, float &g,
                        float &b);

    static inline void hsv2rgbdcp(float h, float s, float v, float &r, float &g,
                                  float &b)
    {
        // special version for dcp which saves 1 division (in caller) and six
        // multiplications (inside this function)
        const int sector =
            h; // sector 0 to 5, floor() is very slow, and h is always > 0
        const float f = h - sector; // fractional part of h

        v *= 65535.f;
        const float vs = v * s;
        const float p = v - vs;
        const float q = v - f * vs;
        const float t = p + v - q;

        switch (sector) {
        case 1:
            r = q;
            g = v;
            b = p;
            break;

        case 2:
            r = p;
            g = v;
            b = t;
            break;

        case 3:
            r = p;
            g = q;
            b = v;
            break;

        case 4:
            r = t;
            g = p;
            b = v;
            break;

        case 5:
            r = v;
            g = p;
            b = q;
            break;

        default:
            r = v;
            g = t;
            b = p;
        }
    }

    static void hsv2rgb(float h, float s, float v, int &r, int &g, int &b);

    /**
     * @brief Convert hue saturation value in red green blue
     * @param h hue channel [0 ; 1]
     * @param s saturation channel [0 ; 1]
     * @param v value channel [0 ; 1]
     * @param r red channel [0 ; 1] (return value)
     * @param g green channel [0 ; 1] (return value)
     * @param b blue channel [0 ; 1] (return value)
     */
    static void hsv2rgb01(float h, float s, float v, float &r, float &g,
                          float &b);

    /**
     * @brief Convert xyz to red/green/blue
     * Color space : sRGB   - illuminant D50 - use matrix sRGB_xyz[]
     * @param x X coordinate [0 ; 1] or [0 ; 65535]
     * @param y Y coordinate [0 ; 1] or [0 ; 65535]
     * @param z Z coordinate [0 ; 1] or [0 ; 65535]
     * @param r red channel [same range than xyz channel] (return value)
     * @param g green channel [same range than xyz channel] (return value)
     * @param b blue channel [same range than xyz channel] (return value)
     */
    static void xyz2srgb(float x, float y, float z, float &r, float &g,
                         float &b);

    /**
     * @brief Convert xyz to red/green/blue
     * Color space : Prophoto   - illuminant D50 -  use the Prophoto_xyz[]
     * matrix
     * @param x X coordinate [0 ; 1] or [0 ; 65535]
     * @param y Y coordinate [0 ; 1] or [0 ; 65535]
     * @param z Z coordinate [0 ; 1] or [0 ; 65535]
     * @param r red channel [same range than xyz channel] (return value)
     * @param g green channel [same range than xyz channel] (return value)
     * @param b blue channel [same range than xyz channel] (return value)
     */
    static void xyz2Prophoto(float x, float y, float z, float &r, float &g,
                             float &b);

    /**
     * @brief Convert rgb in xyz
     * Color space : Prophoto   - illuminant D50 - use matrix xyz_prophoto[]
     * @param r red channel [0 ; 1] or [0 ; 65535] (return value)
     * @param g green channel [0 ; 1] or [0 ; 65535] (return value)
     * @param b blue channel [0 ; 1] or [0 ; 65535] (return value)
     * @param x X coordinate [same range than xyz channel]
     * @param y Y coordinate [same range than xyz channel]
     * @param z Z coordinate [same range than xyz channel]
     */
    static void Prophotoxyz(float r, float g, float b, float &x, float &y,
                            float &z);

    /**
     * @brief Convert xyz in rgb
     * Color space : undefined - use adhoc matrix: rgb_xyz[3][3] (iccmatrice.h)
     * in function of working space
     * @param x X coordinate [0 ; 1] or [0 ; 65535]
     * @param y Y coordinate [0 ; 1] or [0 ; 65535]
     * @param z Z coordinate [0 ; 1] or [0 ; 65535]
     * @param r red channel [same range than xyz channel] (return value)
     * @param g green channel [same range than xyz channel] (return value)
     * @param b blue channel [same range than xyz channel] (return value)
     * @param rgb_xyz[3][3] transformation matrix to use for the conversion
     */
    static void xyz2rgb(float x, float y, float z, float &r, float &g, float &b,
                        const double rgb_xyz[3][3]);
    static void xyz2rgb(float x, float y, float z, float &r, float &g, float &b,
                        const float rgb_xyz[3][3]);
#ifdef ART_SIMD
    static void xyz2rgb(vfloat x, vfloat y, vfloat z, vfloat &r, vfloat &g,
                        vfloat &b, const vfloat rgb_xyz[3][3]);
#endif

    /**
     * @brief Convert rgb in xyz
     * Color space : undefined - use adhoc matrix : xyz_rgb[3][3] (iccmatrice.h)
     * in function of working space
     * @param r red channel [0 ; 1] or [0 ; 65535]
     * @param g green channel [0 ; 1] or [0 ; 65535]
     * @param b blue channel [0 ; 1] or [0 ; 65535]
     * @param x X coordinate [same range than rgb channel] (return value)
     * @param y Y coordinate [same range than rgb channel] (return value)
     * @param z Z coordinate [same range than rgb channel] (return value)
     * @param xyz_rgb[3][3] transformation matrix to use for the conversion
     */
    static void rgbxyz(float r, float g, float b, float &x, float &y, float &z,
                       const double xyz_rgb[3][3]);
    static void rgbxyz(float r, float g, float b, float &x, float &y, float &z,
                       const float xyz_rgb[3][3]);
#ifdef ART_SIMD
    static void rgbxyz(vfloat r, vfloat g, vfloat b, vfloat &x, vfloat &y,
                       vfloat &z, const vfloat xyz_rgb[3][3]);
#endif

    /**
     * @brief Convert Lab in xyz
     * @param L L channel [0 ; 32768] ; L can be negative rarely or superior
     * 32768
     * @param a channel [-42000 ; +42000] ; can be more than 42000
     * @param b channel [-42000 ; +42000] ; can be more than 42000
     * @param x X coordinate [0 ; 65535] ; can be negative! (return value)
     * @param y Y coordinate [0 ; 65535] ; can be negative! (return value)
     * @param z Z coordinate [0 ; 65535] ; can be negative! (return value)
     */
    static void Lab2XYZ(float L, float a, float b, float &x, float &y,
                        float &z);

#ifdef ART_SIMD
    static void Lab2XYZ(vfloat L, vfloat a, vfloat b, vfloat &x, vfloat &y,
                        vfloat &z);
#endif // ART_SIMD

    /**
     * @brief Convert xyz in Lab
     * @param x X coordinate [0 ; 65535] ; can be negative or superior to 65535
     * @param y Y coordinate [0 ; 65535] ; can be negative or superior to 65535
     * @param z Z coordinate [0 ; 65535] ; can be negative or superior to 65535
     * @param L L channel [0 ; 32768] ; L can be negative rarely or superior
     * 32768 (return value)
     * @param a channel [-42000 ; +42000] ; can be more than 42000 (return
     * value)
     * @param b channel [-42000 ; +42000] ; can be more than 42000 (return
     * value)
     */
    static void XYZ2Lab(float x, float y, float z, float &L, float &a,
                        float &b);
#ifdef ART_SIMD
    static void XYZ2Lab(vfloat x, vfloat y, vfloat z, vfloat &L, vfloat &a,
                        vfloat &b);
#endif
    static void RGB2Lab(float *X, float *Y, float *Z, float *L, float *a,
                        float *b, const float wp[3][3], int width);
    static void RGB2L(float *X, float *Y, float *Z, float *L,
                      const float wp[3][3], int width);

    template <class T>
    static void rgb2lab(float R, float G, float B, float &l, float &a, float &b,
                        const T ws[3][3])
    {
        float x, y, z;
        rgbxyz(R, G, B, x, y, z, ws);
        XYZ2Lab(x, y, z, l, a, b);
    }

    template <class T>
    static void lab2rgb(float l, float a, float b, float &R, float &G, float &B,
                        const T iws[3][3])
    {
        float x, y, z;
        Lab2XYZ(l, a, b, x, y, z);
        xyz2rgb(x, y, z, R, G, B, iws);
    }

#ifdef ART_SIMD
    static void rgb2lab(vfloat R, vfloat G, vfloat B, vfloat &l, vfloat &a,
                        vfloat &b, const vfloat ws[3][3])
    {
        vfloat x, y, z;
        rgbxyz(R, G, B, x, y, z, ws);
        XYZ2Lab(x, y, z, l, a, b);
    }

    static void lab2rgb(vfloat l, vfloat a, vfloat b, vfloat &R, vfloat &G,
                        vfloat &B, const vfloat iws[3][3])
    {
        vfloat x, y, z;
        Lab2XYZ(l, a, b, x, y, z);
        xyz2rgb(x, y, z, R, G, B, iws);
    }
#endif


    /**
     * @brief Convert the 'a' and 'b' channels of the L*a*b color space to 'c'
     * and 'h' channels of the Lch color space (channel 'L' is identical [0 ;
     * 32768])
     * @param a 'a' channel [-42000 ; +42000] ; can be more than 42000
     * @param b 'b' channel [-42000 ; +42000] ; can be more than 42000
     * @param c 'c' channel return value, in [0 ; 42000] ; can be more than
     * 42000 (return value)
     * @param h 'h' channel return value, in [-PI ; +PI] (return value)
     */
    static void Lab2Lch(float a, float b, float &c, float &h);
#ifdef ART_SIMD
    static void Lab2Lch(float *a, float *b, float *c, float *h, int w);
#endif


    /**
     * @brief Return "f" in function of CIE's kappa and epsilon constants
     * @param f f can be fx fy fz where:
     *          fx=a/500 + fy  a=chroma green red [-128 ; +128]
     *          fy=(L+16)/116 L=luminance [0 ; 100]
     *          fz=fy-b/200 b=chroma blue yellow [-128 ; +128]
     */
    static inline double f2xyz(double f)
    {
        return (f > epsilonExpInv3) ? f * f * f : (116. * f - 16.) * kappaInv;
    }
    static inline float f2xyz(float f)
    {
        return (f > epsilonExpInv3f) ? f * f * f
                                     : (116.f * f - 16.f) * kappaInvf;
    }
#ifdef ART_SIMD
    static inline vfloat f2xyz(vfloat f)
    {
        const vfloat epsilonExpInv3v = F2V(epsilonExpInv3f);
        const vfloat kappaInvv = F2V(kappaInvf);
        vfloat res1 = f * f * f;
        vfloat res2 = (F2V(116.f) * f - F2V(16.f)) * kappaInvv;
        return vself(vmaskf_gt(f, epsilonExpInv3v), res1, res2);
    }
#endif

    template <class T>
    static void rgb2yuv(float r, float g, float b, float &Y, float &u, float &v,
                        const T workingspace[3][3])
    {
        Y = rgbLuminance(r, g, b, workingspace);
        u = Y - b;
        v = r - Y;
    }

    template <class T>
    static void yuv2rgb(float Y, float u, float v, float &r, float &g, float &b,
                        const T workingspace[3][3])
    {
        b = Y - u;
        r = v + Y;
        g = (Y - r * workingspace[1][0] - b * workingspace[1][2]) /
            workingspace[1][1];
    }

#ifdef ART_SIMD
    static void rgb2yuv(vfloat r, vfloat g, vfloat b, vfloat &Y, vfloat &u,
                        vfloat &v, const vfloat workingspace[3][3])
    {
        Y = rgbLuminance(r, g, b, workingspace);
        u = Y - b;
        v = r - Y;
    }

    static void yuv2rgb(vfloat Y, vfloat u, vfloat v, vfloat &r, vfloat &g,
                        vfloat &b, const vfloat workingspace[3][3])
    {
        b = Y - u;
        r = v + Y;
        g = (Y - r * workingspace[1][0] - b * workingspace[1][2]) /
            workingspace[1][1];
    }
#endif

    static void yuv2hsl(float u, float v, float &h, float &s);
    static void hsl2yuv(float h, float s, float &u, float &v);


    // @brief Get the gamma curves' parameters used by LCMS2
    static void compute_LCMS_tone_curve_params(double gamma, double slope,
                                               LMCSToneCurveParams &params);

    // Rec.2100 PQ curve
    // https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-2-201807-I!!PDF-F.pdf
    // Perceptual Quantization / SMPTE standard ST.2084
    static float eval_PQ_curve(float x, bool oetf);

    // Hybrid-log gamma curve
    // https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-2-201807-I!!PDF-F.pdf
    static float eval_HLG_curve(float x, bool oetf);


    // standard srgb gamma and its inverse
    /**
     * @brief sRGB gamma
     * See also calcGamma above with the following values: pwr=2.399 ts=12.92310
     * mode=0.003041  imax=0.055
     * @param x red, green or blue channel's value [0 ; 1]
     * @return the gamma modified's value [0 ; 1]
     */
    static inline double gamma2(double x) //  g3                  1+g4
    {
        //  return x <= 0.003041 ? x * 12.92310 : 1.055 * exp(log(x) / 2.39990)
        //  - 0.055;//calculate with calcgamma
        // return x <= 0.0031308 ? x * 12.92310 : 1.055 * exp(log(x) /
        // sRGBGammaCurve) - 0.055;//standard discontinuous very small
        // differences between the 2
        return x <= 0.003040
                   ? x * 12.92310
                   : 1.055 * exp(log(x) / sRGBGammaCurve) - 0.055; // continuous
        //  return x <= 0.003041 ? x * 12.92310 : 1.055011 * exp(log(x) /
        //  sRGBGammaCurve) - 0.055011;//continuous
    }

    /**
     * @brief Inverse sRGB gamma
     * See also calcGamma above with the following values: pwr=2.3999
     * ts=12.92310  mode=0.003041  imax=0.055
     * @param x red, green or blue channel's value [0 ; 1]
     * @return the inverse gamma modified's value [0 ; 1]
     */
    static inline double igamma2(double x) // g2
    {
        // return x <= 0.039289 ? x / 12.92310 : exp(log((x + 0.055) / 1.055)
        // * 2.39990);//calculate with calcgamma return x <= 0.04045 ? x
        // / 12.92310 : exp(log((x + 0.055) / 1.055) *
        // sRGBGammaCurve);//standard discontinuous
        // very small differences between the 4
        return x <= 0.039286 ? x / 12.92310
                             : exp(log((x + 0.055) / 1.055) *
                                   sRGBGammaCurve); // continuous
        //  return x <= 0.039293 ? x / 12.92310 : exp(log((x + 0.055011)
        //  / 1.055011) * sRGBGammaCurve);//continuous
    }

    /**
     * @brief Get the gamma value for Gamma=5.5 Slope=10
     * @param x red, green or blue channel's value [0 ; 1]
     * @return the gamma modified's value [0 ; 1]
     */
    static inline double gamma55(double x) //  g3                  1+g4
    {
        return x <= 0.013189
                   ? x * 10.0
                   : 1.593503 * exp(log(x) / 5.5) - 0.593503; // 5.5 10
    }

    /**
     * @brief Get the inverse gamma value for Gamma=5.5 Slope=10
     * @param x red, green or blue channel's value [0 ; 1]
     * @return the inverse gamma modified's value [0 ; 1]
     */
    static inline double igamma55(double x) // g2
    {
        return x <= 0.131889
                   ? x / 10.0
                   : exp(log((x + 0.593503) / 1.593503) * 5.5); // 5.5 10
    }

    /**
     * @brief Get the gamma value for Gamma=2.4 Slope=17
     * @param x red, green or blue channel's value [0 ; 1]
     * @return the gamma modified's value [0 ; 1]
     */
    static inline double gamma24_17(double x)
    {
        return x <= 0.001867 ? x * 17.0
                             : 1.044445 * exp(log(x) / 2.4) - 0.044445;
    }

    /**
     * @brief Get the inverse gamma value for Gamma=2.4 Slope=17
     * @param x red, green or blue channel's value [0 ; 1]
     * @return the inverse gamma modified's value [0 ; 1]
     */
    static inline double igamma24_17(double x)
    {
        return x <= 0.031746 ? x / 17.0
                             : exp(log((x + 0.044445) / 1.044445) * 2.4);
    }

    // gamma function with adjustable parameters
    // same as above with values calculate with Calcgamma above
    // X range 0..1
    static inline double gamma(double x, double gamma, double start,
                               double slope, double mul, double add)
    {
        return (x <= start ? x * slope : exp(log(x) / gamma) * mul - add);
    }

    static inline float gammaf(float x, float gamma, float start, float slope)
    {
        return x <= start ? x * slope : xexpf(xlogf(x) / gamma);
    }

    // fills a LUT of size 65536 using gamma with slope...
    static void gammaf2lut(LUTf &gammacurve, float gamma, float start,
                           float slope, float divisor, float factor);


    /**
     * @brief Very basic gamma
     * @param x red, green or blue channel's value [0 ; 1]
     * @param gamma gamma value [1 ; 5]
     * @return the gamma modified's value [0 ; 1]
     */
    static inline float gammanf(float x,
                                float gamma) // standard gamma without slope...
    {
        return xexpf(xlogf(x) / gamma);
    }


    /**
     * @brief Get the gamma value out of look-up tables
     * Calculated with gamma function above. e.g. :
     *    for (int i=0; i<65536; i++)
     *       gammatab_srgb[i] = (65535.0 * gamma2 (i/65535.0));
     * @param x [0 ; 1]
     * @return the gamma modified's value [0 ; 65535]
     */
    static inline float gamma_srgb(char x) { return gammatab_srgb[x]; }
    static inline float gamma(char x) { return gammatab[x]; }
    static inline float igamma_srgb(char x) { return igammatab_srgb[x]; }
    static inline float gamma_srgb(int x) { return gammatab_srgb[x]; }
    static inline float gamma(int x) { return gammatab[x]; }
    static inline float igamma_srgb(int x) { return igammatab_srgb[x]; }
    static inline float gamma_srgb(float x) { return gammatab_srgb[x]; }
    static inline float gamma_srgbclipped(float x) { return gamma2curve[x]; }
    static inline float gamma(float x) { return gammatab[x]; }
    static inline float igamma_srgb(float x) { return igammatab_srgb[x]; }
    // static inline float  gamma_srgb       (double x) { return
    // gammatab_srgb[x]; } static inline float  gamma            (double x) {
    // return gammatab[x]; } static inline float  igamma_srgb      (double x) {
    // return igammatab_srgb[x]; }


    /**
     * @brief Get HSV's hue from the Lab's hue
     * @param HH Lab's hue value, in radians [-PI ; +PI]
     * @return HSV's hue value [0 ; 1]
     */
    static inline double huelab_to_huehsv2(float HH)
    {
        // hr=translate Hue Lab value  (-Pi +Pi) in approximative hr (hsv
        // values) (0 1) [red 1/6 yellow 1/6 green 1/6 cyan 1/6 blue 1/6 magenta
        // 1/6 ]
        //  with multi linear correspondances (I expect there is no error !!)
        double hr = 0.0;
        // always put h between 0 and 1

        if (HH >= 0.f && HH < 0.6f) {
            hr = 0.11666 * double(HH) + 0.93; // hr 0.93  1.00    full red
        } else if (HH >= 0.6f && HH < 1.4f) {
            hr = 0.1125 * double(HH) -
                 0.0675; // hr 0.00  0.09    red yellow orange
        } else if (HH >= 1.4f && HH < 2.f) {
            hr = 0.2666 * double(HH) - 0.2833; // hr 0.09  0.25    orange yellow
        } else if (HH >= 2.f && HH <= 3.14159f) {
            hr = 0.1489 * double(HH) -
                 0.04785; // hr 0.25  0.42    yellow green green
        } else if (HH >= -3.1416f && HH < -2.8f) {
            hr = 0.23419 * double(HH) + 1.1557; // hr 0.42  0.50    green
        } else if (HH >= -2.8f && HH < -2.3f) {
            hr = 0.16 * double(HH) + 0.948; // hr 0.50  0.58    cyan
        } else if (HH >= -2.3f && HH < -0.9f) {
            hr = 0.12143 * double(HH) +
                 0.85928; // hr 0.58  0.75    blue blue-sky
        } else if (HH >= -0.9f && HH < -0.1f) {
            hr = 0.2125 * double(HH) +
                 0.94125; // hr 0.75  0.92    purple magenta
        } else if (HH >= -0.1f && HH < 0.f) {
            hr = 0.1 * double(HH) + 0.93; // hr 0.92  0.93    red
        }

        // in case of !
        if (hr < 0.0) {
            hr += 1.0;
        } else if (hr > 1.0) {
            hr -= 1.0;
        }

        return (hr);
    }

    // This is Adobe's hue-stable film-like curve with a diagonal, ie only used
    // for clipping. Can probably be further optimized.
    static void filmlike_clip(float *r, float *g, float *b, float Lmax);

    static void xyz2jzazbz(float X, float Y, float Z, float &Jz, float &az,
                           float &bz);
    static void jzazbz2xyz(float Jz, float az, float bz, float &X, float &Y,
                           float &Z);

    template <class T>
    static void rgb2jzazbz(float R, float G, float B, float &Jz, float &az,
                           float &bz, const T ws[3][3])
    {
        float X, Y, Z;
        rgbxyz(R, G, B, X, Y, Z, ws);
        xyz2jzazbz(X, Y, Z, Jz, az, bz);
    }

    template <class T>
    static void jzazbz2rgb(float Jz, float az, float bz, float &R, float &G,
                           float &B, const T iws[3][3])
    {
        float X, Y, Z;
        jzazbz2xyz(Jz, az, bz, X, Y, Z);
        xyz2rgb(X, Y, Z, R, G, B, iws);
    }

    static void jzazbz2jzch(float az, float bz, float &c, float &h)
    {
        yuv2hsl(bz, az, h, c);
    }

    static void jzch2jzazbz(float c, float h, float &az, float &bz)
    {
        hsl2yuv(h, c, bz, az);
    }

    template <class T>
    static void rgb2jzczhz(float R, float G, float B, float &Jz, float &cz,
                           float &hz, const T ws[3][3])
    {
        float az, bz;
        rgb2jzazbz(R, G, B, Jz, az, bz, ws);
        jzazbz2jzch(az, bz, cz, hz);
    }

    template <class T>
    static void jzczhz2rgb(float Jz, float cz, float hz, float &R, float &G,
                           float &B, const T iws[3][3])
    {
        float az, bz;
        jzch2jzazbz(cz, hz, az, bz);
        jzazbz2rgb(Jz, az, bz, R, G, B, iws);
    }


};

}} // namespace art::engine
