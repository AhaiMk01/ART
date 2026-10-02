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
#include "guiutils.h"
#include "options.h"
#include "toolpanel.h"
#include <gtkmm.h>

class Denoise: public ToolParamBlock,
               public AdjusterListener,
               public FoldableToolPanel,
               public art::engine::AutoChromaListener {
public:
    Denoise();
    ~Denoise() override;

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void adjusterChanged(Adjuster *a, double newval) override;
    void adjusterAutoToggled(Adjuster *a, bool newval) override;
    void enabledChanged() override;

    void chromaChanged(double autchroma, double autred,
                       double autblue) override;
    bool chromaComputed(double chroma, double red, double blue);

    void noiseChanged(double nresid, double highresid) override {}
    void noiseTilePrev(int tileX, int tileY, int prevX, int prevY, int sizeT,
                       int sizeP) override
    {
    }

    void trimValues(art::engine::procparams::ProcParams *pp) override;

    void toolReset(bool to_initial) override;

private:
    void aggressiveChanged();
    void chrominanceMethodChanged();
    void smoothingEnabledToggled();
    void colorSpaceChanged();

    art::engine::ProcEvent EvGuidedChromaRadius;
    art::engine::ProcEvent EvChrominanceAutoFactor;
    art::engine::ProcEvent EvLuminanceDetailThreshold;
    art::engine::ProcEvent EvColorSpace;
    art::engine::ProcEvent EvNlDetail;
    art::engine::ProcEvent EvNlStrength;

    MyComboBoxText *aggressive;
    MyComboBoxText *colorSpace;
    Adjuster *gamma;
    Adjuster *luminance;
    Adjuster *luminanceDetail;
    Adjuster *luminanceDetailThreshold;
    MyComboBoxText *chrominanceMethod;
    Adjuster *chrominanceAutoFactor;
    Adjuster *chrominance;
    Adjuster *chrominanceRedGreen;
    Adjuster *chrominanceBlueYellow;
    MyExpander *smoothingEnabled;
    Adjuster *guidedChromaRadius;
    Adjuster *nlDetail;
    Adjuster *nlStrength;

    IdleRegister idle_register;

    art::engine::procparams::DenoiseParams initial_params;
};
