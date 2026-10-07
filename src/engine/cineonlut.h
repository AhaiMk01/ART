#pragma once

#include "imagefloat.h"
#include "procparams.h"
#include "rtengine.h"

namespace art { namespace engine {

// Encodes the film-negative linear buffer as Cineon, evaluates a .cube,
// decodes the declared output transfer, and writes linear working RGB back.
// Returns false when the LUT is missing, changed, or not a declared linear
// output. The linear inversion is left unchanged and no other LUT is used.
// An empty CineonLUT is not an error and returns true.
bool applyCineonPrintLut(Imagefloat *img,
                         const procparams::FilmNegativeParams &params,
                         const procparams::ColorManagementParams &icm,
                         ProgressListener *pl);
Glib::ustring cineonLutSha256(const Glib::ustring &path);

}} // namespace art::engine
