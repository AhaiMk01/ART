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


class LabCurve: public ToolParamBlock,
                public AdjusterListener,
                public FoldableToolPanel,
                public CurveListener,
                public ColorProvider {

protected:
    CurveEditorGroup *curveEditorG;
    Adjuster *brightness;
    Adjuster *contrast;
    Adjuster *chromaticity;
    DiagonalCurveEditor *lshape;
    DiagonalCurveEditor *ashape;
    DiagonalCurveEditor *bshape;

    art::engine::procparams::LabCurveParams initial_params;

public:
    LabCurve();
    ~LabCurve() override;

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void autoOpenCurve() override;
    void setEditProvider(EditDataProvider *provider) override;
    void trimValues(art::engine::procparams::ProcParams *pp) override;

    void curveChanged(CurveEditor *ce) override;
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;

    void updateCurveBackgroundHistogram(
        const art::engine::LUTu &histToneCurve, const art::engine::LUTu &histLCurve,
        const art::engine::LUTu &histCCurve, const art::engine::LUTu &histLCAM, const art::engine::LUTu &histCCAM,
        const art::engine::LUTu &histRed, const art::engine::LUTu &histGreen, const art::engine::LUTu &histBlue,
        const art::engine::LUTu &histLuma, const art::engine::LUTu &histLRETI);

    void enabledChanged() override;
    void toolReset(bool to_initial) override;
    void registerShortcuts(ToolShortcutManager *mgr) override;
};


} } // namespace art::gui
