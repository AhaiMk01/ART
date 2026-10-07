#pragma once

#include "imagefloat.h"
#include "procparams.h"
#include "rtengine.h"

namespace art { namespace engine {

// Encodes the film-negative linear buffer as Cineon, evaluates a .cube,
// decodes the declared output transfer, and writes linear working RGB back.
// A missing, unreadable, hash-changed-but-unreadable, or log-output LUT is
// an error: the linear inversion is left unchanged and no other LUT is used.
void applyCineonPrintLut(Imagefloat *img,
                         const procparams::FilmNegativeParams &params,
                         const procparams::ColorManagementParams &icm,
                         ProgressListener *pl);

}} // namespace art::engine
