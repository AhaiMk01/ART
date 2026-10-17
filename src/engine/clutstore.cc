#include <algorithm>
#include <unordered_map>

#include "clutstore.h"

#include "iccstore.h"
#include "imagefloat.h"
#include "linalgebra.h"
#include "opthelper.h"
#include "rt_math.h"
#include "settings.h"
#include "stdimagesource.h"

#include <fstream>
#include <giomm.h>
#include <iostream>
#include <locale.h>
#include <sstream>

#include "../utils/multilangmgr.h"
#include "../gui/options.h"
#include "../utils/editid.h"
#include "../utils/pathutils.h"
#include "cJSON.h"

#define BENCHMARK
#include "StopWatch.h"

#ifdef _OPENMP
#include <omp.h>
#endif

namespace art { namespace engine {

extern const Settings *settings;

namespace {

bool loadFile(const Glib::ustring &filename,
              const Glib::ustring &working_color_space,
              AlignedBuffer<std::uint16_t> &clut_image,
              unsigned int &clut_level)
{
    art::engine::StdImageSource img_src;

    if (!Glib::file_test(filename, Glib::FILE_TEST_EXISTS) ||
        img_src.load(filename)) {
        return false;
    }

    int fw, fh;
    img_src.getFullSize(fw, fh, TR_NONE);

    bool res = false;

    if (fw == fh) {
        int level = 1;

        while (level * level * level < fw) {
            ++level;
        }

        if (level * level * level == fw && level > 1) {
            clut_level = level;
            res = true;
        }
    }

    if (res) {
        art::engine::ColorTemp curr_wb = img_src.getWB();
        std::unique_ptr<art::engine::Imagefloat> img_float =
            std::unique_ptr<art::engine::Imagefloat>(
                new art::engine::Imagefloat(fw, fh));
        const PreviewProps pp(0, 0, fw, fh, 1);

        art::engine::procparams::ColorManagementParams icm;
        icm.workingProfile = working_color_space;

        img_src.getImage(curr_wb, TR_NONE, img_float.get(), pp,
                         art::engine::procparams::ExposureParams(),
                         art::engine::procparams::RAWParams());

        if (!working_color_space.empty()) {
            img_src.convertColorSpace(img_float.get(), icm, curr_wb);
        }

        AlignedBuffer<std::uint16_t> image(
            fw * fh * 4 + 4); // getClutValues() loads one pixel in advance

        std::size_t index = 0;

        for (int y = 0; y < fh; ++y) {
            for (int x = 0; x < fw; ++x) {
                image.data[index] = img_float->r(y, x);
                ++index;
                image.data[index] = img_float->g(y, x);
                ++index;
                image.data[index] = img_float->b(y, x);
                index += 2;
            }
        }

        clut_image.swap(image);
    }

    return res;
}

#ifdef ART_SIMD
vfloat2 getClutValues(const AlignedBuffer<std::uint16_t> &clut_image,
                      size_t index)
{
    const vint v_values = _mm_loadu_si128(
        reinterpret_cast<const vint *>(clut_image.data + index));
#ifdef __SSE4_1__
    return {_mm_cvtepi32_ps(_mm_cvtepu16_epi32(v_values)),
            _mm_cvtepi32_ps(_mm_cvtepu16_epi32(_mm_srli_si128(v_values, 8)))};
#else
    const vint v_mask = _mm_set1_epi32(0x0000FFFF);

    vint v_low = _mm_shuffle_epi32(v_values, _MM_SHUFFLE(1, 0, 1, 0));
    vint v_high = _mm_shuffle_epi32(v_values, _MM_SHUFFLE(3, 2, 3, 2));
    v_low = _mm_shufflelo_epi16(v_low, _MM_SHUFFLE(1, 1, 0, 0));
    v_high = _mm_shufflelo_epi16(v_high, _MM_SHUFFLE(1, 1, 0, 0));
    v_low = _mm_shufflehi_epi16(v_low, _MM_SHUFFLE(3, 3, 2, 2));
    v_high = _mm_shufflehi_epi16(v_high, _MM_SHUFFLE(3, 3, 2, 2));
    v_low = vandm(v_low, v_mask);
    v_high = vandm(v_high, v_mask);

    return {_mm_cvtepi32_ps(v_low), _mm_cvtepi32_ps(v_high)};
#endif
}
#endif

} // namespace

art::engine::HaldCLUT::HaldCLUT()
    : clut_level(0), flevel_minus_one(0.0f), flevel_minus_two(0.0f),
      clut_profile("sRGB")
{
}

art::engine::HaldCLUT::~HaldCLUT() {}

bool art::engine::HaldCLUT::load(const Glib::ustring &filename)
{
    if (loadFile(filename, "", clut_image, clut_level)) {
        Glib::ustring name, ext;
        art::engine::CLUTStore::splitClutFilename(filename, name, ext,
                                               clut_profile);

        clut_filename = filename;
        clut_level *= clut_level;
        flevel_minus_one = static_cast<float>(clut_level - 1) / 65535.0f;
        flevel_minus_two = static_cast<float>(clut_level - 2);
        return true;
    }

    return false;
}

art::engine::HaldCLUT::operator bool() const { return !clut_image.isEmpty(); }

Glib::ustring art::engine::HaldCLUT::getFilename() const { return clut_filename; }

Glib::ustring art::engine::HaldCLUT::getProfile() const { return clut_profile; }

void art::engine::HaldCLUT::getRGB(float strength, std::size_t line_size,
                                const float *r, const float *g, const float *b,
                                float *out_rgbx) const
{
    const unsigned int level = clut_level; // This is important

    const unsigned int level_square = level * level;

#ifdef ART_SIMD
    const vfloat v_strength = F2V(strength);
#endif

    for (std::size_t column = 0; column < line_size;
         ++column, ++r, ++g, ++b, out_rgbx += 4) {
        const unsigned int red =
            std::min(flevel_minus_two, *r * flevel_minus_one);
        const unsigned int green =
            std::min(flevel_minus_two, *g * flevel_minus_one);
        const unsigned int blue =
            std::min(flevel_minus_two, *b * flevel_minus_one);

        const unsigned int color = red + green * level + blue * level_square;

#ifndef ART_SIMD
        const float re = *r * flevel_minus_one - red;
        const float gr = *g * flevel_minus_one - green;
        const float bl = *b * flevel_minus_one - blue;

        size_t index = color * 4;

        float tmp1[4] ALIGNED16;
        tmp1[0] =
            intp<float>(re, clut_image.data[index + 4], clut_image.data[index]);
        tmp1[1] = intp<float>(re, clut_image.data[index + 5],
                              clut_image.data[index + 1]);
        tmp1[2] = intp<float>(re, clut_image.data[index + 6],
                              clut_image.data[index + 2]);

        index = (color + level) * 4;

        float tmp2[4] ALIGNED16;
        tmp2[0] =
            intp<float>(re, clut_image.data[index + 4], clut_image.data[index]);
        tmp2[1] = intp<float>(re, clut_image.data[index + 5],
                              clut_image.data[index + 1]);
        tmp2[2] = intp<float>(re, clut_image.data[index + 6],
                              clut_image.data[index + 2]);

        out_rgbx[0] = intp<float>(gr, tmp2[0], tmp1[0]);
        out_rgbx[1] = intp<float>(gr, tmp2[1], tmp1[1]);
        out_rgbx[2] = intp<float>(gr, tmp2[2], tmp1[2]);

        index = (color + level_square) * 4;

        tmp1[0] =
            intp<float>(re, clut_image.data[index + 4], clut_image.data[index]);
        tmp1[1] = intp<float>(re, clut_image.data[index + 5],
                              clut_image.data[index + 1]);
        tmp1[2] = intp<float>(re, clut_image.data[index + 6],
                              clut_image.data[index + 2]);

        index = (color + level + level_square) * 4;

        tmp2[0] =
            intp<float>(re, clut_image.data[index + 4], clut_image.data[index]);
        tmp2[1] = intp<float>(re, clut_image.data[index + 5],
                              clut_image.data[index + 1]);
        tmp2[2] = intp<float>(re, clut_image.data[index + 6],
                              clut_image.data[index + 2]);

        tmp1[0] = intp<float>(gr, tmp2[0], tmp1[0]);
        tmp1[1] = intp<float>(gr, tmp2[1], tmp1[1]);
        tmp1[2] = intp<float>(gr, tmp2[2], tmp1[2]);

        out_rgbx[0] = intp<float>(bl, tmp1[0], out_rgbx[0]);
        out_rgbx[1] = intp<float>(bl, tmp1[1], out_rgbx[1]);
        out_rgbx[2] = intp<float>(bl, tmp1[2], out_rgbx[2]);

        out_rgbx[0] = intp<float>(strength, out_rgbx[0], *r);
        out_rgbx[1] = intp<float>(strength, out_rgbx[1], *g);
        out_rgbx[2] = intp<float>(strength, out_rgbx[2], *b);
#else
        const vfloat v_in = _mm_set_ps(0.0f, *b, *g, *r);
        const vfloat v_tmp = v_in * F2V(flevel_minus_one);
        const vfloat v_rgb = v_tmp - _mm_cvtepi32_ps(_mm_cvttps_epi32(
                                         vminf(v_tmp, F2V(flevel_minus_two))));

        size_t index = color * 4;

        const vfloat v_r = PERMUTEPS(v_rgb, _MM_SHUFFLE(0, 0, 0, 0));

        vfloat2 v_clut_values = getClutValues(clut_image, index);
        vfloat v_tmp1 = vintpf(v_r, v_clut_values.y, v_clut_values.x);

        index = (color + level) * 4;

        v_clut_values = getClutValues(clut_image, index);
        vfloat v_tmp2 = vintpf(v_r, v_clut_values.y, v_clut_values.x);

        const vfloat v_g = PERMUTEPS(v_rgb, _MM_SHUFFLE(1, 1, 1, 1));

        vfloat v_out = vintpf(v_g, v_tmp2, v_tmp1);

        index = (color + level_square) * 4;

        v_clut_values = getClutValues(clut_image, index);
        v_tmp1 = vintpf(v_r, v_clut_values.y, v_clut_values.x);

        index = (color + level + level_square) * 4;

        v_clut_values = getClutValues(clut_image, index);
        v_tmp2 = vintpf(v_r, v_clut_values.y, v_clut_values.x);

        v_tmp1 = vintpf(v_g, v_tmp2, v_tmp1);

        const vfloat v_b = PERMUTEPS(v_rgb, _MM_SHUFFLE(2, 2, 2, 2));

        v_out = vintpf(v_b, v_tmp1, v_out);

        STVF(*out_rgbx, vintpf(v_strength, v_out, v_in));
#endif
    }
}

art::engine::CLUTStore::CLUTName
art::engine::CLUTStore::getClutDisplayName(const Glib::ustring &filename)
{
    Glib::ustring name;

#ifdef ART_USE_CTL
    if (getFileExtension(filename) == "ctl") {
        int order = -1;
        if (CTLStore::getDisplayName(filename, name, order)) {
            return CLUTName(name, order);
        }
    }
#endif // ART_USE_CTL

#ifdef ART_USE_OCIO
    if (getFileExtension(filename) == "json") {
        ExternalLUT3D extlut(filename);
        if (extlut.ok()) {
            return extlut.get_display_name();
        } else {
            return CLUTName("");
        }
    }
#endif // ART_USE_OCIO

    Glib::ustring dummy;
    splitClutFilename(filename, name, dummy, dummy);
    return name;
}

void art::engine::CLUTStore::splitClutFilename(const Glib::ustring &filename,
                                            Glib::ustring &name,
                                            Glib::ustring &extension,
                                            Glib::ustring &profile_name)
{
    Glib::ustring basename = Glib::path_get_basename(filename);

    const Glib::ustring::size_type last_dot_pos = basename.rfind('.');

    if (last_dot_pos != Glib::ustring::npos) {
        name.assign(basename, 0, last_dot_pos);
        extension.assign(basename, last_dot_pos + 1, Glib::ustring::npos);
    } else {
        name = basename;
    }

    profile_name = "sRGB";

    bool search_profile_name = true;
#ifdef ART_USE_OCIO
    search_profile_name = !(extension.casefold().find("clf") == 0) &&
                          !(extension.casefold() == "json");
#endif // ART_USE_OCIO
#ifdef ART_USE_CTL
    search_profile_name =
        search_profile_name && !(extension.casefold().find("ctl") == 0);
#endif // ART_USE_CTL
    if (search_profile_name && !name.empty()) {
        for (const auto &working_profile :
             art::engine::ICCStore::getInstance()->getWorkingProfiles()) {
            if (!working_profile
                     .empty() // This isn't strictly needed, but an empty wp
                              // name should be skipped anyway
                && std::search(name.rbegin(), name.rend(),
                               working_profile.rbegin(),
                               working_profile.rend()) == name.rbegin()) {
                profile_name = working_profile;
                name.erase(name.size() - working_profile.size());
                break;
            }
        }
    } else if (!search_profile_name) {
        profile_name = "";
    }
}

art::engine::CLUTStore &art::engine::CLUTStore::getInstance()
{
    static CLUTStore instance;
    return instance;
}

std::shared_ptr<art::engine::HaldCLUT>
art::engine::CLUTStore::getHaldClut(const Glib::ustring &filename) const
{
    art::utils::MyMutex::MyLock lock(mutex_);
    std::shared_ptr<art::engine::HaldCLUT> result;

    const Glib::ustring full_filename =
        !Glib::path_is_absolute(filename)
            ? Glib::ustring(Glib::build_filename(art::gui::options.clutsDir, filename))
            : filename;

    if (!cache.get(full_filename, result)) {
        std::unique_ptr<art::engine::HaldCLUT> clut(new art::engine::HaldCLUT);

        if (clut->load(full_filename)) {
            result = std::move(clut);
            cache.insert(full_filename, result);
        }
    }

    return result;
}

#ifdef ART_USE_OCIO

namespace {

std::string decompress_to_temp(const Glib::ustring &fname)
{
    std::string templ = Glib::build_filename(
        Glib::get_tmp_dir(),
        Glib::ustring::compose("ART-ocio-clf-%1-XXXXXX",
                               Glib::path_get_basename(fname)));
    int fd = Glib::mkstemp(templ);
    if (fd < 0) {
        throw "error";
    }

    close(fd);
    bool err = false;

    auto f = Gio::File::create_for_path(templ);
    auto s = f->append_to();
    auto c = Gio::ZlibDecompressor::create(Gio::ZLIB_COMPRESSOR_FORMAT_GZIP);
    {
        auto stream = Gio::ConverterOutputStream::create(s, c);
        stream->set_close_base_stream(true);
        constexpr gsize chunk = 512;
        char buffer[chunk];
        auto src_fname = Glib::filename_from_utf8(fname);
        FILE *src = g_fopen(src_fname.c_str(), "rb");
        if (!src) {
            err = true;
        } else {
            try {
                size_t n = 0;
                while ((n = fread(buffer, 1, chunk, src)) > 0) {
                    stream->write(buffer, n);
                }
            } catch (...) {
                err = true;
            }
            fclose(src);
        }
    }

    if (err) {
        g_remove(templ.c_str());
        throw "error";
    }
    return templ;
}

std::string copy_to_temp(const Glib::ustring &fname)
{
    std::string templ = Glib::build_filename(
        Glib::get_tmp_dir(),
        Glib::ustring::compose("ART-ocio-clf-%1-XXXXXX",
                               Glib::path_get_basename(fname)));
    int fd = Glib::mkstemp(templ);
    if (fd < 0) {
        throw "error";
    }

    close(fd);
    bool err = false;

    auto f = Gio::File::create_for_path(templ);
    {
        auto stream = f->append_to();
        constexpr gsize chunk = 512;
        char buffer[chunk];
        auto src_fname = Glib::filename_from_utf8(fname);
        FILE *src = g_fopen(src_fname.c_str(), "rb");
        if (!src) {
            err = true;
        } else {
            try {
                size_t n = 0;
                while ((n = fread(buffer, 1, chunk, src)) > 0) {
                    stream->write(buffer, n);
                }
            } catch (...) {
                err = true;
            }
            fclose(src);
        }
    }

    if (err) {
        g_remove(templ.c_str());
        throw "error";
    }
    return templ;
}

} // namespace

OCIO::ConstProcessorRcPtr
art::engine::CLUTStore::getOCIOLut(const Glib::ustring &filename) const
{
    art::utils::MyMutex::MyLock lock(mutex_);

    OCIOCacheEntry result;
    OCIO::ConstProcessorRcPtr retval;

    const Glib::ustring full_filename =
        !Glib::path_is_absolute(filename)
            ? Glib::ustring(Glib::build_filename(art::gui::options.clutsDir, filename))
            : filename;

    auto ext = getFileExtension(full_filename);
    if (ext != "clf" && ext != "clfz") {
        return retval;
    }

    const auto md5 = getMD5(full_filename, true);

    bool found = ocio_cache_.get(full_filename, result);
    if (!found || result.second != md5) {
        if (settings->verbose > 1) {
            std::cout << "CLF cache miss: " << full_filename << std::endl;
        }
        StopWatch load_CLF("CLF LUT load", true);

        std::string fn = "";
        bool del_fn = false;
        try {
            OCIO::ConstConfigRcPtr config = OCIO::Config::CreateRaw();
            OCIO::FileTransformRcPtr t = OCIO::FileTransform::Create();
            if (ext == "clfz") {
                fn = decompress_to_temp(full_filename);
                del_fn = true;
            } else {
                fn = copy_to_temp(full_filename);
                del_fn = true;
            }
            t->setSrc(fn.c_str());
            t->setInterpolation(OCIO::INTERP_BEST);
            retval = config->getProcessor(t);
            result = std::make_pair(retval, md5);
            ocio_cache_.set(full_filename, result);
        } catch (...) {
        }
        if (del_fn && !fn.empty()) {
            g_remove(fn.c_str());
        }
    } else {
        retval = result.first;
    }

    return retval;
}

ExternalLUT3D CLUTStore::getExternalLut(const Glib::ustring &filename) const
{
    art::utils::MyMutex::MyLock lock(mutex_);

    ExternalLUT3D retval;

    const Glib::ustring full_filename =
        !Glib::path_is_absolute(filename)
            ? Glib::ustring(Glib::build_filename(art::gui::options.clutsDir, filename))
            : filename;

    auto ext = getFileExtension(full_filename);
    if (ext != "json") {
        return retval;
    }

    retval.init(full_filename);
    return retval;
}

#endif // ART_USE_OCIO

#ifdef ART_USE_CTL

std::pair<std::shared_ptr<Ctl::Interpreter>, std::vector<Ctl::FunctionCallPtr>>
art::engine::CLUTStore::getCTLLut(const Glib::ustring &filename,
                                  int num_threads, int &chunk_size,
                                  CLUTParamDescriptorList &params,
                                  Glib::ustring &colorspace, int &lut_dim) const
{
    return CTLStore::getInstance().getLut(filename, num_threads, chunk_size,
                                          params, colorspace, lut_dim);
}

#endif // ART_USE_CTL

void art::engine::CLUTStore::clearCache()
{
    art::utils::MyMutex::MyLock lock(mutex_);

    cache.clear();
#ifdef ART_USE_OCIO
    ocio_cache_.clear();
#endif // ART_USE_OCIO
#ifdef ART_USE_CTL
    CTLStore::getInstance().clearCache();
#endif // ART_USE_CTL
}

art::engine::CLUTStore::CLUTStore()
    : cache(art::gui::options.clutCacheSize)
#ifdef ART_USE_OCIO
      ,
      ocio_cache_(art::gui::options.clutCacheSize)
#endif // ART_USE_OCIO
{
}

#ifdef ART_USE_CTL

float CLUTStore::CTL_shaper(float a, bool inv)
{
    return CTLStore::shaper(a, inv);
}

#endif // ART_USE_CTL

//-----------------------------------------------------------------------------
// CLUTApplication
//-----------------------------------------------------------------------------

CLUTApplication::CLUTApplication(const Glib::ustring &clut_filename,
                                 const Glib::ustring &working_profile,
                                 float strength, int num_threads)
    : clut_filename_(clut_filename), working_profile_(working_profile),
      ok_(false), clut_and_working_profiles_are_same_(false),
      num_threads_(num_threads), strength_(strength)
{
    init(num_threads);
}

void CLUTApplication::init(int num_threads)
{
    hald_clut_ = CLUTStore::getInstance().getHaldClut(clut_filename_);
    if (!hald_clut_) {
#ifdef ART_USE_OCIO
        if (!OCIO_init())
            if (!extlut_init())
#endif // ART_USE_OCIO
#ifdef ART_USE_CTL
                if (!CTL_init(num_threads))
#endif // ART_USE_CTL
                    ok_ = false;
        return;
    }

    clut_and_working_profiles_are_same_ =
        hald_clut_->getProfile() == working_profile_;

    if (!clut_and_working_profiles_are_same_) {
        wprof_ = ICCStore::getInstance()->workingSpaceMatrix(working_profile_);
        wiprof_ = ICCStore::getInstance()->workingSpaceInverseMatrix(
            working_profile_);

        xyz2clut_ = ICCStore::getInstance()->workingSpaceInverseMatrix(
            hald_clut_->getProfile());
        clut2xyz_ = ICCStore::getInstance()->workingSpaceMatrix(
            hald_clut_->getProfile());

#ifdef ART_SIMD
        for (int i = 0; i < 3; ++i) {
            for (int j = 0; j < 3; ++j) {
                v_work2xyz_[i][j] = F2V(wprof_[i][j]);
                v_xyz2clut_[i][j] = F2V(xyz2clut_[i][j]);
                v_xyz2work_[i][j] = F2V(wiprof_[i][j]);
                v_clut2xyz_[i][j] = F2V(clut2xyz_[i][j]);
            }
        }
#endif
    }

    ok_ = true;
}

#ifdef ART_USE_OCIO

bool CLUTApplication::OCIO_init()
{
    auto proc = CLUTStore::getInstance().getOCIOLut(clut_filename_);
    if (!proc) {
        ok_ = false;
        return false;
    }

    try {
        ok_ = true;

        ocio_processor_ = proc->getOptimizedCPUProcessor(
            OCIO::BIT_DEPTH_F32, OCIO::BIT_DEPTH_F32,
            OCIO::OPTIMIZATION_DEFAULT);
        init_matrices("ACESp0");
        return true;
    } catch (...) {
        ok_ = false;
        return false;
    }
}

bool CLUTApplication::extlut_init()
{
    ext_lut_ = CLUTStore::getInstance().getExternalLut(clut_filename_);
    if (!ext_lut_.ok()) {
        ok_ = false;
        return false;
    }

    init_matrices("ACESp0");
    ok_ = true;
    return true;
}
#endif // ART_USE_OCIO

#ifdef ART_USE_CTL

bool CLUTApplication::CTL_init(int num_threads)
{
    try {
        Glib::ustring colorspace = "";
        if (!ctl_.init(clut_filename_, num_threads, colorspace)) {
            ok_ = false;
            return false;
        }
        init_matrices(colorspace);
        ok_ = true;
        return true;
    } catch (...) {
        ok_ = false;
        return false;
    }
}

#endif // ART_USE_CTL

CLUTParamDescriptorList CLUTApplication::get_param_descriptors() const
{
#ifdef ART_USE_CTL
    if (!ctl_.empty()) {
        return ctl_.params();
    }
#endif // ART_USE_CTL
#ifdef ART_USE_OCIO
    if (ext_lut_.ok()) {
        return ext_lut_.get_param_descriptors();
    }
#endif // ART_USE_OCIO
    return {};
}

bool CLUTApplication::set_param_values(const CLUTParamValueMap &values,
                                       Quality q)
{
#ifdef ART_USE_CTL
    if (!ctl_.empty()) {
        return ctl_.set_params(values, int(q));
    }
#endif // ART_USE_CTL
#ifdef ART_USE_OCIO
    if (ext_lut_.ok()) {
        if (ext_lut_.set_param_values(values)) {
            ocio_processor_ = ext_lut_.get_processor();
            return true;
        } else {
            return false;
        }
    }
#endif // ART_USE_OCIO
    return values.empty();
}

CLUTParamDescriptorList
CLUTApplication::get_param_descriptors(const Glib::ustring &filename)
{
#ifdef ART_USE_OCIO
    if (getFileExtension(filename) == "json") {
        ExternalLUT3D extlut(filename);
        if (extlut.ok()) {
            return extlut.get_param_descriptors();
        } else {
            return {};
        }
    } else
#endif // ART_USE_OCIO
#ifdef ART_USE_CTL
        try {
            CLUTParamDescriptorList params;
            int n = 0;
            Glib::ustring colorspace;
            auto p = CLUTStore::getInstance().getCTLLut(filename, 1, n, params,
                                                        colorspace, n);
            return params;
        } catch (...) {
        }
#endif // ART_USE_CTL
    return {};
}

#if defined ART_USE_OCIO || defined ART_USE_CTL

void CLUTApplication::init_matrices(const Glib::ustring &lut_profile)
{
    wprof_ = ICCStore::getInstance()->workingSpaceMatrix(working_profile_);
    wiprof_ =
        ICCStore::getInstance()->workingSpaceInverseMatrix(working_profile_);
    if (lut_profile.empty()) {
        for (int i = 0; i < 3; ++i) {
            for (int j = 0; j < 3; ++j) {
                float val = (i == j) ? 1.f : 0.f;
                conv_[i][j] = val;
                iconv_[i][j] = val * 65535.f;
            }
        }
    } else {
        auto lprof = ICCStore::getInstance()->workingSpaceMatrix(lut_profile);
        auto liprof =
            ICCStore::getInstance()->workingSpaceInverseMatrix(lut_profile);

        auto ws = dot_product(liprof, wprof_);
        auto iws = dot_product(wiprof_, lprof);

        for (int i = 0; i < 3; ++i) {
            for (int j = 0; j < 3; ++j) {
                conv_[i][j] = ws[i][j];
                iconv_[i][j] = iws[i][j] * 65535.f;
            }
        }
    }
}

#endif // ART_USE_OCIO || ART_USE_CTL

void CLUTApplication::operator()(Imagefloat *img)
{
    if (!ok_) {
        return;
    }

    const int W = img->getWidth();
    const int H = img->getHeight();

#ifdef _OPENMP
#pragma omp parallel for if (num_threads_ > 1) num_threads(num_threads_)
#endif
    for (int y = 0; y < H; ++y) {
#ifdef _OPENMP
        int thread_id = omp_get_thread_num();
#else
        int thread_id = 0;
#endif
        apply(thread_id, W, img->r(y), img->g(y), img->b(y));
    }
}

bool CLUTApplication::set_num_threads(int num_threads)
{
    if (!ok_) {
        return false;
    }
#ifdef ART_USE_CTL
    if (!ctl_.empty()) {
        return false;
    }
#endif
    num_threads_ = num_threads;
    return true;
}

inline void CLUTApplication::do_apply(int W, float *r, float *g, float *b)
{
    AlignedBuffer<float> buf_out_rgbx(4 * W); // Line buffer for CLUT
    AlignedBuffer<float> buf_clutr(W);
    AlignedBuffer<float> buf_clutg(W);
    AlignedBuffer<float> buf_clutb(W);
    float *out_rgbx = buf_out_rgbx.data;
    float *clutr = buf_clutr.data;
    float *clutg = buf_clutg.data;
    float *clutb = buf_clutb.data;

    if (!clut_and_working_profiles_are_same_) {
        // Convert from working to clut profile
        int j = 0;

#ifdef ART_SIMD
        for (; j < W - 3; j += 4) {
            vfloat sourceR = LVF(r[j]);
            vfloat sourceG = LVF(g[j]);
            vfloat sourceB = LVF(b[j]);

            vfloat x;
            vfloat y;
            vfloat z;
            Color::rgbxyz(sourceR, sourceG, sourceB, x, y, z, v_work2xyz_);
            Color::xyz2rgb(x, y, z, sourceR, sourceG, sourceB, v_xyz2clut_);

            STVF(clutr[j], sourceR);
            STVF(clutg[j], sourceG);
            STVF(clutb[j], sourceB);
        }

#endif

        for (; j < W; j++) {
            float sourceR = r[j];
            float sourceG = g[j];
            float sourceB = b[j];

            float x, y, z;
            Color::rgbxyz(sourceR, sourceG, sourceB, x, y, z, wprof_);
            Color::xyz2rgb(x, y, z, clutr[j], clutg[j], clutb[j], xyz2clut_);
        }
    } else {
        memcpy(clutr, r, sizeof(float) * W);
        memcpy(clutg, g, sizeof(float) * W);
        memcpy(clutb, b, sizeof(float) * W);
    }

    for (int j = 0; j < W; j++) {
        float &sourceR = clutr[j];
        float &sourceG = clutg[j];
        float &sourceB = clutb[j];

        // Apply gamma sRGB (default RT)
        sourceR = Color::gamma_srgbclipped(sourceR);
        sourceG = Color::gamma_srgbclipped(sourceG);
        sourceB = Color::gamma_srgbclipped(sourceB);
    }

    hald_clut_->getRGB(strength_, W, clutr, clutg, clutb, out_rgbx);

    for (int j = 0; j < W; j++) {
        float &sourceR = clutr[j];
        float &sourceG = clutg[j];
        float &sourceB = clutb[j];

        // Apply inverse gamma sRGB
        sourceR = Color::igamma_srgb(out_rgbx[j * 4 + 0]);
        sourceG = Color::igamma_srgb(out_rgbx[j * 4 + 1]);
        sourceB = Color::igamma_srgb(out_rgbx[j * 4 + 2]);
    }

    if (!clut_and_working_profiles_are_same_) {
        // Convert from clut to working profile
        int j = 0;

#ifdef ART_SIMD

        for (; j < W - 3; j += 4) {
            vfloat sourceR = LVF(clutr[j]);
            vfloat sourceG = LVF(clutg[j]);
            vfloat sourceB = LVF(clutb[j]);

            vfloat x;
            vfloat y;
            vfloat z;
            Color::rgbxyz(sourceR, sourceG, sourceB, x, y, z, v_clut2xyz_);
            Color::xyz2rgb(x, y, z, sourceR, sourceG, sourceB, v_xyz2work_);

            STVF(clutr[j], sourceR);
            STVF(clutg[j], sourceG);
            STVF(clutb[j], sourceB);
        }

#endif

        for (; j < W; j++) {
            float &sourceR = clutr[j];
            float &sourceG = clutg[j];
            float &sourceB = clutb[j];

            float x, y, z;
            Color::rgbxyz(sourceR, sourceG, sourceB, x, y, z, clut2xyz_);
            Color::xyz2rgb(x, y, z, sourceR, sourceG, sourceB, wiprof_);
        }
    }

    for (int j = 0; j < W; j++) {
        r[j] = clutr[j];
        g[j] = clutg[j];
        b[j] = clutb[j];
    }
}

#ifdef ART_USE_OCIO

inline void CLUTApplication::OCIO_apply(int W, float *r, float *g, float *b)
{
    const bool blend = strength_ < 1.f;

    Vec3<float> v;
    std::vector<float> data(W * 3);
    for (int x = 0, i = 0; x < W; ++x) {
        v[0] = r[x] / 65535.f;
        v[1] = g[x] / 65535.f;
        v[2] = b[x] / 65535.f;
        v = dot_product(conv_, v);
        data[i++] = v[0];
        data[i++] = v[1];
        data[i++] = v[2];
    }

    OCIO::PackedImageDesc pd(&data[0], W, 1, 3);
    ocio_processor_->apply(pd);

    for (int x = 0, i = 0; x < W; ++x) {
        v[0] = data[i++];
        v[1] = data[i++];
        v[2] = data[i++];
        v = dot_product(iconv_, v);
        // no need to renormalize to 65535 as this is already done in iconv_
        if (blend) {
            r[x] = intp(strength_, v[0], r[x]);
            g[x] = intp(strength_, v[1], g[x]);
            b[x] = intp(strength_, v[2], b[x]);
        } else {
            r[x] = v[0];
            g[x] = v[1];
            b[x] = v[2];
        }
    }
}

#endif // ART_USE_OCIO

#ifdef ART_USE_CTL

inline void CLUTApplication::CTL_apply(int thread_id, int W, float *r, float *g,
                                       float *b)
{
    if (!ctl_.empty()) {
        Vec3<float> v;
        std::vector<float> rgb[3];
        for (int i = 0; i < 3; ++i) {
            rgb[i].resize(W);
        }

        for (int x = 0; x < W; ++x) {
            v[0] = r[x] / 65535.f;
            v[1] = g[x] / 65535.f;
            v[2] = b[x] / 65535.f;
            v = dot_product(conv_, v);
            rgb[0][x] = v[0];
            rgb[1][x] = v[1];
            rgb[2][x] = v[2];
        }

        ctl_.apply(thread_id, W, rgb[0].data(), rgb[1].data(), rgb[2].data());

        const bool blend = strength_ < 1.f;

        for (int x = 0; x < W; ++x) {
            v[0] = rgb[0][x];
            v[1] = rgb[1][x];
            v[2] = rgb[2][x];
            v = dot_product(iconv_, v);
            // no need to renormalize to 65535 as this is already done in iconv_
            if (blend) {
                r[x] = intp(strength_, v[0], r[x]);
                g[x] = intp(strength_, v[1], g[x]);
                b[x] = intp(strength_, v[2], b[x]);
            } else {
                r[x] = v[0];
                g[x] = v[1];
                b[x] = v[2];
            }
        }
    }
}

#endif // ART_USE_CTL

bool CLUTApplication::hasPipette() const
{
#ifdef ART_USE_CTL
    return ok_ && ctl_.has_pipette();
#else
    return false;
#endif
}

bool CLUTApplication::fillPipette(int thread_id, int curve_id, int W, float *r,
                                  float *g, float *b)
{
#ifdef ART_USE_CTL
    if (!hasPipette() || !ctl_.can_pipette(thread_id)) {
        return false;
    }
    std::vector<float> rgb[3];
    for (int i = 0; i < 3; ++i) {
        rgb[i].resize(W);
    }
    Vec3<float> v;
    for (int x = 0; x < W; ++x) {
        v[0] = r[x] / 65535.f;
        v[1] = g[x] / 65535.f;
        v[2] = b[x] / 65535.f;
        v = dot_product(conv_, v);
        rgb[0][x] = v[0];
        rgb[1][x] = v[1];
        rgb[2][x] = v[2];
    }
    const float *in[3] = {rgb[0].data(), rgb[1].data(), rgb[2].data()};
    float *const out[3] = {r, g, b};
    return ctl_.fill_pipette(thread_id, curve_id, W, in, out);
#endif // ART_USE_CTL
    return false;
}

void CLUTApplication::apply(int thread_id, int W, float *r, float *g, float *b)
{
    if (!ok_) {
        return;
    }

#ifdef ART_USE_OCIO
    if (ocio_processor_) {
        OCIO_apply(W, r, g, b);
        return;
    }
#endif
#ifdef ART_USE_CTL
    if (!ctl_.empty()) {
        try {
            CTL_apply(thread_id, W, r, g, b);
        } catch (std::exception &exc) {
            if (settings->verbose) {
                std::cout << "Error in applying CTL LUT " << clut_filename_
                          << ": " << exc.what() << std::endl;
            }
        }
        return;
    }
#endif

    do_apply(W, r, g, b);
}

#ifdef ART_USE_OCIO

OCIOInputProfile::OCIOInputProfile(const Glib::ustring &clut_filename,
                                   const Glib::ustring &working_profile,
                                   int num_threads)
    : CLUTApplication(!clut_filename.compare(0, 5, "file:")
                          ? clut_filename.substr(5)
                          : clut_filename,
                      working_profile, 1.f, num_threads)
{
    if (!ok_ || !ocio_processor_) {
        ok_ = false;
    } else {
        init_matrices("");
        for (int i = 0; i < 3; ++i) {
            for (int j = 0; j < 3; ++j) {
                iconv_[i][j] = wiprof_[i][j] * 65535.f;
            }
        }
    }
}

#endif // ART_USE_OCIO

}} // namespace art::engine
