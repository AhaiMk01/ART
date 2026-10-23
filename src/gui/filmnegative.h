/* -*- C++ -*-
 *  This file is part of ART.
 *
 *  Copyright (c) 2019 Alberto Romei <aldrop8@gmail.com>
 *  Copyright (c) 2019-2026 Alberto Griggio <alberto.griggio@gmail.com>
 *
 *  ART is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  ART is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with ART.  If not, see <https://www.gnu.org/licenses/>.
 */
#pragma once

#include <array>

#include <gtkmm.h>

#include "adjuster.h"
#include "edit.h"
#include "guiutils.h"
#include "toolpanel.h"

#include "../engine/colortemp.h"

namespace art { namespace gui {


namespace {
using RGB = art::engine::procparams::FilmNegativeParams::RGB;
using ColorSpace = art::engine::procparams::FilmNegativeParams::ColorSpace;
using BackCompat = art::engine::procparams::FilmNegativeParams::BackCompat;
using Method = art::engine::procparams::FilmNegativeParams::Method;
using FilmType = art::engine::procparams::FilmNegativeParams::FilmType;
} // namespace
class FilmNegProvider {
public:
    virtual ~FilmNegProvider() = default;

    virtual bool getFilmNegativeSpot(art::engine::Coord spot, int spotSize,
                                     RGB &refInput, RGB &refOutput) = 0;
    virtual bool getFilmNegativeBaseGains(art::engine::Coord spot, int spotSize,
                                          std::array<double, 3> &gains) = 0;
    virtual Glib::ustring getFilmNegativeSourceId() const
    {
        return "Unknown";
    }
};

class FilmNegative final: public ToolParamBlock,
                          public AdjusterListener,
                          public FoldableToolPanel,
                          public EditSubscriber,
                          public art::engine::FilmNegListener {
public:
    FilmNegative();
    ~FilmNegative() override;

    void read(const art::engine::procparams::ProcParams *pp) override;
    void write(art::engine::procparams::ProcParams *pp) override;
    // Rebinds MatrixBasis when the colour management profiles
    // changed since read(). Call after every panel has written pp, since the
    // ICM panel may write after this one.
    void syncBindings(art::engine::procparams::ProcParams *pp);
    void
    setDefaults(const art::engine::procparams::ProcParams *defParams) override;
    void toolReset(bool to_initial) override;

    void adjusterChanged(Adjuster *a, double newval) override;
    void registerShortcuts(ToolShortcutsManager *mgr) override;
    void enabledChanged() override;
    void colorSpaceChanged();
    void methodChanged();
    void filmTypeChanged();
    void matrixPresetChanged();
    void matrixEdited();
    void calibrationNoteEdited();
    void applyMatrixPresetDisplay();
    void namicolorFitBaseChanged();
    void updateVisibility();
    void filmRefValuesChanged(const RGB &refInput,
                              const RGB &refOutput) override;

    void setFilmNegProvider(FilmNegProvider *provider);

    void setEditProvider(EditDataProvider *provider) override;

    // EditSubscriber interface
    CursorShape getCursor(int objectID) override;
    bool mouseOver(int modifierKey) override;
    bool button1Pressed(int modifierKey) override;
    bool button1Released() override;
    bool button3Pressed(int modifierKey) override;
    void switchOffEditMode() override;

private:
    void editToggled();
    void refSpotToggled();
    void filmBaseToggled();

    void readOutputSliders(RGB &refOutput);
    void writeOutputSliders(const RGB &refOutput);

    // ColorTemp value corresponding to neutral RGB multipliers (1,1,1). Should
    // be around 6500K.
    const art::engine::ColorTemp NEUTRAL_TEMP;

    const art::engine::ProcEvent evFilmNegativeExponents;
    const art::engine::ProcEvent evFilmNegativeEnabled;
    const art::engine::ProcEvent evFilmNegativeRefSpot;
    const art::engine::ProcEvent evFilmNegativeBalance;
    const art::engine::ProcEvent evFilmNegativeColorSpace;
    const art::engine::ProcEvent evFilmNegativeMethod;
    const art::engine::ProcEvent evFilmNegativeDensity;
    const art::engine::ProcEvent evFilmNegativeFilmBase;
    const art::engine::ProcEvent evFilmNegativeCineon;
    const art::engine::ProcEvent evFilmNegativeMatrix;
    const art::engine::ProcEvent evFilmNegativeFlare;
    std::vector<art::engine::Coord> refSpotCoords;

    RGB refInputValues;
    bool paramsUpgraded;

    /**
     * Luminance reference: these input RGB values must produce this output
     * luminance. This allows keeping constant luminance when picking several
     * white balance  spot samples in sequence; values are set on the initial
     * white balance spot sampling, and reset every time params are read, or the
     * output sliders are changed.
     */
    struct {
        RGB input;
        float lum;
    } refLuminance;

    FilmNegProvider *fnp;
    MyComboBoxText *const method;
    Gtk::Grid *methodGrid;
    MyComboBoxText *const filmType;
    Gtk::Grid *filmTypeGrid;

    MyComboBoxText *const colorSpace;

    Adjuster *const greenExp;
    Adjuster *const redRatio;
    Adjuster *const blueRatio;

    Gtk::ToggleButton *const spotButton;
    MyComboBoxText *spotsize;

    Gtk::Label *const refInputLabel;
    Gtk::ToggleButton *const refSpotButton;
    MyComboBoxText *refspotsize;
    Gtk::ToggleButton *const filmBaseButton;
    MyComboBoxText *filmBaseSize;

    Adjuster *const outputLevel;
    Adjuster *const greenBalance;
    Adjuster *const blueBalance;

    Gtk::Grid *csGrid;

    Adjuster *const inputGamma;
    Adjuster *const densityGamma;
    Adjuster *const densityDmax;
    std::array<Adjuster *, 12> namicolorAdjusters;
    MyComboBoxText *namicolorFitBase;
    Adjuster *const channelGammaR;
    Adjuster *const channelGammaG;
    Adjuster *const channelGammaB;
    Adjuster *const rgbGainR;
    Adjuster *const rgbGainG;
    Adjuster *const rgbGainB;
    Adjuster *const outputBlackOffset;
    Adjuster *const flareR;
    Adjuster *const flareG;
    Adjuster *const flareB;
    Gtk::Label *const vignettingWarning;
    bool vignettingActive;

    Adjuster *const cineonReferenceWhite;
    MyComboBoxText *const matrixPreset;
    Gtk::Grid *matrixPresetGrid;
    Gtk::Label *const matrixCustomNote;
    Gtk::Entry *const matrixCoeffs;
    Gtk::Entry *const calibrationNote;
    // inputProfile + "\n" + workingProfile as of read() or the last rebind
    Glib::ustring boundProfiles;

    Gtk::Widget *spotPickerBox;
    Gtk::Widget *refSpotPickerBox;
    Gtk::Widget *filmBasePickerBox;
    Gtk::Separator *sep;

    IdleRegister idle_register;

    art::engine::procparams::FilmNegativeParams initial_params;
    std::array<double, 9> storedMatrix;
    Glib::ustring matrixBasis;
    bool captureMatrixBasis;
    bool suppressMatrixEdit;
};


} } // namespace art::gui
