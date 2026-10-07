#pragma once

#include <glibmm.h>

namespace art { namespace engine {

// Reference paper responses (DiVERE curve assets, MIT). Shared RGB, then
// per-channel, in density space:
//   R = log10(65536), u = 1 - clamp(C / R, 0, 1), v = interp(u),
//   C = R * (1 - v).
// Unknown identifiers are not substituted.

struct PaperCurve {
    const char *id;
    int nRgb;
    const double *rgbX;
    const double *rgbY;
    int nR;
    const double *rX;
    const double *rY;
    int nG;
    const double *gX;
    const double *gY;
    int nB;
    const double *bX;
    const double *bY;
};

const PaperCurve *findPaperCurve(const Glib::ustring &id);

// false: id unknown, densities unchanged. true: shared curve then the
// matching channel curve applied to each density.
bool applyPaperCurves(double &c0, double &c1, double &c2,
                      const Glib::ustring &id);

}} // namespace art::engine
