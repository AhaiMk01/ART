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

#include "shortcutsmanager.h"
#include "guiutils.h"
#include "../utils/multilangmgr.h"
#include "shortcutdefs.h"

#include <cstdio>
#include <cstdlib>
#include <glib/gstdio.h>
#include <glibmm.h>
#include <set>

namespace art { namespace gui {

namespace {

const char *const USER_FILE = "shortcuts.json";
const char *const REFERENCE_FILE = "shortcuts_reference.json";

void writeIfDifferent(const std::string &path, const std::string &text)
{
    if (FILE *f = g_fopen(path.c_str(), "rb")) {
        std::string cur;
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof(buf), f)) > 0) {
            cur.append(buf, n);
        }
        fclose(f);
        if (cur == text) {
            return;
        }
    }
    if (FILE *f = g_fopen(path.c_str(), "wb")) {
        fwrite(text.data(), 1, text.size(), f);
        fclose(f);
    }
}

} // namespace


ShortcutsManager::ShortcutsManager():
    table_(new ShortcutTable(ModifierMasks())),
    debug_(std::getenv("ART_SHORTCUTS_DEBUG") != nullptr)
{
}


ShortcutsManager *ShortcutsManager::getInstance()
{
    static ShortcutsManager instance;
    return &instance;
}


void ShortcutsManager::init(const Glib::ustring &system_dir,
                            const Glib::ustring &user_config_dir)
{
    table_.reset(new ShortcutTable(ModifierMasks::native()));
    defineDefaultShortcuts(*table_);

    // for "%shortcut(action.id)%" in the translated strings (tooltips, ...):
    // they are markup, hence the escaping
    utils::langMgr.setShortcutLabeler([this](const std::string &id) {
        if (!table_->contains(id)) {
            fprintf(stderr, "shortcuts: unknown action '%s' in a string\n",
                    id.c_str());
            return Glib::ustring("?");
        }
        auto l = table_->label(id);
        return l.empty() ? Glib::ustring("-") : Glib::Markup::escape_text(l);
    });

    // two layers on top of the built-in defaults: the shortcuts.json installed
    // with ART, then the user's one. Problems are reported with the name of
    // the file they were found in.
    system_dir_ = system_dir;
    user_dir_ = user_config_dir;
    std::vector<std::string> loaded;
    for (const auto &dir : {system_dir, user_config_dir}) {
        if (dir.empty()) {
            continue;
        }
        const std::string file = Glib::build_filename(dir, USER_FILE);
        if (table_->loadFile(file, false)) {
            loaded.push_back(file);
        }
        for (auto &w : table_->warnings()) {
            fprintf(stderr, "%s (%s)\n", w.c_str(), file.c_str());
        }
        table_->clearWarnings();
    }

    // "%mouse_primary%" in the strings: "Ctrl-click" or "Cmd-click"
    utils::langMgr.setMousePrimaryModifierName(table_->mouseModifierName());

    if (!user_config_dir.empty()) {
        // something to copy from: all the actions with their default keys,
        // kept up to date with the version of ART that is running
        writeIfDifferent(Glib::build_filename(user_config_dir, REFERENCE_FILE),
                         table_->dumpJson(true, true));
    }

    if (debug_) {
        for (auto &c : table_->conflicts()) {
            fprintf(stderr, "shortcuts: conflict: %s\n", c.c_str());
        }
        std::string from = "defaults only";
        for (size_t i = 0; i < loaded.size(); ++i) {
            from = (i ? from + ", " : "customised from ") + loaded[i];
        }
        fprintf(stderr, "shortcuts: %zu actions, %s\n", table_->ids().size(),
                from.c_str());
        fprintf(stderr, "shortcuts: mouse modifier: %s (mask 0x%x), save: %s\n",
                table_->mouseModifierName().c_str(), table_->mousePrimaryMask(),
                table_->label("editor.save").c_str());
    }
}


ShortcutTable ShortcutsManager::baselineTable() const
{
    ShortcutTable t(table_->masks());
    defineDefaultShortcuts(t);
    if (!system_dir_.empty()) {
        t.loadFile(Glib::build_filename(system_dir_, USER_FILE), false);
    }
    return t;
}


bool ShortcutsManager::saveUserFile(const ShortcutTable &edited,
                                    std::string &err) const
{
    if (user_dir_.empty()) {
        err = "no configuration folder";
        return false;
    }
    const std::string text = edited.dumpOverrides(baselineTable());
    const std::string path = Glib::build_filename(user_dir_, USER_FILE);
    const std::string backup = path + ".bak";

    if (Glib::file_test(path, Glib::FILE_TEST_IS_REGULAR) &&
        !Glib::file_test(backup, Glib::FILE_TEST_EXISTS)) {
        try {
            Glib::file_set_contents(backup, Glib::file_get_contents(path));
        } catch (Glib::Error &e) {
            err = "cannot back up " + path + ": " + e.what();
            return false;
        }
    }
    try {
        // atomic: a crash must not leave half a file
        Glib::file_set_contents(path, text);
    } catch (Glib::Error &e) {
        err = "cannot write " + path + ": " + e.what();
        return false;
    }
    return true;
}


void ShortcutsManager::bind(const void *owner, const std::string &id,
                            Handler handler, Guard enabled)
{
    if (!table_->contains(id)) {
        fprintf(stderr, "shortcuts: binding to unknown action '%s'\n",
                id.c_str());
        return;
    }
    bindings_[std::make_pair(owner, id)] = {std::move(handler),
                                            std::move(enabled)};
}


void ShortcutsManager::unbindOwner(const void *owner)
{
    for (auto it = bindings_.begin(); it != bindings_.end();) {
        if (it->first.first == owner) {
            it = bindings_.erase(it);
        } else {
            ++it;
        }
    }
}


std::vector<ShortcutKey> ShortcutsManager::candidates(GdkEventKey *event) const
{
    return shortcutCandidates(table_->masks(), getKeyval(event, false),
                              event->keyval, event->state);
}


bool ShortcutsManager::matches(GdkEventKey *event, ShortcutPhase phase,
                               const std::string &context) const
{
    return !table_->lookup(candidates(event), context, phase).empty();
}


bool ShortcutsManager::matchesKey(GdkEventKey *event, ShortcutPhase phase,
                                   const std::string &context) const
{
    return table_->usesKeyval(getKeyval(event, false), context, phase) ||
           table_->usesKeyval(event->keyval, context, phase);
}


bool ShortcutsManager::dispatch(GdkEventKey *event, ShortcutPhase phase,
                                const std::vector<ShortcutScope> &chain)
{
    const auto &masks = table_->masks();
    const auto cands = candidates(event);

    for (auto &scope : chain) {
        for (auto action : table_->lookup(cands, scope.context, phase)) {
            auto it = bindings_.find(std::make_pair(scope.owner, action->id));
            if (it == bindings_.end()) {
                continue;
            }
            auto &b = it->second;
            if (b.enabled && !b.enabled()) {
                continue;
            }
            // the handler may bind/unbind: work on a copy
            Handler h = b.handler;
            if (h(event)) {
                if (debug_) {
                    fprintf(stderr, "shortcuts: %s -> %s [%s]\n",
                            formatShortcutKey(cands[0], masks).c_str(),
                            action->id.c_str(), scope.context.c_str());
                }
                return true;
            }
        }
    }
    // a bare Shift/Ctrl/Alt/Cmd press is never a shortcut: keep it out of the log
    const bool modifier_only =
        (event->keyval >= GDK_KEY_Shift_L && event->keyval <= GDK_KEY_Hyper_R) ||
        event->keyval == GDK_KEY_ISO_Level3_Shift;
    // (the before phase sees every key first: only the final verdict is news)
    if (debug_ && !modifier_only && phase == ShortcutPhase::After) {
        fprintf(stderr, "shortcuts: %s: not handled (%s)\n",
                formatShortcutKey(cands[0], masks).c_str(),
                phase == ShortcutPhase::Before ? "before" : "after");
    }
    return false;
}


void ShortcutsManager::addAccelerator(
    Gtk::MenuItem &item, const Glib::RefPtr<Gtk::AccelGroup> &group,
    const std::string &id) const
{
    auto &keys = table_->keys(id);
    if (keys.empty()) {
        return;
    }
    guint keyval;
    GdkModifierType mods;
    shortcutToAccelerator(keys[0], table_->masks(), keyval, mods);
    item.add_accelerator("activate", group, keyval,
                         static_cast<Gdk::ModifierType>(mods),
                         Gtk::ACCEL_VISIBLE);
}


std::vector<std::string> ShortcutsManager::unboundActions() const
{
    std::set<std::string> bound;
    for (auto &b : bindings_) {
        bound.insert(b.first.second);
    }
    std::vector<std::string> res;
    for (auto &id : table_->ids()) {
        if (!bound.count(id)) {
            res.push_back(id);
        }
    }
    return res;
}


void ShortcutsManager::reportUnbound() const
{
    if (!debug_) {
        return;
    }
    for (auto &id : unboundActions()) {
        fprintf(stderr, "shortcuts: never bound: %s\n", id.c_str());
    }
}


Glib::ustring ShortcutsManager::label(const std::string &id) const
{
    return table_->label(id);
}

} } // namespace art::gui
