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

#include "shortcuttable.h"
#include <functional>
#include <glibmm/ustring.h>
#include <gtkmm/accelgroup.h>
#include <gtkmm/menuitem.h>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace art { namespace gui {

/// One step of the chain a window asks when a key is pressed: the shortcuts
/// of `context` as handled by the component instance `owner` (nullptr for
/// components that exist once, like the batch queue).
struct ShortcutScope {
    std::string context;
    const void *owner = nullptr;

    ShortcutScope(std::string c, const void *o = nullptr):
        context(std::move(c)), owner(o)
    {
    }
};

/**
 * The single place where keyboard shortcuts are defined (shortcutdefs.cc),
 * customised (shortcuts.json in the user config dir) and dispatched.
 *
 * Components bind a handler to the id of an action; windows call dispatch()
 * from their key handlers with the ordered list of scopes that are active,
 * and the first enabled handler that returns true consumes the key. See
 * shortcuttable.h for the key syntax and the customisation rules.
 *
 * Only to be used from the GTK main thread.
 */
class ShortcutsManager {
public:
    using Handler = std::function<bool(GdkEventKey *)>;
    using Guard = std::function<bool()>;

    static ShortcutsManager *getInstance();

    /// Define the default actions and overlay `<user_config_dir>/shortcuts.json`
    /// if there is one. Problems with the file are reported on stderr and
    /// never prevent startup. Must be called after gtk_init (it asks GDK
    /// which modifier is the primary one). Calling it again reloads.
    void init(const Glib::ustring &user_config_dir);

    /// Attach the code for action `id` of component `owner`. `enabled`, if
    /// given, is asked before every call and replaces inline checks such as
    /// "not in simple editor mode". Rebinding the same (owner, id) replaces.
    void bind(const void *owner, const std::string &id, Handler handler,
              Guard enabled = Guard());
    /// Shorthand for components that exist once.
    void bind(const std::string &id, Handler handler, Guard enabled = Guard())
    {
        bind(nullptr, id, std::move(handler), std::move(enabled));
    }
    /// To be called when a component goes away.
    void unbindOwner(const void *owner);

    /// Try to handle `event`. Returns true if a handler consumed it.
    bool dispatch(GdkEventKey *event, ShortcutPhase phase,
                  const std::vector<ShortcutScope> &chain);

    /// Whether `event` is a key of some action of `context`, without running
    /// anything (e.g. to tell a key release that belongs to a shortcut).
    bool matches(GdkEventKey *event, ShortcutPhase phase,
                 const std::string &context) const;

    /// Like matches(), but ignoring the modifiers: for the release of a key
    /// whose action is done with modifiers that may be let go first.
    bool matchesKey(GdkEventKey *event, ShortcutPhase phase,
                    const std::string &context) const;

    /// How GTK shows the first key of action `id` ("Ctrl+S", "⌘S"), "" if it
    /// is disabled. The same text as the menu hints.
    /// For tooltips and menu hints.
    Glib::ustring label(const std::string &id) const;

    /// The modifier mask(s) of the OS-convention primary modifier (Ctrl, or
    /// Cmd on macOS), for code that inspects event states itself, e.g. for
    /// "Ctrl-click": `event->state & ShortcutsManager::primaryMask()`.
    static guint primaryMask() { return getInstance()->table_->masks().primary; }

    /// Show action `id`'s first key as the accelerator hint of a menu item
    /// (for items whose activation is done by dispatch(), not by GTK).
    /// Nothing is shown if the action is disabled.
    void addAccelerator(Gtk::MenuItem &item,
                        const Glib::RefPtr<Gtk::AccelGroup> &group,
                        const std::string &id) const;

    /// Actions that no component ever bound a handler to (a to-do list while
    /// the migration is going on, and a check that nothing was forgotten).
    std::vector<std::string> unboundActions() const;

    /// With ART_SHORTCUTS_DEBUG set, print unboundActions() on stderr.
    void reportUnbound() const;

    const ShortcutTable &table() const { return *table_; }

private:
    ShortcutsManager();
    std::vector<ShortcutKey> candidates(GdkEventKey *event) const;

    struct Binding {
        Handler handler;
        Guard enabled;
    };

    std::unique_ptr<ShortcutTable> table_;
    std::map<std::pair<const void *, std::string>, Binding> bindings_;
    bool debug_;
};

} } // namespace art::gui
