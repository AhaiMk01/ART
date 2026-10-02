/* -*- C++ -*-
 *
 *  This file is part of RawTherapee.
 */
#pragma once

#include "adjuster.h"
#include "edit.h"
#include "guiutils.h"
#include "toolpanel.h"
#include <gtkmm.h>

class Gradient: public ToolParamBlock,
                public AdjusterListener,
                public FoldableToolPanel,
                public EditSubscriber {

private:
    int lastObject;

protected:
    Gtk::HBox *editHBox;
    Gtk::ToggleButton *edit;
    Adjuster *degree;
    Adjuster *feather;
    Adjuster *strength;
    Adjuster *centerX;
    Adjuster *centerY;
    double draggedPointOldAngle;
    double draggedPointAdjusterAngle;
    double draggedFeatherOffset;
    art::engine::Coord draggedCenter;
    sigc::connection editConn;

    art::engine::procparams::GradientParams initial_params;

    void editToggled();

public:
    Gradient();
    ~Gradient() override;

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void enabledChanged() override;
    void trimValues(art::engine::procparams::ProcParams *pp) override;
    void updateGeometry(const int centerX, const int centerY,
                        const double feather, const double degree,
                        const int fullWidth = -1, const int fullHeight = -1);

    void setEditProvider(EditDataProvider *provider) override;

    // EditSubscriber interface
    CursorShape getCursor(int objectID) override;
    bool mouseOver(int modifierKey) override;
    bool button1Pressed(int modifierKey) override;
    bool button1Released() override;
    bool drag1(int modifierKey) override;
    void switchOffEditMode() override;

    void toolReset(bool to_initial) override;
};
