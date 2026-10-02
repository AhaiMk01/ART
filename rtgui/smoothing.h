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
#include "maskspanel.h"
#include "toolpanel.h"
#include <gtkmm.h>

class Smoothing: public ToolParamBlock,
                 public AdjusterListener,
                 public FoldableToolPanel,
                 public PParamsChangeListener {
public:
    Smoothing();

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;

    void adjusterChanged(Adjuster *a, double newval) override;
    void enabledChanged() override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override {}

    void setEditProvider(EditDataProvider *provider) override;

    PParamsChangeListener *getPParamsChangeListener() override { return this; }
    void procParamsChanged(const art::engine::procparams::ProcParams *params,
                           const art::engine::ProcEvent &ev,
                           const Glib::ustring &descr,
                           const ParamsEdited *paramsEdited = nullptr) override;
    void clearParamChanges() override {}

    void updateGeometry(int fullWidth, int fullHeight);
    void setAreaDrawListener(AreaDrawListener *l);
    void setDeltaEColorProvider(DeltaEColorProvider *p);

    void toolReset(bool to_initial) override;

    void setExternalMaskPath(const Glib::ustring &dir)
    {
        masks_->setExternalMaskPath(dir);
    }

private:
    void regionGet(int idx);
    void regionShow(int idx);
    void channelChanged();
    void modeChanged();

    art::engine::ProcEvent EvEnabled;
    art::engine::ProcEvent EvChannel;
    art::engine::ProcEvent EvRadius;
    art::engine::ProcEvent EvEpsilon;
    art::engine::ProcEvent EvIterations;
    art::engine::ProcEvent EvMode;
    art::engine::ProcEvent EvSigma;
    art::engine::ProcEvent EvFalloff;
    art::engine::ProcEvent EvNLStrength;
    art::engine::ProcEvent EvNLDetail;
    art::engine::ProcEvent EvNumBlades;
    art::engine::ProcEvent EvAngle;
    art::engine::ProcEvent EvCurvature;
    art::engine::ProcEvent EvOffset;
    art::engine::ProcEvent EvNoiseStrength;
    art::engine::ProcEvent EvNoiseCoarseness;
    art::engine::ProcEvent EvHalationSize;
    art::engine::ProcEvent EvHalationColor;
    art::engine::ProcEvent EvWavStrength;
    art::engine::ProcEvent EvWavLevels;
    art::engine::ProcEvent EvWavGamma;

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

    std::vector<art::engine::procparams::SmoothingParams::Region> data;

    friend class SmoothingMasksContentProvider;
    std::unique_ptr<MasksContentProvider> masks_content_provider_;
    MasksPanel *masks_;

    MyComboBoxText *channel;
    MyComboBoxText *mode;
    Adjuster *radius;
    Adjuster *epsilon;
    Adjuster *iterations;
    Adjuster *sigma;
    Adjuster *falloff;
    Adjuster *nlstrength;
    Adjuster *nldetail;
    Adjuster *numblades;
    Adjuster *angle;
    Adjuster *curvature;
    Adjuster *offset;
    Adjuster *noise_strength;
    Adjuster *noise_coarseness;
    Adjuster *halation_size;
    Adjuster *halation_color;
    Adjuster *wav_strength;
    Adjuster *wav_levels;
    Adjuster *wav_gamma;
    Gtk::VBox *box;
    Gtk::HBox *chan_box;
    Gtk::VBox *guided_box;
    Gtk::VBox *gaussian_box;
    Gtk::VBox *nl_box;
    Gtk::VBox *lens_motion_box;
    Gtk::VBox *noise_box;
    Gtk::VBox *halation_box;
    Gtk::VBox *wavelets_box;

    art::engine::procparams::SmoothingParams initial_params;
};
