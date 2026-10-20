/* -*- C++ -*-
 *
 *  This file is part of ART.
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

#include <glibmm.h>

namespace art { namespace dialogs {

// Apply the same GTK theme, colours and font as the main ART window.
// This is a stripped-down version of RTWindow's theme setup that reads the
// few relevant keys straight from the "options" files, so that ART-dialogs
// does not depend on the engine or on the rest of the GUI.
// Must be called after gtk has been initialised. Never fails: missing files
// just leave the stock dark Adwaita look.
void applyTheme(const char *argv0);

} } // namespace art::dialogs
