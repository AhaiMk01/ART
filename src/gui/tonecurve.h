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
#include "mycurve.h"
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class ToneCurve: public ToolParamBlock,
                 public FoldableToolPanel,
                 public CurveListener,
                 public AdjusterListener,
                 public ColorProvider {
private:
    IdleRegister idle_register;

protected:
    Adjuster *contrast;
    MyComboBoxText *toneCurveMode;
    MyComboBoxText *toneCurveMode2;
    Gtk::ToggleButton *histmatching;
    bool fromHistMatching;

    sigc::connection tcmodeconn, tcmode2conn;
    sigc::connection histmatchconn;
    CurveEditorGroup *curveEditorG;
    CurveEditorGroup *curveEditorG2;
    DiagonalCurveEditor *shape;
    DiagonalCurveEditor *shape2;
    CurveEditorGroup *satcurveG;
    FlatCurveEditor *satcurve;
    DiagonalCurveEditor *satcurve2_;
    Adjuster *perceptualStrength;
    Adjuster *whitePoint;

    Gtk::HBox *mode1_box_;
    Gtk::HBox *mode2_box_;
    MyComboBoxText *mode_;
    Gtk::CheckButton *contrast_legacy_;
    Gtk::HBox *mode_box_;
    Gtk::HBox *contrast_legacy_box_;
    MyComboBoxText *basecurve_;

    art::engine::ProcEvent EvHistMatching;
    art::engine::ProcEvent EvHistMatchingBatch;
    art::engine::ProcEvent EvSatCurve;
    art::engine::ProcEvent EvPerceptualStrength;
    art::engine::ProcEvent EvContrastLegacy;
    art::engine::ProcEvent EvMode;
    art::engine::ProcEvent EvWhitePoint;
    art::engine::ProcEvent EvBaseCurve;

    // used temporarily in eventing
    std::vector<double> nextToneCurve;
    std::vector<double> nextToneCurve2;

    void setHistmatching(bool enabled);
    void showPerceptualStrength();
    void contrastLegacyToggled();
    void modeChanged();
    void baseCurveChanged();
    void showWhitePoint();
    void updateSatCurves(int i);

    art::engine::procparams::ToneCurveParams initial_params;

public:
    ToneCurve();
    ~ToneCurve() override;

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void trimValues(art::engine::procparams::ProcParams *pp) override;
    void autoOpenCurve() override;
    void setEditProvider(EditDataProvider *provider) override;

    float blendPipetteValues(CurveEditor *ce, float chan1, float chan2,
                             float chan3) override;

    void enableAll(bool yes = true);
    void curveChanged(CurveEditor *ce) override;
    void curveMode1Changed();
    bool curveMode1Changed_();
    void curveMode2Changed();
    bool curveMode2Changed_();
    void expandCurve(bool isExpanded);
    bool isCurveExpanded();
    void updateCurveBackgroundHistogram(
        const art::engine::LUTu &histToneCurve, const art::engine::LUTu &histLCurve,
        const art::engine::LUTu &histCCurve, const art::engine::LUTu &histLCAM, const art::engine::LUTu &histCCAM,
        const art::engine::LUTu &histRed, const art::engine::LUTu &histGreen, const art::engine::LUTu &histBlue,
        const art::engine::LUTu &histLuma, const art::engine::LUTu &histLRETI);

    void histmatchingToggled();
    void autoMatchedToneCurveChanged(const std::vector<double> &curve,
                                     const std::vector<double> &curve2);
    void setRaw(bool raw);

    void adjusterChanged(Adjuster *a, double newval) override;

    void toolReset(bool to_initial) override;
    void registerShortcuts(ToolShortcutManager *mgr) override;

    void colorForValue(double valX, double valY,
                       enum ColorCaller::ElemType elemType, int callerId,
                       ColorCaller *caller) override;
};


} } // namespace art::gui
