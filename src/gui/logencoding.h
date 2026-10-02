/** -*- C++ -*-
 *
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2017 Alberto Griggio <alberto.griggio@gmail.com>
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


class LogEncoding: public ToolParamBlock,
                   public AdjusterListener,
                   public art::engine::AutoLogListener,
                   public FoldableToolPanel {
public:
    LogEncoding();

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;

    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void enabledChanged() override;

    void logEncodingChanged(
        const art::engine::procparams::LogEncodingParams &params) override;
    void autocomputeToggled();

    void toolReset(bool to_initial) override;
    void registerShortcuts(ToolShortcutManager *mgr) override;

private:
    void satcontrolChanged();

    Gtk::ToggleButton *autocompute;
    Adjuster *gain;
    Adjuster *targetGray;
    Adjuster *blackEv;
    Adjuster *whiteEv;
    Adjuster *regularization;
    Gtk::CheckButton *satcontrol;
    Adjuster *highlightCompression;

    art::engine::ProcEvent EvEnabled;
    art::engine::ProcEvent EvAuto;
    art::engine::ProcEvent EvAutoGainOn;
    art::engine::ProcEvent EvAutoGainOff;
    art::engine::ProcEvent EvAutoBatch;
    art::engine::ProcEvent EvGain;
    art::engine::ProcEvent EvGainAuto;
    art::engine::ProcEvent EvTargetGray;
    art::engine::ProcEvent EvBlackEv;
    art::engine::ProcEvent EvWhiteEv;
    art::engine::ProcEvent EvRegularization;
    art::engine::ProcEvent EvSatControl;
    art::engine::ProcEvent EvHLCompression;

    sigc::connection autoconn;

    art::engine::procparams::LogEncodingParams initial_params;
};


} } // namespace art::gui
