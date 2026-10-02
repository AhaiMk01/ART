/*  -*- C++ -*-
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
#include "../engine/rtengine.h"
#include "mydiagonalcurve.h"
#include "myflatcurve.h"
#include "paramsedited.h"
#include <vector>

namespace art { namespace gui {
using namespace utils;


class Clipboard {
private:
    bool _hasIPTC;
    art::engine::procparams::IPTCPairs iptc;
    std::unique_ptr<art::engine::procparams::ProcParams> pparams;
    ParamsEdited pedited;
    bool has_pparams_;
    bool has_pedited_;
    DiagonalCurveType hasDiagonalCurveDataType;
    FlatCurveType hasFlatCurveDataType;
    std::vector<double> diagonalCurve;
    std::vector<double> flatCurve;
    art::engine::procparams::AreaMask areaMask;
    art::engine::procparams::DrawnMask drawnMask;
    art::engine::procparams::Mask mask;

public:
    void setIPTC(const art::engine::procparams::IPTCPairs &iptcc)
    {
        iptc = iptcc;
        _hasIPTC = true;
    }

    const art::engine::procparams::IPTCPairs &getIPTC() { return iptc; }

    bool hasIPTC() { return _hasIPTC; }

    void setProcParams(const art::engine::procparams::ProcParams &pp)
    {
        if (!pparams) {
            pparams.reset(new art::engine::procparams::ProcParams());
        }
        *pparams = pp;
        has_pparams_ = true;
    }

    const art::engine::procparams::ProcParams &getProcParams()
    {
        if (!pparams) {
            pparams.reset(new art::engine::procparams::ProcParams());
        }
        return *pparams;
    }

    void setParamsEdited(const ParamsEdited &pe)
    {
        pedited = pe;
        has_pedited_ = true;
    }

    const ParamsEdited &getParamsEdited() { return pedited; }

    bool hasProcParams() { return has_pparams_; }

    bool hasPEdited() { return has_pedited_; }

    void setDiagonalCurveData(std::vector<double> &p, DiagonalCurveType type)
    {
        diagonalCurve = p;
        hasDiagonalCurveDataType = type;
        return;
    }

    const std::vector<double> &getDiagonalCurveData() { return diagonalCurve; }

    DiagonalCurveType hasDiagonalCurveData()
    {
        return hasDiagonalCurveDataType;
    }

    void setFlatCurveData(std::vector<double> &p, FlatCurveType type)
    {
        flatCurve = p;
        hasFlatCurveDataType = type;
        return;
    }

    const std::vector<double> &getFlatCurveData() { return flatCurve; }

    FlatCurveType hasFlatCurveData() { return hasFlatCurveDataType; }

    bool hasAreaMask() { return !areaMask.isTrivial(); }

    bool hasDrawnMask() { return !drawnMask.isTrivial(); }

    const art::engine::procparams::AreaMask &getAreaMask() { return areaMask; }

    const art::engine::procparams::DrawnMask &getDrawnMask() { return drawnMask; }

    void setAreaMask(const art::engine::procparams::AreaMask &am)
    {
        areaMask = am;
    }

    void setDrawnMask(const art::engine::procparams::DrawnMask &dm)
    {
        drawnMask = dm;
    }

    bool hasMask() const { return mask != art::engine::procparams::Mask(); }

    const art::engine::procparams::Mask &getMask() { return mask; }

    void setMask(const art::engine::procparams::Mask &m) { mask = m; }

    Clipboard();
    ~Clipboard();
};

extern Clipboard clipboard;


} } // namespace art::gui
