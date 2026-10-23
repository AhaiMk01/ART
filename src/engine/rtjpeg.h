/* -*- C++ -*-
 *
 *  This file is part of ART.
 *
 *  Copyright (c) 2004-2010 Gabor Horvath <hgabor@rawtherapee.com>
 *  Copyright (c) 2020-2026 Alberto Griggio <alberto.griggio@gmail.com>
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

#pragma once

#include <exception>
#include <stdio.h>

namespace art { namespace engine {
class ProgressListener;
}}

#ifdef __cplusplus
extern "C" {
#endif

#include <jpeglib.h>

struct rt_jpeg_error_mgr {
    struct jpeg_error_mgr pub;
    const char *filename;
    art::engine::ProgressListener *pl;
};

extern GLOBAL(struct jpeg_error_mgr *)
    rt_jpeg_std_error(rt_jpeg_error_mgr *err, const char *filename,
                      art::engine::ProgressListener *pl);

#ifdef __cplusplus
}
#endif

struct rt_jpeg_error: public std::exception {
    const char *what() const throw() { return ""; }
};
