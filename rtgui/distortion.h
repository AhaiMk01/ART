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
#include "lensgeomlistener.h"
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class Distortion: public ToolParamBlock,
                  public AdjusterListener,
                  public FoldableToolPanel {
protected:
    Gtk::ToggleButton *autoDistor;
    Adjuster *distor;
    sigc::connection idConn;
    LensGeomListener *rlistener;

    art::engine::ProcEvent EvAuto;
    art::engine::ProcEvent EvAutoLoad;
    bool is_auto_load_event_;

    art::engine::procparams::DistortionParams initial_params;

    IdleRegister idle_register;

public:
    Distortion();
    ~Distortion();

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void trimValues(art::engine::procparams::ProcParams *pp) override;
    void idPressed();
    void setLensGeomListener(LensGeomListener *l) { rlistener = l; }

    void toolReset(bool to_initial) override;
    void enabledChanged() override;
};


} } // namespace art::gui
