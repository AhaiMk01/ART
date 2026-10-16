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
#include <gtkmm.h>
#include <map>
#include <string>

namespace art { namespace gui {

/**
 * The "Shortcuts" tab of the Preferences: a tree of all the actions of the
 * ShortcutsManager, with the hierarchy of the dotted action ids that are the
 * entries of shortcuts.json (editor -> zoom_fit, filecatalog -> filter_rank
 * -> 1, ...), where keys can be recorded, added, removed and reset.
 *
 * It works on a copy of the table; nothing is written until save(), which is
 * called when the Preferences are confirmed. The new keys are used from the
 * next start of ART.
 */
class ShortcutsEditor: public Gtk::Box {
public:
    ShortcutsEditor();

    /// Write shortcuts.json if anything was changed. Returns false, and sets
    /// `err`, if that failed.
    bool save(std::string &err);

private:
    class Columns: public Gtk::TreeModel::ColumnRecord {
    public:
        Gtk::TreeModelColumn<Glib::ustring> name;
        Gtk::TreeModelColumn<Glib::ustring> keys;
        Gtk::TreeModelColumn<std::string> id; // empty for the groups
        Gtk::TreeModelColumn<int> weight;     // bold: differs from the default
        Gtk::TreeModelColumn<Glib::ustring> tooltip;

        Columns()
        {
            add(name);
            add(keys);
            add(id);
            add(weight);
            add(tooltip);
        }
    };

    void populate();
    bool rowVisible(const Gtk::TreeModel::const_iterator &row) const;
    bool rowMatches(const Gtk::TreeModel::const_iterator &row) const;
    void searchChanged();
    void primaryModifierChanged();
    void mouseModifierChanged();
    void syncModifierButtons();
    Gtk::TreeIter node(const std::string &path);
    void refresh();
    void refreshRow(const Gtk::TreeIter &row);
    std::string selectedAction();

    void selectionChanged();
    void rowActivated(const Gtk::TreeModel::Path &path,
                      Gtk::TreeViewColumn *column);
    void changePressed(bool add);
    void disablePressed();
    void resetPressed();
    void resetAllPressed();

    bool recordKey(ShortcutKey &out);
    bool assign(const std::string &id, const ShortcutKey &key, bool add);
    bool resolveSystemClashes();
    Glib::ustring displayKeys(const std::string &id) const;
    static Glib::ustring displayName(const std::string &id);

    ShortcutTable work_;
    ShortcutTable base_;
    std::string saved_; // work_.dumpOverrides(base_) when it was opened

    Columns columns_;
    Glib::RefPtr<Gtk::TreeStore> model_;
    std::map<std::string, Gtk::TreeIter> nodes_;
    Glib::RefPtr<Gtk::TreeModelFilter> filter_;
    Glib::ustring query_; // lower case
    Gtk::SearchEntry search_;
    // the choice of the Primary modifier and of the one of the mouse actions:
    // Ctrl or the OS key; the second button of each is in the group of the
    // first
    Gtk::RadioButton primary_ctrl_;
    Gtk::RadioButton primary_os_;
    Gtk::RadioButton mouse_ctrl_;
    Gtk::RadioButton mouse_os_;
    sigc::connection primary_conn_;
    sigc::connection mouse_conn_;
    Gtk::TreeView tree_;
    Gtk::Button *change_;
    Gtk::Button *add_;
    Gtk::Button *disable_;
    Gtk::Button *reset_;
};

} } // namespace art::gui
