/* -*- C++ -*-
 *  This file is part of ART.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
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
 *  along with ART.  If not, see <http://www.gnu.org/licenses/>.
 */
#include "rawimagesource.h"
#include "rtengine.h"
#include "stdimagesource.h"

namespace art { namespace engine {

InitialImage *InitialImage::load(const Glib::ustring &fname, bool isRaw,
                                 int *errorCode, ProgressListener *pl)
{

    ImageSource *isrc;

    if (!isRaw) {
        isrc = new StdImageSource();
    } else {
        isrc = new RawImageSource();
    }

    isrc->setProgressListener(pl);

    *errorCode = isrc->load(fname);

    if (*errorCode) {
        delete isrc;
        return nullptr;
    }

    return isrc;
}
}} // namespace art::engine
