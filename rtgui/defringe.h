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
#include "guiutils.h"
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class Defringe: public ToolParamBlock,
                public AdjusterListener,
                public FoldableToolPanel,
                public CurveListener,
                public ColorProvider {

protected:
    CurveEditorGroup *curveEditorPF;
    FlatCurveEditor *chshape;

    Adjuster *radius;
    Adjuster *threshold;
    bool edges;

    art::engine::procparams::DefringeParams initial_params;

public:
    Defringe();
    ~Defringe() override;
    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void autoOpenCurve() override;
    void curveChanged() override;

    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void enabledChanged() override;
    void colorForValue(double valX, double valY,
                       enum ColorCaller::ElemType elemType, int callerId,
                       ColorCaller *caller) override;

    void toolReset(bool to_initial) override;
};


} } // namespace art::gui
