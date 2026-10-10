#include "cineonlut.h"

#include <cctype>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <algorithm>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include <glibmm/checksum.h>
#include "color.h"
#include "iccstore.h"
#include "linalgebra.h"
#include "../utils/multilangmgr.h"

namespace art { namespace engine {

namespace {

struct CubeLut {
    int size;
    float domainMin[3];
    float domainMax[3];
    std::vector<float> rgb; // R changes fastest, then G, then B
    std::uint64_t hash;
};

std::mutex gCubeMutex;
std::unordered_map<std::string, std::shared_ptr<const CubeLut>> gCubeCache;

std::string lowerCopy(const std::string &in)
{
    std::string out = in;
    for (size_t i = 0; i < out.size(); ++i) {
        out[i] = static_cast<char>(std::tolower(static_cast<unsigned char>(out[i])));
    }
    return out;
}

std::uint64_t fnv1a(const std::string &bytes)
{
    std::uint64_t h = 14695981039346656037ull;
    for (size_t i = 0; i < bytes.size(); ++i) {
        h ^= static_cast<unsigned char>(bytes[i]);
        h *= 1099511628211ull;
    }
    return h;
}

bool isLogOutputName(const std::string &raw)
{
    std::string s = lowerCopy(raw);
    while (!s.empty() && (s[0] == '"' || s[0] == '\'')) {
        s.erase(s.begin());
    }
    while (!s.empty() && (s[s.size() - 1] == '"' || s[s.size() - 1] == '\'' ||
                          s[s.size() - 1] == ',')) {
        s.erase(s.end() - 1);
    }
    if (s == "linear" || s == "srgb" || s == "gamma_2_4" || s == "gamma2.4" ||
        s == "gamma2_4" || s == "gamma 2.4" || s == "rec709" || s == "rec.709") {
        return false;
    }
    if (s.find("log") != std::string::npos || s.find("cineon") != std::string::npos ||
        s.find("acescc") != std::string::npos || s.find("slog") != std::string::npos ||
        s.find("v-log") != std::string::npos || s.find("vlog") != std::string::npos ||
        s.find("clog") != std::string::npos || s.find("n-log") != std::string::npos ||
        s.find("nlog") != std::string::npos) {
        return true;
    }
    return false;
}

// Explicit output-transfer keys. A log value is unsupported; display
// transfers are ignored because CineonLUTOutputTransfer is the contract.
bool headerDeclaresLogOutput(const std::string &line, std::string &declared)
{
    std::string s = line;
    if (!s.empty() && s[0] == '#') {
        s = s.substr(1);
    }
    const std::string low = lowerCopy(s);
    const char *keys[] = {"output_transfer", "lut_output_transfer",
                          "output_encoding", "art_output_transfer",
                          "lut output transfer", "output transfer"};
    for (size_t k = 0; k < sizeof(keys) / sizeof(keys[0]); ++k) {
        const std::string key = keys[k];
        const size_t pos = low.find(key);
        if (pos == std::string::npos) {
            continue;
        }
        size_t v = pos + key.size();
        while (v < s.size() &&
               (s[v] == ' ' || s[v] == '\t' || s[v] == ':' || s[v] == '=')) {
            ++v;
        }
        if (v >= s.size()) {
            continue;
        }
        // Whole value up to a comment: "ARRI LogC3" must not stop at "ARRI"
        declared = s.substr(v);
        const size_t cut = declared.find('#');
        if (cut != std::string::npos) {
            declared = declared.substr(0, cut);
        }
        while (!declared.empty() &&
               (declared[declared.size() - 1] == ' ' ||
                declared[declared.size() - 1] == '\t' ||
                declared[declared.size() - 1] == '\r')) {
            declared.erase(declared.end() - 1);
        }
        return isLogOutputName(declared);
    }
    return false;
}

void report(ProgressListener *pl, const Glib::ustring &msg)
{
    std::cerr << msg << "\n";
    if (pl) {
        pl->error(msg);
    }
}

bool parseCube(const std::string &text, CubeLut &cube, std::string &error,
               std::string &logDeclared)
{
    cube.size = 0;
    cube.domainMin[0] = cube.domainMin[1] = cube.domainMin[2] = 0.f;
    cube.domainMax[0] = cube.domainMax[1] = cube.domainMax[2] = 1.f;
    cube.rgb.clear();
    bool saw3d = false;
    std::istringstream in(text);
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line[line.size() - 1] == '\r') {
            line.erase(line.size() - 1);
        }
        if (headerDeclaresLogOutput(line, logDeclared)) {
            error = Glib::ustring::compose(
                        art::utils::M("TP_FILMNEGATIVE_ERR_LUT_LOG_DETAIL"),
                        logDeclared)
                        .raw();
            return false;
        }
        std::string trimmed = line;
        const size_t hash = trimmed.find('#');
        if (hash != std::string::npos) {
            trimmed = trimmed.substr(0, hash);
        }
        std::istringstream ls(trimmed);
        std::string key;
        if (!(ls >> key)) {
            continue;
        }
        const std::string low = lowerCopy(key);
        if (low == "title") {
            continue;
        }
        if (low == "lut_in_video_range" || low == "lut_out_video_range") {
            // Legal-range scaling would change the meaning of the file and is
            // not implemented; refuse instead of silently ignoring it.
            error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_VIDEO_RANGE").raw();
            return false;
        }
        if (low == "lut_1d_size" || low == "lut_1d_input_range") {
            // A 1D shaper would change the meaning of the file and is not
            // implemented; refuse instead of silently skipping its rows.
            error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_1D").raw();
            return false;
        }
        if (low == "lut_3d_input_range") {
            // Adobe/Resolve scalar domain for all three channels
            float lo = 0.f, hi = 1.f;
            if (!(ls >> lo >> hi)) {
                error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_DOMAIN").raw();
                return false;
            }
            for (int c = 0; c < 3; ++c) {
                cube.domainMin[c] = lo;
                cube.domainMax[c] = hi;
            }
            continue;
        }
        if (low == "lut_3d_size") {
            ls >> cube.size;
            saw3d = true;
            if (cube.size < 2 || cube.size > 128) {
                error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_SIZE").raw();
                return false;
            }
            continue;
        }
        if (low == "domain_min" || low == "domain_max") {
            float d[3];
            if (!(ls >> d[0] >> d[1] >> d[2])) {
                error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_DOMAIN").raw();
                return false;
            }
            float *dst = low == "domain_min" ? cube.domainMin : cube.domainMax;
            for (int c = 0; c < 3; ++c) {
                dst[c] = d[c];
            }
            continue;
        }
        float r = 0.f, g = 0.f, b = 0.f;
        std::istringstream vs(trimmed);
        if (!(vs >> r >> g >> b)) {
            continue;
        }
        if (!std::isfinite(r) || !std::isfinite(g) || !std::isfinite(b)) {
            error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_NONFINITE").raw();
            return false;
        }
        cube.rgb.push_back(r);
        cube.rgb.push_back(g);
        cube.rgb.push_back(b);
    }
    if (!saw3d || cube.size < 2) {
        error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_NOT_3D").raw();
        return false;
    }
    const size_t expect =
        static_cast<size_t>(cube.size) * cube.size * cube.size * 3;
    if (cube.rgb.size() != expect) {
        error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_LENGTH").raw();
        return false;
    }
    for (int c = 0; c < 3; ++c) {
        if (!std::isfinite(cube.domainMin[c]) ||
            !std::isfinite(cube.domainMax[c]) ||
            !(cube.domainMax[c] > cube.domainMin[c])) {
            error = art::utils::M("TP_FILMNEGATIVE_ERR_LUT_DOMAIN").raw();
            return false;
        }
    }
    return true;
}

bool readFileBytes(const Glib::ustring &path, std::string &bytes)
{
    if (path.empty() || !Glib::file_test(path, Glib::FILE_TEST_IS_REGULAR)) {
        return false;
    }
    std::ifstream in(Glib::filename_from_utf8(path).c_str(),
                     std::ios::in | std::ios::binary);
    if (!in) {
        return false;
    }
    std::ostringstream buf;
    buf << in.rdbuf();
    bytes = buf.str();
    return true;
}

// Parses (or fetches from the cache) a cube from already-read file bytes.
// The cache hands out shared immutable cubes, so a hit copies nothing.
bool loadCube(const Glib::ustring &path, const std::string &bytes,
              std::shared_ptr<const CubeLut> &out, ProgressListener *pl)
{
    const std::string key = path.raw();
    const std::uint64_t hash = fnv1a(bytes);
    {
        std::lock_guard<std::mutex> lock(gCubeMutex);
        const auto it = gCubeCache.find(key);
        if (it != gCubeCache.end() && it->second->hash == hash) {
            out = it->second;
            return true;
        }
    }
    std::shared_ptr<CubeLut> parsed(new CubeLut());
    parsed->hash = hash;
    std::string error;
    std::string logDeclared;
    if (!parseCube(bytes, *parsed, error, logDeclared)) {
        {
            std::lock_guard<std::mutex> lock(gCubeMutex);
            gCubeCache.erase(key);
        }
        if (!logDeclared.empty()) {
            report(pl, Glib::ustring::compose(
                           art::utils::M("TP_FILMNEGATIVE_ERR_LUT_LOG"), path,
                           error));
        } else {
            report(pl, Glib::ustring::compose(
                           art::utils::M("TP_FILMNEGATIVE_ERR_LUT_BAD"), path,
                           error));
        }
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(gCubeMutex);
        gCubeCache[key] = parsed;
    }
    out = parsed;
    return true;
}

void sampleCube(const CubeLut &cube, float r, float g, float b, float &or_,
                float &og, float &ob)
{
    float t[3] = {r, g, b};
    int i0[3], i1[3];
    float f[3];
    const int n = cube.size;
    for (int c = 0; c < 3; ++c) {
        float u = (t[c] - cube.domainMin[c]) /
                  (cube.domainMax[c] - cube.domainMin[c]);
        if (u < 0.f) {
            u = 0.f;
        } else if (u > 1.f) {
            u = 1.f;
        }
        const float x = u * static_cast<float>(n - 1);
        i0[c] = static_cast<int>(x);
        if (i0[c] >= n - 1) {
            i0[c] = n - 2;
            f[c] = 1.f;
        } else {
            f[c] = x - static_cast<float>(i0[c]);
        }
        i1[c] = i0[c] + 1;
    }
    auto at = [&](int ri, int gi, int bi, int ch) -> float {
        const size_t idx =
            (static_cast<size_t>(bi) * n + gi) * n + ri;
        return cube.rgb[idx * 3 + ch];
    };
    float out[3];
    for (int ch = 0; ch < 3; ++ch) {
        const float c000 = at(i0[0], i0[1], i0[2], ch);
        const float c100 = at(i1[0], i0[1], i0[2], ch);
        const float c010 = at(i0[0], i1[1], i0[2], ch);
        const float c110 = at(i1[0], i1[1], i0[2], ch);
        const float c001 = at(i0[0], i0[1], i1[2], ch);
        const float c101 = at(i1[0], i0[1], i1[2], ch);
        const float c011 = at(i0[0], i1[1], i1[2], ch);
        const float c111 = at(i1[0], i1[1], i1[2], ch);
        const float c00 = c000 + (c100 - c000) * f[0];
        const float c10 = c010 + (c110 - c010) * f[0];
        const float c01 = c001 + (c101 - c001) * f[0];
        const float c11 = c011 + (c111 - c011) * f[0];
        const float c0 = c00 + (c10 - c00) * f[1];
        const float c1 = c01 + (c11 - c01) * f[1];
        out[ch] = c0 + (c1 - c0) * f[2];
    }
    or_ = out[0];
    og = out[1];
    ob = out[2];
}

// Formula constants verified against Colour's ARRI SUP 3.x scene-exposure
// EI800, Sony normalized 10-bit S-Log3 and Academy S-2016-001 ACEScct.
// https://github.com/colour-science/colour/tree/develop/colour/models/rgb/transfer_functions
double encodeLutTransfer(double x,
                        procparams::FilmNegativeParams::CineonLUTInputTransfer t,
                        double referenceWhite, bool preserveSigned)
{
    using Transfer = procparams::FilmNegativeParams::CineonLUTInputTransfer;
    switch (t) {
    case Transfer::CINEON:
        return encodeFilmCineon(x, referenceWhite, preserveSigned);
    case Transfer::LINEAR:
        return x;
    case Transfer::SRGB:
        return x <= 0.0031308 ? 12.92 * x
                             : 1.055 * std::pow(x, 1.0 / 2.4) - 0.055;
    case Transfer::GAMMA_2_4:
        return std::copysign(std::pow(std::fabs(x), 1.0 / 2.4), x);
    case Transfer::LOGC3:
        return x > 0.010591
            ? 0.247190 * std::log10(5.555556 * x + 0.052272) + 0.385537
            : 5.367655 * x + 0.092809;
    case Transfer::SLOG3:
        return x >= 0.01125
            ? (420.0 + 261.5 * std::log10((x + 0.01) / 0.19)) / 1023.0
            : (x * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0;
    case Transfer::ACESCCT:
        return x <= 0.0078125
            ? 10.5402377416545 * x + 0.0729055341958355
            : (std::log2(x) + 9.72) / 17.52;
    }
    return std::numeric_limits<double>::quiet_NaN();
}

float decodeTransfer(float y, procparams::FilmNegativeParams::CineonLUTOutputTransfer t)
{
    if (t == procparams::FilmNegativeParams::CineonLUTOutputTransfer::LINEAR) {
        return y;
    }
    if (!(y > 0.f)) {
        return 0.f;
    }
    if (t == procparams::FilmNegativeParams::CineonLUTOutputTransfer::GAMMA_2_4) {
        return std::pow(y, 2.4f);
    }
    // IEC 61966-2-1 EOTF: encoded sRGB -> linear. The ticket's "EOTF inverse"
    // names this decode (the inverse of the encoding function).
    if (y <= 0.04045f) {
        return y / 12.92f;
    }
    return std::pow((y + 0.055f) / 1.055f, 2.4f);
}

struct PrimariesMap {
    bool active;
    float toLut[3][3];
    float fromLut[3][3];
};

void mul3(const float m[3][3], float r, float g, float b, float &or_, float &og,
          float &ob)
{
    or_ = m[0][0] * r + m[0][1] * g + m[0][2] * b;
    og = m[1][0] * r + m[1][1] * g + m[1][2] * b;
    ob = m[2][0] * r + m[2][1] * g + m[2][2] * b;
}

PrimariesMap primariesMap(const procparams::FilmNegativeParams &params,
                          const procparams::ColorManagementParams &icm,
                          ProgressListener *pl, bool &ok)
{
    PrimariesMap map;
    map.active = false;
    ok = true;
    const Glib::ustring &inName = params.cineonLUTInputPrimaries;
    const Glib::ustring &outName = params.cineonLUTOutputPrimaries;
    if (inName.empty() && outName.empty()) {
        return map;
    }
    const Glib::ustring work = icm.workingProfile;
    const Glib::ustring inProf = inName.empty() ? work : inName;
    const Glib::ustring outProf = outName.empty() ? inProf : outName;
    Mat33<float> workM, inM, outM, workInv, inInv;
    if (work.empty() ||
        !ICCStore::getInstance()->getProfileMatrix(work, workM) ||
        !ICCStore::getInstance()->getProfileMatrix(inProf, inM) ||
        !ICCStore::getInstance()->getProfileMatrix(outProf, outM) ||
        !inverse(workM, workInv) || !inverse(inM, inInv)) {
        ok = false;
        report(pl, Glib::ustring::compose(
                       art::utils::M("TP_FILMNEGATIVE_ERR_LUT_PRIMARIES"),
                       inProf, outProf));
        return map;
    }
    const Mat33<float> to = dot_product(inInv, workM);
    const Mat33<float> from = dot_product(workInv, outM);
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 3; ++c) {
            map.toLut[r][c] = to[r][c];
            map.fromLut[r][c] = from[r][c];
        }
    }
    map.active = true;
    return map;
}

} // namespace

double encodeFilmCineon(double linear01, double referenceWhite,
                        bool preserveSigned)
{
    static const double b = std::pow(10.0, (95.0 - 685.0) / 300.0);
    if (preserveSigned) {
        // log1p retains signed values around Cineon black without cancellation.
        return (95.0 + 300.0 / std::log(10.0) *
                           std::log1p(linear01 / referenceWhite * (1.0 - b) / b)) /
               1023.0;
    }
    const double x = std::max(0.0, linear01) / referenceWhite;
    return (685.0 + 300.0 * std::log10(x * (1.0 - b) + b)) / 1023.0;
}

double decodeFilmCineon(double code, double referenceWhite)
{
    static const double b = std::pow(10.0, (95.0 - 685.0) / 300.0);
    return referenceWhite * b *
           std::expm1((1023.0 * code - 95.0) / 300.0 * std::log(10.0)) /
           (1.0 - b);
}

bool applyCineonPrintLut(Imagefloat *img,
                         const procparams::FilmNegativeParams &params,
                         const procparams::ColorManagementParams &icm,
                         ProgressListener *pl)
{
    if (!img || params.cineonLUT.empty()) {
        return true;
    }
    using Transfer = procparams::FilmNegativeParams::CineonLUTOutputTransfer;
    if (params.cineonLUTOutputTransfer == Transfer::UNSUPPORTED) {
        report(pl, art::utils::M("TP_FILMNEGATIVE_ERR_LUT_TRANSFER"));
        return false;
    }
    using InputTransfer = procparams::FilmNegativeParams::CineonLUTInputTransfer;
    if (params.cineonLUTInputTransfer < InputTransfer::CINEON ||
        params.cineonLUTInputTransfer > InputTransfer::ACESCCT) {
        report(pl, art::utils::M("TP_FILMNEGATIVE_ERR_LUT_INPUT_TRANSFER"));
        return false;
    }
    if (!std::isfinite(params.cineonReferenceWhite) ||
        params.cineonReferenceWhite <= 0.0) {
        report(pl, art::utils::M("TP_FILMNEGATIVE_ERR_CINEON_DOMAIN"));
        return false;
    }
    std::string bytes;
    Glib::ustring sha;
    if (readFileBytes(params.cineonLUT, bytes)) {
        sha = Glib::Checksum::compute_checksum(
            Glib::Checksum::CHECKSUM_SHA256, bytes);
    }
    if (sha.empty() || params.cineonLUTSha256.empty() ||
        sha != params.cineonLUTSha256) {
        report(pl, Glib::ustring::compose(
                       art::utils::M("TP_FILMNEGATIVE_ERR_LUT_HASH"),
                       params.cineonLUT));
        return false;
    }
    std::shared_ptr<const CubeLut> cubePtr;
    if (!loadCube(params.cineonLUT, bytes, cubePtr, pl)) {
        return false;
    }
    bytes.clear();
    const CubeLut &cube = *cubePtr;
    bool primOk = true;
    const PrimariesMap prim = primariesMap(params, icm, pl, primOk);
    if (!primOk) {
        return false;
    }
    double referenceWhite = params.cineonReferenceWhite;
    const bool namiColor =
        params.method == procparams::FilmNegativeParams::Method::NAMICOLOR;
    if (!namiColor) {
        referenceWhite = std::max(1e-6, std::min(1e6, referenceWhite));
    }
    const bool preserveSigned = namiColor;
    const float offset = preserveSigned ? 0.f :
        static_cast<float>(params.outputBlackOffset);
    const bool preserveOutputRange = namiColor && params.preserveRange;
    const bool clampCineonDomain = preserveSigned &&
        params.cineonLUTInputTransfer ==
            procparams::FilmNegativeParams::CineonLUTInputTransfer::CINEON;
    float minimumLinear[3] = {0.f, 0.f, 0.f};
    if (clampCineonDomain) {
        for (int c = 0; c < 3; ++c) {
            minimumLinear[c] = static_cast<float>(
                decodeFilmCineon(cube.domainMin[c], referenceWhite));
        }
    }
    img->syncCpuForWrite();
    int nonFiniteCount = 0;

    const int height = img->getHeight();
    const int width = img->getWidth();
    const float S = 65535.f;
#ifdef _OPENMP
#pragma omp parallel for reduction(+ : nonFiniteCount) schedule(dynamic, 16)
#endif
    for (int row = 0; row < height; ++row) {
        for (int col = 0; col < width; ++col) {
            float r = img->r(row, col) / S;
            float g = img->g(row, col) / S;
            float b = img->b(row, col) / S;
            if (prim.active) {
                float rr, gg, bb;
                mul3(prim.toLut, r, g, b, rr, gg, bb);
                r = rr;
                g = gg;
                b = bb;
            }
            if (!std::isfinite(r) || !std::isfinite(g) || !std::isfinite(b)) {
                ++nonFiniteCount;
                continue;
            }
            if (clampCineonDomain) {
                // sampleCube clamps to its declared domain. Apply the same
                // lower bound before taking a log: a gamut conversion can
                // produce finite RGB below the Cineon logarithm's domain.
                r = std::max(r, minimumLinear[0]);
                g = std::max(g, minimumLinear[1]);
                b = std::max(b, minimumLinear[2]);
            }
            const float cr = static_cast<float>(encodeLutTransfer(
                r, params.cineonLUTInputTransfer, referenceWhite, preserveSigned));
            const float cg = static_cast<float>(encodeLutTransfer(
                g, params.cineonLUTInputTransfer, referenceWhite, preserveSigned));
            const float cb = static_cast<float>(encodeLutTransfer(
                b, params.cineonLUTInputTransfer, referenceWhite, preserveSigned));
            if (!std::isfinite(cr) || !std::isfinite(cg) || !std::isfinite(cb)) {
                ++nonFiniteCount;
                continue;
            }
            float lr, lg, lb;
            sampleCube(cube, cr, cg, cb, lr, lg, lb);
            lr = decodeTransfer(lr, params.cineonLUTOutputTransfer);
            lg = decodeTransfer(lg, params.cineonLUTOutputTransfer);
            lb = decodeTransfer(lb, params.cineonLUTOutputTransfer);
            if (prim.active) {
                float rr, gg, bb;
                mul3(prim.fromLut, lr, lg, lb, rr, gg, bb);
                lr = rr;
                lg = gg;
                lb = bb;
            }
            if (!std::isfinite(lr) || !std::isfinite(lg) || !std::isfinite(lb)) {
                ++nonFiniteCount;
                continue;
            }
            auto store = [offset, preserveOutputRange](float v) -> float {
                v -= offset;
                return preserveOutputRange || v > 0.f ? v * 65535.f : 0.f;
            };
            lr = store(lr);
            lg = store(lg);
            lb = store(lb);
            if (!std::isfinite(lr) || !std::isfinite(lg) || !std::isfinite(lb)) {
                ++nonFiniteCount;
                continue;
            }
            img->r(row, col) = lr;
            img->g(row, col) = lg;
            img->b(row, col) = lb;
        }
    }
    if (nonFiniteCount) {
        report(pl, art::utils::M("TP_FILMNEGATIVE_ERR_LUT_NONFINITE"));
        return false;
    }
    return true;
}

Glib::ustring cineonLutSha256(const Glib::ustring &path)
{
    std::string bytes;
    if (!readFileBytes(path, bytes)) {
        return Glib::ustring();
    }
    return Glib::Checksum::compute_checksum(Glib::Checksum::CHECKSUM_SHA256,
                                            bytes);
}

}} // namespace art::engine
