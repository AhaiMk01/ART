/*
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

#include "color.h"
#include "iccmatrices.h"
#include "iccstore.h"
#include "linalgebra.h"
#include "mytime.h"
#include "opthelper.h"
#include "rtengine.h"
#include "sleef.h"

namespace art { namespace engine {

namespace {

typedef Vec3f A3;

// D50 <-> D65 adapted from darktable

void XYZ_D50_to_D65(float &X, float &Y, float &Z)
{
    // Bradford adaptation matrix from
    // http://www.brucelindbloom.com/index.html?Eqn_ChromAdapt.html
    constexpr float M[3][3] = {{0.9555766f, -0.0230393f, 0.0631636f},
                               {-0.0282895f, 1.0099416f, 0.0210077f},
                               {0.0122982f, -0.0204830f, 1.3299098f}};
    A3 res = dot_product(M, A3(X, Y, Z));
    X = res[0];
    Y = res[1];
    Z = res[2];
}

void XYZ_D65_to_D50(float &X, float &Y, float &Z)
{
    // Bradford adaptation matrix from
    // http://www.brucelindbloom.com/index.html?Eqn_ChromAdapt.html
    constexpr float M[3][3] = {{1.0478112f, 0.0228866f, -0.0501270f},
                               {0.0295424f, 0.9904844f, -0.0170491f},
                               {-0.0092345f, 0.0150436f, 0.7521316f}};
    A3 res = dot_product(M, A3(X, Y, Z));
    X = res[0];
    Y = res[1];
    Z = res[2];
}

float PQ(float X)
{
    X = std::max(X, 1e-10f);
    const float XX = std::pow(X * 1e-4f, 0.1593017578125f);
    return std::pow((0.8359375f + 18.8515625f * XX) / (1 + 18.6875f * XX),
                    134.034375f);
}

float PQ_inv(float X)
{
    X = std::max(X, 1e-10f);
    const auto XX = std::pow(X, 7.460772656268214e-03f);
    return 1e4f * std::pow((0.8359375f - XX) / (18.6875f * XX - 18.8515625f),
                           6.277394636015326f);
}

} // namespace

extern const Settings *settings;

LUTf Color::cachef;
LUTf Color::cachefy;
LUTf Color::gamma2curve;

LUTf Color::gammatab;
LUTuc Color::gammatabThumb;
LUTf Color::igammatab_srgb;
LUTf Color::igammatab_srgb1;
LUTf Color::gammatab_srgb;
LUTf Color::gammatab_srgb1;

LUTf Color::denoiseGammaTab;
LUTf Color::denoiseIGammaTab;

LUTf Color::igammatab_24_17;
LUTf Color::gammatab_24_17a;

LUTf Color::jzazbz_pq_;
LUTf Color::jzazbz_pq_inv_;

void Color::init()
{

    /*******************************************/

    constexpr auto maxindex = 65536;

    cachef(maxindex, LUT_CLIP_BELOW);
    cachefy(maxindex, LUT_CLIP_BELOW);
    gammatab(maxindex, 0);
    gammatabThumb(maxindex, 0);

    igammatab_srgb(maxindex, 0);
    igammatab_srgb1(maxindex, 0);
    gammatab_srgb(maxindex, 0);
    gammatab_srgb1(maxindex, 0);

    denoiseGammaTab(maxindex, 0);
    denoiseIGammaTab(maxindex, 0);

    igammatab_24_17(maxindex, 0);
    gammatab_24_17a(maxindex, LUT_CLIP_ABOVE | LUT_CLIP_BELOW);

    jzazbz_pq_(maxindex, 0);
    jzazbz_pq_inv_(maxindex, 0);

#ifdef _OPENMP
#pragma omp parallel sections
#endif
    {
#ifdef _OPENMP
#pragma omp section
#endif
        {
            int i = 0;
            int epsmaxint = eps_max;

            for (; i <= epsmaxint; i++) {
                cachef[i] = 327.68 * ((kappa * i / MAXVALF + 16.0) / 116.0);
            }

            for (; i < maxindex; i++) {
                cachef[i] = 327.68 * std::cbrt((double)i / MAXVALF);
            }
        }
#ifdef _OPENMP
#pragma omp section
#endif
        {
            int i = 0;
            int epsmaxint = eps_max;

            for (; i <= epsmaxint; i++) {
                cachefy[i] = 327.68 * (kappa * i / MAXVALF);
            }

            for (; i < maxindex; i++) {
                cachefy[i] =
                    327.68 * (116.0 * std::cbrt((double)i / MAXVALF) - 16.0);
            }
        }
#ifdef _OPENMP
#pragma omp section
#endif
        {
            for (int i = 0; i < maxindex; i++) {
                gammatab_srgb[i] = gammatab_srgb1[i] = gamma2(i / 65535.0);
            }
            gammatab_srgb *= 65535.f;
            gamma2curve.share(
                gammatab_srgb,
                LUT_CLIP_BELOW |
                    LUT_CLIP_ABOVE); // shares the buffer with gammatab_srgb but
                                     // has different clip flags
        }
#ifdef _OPENMP
#pragma omp section
#endif
        {
            for (int i = 0; i < maxindex; i++) {
                igammatab_srgb[i] = igammatab_srgb1[i] = igamma2(i / 65535.0);
            }

            igammatab_srgb *= 65535.f;
        }
#ifdef _OPENMP
#pragma omp section
#endif
        {
            double rsRGBGamma = 1.0 / sRGBGamma;

            for (int i = 0; i < maxindex; i++) {
                double val = pow(i / 65535.0, rsRGBGamma);
                gammatab[i] = 65535.0 * val;
                gammatabThumb[i] = (unsigned char)(255.0 * val);
            }
        }

#ifdef _OPENMP
#pragma omp section
#endif
        // modify arbitrary data for Lab..I have test : nothing, gamma 2.6 11 -
        // gamma 4 5 - gamma 5.5 10 we can put other as gamma g=2.6 slope=11,
        // etc. but noting to do with real gamma !!!: it's only for data Lab #
        // data RGB finally I opted for gamma55 and with options we can change
        for (int i = 0; i < maxindex; i++) {
            denoiseGammaTab[i] = 65535.0 * gamma55(i / 65535.0);
        }

#ifdef _OPENMP
#pragma omp section
#endif
        // modify arbitrary data for Lab..I have test : nothing, gamma 2.6 11 -
        // gamma 4 5 - gamma 5.5 10 we can put other as gamma g=2.6 slope=11,
        // etc. but noting to do with real gamma !!!: it's only for data Lab #
        // data RGB finally I opted for gamma55 and with options we can change

        for (int i = 0; i < maxindex; i++) {
            denoiseIGammaTab[i] = 65535.0 * igamma55(i / 65535.0);
        }

#ifdef _OPENMP
#pragma omp section
#endif

        for (int i = 0; i < maxindex; i++) {
            gammatab_24_17a[i] = gamma24_17(i / 65535.0);
        }

#ifdef _OPENMP
#pragma omp section
#endif

        for (int i = 0; i < maxindex; i++) {
            igammatab_24_17[i] = 65535.0 * igamma24_17(i / 65535.0);
        }

#ifdef _OPENMP
#pragma omp section
#endif
        for (int i = 0; i < maxindex; ++i) {
            jzazbz_pq_[i] = PQ(float(i) / 65535.f);
            /* Sampled over [0, jzazbzPQInvMax()], not [0,1] -- see the comment
             * on jzazbzPQInvMax() in color.h. */
            jzazbz_pq_inv_[i] =
                PQ_inv(jzazbzPQInvMax() * float(i) / 65535.f);
        }
    }
}

void Color::rgb2lab01(const Glib::ustring &profile,
                      const Glib::ustring &profileW, float r, float g, float b,
                      float &LAB_l, float &LAB_a, float &LAB_b,
                      bool workingSpace)
{ // do not use this function in a loop. It really eats processing time caused
  // by Glib::ustring comparisons

    cmsHPROFILE oprof = nullptr;
    if (workingSpace) {
        oprof = ICCStore::getInstance()->workingSpace(profileW);
    } else if (profile == procparams::ColorManagementParams::NoICMString) {
        oprof = ICCStore::getInstance()->getsRGBProfile();
    } else {
        oprof = ICCStore::getInstance()->getProfile(profile);
    }

    if (!oprof) {
        LAB_l = LAB_a = LAB_b = 0.f;
        return;
    }

    lcmsMutex->lock();
    cmsHPROFILE labprof = cmsCreateLab4Profile(nullptr);
    cmsHTRANSFORM hTransform = cmsCreateTransform(
        oprof, TYPE_RGB_FLT, labprof, TYPE_Lab_DBL,
        INTENT_RELATIVE_COLORIMETRIC, cmsFLAGS_NOOPTIMIZE | cmsFLAGS_NOCACHE);
    cmsCloseProfile(labprof);
    lcmsMutex->unlock();

    float inbuf[3] = {r, g, b};
    double outbuf[3];

    cmsDoTransform(hTransform, inbuf, outbuf, 1);
    cmsDeleteTransform(hTransform);

    LAB_l = outbuf[0];
    LAB_a = outbuf[1];
    LAB_b = outbuf[2];
}

void Color::lab2lch01(float L, float a, float b, float &l, float &c, float &h)
{
    l = L / 100.f;
    c = sqrtf(a * a + b * b) / 100.f;
    h = xatan2f(b, a);
    if (h < 0.f) {
        h += 2.f * art::engine::RT_PI_F;
    }
    h /= (2.f * art::engine::RT_PI_F);
}

void Color::rgb2hsl(float r, float g, float b, float &h, float &s, float &l)
{

    double var_R = double(r) / 65535.0;
    double var_G = double(g) / 65535.0;
    double var_B = double(b) / 65535.0;

    double m = min(var_R, var_G, var_B);
    double M = max(var_R, var_G, var_B);
    double C = M - m;

    double l_ = (M + m) / 2.;
    l = float(l_);

    if (C < 0.00001 && C > -0.00001) { // no fabs, slow!
        h = 0.f;
        s = 0.f;
    } else {
        double h_;

        if (l_ <= 0.5) {
            s = float((M - m) / (M + m));
        } else {
            s = float((M - m) / (2.0 - M - m));
        }

        if (var_R == M) {
            h_ = (var_G - var_B) / C;
        } else if (var_G == M) {
            h_ = 2. + (var_B - var_R) / C;
        } else {
            h_ = 4. + (var_R - var_G) / C;
        }

        h = float(h_ / 6.0);

        if (h < 0.f) {
            h += 1.f;
        }

        if (h > 1.f) {
            h -= 1.f;
        }
    }
}

#ifdef ART_SIMD
void Color::rgb2hsl(vfloat r, vfloat g, vfloat b, vfloat &h, vfloat &s,
                    vfloat &l)
{
    vfloat maxv = vmaxf(r, vmaxf(g, b));
    vfloat minv = vminf(r, vminf(g, b));
    vfloat C = maxv - minv;
    vfloat tempv = maxv + minv;
    l = (tempv)*F2V(7.6295109e-6f);
    s = (maxv - minv);
    s /= vself(vmaskf_gt(l, F2V(0.5f)), F2V(131070.f) - tempv, tempv);

    h = F2V(4.f) * C + r - g;
    h = vself(vmaskf_eq(g, maxv), F2V(2.f) * C + b - r, h);
    h = vself(vmaskf_eq(r, maxv), g - b, h);

    h /= (F2V(6.f) * C);
    vfloat onev = F2V(1.f);
    h = vself(vmaskf_lt(h, ZEROV), h + onev, h);

    vmask zeromask = vmaskf_lt(C, F2V(0.65535f));
    h = vself(zeromask, ZEROV, h);
    s = vself(zeromask, ZEROV, s);
}
#endif

double Color::hue2rgb(double p, double q, double t)
{
    if (t < 0.) {
        t += 6.;
    } else if (t > 6.) {
        t -= 6.;
    }

    if (t < 1.) {
        return p + (q - p) * t;
    } else if (t < 3.) {
        return q;
    } else if (t < 4.) {
        return p + (q - p) * (4. - t);
    } else {
        return p;
    }
}


#ifdef ART_SIMD
vfloat Color::hue2rgb(vfloat p, vfloat q, vfloat t)
{
    vfloat fourv = F2V(4.f);
    vfloat threev = F2V(3.f);
    vfloat sixv = threev + threev;
    t = vself(vmaskf_lt(t, ZEROV), t + sixv, t);
    t = vself(vmaskf_gt(t, sixv), t - sixv, t);

    vfloat temp1 = p + (q - p) * t;
    vfloat temp2 = p + (q - p) * (fourv - t);
    vfloat result = vself(vmaskf_lt(t, fourv), temp2, p);
    result = vself(vmaskf_lt(t, threev), q, result);
    return vself(vmaskf_lt(t, fourv - threev), temp1, result);
}
#endif

void Color::hsl2rgb(float h, float s, float l, float &r, float &g, float &b)
{

    if (s == 0) {
        r = g = b = 65535.0f * l; //  achromatic
    } else {
        double m2;
        double h_ = double(h);
        double s_ = double(s);
        double l_ = double(l);

        if (l <= 0.5f) {
            m2 = l_ * (1.0 + s_);
        } else {
            m2 = l_ + s_ - l_ * s_;
        }

        double m1 = 2.0 * l_ - m2;

        r = float(65535.0 * hue2rgb(m1, m2, h_ * 6.0 + 2.0));
        g = float(65535.0 * hue2rgb(m1, m2, h_ * 6.0));
        b = float(65535.0 * hue2rgb(m1, m2, h_ * 6.0 - 2.0));
    }
}

#ifdef ART_SIMD
void Color::hsl2rgb(vfloat h, vfloat s, vfloat l, vfloat &r, vfloat &g,
                    vfloat &b)
{

    vfloat m2 = s * l;
    m2 = vself(vmaskf_gt(l, F2V(0.5f)), s - m2, m2);
    m2 += l;

    vfloat twov = F2V(2.f);
    vfloat c65535v = F2V(65535.f);
    vfloat m1 = l + l - m2;

    h *= F2V(6.f);
    r = c65535v * hue2rgb(m1, m2, h + twov);
    g = c65535v * hue2rgb(m1, m2, h);
    b = c65535v * hue2rgb(m1, m2, h - twov);

    vmask selectsMask = vmaskf_eq(ZEROV, s);
    vfloat lc65535v = c65535v * l;
    r = vself(selectsMask, lc65535v, r);
    g = vself(selectsMask, lc65535v, g);
    b = vself(selectsMask, lc65535v, b);
}
#endif


void Color::rgb2hsv(float r, float g, float b, float &h, float &s, float &v)
{
    const double var_R = r / 65535.0;
    const double var_G = g / 65535.0;
    const double var_B = b / 65535.0;

    const double var_Min = min(var_R, var_G, var_B);
    const double var_Max = max(var_R, var_G, var_B);
    const double del_Max = var_Max - var_Min;

    h = 0.f;
    v = var_Max;

    if (del_Max < 0.00001 && del_Max > -0.00001) { // no fabs, slow!
        s = 0.f;
    } else {
        s = del_Max / (var_Max == 0.0 ? 1.0 : var_Max);

        if (var_R == var_Max) {
            h = (var_G - var_B) / del_Max;
        } else if (var_G == var_Max) {
            h = 2.0 + (var_B - var_R) / del_Max;
        } else if (var_B == var_Max) {
            h = 4.0 + (var_R - var_G) / del_Max;
        }

        h /= 6.f;

        if (h < 0.f) {
            h += 1.f;
        }

        if (h > 1.f) {
            h -= 1.f;
        }
    }
}


void Color::hsv2rgb(float h, float s, float v, float &r, float &g, float &b)
{

    float h1 = h * 6.f; // sector 0 to 5
    int i = (int)h1;    // floor() is very slow, and h1 is always >0
    float f = h1 - i;   // fractional part of h

    float p = v * (1.f - s);
    float q = v * (1.f - s * f);
    float t = v * (1.f - s * (1.f - f));

    float r1, g1, b1;

    if (i == 1) {
        r1 = q;
        g1 = v;
        b1 = p;
    } else if (i == 2) {
        r1 = p;
        g1 = v;
        b1 = t;
    } else if (i == 3) {
        r1 = p;
        g1 = q;
        b1 = v;
    } else if (i == 4) {
        r1 = t;
        g1 = p;
        b1 = v;
    } else if (i == 5) {
        r1 = v;
        g1 = p;
        b1 = q;
    } else { /*i==(0|6)*/
        r1 = v;
        g1 = t;
        b1 = p;
    }

    r = ((r1) * 65535.0f);
    g = ((g1) * 65535.0f);
    b = ((b1) * 65535.0f);
}

// Function copied for speed concerns
// Not exactly the same as above ; this one return a result in the [0.0 ; 1.0]
// range
void Color::hsv2rgb01(float h, float s, float v, float &r, float &g, float &b)
{
    // // // try to get a better visual match -- this is empirical and to be
    // confirmed h -= 0.05f; if (h < 0.f) {
    //     h += 1.f;
    // }

    float h1 = h * 6; // sector 0 to 5
    int i = int(h1);
    float f = h1 - i; // fractional part of h

    float p = v * (1 - s);
    float q = v * (1 - s * f);
    float t = v * (1 - s * (1 - f));

    if (i == 1) {
        r = q;
        g = v;
        b = p;
    } else if (i == 2) {
        r = p;
        g = v;
        b = t;
    } else if (i == 3) {
        r = p;
        g = q;
        b = v;
    } else if (i == 4) {
        r = t;
        g = p;
        b = v;
    } else if (i == 5) {
        r = v;
        g = p;
        b = q;
    } else { /*(i==0|6)*/
        r = v;
        g = t;
        b = p;
    }
}

void Color::hsv2rgb(float h, float s, float v, int &r, int &g, int &b)
{

    float h1 = h * 6; // sector 0 to 5
    int i = floor(h1);
    float f = h1 - i; // fractional part of h

    float p = v * (1 - s);
    float q = v * (1 - s * f);
    float t = v * (1 - s * (1 - f));

    float r1, g1, b1;

    if (i == 0) {
        r1 = v;
        g1 = t;
        b1 = p;
    } else if (i == 1) {
        r1 = q;
        g1 = v;
        b1 = p;
    } else if (i == 2) {
        r1 = p;
        g1 = v;
        b1 = t;
    } else if (i == 3) {
        r1 = p;
        g1 = q;
        b1 = v;
    } else if (i == 4) {
        r1 = t;
        g1 = p;
        b1 = v;
    } else /*if (i == 5)*/ {
        r1 = v;
        g1 = p;
        b1 = q;
    }

    r = (int)(r1 * 65535);
    g = (int)(g1 * 65535);
    b = (int)(b1 * 65535);
}

//%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

void Color::xyz2srgb(float x, float y, float z, float &r, float &g, float &b)
{

    // Transform to output color.  Standard sRGB is D65, but internal
    // representation is D50 Note that it is only at this point that we should
    // have need of clipping color data

    /*float x65 = d65_d50[0][0]*x + d65_d50[0][1]*y + d65_d50[0][2]*z ;
    float y65 = d65_d50[1][0]*x + d65_d50[1][1]*y + d65_d50[1][2]*z ;
    float z65 = d65_d50[2][0]*x + d65_d50[2][1]*y + d65_d50[2][2]*z ;

    r = sRGB_xyz[0][0]*x65 + sRGB_xyz[0][1]*y65 + sRGB_xyz[0][2]*z65;
    g = sRGB_xyz[1][0]*x65 + sRGB_xyz[1][1]*y65 + sRGB_xyz[1][2]*z65;
    b = sRGB_xyz[2][0]*x65 + sRGB_xyz[2][1]*y65 + sRGB_xyz[2][2]*z65;*/

    /*r = sRGBd65_xyz[0][0]*x + sRGBd65_xyz[0][1]*y + sRGBd65_xyz[0][2]*z ;
    g = sRGBd65_xyz[1][0]*x + sRGBd65_xyz[1][1]*y + sRGBd65_xyz[1][2]*z ;
    b = sRGBd65_xyz[2][0]*x + sRGBd65_xyz[2][1]*y + sRGBd65_xyz[2][2]*z ;*/

    r = ((sRGB_xyz[0][0] * x + sRGB_xyz[0][1] * y + sRGB_xyz[0][2] * z));
    g = ((sRGB_xyz[1][0] * x + sRGB_xyz[1][1] * y + sRGB_xyz[1][2] * z));
    b = ((sRGB_xyz[2][0] * x + sRGB_xyz[2][1] * y + sRGB_xyz[2][2] * z));
}
void Color::xyz2Prophoto(float x, float y, float z, float &r, float &g,
                         float &b)
{
    r = ((prophoto_xyz[0][0] * x + prophoto_xyz[0][1] * y +
          prophoto_xyz[0][2] * z));
    g = ((prophoto_xyz[1][0] * x + prophoto_xyz[1][1] * y +
          prophoto_xyz[1][2] * z));
    b = ((prophoto_xyz[2][0] * x + prophoto_xyz[2][1] * y +
          prophoto_xyz[2][2] * z));
}
void Color::Prophotoxyz(float r, float g, float b, float &x, float &y, float &z)
{
    x = ((xyz_prophoto[0][0] * r + xyz_prophoto[0][1] * g +
          xyz_prophoto[0][2] * b));
    y = ((xyz_prophoto[1][0] * r + xyz_prophoto[1][1] * g +
          xyz_prophoto[1][2] * b));
    z = ((xyz_prophoto[2][0] * r + xyz_prophoto[2][1] * g +
          xyz_prophoto[2][2] * b));
}

void Color::rgbxyz(float r, float g, float b, float &x, float &y, float &z,
                   const double xyz_rgb[3][3])
{
    x = ((xyz_rgb[0][0] * r + xyz_rgb[0][1] * g + xyz_rgb[0][2] * b));
    y = ((xyz_rgb[1][0] * r + xyz_rgb[1][1] * g + xyz_rgb[1][2] * b));
    z = ((xyz_rgb[2][0] * r + xyz_rgb[2][1] * g + xyz_rgb[2][2] * b));
}

void Color::rgbxyz(float r, float g, float b, float &x, float &y, float &z,
                   const float xyz_rgb[3][3])
{
    x = ((xyz_rgb[0][0] * r + xyz_rgb[0][1] * g + xyz_rgb[0][2] * b));
    y = ((xyz_rgb[1][0] * r + xyz_rgb[1][1] * g + xyz_rgb[1][2] * b));
    z = ((xyz_rgb[2][0] * r + xyz_rgb[2][1] * g + xyz_rgb[2][2] * b));
}

#ifdef ART_SIMD
void Color::rgbxyz(vfloat r, vfloat g, vfloat b, vfloat &x, vfloat &y,
                   vfloat &z, const vfloat xyz_rgb[3][3])
{
    x = ((xyz_rgb[0][0] * r + xyz_rgb[0][1] * g + xyz_rgb[0][2] * b));
    y = ((xyz_rgb[1][0] * r + xyz_rgb[1][1] * g + xyz_rgb[1][2] * b));
    z = ((xyz_rgb[2][0] * r + xyz_rgb[2][1] * g + xyz_rgb[2][2] * b));
}
#endif

void Color::xyz2rgb(float x, float y, float z, float &r, float &g, float &b,
                    const double rgb_xyz[3][3])
{
    // Transform to output color.  Standard sRGB is D65, but internal
    // representation is D50 Note that it is only at this point that we should
    // have need of clipping color data

    /*float x65 = d65_d50[0][0]*x + d65_d50[0][1]*y + d65_d50[0][2]*z ;
    float y65 = d65_d50[1][0]*x + d65_d50[1][1]*y + d65_d50[1][2]*z ;
    float z65 = d65_d50[2][0]*x + d65_d50[2][1]*y + d65_d50[2][2]*z ;

    r = sRGB_xyz[0][0]*x65 + sRGB_xyz[0][1]*y65 + sRGB_xyz[0][2]*z65;
    g = sRGB_xyz[1][0]*x65 + sRGB_xyz[1][1]*y65 + sRGB_xyz[1][2]*z65;
    b = sRGB_xyz[2][0]*x65 + sRGB_xyz[2][1]*y65 + sRGB_xyz[2][2]*z65;*/

    /*r = sRGBd65_xyz[0][0]*x + sRGBd65_xyz[0][1]*y + sRGBd65_xyz[0][2]*z ;
    g = sRGBd65_xyz[1][0]*x + sRGBd65_xyz[1][1]*y + sRGBd65_xyz[1][2]*z ;
    b = sRGBd65_xyz[2][0]*x + sRGBd65_xyz[2][1]*y + sRGBd65_xyz[2][2]*z ;*/

    r = ((rgb_xyz[0][0] * x + rgb_xyz[0][1] * y + rgb_xyz[0][2] * z));
    g = ((rgb_xyz[1][0] * x + rgb_xyz[1][1] * y + rgb_xyz[1][2] * z));
    b = ((rgb_xyz[2][0] * x + rgb_xyz[2][1] * y + rgb_xyz[2][2] * z));
}


// same for float
void Color::xyz2rgb(float x, float y, float z, float &r, float &g, float &b,
                    const float rgb_xyz[3][3])
{
    r = ((rgb_xyz[0][0] * x + rgb_xyz[0][1] * y + rgb_xyz[0][2] * z));
    g = ((rgb_xyz[1][0] * x + rgb_xyz[1][1] * y + rgb_xyz[1][2] * z));
    b = ((rgb_xyz[2][0] * x + rgb_xyz[2][1] * y + rgb_xyz[2][2] * z));
}

#ifdef ART_SIMD
void Color::xyz2rgb(vfloat x, vfloat y, vfloat z, vfloat &r, vfloat &g,
                    vfloat &b, const vfloat rgb_xyz[3][3])
{
    r = ((rgb_xyz[0][0] * x + rgb_xyz[0][1] * y + rgb_xyz[0][2] * z));
    g = ((rgb_xyz[1][0] * x + rgb_xyz[1][1] * y + rgb_xyz[1][2] * z));
    b = ((rgb_xyz[2][0] * x + rgb_xyz[2][1] * y + rgb_xyz[2][2] * z));
}
#endif // ART_SIMD


void Color::compute_LCMS_tone_curve_params(double gamma, double slope,
                                           LMCSToneCurveParams &params)
{
    double ts = slope;
    double pwr = 1.0 / gamma;

    // from Dcraw (D.Coffin)
    int i;
    double g[6], bnd[2] = {0., 0.};

    g[0] = pwr;
    g[1] = ts;
    g[2] = g[3] = g[4] = 0.;
    bnd[g[1] >= 1.] = 1.;

    if (g[1] && (g[1] - 1.) * (g[0] - 1.) <= 0.) {
        for (i = 0; i < 99; i++) {
            g[2] = (bnd[0] + bnd[1]) / 2.;

            if (g[0]) {
                bnd[(pow(g[2] / g[1], -g[0]) - 1.) / g[0] - 1. / g[2] > -1.] =
                    g[2];
            } else {
                bnd[g[2] / exp(1. - 1. / g[2]) < g[1]] = g[2];
            }
        }

        g[3] = g[2] / g[1];

        if (g[0]) {
            g[4] = g[2] * (1. / g[0] - 1.);
        }
    }

    if (g[0]) {
        g[5] = 1. / (g[1] * SQR(g[3]) / 2. - g[4] * (1. - g[3]) +
                     (1. - pow(g[3], 1. + g[0])) * (1. + g[4]) / (1. + g[0])) -
               1.;
    } else {
        g[5] = 1. / (g[1] * SQR(g[3]) / 2. + 1. - g[2] - g[3] -
                     g[2] * g[3] * (log(g[3]) - 1.)) -
               1.;
    }

    params[0] = gamma;
    params[1] = 1. / (1.0 + g[4]);
    params[2] = g[4] / (1.0 + g[4]);
    params[3] = 1. / std::max(slope, 1e-9);
    params[4] = g[3] * ts;
    params[5] = 0.;
    params[6] = 0.;
}

void Color::gammaf2lut(LUTf &gammacurve, float gamma, float start, float slope,
                       float divisor, float factor)
{
#ifdef ART_SIMD
    // SSE2 version is more than 6 times faster than scalar version
    vfloat iv = _mm_set_ps(3.f, 2.f, 1.f, 0.f);
    vfloat fourv = F2V(4.f);
    vfloat gammav = F2V(1.f / gamma);
    vfloat slopev = F2V((slope / divisor) * factor);
    vfloat divisorv = F2V(xlogf(divisor));
    vfloat factorv = F2V(factor);
    vfloat comparev = F2V(start * divisor);
    int border = start * divisor;
    int border1 = border - (border & 3);
    int border2 = border1 + 4;
    int i = 0;

    for (; i < border1; i += 4) {
        vfloat resultv = iv * slopev;
        STVFU(gammacurve[i], resultv);
        iv += fourv;
    }

    for (; i < border2; i += 4) {
        vfloat result0v = iv * slopev;
        vfloat result1v = xexpf((xlogf(iv) - divisorv) * gammav) * factorv;
        STVFU(gammacurve[i],
              vself(vmaskf_le(iv, comparev), result0v, result1v));
        iv += fourv;
    }

    for (; i < 65536; i += 4) {
        vfloat resultv =
            xexpfNoCheck((xlogfNoCheck(iv) - divisorv) * gammav) * factorv;
        STVFU(gammacurve[i], resultv);
        iv += fourv;
    }

#else

    for (int i = 0; i < 65536; ++i) {
        gammacurve[i] =
            gammaf(static_cast<float>(i) / divisor, gamma, start, slope) *
            factor;
    }

#endif
}


void Color::Lab2XYZ(float L, float a, float b, float &x, float &y, float &z)
{
    float LL = L / 327.68f;
    float aa = a / 327.68f;
    float bb = b / 327.68f;
    float fy = (c1By116 * LL) + c16By116; // (L+16)/116
    float fx = (0.002f * aa) + fy;
    float fz = fy - (0.005f * bb);
    x = 65535.0f * f2xyz(fx) * D50x;
    z = 65535.0f * f2xyz(fz) * D50z;
    y = (LL > epskap) ? 65535.0f * fy * fy * fy : 65535.0f * LL / kappa;
}


#ifdef ART_SIMD
void Color::Lab2XYZ(vfloat L, vfloat a, vfloat b, vfloat &x, vfloat &y,
                    vfloat &z)
{
    vfloat c327d68 = F2V(327.68f);
    L /= c327d68;
    a /= c327d68;
    b /= c327d68;
    vfloat fy = F2V(c1By116) * L + F2V(c16By116);
    vfloat fx = F2V(0.002f) * a + fy;
    vfloat fz = fy - (F2V(0.005f) * b);
    vfloat c65535 = F2V(65535.f);
    x = c65535 * f2xyz(fx) * F2V(D50x);
    z = c65535 * f2xyz(fz) * F2V(D50z);
    vfloat res1 = fy * fy * fy;
    vfloat res2 = L / F2V(kappa);
    y = vself(vmaskf_gt(L, F2V(epskap)), res1, res2);
    y *= c65535;
}
#endif // ART_SIMD

inline float Color::computeXYZ2Lab(float f)
{
    if (xisnanf(f)) {
        return f;
    }
    if (f < 0.f) {
        return 327.68 * ((kappa * f / MAXVALF + 16.0) / 116.0);
    } else if (f > 65535.f) {
        return (327.68f * xcbrtf(f / MAXVALF));
    } else {
        return cachef[f];
    }
}

inline float Color::computeXYZ2LabY(float f)
{
    if (xisnanf(f)) {
        return f;
    }
    if (f < 0.f) {
        return 327.68 * (kappa * f / MAXVALF);
    } else if (f > 65535.f) {
        return 327.68f * (116.f * xcbrtf(f / MAXVALF) - 16.f);
    } else {
        return cachefy[f];
    }
}

void Color::RGB2Lab(float *R, float *G, float *B, float *L, float *a, float *b,
                    const float wp[3][3], int width)
{

#ifdef ART_SIMD
    vfloat minvalfv = F2V(0.f);
    vfloat maxvalfv = F2V(MAXVALF);
    vfloat c500v = F2V(500.f);
    vfloat c200v = F2V(200.f);
#endif
    int i = 0;

#ifdef ART_SIMD
    for (; i < width - 3; i += 4) {
        const vfloat rv = LVFU(R[i]);
        const vfloat gv = LVFU(G[i]);
        const vfloat bv = LVFU(B[i]);
        const vfloat xv =
            F2V(wp[0][0]) * rv + F2V(wp[0][1]) * gv + F2V(wp[0][2]) * bv;
        const vfloat yv =
            F2V(wp[1][0]) * rv + F2V(wp[1][1]) * gv + F2V(wp[1][2]) * bv;
        const vfloat zv =
            F2V(wp[2][0]) * rv + F2V(wp[2][1]) * gv + F2V(wp[2][2]) * bv;

        vmask maxMask = vmaskf_gt(vmaxf(xv, vmaxf(yv, zv)), maxvalfv);
        vmask minMask = vmaskf_lt(vminf(xv, vminf(yv, zv)), minvalfv);
        if (_mm_movemask_ps((vfloat)maxMask) ||
            _mm_movemask_ps((vfloat)minMask)) {
            // take slower code path for all 4 pixels if one of the values is >
            // MAXVALF. Still faster than non SSE2 version
            for (int k = 0; k < 4; ++k) {
                float x = xv[k];
                float y = yv[k];
                float z = zv[k];
                float fx = computeXYZ2Lab(x);
                float fy = computeXYZ2Lab(y);
                float fz = computeXYZ2Lab(z);

                L[i + k] = computeXYZ2LabY(y);
                a[i + k] = (500.f * (fx - fy));
                b[i + k] = (200.f * (fy - fz));
            }
        } else {
            const vfloat fx = cachef[xv];
            const vfloat fy = cachef[yv];
            const vfloat fz = cachef[zv];

            STVFU(L[i], cachefy[yv]);
            STVFU(a[i], c500v * (fx - fy));
            STVFU(b[i], c200v * (fy - fz));
        }
    }
#endif
    for (; i < width; ++i) {
        const float rv = R[i];
        const float gv = G[i];
        const float bv = B[i];
        float x = wp[0][0] * rv + wp[0][1] * gv + wp[0][2] * bv;
        float y = wp[1][0] * rv + wp[1][1] * gv + wp[1][2] * bv;
        float z = wp[2][0] * rv + wp[2][1] * gv + wp[2][2] * bv;
        float fx, fy, fz;

        fx = computeXYZ2Lab(x);
        fy = computeXYZ2Lab(y);
        fz = computeXYZ2Lab(z);

        L[i] = computeXYZ2LabY(y);
        a[i] = 500.0f * (fx - fy);
        b[i] = 200.0f * (fy - fz);
    }
}

void Color::RGB2L(float *R, float *G, float *B, float *L, const float wp[3][3],
                  int width)
{

#ifdef ART_SIMD
    vfloat minvalfv = F2V(0.f);
    vfloat maxvalfv = F2V(MAXVALF);
#endif
    int i = 0;

#ifdef ART_SIMD
    for (; i < width - 3; i += 4) {
        const vfloat rv = LVFU(R[i]);
        const vfloat gv = LVFU(G[i]);
        const vfloat bv = LVFU(B[i]);
        const vfloat yv =
            F2V(wp[1][0]) * rv + F2V(wp[1][1]) * gv + F2V(wp[1][2]) * bv;

        vmask maxMask = vmaskf_gt(yv, maxvalfv);
        vmask minMask = vmaskf_lt(yv, minvalfv);
        if (_mm_movemask_ps((vfloat)vorm(maxMask, minMask))) {
            // take slower code path for all 4 pixels if one of the values is >
            // MAXVALF. Still faster than non SSE2 version
            for (int k = 0; k < 4; ++k) {
                float y = yv[k];
                L[i + k] = computeXYZ2LabY(y);
            }
        } else {
            STVFU(L[i], cachefy[yv]);
        }
    }
#endif
    for (; i < width; ++i) {
        const float rv = R[i];
        const float gv = G[i];
        const float bv = B[i];
        float y = wp[1][0] * rv + wp[1][1] * gv + wp[1][2] * bv;

        L[i] = computeXYZ2LabY(y);
    }
}

void Color::XYZ2Lab(float X, float Y, float Z, float &L, float &a, float &b)
{

    float x = X / D50x;
    float z = Z / D50z;
    float y = Y;
    float fx, fy, fz;

    fx = computeXYZ2Lab(x);
    fy = computeXYZ2Lab(y);
    fz = computeXYZ2Lab(z);

    L = computeXYZ2LabY(y);
    a = (500.0f * (fx - fy));
    b = (200.0f * (fy - fz));
}

#ifdef ART_SIMD
void Color::XYZ2Lab(vfloat X, vfloat Y, vfloat Z, vfloat &L, vfloat &a,
                    vfloat &b)
{
    vfloat minvalfv = F2V(0.f);
    vfloat maxvalfv = F2V(MAXVALF);
    vfloat c500v = F2V(500.f);
    vfloat c200v = F2V(200.f);

    X = X / F2V(D50x);
    Z = Z / F2V(D50z);

    vmask maxMask = vmaskf_gt(vmaxf(X, vmaxf(Y, Z)), maxvalfv);
    vmask minMask = vmaskf_lt(vminf(X, vminf(Y, Z)), minvalfv);
    if (_mm_movemask_ps((vfloat)maxMask) || _mm_movemask_ps((vfloat)minMask)) {
        // take slower code path for all 4 pixels if one of the values is
        // > MAXVALF. Still faster than non SSE2 version
        for (int k = 0; k < 4; ++k) {
            float x = X[k];
            float y = Y[k];
            float z = Z[k];
            float fx = computeXYZ2Lab(x);
            float fy = computeXYZ2Lab(y);
            float fz = computeXYZ2Lab(z);

            L[k] = computeXYZ2LabY(y);
            a[k] = (500.f * (fx - fy));
            b[k] = (200.f * (fy - fz));
        }
    } else {
        const vfloat fx = cachef[X];
        const vfloat fy = cachef[Y];
        const vfloat fz = cachef[Z];

        L = cachefy[Y];
        a = c500v * (fx - fy);
        b = c200v * (fy - fz);
    }
}
#endif


void Color::Lab2Lch(float a, float b, float &c, float &h)
{
    c = (sqrtf(a * a + b * b)) / 327.68f;
    h = xatan2f(b, a);
}

#ifdef ART_SIMD
void Color::Lab2Lch(float *a, float *b, float *c, float *h, int w)
{
    int i = 0;
    vfloat c327d68v = F2V(327.68f);
    for (; i < w - 3; i += 4) {
        vfloat av = LVFU(a[i]);
        vfloat bv = LVFU(b[i]);
        STVFU(c[i], vsqrtf(SQRV(av) + SQRV(bv)) / c327d68v);
        STVFU(h[i], xatan2f(bv, av));
    }
    for (; i < w; ++i) {
        float ai = a[i], bi = b[i];
        c[i] = sqrtf(SQR(ai) + SQR(bi)) / 327.68f;
        h[i] = xatan2f(bi, ai);
    }
}
#endif


namespace {

inline void filmlike_clip_rgb_tone(float *r, float *g, float *b, const float L)
{
    float r_ = *r > L ? L : *r;
    float b_ = *b > L ? L : *b;
    float g_ = b_ + ((r_ - b_) * (*g - *b) / (*r - *b));
    *r = r_;
    *g = g_;
    *b = b_;
}

} // namespace

void Color::filmlike_clip(float *r, float *g, float *b, float Lmax)
{
    // This is Adobe's hue-stable film-like curve with a diagonal, ie only used
    // for clipping. Can probably be further optimized.
    const float L = Lmax; // 65535.0;

    if (*r >= *g) {
        if (*g > *b) { // Case 1: r >= g >  b
            filmlike_clip_rgb_tone(r, g, b, L);
        } else if (*b > *r) { // Case 2: b >  r >= g
            filmlike_clip_rgb_tone(b, r, g, L);
        } else if (*b > *g) { // Case 3: r >= b >  g
            filmlike_clip_rgb_tone(r, b, g, L);
        } else { // Case 4: r >= g == b
            *r = *r > L ? L : *r;
            *g = *g > L ? L : *g;
            *b = *g;
        }
    } else {
        if (*r >= *b) { // Case 5: g >  r >= b
            filmlike_clip_rgb_tone(g, r, b, L);
        } else if (*b > *g) { // Case 6: b >  g >  r
            filmlike_clip_rgb_tone(b, g, r, L);
        } else { // Case 7: g >= b >  r
            filmlike_clip_rgb_tone(g, b, r, L);
        }
    }
}

void Color::yuv2hsl(float u, float v, float &h, float &s)
{
    s = std::sqrt(SQR(u) + SQR(v));
    h = xatan2f(u, v);
}

void Color::hsl2yuv(float h, float s, float &u, float &v)
{
    float2 sincosval = xsincosf(h);
    u = s * sincosval.x;
    v = s * sincosval.y;
}

void Color::xyz2jzazbz(float X, float Y, float Z, float &Jz, float &az,
                       float &bz)
{
    const auto get_PQ = [&](float x) -> float {
        return (x >= 0.f && x <= 1.f) ? jzazbz_pq_[x * 65535.f] : PQ(x);
    };

    XYZ_D50_to_D65(X, Y, Z);
    auto Lp = get_PQ(0.674207838f * X + 0.382799340f * Y - 0.047570458f * Z);
    auto Mp = get_PQ(0.149284160f * X + 0.739628340f * Y + 0.083327300f * Z);
    auto Sp = get_PQ(0.070941080f * X + 0.174768000f * Y + 0.670970020f * Z);
    auto Iz = 0.5f * (Lp + Mp);
    az = 3.524000f * Lp - 4.066708f * Mp + 0.542708f * Sp;
    bz = 0.199076f * Lp + 1.096799f * Mp - 1.295875f * Sp;
    Jz = (0.44f * Iz) / (1.f - 0.56f * Iz) - 1.6295499532821566e-11f;
}

void Color::jzazbz2xyz(float Jz, float az, float bz, float &X, float &Y,
                       float &Z)
{
    const float pq_inv_max = jzazbzPQInvMax();
    const float pq_inv_scale = 65535.f / pq_inv_max;
    const auto get_PQ_inv = [&](float x) -> float {
        return (x >= 0.f && x <= pq_inv_max) ? jzazbz_pq_inv_[x * pq_inv_scale]
                                             : PQ_inv(x);
    };

    Jz = Jz + 1.6295499532821566e-11f;
    auto Iz = Jz / (0.44f + 0.56f * Jz);
    auto L = get_PQ_inv(Iz + 1.386050432715393e-1f * az +
                        5.804731615611869e-2f * bz);
    auto M = get_PQ_inv(Iz - 1.386050432715393e-1f * az -
                        5.804731615611891e-2f * bz);
    auto S = get_PQ_inv(Iz - 9.601924202631895e-2f * az -
                        8.118918960560390e-1f * bz);
    X = +1.661373055774069e+00f * L - 9.145230923250668e-01f * M +
        2.313620767186147e-01f * S;
    Y = -3.250758740427037e-01f * L + 1.571847038366936e+00f * M -
        2.182538318672940e-01f * S;
    Z = -9.098281098284756e-02f * L - 3.127282905230740e-01f * M +
        1.522766561305260e+00f * S;

    XYZ_D65_to_D50(X, Y, Z);
}

//-----------------------------------------------------------------------------
// oklab color space from https://bottosson.github.io/posts/oklab/
//-----------------------------------------------------------------------------


// https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-2-201807-I!!PDF-F.pdf
// Perceptual Quantization / SMPTE standard ST.2084
float Color::eval_PQ_curve(float x, bool oetf)
{
    constexpr float M1 = 2610.0 / 16384.0;
    constexpr float M2 = (2523.0 / 4096.0) * 128.0;
    constexpr float C1 = 3424.0 / 4096.0;
    constexpr float C2 = (2413.0 / 4096.0) * 32.0;
    constexpr float C3 = (2392.0 / 4096.0) * 32.0;

    if (x == 0.f) {
        return 0.f;
    }

    // 203 nits is Operational Target as Standardized by ITU-R BT.2408
    constexpr float sdr_peak_nits = 203.f;
    constexpr float scaling = 10000.f / sdr_peak_nits;
    float res = 0.f;
    if (oetf) {
        float p = std::pow(std::max(x, 0.f) / scaling, M1);
        float num = C1 + C2 * p;
        float den = 1.f + C3 * p;
        res = std::pow(num / den, M2);
    } else {
        float p = std::pow(x, 1.f / M2);
        float num = std::max(p - C1, 0.f);
        float den = C2 - C3 * p;
        res = std::pow(num / den, 1.f / M1) * scaling;
    }
    return res;
}

// https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.2100-2-201807-I!!PDF-F.pdf
// Hybrid Log-Gamma
float Color::eval_HLG_curve(float x, bool oetf)
{
    constexpr float A = 0.17883277f;
    constexpr float B = 0.28466892f;    // 1.f - 4.f * A
    constexpr float C = 0.55991072953f; // 0.5f - A * std::log(4.f * A)

    if (x == 0.f) {
        return 0.f;
    }

    constexpr float sdr_peak_nits = 203.f;
    constexpr float scaling = 1000.f / sdr_peak_nits;
    float res = 0.f;
    if (oetf) {
        float e = LIM01(x / scaling);
        res = (e <= 1.f / 12.f) ? std::sqrt(3.f * e)
                                : A * std::log(12.f * e - B) + C;
    } else {
        res = (x <= 0.5f) ? SQR(x) / 3.f : (std::exp((x - C) / A) + B) / 12.f;
        res *= scaling;
    }

    return res;
}


}} // namespace art::engine
