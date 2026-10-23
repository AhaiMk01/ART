/* -*- C++ -*-
 *
 *  This file is part of ART.
 *
 *  Copyright (c) 2019-2026 Alberto Griggio <alberto.griggio@gmail.com>
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

#include "../utils/multilangmgr.h"
#include "clutstore.h"
#include "color.h"
#include "curves.h"
#include "improcfun.h"

#ifdef _OPENMP
#include <omp.h>
#endif

namespace art { namespace engine {

// pipette for the curves of a CTL script: the buffer is filled with the
// position in the curve of each pixel, as computed by ART_fill_pipette. If
// clut is null (tool disabled, or script not usable), the buffer is zeroed.
void ImProcFunctions::fillCTLPipette(CLUTApplication *clut, Imagefloat *img)
{
    const art::utils::EditUniqueID eid =
        pipetteBuffer ? pipetteBuffer->getEditID() : art::utils::EUID_None;
    if (!art::utils::isCTLEditID(eid) ||
        (art::utils::ctlEditValue(eid) & art::utils::EUID_CTL_COLORCORRECTION_TAG) ||
        pipetteBuffer->getDataProvider()
                ->getCurrSubscriber()
                ->getPipetteBufferType() != art::utils::BT_IMAGEFLOAT) {
        return;
    }
    Imagefloat *buf = pipetteBuffer->getImgFloatBuffer();
    if (!buf) {
        return;
    }

    const int W = buf->getWidth();
    const int H = buf->getHeight();
    const int curve_id = art::utils::ctlEditCurve(eid);
    const bool ok = clut && img && clut->hasPipette() &&
                    art::utils::ctlEditBase(eid) == art::utils::ctlEditBase(false);

#ifdef _OPENMP
#pragma omp parallel for if (multiThread)
#endif
    for (int y = 0; y < H; ++y) {
        float *r = buf->r(y);
        float *g = buf->g(y);
        float *b = buf->b(y);
        if (ok) {
            memcpy(r, img->r(y), sizeof(float) * W);
            memcpy(g, img->g(y), sizeof(float) * W);
            memcpy(b, img->b(y), sizeof(float) * W);
#ifdef _OPENMP
            int thread_id = omp_get_thread_num();
#else
            int thread_id = 0;
#endif
            if (clut->fillPipette(thread_id, curve_id, W, r, g, b)) {
                continue;
            }
        }
        // no pipette for this curve, or an error: no marker
        for (int x = 0; x < W; ++x) {
            r[x] = g[x] = b[x] = 0.f;
        }
    }
}

void ImProcFunctions::filmSimulation(Imagefloat *img)
{
    if (!params->filmSimulation.enabled) {
        fillCTLPipette(nullptr, nullptr);
        return;
    }

    img->setMode(Imagefloat::Mode::RGB, multiThread);

#ifdef _OPENMP
    int num_threads = multiThread ? omp_get_max_threads() : 1;
#else
    int num_threads = 1;
#endif
    CLUTApplication clut(
        params->filmSimulation.clutFilename, params->icm.workingProfile,
        float(params->filmSimulation.strength) / 100.f, num_threads);

    if (clut) {
        CLUTApplication::Quality q = CLUTApplication::Quality::HIGHEST;
        switch (cur_pipeline) {
        case Pipeline::THUMBNAIL:
            q = CLUTApplication::Quality::LOW;
            break;
        case Pipeline::NAVIGATOR:
            q = CLUTApplication::Quality::MEDIUM;
            break;
        case Pipeline::PREVIEW:
            if (scale > 1) {
                q = CLUTApplication::Quality::HIGH;
            }
            break;
        default:
            break;
        }
        if (clut.set_param_values(params->filmSimulation.lut_params, q)) {
            fillCTLPipette(&clut, img);
            clut(img);
        } else {
            fillCTLPipette(nullptr, nullptr);
            if (plistener) {
                plistener->error(Glib::ustring::compose(
                    art::utils::M("TP_FILMSIMULATION_LABEL") + " - " +
                        art::utils::M("ERROR_MSG_INVALID_LUT_PARAMS"),
                    params->filmSimulation.clutFilename));
            }
        }
    } else {
        fillCTLPipette(nullptr, nullptr);
        if (plistener) {
            plistener->error(Glib::ustring::compose(
                art::utils::M("TP_FILMSIMULATION_LABEL") + " - " +
                    art::utils::M("ERROR_MSG_FILE_READ"),
                params->filmSimulation.clutFilename.empty()
                    ? "(" + art::utils::M("GENERAL_NONE") + ")"
                    : params->filmSimulation.clutFilename));
        }
    }
}

}} // namespace art::engine
