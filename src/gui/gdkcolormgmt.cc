/** -*- C++ -*-
 *
 *  This file is part of ART.
 *
 *  Copyright (c) 2025-2026 Alberto Griggio <alberto.griggio@gmail.com>
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

#include "gdkcolormgmt.h"
#include "options.h"
#ifdef __APPLE__
#include <ApplicationServices/ApplicationServices.h>
#endif
#include <stdio.h>

#include <gdk/gdkconfig.h>
#ifdef GDK_WINDOWING_QUARTZ
#include <gdk/gdkquartz.h>
#endif

namespace art { namespace gui {




void gdk_set_monitor_profile(GdkWindow *window,
                             art::engine::Settings::StdMonitorProfile prof)
{
#if defined __APPLE__ && defined GDK_QUARTZ_WINDOW_SUPPORTS_COLORSPACE
    auto colorspace = kCGColorSpaceSRGB;
    switch (prof) {
    case art::engine::Settings::StdMonitorProfile::DISPLAY_P3:
        colorspace = kCGColorSpaceDisplayP3;
        break;
    case art::engine::Settings::StdMonitorProfile::ADOBE_RGB:
        colorspace = kCGColorSpaceAdobeRGB1998;
        break;
    default:
        colorspace = kCGColorSpaceSRGB;
    }
    const char *csp = g_getenv("ART_DEBUG_GDK_QUARTZ_COLORSPACE");
    if (csp) {
        colorspace =
            CFStringCreateWithCString(NULL, csp, kCFStringEncodingUTF8);
    }
    if (options.rtSettings.verbose > 1) {
        fprintf(stderr, "gdk_set_monitor_profile: %s\n",
                CFStringGetCStringPtr(colorspace, kCFStringEncodingUTF8));
    }
    g_object_set_data(G_OBJECT(window), "gdk-quartz-colorspace",
                      (gpointer)colorspace);
#endif
}

 // namespace art


} } // namespace art::gui
