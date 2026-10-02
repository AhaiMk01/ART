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

#include "../engine/rtengine.h"
#include "paramsedited.h"
#include <glibmm.h>

namespace art { namespace gui {


class PParamsChangeListener {
public:
    virtual ~PParamsChangeListener() = default;
    virtual void
    procParamsChanged(const art::engine::procparams::ProcParams *params,
                      const art::engine::ProcEvent &ev, const Glib::ustring &descr,
                      const ParamsEdited *paramsEdited = nullptr) = 0;
    virtual void clearParamChanges() = 0;
};

class PParamsSnapshotListener {
public:
    virtual ~PParamsSnapshotListener() = default;
    virtual void
    snapshotsChanged(const std::vector<
                     std::pair<Glib::ustring, art::engine::procparams::ProcParams>>
                         &snapshots) = 0;
};


} } // namespace art::gui
