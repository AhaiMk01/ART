/** -*- C++ -*-
 *
 *  This file is part of RawTherapee.
 *
 *  Copyright (c) 2018 Alberto Griggio <alberto.griggio@gmail.com>
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
#include "clutparamspanel.h"
#include "colorprovider.h"
#include "colorwheel.h"
#include "maskspanel.h"
#include "thresholdadjuster.h"
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class ColorCorrection: public ToolParamBlock,
                       public AdjusterListener,
                       public FoldableToolPanel,
                       public PParamsChangeListener,
                       public ThresholdAdjusterListener,
                       public ColorProvider {
public:
    ColorCorrection();

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;

    void adjusterChanged(Adjuster *a, double newval) override;
    void enabledChanged() override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override {}

    void setEditProvider(EditDataProvider *provider) override;
    void setListener(ToolPanelListener *tpl) override;

    PParamsChangeListener *getPParamsChangeListener() override { return this; }
    void procParamsChanged(const art::engine::procparams::ProcParams *params,
                           const art::engine::ProcEvent &ev,
                           const Glib::ustring &descr,
                           const ParamsEdited *paramsEdited = nullptr) override;
    void clearParamChanges() override {}

    void updateGeometry(int fullWidth, int fullHeight);
    void setAreaDrawListener(AreaDrawListener *l);
    void setDeltaEColorProvider(DeltaEColorProvider *p);

    void adjusterChanged(ThresholdAdjuster *a, double newBottom,
                         double newTop) override;
    void adjusterChanged(ThresholdAdjuster *a, double newBottomLeft,
                         double newTopLeft, double newBottomRight,
                         double newTopRight) override
    {
    }
    void adjusterChanged(ThresholdAdjuster *a, int newBottom,
                         int newTop) override
    {
    }
    void adjusterChanged(ThresholdAdjuster *a, int newBottomLeft,
                         int newTopLeft, int newBottomRight,
                         int newTopRight) override
    {
    }
    void adjusterChanged2(ThresholdAdjuster *a, int newBottomL, int newTopL,
                          int newBottomR, int newTopR) override
    {
    }

    void colorForValue(double valX, double valY,
                       enum ColorCaller::ElemType elemType, int callerId,
                       ColorCaller *caller) override;

    void toolReset(bool to_initial) override;

    void drawCurve(bool rgb, Cairo::RefPtr<Cairo::Context> cr,
                   Glib::RefPtr<Gtk::StyleContext> style, int W, int H);

    void setExternalMaskPath(const Glib::ustring &dir)
    {
        masks_->setExternalMaskPath(dir);
    }

private:
    void regionGet(int idx);
    void regionShow(int idx);
    void modeChanged();
    void syncSlidersToggled();
    void wheelChanged();
    void hslWheelChanged(int c);
    void lutChanged();
    void lutParamsChanged();

    art::engine::ProcEvent EvEnabled;
    art::engine::ProcEvent EvColorWheel;
    art::engine::ProcEvent EvInSaturation;
    art::engine::ProcEvent EvOutSaturation;
    art::engine::ProcEvent EvLightness;
    art::engine::ProcEvent EvSlope;
    art::engine::ProcEvent EvOffset;
    art::engine::ProcEvent EvPower;
    art::engine::ProcEvent EvPivot;
    art::engine::ProcEvent EvMode;
    art::engine::ProcEvent EvRgbLuminance;
    art::engine::ProcEvent EvHueShift;
    art::engine::ProcEvent EvCompression;
    art::engine::ProcEvent EvLUT;
    art::engine::ProcEvent EvLUTParams;
    art::engine::ProcEvent EvHSLGamma;

    art::engine::ProcEvent EvList;
    art::engine::ProcEvent EvParametricMask;
    art::engine::ProcEvent EvHueMask;
    art::engine::ProcEvent EvChromaticityMask;
    art::engine::ProcEvent EvLightnessMask;
    art::engine::ProcEvent EvMaskBlur;
    art::engine::ProcEvent EvShowMask;
    art::engine::ProcEvent EvAreaMask;
    art::engine::ProcEvent EvDeltaEMask;
    art::engine::ProcEvent EvContrastThresholdMask;
    art::engine::ProcEvent EvDrawnMask;
    art::engine::ProcEvent EvMaskPostprocess;
    art::engine::ProcEvent EvLinkedMask;
    art::engine::ProcEvent EvExternalMask;

    std::vector<art::engine::procparams::ColorCorrectionParams::Region> data;

    friend class ColorCorrectionMasksContentProvider;
    std::unique_ptr<MasksContentProvider> masks_content_provider_;
    MasksPanel *masks_;

    Gtk::VBox *box;
    MyComboBoxText *mode;

    Gtk::VBox *box_combined;
    Gtk::VBox *box_rgb;
    Gtk::VBox *box_hsl;
    Gtk::VBox *box_lut;

    ColorWheel *wheel;
    Adjuster *inSaturation;
    Adjuster *outSaturation;
    Adjuster *hueshift;
    Gtk::DrawingArea *hueshift_bar;
    Gtk::Frame *hueframe;
    Gtk::Frame *satframe;
    MyFileChooserButton *lut_filename;
    CLUTParamsPanel *lut_params;
    Gtk::HBox *lut_filename_box;

    Adjuster *slope;
    Adjuster *offset;
    Adjuster *power;
    Adjuster *pivot;
    Adjuster *compression;

    Adjuster *slope_rgb[3];
    Adjuster *offset_rgb[3];
    Adjuster *power_rgb[3];
    Adjuster *pivot_rgb[3];
    Adjuster *compression_rgb[3];
    Gtk::CheckButton *rgbluminance;

    Gtk::CheckButton *sync_rgb_sliders;

    Adjuster *lfactor[3];
    HueSatColorWheel *huesat[3];
    Adjuster *hsl_gamma;

    Gtk::DrawingArea *curve_lum;
    Gtk::DrawingArea *curve_rgb;

    art::engine::procparams::ColorCorrectionParams initial_params;
};


} } // namespace art::gui
