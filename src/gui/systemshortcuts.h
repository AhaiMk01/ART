/** -*- C++ -*-
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

/**
 * Shortcuts that the operating system takes before they reach ART. Only
 * macOS can tell: it lists its enabled "symbolic hot keys" (Mission Control,
 * Spotlight, screenshots, switching spaces and input sources, ...), as set in
 * System Settings > Keyboard > Keyboard Shortcuts. On the other platforms the
 * list is empty. It is a hint for the shortcuts editor: some shortcuts are
 * not in the list (Cmd+Tab, the menu shortcuts of other applications).
 */

#include "shortcuttable.h"

#include <functional>
#include <vector>

namespace art { namespace gui {

/// One system shortcut, as macOS describes it: a virtual key code and
/// Carbon modifier flags (cmdKey 0x100, shiftKey 0x200, optionKey 0x800,
/// controlKey 0x1000; Fn, 0x20000, only counts on keys that type no character; other bits are ignored)
struct SystemHotKey {
    int keycode;
    unsigned carbon_mods;
};

/// The enabled system shortcuts (empty except on macOS)
std::vector<SystemHotKey> enabledSystemHotKeys();

/// Whether `key` is one of `list`. `keyval_of` gives the (lower case) GDK
/// keyval that a virtual key code types without modifiers, 0 if none.
bool matchesSystemHotKey(const ShortcutKey &key, const ModifierMasks &masks,
                         const std::vector<SystemHotKey> &list,
                         const std::function<guint(int)> &keyval_of);

/// Whether `key` is one of the standard keys of macOS that are not in that
/// list because the application menu or the window server handles them:
/// Cmd+, (Preferences), Cmd+H and Cmd+Alt+H (hide), Cmd+M (minimise), Cmd+Tab,
/// Cmd+` and so on. Cmd+Q is not there: it is the quit key of ART as well.
/// Pure matching, whatever the platform.
bool isReservedByMacOS(const ShortcutKey &key, const ModifierMasks &masks);

/// Whether the system takes `key` (always false except on macOS)
bool isSystemShortcut(const ShortcutKey &key, const ModifierMasks &masks);

} } // namespace art::gui
