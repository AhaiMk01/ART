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
#include "maskspanel.h"
#include "toolpanel.h"
#include <gtkmm.h>

namespace art { namespace gui {


class TextureBoost: public ToolParamBlock,
                    public AdjusterListener,
                    public FoldableToolPanel,
                    public PParamsChangeListener {
public:
    TextureBoost();

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void enabledChanged() override;
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

    art::engine::ProcEvent EvIterations;
    art::engine::ProcEvent EvDetailThreshold;
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

    std::vector<art::engine::procparams::TextureBoostParams::Region> data;

    friend class EPDMasksContentProvider;
    std::unique_ptr<MasksContentProvider> masks_content_provider_;
    MasksPanel *masks_;

    Adjuster *strength;
    Adjuster *detailThreshold;
    Adjuster *iterations;
    Gtk::VBox *box;

    art::engine::procparams::TextureBoostParams initial_params;
};


} } // namespace art::gui
