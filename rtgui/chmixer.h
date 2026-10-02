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
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class ChMixer: public ToolParamBlock,
               public AdjusterListener,
               public FoldableToolPanel {
public:
    ChMixer();

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void trimValues(art::engine::procparams::ProcParams *pp) override;
    void enabledChanged() override;

    void toolReset(bool to_initial) override;

private:
    void modeChanged();

    MyComboBoxText *mode;
    Gtk::VBox *matrix_box;
    Gtk::VBox *primaries_box;
    Adjuster *red[3];
    Adjuster *green[3];
    Adjuster *blue[3];
    Gtk::Image *imgIcon[9];
    Adjuster *hue_tweak[3];
    Adjuster *sat_tweak[3];

    art::engine::procparams::ChannelMixerParams initial_params;

    art::engine::ProcEvent EvMode;
    art::engine::ProcEvent EvRedPrimary;
    art::engine::ProcEvent EvGreenPrimary;
    art::engine::ProcEvent EvBluePrimary;
};


} } // namespace art::gui
