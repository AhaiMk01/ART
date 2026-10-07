#include "cineonlut.h"

#include <cctype>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#include "color.h"
#include "iccstore.h"
#include "linalgebra.h"

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
std::unordered_map<std::string, CubeLut> gCubeCache;

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
        declared = s.substr(v);
        const size_t cut = declared.find_first_of(" \t#");
        if (cut != std::string::npos) {
            declared = declared.substr(0, cut);
        }
        return isLogOutputName(declared);
    }
    return false;
}

void report(ProgressListener *pl, const Glib::ustring &msg)
{
    std::cerr << "Film Negative: " << msg << "\n";
    if (pl) {
        pl->error(Glib::ustring("Film Negative: ") + msg);
    }
}

bool parseCube(const std::string &text, CubeLut &cube, std::string &error,
               std::string &logDeclared)
{
    cube.size = 0;
    cube.domainMin[0] = cube.domainMin[1] = cube.domainMin[2] = 0.f;
    cube.domainMax[0] = cube.domainMax[1] = cube.domainMax[2] = 1.f;
    cube.rgb.clear();
    int size1d = 0;
    int data1d = 0;
    bool saw3d = false;
    std::istringstream in(text);
    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty() && line[line.size() - 1] == '\r') {
            line.erase(line.size() - 1);
        }
        if (headerDeclaresLogOutput(line, logDeclared)) {
            error = "declares an unsupported log output transfer '" +
                    logDeclared +
                    "'. Supported decoded outputs are linear, sRGB and "
                    "gamma 2.4";
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
        if (low == "title" || low == "lut_in_video_range" ||
            low == "lut_out_video_range") {
            continue;
        }
        if (low == "lut_1d_size") {
            ls >> size1d;
            continue;
        }
        if (low == "lut_3d_size") {
            ls >> cube.size;
            saw3d = true;
            if (cube.size < 2 || cube.size > 128) {
                error = "LUT_3D_SIZE must be between 2 and 128";
                return false;
            }
            continue;
        }
        if (low == "domain_min") {
            ls >> cube.domainMin[0] >> cube.domainMin[1] >> cube.domainMin[2];
            continue;
        }
        if (low == "domain_max") {
            ls >> cube.domainMax[0] >> cube.domainMax[1] >> cube.domainMax[2];
            continue;
        }
        float r = 0.f, g = 0.f, b = 0.f;
        std::istringstream vs(trimmed);
        if (!(vs >> r >> g >> b)) {
            continue;
        }
        if (!saw3d && size1d > 0 && data1d < size1d) {
            ++data1d;
            continue;
        }
        cube.rgb.push_back(r);
        cube.rgb.push_back(g);
        cube.rgb.push_back(b);
    }
    if (!saw3d || cube.size < 2) {
        error = "file is not a 3D .cube (LUT_3D_SIZE is required). "
                "A 1D LUT is not a Cineon print LUT";
        return false;
    }
    const size_t expect =
        static_cast<size_t>(cube.size) * cube.size * cube.size * 3;
    if (cube.rgb.size() != expect) {
        error = "3D lattice length does not match LUT_3D_SIZE";
        return false;
    }
    for (int c = 0; c < 3; ++c) {
        if (!(cube.domainMax[c] > cube.domainMin[c])) {
            error = "DOMAIN_MAX must be greater than DOMAIN_MIN";
            return false;
        }
    }
    return true;
}

bool loadCube(const Glib::ustring &path, CubeLut &out, ProgressListener *pl)
{
    const std::string key = path.raw();
    if (!Glib::file_test(path, Glib::FILE_TEST_IS_REGULAR)) {
        std::lock_guard<std::mutex> lock(gCubeMutex);
        gCubeCache.erase(key);
        report(pl, Glib::ustring::compose(
                       "Cineon print LUT file is missing: '%1'. Set CineonLUT "
                       "to an existing .cube file; no other LUT was used",
                       path));
        return false;
    }
    std::ifstream in(Glib::filename_from_utf8(path).c_str(),
                     std::ios::in | std::ios::binary);
    if (!in) {
        std::lock_guard<std::mutex> lock(gCubeMutex);
        gCubeCache.erase(key);
        report(pl, Glib::ustring::compose(
                       "Cineon print LUT could not be read: '%1'. Check that "
                       "the file is readable; no other LUT was used",
                       path));
        return false;
    }
    std::ostringstream buf;
    buf << in.rdbuf();
    const std::string bytes = buf.str();
    const std::uint64_t hash = fnv1a(bytes);
    {
        std::lock_guard<std::mutex> lock(gCubeMutex);
        const auto it = gCubeCache.find(key);
        if (it != gCubeCache.end() && it->second.hash == hash) {
            out = it->second;
            return true;
        }
    }
    CubeLut parsed;
    parsed.hash = hash;
    std::string error;
    std::string logDeclared;
    if (!parseCube(bytes, parsed, error, logDeclared)) {
        std::lock_guard<std::mutex> lock(gCubeMutex);
        gCubeCache.erase(key);
        if (!logDeclared.empty()) {
            report(pl, Glib::ustring::compose(
                           "Cineon print LUT '%1' %2. Refusing the file; no "
                           "other LUT was used",
                           path, error));
        } else {
            report(pl, Glib::ustring::compose(
                           "Cineon print LUT '%1' is not usable (%2). No other "
                           "LUT was used",
                           path, error));
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

float cineonCode(float linear01, double referenceWhite)
{
    const double b = std::pow(10.0, (95.0 - 685.0) / 300.0);
    const double x = std::max(0.0, static_cast<double>(linear01)) / referenceWhite;
    return static_cast<float>(
        (685.0 + 300.0 * std::log10(x * (1.0 - b) + b)) / 1023.0);
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
                          const procparams::ColorManagementParams &icm)
{
    PrimariesMap map;
    map.active = false;
    // Matrix-shaper profiles only. If either name is empty or is not an
    // invertible ICC matrix profile, Cineon is encoded in the current working
    // RGB and the LUT result is treated as working RGB. A non-matrix colour
    // path is not added here.
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
        std::cerr << "Film Negative: Cineon LUT primaries '" << inProf
                  << "' / '" << outProf
                  << "' are not invertible matrix profiles. Encoding Cineon "
                     "in the working RGB and returning the LUT result as "
                     "working RGB.\n";
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

void applyCineonPrintLut(Imagefloat *img,
                         const procparams::FilmNegativeParams &params,
                         const procparams::ColorManagementParams &icm,
                         ProgressListener *pl)
{
    if (!img || params.cineonLUT.empty()) {
        return;
    }
    using Transfer = procparams::FilmNegativeParams::CineonLUTOutputTransfer;
    if (params.cineonLUTOutputTransfer == Transfer::UNSUPPORTED) {
        report(pl, "CineonLUTOutputTransfer is not linear, srgb or "
                   "gamma_2_4. The print LUT was not applied");
        return;
    }
    CubeLut cube;
    if (!loadCube(params.cineonLUT, cube, pl)) {
        return;
    }
    double referenceWhite = params.cineonReferenceWhite;
    if (referenceWhite < 1e-6) {
        referenceWhite = 1e-6;
    } else if (referenceWhite > 1e6) {
        referenceWhite = 1e6;
    }
    const PrimariesMap prim = primariesMap(params, icm);
    const int height = img->getHeight();
    const int width = img->getWidth();
    const float S = 65535.f;
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
            const float cr = cineonCode(r, referenceWhite);
            const float cg = cineonCode(g, referenceWhite);
            const float cb = cineonCode(b, referenceWhite);
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
            auto store = [](float v) -> float {
                if (!std::isfinite(v) || !(v > 0.f)) {
                    return 0.f;
                }
                return v * 65535.f;
            };
            img->r(row, col) = store(lr);
            img->g(row, col) = store(lg);
            img->b(row, col) = store(lb);
        }
    }
}

}} // namespace art::engine
