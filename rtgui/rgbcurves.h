/* -*- C++ -*-
 *
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
 *
 *  RawTherapee is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  RawTherapee is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with RawTherapee.  If not, see <http://www.gnu.org/licenses/>.
 */
#pragma once

#include "adjuster.h"
#include "colorprovider.h"
#include "curveeditor.h"
#include "curveeditorgroup.h"
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class RGBCurves: public ToolParamBlock,
                 public FoldableToolPanel,
                 public CurveListener,
                 public ColorProvider,
                 public CurveBackgroundProvider {
private:
    CurveEditorGroup *curveEditorG;
    DiagonalCurveEditor *Rshape;
    DiagonalCurveEditor *Gshape;
    DiagonalCurveEditor *Bshape;

    art::engine::procparams::RGBCurvesParams initial_params;

public:
    RGBCurves();
    ~RGBCurves() override;

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void setEditProvider(EditDataProvider *provider) override;
    void autoOpenCurve() override;

    void curveChanged(CurveEditor *ce) override;
    void updateCurveBackgroundHistogram(
        const art::engine::LUTu &histToneCurve, const art::engine::LUTu &histLCurve,
        const art::engine::LUTu &histCCurve, const art::engine::LUTu &histLCAM, const art::engine::LUTu &histCCAM,
        const art::engine::LUTu &histRed, const art::engine::LUTu &histGreen, const art::engine::LUTu &histBlue,
        const art::engine::LUTu &histLuma, const art::engine::LUTu &histLRETI);
    void enabledChanged() override;

    void setDefaults(const art::engine::procparams::ProcParams *def) override;
    void toolReset(bool to_initial) override;

    void renderCurveBackground(int caller_id,
                               Glib::RefPtr<Gtk::StyleContext> style,
                               Cairo::RefPtr<Cairo::Context> cr, double x,
                               double y, double w, double h) override;
};


} } // namespace art::gui
