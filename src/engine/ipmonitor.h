/* -*- C++ -*-
 *
 *  This file is part of ART.
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

/*
 * Fast path for the output-profile -> monitor-profile conversion done by
 * ImProcFunctions::rgb2monitor() when both profiles are matrix/shaper ones.
 *
 * The lcms2 transform used there is built with cmsFLAGS_NOOPTIMIZE, so every
 * pixel goes through the curve and matrix stages one by one, evaluating the
 * parametric curves with pow().  For matrix/shaper profiles the whole
 * transform is just
 *
 *     encode_dst(M_dst^-1 * M_src * decode_src(rgb))
 *
 * (both PCS are D50, and a matrix/shaper profile has no black point, so BPC
 * and the rendering intent make no difference for relative colorimetric),
 * which can be done with a 3x3 matrix and 1D lookup tables built once per
 * profile change.
 */
#pragma once

#include "iccstore.h"
#include "linalgebra.h"
#include <lcms2.h>
#include <memory>
#include <vector>

namespace art { namespace engine {

class MonitorMatrixTransform {
public:
    /* Returns nullptr if either profile is not a matrix/shaper one with
     * invertible, monotonic curves, in which case the caller keeps using the
     * lcms2 transform. */
    static std::unique_ptr<MonitorMatrixTransform>
    create(cmsHPROFILE src, cmsHPROFILE dst)
    {
        std::unique_ptr<MonitorMatrixTransform> ret(
            new MonitorMatrixTransform());
        return ret->init(src, dst) ? std::move(ret) : nullptr;
    }

    ~MonitorMatrixTransform()
    {
        for (int c = 0; c < 3; ++c) {
            if (dec_curve_[c]) {
                cmsFreeToneCurve(dec_curve_[c]);
            }
        }
    }

    /* in: W RGB triplets in the source space, 0..1; out: encoded monitor
     * RGB, same layout (not clipped, like cmsDoTransform's float output). */
    void operator()(const float *in, float *out, int W) const
    {
        const int W3 = W * 3;
        for (int x = 0; x < W3; x += 3) {
            float v[3];
            for (int c = 0; c < 3; ++c) {
                v[c] = decode(c, in[x + c]);
            }
            for (int c = 0; c < 3; ++c) {
                const float l = m_[c][0] * v[0] + m_[c][1] * v[1] +
                                m_[c][2] * v[2];
                out[x + c] = encode(c, l);
            }
        }
    }

    /* Same as operator(), but for linear working-space input: `a` is the
     * matrix from the working space to the (linear) output profile. Going
     * through the output profile's curve and back is the identity, so only
     * its clipping of negative components is kept, to still show the image
     * as the output profile can represent it. in: W RGB triplets, 0..1 */
    void from_linear(const float *in, const Mat33<float> &a, float *out,
                     int W) const
    {
        const int W3 = W * 3;
        for (int x = 0; x < W3; x += 3) {
            float v[3];
            for (int c = 0; c < 3; ++c) {
                const float l = a[c][0] * in[x] + a[c][1] * in[x + 1] +
                                a[c][2] * in[x + 2];
                v[c] = l > 0.f ? l : 0.f;
            }
            for (int c = 0; c < 3; ++c) {
                out[x + c] = encode(c, m_[c][0] * v[0] + m_[c][1] * v[1] +
                                           m_[c][2] * v[2]);
            }
        }
    }

private:
    static constexpr int DEC_SIZE = 4096;
    static constexpr int ENC_SIZE = 16384;

    MonitorMatrixTransform()
    {
        for (int c = 0; c < 3; ++c) {
            dec_curve_[c] = nullptr;
        }
    }

    static bool read_curves(cmsHPROFILE prof, cmsToneCurve *out[3])
    {
        const cmsTagSignature tags[3] = {cmsSigRedTRCTag, cmsSigGreenTRCTag,
                                         cmsSigBlueTRCTag};
        for (int c = 0; c < 3; ++c) {
            out[c] = static_cast<cmsToneCurve *>(cmsReadTag(prof, tags[c]));
            if (!out[c]) {
                return false;
            }
        }
        return true;
    }

    bool init(cmsHPROFILE src, cmsHPROFILE dst)
    {
        Mat33<float> ms, md, mdi;
        if (!ICCStore::getProfileMatrix(src, ms) ||
            !ICCStore::getProfileMatrix(dst, md) || !inverse(md, mdi)) {
            return false;
        }
        m_ = dot_product(mdi, ms);

        cmsToneCurve *sc[3];
        cmsToneCurve *dc[3];
        if (!read_curves(src, sc) || !read_curves(dst, dc)) {
            return false;
        }

        dec_lut_.resize(3 * (DEC_SIZE + 1));
        enc_lut_.resize(3 * (ENC_SIZE + 1));
        for (int c = 0; c < 3; ++c) {
            dec_curve_[c] = cmsDupToneCurve(sc[c]);
            cmsToneCurve *rev = cmsReverseToneCurve(dc[c]);
            if (!dec_curve_[c] || !rev) {
                if (rev) {
                    cmsFreeToneCurve(rev);
                }
                return false;
            }
            float *dl = &dec_lut_[c * (DEC_SIZE + 1)];
            for (int i = 0; i <= DEC_SIZE; ++i) {
                dl[i] = cmsEvalToneCurveFloat(
                    dec_curve_[c], float(std::min(i, DEC_SIZE - 1)) /
                                       float(DEC_SIZE - 1));
            }
            dl[DEC_SIZE] = dl[DEC_SIZE - 1];
            float *el = &enc_lut_[c * (ENC_SIZE + 1)];
            for (int i = 0; i < ENC_SIZE; ++i) {
                el[i] = cmsEvalToneCurveFloat(rev, float(i) /
                                                       float(ENC_SIZE - 1));
            }
            el[ENC_SIZE] = el[ENC_SIZE - 1];
            cmsFreeToneCurve(rev);
            // the clamping in encode() assumes the curve maps [0, 1] onto
            // itself
            if (std::abs(el[0]) > 1e-4f ||
                std::abs(el[ENC_SIZE - 1] - 1.f) > 1e-4f) {
                return false;
            }
        }
        return true;
    }

    float decode(int c, float x) const
    {
        if (!(x >= 0.f && x <= 1.f)) {
            // outside the table: evaluate the curve, like lcms2 does (this
            // also handles NaN by letting the curve decide)
            return cmsEvalToneCurveFloat(dec_curve_[c], x);
        }
        const float *l = &dec_lut_[c * (DEC_SIZE + 1)];
        const float p = x * float(DEC_SIZE - 1);
        const int i = int(p);
        const float f = p - float(i);
        return l[i] + f * (l[i + 1] - l[i]);
    }

    float encode(int c, float x) const
    {
        // the result is clipped to 0..1 by the caller, and the curve is
        // monotonic with 0 -> 0 and 1 -> 1
        if (!(x > 0.f)) {
            return 0.f;
        }
        if (x >= 1.f) {
            return 1.f;
        }
        const float *l = &enc_lut_[c * (ENC_SIZE + 1)];
        const float p = x * float(ENC_SIZE - 1);
        const int i = int(p);
        const float f = p - float(i);
        return l[i] + f * (l[i + 1] - l[i]);
    }

    Mat33<float> m_;
    cmsToneCurve *dec_curve_[3];
    std::vector<float> dec_lut_;
    std::vector<float> enc_lut_;
};

}} // namespace art::engine
