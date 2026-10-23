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

#include "rtjpeg.h"
#include "../utils/multilangmgr.h"
#include "rtengine.h"
#include <cstdio>
#include <jerror.h>
#include <jpeglib.h>

namespace {

METHODDEF(void)
error_exit(j_common_ptr cinfo)
{
    (*cinfo->err->output_message)(cinfo);
    // jpeg_destroy(cinfo);
    throw rt_jpeg_error();
}

METHODDEF(void)
output_message(j_common_ptr cinfo)
{
    char buffer[JMSG_LENGTH_MAX];

    /* Create the message */
    (*cinfo->err->format_message)(cinfo, buffer);

    rt_jpeg_error_mgr *rterr =
        reinterpret_cast<rt_jpeg_error_mgr *>(cinfo->err);
    const char *filename = rterr->filename;

    if (rterr->pl) {
        rterr->pl->error(
            Glib::ustring::compose(art::utils::M("JPEG_ERROR_MSG"), filename, buffer));
    } else {
        fprintf(stderr, "%s: %s\n", filename, buffer);
    }
}

} // namespace

GLOBAL(struct jpeg_error_mgr *)
rt_jpeg_std_error(rt_jpeg_error_mgr *err, const char *filename,
                  art::engine::ProgressListener *pl)
{
    jpeg_std_error(&(err->pub));
    err->pub.error_exit = error_exit;
    err->pub.output_message = output_message;
    err->filename = filename ? filename : "<UNKNOWN>";
    err->pl = pl;

    return &(err->pub);
}
