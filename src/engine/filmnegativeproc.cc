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
#include <array>
#include <limits>

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
#include "cineonlut.h"
#include "papercurve.h"
#include "../utils/multilangmgr.h"
#include "imageio.h"
#include "linalgebra.h"

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

void filmNegError(ProgressListener *pl, const Glib::ustring &msg)
{
    std::cerr << msg << "\n";
    if (pl) {
        pl->error(msg);
    }
}

// Unity is a no-op. A non-unity override is applied only for an explicitly
// unprofiled non-RAW scan. Otherwise the density inversion must not run.
bool resolveInputGamma(const FilmNegativeParams &params, SourceTransfer src,
                       ProgressListener *pl, float &gamma)
{
    if (params.inputGamma == 1.0) {
        gamma = 1.f;
        return true;
    }
    if (src == SourceTransfer::UNPROFILED_SCAN) {
        gamma = static_cast<float>(params.inputGamma);
        return true;
    }
    const char *key = src == SourceTransfer::RAW
                          ? "TP_FILMNEGATIVE_ERR_INPUT_GAMMA_RAW"
                          : "TP_FILMNEGATIVE_ERR_INPUT_GAMMA_PROFILED";
    filmNegError(pl, Glib::ustring::compose(art::utils::M(key),
                                            params.inputGamma));
    return false;
}

// Always writes linear RGB (0..65535). TargetMode::CINEON is an export
// encoding, applied once in prepareFilmNegativeCineonExport, never here.
bool activeDensityMatrix(const FilmNegativeParams &params,
                         const ColorManagementParams &icm, ProgressListener *pl,
                         const Glib::ustring &sourceId, float M[9])
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
            filmNegError(pl, art::utils::M(
                                 "TP_FILMNEGATIVE_ERR_MATRIX_NONFINITE"));
            return false;
        }
        M[i] = static_cast<float>(coeffs[i]);
    }
    if (params.matrixPreset == Preset::IDENTITY) {
        return true;
    }
    if (params.matrixBasis.empty()) {
        filmNegError(pl, art::utils::M(
                             "TP_FILMNEGATIVE_ERR_MATRIX_BASIS_EMPTY"));
        return false;
    }
    Glib::ustring message;
    if (FilmNegativeParams::matrixBasisMatches(
            params.matrixBasis, params.colorSpace, icm, params.inputGamma,
            sourceId, message)) {
        return true;
    }
    filmNegError(pl, message);
    return false;
}

bool paperBasisMatches(const FilmNegativeParams &params,
                       const ColorManagementParams &icm)
{
    const Glib::ustring &stored = params.paperBasis;
    const auto bar = stored.find('|');
    if (stored.empty() || bar == Glib::ustring::npos || bar == 0 ||
        bar + 1 >= stored.length()) {
        return false;
    }
    const Glib::ustring space = stored.substr(0, bar);
    const Glib::ustring profile = stored.substr(bar + 1);
    if (profile.empty()) {
        return false;
    }
    const bool input =
        params.colorSpace == FilmNegativeParams::ColorSpace::INPUT;
    if (space != (input ? "input" : "working")) {
        return false;
    }
    const Glib::ustring active =
        input ? icm.inputProfile : icm.workingProfile;
    return profile == active;
}

void leaveUnconverted(Imagefloat *input, Imagefloat *output)
{
    // Preserve the input on a validation failure; drivers abort processing.
    if (input != output) {
        input->copyTo(output);
    }
}

// Shared with the render path so a basis bound by one matches the other.
Glib::ustring filmNegSourceId(const std::string &camera)
{
    return camera.empty() ? Glib::ustring("Unknown") : Glib::ustring(camera);
}

// Rejects density parameters that would render NaN/black instead of failing.
bool validDensityParams(const FilmNegativeParams &params, ProgressListener *pl)
{
    bool ok = std::isfinite(params.inputGamma) && params.inputGamma > 0.0 &&
              std::isfinite(params.densityGamma) && params.densityGamma > 0.0 &&
              std::isfinite(params.densityDmax);
    for (int c = 0; c < 3 && ok; ++c) {
        ok = std::isfinite(params.channelGamma[c]) &&
             params.channelGamma[c] > 0.0 && std::isfinite(params.rgbGains[c]);
    }
    if (!ok) {
        filmNegError(pl, art::utils::M("TP_FILMNEGATIVE_ERR_DENSITY_PARAMS"));
    }
    return ok;
}

// Flare is a transmission fraction subtracted before the log; reject values
// that are not a plausible veiling-light level instead of rendering garbage.
bool validFlare(const FilmNegativeParams &params, ProgressListener *pl)
{
    bool ok = true;
    for (int c = 0; c < 3 && ok; ++c) {
        ok = std::isfinite(params.flare[c]) && params.flare[c] >= 0.0 &&
             params.flare[c] <= 0.5;
    }
    if (!ok) {
        filmNegError(pl, art::utils::M("TP_FILMNEGATIVE_ERR_FLARE"));
    }
    return ok;
}

bool doProcessDensity(Imagefloat *input, Imagefloat *output,
                      const FilmNegativeParams &params,
                      const ColorManagementParams &icm, SourceTransfer src,
                      ProgressListener *pl, const float densityMatrix[9])
{
    input->syncCpu();
    output->syncCpuForWrite();

    const float S = 65535.f;
    float inputGamma = 1.f;
    if (!validDensityParams(params, pl) || !validFlare(params, pl) ||
        !resolveInputGamma(params, src, pl, inputGamma)) {
        // Validation failures must not produce an inverted output.
        leaveUnconverted(input, output);
        return false;
    }
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

    const std::array<float, 3> flare = {
        static_cast<float>(params.flare[0]),
        static_cast<float>(params.flare[1]),
        static_cast<float>(params.flare[2])};

    float outputBlackOffset = static_cast<float>(params.outputBlackOffset);
    if (!std::isfinite(outputBlackOffset) || outputBlackOffset < 0.f) {
        outputBlackOffset = 0.f;
    }

    // A Cineon print LUT replaces the paper curve. Do not apply both.
    const bool cineonLutActive = !params.cineonLUT.empty();
    const bool paperTarget =
        params.targetMode == FilmNegativeParams::TargetMode::PAPER &&
        !cineonLutActive;
    bool paperOk = false;
    if (paperTarget) {
        if (!paperBasisMatches(params, icm)) {
            filmNegError(pl, art::utils::M("TP_FILMNEGATIVE_ERR_PAPER_BASIS"));
            leaveUnconverted(input, output);
            return false;
        }
        if (!findPaperCurve(params.paperCurve)) {
            filmNegError(pl, Glib::ustring::compose(
                                 art::utils::M("TP_FILMNEGATIVE_ERR_PAPER_CURVE"),
                                 params.paperCurve));
            leaveUnconverted(input, output);
            return false;
        }
        paperOk = true;
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
            if (!std::isfinite(in[0]) || !std::isfinite(in[1]) ||
                !std::isfinite(in[2])) {
                nonFiniteCount++;
                rlineout[j] = in[0];
                glineout[j] = in[1];
                blineout[j] = in[2];
                continue;
            }
            float A[3];
            double density[3];

            for (int c = 0; c < 3; ++c) {
                float sample = in[c];
                float norm = sample / S;
                // sign(x)*|x|^InputGamma on normalized source RGB. Unity
                // skips this so decoded linear values are unchanged.
                if (inputGamma != 1.f) {
                    const float sign = norm < 0.f ? -1.f : 1.f;
                    norm = sign * std::pow(std::fabs(norm), inputGamma);
                }
                // Veiling light is linear transmission: remove it before the
                // log, then the usual floor applies.
                norm -= flare[c];
                const float Tc = norm > 1e-10f ? norm : 1e-10f;

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
                if (!std::isfinite(Lc)) {
                    Lc = 0.f;
                }
                // A print LUT decodes to linear later. Offset applies to that
                // decoded result, not to the pre-LUT density inversion.
                if (!cineonLutActive) {
                    Lc -= outputBlackOffset;
                    if (!(Lc > 0.f) || !std::isfinite(Lc)) {
                        Lc = 0.f;
                    }
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
        filmNegError(pl, art::utils::M("TP_FILMNEGATIVE_ERR_NONFINITE"));
    }
    return nonFiniteCount == 0;
}

// NamiColor 3.1 log-channel alignment (Wavechaser/HikariDragon, GPL-3.0).
// https://github.com/Wavechaser/NamiColor/blob/main/NamiColor_dev/NamiColor_dev.c
// ART retains its selected INPUT/WORKING basis and a linear pixel buffer.
bool doProcessNamiColor(Imagefloat *input, Imagefloat *output,
                       const FilmNegativeParams &params, SourceTransfer src,
                       ProgressListener *pl, const float matrix[9])
{
    double denominator[3], shift[3];
    bool valid = std::isfinite(params.namicolorInputGain) &&
                 std::isfinite(params.namicolorMasterGain) &&
                 std::isfinite(params.namicolorMasterShift) &&
                 std::isfinite(params.inputGamma) && params.inputGamma > 0.0 &&
                 std::isfinite(params.cineonReferenceWhite) &&
                 params.cineonReferenceWhite > 0.0;
    if (!validFlare(params, pl)) {
        leaveUnconverted(input, output);
        return false;
    }
    for (int c = 0; c < 3; ++c) {
        denominator[c] = 1.0 - params.namicolorGain[c] -
                         params.namicolorMasterGain + params.namicolorBlack[c];
        shift[c] = params.namicolorShift[c] + params.namicolorMasterShift +
                   params.namicolorBlack[c];
        valid = valid && std::isfinite(params.namicolorGain[c]) &&
                std::isfinite(params.namicolorBlack[c]) &&
                std::isfinite(params.namicolorShift[c]) &&
                std::isfinite(denominator[c]) && denominator[c] > 0.0 &&
                std::isfinite(shift[c]);
    }
    if (!valid) {
        filmNegError(pl, art::utils::M("TP_FILMNEGATIVE_ERR_NAMICOLOR_PARAMS"));
        leaveUnconverted(input, output);
        return false;
    }
    double inverseDenominator[3];
    for (int c = 0; c < 3; ++c) {
        inverseDenominator[c] = 1.0 / denominator[c];
    }
    float inputGamma = 1.f;
    if (!resolveInputGamma(params, src, pl, inputGamma)) {
        leaveUnconverted(input, output);
        return false;
    }
    input->syncCpu();
    output->syncCpuForWrite();
    const bool negative =
        params.filmType == FilmNegativeParams::FilmType::NEGATIVE;
    // Legacy: q' = (q + a) / (1 + a), a = 93/1023 (q = 0 -> code 93).
    // CODE95: q' = lo + (1 - lo) q, lo = 95/1023 (q = 0 -> code 95).
    // Both map q = 1 to code 1023.
    const bool anchor95 =
        params.namicolorFitBaseAnchor ==
        FilmNegativeParams::FitBaseAnchor::CODE95;
    const double lift =
        !params.namicolorFitBase ? 0.0 : anchor95 ? 0.0 : 93.0 / 1023.0;
    const double inverseLiftScale = 1.0 / (1.0 + lift);
    const double fitLo =
        (params.namicolorFitBase && anchor95) ? 95.0 / 1023.0 : 0.0;
    bool applyMask = false;
    for (int i = 0; i < 9; ++i) {
        if (matrix[i] != (i % 4 == 0 ? 1.f : 0.f)) {
            applyMask = true;
            break;
        }
    }
    const double densityPivot = 0.7;
    const double log16 = applyMask ? std::log10(16.0) : 0.0;
    int nonFiniteCount = 0;
#ifdef _OPENMP
    #pragma omp parallel for reduction(+:nonFiniteCount)
#endif
    for (int row = 0; row < input->getHeight(); ++row) {
        const float *in[3] = {input->r(row), input->g(row), input->b(row)};
        float *out[3] = {output->r(row), output->g(row), output->b(row)};
        for (int col = 0; col < input->getWidth(); ++col) {
            double centeredDensity[3];
            if (applyMask) {
                bool finite = true;
                for (int c = 0; c < 3; ++c) {
                    double t = static_cast<double>(in[c][col]) / 65535.0;
                    if (!std::isfinite(t)) {
                        finite = false;
                        break;
                    }
                    if (inputGamma != 1.f) {
                        t = std::copysign(
                            std::pow(std::fabs(t), inputGamma), t);
                    }
                    t -= params.flare[c];
                    centeredDensity[c] =
                        -std::log10(std::max(t, 1e-10)) - densityPivot;
                }
                if (!finite) {
                    ++nonFiniteCount;
                    continue;
                }
            }
            for (int c = 0; c < 3; ++c) {
                double q;
                if (applyMask) {
                    const float *m = matrix + c * 3;
                    const double d = densityPivot +
                        m[0] * centeredDensity[0] +
                        m[1] * centeredDensity[1] +
                        m[2] * centeredDensity[2];
                    q = negative
                        ? 1.0 + params.namicolorInputGain * (d - log16)
                        : 0.8 - params.namicolorInputGain * d;
                } else {
                    // Preserve the original arithmetic for identity masks.
                    double transmission =
                        static_cast<double>(in[c][col]) / 65535.0;
                    if (!std::isfinite(transmission)) {
                        ++nonFiniteCount;
                        continue;
                    }
                    if (inputGamma != 1.f) {
                        transmission = std::copysign(
                            std::pow(std::fabs(transmission), inputGamma),
                            transmission);
                    }
                    transmission -= params.flare[c];
                    transmission = std::max(transmission, 1e-10);
                    q = negative
                        ? 1.0 - params.namicolorInputGain *
                                    std::log10(16.0 * transmission)
                        : 0.8 + params.namicolorInputGain *
                                    std::log10(transmission);
                }
                q = (q + shift[c]) * inverseDenominator[c];
                if (fitLo != 0.0) {
                    q = fitLo + (1.0 - fitLo) * q;
                } else {
                    q = (q + lift) * inverseLiftScale;
                }
                if (!std::isfinite(q)) {
                    ++nonFiniteCount;
                    continue;
                }
                const float linear = static_cast<float>(
                    decodeFilmCineon(q, params.cineonReferenceWhite) * 65535.0);
                if (!std::isfinite(linear)) {
                    ++nonFiniteCount;
                    continue;
                }
                out[c][col] = linear;
            }
        }
    }
    if (nonFiniteCount) {
        filmNegError(pl, art::utils::M("TP_FILMNEGATIVE_ERR_NONFINITE"));
        return false;
    }
    return true;
}

bool processLinearFilm(Imagefloat *input, Imagefloat *output,
                       const FilmNegativeParams &params,
                       const ColorManagementParams &icm, SourceTransfer src,
                       const Glib::ustring &sourceId, ProgressListener *pl)
{
    float matrix[9];
    if (!activeDensityMatrix(params, icm, pl, sourceId, matrix)) {
        leaveUnconverted(input, output);
        return false;
    }
    if (params.method == FilmNegativeParams::Method::NAMICOLOR) {
        return doProcessNamiColor(input, output, params, src, pl, matrix);
    }
    return doProcessDensity(input, output, params, icm, src, pl, matrix);
}

// The legacy route runs the cube before the input->working conversion, while
// the primaries map assumes working-space pixels: refuse that combination.
bool legacyInputLutPrimariesOk(const FilmNegativeParams &params,
                               ProgressListener *pl)
{
    if (params.cineonLUT.empty() ||
        (params.cineonLUTInputPrimaries.empty() &&
         params.cineonLUTOutputPrimaries.empty())) {
        return true;
    }
    filmNegError(pl, art::utils::M("TP_FILMNEGATIVE_ERR_LEGACY_LUT_PRIMARIES"));
    return false;
}

bool legacyInputLut(const FilmNegativeParams &params)
{
    return params.method == FilmNegativeParams::Method::DENSITY &&
           params.colorSpace == FilmNegativeParams::ColorSpace::INPUT &&
           params.cineonLUTStage ==
               FilmNegativeParams::CineonLUTStage::BEFORE_GRADE &&
           params.legacyInputLUT;
}

/**
 * Perform actual film negative inversion process.
 * Returns true if the input and output reference values are not set in params;
 * refIn/refOut will be updated with median-based estimates. Otherwise, use
 * provided values in params and return false
 */
bool doProcess(Imagefloat *input, Imagefloat *output,
               const FilmNegativeParams &params, RGB &refIn, RGB &refOut)
{
    input->syncCpu();
    output->syncCpuForWrite();

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
    // Power-law ignores the dormant Density/NamiColor LUT controls.
    return refsUpdated;
}

// Printer-light gains that map a rebate sample to density 4 (linear 1e-4)
// before paper, LUT, and black offset. C is the matrix/channel-adjusted
// density with the current RGBGains omitted. Writes gains only if every
// channel is finite and inside [-3, 3].
bool filmBaseGainsFromAverage(const float avg[3],
                              const FilmNegativeParams &params,
                              const ColorManagementParams &icm, bool isRaw,
                              const Glib::ustring &sourceId,
                              std::array<double, 3> &gains)
{
    if (params.method != FilmNegativeParams::Method::DENSITY ||
        params.filmType != FilmNegativeParams::FilmType::NEGATIVE) {
        return false;
    }
    float densityMatrix[9];
    if (!activeDensityMatrix(params, icm, nullptr, sourceId, densityMatrix)) {
        return false;
    }

    float inputGamma = 1.f;
    if (!validDensityParams(params, nullptr) || !validFlare(params, nullptr) ||
        !resolveInputGamma(params, sourceTransfer(isRaw, icm), nullptr,
                           inputGamma)) {
        return false;
    }
    const float S = 65535.f;
    const float densityGamma = static_cast<float>(params.densityGamma);
    const float densityDmax = static_cast<float>(params.densityDmax);
    const float p = 0.7f;
    const float P = 4.1f - densityDmax;
    const float channelGamma[3] = {
        static_cast<float>(params.channelGamma[0]),
        static_cast<float>(params.channelGamma[1]),
        static_cast<float>(params.channelGamma[2])};

    float A[3];
    for (int c = 0; c < 3; ++c) {
        if (!std::isfinite(avg[c]) || !(avg[c] > 0.f)) {
            return false;
        }
        float norm = avg[c] / S;
        if (inputGamma != 1.f) {
            const float sign = norm < 0.f ? -1.f : 1.f;
            norm = sign * std::pow(std::fabs(norm), inputGamma);
        }
        if (!std::isfinite(norm)) {
            return false;
        }
        // Same veiling-light subtraction as the render, so picks match it.
        norm -= static_cast<float>(params.flare[c]);
        const float Tc = norm > 1e-10f ? norm : 1e-10f;
        const float Dc = -std::log10(Tc);
        A[c] = densityDmax - p - densityGamma * (Dc - p);
        if (!std::isfinite(A[c])) {
            return false;
        }
    }

    float B[3];
    for (int row = 0; row < 3; ++row) {
        float sum = 0.f;
        for (int col = 0; col < 3; ++col) {
            sum += densityMatrix[row * 3 + col] * (A[col] - P);
        }
        B[row] = P + sum;
    }

    std::array<double, 3> computed;
    for (int c = 0; c < 3; ++c) {
        // Current printer lights are not part of C.
        const float density = P + channelGamma[c] * (B[c] - P);
        const double gain = static_cast<double>(density) - 4.0;
        if (!std::isfinite(gain) || gain < -3.0 || gain > 3.0) {
            return false;
        }
        computed[c] = gain;
    }
    gains = computed;
    return true;
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
    filmNegContractFailed = false;
    if (!fnp.enabled) {
        return false;
    }

    const FramesMetaData *meta =
        imgsrc ? const_cast<ImageSource *>(imgsrc)->getMetaData() : nullptr;
    const std::string camera = meta ? meta->getCamera() : std::string();
    const Glib::ustring sourceId = filmNegSourceId(camera);

    if (fnp.method != FilmNegativeParams::Method::POWER_LAW) {
        fnp.backCompat = FilmNegativeParams::BackCompat::CURRENT;
        const SourceTransfer src =
            sourceTransfer(imgsrc && imgsrc->isRAW(), this->params->icm);
        filmNegContractFailed = !processLinearFilm(
            input, output, fnp, this->params->icm, src, sourceId, plistener);
        if (!filmNegContractFailed && legacyInputLut(fnp)) {
            filmNegContractFailed =
                !legacyInputLutPrimariesOk(fnp, plistener) ||
                !applyCineonPrintLut(output, fnp, this->params->icm, plistener);
        }
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
    paramsUpdated |= doProcess(input, output, fnp, refIn, refOut);

    return paramsUpdated;
}

void art::engine::ImProcFunctions::filmNegativeProcess(
    art::engine::Imagefloat *input, art::engine::Imagefloat *output,
    const procparams::FilmNegativeParams &params, bool rawSource,
    const Glib::ustring &sourceId)
{
    filmNegContractFailed = false;
    if (!params.enabled) {
        return;
    }
    const SourceTransfer src = sourceTransfer(rawSource, this->params->icm);
    if (params.method != FilmNegativeParams::Method::POWER_LAW) {
        filmNegContractFailed = !processLinearFilm(
            input, output, params, this->params->icm, src, sourceId, plistener);
        if (!filmNegContractFailed && legacyInputLut(params)) {
            filmNegContractFailed =
                !legacyInputLutPrimariesOk(params, plistener) ||
                !applyCineonPrintLut(output, params, this->params->icm,
                                     plistener);
        }
        return;
    }
    RGB refIn = params.refInput, refOut = params.refOutput;
    doProcess(input, output, params, refIn, refOut);
}

bool art::engine::ImProcFunctions::filmNegativeApplyLut(
    Imagefloat *img, FilmNegativeParams::CineonLUTStage stage)
{
    const FilmNegativeParams &fnp = params->filmNegative;
    if (!fnp.enabled) {
        // A stale failure from a previous enabled run must not block a
        // pipeline that no longer runs the tool.
        filmNegContractFailed = false;
        return true;
    }
    if (filmNegContractFailed) {
        return false;
    }
    if (fnp.method == FilmNegativeParams::Method::POWER_LAW ||
        fnp.cineonLUT.empty()) {
        return true;
    }
    if (fnp.cineonLUTStage != FilmNegativeParams::CineonLUTStage::BEFORE_GRADE &&
        fnp.cineonLUTStage != FilmNegativeParams::CineonLUTStage::AFTER_GRADE) {
        filmNegError(plistener, art::utils::M("TP_FILMNEGATIVE_ERR_LUT_STAGE"));
        filmNegContractFailed = true;
        return false;
    }
    if (fnp.cineonLUTStage != stage || legacyInputLut(fnp)) {
        return true;
    }
    img->setMode(Imagefloat::Mode::RGB, multiThread);
    filmNegContractFailed =
        !applyCineonPrintLut(img, fnp, params->icm, plistener);
    return !filmNegContractFailed;
}

bool art::engine::ImProcFunctions::filmNegativeApplyLutAfterGrade(
    Imagefloat *img)
{
    return filmNegativeApplyLut(
        img, FilmNegativeParams::CineonLUTStage::AFTER_GRADE);
}

namespace {

// the centre of the spot square (frame pixel x, y), mapped through the coarse
// transform and kept inside the frame (unlike the GUI pickers, which can hang
// over the right/bottom edge)
Coord2D spotCentre(ImProcFunctions &ipf, int fw, int fh, int x, int y,
                   int size)
{
    Coord2D p = translateCoord(ipf, fw, fh, x, y);
    if (fw >= size) {
        p.x = LIM<double>(p.x, size / 2, fw - size + size / 2);
    }
    if (fh >= size) {
        p.y = LIM<double>(p.y, size / 2, fh - size + size / 2);
    }
    return p;
}

// the average and maximum of one spot (frame pixel x, y), see sampleSpots()
void sampleSpot(ImProcFunctions &ipf, ImageSource *imgsrc,
                const ColorTemp &currWB, const ProcParams &params, int fw,
                int fh, int x, int y, int size, SpotSpace space,
                SpotSample &out)
{
    const int tr = getCoarseBitMask(params.coarse);
    const Coord2D p = spotCentre(ipf, fw, fh, x, y, size);
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

// the CONVERTED / CINEON spots, defined at the end of this file
SpotStatus sampleSpotsStage(ImProcFunctions &ipf, ImageSource *imgsrc,
                            const ColorTemp &currWB, const ProcParams &params,
                            int fw, int fh, const SpotRequest &req,
                            SpotResult &res);

SpotStatus sampleSpots(ImProcFunctions &ipf, ImageSource *imgsrc,
                       const ColorTemp &currWB, const ProcParams &params,
                       int fw, int fh, const SpotRequest &req, SpotResult &res)
{
    res.spots.clear();
    res.stage = req.stage;
    SpotStatus st = checkSpots(fw, fh, req, res);
    if (st != SpotStatus::OK) {
        return st;
    }
    if (req.stage != SpotStage::SOURCE) {
        return sampleSpotsStage(ipf, imgsrc, currWB, params, fw, fh, req, res);
    }
    for (auto &p : req.pos) {
        SpotSample s;
        sampleSpot(ipf, imgsrc, currWB, params, fw, fh, p.first, p.second,
                   req.size, req.space, s);
        res.spots.push_back(s);
    }
    return SpotStatus::OK;
}

namespace {

const char *stageName(SpotStage s)
{
    return s == SpotStage::CONVERTED
               ? "converted"
               : s == SpotStage::CINEON ? "cineon" : "source";
}

const char *stageUnit(SpotStage s)
{
    return s == SpotStage::CINEON ? "cineon_code" : "linear_65535";
}

// JSON has no NaN/Inf
void jnum(std::ostream &o, double v)
{
    if (std::isfinite(v)) {
        o << v;
    } else {
        o << "null";
    }
}

} // namespace

std::string spotResultJson(const SpotResult &res)
{
    std::ostringstream o;
    o.imbue(std::locale::classic());
    o.precision(9);
    o << "{\"stage\":\"" << stageName(res.stage) << "\",\"unit\":\""
      << stageUnit(res.stage) << "\"";
    if (res.stage != SpotStage::SOURCE) {
        o << ",\"film\":\"" << res.film << "\",\"w\":";
        jnum(o, res.w);
    }
    o << ",\"width\":" << res.width << ",\"height\":" << res.height
      << ",\"spots\":[";
    for (size_t i = 0; i < res.spots.size(); ++i) {
        const SpotSample &s = res.spots[i];
        o << (i ? "," : "") << "{\"x\":" << s.x << ",\"y\":" << s.y
          << ",\"avg\":[";
        for (int c = 0; c < 3; ++c) {
            o << (c ? "," : "");
            jnum(o, s.avg[c]);
        }
        o << "],\"max\":[";
        for (int c = 0; c < 3; ++c) {
            o << (c ? "," : "");
            jnum(o, s.max[c]);
        }
        o << "]}";
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

bool art::engine::ImProcCoordinator::getFilmNegativeBaseGains(
    int x, int y, int spotSize, std::array<double, 3> &gains)
{
    art::utils::MyMutex::MyLock lock(mProcessing);
    if (!imgsrc || spotSize < 1 || fw <= 0 || fh <= 0) {
        return false;
    }
    if (params.filmNegative.method != FilmNegativeParams::Method::DENSITY ||
        params.filmNegative.filmType !=
            FilmNegativeParams::FilmType::NEGATIVE) {
        return false;
    }

    const int tr = getCoarseBitMask(params.coarse);
    const Coord2D p = translateCoord(ipf, fw, fh, x, y);
    RGB avg, max;
    getSpotAvgMax(imgsrc, currWB, params, p, tr, spotSize,
                  params.filmNegative.colorSpace ==
                          FilmNegativeParams::ColorSpace::INPUT
                      ? SpotSpace::INPUT
                      : SpotSpace::WORKING,
                  avg, max, ipf.getGPUContext());

    const float sample[3] = {avg.r, avg.g, avg.b};
    std::array<double, 3> computed;
    const FramesMetaData *gainMeta = imgsrc->getMetaData();
    const Glib::ustring sourceId = filmNegSourceId(
        gainMeta ? gainMeta->getCamera() : std::string());
    if (!filmBaseGainsFromAverage(sample, params.filmNegative, params.icm,
                                  imgsrc->isRAW(), sourceId, computed)) {
        return false;
    }
    gains = computed;
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


// Transfer is verified for "(none)" (working RGB stays linear), the known
// sRGB "No ICM" path, and ART profiles getProfileParametricTRC can read.
// A named profile whose transfer is not reported is refused.
bool cineonSourceIsLinear(const procparams::ColorManagementParams &icm,
                          Glib::ustring &basis, Glib::ustring &error)
{
    const Glib::ustring &out = icm.outputProfile;
    if (out == procparams::ColorManagementParams::NoProfileString) {
        basis = icm.workingProfile;
        return true;
    }
    const Glib::ustring shown =
        out.empty() ? procparams::ColorManagementParams::NoICMString : out;
    if (out.empty() ||
        out == procparams::ColorManagementParams::NoICMString) {
        error = Glib::ustring::compose(
            art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_TRANSFER"), shown);
        return false;
    }
    cmsHPROFILE prof = ICCStore::getInstance()->getProfile(out);
    float gamma = 0.f;
    float slope = 0.f;
    if (!prof || !ICCStore::getProfileParametricTRC(prof, gamma, slope) ||
        gamma != 1.f || slope != 0.f) {
        error = Glib::ustring::compose(
            art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_TRANSFER"), shown);
        return false;
    }
    basis = out;
    return true;
}

bool convertLinearBasis(Imagefloat *img, const Glib::ustring &from,
                        const Glib::ustring &to)
{
    if (from == to) {
        return true;
    }
    if (from.empty() || to.empty()) {
        return false;
    }
    Mat33<float> fromM;
    Mat33<float> toM;
    Mat33<float> toInv;
    if (!ICCStore::getInstance()->getProfileMatrix(from, fromM) ||
        !ICCStore::getInstance()->getProfileMatrix(to, toM) ||
        !inverse(toM, toInv)) {
        return false;
    }
    const Mat33<float> conv = dot_product(toInv, fromM);
    const int height = img->getHeight();
    const int width = img->getWidth();
    for (int row = 0; row < height; ++row) {
        for (int col = 0; col < width; ++col) {
            Vec3<float> rgb(img->r(row, col) / 65535.f,
                            img->g(row, col) / 65535.f,
                            img->b(row, col) / 65535.f);
            rgb = dot_product(conv, rgb);
            img->r(row, col) = rgb[0] * 65535.f;
            img->g(row, col) = rgb[1] * 65535.f;
            img->b(row, col) = rgb[2] * 65535.f;
        }
    }
    return true;
}

} // namespace

Glib::ustring prepareFilmNegativeCineonExport(
    IImagefloat *img, const procparams::FilmNegativeParams &fnp,
    const procparams::ColorManagementParams &icm,
    const Glib::ustring &format, int bits, bool isFloat)
{
    if (!fnp.enabled ||
        fnp.method == procparams::FilmNegativeParams::Method::POWER_LAW) {
        return Glib::ustring();
    }
    if (!fnp.cineonLUT.empty()) {
        return Glib::ustring();
    }
    if (fnp.targetMode != procparams::FilmNegativeParams::TargetMode::CINEON) {
        return Glib::ustring();
    }

    const bool tiff16 = format == "tif" && bits == 16 && !isFloat;
    if (!tiff16) {
        return art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_FORMAT");
    }
    if (!img) {
        return art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_IMAGE");
    }
    if (!std::isfinite(fnp.cineonReferenceWhite) ||
        fnp.cineonReferenceWhite <= 0.0) {
        return art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_DOMAIN");
    }

    Glib::ustring basis;
    Glib::ustring transferError;
    if (!cineonSourceIsLinear(icm, basis, transferError)) {
        return transferError;
    }

    Imagefloat *out = static_cast<Imagefloat *>(img);
    out->syncCpuForWrite();

    const Glib::ustring target =
        fnp.cineonPrimaries.empty() ? icm.workingProfile : fnp.cineonPrimaries;
    if (!convertLinearBasis(out, basis, target)) {
        return Glib::ustring::compose(
            art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_PRIMARIES"),
            target.empty() ? Glib::ustring("(empty)") : target);
    }

    double referenceWhite = fnp.cineonReferenceWhite;
    const bool preserveSigned =
        fnp.method == procparams::FilmNegativeParams::Method::NAMICOLOR;
    if (!preserveSigned) {
        referenceWhite = std::max(1e-6, std::min(1e6, referenceWhite));
    }

    const int height = out->getHeight();
    const int width = out->getWidth();
    for (int row = 0; row < height; ++row) {
        float *channel[3] = {out->r(row), out->g(row), out->b(row)};
        for (int col = 0; col < width; ++col) {
            for (int c = 0; c < 3; ++c) {
                const float v = channel[c][col];
                const double y = encodeFilmCineon(
                    static_cast<double>(v) / 65535.0, referenceWhite,
                    preserveSigned);
                if (!std::isfinite(v) || !std::isfinite(y)) {
                    return art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_DOMAIN");
                }
                const double encoded = std::round(y * 65535.0);
                if (preserveSigned && fnp.preserveRange &&
                    (encoded < 0.0 || encoded > 65535.0)) {
                    return art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_RANGE");
                }
                channel[c][col] = static_cast<float>(
                    std::max(0.0, std::min(65535.0, encoded)));
            }
        }
    }

    // Do not embed a linear or sRGB ICC that describes these code values as
    // scene-linear or display-encoded RGB.
    out->setOutputProfile(nullptr, 0);
    std::ostringstream rw;
    rw.imbue(std::locale::classic());
    rw << referenceWhite;
    out->setSaveAnnotation(Glib::ustring::compose(
        "Cineon full-range encoding, primaries=%1, reference white=%2", target,
        Glib::ustring(rw.str())));
    return Glib::ustring();
}

// ----------------- stage observation (CONVERTED / CINEON) -----------------

namespace {

const char *filmStageName(const ProcParams &p)
{
    const FilmNegativeParams &f = p.filmNegative;
    if (!f.enabled) {
        return "disabled";
    }
    switch (f.method) {
    case FilmNegativeParams::Method::POWER_LAW:
        return "power_law";
    case FilmNegativeParams::Method::NAMICOLOR:
        return "namicolor";
    default:
        return "density";
    }
}

// Brings `img` (a getImage() result: linear, white balanced, camera space) to
// the CONVERTED stage, in the order ImageProcessor::stage_denoise() uses: the
// film conversion in the configured colour space, the input -> working colour
// conversion, no before_grade LUT. Per pixel, so it is valid on a crop of the
// frame, except for a power-law conversion whose references are estimated
// from the whole frame (`wholeFrame` false).
bool convertToStage(ImageSource *imgsrc, const ColorTemp &currWB,
                    const ProcParams &params, Imagefloat *img, bool wholeFrame,
                    std::string &err)
{
    const FilmNegativeParams &fnp = params.filmNegative;
    const bool inputFirst =
        fnp.colorSpace == FilmNegativeParams::ColorSpace::INPUT;
    if (!inputFirst) {
        imgsrc->convertColorSpace(img, params.icm, currWB);
    }
    if (fnp.enabled) {
        if (!wholeFrame &&
            fnp.method == FilmNegativeParams::Method::POWER_LAW &&
            (fnp.backCompat != FilmNegativeParams::BackCompat::CURRENT ||
             !(fnp.refInput.g > 0.f) || !(fnp.refOutput.g > 0.f))) {
            err = "power-law film negative without stored reference values "
                  "estimates them from the whole frame: spots cannot be "
                  "converted, use -X";
            return false;
        }
        ImProcFunctions ipf(&params, true);
        FilmNegativeParams copy = fnp;
        ipf.filmNegativeProcess(img, img, copy, params.raw, imgsrc, currWB);
        if (ipf.filmNegativeContractFailed()) {
            err = "the film negative conversion failed (see the message above)";
            return false;
        }
    }
    if (inputFirst) {
        imgsrc->convertColorSpace(img, params.icm, currWB);
    }
    return true;
}

// the Cineon encode of prepareFilmNegativeCineonExport()
struct StageEncoder {
    double w = 1.0;
    bool preserveSigned = false;
    bool convert = false; // the export converts to cineonPrimaries first
    Glib::ustring target;

    // Cineon code (0..1023 scale) of a linear value on the 0..65535 scale
    double code(double v) const
    {
        return encodeFilmCineon(v / 65535.0, w, preserveSigned) * 1023.0;
    }
};

bool stageEncoder(const ProcParams &params, StageEncoder &e, std::string &err)
{
    const FilmNegativeParams &f = params.filmNegative;
    if (!std::isfinite(f.cineonReferenceWhite) ||
        f.cineonReferenceWhite <= 0.0) {
        err = art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_DOMAIN");
        return false;
    }
    e.w = f.cineonReferenceWhite;
    e.preserveSigned =
        f.enabled && f.method == FilmNegativeParams::Method::NAMICOLOR;
    if (!e.preserveSigned) {
        e.w = std::max(1e-6, std::min(1e6, e.w));
    }
    e.target = f.cineonPrimaries.empty() ? params.icm.workingProfile
                                         : f.cineonPrimaries;
    e.convert = e.target != params.icm.workingProfile;
    return true;
}

} // namespace

SpotStatus sampleSpotsStage(ImProcFunctions &ipf, ImageSource *imgsrc,
                            const ColorTemp &currWB, const ProcParams &params,
                            int fw, int fh, const SpotRequest &req,
                            SpotResult &res)
{
    res.film = filmStageName(params);
    res.w = params.filmNegative.cineonReferenceWhite;
    const bool cineon = req.stage == SpotStage::CINEON;
    StageEncoder enc;
    if (cineon) {
        if (!stageEncoder(params, enc, res.error)) {
            return SpotStatus::FAILED;
        }
        res.w = enc.w;
    }
    const int tr = getCoarseBitMask(params.coarse);
    const int size = req.size;
    for (auto &pos : req.pos) {
        const Coord2D p = spotCentre(ipf, fw, fh, pos.first, pos.second, size);
        const int x1 = MAX(0, (int)p.x - size / 2);
        const int y1 = MAX(0, (int)p.y - size / 2);
        PreviewProps pp(x1, y1, size, size, 1);
        Imagefloat spotImg(size, size);
        imgsrc->getImage(currWB, tr, &spotImg, pp, params.exposure,
                         params.raw);
        if (!convertToStage(imgsrc, currWB, params, &spotImg, false,
                            res.error)) {
            return SpotStatus::FAILED;
        }
        if (cineon && enc.convert &&
            !convertLinearBasis(&spotImg, params.icm.workingProfile,
                                enc.target)) {
            res.error = "cannot convert the working space to the Cineon "
                        "primaries " +
                        std::string(enc.target);
            return SpotStatus::FAILED;
        }
        double sum[3] = {0, 0, 0};
        double mx[3] = {-std::numeric_limits<double>::infinity(),
                        -std::numeric_limits<double>::infinity(),
                        -std::numeric_limits<double>::infinity()};
        for (int i = 0; i < size; ++i) {
            const float *ch[3] = {spotImg.r(i), spotImg.g(i), spotImg.b(i)};
            for (int j = 0; j < size; ++j) {
                for (int c = 0; c < 3; ++c) {
                    const double v =
                        cineon ? enc.code(ch[c][j]) : double(ch[c][j]);
                    if (!std::isfinite(v)) {
                        res.error = "the spot at " +
                                    std::to_string(pos.first) + "," +
                                    std::to_string(pos.second) +
                                    " has non-finite values at this stage";
                        return SpotStatus::FAILED;
                    }
                    sum[c] += v;
                    mx[c] = std::max(mx[c], v);
                }
            }
        }
        SpotSample s;
        s.x = pos.first;
        s.y = pos.second;
        for (int c = 0; c < 3; ++c) {
            s.avg[c] = static_cast<float>(sum[c] / (double(size) * size));
            s.max[c] = static_cast<float>(mx[c]);
        }
        res.spots.push_back(s);
    }
    return SpotStatus::OK;
}

namespace {

void channelStats(const std::vector<float> &v, double lo, double hi, int bins,
                  StageChannelStats &out)
{
    out = StageChannelStats();
    out.hist.assign(bins, 0);
    std::vector<float> fin;
    fin.reserve(v.size());
    double sum = 0.0;
    double mn = std::numeric_limits<double>::infinity();
    double mx = -std::numeric_limits<double>::infinity();
    for (float f : v) {
        if (!std::isfinite(f)) {
            ++out.nonfinite;
            continue;
        }
        const double d = f;
        fin.push_back(f);
        sum += d;
        mn = std::min(mn, d);
        mx = std::max(mx, d);
        if (d < lo) {
            ++out.below;
        } else if (d > hi) {
            ++out.above;
        } else {
            int b = static_cast<int>((d - lo) / (hi - lo) * bins);
            ++out.hist[std::min(std::max(b, 0), bins - 1)];
        }
    }
    const double nan = std::numeric_limits<double>::quiet_NaN();
    if (fin.empty()) {
        out.min = out.max = out.mean = out.p01 = out.p50 = out.p99 = nan;
        return;
    }
    out.min = mn;
    out.max = mx;
    out.mean = sum / fin.size();
    // nearest rank over the finite values (out of range ones included)
    auto pct = [&fin](double q) -> double {
        const size_t k = static_cast<size_t>(q * (fin.size() - 1) + 0.5);
        std::nth_element(fin.begin(), fin.begin() + k, fin.end());
        return fin[k];
    };
    out.p01 = pct(0.01);
    out.p50 = pct(0.50);
    out.p99 = pct(0.99);
}

} // namespace

bool filmStageStats(Imagefloat *img, const ProcParams &params,
                    const StageStatsRequest &req, StageStatsResult &res)
{
    res = StageStatsResult();
    res.stage = req.stage;
    res.film = filmStageName(params);
    if (req.stage != SpotStage::CONVERTED && req.stage != SpotStage::CINEON) {
        res.error = "the stage must be converted or cineon";
        return false;
    }
    if (req.bins < 2 || req.bins > 1024 || req.maxsize < 0) {
        res.error = "bins must be from 2 to 1024 and maxsize >= 0";
        return false;
    }
    if (req.hasRegion &&
        !(std::isfinite(req.x0) && std::isfinite(req.y0) &&
          std::isfinite(req.x1) && std::isfinite(req.y1) && req.x0 >= 0 &&
          req.y0 >= 0 && req.x1 <= 1 && req.y1 <= 1 && req.x0 < req.x1 &&
          req.y0 < req.y1)) {
        res.error = "the region must satisfy 0 <= x0 < x1 <= 1 and "
                    "0 <= y0 < y1 <= 1";
        return false;
    }
    const bool cineon = req.stage == SpotStage::CINEON;
    StageEncoder enc;
    res.w = params.filmNegative.cineonReferenceWhite;
    if (cineon) {
        if (!stageEncoder(params, enc, res.error)) {
            return false;
        }
        res.w = enc.w;
    }
    res.lo = cineon ? -100.0 : -6553.5;
    res.hi = cineon ? 1100.0 : 131070.0;

    img->syncCpu();
    const int iw = img->getWidth();
    const int ih = img->getHeight();
    // the crop, as stage_finish() applies it (after coarse rotation)
    int cx = 0, cy = 0, cw = iw, ch = ih;
    if (params.crop.enabled) {
        cx = std::max(0, std::min(params.crop.x, iw - 1));
        cy = std::max(0, std::min(params.crop.y, ih - 1));
        cw = std::max(1, std::min(params.crop.w, iw - cx));
        ch = std::max(1, std::min(params.crop.h, ih - cy));
    }
    res.sourceWidth = cw;
    res.sourceHeight = ch;
    int rx0 = cx, ry0 = cy, rx1 = cx + cw, ry1 = cy + ch;
    if (req.hasRegion) {
        rx0 = cx + static_cast<int>(std::floor(req.x0 * cw));
        ry0 = cy + static_cast<int>(std::floor(req.y0 * ch));
        rx1 = cx + static_cast<int>(std::ceil(req.x1 * cw));
        ry1 = cy + static_cast<int>(std::ceil(req.y1 * ch));
        rx0 = std::min(rx0, cx + cw - 1);
        ry0 = std::min(ry0, cy + ch - 1);
        rx1 = std::max(rx0 + 1, std::min(rx1, cx + cw));
        ry1 = std::max(ry0 + 1, std::min(ry1, cy + ch));
    }
    const int sw = rx1 - rx0;
    const int sh = ry1 - ry0;
    int ow = sw, oh = sh;
    const int longest = std::max(sw, sh);
    if (req.maxsize > 0 && longest > req.maxsize) {
        const double s = double(req.maxsize) / longest;
        ow = std::max(
            1, std::min(sw, static_cast<int>(std::floor(sw * s + 0.5))));
        oh = std::max(
            1, std::min(sh, static_cast<int>(std::floor(sh * s + 0.5))));
    }
    res.width = ow;
    res.height = oh;

    // box average, in linear light (before any Cineon encoding)
    Imagefloat ds(ow, oh);
    ds.syncCpuForWrite();
#ifdef _OPENMP
#pragma omp parallel for
#endif
    for (int oy = 0; oy < oh; ++oy) {
        const int ya = ry0 + static_cast<int>(int64_t(oy) * sh / oh);
        const int yb = std::max(
            ya + 1, ry0 + static_cast<int>(int64_t(oy + 1) * sh / oh));
        for (int ox = 0; ox < ow; ++ox) {
            const int xa = rx0 + static_cast<int>(int64_t(ox) * sw / ow);
            const int xb = std::max(
                xa + 1, rx0 + static_cast<int>(int64_t(ox + 1) * sw / ow));
            double sr = 0, sg = 0, sb = 0;
            for (int y = ya; y < yb; ++y) {
                const float *r = img->r(y);
                const float *g = img->g(y);
                const float *b = img->b(y);
                for (int x = xa; x < xb; ++x) {
                    sr += r[x];
                    sg += g[x];
                    sb += b[x];
                }
            }
            const double n = double(yb - ya) * (xb - xa);
            ds.r(oy, ox) = static_cast<float>(sr / n);
            ds.g(oy, ox) = static_cast<float>(sg / n);
            ds.b(oy, ox) = static_cast<float>(sb / n);
        }
    }
    if (cineon && enc.convert &&
        !convertLinearBasis(&ds, params.icm.workingProfile, enc.target)) {
        res.error = "cannot convert the working space to the Cineon "
                    "primaries " +
                    std::string(enc.target);
        return false;
    }
    std::vector<float> vals[3];
    for (int c = 0; c < 3; ++c) {
        vals[c].resize(size_t(ow) * oh);
    }
    for (int y = 0; y < oh; ++y) {
        const float *ch3[3] = {ds.r(y), ds.g(y), ds.b(y)};
        for (int x = 0; x < ow; ++x) {
            for (int c = 0; c < 3; ++c) {
                const double v = ch3[c][x];
                vals[c][size_t(y) * ow + x] =
                    static_cast<float>(cineon ? enc.code(v) : v);
            }
        }
    }
    for (int c = 0; c < 3; ++c) {
        channelStats(vals[c], res.lo, res.hi, req.bins, res.ch[c]);
    }
    return true;
}

std::string stageStatsJson(const StageStatsResult &res)
{
    std::ostringstream o;
    o.imbue(std::locale::classic());
    o.precision(9);
    o << "{\"stage\":\"" << stageName(res.stage) << "\",\"unit\":\""
      << stageUnit(res.stage) << "\",\"film\":\"" << res.film
      << "\",\"width\":" << res.width << ",\"height\":" << res.height
      << ",\"source_width\":" << res.sourceWidth
      << ",\"source_height\":" << res.sourceHeight << ",\"w\":";
    jnum(o, res.w);
    o << ",\"range\":[";
    jnum(o, res.lo);
    o << ",";
    jnum(o, res.hi);
    o << "],\"channels\":[";
    for (int c = 0; c < 3; ++c) {
        const StageChannelStats &s = res.ch[c];
        o << (c ? "," : "") << "{";
        const char *names[] = {"min", "max", "mean", "p01", "p50", "p99"};
        const double nums[] = {s.min, s.max, s.mean, s.p01, s.p50, s.p99};
        for (int i = 0; i < 6; ++i) {
            o << "\"" << names[i] << "\":";
            jnum(o, nums[i]);
            o << ",";
        }
        o << "\"below\":" << s.below << ",\"above\":" << s.above
          << ",\"nonfinite\":" << s.nonfinite << ",\"hist\":[";
        for (size_t i = 0; i < s.hist.size(); ++i) {
            o << (i ? "," : "") << s.hist[i];
        }
        o << "]}";
    }
    o << "]}";
    return o.str();
}

} } // namespace art::engine
