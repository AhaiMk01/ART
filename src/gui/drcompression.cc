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
#include "drcompression.h"
#include "eventmapper.h"
#include <cmath>
#include <iomanip>

namespace art { namespace gui {
using namespace utils;


using namespace art::engine;
using namespace art::engine::procparams;

DynamicRangeCompression::DynamicRangeCompression()
    : FoldableToolPanel(this, "drcompression", M("TP_DRCOMPRESSION_LABEL"), false, true,
                        true)
{
    auto m = ProcEventMapper::getInstance();
    EvSatControl =
        m->newEvent(art::engine::HDR, "HISTORY_MSG_DRCOMPRESSION_SATCONTROL");
    EvToolReset.set_action(art::engine::HDR);

    amount =
        Gtk::manage(new Adjuster(M("TP_DRCOMPRESSION_AMOUNT"), 1., 100., 1., 20.));
    threshold = Gtk::manage(
        new Adjuster(M("TP_DRCOMPRESSION_THRESHOLD"), -100., 300., 1., 30.0));
    satcontrol =
        Gtk::manage(new Gtk::CheckButton(M("TP_DRCOMPRESSION_SATCONTROL")));
    satcontrol->signal_toggled().connect(
        sigc::mem_fun(*this, &DynamicRangeCompression::satcontrolChanged), true);

    amount->setAdjusterListener(this);
    threshold->setAdjusterListener(this);

    threshold->setLogScale(10, 0);

    amount->show();
    threshold->show();

    pack_start(*amount);
    pack_start(*threshold);
    pack_start(*satcontrol);
}

void DynamicRangeCompression::read(const ProcParams *pp)
{
    disableListener();

    setEnabled(pp->drcompression.enabled);
    threshold->setValue(pp->drcompression.threshold);
    amount->setValue(pp->drcompression.amount);
    satcontrol->set_active(pp->drcompression.satcontrol);

    enableListener();
}

void DynamicRangeCompression::write(ProcParams *pp)
{
    pp->drcompression.threshold = threshold->getValue();
    pp->drcompression.amount = amount->getValue();
    pp->drcompression.enabled = getEnabled();
    pp->drcompression.satcontrol = satcontrol->get_active();
}

void DynamicRangeCompression::setDefaults(const ProcParams *defParams)
{
    threshold->setDefault(defParams->drcompression.threshold);
    amount->setDefault(defParams->drcompression.amount);

    initial_params = defParams->drcompression;
}

void DynamicRangeCompression::adjusterChanged(Adjuster *a, double newval)
{
    if (listener && getEnabled()) {
        if (a == threshold) {
            listener->panelChanged(EvDRCompressionThreshold, a->getTextValue());
        } else if (a == amount) {
            listener->panelChanged(EvDRCompressionAmount, a->getTextValue());
        }
    }
}

void DynamicRangeCompression::adjusterAutoToggled(Adjuster *a, bool newval) {}

void DynamicRangeCompression::enabledChanged()
{
    if (listener) {
        if (get_inconsistent()) {
            listener->panelChanged(EvDRCompressionEnabled, M("GENERAL_UNCHANGED"));
        } else if (getEnabled()) {
            listener->panelChanged(EvDRCompressionEnabled, M("GENERAL_ENABLED"));
        } else {
            listener->panelChanged(EvDRCompressionEnabled, M("GENERAL_DISABLED"));
        }
    }
}

void DynamicRangeCompression::satcontrolChanged()
{
    if (listener && getEnabled()) {
        listener->panelChanged(EvSatControl, satcontrol->get_active()
                                                 ? M("GENERAL_ENABLED")
                                                 : M("GENERAL_DISABLED"));
    }
}

void DynamicRangeCompression::toolReset(bool to_initial)
{
    ProcParams pp;
    if (to_initial) {
        pp.drcompression = initial_params;
    }
    pp.drcompression.enabled = getEnabled();
    read(&pp);
}


void DynamicRangeCompression::registerShortcuts(ToolShortcutsManager *mgr)
{
    mgr->addShortcut("tool.drcompression.detail", this, threshold);
    mgr->addShortcut("tool.drcompression.amount", this, amount);
}


} } // namespace art::gui
