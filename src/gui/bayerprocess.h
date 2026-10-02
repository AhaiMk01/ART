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
#include "checkbox.h"
#include "guiutils.h"
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class BayerProcess: public ToolParamBlock,
                    public AdjusterListener,
                    public CheckBoxListener,
                    public FoldableToolPanel,
                    public art::engine::FrameCountListener,
                    public art::engine::AutoContrastListener {

protected:
    MyComboBoxText *method;
    Gtk::HBox *borderbox;
    Gtk::HBox *imageNumberBox;
    Adjuster *border;
    MyComboBoxText *imageNumber;
    Adjuster *ccSteps;
    Gtk::VBox *dcbOptions;
    Adjuster *dcbIterations;
    CheckBox *dcbEnhance;
    Gtk::VBox *lmmseOptions;
    Adjuster *lmmseIterations;
    Gtk::Frame *pixelShiftFrame;
    Gtk::VBox *pixelShiftOptions;
    MyComboBoxText *pixelShiftMotionMethod;
    MyComboBoxText *pixelShiftDemosaicMethod;
    CheckBox *pixelShiftShowMotion;
    CheckBox *pixelShiftShowMotionMaskOnly;
    CheckBox *pixelShiftNonGreenCross;
    CheckBox *pixelShiftGreen;
    CheckBox *pixelShiftBlur;
    CheckBox *pixelShiftHoleFill;
    CheckBox *pixelShiftMedian;
    CheckBox *pixelShiftEqualBright;
    CheckBox *pixelShiftEqualBrightChannel;
    Adjuster *pixelShiftSmooth;
    Adjuster *pixelShiftEperIso;
    Adjuster *pixelShiftSigma;
    Gtk::VBox *dualDemosaicOptions;
    Adjuster *dualDemosaicContrast;
    int oldMethod;
    bool lastAutoContrast;
    IdleRegister idle_register;

    art::engine::ProcEvent EvDemosaicBorder;
    art::engine::ProcEvent EvDemosaicAutoContrast;
    art::engine::ProcEvent EvDemosaicContrast;
    art::engine::ProcEvent EvDemosaicPixelshiftDemosaicMethod;

    art::engine::procparams::RAWParams::BayerSensor initial_params;

public:
    BayerProcess();
    ~BayerProcess() override;

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void trimValues(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;

    void methodChanged();
    void imageNumberChanged();
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void checkBoxToggled(CheckBox *c, CheckValue newval) override;
    void pixelShiftMotionMethodChanged();
    void pixelShiftDemosaicMethodChanged();
    void autoContrastChanged(double autoContrast) override;
    void FrameCountChanged(int n, int frameNum) override;

    void toolReset(bool to_initial) override;
};


} } // namespace art::gui
