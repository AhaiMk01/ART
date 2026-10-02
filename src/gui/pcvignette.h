/* -*- C++ -*-
 *
 *  This file is part of RawTherapee.
 */
#pragma once

#include "adjuster.h"
#include "edit.h"
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class PCVignette: public ToolParamBlock,
                  public AdjusterListener,
                  public FoldableToolPanel,
                  public EditSubscriber,
                  public PParamsChangeListener {

protected:
    Adjuster *strength;
    Adjuster *feather;
    Adjuster *roundness;
    Adjuster *centerX;
    Adjuster *centerY;
    art::engine::ProcEvent EvCenter;

    Gtk::ToggleButton *edit;
    art::engine::Coord draggedCenter;
    sigc::connection editConn;
    int lastObject;

    art::engine::procparams::PCVignetteParams initial_params;
    art::engine::procparams::CropParams crop_;

    void editToggled();
    void updateGeometry(const int centerX, const int centerY);
    void getDimensions(int &x, int &y, int &w, int &h);

public:
    PCVignette();
    ~PCVignette();

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void enabledChanged() override;
    void trimValues(art::engine::procparams::ProcParams *pp) override;
    void toolReset(bool to_initial) override;

    void setEditProvider(EditDataProvider *provider) override;

    // EditSubscriber interface
    CursorShape getCursor(int objectID) override;
    bool mouseOver(int modifierKey) override;
    bool button1Pressed(int modifierKey) override;
    bool button1Released() override;
    bool drag1(int modifierKey) override;
    void switchOffEditMode() override;

    PParamsChangeListener *getPParamsChangeListener() override { return this; }
    void procParamsChanged(const art::engine::procparams::ProcParams *params,
                           const art::engine::ProcEvent &ev,
                           const Glib::ustring &descr,
                           const ParamsEdited *paramsEdited = nullptr) override;
    void clearParamChanges() override {}
};


} } // namespace art::gui
