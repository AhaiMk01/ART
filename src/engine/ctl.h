/** -*- C++ -*-
 *
 *  This file is part of ART
 *
 *  Copyright (c) 2026 Alberto Griggio <alberto.griggio@gmail.com>
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

#pragma once

#ifdef ART_USE_CTL

#include <glibmm.h>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "LUT3D.h"
#include "cache.h"
#include "clutparams.h"
#include "noncopyable.h"
#include <CtlSimdInterpreter.h>

namespace art { namespace engine {

/**
 * Loads (and caches) CTL scripts. CLUTStore forwards its CTL entry points here.
 */
class CTLStore final: public NonCopyable {
public:
    static CTLStore &getInstance();

    /// see CLUTStore::getCTLLut. If md5 is not null, it is set to the
    /// checksum of the script
    std::pair<std::shared_ptr<Ctl::Interpreter>,
              std::vector<Ctl::FunctionCallPtr>>
    getLut(const Glib::ustring &filename, int num_threads, int &chunk_size,
           CLUTParamDescriptorList &params, Glib::ustring &colorspace,
           int &lut_dim, std::string *md5 = nullptr) const;

    /// Cache of the 3D LUTs baked from a script. The key identifies the
    /// script and the values of its parameters, but not the dimension of the
    /// LUT: findLut3d() hits if the cached LUT is at least min_dim large (a
    /// bigger LUT is only more accurate), and storeLut3d() never replaces a
    /// LUT with a smaller one.
    std::shared_ptr<const LUT3D> findLut3d(const std::string &key,
                                           int min_dim) const;
    void storeLut3d(const std::string &key, std::shared_ptr<const LUT3D> lut);

    /// Perceptual shaper applied to the input of the baked 3D LUT
    /// (inv == true for the inverse)
    static float shaper(float a, bool inv);

    /// Extract the GUI name and the sort order (@ART-label, @ART-order) from
    /// the script. Returns true if a label was found
    static bool getDisplayName(const Glib::ustring &filename,
                               Glib::ustring &name, int &order);

    void clearCache();

private:
    CTLStore();

    struct CacheEntry {
        std::shared_ptr<Ctl::Interpreter> intp;
        std::string md5;
        CLUTParamDescriptorList params;
        Glib::ustring colorspace;
        int lut_dim;
    };
    mutable Cache<std::string, CacheEntry> cache_;
    mutable art::utils::MyMutex mutex_;

    mutable Cache<std::string, std::shared_ptr<const LUT3D>> lut_cache_;
    mutable art::utils::MyMutex lut_mutex_;
};


/**
 * The CTL state of a CLUTApplication: the script instances (one per thread),
 * its parameters and the 3D LUT baked from it. Works in the colour space of
 * the script: conversions from/to the working profile and blending are up to
 * the caller.
 */
class CTLApplication {
public:
    CTLApplication();

    /// load the script; the colour space it expects is returned in colorspace
    bool init(const Glib::ustring &filename, int num_threads,
              Glib::ustring &colorspace);

    /// true if no script is loaded
    bool empty() const { return func_.empty(); }

    const CLUTParamDescriptorList &params() const { return params_; }

    /// set the parameters, and (re)compute the 3D LUT if needed. max_dim is
    /// the cap on the LUT dimension requested by the quality (0 for none)
    bool set_params(const CLUTParamValueMap &values, int max_dim);

    /// transform W pixels in place
    void apply(int thread_id, int W, float *r, float *g, float *b);

    bool has_pipette() const { return !pipette_func_.empty(); }
    bool can_pipette(int thread_id) const
    {
        return thread_id >= 0 && size_t(thread_id) < pipette_func_.size();
    }
    /// see CLUTApplication::fillPipette. in: pixels already converted to the
    /// colour space of the script
    bool fill_pipette(int thread_id, int curve_id, int W,
                      const float *const in[3], float *const out[3]);

private:
    std::string lut_key(const CLUTParamValueMap &values) const;
    std::shared_ptr<const LUT3D> compute_lut(int dim);

    Glib::ustring filename_;
    std::string md5_;
    std::shared_ptr<Ctl::Interpreter> intp_;
    std::vector<Ctl::FunctionCallPtr> func_;
    std::vector<Ctl::FunctionCallPtr> pipette_func_;
    int chunk_size_;
    CLUTParamDescriptorList params_;
    std::shared_ptr<const LUT3D> lut_;
    int lut_dim_;
};

}} // namespace art::engine

#endif // ART_USE_CTL
