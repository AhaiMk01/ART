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
 * The data half of the shortcuts machinery: key specs, the action table, the
 * user overlay and the lookup. Deliberately free of widgets, Glib and the rest
 * of the GUI (it only needs GDK's keyval helpers) so that it can be unit-tested
 * on its own; see shortcutsmanager.h for the dispatcher built on top of it.
 */

#include <gdk/gdk.h>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace art { namespace gui {

enum class ShortcutPhase {
    Before, // before the focused widget sees the key
    After   // after it, i.e. only keys the widget did not consume
};

/// Modifier bits of a normalised key. `Primary` is the OS-convention
/// modifier (Ctrl on Linux/Windows, Cmd on macOS); `Ctrl` is the physical
/// Control key and only exists as a separate bit where it differs from Primary.
namespace shortcut_mod {
constexpr unsigned Primary = 1;
constexpr unsigned Ctrl = 2;
constexpr unsigned Alt = 4;
constexpr unsigned Shift = 8;
} // namespace shortcut_mod


/// The GDK modifier masks that the platform uses for each logical modifier.
struct ModifierMasks {
    guint primary = GDK_CONTROL_MASK;
    guint ctrl = GDK_CONTROL_MASK;
    guint alt = GDK_MOD1_MASK;
    guint shift = GDK_SHIFT_MASK;
    guint altgr = 0; // mask that signals AltGr (0 if the platform has none)

    /// Ask the running GDK; falls back to the X11 conventions if there is
    /// no keymap (e.g. before gtk_init).
    static ModifierMasks native();

    /// Test configurations
    static ModifierMasks linux_like();
    static ModifierMasks mac_like();

    /// Reduce a GdkEventKey::state to a combination of shortcut_mod bits.
    /// Lock and button bits are ignored, and an AltGr press (which some
    /// platforms report as Ctrl+Alt) is not mistaken for those modifiers.
    unsigned normalize(guint state) const;

    bool primaryIsCtrl() const { return primary == ctrl; }
};


struct ShortcutKey {
    guint keyval = 0; // lower-cased: the shift state is in `mods`
    unsigned mods = 0;

    bool valid() const { return keyval != 0; }
    bool operator==(const ShortcutKey &o) const
    {
        return keyval == o.keyval && mods == o.mods;
    }
    bool operator!=(const ShortcutKey &o) const { return !(*this == o); }
};

/// Parse "[Primary+][Ctrl+][Alt+][Shift+]<gdk key name>", case-insensitive
/// for the modifiers. The key is a GDK keyval name ("z", "F3", "plus",
/// "KP_Add", "bracketleft"): the character '+' itself cannot be written, use
/// "plus". Returns false and sets `err` if the spec is not valid.
bool parseShortcutKey(const std::string &spec, const ModifierMasks &masks,
                      ShortcutKey &out, std::string *err = nullptr);

/// What GTK shows for the primary modifier alone ("Ctrl", "⌘"), for prose
/// such as "Ctrl-click".
std::string primaryModifierName(const ModifierMasks &masks);

/// The key as a GTK accelerator (key + modifiers), which is how GTK shows
/// and matches keys in menus. Cmd is spelled META there (not MOD2, with which
/// GTK would print "Mod2" as well).
void shortcutToAccelerator(const ShortcutKey &key, const ModifierMasks &masks,
                           guint &keyval, GdkModifierType &mods);

/// The inverse of parseShortcutKey (canonical spelling). With `display` it is
/// what GTK shows for that accelerator on this platform (gtk_accelerator_
/// get_label: "Ctrl+S", "⌘S", ...), so that tooltips agree with menu hints.
std::string formatShortcutKey(const ShortcutKey &key,
                              const ModifierMasks &masks,
                              bool display = false);

/// The keys an event can be matched as, best first.
///  1. the base-level key (layout independent) with the Shift state as a
///     modifier, so that "Shift+1" works on a layout where Shift+1 is "!";
///  2. if Shift was held and produced a symbol rather than a letter ("plus"
///     from Shift+equal on a US layout, "less" from Shift+comma), that symbol
///     without Shift, so that a spec like "plus" matches whatever key
///     combination types a '+' on the current layout.
/// `base_keyval` is the keyval at shift level 0 (see getKeyval in guiutils),
/// `typed_keyval` is GdkEventKey::keyval.
std::vector<ShortcutKey> shortcutCandidates(const ModifierMasks &masks,
                                            guint base_keyval,
                                            guint typed_keyval, guint state);


struct ShortcutAction {
    std::string id;      // stable dotted name; the key used in shortcuts.json
    std::string context; // where it is active, e.g. "editor", "filebrowser"
    std::vector<std::string> defaults; // key specs, resolved per platform
    ShortcutPhase phase = ShortcutPhase::After;

    ShortcutAction() = default;
    ShortcutAction(std::string i, std::string c, std::vector<std::string> d,
                   ShortcutPhase p = ShortcutPhase::After):
        id(std::move(i)), context(std::move(c)), defaults(std::move(d)),
        phase(p)
    {
    }
};

class ShortcutTable {
public:
    explicit ShortcutTable(const ModifierMasks &masks);

    /// Add an action. Fails (with a warning) on a duplicate id or an
    /// unparsable default key.
    bool define(const ShortcutAction &action);

    bool contains(const std::string &id) const;
    std::vector<std::string> ids() const;
    const ShortcutAction *find(const std::string &id) const;
    const std::vector<ShortcutKey> &keys(const std::string &id) const;
    bool isCustomized(const std::string &id) const;

    /// Replace the current bindings with the defaults overlaid with the
    /// contents of a shortcuts.json. Never throws: every problem becomes an
    /// entry in warnings() and the offending entry is ignored.
    void applyOverrides(const std::string &json_text);
    /// Like applyOverrides, reading the file. A missing file is not an error
    /// (returns false, no warning); an unreadable or invalid one warns.
    bool loadFile(const std::string &path);

    /// Actions of `context`/`phase` that have one of `candidates` among
    /// their keys, in candidate order, then definition order.
    std::vector<const ShortcutAction *>
    lookup(const std::vector<ShortcutKey> &candidates,
           const std::string &context, ShortcutPhase phase) const;

    /// Whether some action of `context`/`phase` has `keyval` as its key,
    /// whatever the modifiers (for key releases, which may come after the
    /// modifier was let go).
    bool usesKeyval(guint keyval, const std::string &context,
                    ShortcutPhase phase) const;

    /// Pairs of actions in the same context and phase sharing a key, as
    /// human-readable lines.
    std::vector<std::string> conflicts() const;

    /// The first key of an action as shown to the user ("Cmd+S"); empty if
    /// the action is disabled.
    std::string label(const std::string &id) const;

    const std::vector<std::string> &warnings() const { return warnings_; }
    void clearWarnings() { warnings_.clear(); }
    const ModifierMasks &masks() const { return masks_; }

    /// All actions with their current keys (or the default ones), as a
    /// shortcuts.json that can be edited to customise them. With `header` it
    /// starts with a comment explaining the structure and the key syntax.
    std::string dumpJson(bool defaults_only = false, bool header = false) const;

private:
    struct Entry {
        ShortcutAction action;
        std::vector<ShortcutKey> defaults;
        std::vector<ShortcutKey> keys;
        bool custom = false;
    };

    int index(const std::string &id) const;
    void resolveConflicts();
    void warn(const std::string &msg);

    ModifierMasks masks_;
    std::vector<Entry> entries_;
    std::map<std::string, int> by_id_;
    std::vector<std::string> warnings_;
};

} } // namespace art::gui
