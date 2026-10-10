#pragma once

#include "imagefloat.h"
#include "procparams.h"
#include "rtengine.h"

namespace art { namespace engine {

// Standard Cineon, normalized 10-bit codes, black=95 and white=685.
// Signed encoding is used for NamiColor; Density retains its zero floor.
double encodeFilmCineon(double linear01, double referenceWhite,
                        bool preserveSigned);
double decodeFilmCineon(double code, double referenceWhite);

// Converts linear working RGB to the chosen LUT primaries and input transfer,
// evaluates a .cube, then returns its decoded output to linear working RGB.
// Returns false on a LUT contract failure. An empty LUT is a no-op.
bool applyCineonPrintLut(Imagefloat *img,
                         const procparams::FilmNegativeParams &params,
                         const procparams::ColorManagementParams &icm,
                         ProgressListener *pl);
Glib::ustring cineonLutSha256(const Glib::ustring &path);

}} // namespace art::engine
