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

#include "systemshortcuts.h"

#ifdef __APPLE__
#include <Carbon/Carbon.h>
#endif

namespace art { namespace gui {

namespace {

constexpr unsigned CARBON_CMD = 0x100;
constexpr unsigned CARBON_SHIFT = 0x200;
constexpr unsigned CARBON_OPTION = 0x800;
constexpr unsigned CARBON_CONTROL = 0x1000;
constexpr unsigned CARBON_FN = 0x20000;
constexpr unsigned CARBON_ALL =
    CARBON_CMD | CARBON_SHIFT | CARBON_OPTION | CARBON_CONTROL;

} // namespace


#ifdef __APPLE__

std::vector<SystemHotKey> enabledSystemHotKeys()
{
    std::vector<SystemHotKey> res;
    CFArrayRef arr = nullptr;
    if (CopySymbolicHotKeys(&arr) != noErr || !arr) {
        return res;
    }
    const auto number = [](CFDictionaryRef d, CFStringRef k, int &out) {
        CFNumberRef n = static_cast<CFNumberRef>(CFDictionaryGetValue(d, k));
        return n && CFNumberGetValue(n, kCFNumberIntType, &out);
    };
    for (CFIndex i = 0, n = CFArrayGetCount(arr); i < n; ++i) {
        CFDictionaryRef d =
            static_cast<CFDictionaryRef>(CFArrayGetValueAtIndex(arr, i));
        CFBooleanRef on = static_cast<CFBooleanRef>(
            CFDictionaryGetValue(d, CFSTR("kHISymbolicHotKeyEnabled")));
        int code = 0, mods = 0;
        if (on && CFBooleanGetValue(on) &&
            number(d, CFSTR("kHISymbolicHotKeyCode"), code) &&
            number(d, CFSTR("kHISymbolicHotKeyModifiers"), mods)) {
            SystemHotKey k = {code, unsigned(mods)};
            res.push_back(k);
        }
    }
    CFRelease(arr);
    return res;
}

#else

std::vector<SystemHotKey> enabledSystemHotKeys() { return {}; }

#endif


namespace {

unsigned carbonMods(const ShortcutKey &key, const ModifierMasks &masks)
{
    unsigned mods = 0;
    if (key.mods & shortcut_mod::Primary) {
        mods |= masks.primary == masks.os_key ? CARBON_CMD : CARBON_CONTROL;
    }
    if (key.mods & shortcut_mod::Ctrl) {
        mods |= CARBON_CONTROL;
    }
    if (key.mods & shortcut_mod::Alt) {
        mods |= CARBON_OPTION;
    }
    if (key.mods & shortcut_mod::Shift) {
        mods |= CARBON_SHIFT;
    }
    return mods;
}

} // namespace


bool matchesSystemHotKey(const ShortcutKey &key, const ModifierMasks &masks,
                         const std::vector<SystemHotKey> &list,
                         const std::function<guint(int)> &keyval_of)
{
    const unsigned mods = carbonMods(key, masks);
    for (auto &h : list) {
        // Fn is added by the system to the arrows and the like, but on a key
        // that types a character it is a real modifier (Fn+A, Fn+E), which
        // must not shadow the plain key
        if ((h.carbon_mods & CARBON_FN) && gdk_keyval_to_unicode(key.keyval)) {
            continue;
        }
        if ((h.carbon_mods & CARBON_ALL) == mods &&
            keyval_of(h.keycode) == key.keyval) {
            return true;
        }
    }
    return false;
}


bool isReservedByMacOS(const ShortcutKey &key, const ModifierMasks &masks)
{
    struct Reserved {
        guint keyval;
        unsigned mods;
    };
    static const Reserved reserved[] = {
        {GDK_KEY_comma, CARBON_CMD},                    // Preferences
        {GDK_KEY_h, CARBON_CMD},                        // Hide
        {GDK_KEY_h, CARBON_CMD | CARBON_OPTION},        // Hide others
        {GDK_KEY_m, CARBON_CMD},                        // Minimise
        {GDK_KEY_Tab, CARBON_CMD},                      // Switch application
        {GDK_KEY_Tab, CARBON_CMD | CARBON_SHIFT},
        {GDK_KEY_grave, CARBON_CMD},                    // Switch window
        {GDK_KEY_Escape, CARBON_CMD | CARBON_OPTION},   // Force quit
        {GDK_KEY_space, CARBON_CMD},                    // Spotlight
    };
    const unsigned mods = carbonMods(key, masks);
    for (auto &r : reserved) {
        if (r.keyval == key.keyval && r.mods == mods) {
            return true;
        }
    }
    return false;
}


bool isSystemShortcut(const ShortcutKey &key, const ModifierMasks &masks)
{
#ifdef __APPLE__
    if (isReservedByMacOS(key, masks)) {
        return true;
    }
#endif
    const auto list = enabledSystemHotKeys();
    if (list.empty()) {
        return false;
    }
    // on macOS GDK's hardware key codes are the virtual key codes
    GdkKeymap *km = gdk_keymap_get_default();
    return km && matchesSystemHotKey(
                     key, masks, list, [km](int code) -> guint {
                         GdkKeymapKey *keys = nullptr;
                         guint *vals = nullptr;
                         gint n = 0;
                         guint res = 0;
                         if (gdk_keymap_get_entries_for_keycode(km, code, &keys,
                                                                &vals, &n)) {
                             for (gint i = 0; i < n; ++i) {
                                 if (keys[i].level == 0 && keys[i].group == 0) {
                                     res = gdk_keyval_to_lower(vals[i]);
                                     break;
                                 }
                             }
                             g_free(keys);
                             g_free(vals);
                         }
                         return res;
                     });
}

} } // namespace art::gui
