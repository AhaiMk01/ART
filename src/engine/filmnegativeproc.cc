/*
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2019 Alberto Romei <aldrop8@gmail.com>
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
 *  along with RawTherapee.  If not, see <https://www.gnu.org/licenses/>.
 */
#include <algorithm>
#include <cmath>
#include <iostream>
#include <locale>
#include <sstream>

#include "imagefloat.h"
#include "improccoordinator.h"
#include "improcfun.h"
#include "rawimage.h"
#include "rawimagesource.h"

#include "coord.h"
#include "opthelper.h"
#include "pixelsmap.h"
#include "procparams.h"
#include "rt_algo.h"
#include "rtengine.h"
#include "rtthumbnail.h"
#include "settings.h"
#include "sleef.h"
// #define BENCHMARK
// #include "StopWatch.h"
#include "color.h"
#include "iccstore.h"
#include "rt_math.h"
#include "papercurve.h"

namespace art { namespace engine {



extern const Settings *settings;


namespace {
using art::engine::CLIP;
using art::engine::Color;
using art::engine::ColorTemp;
using art::engine::Coord2D;
using art::engine::findMinMaxPercentile;
using art::engine::ICCStore;
using art::engine::Imagefloat;
using art::engine::ImageSource;
using art::engine::MAXVALF;
using art::engine::settings;
using art::engine::TMatrix;
using art::engine::procparams::ColorManagementParams;
using art::engine::procparams::FilmNegativeParams;
using art::engine::procparams::RAWParams;
using RGB = art::engine::procparams::FilmNegativeParams::RGB;

Coord2D translateCoord(art::engine::ImProcFunctions &ipf, int fw, int fh, int x,
                       int y)
{

    const std::vector<Coord2D> points = {Coord2D(x, y)};

    std::vector<Coord2D> red;
    std::vector<Coord2D> green;
    std::vector<Coord2D> blue;
    ipf.transCoord(fw, fh, points, red, green, blue);

    return green[0];
}

void getSpotAvgMax(ImageSource *imgsrc, ColorTemp currWB,
                   const art::engine::procparams::ProcParams &params, Coord2D p,
                   int tr, int spotSize, SpotSpace space, RGB &avg, RGB &max,
                   art::engine::gpu::Context *ctx)
{
    int x1 = MAX(0, (int)p.x - spotSize / 2);
    int y1 = MAX(0, (int)p.y - spotSize / 2);
    PreviewProps pp(x1, y1, spotSize, spotSize, 1);

    if (settings->verbose) {
        printf("Spot: %d,%d   %d,%d\n", x1, y1, x1 + spotSize / 2,
               y1 + spotSize / 2);
    }

    art::engine::Imagefloat spotImg(spotSize, spotSize);
    imgsrc->getImage(currWB, tr, &spotImg, pp, params.exposure, params.raw);

    auto avgMax = [spotSize, &spotImg](RGB &avg, RGB &max) -> void {
        avg = {};
        max = {};

        for (int i = 0; i < spotSize; ++i) {
            for (int j = 0; j < spotSize; ++j) {

                float r = spotImg.r(i, j);
                float g = spotImg.g(i, j);
                float b = spotImg.b(i, j);

                avg.r += r;
                avg.g += g;
                avg.b += b;
                max.r = MAX(max.r, r);
                max.g = MAX(max.g, g);
                max.b = MAX(max.b, b);
            }
        }

        avg.r /= (spotSize * spotSize);
        avg.g /= (spotSize * spotSize);
        avg.b /= (spotSize * spotSize);
    };

    if (space == SpotSpace::INPUT) {
        avgMax(avg, max);
    } else {
        // Convert spot image to current working space
        imgsrc->convertColorSpace(&spotImg, params.icm, currWB);

        avgMax(avg, max);

        // TODO handle custom color profile !
    }

    // Clip away zeroes or negative numbers, you never know
    avg.r = MAX(avg.r, 1.f);
    avg.g = MAX(avg.g, 1.f);
    avg.b = MAX(avg.b, 1.f);

    if (settings->verbose) {
        printf("Average Spot RGB: %f,%f,%f\n", avg.r, avg.g, avg.b);
    }
}

void calcMedians(const art::engine::Imagefloat *input, int x1, int y1, int x2,
                 int y2, float &rmed, float &gmed, float &bmed)
{
    using art::engine::findMinMaxPercentile;

    // Channel vectors to calculate medians
    std::vector<float> rv, gv, bv;

    const int sz = (x2 - x1) * (y2 - y1);
    rv.reserve(sz);
    gv.reserve(sz);
    bv.reserve(sz);

    for (int ii = y1; ii < y2; ii++) {
        for (int jj = x1; jj < x2; jj++) {
            rv.push_back(input->r(ii, jj));
            gv.push_back(input->g(ii, jj));
            bv.push_back(input->b(ii, jj));
        }
    }

    // Calculate channel medians of the specified area
    findMinMaxPercentile(rv.data(), rv.size(), 0.5f, rmed, 0.5f, rmed, true);
    findMinMaxPercentile(gv.data(), gv.size(), 0.5f, gmed, 0.5f, gmed, true);
    findMinMaxPercentile(bv.data(), bv.size(), 0.5f, bmed, 0.5f, bmed, true);
}

RGB getMedians(const art::engine::Imagefloat *input, int borderPercent)
{
    float rmed, gmed, bmed;
    // Cut 20% border from medians calculation. It will probably contain outlier
    // values from the film holder, which will bias the median result.
    const int bW = input->getWidth() * borderPercent / 100;
    const int bH = input->getHeight() * borderPercent / 100;
    calcMedians(input, bW, bH, input->getWidth() - bW, input->getHeight() - bH,
                rmed, gmed, bmed);

    if (settings->verbose) {
        printf("Channel medians: R=%g, G=%g, B=%g\n", rmed, gmed, bmed);
    }

    return {rmed, gmed, bmed};
}

/*
// TODO not needed for now
void convertColorSpace(Imagefloat* input, const TMatrix &src2xyz, const TMatrix
&xyz2dest)
{

#ifdef _OPENMP
    #pragma omp parallel for
#endif

    for (int i = 0; i < input->getHeight(); i++) {
        for (int j = 0; j < input->getWidth(); j++) {

            float newr = input->r(i, j);
            float newg = input->g(i, j);
            float newb = input->b(i, j);

            float x, y, z;
            Color::rgbxyz (newr, newg, newb, x, y, z, src2xyz);
            Color::xyz2rgb (x, y, z, newr, newg, newb, xyz2dest);

            input->r(i, j) = newr;
            input->g(i, j) = newg;
            input->b(i, j) = newb;

        }
    }
}
*/

enum class SourceTransfer { UNPROFILED_SCAN, RAW, PROFILED };

SourceTransfer sourceTransfer(bool isRaw, const ColorManagementParams &icm)
{
    if (isRaw) {
        return SourceTransfer::RAW;
    }
    if (icm.inputProfile == ColorManagementParams::NoProfileString) {
        return SourceTransfer::UNPROFILED_SCAN;
    }
    return SourceTransfer::PROFILED;
}

// Unity is a no-op. A non-unity override is applied only for an explicitly
// unprofiled non-RAW scan; otherwise it is left unapplied and reported.
float resolvedInputGamma(const FilmNegativeParams &params, SourceTransfer src,
                         ProgressListener *pl)
{
    if (params.inputGamma == 1.0) {
        return 1.f;
    }
    if (src == SourceTransfer::UNPROFILED_SCAN) {
        return static_cast<float>(params.inputGamma);
    }
    const char *why =
        src == SourceTransfer::RAW
            ? "RAW input is already linear. Set InputGamma to 1; a non-unity "
              "scanner override was not applied, to avoid double-decoding."
            : "this input is already profile-linearized. Set InputGamma to 1, "
              "or set the input profile to \"(none)\" for an explicitly "
              "unprofiled power-encoded non-RAW scan. The override was not "
              "applied, to avoid double-decoding.";
    std::cerr << "Film Negative: " << why << " (InputGamma=" << params.inputGamma
              << ")\n";
    if (pl) {
        pl->error(Glib::ustring("Film Negative: ") + why);
    }
    return 1.f;
}

// Always writes linear RGB (0..65535). TargetMode::CINEON is an export
// encoding, applied once in prepareFilmNegativeCineonExport, never here.
bool activeDensityMatrix(const FilmNegativeParams &params,
                         const ColorManagementParams &icm, ProgressListener *pl,
                         float M[9])
{
    using Preset = FilmNegativeParams::MatrixPreset;
    std::array<double, 9> coeffs = FilmNegativeParams::identityMatrix();
    if (params.matrixPreset == Preset::STATUS_M_REFERENCE) {
        coeffs = FilmNegativeParams::statusMReferenceMatrix();
    } else if (params.matrixPreset == Preset::CUSTOM) {
        coeffs = params.matrix;
    }
    for (int i = 0; i < 9; ++i) {
        if (!std::isfinite(coeffs[i])) {
            const char *why =
                "custom density matrix has a non-finite coefficient. "
                "Enter finite coefficients or select Identity.";
            std::cerr << "Film Negative: " << why << "\n";
            if (pl) {
                pl->error(Glib::ustring("Film Negative: ") + why);
            }
            return false;
        }
        M[i] = static_cast<float>(coeffs[i]);
    }
    if (params.matrixPreset == Preset::IDENTITY ||
        params.matrixBasis.empty()) {
        return true;
    }
    Glib::ustring message;
    if (FilmNegativeParams::matrixBasisMatches(params.matrixBasis,
                                               params.colorSpace, icm,
                                               message)) {
        return true;
    }
    std::cerr << "Film Negative: " << message << "\n";
    if (pl) {
        pl->error(Glib::ustring("Film Negative: ") + message);
    }
    return false;
}

void doProcessDensity(Imagefloat *input, Imagefloat *output,
                      const FilmNegativeParams &params, SourceTransfer src,
                      ProgressListener *pl, const float densityMatrix[9])
{
    input->syncCpu();
    output->syncCpuForWrite();

    const float S = 65535.f;
    const float inputGamma = resolvedInputGamma(params, src, pl);
    const float densityGamma = static_cast<float>(params.densityGamma);
    const float densityDmax = static_cast<float>(params.densityDmax);
    const float p = 0.7f;
    const float P = (params.filmType == FilmNegativeParams::FilmType::NEGATIVE)
                        ? (4.1f - densityDmax)
                        : 0.7f;

    const std::array<float, 3> channelGamma = {
        static_cast<float>(params.channelGamma[0]),
        static_cast<float>(params.channelGamma[1]),
        static_cast<float>(params.channelGamma[2])};

    const std::array<float, 3> rgbGains = {
        static_cast<float>(params.rgbGains[0]),
        static_cast<float>(params.rgbGains[1]),
        static_cast<float>(params.rgbGains[2])};

    float outputBlackOffset = static_cast<float>(params.outputBlackOffset);
    if (!std::isfinite(outputBlackOffset) || outputBlackOffset < 0.f) {
        outputBlackOffset = 0.f;
    }

    const bool paperTarget =
        params.targetMode == FilmNegativeParams::TargetMode::PAPER;
    bool paperOk = false;
    if (paperTarget) {
        if (!findPaperCurve(params.paperCurve)) {
            std::cerr << "Film Negative: unknown paper curve '"
                      << params.paperCurve
                      << "'; paper response not applied\n";
            if (pl) {
                pl->error(Glib::ustring::compose(
                    "Film Negative: unknown paper curve '%1'; paper response "
                    "not applied",
                    params.paperCurve));
            }
        } else if (!params.paperBasis.empty() &&
                   params.paperBasis !=
                       (params.colorSpace ==
                                FilmNegativeParams::ColorSpace::INPUT
                            ? "input"
                            : "working")) {
            std::cerr << "Film Negative: paper basis '" << params.paperBasis
                      << "' does not match the inversion color space; paper "
                         "response not applied. Rebind PaperBasis.\n";
            if (pl) {
                pl->error(
                    "Film Negative: paper basis does not match the inversion "
                    "color space; paper response not applied. Rebind "
                    "PaperBasis.");
            }
        } else {
            paperOk = true;
        }
    }
    const bool isNegative =
        (params.filmType == FilmNegativeParams::FilmType::NEGATIVE);

    const int rheight = input->getHeight();
    const int rwidth = input->getWidth();

    int nonFiniteCount = 0;

#ifdef _OPENMP
    #pragma omp parallel for reduction(+:nonFiniteCount)
#endif
    for (int i = 0; i < rheight; i++) {
        float *rlinein = input->r(i);
        float *glinein = input->g(i);
        float *blinein = input->b(i);
        float *rlineout = output->r(i);
        float *glineout = output->g(i);
        float *blineout = output->b(i);

        for (int j = 0; j < rwidth; ++j) {
            float in[3] = {rlinein[j], glinein[j], blinein[j]};
            float A[3];
            double density[3];

            for (int c = 0; c < 3; ++c) {
                float sample = in[c];
                float Tc;
                if (!std::isfinite(sample)) {
                    nonFiniteCount++;
                    Tc = 1e-10f;
                } else {
                    float norm = sample / S;
                    // sign(x)*|x|^InputGamma on normalized source RGB. Unity
                    // skips this so decoded linear values are unchanged.
                    if (inputGamma != 1.f) {
                        const float sign = norm < 0.f ? -1.f : 1.f;
                        norm = sign * std::pow(std::fabs(norm), inputGamma);
                    }
                    Tc = norm > 1e-10f ? norm : 1e-10f;
                }

                float Dc = -std::log10(Tc);
                float Ac;
                if (isNegative) {
                    Ac = densityDmax - p - densityGamma * (Dc - p);
                } else {
                    Ac = p + densityGamma * (Dc - p);
                }

                A[c] = Ac;
            }

            // B_i = P + sum_j M_ij * (A_j - P). Do not update channels
            // before the sum. Identity preset already forced M = I.
            float B[3];
            for (int row = 0; row < 3; ++row) {
                float sum = 0.f;
                for (int col = 0; col < 3; ++col) {
                    sum += densityMatrix[row * 3 + col] * (A[col] - P);
                }
                B[row] = P + sum;
            }

            for (int c = 0; c < 3; ++c) {
                density[c] = P + channelGamma[c] * (B[c] - P) - rgbGains[c];
            }

            // Cineon returns the linear result (encoding is a later ticket).
            // Unknown curves are not replaced by another response.
            if (paperOk) {
                applyPaperCurves(density[0], density[1], density[2],
                                 params.paperCurve);
            }

            for (int c = 0; c < 3; ++c) {
                float Lc = static_cast<float>(std::pow(10.0, -density[c]));
                // After linear conversion (and any paper response): subtract
                // the output black offset in normalized linear, floor at 0.
                // Do not upper-clamp. Never write inf/nan.
                if (!std::isfinite(Lc)) {
                    Lc = 0.f;
                }
                Lc -= outputBlackOffset;
                if (!(Lc > 0.f) || !std::isfinite(Lc)) {
                    Lc = 0.f;
                }
                float scaled = S * Lc;
                if (!std::isfinite(scaled)) {
                    scaled = 0.f;
                }
                if (c == 0) {
                    rlineout[j] = scaled;
                } else if (c == 1) {
                    glineout[j] = scaled;
                } else {
                    blineout[j] = scaled;
                }
            }
        }
    }

    if (nonFiniteCount > 0) {
        std::cerr << "Film Negative: non-finite sample detected in input image\n";
    }
}

/**
 * Perform actual film negative inversion process.
 * Returns true if the input and output reference values are not set in params;
 * refIn/refOut will be updated with median-based estimates. Otherwise, use
 * provided values in params and return false
 */
bool doProcess(Imagefloat *input, Imagefloat *output,
               const FilmNegativeParams &params,
               const ColorManagementParams &icmParams, RGB &refIn, RGB &refOut,
               SourceTransfer src, ProgressListener *pl)
{
    input->syncCpu();
    output->syncCpuForWrite();

    if (params.method == FilmNegativeParams::Method::DENSITY) {
        float densityMatrix[9];
        if (!activeDensityMatrix(params, icmParams, pl, densityMatrix)) {
            return false;
        }
        doProcessDensity(input, output, params, src, pl, densityMatrix);
        return false;
    }
    bool refsUpdated = false;

    float rexp = -(params.greenExp * params.redRatio);
    float gexp = -params.greenExp;
    float bexp = -(params.greenExp * params.blueRatio);

    // In case we are processing a thumbnail, reference values might not be set
    // in params, so make an estimate on the fly, using channel medians
    if (refIn.g <= 0.f) {
        // Calc medians, 20% border cut
        refIn = getMedians(input, 20);
        refsUpdated = true;
    } else {
        refIn = params.refInput;
    }

    if (refOut.g <= 0.f) {
        // Median will correspond to gray, 1/24th of max in the output
        refOut = {MAXVALF / 24.f, MAXVALF / 24.f, MAXVALF / 24.f};
        refsUpdated = true;
    } else {
        refOut = params.refOutput;
    }

    // Apply channel exponents to reference input values, and compute suitable
    // multipliers in order to reach reference output values.
    float rmult = refOut.r / pow_F(art::engine::max(refIn.r, 1.f), rexp);
    float gmult = refOut.g / pow_F(art::engine::max(refIn.g, 1.f), gexp);
    float bmult = refOut.b / pow_F(art::engine::max(refIn.b, 1.f), bexp);

#ifdef ART_SIMD
    const vfloat clipv = F2V(MAXVALF);
    const vfloat rexpv = F2V(rexp);
    const vfloat gexpv = F2V(gexp);
    const vfloat bexpv = F2V(bexp);
    const vfloat rmultv = F2V(rmult);
    const vfloat gmultv = F2V(gmult);
    const vfloat bmultv = F2V(bmult);
#endif

    const int rheight = input->getHeight();
    const int rwidth = input->getWidth();

    for (int i = 0; i < rheight; i++) {
        float *rlinein = input->r(i);
        float *glinein = input->g(i);
        float *blinein = input->b(i);
        float *rlineout = output->r(i);
        float *glineout = output->g(i);
        float *blineout = output->b(i);
        int j = 0;
#ifdef ART_SIMD

        for (; j < rwidth - 3; j += 4) {
            STVFU(rlineout[j],
                  vminf(rmultv * pow_F(LVFU(rlinein[j]), rexpv), clipv));
            STVFU(glineout[j],
                  vminf(gmultv * pow_F(LVFU(glinein[j]), gexpv), clipv));
            STVFU(blineout[j],
                  vminf(bmultv * pow_F(LVFU(blinein[j]), bexpv), clipv));
        }

#endif

        for (; j < rwidth; ++j) {
            rlineout[j] = CLIP(rmult * pow_F(rlinein[j], rexp));
            glineout[j] = CLIP(gmult * pow_F(glinein[j], gexp));
            blineout[j] = CLIP(bmult * pow_F(blinein[j], bexp));
        }
    }

    return refsUpdated;
}

} // namespace

bool art::engine::ImProcFunctions::filmNegativeProcess(Imagefloat *input,
                                                    Imagefloat *output,
                                                    FilmNegativeParams &fnp,
                                                    const RAWParams &rawParams,
                                                    const ImageSource *imgsrc,
                                                    const ColorTemp &currWB)
{
    // BENCHFUNMICRO

    if (!fnp.enabled) {
        return false;
    }

    if (fnp.method == FilmNegativeParams::Method::DENSITY) {
        fnp.backCompat = FilmNegativeParams::BackCompat::CURRENT;
        const SourceTransfer src =
            sourceTransfer(imgsrc && imgsrc->isRAW(), this->params->icm);
        float densityMatrix[9];
        if (!activeDensityMatrix(fnp, this->params->icm, plistener,
                                 densityMatrix)) {
            return false;
        }
        doProcessDensity(input, output, fnp, src, plistener, densityMatrix);
        return false;
    }

    bool paramsUpdated = false;

    RGB &refIn = fnp.refInput;
    RGB &refOut = fnp.refOutput;

    // If we're opening a profile from an older version, apply the proper
    // multiplier compensations to make processing backwards compatible.

    if (fnp.backCompat == FilmNegativeParams::BackCompat::V1) {
        // Calc medians, no border cut, compensate currWB in+out
        refIn = getMedians(input, 0);
        refOut = {MAXVALF / 24.f, MAXVALF / 24.f, MAXVALF / 24.f};

        std::array<float, 4> scale_mul = {1.f, 1.f, 1.f, 1.f};
        float autoGainComp, rm, gm, bm;
        imgsrc->getWBMults(currWB, params->raw, scale_mul, autoGainComp, rm, gm,
                           bm);

        refOut.r *= rm;
        refOut.g *= gm;
        refOut.b *= bm;

        paramsUpdated = true;

    } else if (fnp.backCompat == FilmNegativeParams::BackCompat::V2) {

        std::array<float, 4> scale_mul = {1.f, 1.f, 1.f, 1.f};
        float autoGainComp, rm, gm, bm;
        imgsrc->getWBMults(currWB, params->raw, scale_mul, autoGainComp, rm, gm,
                           bm);

        float rm2, gm2, bm2;
        imgsrc->getWBMults(art::engine::ColorTemp(3500., 1., 1., "Custom"),
                           params->raw, scale_mul, autoGainComp, rm2, gm2, bm2);
        float mg = art::engine::max(rm2, gm2, bm2);
        rm2 /= mg;
        gm2 /= mg;
        bm2 /= mg;

        if (fnp.refInput.g == 0.f) {
            // Calc medians, 20% border cut
            refIn = getMedians(input, 20);
            refOut = {MAXVALF / 24.f, MAXVALF / 24.f, MAXVALF / 24.f};
        } else if (fnp.refInput.g > 0.f) {
            // Calc refInput + refOutput from base levels, compensate currWB in,
            // 3500 out
            refIn = fnp.refInput;
            refIn.r *= rm * scale_mul[0];
            refIn.g *= gm * scale_mul[1];
            refIn.b *= bm * scale_mul[2];
            refOut = {MAXVALF / 512.f, MAXVALF / 512.f, MAXVALF / 512.f};
        }

        refOut.r *= rm * autoGainComp / rm2;
        refOut.g *= gm * autoGainComp / gm2;
        refOut.b *= bm * autoGainComp / bm2;

        paramsUpdated = true;
    }

    if (settings->verbose > 1 &&
        fnp.backCompat != FilmNegativeParams::BackCompat::CURRENT) {
        printf("Film Negative - Upgraded from V%d - refIn: R=%g G=%g B=%g "
               "refOut: R=%g G=%g B=%g\n",
               (int)fnp.backCompat, static_cast<double>(refIn.r),
               static_cast<double>(refIn.g), static_cast<double>(refIn.b),
               static_cast<double>(refOut.r), static_cast<double>(refOut.g),
               static_cast<double>(refOut.b));
    }

    // FilmNeg params are now upgraded to the latest version
    fnp.backCompat = FilmNegativeParams::BackCompat::CURRENT;

    // Perform actual inversion. Return true if reference values are computed
    // from medians
    paramsUpdated |= doProcess(
        input, output, fnp, this->params->icm, refIn, refOut,
        sourceTransfer(imgsrc && imgsrc->isRAW(), this->params->icm),
        plistener);

    return paramsUpdated;
}

void art::engine::ImProcFunctions::filmNegativeProcess(
    art::engine::Imagefloat *input, art::engine::Imagefloat *output,
    const procparams::FilmNegativeParams &params, bool rawSource)
{
    // BENCHFUNMICRO

    if (!params.enabled) {
        return;
    }

    RGB refIn = params.refInput, refOut = params.refOutput;

    doProcess(input, output, params, this->params->icm, refIn, refOut,
              sourceTransfer(rawSource, this->params->icm), plistener);
}

namespace {

// the average and maximum of one spot (frame pixel x, y), see sampleSpots()
void sampleSpot(ImProcFunctions &ipf, ImageSource *imgsrc,
                const ColorTemp &currWB, const ProcParams &params, int fw,
                int fh, int x, int y, int size, SpotSpace space,
                SpotSample &out)
{
    const int tr = getCoarseBitMask(params.coarse);
    Coord2D p = translateCoord(ipf, fw, fh, x, y);
    // keep the square inside the frame (unlike the GUI pickers, which can
    // hang over the right/bottom edge)
    if (fw >= size) {
        p.x = LIM<double>(p.x, size / 2, fw - size + size / 2);
    }
    if (fh >= size) {
        p.y = LIM<double>(p.y, size / 2, fh - size + size / 2);
    }
    RGB a, m;
    getSpotAvgMax(imgsrc, currWB, params, p, tr, size, space, a, m,
                  ipf.getGPUContext());
    out.x = x;
    out.y = y;
    out.avg[0] = a.r;
    out.avg[1] = a.g;
    out.avg[2] = a.b;
    out.max[0] = m.r;
    out.max[1] = m.g;
    out.max[2] = m.b;
}

} // namespace

SpotStatus checkSpots(int fw, int fh, const SpotRequest &req,
                      SpotResult &res)
{
    res.width = fw;
    res.height = fh;
    for (auto &p : req.pos) {
        if (p.first < 0 || p.first >= fw || p.second < 0 || p.second >= fh) {
            res.error = "spot (" + std::to_string(p.first) + "," +
                        std::to_string(p.second) + ") is outside the frame " +
                        std::to_string(fw) + "x" + std::to_string(fh);
            return SpotStatus::OUT_OF_FRAME;
        }
    }
    return SpotStatus::OK;
}

SpotStatus sampleSpots(ImProcFunctions &ipf, ImageSource *imgsrc,
                       const ColorTemp &currWB, const ProcParams &params,
                       int fw, int fh, const SpotRequest &req, SpotResult &res)
{
    res.spots.clear();
    SpotStatus st = checkSpots(fw, fh, req, res);
    if (st != SpotStatus::OK) {
        return st;
    }
    for (auto &p : req.pos) {
        SpotSample s;
        sampleSpot(ipf, imgsrc, currWB, params, fw, fh, p.first, p.second,
                   req.size, req.space, s);
        res.spots.push_back(s);
    }
    return SpotStatus::OK;
}

std::string spotResultJson(const SpotResult &res)
{
    std::ostringstream o;
    o.imbue(std::locale::classic());
    o.precision(9);
    o << "{\"width\":" << res.width << ",\"height\":" << res.height
      << ",\"spots\":[";
    for (size_t i = 0; i < res.spots.size(); ++i) {
        const SpotSample &s = res.spots[i];
        o << (i ? "," : "") << "{\"x\":" << s.x << ",\"y\":" << s.y
          << ",\"avg\":[" << s.avg[0] << "," << s.avg[1] << "," << s.avg[2]
          << "],\"max\":[" << s.max[0] << "," << s.max[1] << ","
          << s.max[2] << "]}";
    }
    o << "]}";
    return o.str();
}

SpotStatus art::engine::ImProcCoordinator::sampleSpots(const SpotRequest &req,
                                                       SpotResult &res)
{
    art::utils::MyMutex::MyLock lock(mProcessing);

    if (!imgsrc || fw <= 0 || fh <= 0) {
        return SpotStatus::NOT_READY;
    }
    return art::engine::sampleSpots(ipf, imgsrc, currWB, params, fw, fh, req,
                                    res);
}

bool art::engine::ImProcCoordinator::getFilmNegativeSpot(int x, int y,
                                                      const int spotSize,
                                                      RGB &refInput,
                                                      RGB &refOutput)
{
    art::utils::MyMutex::MyLock lock(mProcessing);

    const int tr = getCoarseBitMask(params.coarse);

    const Coord2D p = translateCoord(ipf, fw, fh, x, y);

    // Get the average channel values from the sampled spot
    RGB avg, max;
    getSpotAvgMax(imgsrc, currWB, params, p, tr, spotSize,
                  params.filmNegative.colorSpace ==
                          art::engine::FilmNegativeParams::ColorSpace::INPUT
                      ? SpotSpace::INPUT
                      : SpotSpace::WORKING,
                  avg, max, ipf.getGPUContext());

    float rexp = -(params.filmNegative.greenExp * params.filmNegative.redRatio);
    float gexp = -params.filmNegative.greenExp;
    float bexp =
        -(params.filmNegative.greenExp * params.filmNegative.blueRatio);

    float rmult =
        params.filmNegative.refOutput.r /
        pow_F(art::engine::max(params.filmNegative.refInput.r, 1.f), rexp);
    float gmult =
        params.filmNegative.refOutput.g /
        pow_F(art::engine::max(params.filmNegative.refInput.g, 1.f), gexp);
    float bmult =
        params.filmNegative.refOutput.b /
        pow_F(art::engine::max(params.filmNegative.refInput.b, 1.f), bexp);

    refInput = avg;

    refOutput.r = rmult * pow_F(avg.r, rexp);
    refOutput.g = gmult * pow_F(avg.g, gexp);
    refOutput.b = bmult * pow_F(avg.b, bexp);

    return true;
}

// ---------- >>> legacy mode >>> ---------------

// For backwards compatibility with profiles saved by RT 5.7 - 5.8
void art::engine::Thumbnail::processFilmNegative(
    const procparams::ProcParams &params, const Imagefloat *baseImg,
    const int rwidth, const int rheight)
{

    // Channel exponents
    const float rexp =
        -params.filmNegative.redRatio * params.filmNegative.greenExp;
    const float gexp = -params.filmNegative.greenExp;
    const float bexp =
        -params.filmNegative.blueRatio * params.filmNegative.greenExp;

    const float MAX_OUT_VALUE = 65000.f;

    // Channel medians
    float rmed, gmed, bmed;

    // If using the old method, calculate medians on the whole image
    calcMedians(baseImg, 0, 0, rwidth, rheight, rmed, gmed, bmed);

    if (settings->verbose) {
        printf(
            "FilmNeg legacy V1 :: Thumbnail input channel medians: %g %g %g\n",
            rmed, gmed, bmed);
    }

    // Calculate output medians
    rmed = powf(rmed, rexp);
    gmed = powf(gmed, gexp);
    bmed = powf(bmed, bexp);

    // Calculate output multipliers so that the median value is 1/24 of the
    // output range.
    float rmult, gmult, bmult;
    rmult = (MAX_OUT_VALUE / 24.f) / rmed;
    gmult = (MAX_OUT_VALUE / 24.f) / gmed;
    bmult = (MAX_OUT_VALUE / 24.f) / bmed;

    float rsum = 0.f, gsum = 0.f, bsum = 0.f;

    for (int i = 0; i < rheight; i++) {
        for (int j = 0; j < rwidth; j++) {
            rsum += baseImg->r(i, j);
            gsum += baseImg->g(i, j);
            bsum += baseImg->b(i, j);
        }
    }

    const float ravg = rsum / (rheight * rwidth);
    const float gavg = gsum / (rheight * rwidth);
    const float bavg = bsum / (rheight * rwidth);

    // Shifting current WB multipliers, based on channel averages.
    rmult /= gavg / ravg;
    // gmult /= gAvg / gAvg;  green chosen as reference channel
    bmult /= gavg / bavg;

    if (settings->verbose) {
        printf(
            "FilmNeg legacy V1 :: Thumbnail computed multipliers: %g %g %g\n",
            static_cast<double>(rmult), static_cast<double>(gmult),
            static_cast<double>(bmult));
    }

#ifdef ART_SIMD
    const vfloat clipv = F2V(MAXVALF);
    const vfloat rexpv = F2V(rexp);
    const vfloat gexpv = F2V(gexp);
    const vfloat bexpv = F2V(bexp);
    const vfloat rmultv = F2V(rmult);
    const vfloat gmultv = F2V(gmult);
    const vfloat bmultv = F2V(bmult);
#endif

    for (int i = 0; i < rheight; i++) {
        float *rline = baseImg->r(i);
        float *gline = baseImg->g(i);
        float *bline = baseImg->b(i);
        int j = 0;
#ifdef ART_SIMD

        for (; j < rwidth - 3; j += 4) {
            STVFU(rline[j],
                  vminf(rmultv * pow_F(LVFU(rline[j]), rexpv), clipv));
            STVFU(gline[j],
                  vminf(gmultv * pow_F(LVFU(gline[j]), gexpv), clipv));
            STVFU(bline[j],
                  vminf(bmultv * pow_F(LVFU(bline[j]), bexpv), clipv));
        }

#endif

        for (; j < rwidth; ++j) {
            rline[j] = CLIP(rmult * pow_F(rline[j], rexp));
            gline[j] = CLIP(gmult * pow_F(gline[j], gexp));
            bline[j] = CLIP(bmult * pow_F(bline[j], bexp));
        }
    }
}

// For backwards compatibility with intermediate dev version (see
// filmneg_stable_mults branch)
void art::engine::Thumbnail::processFilmNegativeV2(
    const procparams::ProcParams &params, const Imagefloat *baseImg,
    const int rwidth, const int rheight)
{

    // Channel exponents
    const float rexp =
        -params.filmNegative.redRatio * params.filmNegative.greenExp;
    const float gexp = -params.filmNegative.greenExp;
    const float bexp =
        -params.filmNegative.blueRatio * params.filmNegative.greenExp;

    // Calculate output multipliers
    float rmult, gmult, bmult;

    const float MAX_OUT_VALUE = 65000.f;

    // If the film base values are not set in params, estimate multipliers from
    // each channel's median value.
    if (params.filmNegative.refInput.r <= 0.f) {

        // Channel medians
        float rmed, gmed, bmed;

        // The new method cuts out a 20% border from medians calculation.
        const int bW = rwidth * 20 / 100;
        const int bH = rheight * 20 / 100;
        calcMedians(baseImg, bW, bH, rwidth - bW, rheight - bH, rmed, gmed,
                    bmed);

        if (settings->verbose) {
            printf("FilmNeg legacy V2 :: Thumbnail input channel medians: %g "
                   "%g %g\n",
                   rmed, gmed, bmed);
        }

        // Calculate output medians
        rmed = powf(rmed, rexp);
        gmed = powf(gmed, gexp);
        bmed = powf(bmed, bexp);

        // Calculate output multipliers so that the median value is 1/24 of the
        // output range.
        rmult = (MAX_OUT_VALUE / 24.f) / rmed;
        gmult = (MAX_OUT_VALUE / 24.f) / gmed;
        bmult = (MAX_OUT_VALUE / 24.f) / bmed;

    } else {

        // Read film-base values from params
        float rbase = params.filmNegative.refInput.r; // redBase;
        float gbase = params.filmNegative.refInput.g; // greenBase;
        float bbase = params.filmNegative.refInput.b; // blueBase;

        // Reconstruct scale_mul coefficients from thumbnail metadata:
        //   redMultiplier / camwbRed is pre_mul[0]
        //   pre_mul[0] * scaleGain is scale_mul[0]
        // Apply channel scaling to raw (unscaled) input base values, to
        // match with actual (scaled) data in baseImg
        rbase *= (redMultiplier / camwbRed) * scaleGain;
        gbase *= (greenMultiplier / camwbGreen) * scaleGain;
        bbase *= (blueMultiplier / camwbBlue) * scaleGain;

        if (settings->verbose) {
            printf("FilmNeg legacy V2 :: Thumbnail input film base values: %g "
                   "%g %g\n",
                   rbase, gbase, bbase);
        }

        // Apply exponents to get output film base values
        rbase = powf(rbase, rexp);
        gbase = powf(gbase, gexp);
        bbase = powf(bbase, bexp);

        // Calculate multipliers so that film base value is 1/512th of the
        // output range.
        rmult = (MAX_OUT_VALUE / 512.f) / rbase;
        gmult = (MAX_OUT_VALUE / 512.f) / gbase;
        bmult = (MAX_OUT_VALUE / 512.f) / bbase;
    }

    // Get and un-apply multipliers to adapt the thumbnail to a known fixed WB
    // setting, as in the main image processing.

    double r, g, b;
    ColorTemp(3500., 1., 1., "Custom").getMultipliers(r, g, b);
    // iColorMatrix is cam_rgb
    const double rm =
        camwbRed / (iColorMatrix[0][0] * r + iColorMatrix[0][1] * g +
                    iColorMatrix[0][2] * b);
    const double gm =
        camwbGreen / (iColorMatrix[1][0] * r + iColorMatrix[1][1] * g +
                      iColorMatrix[1][2] * b);
    const double bm =
        camwbBlue / (iColorMatrix[2][0] * r + iColorMatrix[2][1] * g +
                     iColorMatrix[2][2] * b);

    // Normalize max WB multiplier to 1.f
    const double m = max(rm, gm, bm);
    rmult /= rm / m;
    gmult /= gm / m;
    bmult /= bm / m;

    if (settings->verbose) {
        printf(
            "FilmNeg legacy V2 :: Thumbnail computed multipliers: %g %g %g\n",
            static_cast<double>(rmult), static_cast<double>(gmult),
            static_cast<double>(bmult));
    }

#ifdef ART_SIMD
    const vfloat clipv = F2V(MAXVALF);
    const vfloat rexpv = F2V(rexp);
    const vfloat gexpv = F2V(gexp);
    const vfloat bexpv = F2V(bexp);
    const vfloat rmultv = F2V(rmult);
    const vfloat gmultv = F2V(gmult);
    const vfloat bmultv = F2V(bmult);
#endif

    for (int i = 0; i < rheight; i++) {
        float *rline = baseImg->r(i);
        float *gline = baseImg->g(i);
        float *bline = baseImg->b(i);
        int j = 0;
#ifdef ART_SIMD

        for (; j < rwidth - 3; j += 4) {
            STVFU(rline[j],
                  vminf(rmultv * pow_F(LVFU(rline[j]), rexpv), clipv));
            STVFU(gline[j],
                  vminf(gmultv * pow_F(LVFU(gline[j]), gexpv), clipv));
            STVFU(bline[j],
                  vminf(bmultv * pow_F(LVFU(bline[j]), bexpv), clipv));
        }

#endif

        for (; j < rwidth; ++j) {
            rline[j] = CLIP(rmult * pow_F(rline[j], rexp));
            gline[j] = CLIP(gmult * pow_F(gline[j], gexp));
            bline[j] = CLIP(bmult * pow_F(bline[j], bexp));
        }
    }
}

// ----------------- <<< legacy mode <<< ------------


namespace {

double cineonNormalized(double linear01, double referenceWhite)
{
    // Colour/OCIO Cineon: black 95/1023, reference white 685/1023.
    const double b = std::pow(10.0, (95.0 - 685.0) / 300.0);
    const double x = std::max(0.0, linear01) / referenceWhite;
    return (685.0 + 300.0 * std::log10(x * (1.0 - b) + b)) / 1023.0;
}

} // namespace

Glib::ustring prepareFilmNegativeCineonExport(
    IImagefloat *img, const procparams::FilmNegativeParams &fnp,
    const Glib::ustring &format, int bits, bool isFloat)
{
    if (fnp.targetMode != procparams::FilmNegativeParams::TargetMode::CINEON) {
        return Glib::ustring();
    }

    const bool tiff16 = format == "tif" && bits == 16 && !isFloat;
    if (!tiff16) {
        return Glib::ustring(
            "Cineon film-negative target requires a 16-bit integer TIFF; "
            "refusing to write another format");
    }
    if (!img || img->getType() != sImagefloat) {
        return Glib::ustring("Cineon export needs a floating-point image");
    }

    Imagefloat *out = static_cast<Imagefloat *>(img);
    out->syncCpuForWrite();

    double referenceWhite = fnp.cineonReferenceWhite;
    if (referenceWhite < 1e-6) {
        referenceWhite = 1e-6;
    } else if (referenceWhite > 1e6) {
        referenceWhite = 1e6;
    }

    const int height = out->getHeight();
    const int width = out->getWidth();
    for (int row = 0; row < height; ++row) {
        for (int col = 0; col < width; ++col) {
            auto quantize = [&](float v) -> float {
                double y = cineonNormalized(static_cast<double>(v) / 65535.0,
                                            referenceWhite);
                if (y < 0.0) {
                    y = 0.0;
                } else if (y > 1.0) {
                    y = 1.0;
                }
                return static_cast<float>(std::round(y * 65535.0));
            };
            out->r(row, col) = quantize(out->r(row, col));
            out->g(row, col) = quantize(out->g(row, col));
            out->b(row, col) = quantize(out->b(row, col));
        }
    }
    return Glib::ustring();
}

} } // namespace art::engine
