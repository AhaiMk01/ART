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

#include "shortcuttable.h"
#include "../engine/cJSON.h"

#include <gtk/gtk.h>

#include <algorithm>
#include <cctype>
#include <clocale>
#include <cstdio>
#include <set>

namespace art { namespace gui {

namespace {

namespace sm = shortcut_mod;

std::string lower(std::string s)
{
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return s;
}

std::string trim(const std::string &s)
{
    size_t b = s.find_first_not_of(" \t");
    if (b == std::string::npos) {
        return "";
    }
    size_t e = s.find_last_not_of(" \t");
    return s.substr(b, e - b + 1);
}

bool isCased(guint keyval)
{
    return gdk_keyval_to_lower(keyval) != gdk_keyval_to_upper(keyval);
}

} // namespace


ModifierMasks ModifierMasks::linux_like()
{
    ModifierMasks m;
    m.altgr = GDK_MOD5_MASK;
    return m;
}


ModifierMasks ModifierMasks::mac_like()
{
    ModifierMasks m;
    m.primary = GDK_MOD2_MASK;
    return m;
}


ModifierMasks ModifierMasks::native()
{
    ModifierMasks m;
#if defined(__WIN32__)
    m.altgr = GDK_MOD2_MASK;
#elif defined(__APPLE__)
    m.altgr = 0;
#else
    m.altgr = GDK_MOD5_MASK;
#endif
    if (GdkKeymap *km = gdk_keymap_get_default()) {
        guint p = gdk_keymap_get_modifier_mask(
            km, GDK_MODIFIER_INTENT_PRIMARY_ACCELERATOR);
        // virtual modifiers (e.g. META) come along with the real one: keep
        // only the bits that gdk reports in a key event's state
        p &= GDK_CONTROL_MASK | GDK_MOD1_MASK | GDK_MOD2_MASK | GDK_META_MASK |
             GDK_SUPER_MASK;
        if (p) {
            m.primary = p;
        }
    }
    return m;
}


unsigned ModifierMasks::normalize(guint state) const
{
    // some platforms report AltGr as Ctrl+Alt (plus their own bit): that is a
    // character-producing key, not a modifier combination
    if (altgr && (state & altgr) && !(altgr & (primary | ctrl | alt))) {
        state &= ~(primary | ctrl | alt);
    }
    unsigned res = 0;
    if (state & primary) {
        res |= sm::Primary;
    }
    if (!primaryIsCtrl() && (state & ctrl)) {
        res |= sm::Ctrl;
    }
    if (state & alt) {
        res |= sm::Alt;
    }
    if (state & shift) {
        res |= sm::Shift;
    }
    return res;
}


bool parseShortcutKey(const std::string &spec_in, const ModifierMasks &masks,
                      ShortcutKey &out, std::string *err)
{
    auto fail = [&](const std::string &msg) {
        if (err) {
            *err = msg;
        }
        return false;
    };

    const std::string spec = trim(spec_in);
    if (spec.empty()) {
        return fail("empty key");
    }

    std::vector<std::string> tokens;
    size_t start = 0;
    while (true) {
        size_t p = spec.find('+', start);
        tokens.push_back(trim(spec.substr(start, p == std::string::npos
                                                     ? std::string::npos
                                                     : p - start)));
        if (p == std::string::npos) {
            break;
        }
        start = p + 1;
    }

    unsigned mods = 0;
    for (size_t i = 0; i + 1 < tokens.size(); ++i) {
        const std::string t = lower(tokens[i]);
        unsigned m = 0;
        if (t == "primary") {
            m = sm::Primary;
        } else if (t == "ctrl" || t == "control") {
            m = masks.primaryIsCtrl() ? sm::Primary : sm::Ctrl;
        } else if (t == "alt") {
            m = sm::Alt;
        } else if (t == "shift") {
            m = sm::Shift;
        } else {
            return fail("unknown modifier '" + tokens[i] + "'");
        }
        if (mods & m) {
            return fail("repeated modifier '" + tokens[i] + "'");
        }
        mods |= m;
    }

    const std::string &name = tokens.back();
    if (name.empty()) {
        return fail("missing key name (write 'plus' for the + key)");
    }
    guint kv = gdk_keyval_from_name(name.c_str());
    if (kv == GDK_KEY_VoidSymbol || kv == 0) {
        return fail("unknown key '" + name + "'");
    }
    out.keyval = gdk_keyval_to_lower(kv);
    out.mods = mods;
    return true;
}


void shortcutToAccelerator(const ShortcutKey &key, const ModifierMasks &masks,
                           guint &keyval, GdkModifierType &mods)
{
    guint m = 0;
    if (key.mods & sm::Primary) {
        m |= masks.primary;
        if (m & GDK_MOD2_MASK) {
            m = (m & ~GDK_MOD2_MASK) | GDK_META_MASK;
        }
    }
    if (key.mods & sm::Ctrl) {
        m |= masks.ctrl;
    }
    if (key.mods & sm::Alt) {
        m |= masks.alt;
    }
    if (key.mods & sm::Shift) {
        m |= masks.shift;
    }
    keyval = key.keyval;
    mods = static_cast<GdkModifierType>(m);
}


std::string formatShortcutKey(const ShortcutKey &key,
                              const ModifierMasks &masks, bool display)
{
    if (display) {
        guint kv;
        GdkModifierType m;
        shortcutToAccelerator(key, masks, kv, m);
        gchar *label = gtk_accelerator_get_label(kv, m);
        std::string res = label ? label : "";
        g_free(label);
        return res;
    }

    std::string res;
    if (key.mods & sm::Primary) {
        res += "Primary+";
    }
    if (key.mods & sm::Ctrl) {
        res += "Ctrl+";
    }
    if (key.mods & sm::Alt) {
        res += "Alt+";
    }
    if (key.mods & sm::Shift) {
        res += "Shift+";
    }
    const char *n = gdk_keyval_name(key.keyval);
    std::string name = n ? n : "?";
    if (name.size() == 1) {
        name[0] = std::toupper(static_cast<unsigned char>(name[0]));
    }
    return res + name;
}


std::string modifierName(const ModifierMasks &masks, unsigned mod)
{
    ShortcutKey plain;
    plain.keyval = GDK_KEY_a;
    ShortcutKey with = plain;
    with.mods = mod;
    // GTK has no label for a modifier alone: take it from a key
    const std::string full = formatShortcutKey(with, masks, true);
    const std::string key = formatShortcutKey(plain, masks, true);
    std::string res = full;
    if (full.size() > key.size() &&
        full.compare(full.size() - key.size(), key.size(), key) == 0) {
        res = full.substr(0, full.size() - key.size());
    }
    while (!res.empty() && res.back() == '+') {
        res.pop_back();
    }
    return res;
}


std::vector<ShortcutKey> shortcutCandidates(const ModifierMasks &masks,
                                            guint base_keyval,
                                            guint typed_keyval, guint state)
{
    std::vector<ShortcutKey> res;
    const unsigned mods = masks.normalize(state);

    ShortcutKey a;
    a.keyval = gdk_keyval_to_lower(base_keyval ? base_keyval : typed_keyval);
    a.mods = mods;
    res.push_back(a);

    if ((mods & sm::Shift) && typed_keyval && !isCased(typed_keyval)) {
        ShortcutKey b;
        b.keyval = typed_keyval;
        b.mods = mods & ~sm::Shift;
        if (b != a) {
            res.push_back(b);
        }
    }
    return res;
}


ShortcutKey shortcutFromEvent(const ModifierMasks &masks, guint base_keyval,
                              guint typed_keyval, guint state)
{
    const auto cands =
        shortcutCandidates(masks, base_keyval, typed_keyval, state);
    // the second candidate is only there for a Shift-typed non-letter; it is
    // a different symbol from the base key for "plus" or "less", but just the
    // same key without Shift for Shift+F3 or Shift+Up
    if (cands.size() > 1 && cands[1].keyval != cands[0].keyval &&
        !(cands[0].keyval >= GDK_KEY_0 && cands[0].keyval <= GDK_KEY_9)) {
        return cands[1];
    }
    return cands[0];
}


ShortcutTable::ShortcutTable(const ModifierMasks &masks): masks_(masks) {}


void ShortcutTable::warn(const std::string &msg)
{
    warnings_.push_back(msg);
}


int ShortcutTable::index(const std::string &id) const
{
    auto it = by_id_.find(id);
    return it == by_id_.end() ? -1 : it->second;
}


bool ShortcutTable::define(const ShortcutAction &action)
{
    if (action.id.empty() || index(action.id) >= 0) {
        warn("shortcut action defined twice or without id: '" + action.id +
             "'");
        return false;
    }
    Entry e;
    e.action = action;
    for (auto &s : action.defaults) {
        ShortcutKey k;
        std::string err;
        if (!parseShortcutKey(s, masks_, k, &err)) {
            warn("bad default key '" + s + "' for " + action.id + ": " + err);
            return false;
        }
        if (std::find(e.defaults.begin(), e.defaults.end(), k) ==
            e.defaults.end()) {
            e.defaults.push_back(k);
        }
    }
    e.keys = e.defaults;
    by_id_[action.id] = int(entries_.size());
    entries_.push_back(std::move(e));
    return true;
}


bool ShortcutTable::contains(const std::string &id) const
{
    return index(id) >= 0;
}


std::vector<std::string> ShortcutTable::ids() const
{
    std::vector<std::string> res;
    for (auto &e : entries_) {
        res.push_back(e.action.id);
    }
    return res;
}


const ShortcutAction *ShortcutTable::find(const std::string &id) const
{
    int i = index(id);
    return i < 0 ? nullptr : &entries_[i].action;
}


const std::vector<ShortcutKey> &ShortcutTable::keys(const std::string &id) const
{
    static const std::vector<ShortcutKey> none;
    int i = index(id);
    return i < 0 ? none : entries_[i].keys;
}


bool ShortcutTable::isCustomized(const std::string &id) const
{
    int i = index(id);
    return i >= 0 && entries_[i].custom;
}


void ShortcutTable::setKeys(const std::string &id,
                            const std::vector<ShortcutKey> &keys)
{
    int i = index(id);
    if (i < 0) {
        return;
    }
    auto &e = entries_[i];
    e.keys.clear();
    for (auto &k : keys) {
        if (std::find(e.keys.begin(), e.keys.end(), k) == e.keys.end()) {
            e.keys.push_back(k);
        }
    }
    e.custom = e.keys != e.defaults;
}


std::string ShortcutTable::findConflict(const std::string &id,
                                        const ShortcutKey &key) const
{
    int i = index(id);
    if (i < 0) {
        return "";
    }
    for (size_t j = 0; j < entries_.size(); ++j) {
        auto &o = entries_[j];
        if (int(j) != i && o.action.context == entries_[i].action.context &&
            o.action.phase == entries_[i].action.phase &&
            std::find(o.keys.begin(), o.keys.end(), key) != o.keys.end()) {
            return o.action.id;
        }
    }
    return "";
}


void ShortcutTable::applyOverrides(const std::string &json_text, bool reset)
{
    if (reset) {
        for (auto &e : entries_) {
            e.keys = e.defaults;
            e.custom = false;
        }
        mouse_modifier_ = shortcut_mod::Primary;
    }
    // what this layer has to be compared with, to undo what clashes
    std::vector<std::vector<ShortcutKey>> base;
    for (auto &e : entries_) {
        base.push_back(e.keys);
    }

    std::vector<char> buf(json_text.begin(), json_text.end());
    buf.push_back(0);
    cJSON *root = nullptr;
    {
        // cJSON parses numbers with strtod: keep it locale independent
        std::string curloc = setlocale(LC_NUMERIC, nullptr);
        setlocale(LC_NUMERIC, "C");
        cJSON_Minify(buf.data()); // allows comments
        root = cJSON_Parse(buf.data());
        setlocale(LC_NUMERIC, curloc.c_str());
    }
    if (!root) {
        warn("shortcuts: the file is not valid JSON; using the defaults");
        return;
    }

    if (!cJSON_IsObject(root)) {
        warn("shortcuts: expected a JSON object at the top level");
        cJSON_Delete(root);
        return;
    }
    if (cJSON *v = cJSON_GetObjectItemCaseSensitive(root, "version")) {
        if (!cJSON_IsNumber(v) || v->valueint != 1) {
            warn("shortcuts: unsupported \"version\"; trying anyway");
        }
    }
    if (cJSON *m = cJSON_GetObjectItemCaseSensitive(root,
                                                    "mouse_primary_modifier")) {
        const std::string v = cJSON_IsString(m) ? lower(trim(m->valuestring))
                                                : "";
        if (v == "primary") {
            mouse_modifier_ = shortcut_mod::Primary;
        } else if (v == "ctrl" || v == "control") {
            mouse_modifier_ = shortcut_mod::Ctrl;
        } else {
            warn("shortcuts: \"mouse_primary_modifier\" must be \"Primary\" or "
                 "\"Ctrl\"; ignored");
        }
    }
    cJSON *bindings = cJSON_GetObjectItemCaseSensitive(root, "bindings");
    if (!bindings) {
        cJSON_Delete(root); // nothing to customise
        return;
    }
    if (!cJSON_IsObject(bindings)) {
        warn("shortcuts: \"bindings\" must be an object");
        cJSON_Delete(root);
        return;
    }

    for (cJSON *item = bindings->child; item; item = item->next) {
        const std::string id = item->string ? item->string : "";
        int i = index(id);
        if (i < 0) {
            warn("shortcuts: unknown action '" + id + "' ignored");
            continue;
        }
        std::vector<std::string> specs;
        bool ok = true;
        if (cJSON_IsNull(item)) {
            // disabled
        } else if (cJSON_IsString(item)) {
            specs.push_back(item->valuestring);
        } else if (cJSON_IsArray(item)) {
            for (cJSON *s = item->child; s; s = s->next) {
                if (cJSON_IsString(s)) {
                    specs.push_back(s->valuestring);
                } else {
                    ok = false;
                }
            }
        } else {
            ok = false;
        }
        if (!ok) {
            warn("shortcuts: '" + id +
                 "' must be a key string, a list of them, or null; ignored");
            continue;
        }
        std::vector<ShortcutKey> keys;
        for (auto &s : specs) {
            ShortcutKey k;
            std::string err;
            if (!parseShortcutKey(s, masks_, k, &err)) {
                warn("shortcuts: " + id + ": bad key '" + s + "' (" + err +
                     "); ignored");
                ok = false;
                break;
            }
            if (std::find(keys.begin(), keys.end(), k) == keys.end()) {
                keys.push_back(k);
            }
        }
        if (!ok) {
            continue; // keep the defaults of this action
        }
        entries_[i].keys = keys;
        entries_[i].custom = keys != entries_[i].defaults;
    }
    cJSON_Delete(root);

    resolveConflicts(base);
}


void ShortcutTable::resolveConflicts(
    const std::vector<std::vector<ShortcutKey>> &base)
{
    // An action changed by the layer that was just applied, and that now
    // shares a key with another action of the same context, goes back to the
    // keys it had before the layer. Two actions swapping keys are fine, since
    // the check is done on the final state; reverting one may clear or create
    // another clash, hence the loop (each pass strictly reduces the number of
    // changed actions, so it ends).
    const auto changed_by_layer = [&](size_t i) {
        return entries_[i].keys != base[i];
    };
    while (true) {
        bool changed = false;
        for (size_t i = 0; i < entries_.size() && !changed; ++i) {
            for (size_t j = i + 1; j < entries_.size() && !changed; ++j) {
                auto &a = entries_[i];
                auto &b = entries_[j];
                if (a.action.context != b.action.context ||
                    a.action.phase != b.action.phase ||
                    !(changed_by_layer(i) || changed_by_layer(j))) {
                    continue;
                }
                for (auto &k : a.keys) {
                    if (std::find(b.keys.begin(), b.keys.end(), k) ==
                        b.keys.end()) {
                        continue;
                    }
                    // revert the changed one (prefer b: the later one)
                    const size_t v = changed_by_layer(j) ? j : i;
                    Entry &victim = entries_[v];
                    Entry &other = v == j ? a : b;
                    warn("shortcuts: " + victim.action.id + " and " +
                         other.action.id + " would both use " +
                         formatShortcutKey(k, masks_) + "; " +
                         victim.action.id + " keeps its " +
                         (base[v] == victim.defaults ? "default"
                                                     : "previous") +
                         " keys");
                    victim.keys = base[v];
                    victim.custom = victim.keys != victim.defaults;
                    changed = true;
                    break;
                }
            }
        }
        if (!changed) {
            break;
        }
    }
}


bool ShortcutTable::loadFile(const std::string &path, bool reset)
{
    FILE *f = fopen(path.c_str(), "rb");
    if (!f) {
        return false;
    }
    std::string text;
    char tmp[4096];
    size_t n;
    while ((n = fread(tmp, 1, sizeof(tmp), f)) > 0) {
        text.append(tmp, n);
    }
    bool err = ferror(f);
    fclose(f);
    if (err) {
        warn("shortcuts: cannot read " + path);
        return false;
    }
    if (trim(text).empty()) {
        return true; // an empty file customises nothing
    }
    applyOverrides(text, reset);
    return true;
}


std::vector<const ShortcutAction *>
ShortcutTable::lookup(const std::vector<ShortcutKey> &candidates,
                      const std::string &context, ShortcutPhase phase) const
{
    std::vector<const ShortcutAction *> res;
    for (auto &c : candidates) {
        for (auto &e : entries_) {
            if (e.action.phase != phase || e.action.context != context) {
                continue;
            }
            if (std::find(e.keys.begin(), e.keys.end(), c) != e.keys.end() &&
                std::find(res.begin(), res.end(), &e.action) == res.end()) {
                res.push_back(&e.action);
            }
        }
    }
    return res;
}


bool ShortcutTable::usesKeyval(guint keyval, const std::string &context,
                               ShortcutPhase phase) const
{
    keyval = gdk_keyval_to_lower(keyval);
    for (auto &e : entries_) {
        if (e.action.phase != phase || e.action.context != context) {
            continue;
        }
        for (auto &k : e.keys) {
            if (k.keyval == keyval) {
                return true;
            }
        }
    }
    return false;
}


std::vector<std::string> ShortcutTable::conflicts() const
{
    std::vector<std::string> res;
    for (size_t i = 0; i < entries_.size(); ++i) {
        for (size_t j = i + 1; j < entries_.size(); ++j) {
            auto &a = entries_[i];
            auto &b = entries_[j];
            if (a.action.context != b.action.context ||
                a.action.phase != b.action.phase) {
                continue;
            }
            for (auto &k : a.keys) {
                if (std::find(b.keys.begin(), b.keys.end(), k) !=
                    b.keys.end()) {
                    res.push_back(a.action.id + " / " + b.action.id + " [" +
                                  a.action.context + "]: " +
                                  formatShortcutKey(k, masks_));
                }
            }
        }
    }
    return res;
}


std::string ShortcutTable::label(const std::string &id) const
{
    int i = index(id);
    if (i < 0 || entries_[i].keys.empty()) {
        return "";
    }
    return formatShortcutKey(entries_[i].keys[0], masks_, true);
}


namespace {

const char *const FILE_HEADER = R"(// ART keyboard shortcuts: reference of all the actions and their default keys.
//
// This file is generated and overwritten each time ART starts: do NOT edit it.
// It lists the built-in defaults. To change a shortcut, create a file called
// shortcuts.json in this same folder, copy into it the entries you want to
// change, and restart ART.
//
// ART also installs a shortcuts.json of its own in its data folder (for now
// with the Ctrl-based keys of the older versions of ART), which is applied on
// top of these defaults; yours is applied after it and overrides it.
//
// STRUCTURE
//
//   {
//     "version": 1,
//     "mouse_primary_modifier": "Primary",       optional, see below
//     "bindings": {
//       "editor.undo": ["Primary+Z"],            replaces the default keys
//       "editor.redo": ["Primary+Shift+Z", "Primary+Y"],   more than one key
//       "filebrowser.rename": []                 [] (or null) disables it
//     }
//   }
//
// * Each entry is "action id": [list of keys]. The id names what the shortcut
//   does (the comment lines below give the part of ART where it is active),
//   the list is every key that triggers it.
// * Only the actions listed in shortcuts.json change. An action that is listed
//   REPLACES all of its default keys; the others keep theirs.
// * Comments like these (// ... and /* ... */) are allowed in the file.
// * Two actions of the same part of ART cannot share a key: the one that
//   clashes is ignored and keeps its default. A problem with an entry (unknown
//   action, unreadable key) is reported on the standard error and the entry is
//   ignored; ART always starts. Run ART with the environment variable
//   ART_SHORTCUTS_DEBUG=1 to also see which action each key press triggers.
//
// MOUSE MODIFIER
//
//   "mouse_primary_modifier": "Primary" or "Ctrl"
//
// The mouse actions that use the usual command key (Ctrl-click to reset a
// slider, Ctrl-click for a fast export, Ctrl-scroll in the masks, ...) use the
// key that is chosen here: "Primary" (the default) is Ctrl on Linux and Windows
// and Cmd on macOS, "Ctrl" is always the physical Control key. The two differ
// only on macOS. Tooltips follow the choice.
//
// KEY SYNTAX
//
//   [Primary+][Ctrl+][Alt+][Shift+]<key>        e.g. "Primary+Shift+S", "F3"
//
// * <key> is a GDK key name: a letter or digit ("z", "5"), or F1..F12, Delete,
//   Return, space, Left, Up, Page_Down, KP_Add, bracketleft, ... Symbols that
//   are hard to type are spelled out: plus, minus, equal, less, greater, comma,
//   period, slash, asterisk, underscore.
// * Primary is the usual command key of the system: Ctrl on Linux and Windows,
//   Cmd on macOS. Use it (as all the defaults do) and the same file works on
//   every system. Ctrl means the physical Control key: the same as Primary on
//   Linux and Windows, a different key on macOS.
// * Alt is Option on macOS. Modifier names are not case sensitive, and the
//   modifiers must match exactly ("Primary+S" does not fire for
//   "Primary+Shift+S"). Caps Lock is ignored.
// * Keys that need Shift on some keyboards (plus, less, ...) match however
//   the layout types them. For letters and digits write the Shift explicitly:
//   "Shift+R".
)";

} // namespace


std::string ShortcutTable::dumpJson(bool defaults_only, bool header) const
{
    std::string res = header ? std::string(FILE_HEADER) + "\n" : "";
    res += "{\n  \"version\": 1,\n\n";
    res += "  // the modifier of the mouse actions (Ctrl-click ...): \"Primary\" or "
           "\"Ctrl\"\n";
    res += std::string("  \"mouse_primary_modifier\": \"") +
           (!defaults_only && mouse_modifier_ == shortcut_mod::Ctrl
                ? "Ctrl"
                : "Primary") +
           "\",\n\n";
    res += "  \"bindings\": {\n";
    std::string ctx;
    for (size_t i = 0; i < entries_.size(); ++i) {
        auto &e = entries_[i];
        if (e.action.context != ctx) {
            ctx = e.action.context;
            res += "\n    // " + ctx + "\n";
        }
        res += "    \"" + e.action.id + "\": [";
        auto &ks = defaults_only ? e.defaults : e.keys;
        for (size_t j = 0; j < ks.size(); ++j) {
            res += (j ? ", \"" : "\"") + formatShortcutKey(ks[j], masks_) +
                   "\"";
        }
        res += "]";
        res += i + 1 < entries_.size() ? ",\n" : "\n";
    }
    res += "  }\n}\n";
    return res;
}


namespace {

const char *const OVERRIDES_HEADER =
    R"(// ART keyboard shortcuts, written by the shortcuts editor of the Preferences.
//
// Only the actions whose keys differ from the standard ones are listed; an
// action listed here replaces all of its standard keys, and [] disables it.
// The file can be edited by hand: the syntax, and all the actions with their
// standard keys, are described in shortcuts_reference.json in this folder.
// Note that saving from the Preferences rewrites this file (comments are not
// kept; the previous version is saved once as shortcuts.json.bak).
)";

} // namespace


std::string ShortcutTable::dumpOverrides(const ShortcutTable &baseline) const
{
    std::string res = std::string(OVERRIDES_HEADER) + "\n{\n  \"version\": 1";
    if (mouse_modifier_ != baseline.mouse_modifier_) {
        res += std::string(",\n\n  \"mouse_primary_modifier\": \"") +
               (mouse_modifier_ == sm::Ctrl ? "Ctrl" : "Primary") + "\"";
    }
    res += ",\n\n  \"bindings\": {";
    std::string ctx;
    bool first = true;
    for (auto &e : entries_) {
        if (e.keys == baseline.keys(e.action.id)) {
            continue;
        }
        if (!first) {
            res += ",";
        }
        if (e.action.context != ctx) {
            ctx = e.action.context;
            res += std::string(first ? "\n" : "\n\n") + "    // " + ctx + "\n";
        } else {
            res += "\n";
        }
        first = false;
        res += "    \"" + e.action.id + "\": [";
        for (size_t j = 0; j < e.keys.size(); ++j) {
            res += (j ? ", \"" : "\"") +
                   formatShortcutKey(e.keys[j], masks_) + "\"";
        }
        res += "]";
    }
    res += first ? "}\n}\n" : "\n  }\n}\n";
    return res;
}

} } // namespace art::gui
