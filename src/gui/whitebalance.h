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

#include "../engine/procparams.h"
#include "adjuster.h"
#include "guiutils.h"
#include "toolpanel.h"
#include "wbprovider.h"
#include <gtkmm.h>

namespace art { namespace gui {


class SpotWBListener {
public:
    virtual ~SpotWBListener() = default;
    virtual void spotWBRequested(int size) = 0;
};

class WhiteBalance: public ToolParamBlock,
                    public AdjusterListener,
                    public FoldableToolPanel,
                    public art::engine::AutoWBListener {
public:
    WhiteBalance();
    ~WhiteBalance() override;

    static void init();
    static void cleanup();
    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void methodChanged();
    void spotPressed();
    void spotSizeChanged();
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    int getSize();
    void setWBProvider(WBProvider *p) { wbp = p; }
    void setSpotWBListener(SpotWBListener *l) { wblistener = l; }
    void setWB(art::engine::ColorTemp ctemp);
    void WBChanged(art::engine::ColorTemp ctemp) override;

    void trimValues(art::engine::procparams::ProcParams *pp) override;
    void enabledChanged() override;

    void toolReset(bool to_initial) override;
    void registerShortcuts(ToolShortcutManager *mgr) override;

private:
    void fillMethods();
    int getActiveMethod();
    void syncSliders(bool from_mult);
    void updateMethodGui(bool check_temp);

    class MethodColumns: public Gtk::TreeModel::ColumnRecord {
    public:
        Gtk::TreeModelColumn<int> colIcon;
        Gtk::TreeModelColumn<Glib::ustring> colLabel;
        Gtk::TreeModelColumn<int> colPreset;
        MethodColumns()
        {
            add(colIcon);
            add(colLabel);
            add(colPreset);
        }
    };

    static std::vector<std::shared_ptr<RTSurface>> wbPixbufs;
    Glib::RefPtr<Gtk::TreeStore> refTreeModel;
    MethodColumns methodColumns;
    MyComboBox *method;
    MyComboBoxText *spotsize;
    Adjuster *temp;
    Adjuster *green;
    Adjuster *equal;

    std::array<Adjuster *, 3> mult;
    Gtk::VBox *tempBox;
    Gtk::VBox *multBox;

    Gtk::Button *spotbutton;
    int opt;
    WBProvider *wbp;
    SpotWBListener *wblistener;
    sigc::connection methconn;

    IdleRegister idle_register;

    art::engine::procparams::WBParams initial_params;

    art::engine::ProcEvent EvWBMult;
    std::vector<WBPreset> presets;

    Gtk::Box *temp_warning_;
};


} } // namespace art::gui
