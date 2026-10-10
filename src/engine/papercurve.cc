/*
 * Reference paper print curves.
 *
 * Point data is from DiVERE (https://github.com/V7CN/DiVERE), config/curves/,
 * MIT License, Copyright (c) 2025 V7. See data/filmcurves/LICENSE-DiVERE.txt.
 * Source arrays are sorted by increasing x when the table is generated.
 * Piecewise-linear interpolation clamps to the endpoint y outside the
 * points' x domain.
 */
#include "papercurve.h"

#include <cmath>

namespace art { namespace engine {


#include "papercurves.inc"

namespace {

double interp(const double *x, const double *y, int n, double u)
{
    if (n <= 0) {
        return u;
    }
    if (u <= x[0]) {
        return y[0];
    }
    if (u >= x[n - 1]) {
        return y[n - 1];
    }
    int lo = 0;
    int hi = n - 1;
    while (hi - lo > 1) {
        int mid = (lo + hi) / 2;
        if (x[mid] <= u) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    double span = x[hi] - x[lo];
    double t = span != 0.0 ? (u - x[lo]) / span : 0.0;
    return y[lo] + t * (y[hi] - y[lo]);
}

double applyOne(double density, const double *x, const double *y, int n)
{
    const double range = std::log10(65536.0);
    double ratio = density / range;
    if (ratio < 0.0) {
        ratio = 0.0;
    } else if (ratio > 1.0) {
        ratio = 1.0;
    }
    double u = 1.0 - ratio;
    double v = interp(x, y, n, u);
    return range * (1.0 - v);
}

} // namespace

const PaperCurve *findPaperCurve(const Glib::ustring &id)
{
    const int n = (int)(sizeof(kPaperCurves) / sizeof(kPaperCurves[0]));
    for (int i = 0; i < n; ++i) {
        if (id == kPaperCurves[i].id) {
            return &kPaperCurves[i];
        }
    }
    return nullptr;
}

bool applyPaperCurves(double &c0, double &c1, double &c2,
                      const Glib::ustring &id)
{
    const PaperCurve *curve = findPaperCurve(id);
    if (!curve) {
        return false;
    }
    c0 = applyOne(c0, curve->rgbX, curve->rgbY, curve->nRgb);
    c1 = applyOne(c1, curve->rgbX, curve->rgbY, curve->nRgb);
    c2 = applyOne(c2, curve->rgbX, curve->rgbY, curve->nRgb);
    c0 = applyOne(c0, curve->rX, curve->rY, curve->nR);
    c1 = applyOne(c1, curve->gX, curve->gY, curve->nG);
    c2 = applyOne(c2, curve->bX, curve->bY, curve->nB);
    return true;
}

}} // namespace art::engine
