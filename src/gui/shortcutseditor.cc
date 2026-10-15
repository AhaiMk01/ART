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

#include "shortcutseditor.h"
#include "guiutils.h"
#include "shortcutsmanager.h"
#include "../utils/multilangmgr.h"

#include <algorithm>

namespace art { namespace gui {

using utils::M;

namespace {

Glib::ustring prettify(const std::string &component)
{
    Glib::ustring res(component);
    for (auto it = res.begin(); it != res.end(); ++it) {
        if (*it == '_') {
            res.replace(it, std::next(it), " ");
        }
    }
    if (!res.empty()) {
        res.replace(res.begin(), std::next(res.begin()),
                    res.substr(0, 1).uppercase());
    }
    return res;
}


std::vector<std::string> split(const std::string &id)
{
    std::vector<std::string> res;
    size_t b = 0;
    while (true) {
        size_t e = id.find('.', b);
        res.push_back(id.substr(b, e == std::string::npos ? e : e - b));
        if (e == std::string::npos) {
            return res;
        }
        b = e + 1;
    }
}

} // namespace


ShortcutsEditor::ShortcutsEditor():
    Gtk::Box(Gtk::ORIENTATION_VERTICAL, 4),
    work_(ShortcutsManager::getInstance()->table()),
    base_(ShortcutsManager::getInstance()->baselineTable())
{
    saved_ = work_.dumpOverrides(base_);
    set_border_width(4);

    search_.set_placeholder_text(M("PREFERENCES_SHORTCUTS_SEARCH"));
    pack_start(search_, Gtk::PACK_SHRINK);

    model_ = Gtk::TreeStore::create(columns_);
    filter_ = Gtk::TreeModelFilter::create(model_);
    filter_->set_visible_func(
        sigc::mem_fun(*this, &ShortcutsEditor::rowVisible));
    tree_.set_model(filter_);
    tree_.set_tooltip_column(columns_.tooltip.index());
    tree_.set_enable_search(false); // the search box does it
    setTreeViewCssProvider(&tree_);

    auto *name_col = Gtk::manage(new Gtk::TreeViewColumn(
        M("PREFERENCES_SHORTCUTS_ACTION")));
    auto *name_cell = Gtk::manage(new Gtk::CellRendererText());
    name_col->pack_start(*name_cell);
    name_col->add_attribute(name_cell->property_text(), columns_.name);
    name_col->add_attribute(name_cell->property_weight(), columns_.weight);
    name_col->set_expand(true);
    tree_.append_column(*name_col);

    auto *keys_col = Gtk::manage(new Gtk::TreeViewColumn(
        M("PREFERENCES_SHORTCUTS_KEYS")));
    auto *keys_cell = Gtk::manage(new Gtk::CellRendererText());
    keys_col->pack_start(*keys_cell);
    keys_col->add_attribute(keys_cell->property_text(), columns_.keys);
    keys_col->add_attribute(keys_cell->property_weight(), columns_.weight);
    tree_.append_column(*keys_col);

    auto *sw = Gtk::manage(new Gtk::ScrolledWindow());
    sw->set_policy(Gtk::POLICY_AUTOMATIC, Gtk::POLICY_AUTOMATIC);
    sw->set_shadow_type(Gtk::SHADOW_IN);
    sw->add(tree_);
    pack_start(*sw, Gtk::PACK_EXPAND_WIDGET);

    auto *buttons = Gtk::manage(new Gtk::Box(Gtk::ORIENTATION_HORIZONTAL, 4));
    change_ = Gtk::manage(new Gtk::Button(M("PREFERENCES_SHORTCUTS_CHANGE")));
    add_ = Gtk::manage(new Gtk::Button(M("PREFERENCES_SHORTCUTS_ADD")));
    disable_ = Gtk::manage(new Gtk::Button(M("GENERAL_DISABLE")));
    reset_ = Gtk::manage(new Gtk::Button(M("GENERAL_RESET")));
    auto *reset_all =
        Gtk::manage(new Gtk::Button(M("PREFERENCES_SHORTCUTS_RESETALL")));
    for (auto b : {change_, add_, disable_, reset_}) {
        buttons->pack_start(*b, Gtk::PACK_SHRINK);
    }
    buttons->pack_end(*reset_all, Gtk::PACK_SHRINK);
    pack_start(*buttons, Gtk::PACK_SHRINK);

    // Primary and Ctrl are different keys only where Primary is not Ctrl
    const auto &masks = work_.masks();
    if (!masks.primaryIsCtrl()) {
        auto *mm = Gtk::manage(new Gtk::Box(Gtk::ORIENTATION_HORIZONTAL, 8));
        auto *ml = Gtk::manage(new Gtk::Label(
            M("PREFERENCES_SHORTCUTS_MOUSEMOD") + ":"));
        mouse_primary_.set_label(modifierName(masks, shortcut_mod::Primary));
        mouse_ctrl_.set_label(modifierName(masks, shortcut_mod::Ctrl));
        mouse_ctrl_.join_group(mouse_primary_);
        (work_.mouseModifier() == shortcut_mod::Ctrl ? mouse_ctrl_
                                                     : mouse_primary_)
            .set_active(true);
        ml->set_tooltip_text(M("PREFERENCES_SHORTCUTS_MOUSEMOD_TIP"));
        mouse_primary_.set_tooltip_text(
            M("PREFERENCES_SHORTCUTS_MOUSEMOD_TIP"));
        mouse_ctrl_.set_tooltip_text(M("PREFERENCES_SHORTCUTS_MOUSEMOD_TIP"));
        mm->pack_start(*ml, Gtk::PACK_SHRINK);
        mm->pack_start(mouse_primary_, Gtk::PACK_SHRINK);
        mm->pack_start(mouse_ctrl_, Gtk::PACK_SHRINK);
        pack_start(*mm, Gtk::PACK_SHRINK);
        // a change toggles both buttons: the state of one says it all
        mouse_mod_conn_ = mouse_ctrl_.signal_toggled().connect(
            sigc::mem_fun(*this, &ShortcutsEditor::mouseModifierChanged));
    }

    auto *note = Gtk::manage(new Gtk::Label(M("PREFERENCES_SHORTCUTS_RESTART")));
    note->set_xalign(0);
    note->set_line_wrap(true);
    pack_start(*note, Gtk::PACK_SHRINK);

    change_->signal_clicked().connect(
        sigc::bind(sigc::mem_fun(*this, &ShortcutsEditor::changePressed),
                   false));
    add_->signal_clicked().connect(
        sigc::bind(sigc::mem_fun(*this, &ShortcutsEditor::changePressed),
                   true));
    disable_->signal_clicked().connect(
        sigc::mem_fun(*this, &ShortcutsEditor::disablePressed));
    reset_->signal_clicked().connect(
        sigc::mem_fun(*this, &ShortcutsEditor::resetPressed));
    reset_all->signal_clicked().connect(
        sigc::mem_fun(*this, &ShortcutsEditor::resetAllPressed));
    search_.signal_search_changed().connect(
        sigc::mem_fun(*this, &ShortcutsEditor::searchChanged));
    tree_.get_selection()->signal_changed().connect(
        sigc::mem_fun(*this, &ShortcutsEditor::selectionChanged));
    tree_.signal_row_activated().connect(
        sigc::mem_fun(*this, &ShortcutsEditor::rowActivated));

    populate();
    selectionChanged();
}


// The row of a node of the hierarchy ("editor", "editor.zoom_fit"), created
// together with its parents; the groups appear in the order in which the
// actions are defined, which is the order of shortcuts.json.
Gtk::TreeIter ShortcutsEditor::node(const std::string &path)
{
    auto it = nodes_.find(path);
    if (it != nodes_.end()) {
        return it->second;
    }
    const size_t dot = path.rfind('.');
    Gtk::TreeIter row;
    if (dot == std::string::npos) {
        row = model_->append();
        (*row)[columns_.name] = prettify(path);
    } else {
        row = model_->append(node(path.substr(0, dot))->children());
        (*row)[columns_.name] = prettify(path.substr(dot + 1));
    }
    (*row)[columns_.weight] = Pango::WEIGHT_NORMAL;
    nodes_[path] = row;
    return row;
}


// Text that a search looks into: for an action, its name, id and keys; for a
// group, its name
bool ShortcutsEditor::rowMatches(const Gtk::TreeModel::const_iterator &row) const
{
    Glib::ustring text = (*row)[columns_.name];
    const std::string id = (*row)[columns_.id];
    if (!id.empty()) {
        text += " " + displayName(id) + " " + id + " " +
                Glib::ustring((*row)[columns_.keys]);
    }
    return text.lowercase().find(query_) != Glib::ustring::npos;
}


// A row is shown if it matches, if a group above it matches (the whole group
// is then shown), or if something below it does
bool ShortcutsEditor::rowVisible(
    const Gtk::TreeModel::const_iterator &row) const
{
    if (query_.empty() || rowMatches(row)) {
        return true;
    }
    for (auto p = row->parent(); p; p = p->parent()) {
        if (rowMatches(p)) {
            return true;
        }
    }
    for (auto &c : row->children()) {
        if (rowVisible(c)) {
            return true;
        }
    }
    return false;
}


void ShortcutsEditor::searchChanged()
{
    query_ = search_.get_text().lowercase();
    filter_->refilter();
    if (!query_.empty()) {
        tree_.expand_all();
    } else {
        tree_.collapse_all();
    }
    selectionChanged();
}


void ShortcutsEditor::mouseModifierChanged()
{
    work_.setMouseModifier(mouse_ctrl_.get_active() ? shortcut_mod::Ctrl
                               : shortcut_mod::Primary);
}


void ShortcutsEditor::populate()
{
    for (auto &id : work_.ids()) {
        auto row = node(id);
        (*row)[columns_.id] = id;
        auto action = work_.find(id);
        (*row)[columns_.tooltip] =
            Glib::Markup::escape_text(id + "  [" + action->context + "]");
        refreshRow(row);
    }
}


Glib::ustring ShortcutsEditor::displayKeys(const std::string &id) const
{
    Glib::ustring res;
    for (auto &k : work_.keys(id)) {
        res += (res.empty() ? "" : ", ") +
               Glib::ustring(formatShortcutKey(k, work_.masks(), true));
    }
    return res.empty() ? M("GENERAL_DISABLED") : res;
}


Glib::ustring ShortcutsEditor::displayName(const std::string &id)
{
    Glib::ustring res;
    for (auto &c : split(id)) {
        res += (res.empty() ? "" : " / ") + prettify(c);
    }
    return res;
}


void ShortcutsEditor::refreshRow(const Gtk::TreeIter &row)
{
    const std::string id = (*row)[columns_.id];
    if (id.empty()) {
        return;
    }
    (*row)[columns_.keys] = displayKeys(id);
    (*row)[columns_.weight] =
        work_.keys(id) != base_.keys(id) ? Pango::WEIGHT_BOLD
                                         : Pango::WEIGHT_NORMAL;
}


void ShortcutsEditor::refresh()
{
    // an assignment can also take a key away from another action
    for (auto &n : nodes_) {
        refreshRow(n.second);
    }
    if (!query_.empty()) {
        filter_->refilter(); // a search also looks at the keys
    }
}


std::string ShortcutsEditor::selectedAction()
{
    if (auto row = tree_.get_selection()->get_selected()) {
        return (*row)[columns_.id];
    }
    return "";
}


void ShortcutsEditor::selectionChanged()
{
    const std::string id = selectedAction();
    const bool action = !id.empty();
    change_->set_sensitive(action);
    add_->set_sensitive(action);
    disable_->set_sensitive(action && !work_.keys(id).empty());
    reset_->set_sensitive(action && work_.keys(id) != base_.keys(id));
}


void ShortcutsEditor::rowActivated(const Gtk::TreeModel::Path &path,
                                   Gtk::TreeViewColumn *)
{
    if (selectedAction().empty()) {
        if (tree_.row_expanded(path)) {
            tree_.collapse_row(path);
        } else {
            tree_.expand_row(path, false);
        }
    } else {
        changePressed(false);
    }
}


// Ask for a key press. Esc (or the Cancel button) gives up.
bool ShortcutsEditor::recordKey(ShortcutKey &out)
{
    Gtk::Dialog dlg(M("PREFERENCES_SHORTCUTS_PRESS"), getToplevelWindow(this),
                    true);
    auto *label = Gtk::manage(new Gtk::Label(
        M("PREFERENCES_SHORTCUTS_PRESS") + "\n\n" +
        M("PREFERENCES_SHORTCUTS_ESC")));
    label->set_justify(Gtk::JUSTIFY_CENTER);
    label->set_margin_top(24);
    label->set_margin_bottom(24);
    label->set_margin_start(24);
    label->set_margin_end(24);
    dlg.get_content_area()->pack_start(*label);
    dlg.add_button(M("GENERAL_CANCEL"), Gtk::RESPONSE_CANCEL);

    bool got = false;
    const auto &masks = work_.masks();
    dlg.signal_key_press_event().connect(
        [&](GdkEventKey *ev) {
            // a modifier alone is not a shortcut: wait for the key
            if ((ev->keyval >= GDK_KEY_Shift_L &&
                 ev->keyval <= GDK_KEY_Hyper_R) ||
                ev->keyval == GDK_KEY_ISO_Level3_Shift) {
                return true;
            }
            if (ev->keyval == GDK_KEY_Escape &&
                !(ev->state & gtk_accelerator_get_default_mod_mask())) {
                dlg.response(Gtk::RESPONSE_CANCEL);
                return true;
            }
            out = shortcutFromEvent(masks, getKeyval(ev, false), ev->keyval,
                                    ev->state);
            got = out.valid();
            dlg.response(got ? Gtk::RESPONSE_OK : Gtk::RESPONSE_CANCEL);
            return true;
        },
        false); // before the dialog's own handling (Tab, mnemonics, ...)
    dlg.show_all_children();
    dlg.run();
    return got;
}


void ShortcutsEditor::assign(const std::string &id, const ShortcutKey &key,
                             bool add)
{
    const std::string other = work_.findConflict(id, key);
    if (!other.empty()) {
        Gtk::MessageDialog msg(
            getToplevelWindow(this),
            Glib::ustring::compose(M("PREFERENCES_SHORTCUTS_CONFLICT"),
                                   formatShortcutKey(key, work_.masks(), true),
                                   displayName(other)),
            false, Gtk::MESSAGE_QUESTION, Gtk::BUTTONS_NONE, true);
        msg.add_button(M("GENERAL_CANCEL"), Gtk::RESPONSE_CANCEL);
        msg.add_button(M("PREFERENCES_SHORTCUTS_REASSIGN"), Gtk::RESPONSE_OK);
        if (msg.run() != Gtk::RESPONSE_OK) {
            return;
        }
        // the other action loses the key (and is disabled if it was its last)
        auto keys = work_.keys(other);
        keys.erase(std::remove(keys.begin(), keys.end(), key), keys.end());
        work_.setKeys(other, keys);
    }
    auto keys = add ? work_.keys(id) : std::vector<ShortcutKey>();
    keys.push_back(key);
    work_.setKeys(id, keys);
}


void ShortcutsEditor::changePressed(bool add)
{
    const std::string id = selectedAction();
    ShortcutKey key;
    if (!id.empty() && recordKey(key)) {
        assign(id, key, add);
        refresh();
        selectionChanged();
    }
}


void ShortcutsEditor::disablePressed()
{
    const std::string id = selectedAction();
    if (!id.empty()) {
        work_.setKeys(id, {});
        refresh();
        selectionChanged();
    }
}


void ShortcutsEditor::resetPressed()
{
    const std::string id = selectedAction();
    if (!id.empty()) {
        // the baseline cannot clash with itself, but another action may have
        // been given its key since: take it back from there
        for (auto &k : base_.keys(id)) {
            const std::string other = work_.findConflict(id, k);
            if (!other.empty()) {
                auto keys = work_.keys(other);
                keys.erase(std::remove(keys.begin(), keys.end(), k),
                           keys.end());
                work_.setKeys(other, keys);
            }
        }
        work_.setKeys(id, base_.keys(id));
        refresh();
        selectionChanged();
    }
}


void ShortcutsEditor::resetAllPressed()
{
    for (auto &id : work_.ids()) {
        work_.setKeys(id, base_.keys(id));
    }
    work_.setMouseModifier(base_.mouseModifier());
    mouse_mod_conn_.block();
    (base_.mouseModifier() == shortcut_mod::Ctrl ? mouse_ctrl_
                                                 : mouse_primary_)
        .set_active(true);
    mouse_mod_conn_.unblock();
    refresh();
    selectionChanged();
}


bool ShortcutsEditor::save(std::string &err)
{
    const std::string text = work_.dumpOverrides(base_);
    if (text == saved_) {
        return true; // nothing changed: leave the user's file alone
    }
    if (ShortcutsManager::getInstance()->saveUserFile(work_, err)) {
        saved_ = text;
        return true;
    }
    return false;
}

} } // namespace art::gui
