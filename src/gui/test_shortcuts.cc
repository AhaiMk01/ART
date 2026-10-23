/** -*- C++ -*-
 *
 *  This file is part of ART.
 *
 *  Copyright (c) 2026 Alberto Griggio <alberto.griggio@gmail.com>
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

// Unit tests for the shortcut table (no display needed): ctest -R shortcuts

#include "../utils/multilangmgr.h"
#include "shortcutdefs.h"
#include "shortcuttable.h"
#include "systemshortcuts.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <glib/gstdio.h>
#include <glibmm.h>
#include <gtk/gtk.h>
#include <iostream>

using namespace art::gui;
namespace sm = art::gui::shortcut_mod;

// a Mac keyboard with Cmd chosen as the Primary modifier (the default is Ctrl)
static ModifierMasks macCmd()
{
    return ModifierMasks::mac_like().withPrimary(true);
}

namespace {

int failures = 0;

#define CHECK(cond)                                                           \
    do {                                                                      \
        if (!(cond)) {                                                        \
            ++failures;                                                       \
            std::cerr << __FILE__ << ":" << __LINE__ << ": CHECK failed: "    \
                      << #cond << std::endl;                                  \
        }                                                                     \
    } while (0)

ShortcutKey key(const ModifierMasks &m, const char *spec)
{
    ShortcutKey k;
    std::string err;
    if (!parseShortcutKey(spec, m, k, &err)) {
        ++failures;
        std::cerr << "cannot parse '" << spec << "': " << err << std::endl;
    }
    return k;
}

// what GTK itself prints for the same key (menus use that)
std::string gtkLabel(const ModifierMasks &m, const char *spec)
{
    guint kv;
    GdkModifierType mods;
    shortcutToAccelerator(key(m, spec), m, kv, mods);
    gchar *l = gtk_accelerator_get_label(kv, mods);
    std::string res = l ? l : "";
    g_free(l);
    return res;
}

bool bad(const ModifierMasks &m, const char *spec)
{
    ShortcutKey k;
    return !parseShortcutKey(spec, m, k);
}

// a table with a few made-up actions
ShortcutTable small(const ModifierMasks &m)
{
    ShortcutTable t(m);
    t.define({"a.save", "ctx", {"Primary+s"}});
    t.define({"a.undo", "ctx", {"Primary+z"}});
    t.define({"a.redo", "ctx", {"Primary+Shift+z", "Primary+y"}});
    t.define({"a.zoom", "ctx", {"plus", "equal"}});
    t.define({"b.save", "other", {"Primary+s"}}); // same key, other context
    t.define({"c.pre", "ctx", {"F2"}, ShortcutPhase::Before});
    return t;
}

void testParse()
{
    for (auto m : {ModifierMasks::linux_like(), macCmd()}) {
        ShortcutKey k = key(m, "Primary+Shift+Z");
        CHECK(k.keyval == GDK_KEY_z);
        CHECK(k.mods == (sm::Primary | sm::Shift));
        CHECK(formatShortcutKey(k, m) == "Primary+Shift+Z");
        CHECK(key(m, "primary+shift+z") == k);
        CHECK(key(m, " Shift + Primary + z ") == k);
        CHECK(formatShortcutKey(key(m, "F3"), m) == "F3");
        CHECK(formatShortcutKey(key(m, "plus"), m) == "plus");
        CHECK(key(m, "KP_Add").keyval == GDK_KEY_KP_Add);
        // round trip of everything we can spell
        for (auto s : {"Alt+u", "Primary+Alt+Shift+Delete", "bracketleft",
                       "9", "Primary+KP_Enter"}) {
            CHECK(key(m, formatShortcutKey(key(m, s), m).c_str()) ==
                  key(m, s));
        }
        CHECK(bad(m, ""));
        CHECK(bad(m, "Primary+"));
        CHECK(bad(m, "+"));
        CHECK(bad(m, "Primary++s"));
        CHECK(bad(m, "Hyper+s"));
        CHECK(bad(m, "Shift+Shift+s"));
        CHECK(bad(m, "nosuchkey"));
    }

    // Ctrl means Primary where they are the same key, and not on a Mac
    auto lin = ModifierMasks::linux_like();
    auto mac = macCmd();
    CHECK(key(lin, "Ctrl+s") == key(lin, "Primary+s"));
    CHECK(key(mac, "Ctrl+s") != key(mac, "Primary+s"));
    CHECK(key(mac, "Ctrl+s").mods == sm::Ctrl);
    CHECK(formatShortcutKey(key(mac, "Ctrl+s"), mac) == "Ctrl+S");
}

void testNormalize()
{
    auto lin = ModifierMasks::linux_like();
    auto mac = macCmd();
    const guint lock = GDK_LOCK_MASK | GDK_BUTTON1_MASK;

    CHECK(lin.normalize(0) == 0);
    CHECK(lin.normalize(GDK_CONTROL_MASK) == sm::Primary);
    CHECK(lin.normalize(GDK_CONTROL_MASK | lock) == sm::Primary);
    CHECK(lin.normalize(GDK_SHIFT_MASK | GDK_MOD1_MASK) ==
          (sm::Shift | sm::Alt));
    // NumLock is MOD2 on X11: must not look like a modifier
    CHECK(lin.normalize(GDK_MOD2_MASK) == 0);
    // AltGr (MOD5) alone is not a modifier either
    CHECK(lin.normalize(GDK_MOD5_MASK) == 0);

    CHECK(mac.normalize(GDK_MOD2_MASK) == sm::Primary);
    CHECK(mac.normalize(GDK_CONTROL_MASK) == sm::Ctrl);
    CHECK(mac.normalize(GDK_MOD2_MASK | GDK_CONTROL_MASK) ==
          (sm::Primary | sm::Ctrl));

    // a platform that reports AltGr as Ctrl+Alt+its own bit
    ModifierMasks win = lin;
    win.altgr = GDK_MOD2_MASK;
    CHECK(win.normalize(GDK_CONTROL_MASK | GDK_MOD1_MASK | GDK_MOD2_MASK) ==
          0);
    CHECK(win.normalize(GDK_CONTROL_MASK | GDK_MOD1_MASK) ==
          (sm::Primary | sm::Alt));
}

void testCandidates()
{
    auto lin = ModifierMasks::linux_like();
    // plain 'z'
    auto c = shortcutCandidates(lin, GDK_KEY_z, GDK_KEY_z, 0);
    CHECK(c.size() == 1 && c[0] == key(lin, "z"));
    // Shift+z types 'Z' but is Shift+z
    c = shortcutCandidates(lin, GDK_KEY_z, GDK_KEY_Z, GDK_SHIFT_MASK);
    CHECK(c.size() == 1 && c[0] == key(lin, "Shift+z"));
    // Caps Lock is ignored
    c = shortcutCandidates(lin, GDK_KEY_z, GDK_KEY_Z, GDK_LOCK_MASK);
    CHECK(c.size() == 1 && c[0] == key(lin, "z"));
    // US layout: '+' is Shift+equal: either spelling matches
    c = shortcutCandidates(lin, GDK_KEY_equal, GDK_KEY_plus, GDK_SHIFT_MASK);
    CHECK(c.size() == 2);
    CHECK(c[0] == key(lin, "Shift+equal"));
    CHECK(c[1] == key(lin, "plus"));
    // with Ctrl
    c = shortcutCandidates(lin, GDK_KEY_equal, GDK_KEY_plus,
                           GDK_SHIFT_MASK | GDK_CONTROL_MASK);
    CHECK(c.size() == 2 && c[1] == key(lin, "Primary+plus"));
    // Shift+1 types '!' on a US layout: the digit with Shift matches, and
    // so does the symbol
    c = shortcutCandidates(lin, GDK_KEY_1, GDK_KEY_exclam, GDK_SHIFT_MASK);
    CHECK(c[0] == key(lin, "Shift+1"));
    // a layout with '+' on its own key: plain match
    c = shortcutCandidates(lin, GDK_KEY_plus, GDK_KEY_plus, 0);
    CHECK(c.size() == 1 && c[0] == key(lin, "plus"));
}

void testOverrides()
{
    auto lin = ModifierMasks::linux_like();
    {
        ShortcutTable t = small(lin);
        CHECK(t.warnings().empty());
        CHECK(t.keys("a.save").size() == 1);
        CHECK(t.label("a.save") == gtkLabel(lin, "Primary+s"));
        CHECK(t.conflicts().empty());

        t.applyOverrides(R"({ "version": 1, "bindings": {
            // remap, replacing the defaults
            "a.undo": ["Primary+Alt+z"],
            "a.redo": "Primary+Shift+r",   /* single string */
            "a.zoom": [],                   // disabled
            "c.pre": null                   // also disabled
        }})");
        CHECK(t.warnings().empty());
        CHECK(t.keys("a.undo").size() == 1 &&
              t.keys("a.undo")[0] == key(lin, "Primary+Alt+z"));
        CHECK(t.keys("a.redo").size() == 1);
        CHECK(t.keys("a.zoom").empty());
        CHECK(t.keys("c.pre").empty());
        CHECK(t.label("a.zoom").empty());
        CHECK(t.isCustomized("a.undo"));
        CHECK(!t.isCustomized("a.save"));
        CHECK(t.keys("a.save").size() == 1); // untouched

        // applying again starts from the defaults
        t.applyOverrides("{}");
        CHECK(!t.isCustomized("a.undo"));
        CHECK(t.keys("a.zoom").size() == 2);
    }
    {
        // unknown id, bad key, bad types: each is a warning, the rest applies
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {
            "no.such": ["F5"],
            "a.undo": ["Primary+nosuchkey"],
            "a.zoom": 5,
            "a.redo": ["Primary+r", 7],
            "a.save": ["Primary+w"]
        }})");
        CHECK(t.warnings().size() == 4);
        CHECK(t.keys("a.undo").size() == 1 &&
              t.keys("a.undo")[0] == key(lin, "Primary+z"));
        CHECK(t.keys("a.zoom").size() == 2);
        CHECK(t.keys("a.redo").size() == 2);
        CHECK(t.keys("a.save")[0] == key(lin, "Primary+w"));
    }
    {
        // same context: the customised action goes back to its default
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {"a.undo": ["Primary+s"]}})");
        CHECK(t.warnings().size() == 1);
        CHECK(t.keys("a.undo")[0] == key(lin, "Primary+z"));
        CHECK(!t.isCustomized("a.undo"));
        CHECK(t.conflicts().empty());
    }
    {
        // other context or other phase: no clash
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {"b.save": ["Primary+z"],
                                          "c.pre": ["Primary+s"]}})");
        CHECK(t.warnings().empty());
    }
    {
        // swapping two keys is fine
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {"a.save": ["Primary+z"],
                                          "a.undo": ["Primary+s"]}})");
        CHECK(t.warnings().empty());
        CHECK(t.keys("a.save")[0] == key(lin, "Primary+z"));
        CHECK(t.keys("a.undo")[0] == key(lin, "Primary+s"));
    }
    {
        // two customised actions fighting for one key: one is reverted
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {"a.save": ["F9"],
                                          "a.undo": ["F9"]}})");
        CHECK(t.warnings().size() == 1);
        CHECK(t.conflicts().empty());
        CHECK(t.keys("a.save")[0] == key(lin, "F9"));
        CHECK(t.keys("a.undo")[0] == key(lin, "Primary+z"));
    }
    for (auto bad_json : {"", "{", "not json", "[1,2]", "{\"bindings\": 3}",
                          "{\"bindings\": [\"a.undo\"]}"}) {
        ShortcutTable t = small(lin);
        t.applyOverrides(bad_json);
        CHECK(t.keys("a.undo")[0] == key(lin, "Primary+z"));
        CHECK(t.keys("a.zoom").size() == 2);
        CHECK(!t.isCustomized("a.undo"));
        CHECK(!t.warnings().empty() || std::string(bad_json) == "" );
    }
    {
        // missing/empty file: not an error
        ShortcutTable t = small(lin);
        CHECK(!t.loadFile("/nonexistent/shortcuts.json"));
        CHECK(t.warnings().empty());
    }
}

void testLayers()
{
    auto lin = ModifierMasks::linux_like();
    // system layer, then the user's on top
    {
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {"a.save": ["F9"], "a.zoom": []}})",
                         false);
        CHECK(t.warnings().empty());
        CHECK(t.keys("a.save")[0] == key(lin, "F9"));
        t.applyOverrides(R"({"bindings": {"a.undo": ["F8"]}})", false);
        // the first layer is still there, the second one added to it
        CHECK(t.keys("a.save")[0] == key(lin, "F9"));
        CHECK(t.keys("a.zoom").empty());
        CHECK(t.keys("a.undo")[0] == key(lin, "F8"));
        // and it can override the first
        t.applyOverrides(R"({"bindings": {"a.save": ["F7"]}})", false);
        CHECK(t.keys("a.save")[0] == key(lin, "F7"));
        CHECK(t.keys("a.zoom").empty());
        CHECK(t.warnings().empty());
        // a reset forgets the layers
        t.applyOverrides("{}");
        CHECK(t.keys("a.save")[0] == key(lin, "Primary+s"));
        CHECK(t.keys("a.zoom").size() == 2);
    }
    // a clash with what an earlier layer did: back to what it had before
    {
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {"a.save": ["F9"]}})", false);
        t.applyOverrides(R"({"bindings": {"a.undo": ["F9"]}})", false);
        CHECK(t.warnings().size() == 1);
        CHECK(t.keys("a.save")[0] == key(lin, "F9")); // the older layer wins
        CHECK(t.keys("a.undo")[0] == key(lin, "Primary+z"));
        CHECK(t.conflicts().empty());
    }
    // an action that is changed back to its default keys is not customised
    {
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {"a.save": ["F9"]}})", false);
        CHECK(t.isCustomized("a.save"));
        t.applyOverrides(R"({"bindings": {"a.save": ["Primary+s"]}})", false);
        CHECK(!t.isCustomized("a.save"));
    }
    // a missing file leaves the layers below as they are
    {
        ShortcutTable t = small(lin);
        t.applyOverrides(R"({"bindings": {"a.save": ["F9"]}})", false);
        CHECK(!t.loadFile("/nonexistent/shortcuts.json", false));
        CHECK(t.keys("a.save")[0] == key(lin, "F9"));
    }
}

void testMouseModifier()
{
    auto lin = ModifierMasks::linux_like();
    auto mac = macCmd();

    // by default Ctrl, whatever Primary is
    ShortcutTable t = small(mac);
    CHECK(!t.mouseIsOsKey());
    CHECK(t.mousePrimaryMask() == GDK_CONTROL_MASK);
    CHECK(t.mouseModifierName() == modifierName(mac, sm::Ctrl));
    t.applyOverrides(R"({"mouse_primary_modifier": "Cmd"})");
    CHECK(t.warnings().empty());
    CHECK(t.mouseIsOsKey());
    CHECK(t.mousePrimaryMask() == GDK_MOD2_MASK);
    CHECK(t.mouseModifierName() == modifierName(mac, sm::Primary));
    // the keys are not affected
    CHECK(t.keys("a.save")[0] == key(mac, "Primary+s"));
    // and it does not follow Primary
    t.applyOverrides(R"({"primary_modifier": "Cmd"})");
    CHECK(t.primaryIsOsKey() && !t.mouseIsOsKey());

    // not case sensitive; other names of the keys are accepted too
    for (auto v : {"\"ctrl\"", "\" Control \""}) {
        t.applyOverrides(std::string("{\"mouse_primary_modifier\": ") + v + "}");
        CHECK(!t.mouseIsOsKey());
    }
    for (auto v : {"\"cmd\"", "\"Command\"", "\"super\"", "\"Win\"", "\"META\""}) {
        t.applyOverrides(std::string("{\"mouse_primary_modifier\": ") + v + "}");
        CHECK(t.mouseIsOsKey());
    }

    // a reset puts it back, a layer without it leaves it as it is
    t.applyOverrides("{}");
    CHECK(!t.mouseIsOsKey());
    t.applyOverrides(R"({"mouse_primary_modifier": "Cmd"})");
    t.applyOverrides(R"({"bindings": {"a.undo": ["F8"]}})", false);
    CHECK(t.mouseIsOsKey());
    // and a later layer overrides it
    t.applyOverrides(R"({"mouse_primary_modifier": "Ctrl"})", false);
    CHECK(!t.mouseIsOsKey());
    CHECK(t.warnings().empty());

    // anything else: a warning, and it stays as it was
    for (auto bad_value : {"\"Alt\"", "\"Primary\"", "5", "null", "[]", "\"\""}) {
        t.applyOverrides(R"({"mouse_primary_modifier": "Cmd"})");
        t.clearWarnings();
        t.applyOverrides(std::string("{\"mouse_primary_modifier\": ") +
                             bad_value + "}",
                         false);
        CHECK(t.warnings().size() == 1);
        CHECK(t.mouseIsOsKey());
    }
    // an invalid value does not stop the bindings of the same file
    t.clearWarnings();
    t.applyOverrides(R"({"mouse_primary_modifier": "Alt",
                          "bindings": {"a.undo": ["F8"]}})");
    CHECK(t.warnings().size() == 1);
    CHECK(t.keys("a.undo")[0] == key(mac, "F8"));

    // the OS key of the other platforms is the Windows key
    ShortcutTable l = small(lin);
    l.applyOverrides(R"({"mouse_primary_modifier": "Super"})");
    CHECK(l.mousePrimaryMask() == GDK_SUPER_MASK);

    // the dump (which the reference file is made of) has it, and loads back
    ShortcutTable d = small(mac);
    CHECK(d.dumpJson(true).find("\"mouse_primary_modifier\": \"Ctrl\"") !=
          std::string::npos);
    d.applyOverrides(R"({"mouse_primary_modifier": "Cmd"})");
    CHECK(d.dumpJson().find("\"mouse_primary_modifier\": \"Cmd\"") !=
          std::string::npos);
    CHECK(d.dumpJson(true).find("\"mouse_primary_modifier\": \"Ctrl\"") !=
          std::string::npos);
    ShortcutTable e = small(mac);
    e.applyOverrides(d.dumpJson());
    CHECK(e.warnings().empty());
    CHECK(e.mouseIsOsKey());
    CHECK(e.dumpJson(true, true).find("PRIMARY AND MOUSE MODIFIERS") !=
          std::string::npos);
}

// the modifier that "Primary" stands for: Ctrl, or the OS key
void testPrimaryModifier()
{
    for (auto m : {ModifierMasks::linux_like(), ModifierMasks::mac_like()}) {
        const bool mac = m.os_key == GDK_MOD2_MASK;
        const char *os = mac ? "Cmd" : "Super";

        // Ctrl by default
        ShortcutTable t = small(m);
        CHECK(!t.primaryIsOsKey());
        CHECK(t.masks().primary == GDK_CONTROL_MASK);
        CHECK(t.label("a.save") == gtkLabel(m, "Primary+s"));
        CHECK(t.label("a.save") == gtkLabel(m, "Ctrl+s")); // the real Control key
        // a key pressed with the OS key is not the bare key (nor a shortcut)
        CHECK(m.normalize(m.os_key) == sm::Other);
        CHECK(m.normalize(m.os_key | GDK_CONTROL_MASK) ==
              (sm::Primary | sm::Other));
        CHECK(m.normalize(GDK_CONTROL_MASK) == sm::Primary);

        // switched to the OS key by the file
        t.applyOverrides(std::string("{\"primary_modifier\": \"") + os + "\"}");
        CHECK(t.warnings().empty());
        CHECK(t.primaryIsOsKey());
        CHECK(t.masks().primary == m.os_key);
        CHECK(t.keys("a.save")[0] == key(t.masks(), "Primary+s"));
        CHECK(!t.isCustomized("a.save"));
        CHECK(t.label("a.save") != gtkLabel(m, "Primary+s"));
        CHECK(t.masks().normalize(m.os_key) == sm::Primary);
        CHECK(t.masks().normalize(GDK_CONTROL_MASK) == sm::Ctrl);
        // Ctrl is a key of its own now
        t.applyOverrides(std::string("{\"primary_modifier\": \"") + os +
                         "\", \"bindings\": {\"a.undo\": [\"Ctrl+z\"]}}");
        CHECK(t.keys("a.undo")[0].mods == sm::Ctrl);
        // ... and is Primary again when Primary goes back to Ctrl: the
        // table keeps it (that is what the editor's radio button does)
        t.setPrimaryIsOsKey(false);
        CHECK(!t.primaryIsOsKey());
        CHECK(t.keys("a.undo")[0].mods == sm::Primary);
        CHECK(t.isCustomized("a.undo") == false);
        t.setPrimaryIsOsKey(true);
        CHECK(t.masks().primary == m.os_key);

        // a reset puts it back; a layer without it leaves it; wrong values
        t.applyOverrides("{}");
        CHECK(!t.primaryIsOsKey());
        t.applyOverrides(std::string("{\"primary_modifier\": \"") + os + "\"}");
        t.applyOverrides(R"({"bindings": {"a.undo": ["F8"]}})", false);
        CHECK(t.primaryIsOsKey());
        t.clearWarnings();
        t.applyOverrides(R"({"primary_modifier": "Alt"})", false);
        CHECK(t.warnings().size() == 1 && t.primaryIsOsKey());
        t.applyOverrides(R"({"primary_modifier": "ctrl"})", false);
        CHECK(!t.primaryIsOsKey());

        // dump and layers
        ShortcutTable base = small(m);
        ShortcutTable u = base;
        CHECK(u.dumpOverrides(base).find("primary_modifier") == std::string::npos);
        u.setPrimaryIsOsKey(true);
        const std::string json = u.dumpOverrides(base);
        CHECK(json.find(std::string("\"primary_modifier\": \"") + os + "\"") !=
              std::string::npos);
        ShortcutTable again = base;
        again.applyOverrides(json, false);
        CHECK(again.primaryIsOsKey());
        CHECK(again.warnings().empty());
        CHECK(base.dumpJson(true).find("\"primary_modifier\": \"Ctrl\"") !=
              std::string::npos);
        u.setPrimaryIsOsKey(false);
        CHECK(u.dumpOverrides(base).find("primary_modifier") == std::string::npos);
    }

    // the defaults are the ones of the released ART: Ctrl (physical) everywhere
    for (auto m : {ModifierMasks::linux_like(), ModifierMasks::mac_like()}) {
        ShortcutTable t(m);
        defineDefaultShortcuts(t);
        CHECK(t.keys("editor.undo")[0].mods == sm::Primary);
        CHECK(t.masks().primary == GDK_CONTROL_MASK);
        CHECK(t.mousePrimaryMask() == GDK_CONTROL_MASK);
        CHECK(t.label("window.quit") == gtkLabel(m, "Primary+q"));
        CHECK(t.label("editor.save") == gtkLabel(m, "Ctrl+s"));
    }
}

void testLookup()
{
    auto lin = ModifierMasks::linux_like();
    ShortcutTable t = small(lin);
    auto find = [&](const char *spec, const char *ctx,
                    ShortcutPhase ph = ShortcutPhase::After) {
        return t.lookup({key(lin, spec)}, ctx, ph);
    };
    CHECK(find("Primary+s", "ctx").size() == 1);
    CHECK(find("Primary+s", "ctx")[0]->id == "a.save");
    CHECK(find("Primary+s", "other")[0]->id == "b.save");
    CHECK(find("Primary+s", "nowhere").empty());
    CHECK(find("s", "ctx").empty());
    CHECK(find("F2", "ctx").empty());
    CHECK(find("F2", "ctx", ShortcutPhase::Before).size() == 1);
    // candidate order is the priority order
    auto r = t.lookup({key(lin, "Primary+y"), key(lin, "Primary+s")}, "ctx",
                      ShortcutPhase::After);
    CHECK(r.size() == 2 && r[0]->id == "a.redo" && r[1]->id == "a.save");
    // key releases: the key, whatever the modifiers
    CHECK(t.usesKeyval(GDK_KEY_s, "ctx", ShortcutPhase::After));
    CHECK(t.usesKeyval(GDK_KEY_S, "ctx", ShortcutPhase::After));
    CHECK(!t.usesKeyval(GDK_KEY_s, "nowhere", ShortcutPhase::After));
    CHECK(!t.usesKeyval(GDK_KEY_s, "ctx", ShortcutPhase::Before));
    CHECK(t.usesKeyval(GDK_KEY_F2, "ctx", ShortcutPhase::Before));
    CHECK(!t.usesKeyval(GDK_KEY_q, "ctx", ShortcutPhase::After));
    // a disabled action is not found
    t.applyOverrides(R"({"bindings": {"a.save": []}})");
    CHECK(find("Primary+s", "ctx").empty());
    CHECK(!t.usesKeyval(GDK_KEY_s, "ctx", ShortcutPhase::After));
}

void testDefaults()
{
    for (auto m : {ModifierMasks::linux_like(), macCmd()}) {
        ShortcutTable t(m);
        defineDefaultShortcuts(t);
        for (auto &w : t.warnings()) {
            std::cerr << "default table: " << w << std::endl;
        }
        CHECK(t.warnings().empty());
        CHECK(t.ids().size() > 150);
        auto c = t.conflicts();
        for (auto &s : c) {
            std::cerr << "conflict in the default table: " << s << std::endl;
        }
        CHECK(c.empty());

        // a few well-known ones
        CHECK(t.contains("editor.undo"));
        CHECK(t.keys("editor.undo")[0] == key(m, "Primary+z"));
        CHECK(t.label("editor.save") == gtkLabel(m, "Primary+s"));
        CHECK(t.keys("tool.whitebalance.tint").empty());

        // the file written by dumpJson loads back to exactly the same table
        std::string dump = t.dumpJson();
        // the reference file has a comment on top; it must not matter
        const std::string reference = t.dumpJson(true, true);
        CHECK(reference.compare(0, 2, "//") == 0);
        CHECK(reference.size() > dump.size());
        CHECK(reference.find("KEY SYNTAX") != std::string::npos);
        CHECK(reference.find("\"version\": 1") != std::string::npos);
        {
            ShortcutTable r(m);
            defineDefaultShortcuts(r);
            r.applyOverrides(reference);
            CHECK(r.warnings().empty());
            for (auto &id : t.ids()) {
                CHECK(r.keys(id) == t.keys(id));
                CHECK(!r.isCustomized(id));
            }
        }
        ShortcutTable u(m);
        defineDefaultShortcuts(u);
        u.applyOverrides(dump);
        CHECK(u.warnings().empty());
        for (auto &id : t.ids()) {
            CHECK(u.keys(id) == t.keys(id));
            CHECK(!u.isCustomized(id));
        }
    }

    // a file written on Linux means the same on a Mac
    ShortcutTable lin(ModifierMasks::linux_like());
    ShortcutTable mac(macCmd());
    defineDefaultShortcuts(lin);
    defineDefaultShortcuts(mac);
    lin.applyOverrides(lin.dumpJson());
    mac.applyOverrides(lin.dumpJson());
    CHECK(mac.warnings().empty());
    CHECK(mac.keys("editor.undo")[0] == key(macCmd(), "Primary+z"));
    CHECK(mac.keys("editor.undo")[0].mods == sm::Primary);
}

// what the user sees in tooltips must be what GTK shows in menus
void testDisplay()
{
    auto lin = ModifierMasks::linux_like();
    auto mac = macCmd();
    auto d = [](const ModifierMasks &m, const char *spec) {
        return formatShortcutKey(key(m, spec), m, true);
    };
    for (auto m : {lin, mac}) {
        for (auto spec : {"Primary+s", "Primary+Shift+Delete", "Alt+s", "F2",
                          "plus", "less", "Primary+Return", "bracketleft",
                          "Shift+KP_Add", "Primary+Alt+Page_Up", "space"}) {
            CHECK(!d(m, spec).empty());
            CHECK(d(m, spec) == gtkLabel(m, spec));
        }
    }
    // Cmd is spelled META for GTK: with MOD2 as well it prints "Mod2"
    guint kv;
    GdkModifierType mods;
    shortcutToAccelerator(key(mac, "Primary+s"), mac, kv, mods);
    CHECK((mods & GDK_META_MASK) && !(mods & GDK_MOD2_MASK));
    CHECK(d(mac, "Primary+s").find("Mod2") == std::string::npos);
    shortcutToAccelerator(key(mac, "Ctrl+s"), mac, kv, mods);
    CHECK((mods & GDK_CONTROL_MASK) && !(mods & GDK_META_MASK));
    shortcutToAccelerator(key(lin, "Primary+s"), lin, kv, mods);
    CHECK(mods == GDK_CONTROL_MASK);
    // the modifier alone, for "%mouse_primary%-click"
    for (auto m : {lin, mac}) {
        for (auto mod : {sm::Primary, sm::Ctrl}) {
            const std::string n = modifierName(m, mod);
            CHECK(!n.empty());
            CHECK(n.back() != '+');
            ShortcutKey k = key(m, "s");
            k.mods = mod;
            CHECK(formatShortcutKey(k, m, true).compare(0, n.size(), n) == 0);
        }
    }
    // where Primary is not Ctrl they are not the same modifier
    CHECK(modifierName(mac, sm::Primary) != modifierName(mac, sm::Ctrl));
    CHECK(modifierName(lin, sm::Primary) == modifierName(lin, sm::Ctrl));
    // the spelling used in shortcuts.json is not affected
    CHECK(formatShortcutKey(key(lin, "plus"), lin) == "plus");
    CHECK(formatShortcutKey(key(lin, "Primary+Return"), lin) ==
          "Primary+Return");
    CHECK(formatShortcutKey(key(mac, "Primary+Ctrl+Alt+Shift+F5"), mac) ==
          "Primary+Ctrl+Alt+Shift+F5");

    // handy when looking at what the user gets
    if (getenv("SHORTCUTS_TEST_LABELS")) {
#ifdef __APPLE__
        ShortcutTable t(macCmd());
#else
        ShortcutTable t(ModifierMasks::linux_like());
#endif
        defineDefaultShortcuts(t);
        for (auto &id : t.ids()) {
            std::cout << id << "\t" << t.label(id) << std::endl;
        }
    }
}

// "%shortcut(id)%" and "%mouse_primary%" in translated strings
void testPlaceholders()
{
    using art::utils::langMgr;
    const std::string path =
        std::string(g_get_tmp_dir()) + "/art-shortcuts-test-lang";
    {
        FILE *f = fopen(path.c_str(), "w");
        CHECK(f != nullptr);
        if (!f) {
            return;
        }
        fputs("PLAIN;no placeholders here\n"
              "ONE;Save: <b>%shortcut(a.save)%</b>.\n"
              "TWO;%shortcut(a.undo)% and %shortcut(a.save)%, then %shortcut(a.zoom)%\n"
              "PRIM;<b>%mouse_primary%</b>-click, %mouse_primary%+drag\n"
              "BAD;%shortcut(no.such)% %shortcut(a.undo\n"
              "DISABLED;[%shortcut(a.off)%]\n",
              f);
        fclose(f);
    }
    langMgr.load("default", {path});

    // nothing to expand with yet
    CHECK(langMgr.getStr("ONE") == "Save: <b>%shortcut(a.save)%</b>.");

    ShortcutTable t(ModifierMasks::linux_like());
    t.define({"a.save", "ctx", {"Primary+s"}});
    t.define({"a.undo", "ctx", {"Primary+z"}});
    t.define({"a.zoom", "ctx", {"less"}}); // needs escaping in markup
    t.define({"a.off", "ctx", {}});
    langMgr.setShortcutLabeler([&t](const std::string &id) -> Glib::ustring {
        if (!t.contains(id)) {
            return "?";
        }
        auto l = t.label(id);
        return l.empty() ? Glib::ustring("-") : Glib::Markup::escape_text(l);
    });
    langMgr.setMousePrimaryModifierName(t.mouseModifierName());

    const std::string save = gtkLabel(ModifierMasks::linux_like(), "Primary+s");
    const std::string undo = gtkLabel(ModifierMasks::linux_like(), "Primary+z");
    const std::string prim = ShortcutTable(ModifierMasks::linux_like()).mouseModifierName();
    CHECK(langMgr.getStr("PLAIN") == "no placeholders here");
    CHECK(langMgr.getStr("ONE") == "Save: <b>" + save + "</b>.");
    CHECK(langMgr.getStr("TWO") == undo + " and " + save + ", then &lt;");
    CHECK(langMgr.getStr("PRIM") == "<b>" + prim + "</b>-click, " + prim + "+drag");
    CHECK(langMgr.getStr("BAD") == "? %shortcut(a.undo");
    CHECK(langMgr.getStr("DISABLED") == "[-]");
    CHECK(langMgr.getStr("MISSING") == "MISSING");

    // leave the global as it was
    langMgr.setShortcutLabeler(nullptr);
    langMgr.setMousePrimaryModifierName("");
    g_remove(path.c_str());
}


#ifdef ART_LANGUAGES_DIR
// every "%shortcut(action.id)%" in the translations must name a real action
void testLanguageStrings()
{
    ShortcutTable t(ModifierMasks::linux_like());
    defineDefaultShortcuts(t);

    GDir *dir = g_dir_open(ART_LANGUAGES_DIR, 0, nullptr);
    CHECK(dir != nullptr);
    if (!dir) {
        return;
    }
    int found = 0;
    while (const char *name = g_dir_read_name(dir)) {
        gchar *path = g_build_filename(ART_LANGUAGES_DIR, name, nullptr);
        gchar *contents = nullptr;
        if (g_file_get_contents(path, &contents, nullptr, nullptr)) {
            std::string text(contents);
            // the old name of "%mouse_primary%" would be shown as it is
            CHECK(text.find("%primary%") == std::string::npos);
            const std::string open_tag = "%shortcut(";
            for (size_t p = text.find(open_tag); p != std::string::npos;
                 p = text.find(open_tag, p + 1)) {
                size_t e = text.find(")%", p);
                CHECK(e != std::string::npos);
                if (e == std::string::npos) {
                    break;
                }
                std::string id = text.substr(p + open_tag.size(),
                                             e - p - open_tag.size());
                ++found;
                if (!t.contains(id)) {
                    std::cerr << name << ": unknown action in a string: "
                              << id << std::endl;
                }
                CHECK(t.contains(id));
            }
            g_free(contents);
        }
        g_free(path);
    }
    g_dir_close(dir);
    CHECK(found > 50);
}
#endif

} // namespace

void testEditing()
{
    auto lin = ModifierMasks::linux_like();

    // what is recorded for a key press
    CHECK(shortcutFromEvent(lin, GDK_KEY_z, GDK_KEY_z, GDK_CONTROL_MASK) ==
          key(lin, "Primary+z"));
    CHECK(shortcutFromEvent(lin, GDK_KEY_z, GDK_KEY_Z, GDK_SHIFT_MASK) ==
          key(lin, "Shift+z"));
    CHECK(shortcutFromEvent(lin, GDK_KEY_equal, GDK_KEY_plus,
                            GDK_SHIFT_MASK) == key(lin, "plus"));
    CHECK(shortcutFromEvent(lin, GDK_KEY_comma, GDK_KEY_less,
                            GDK_SHIFT_MASK) == key(lin, "less"));
    CHECK(shortcutFromEvent(lin, GDK_KEY_1, GDK_KEY_exclam, GDK_SHIFT_MASK) ==
          key(lin, "Shift+1"));
    CHECK(shortcutFromEvent(lin, GDK_KEY_F3, GDK_KEY_F3, GDK_SHIFT_MASK) ==
          key(lin, "Shift+F3"));
    CHECK(shortcutFromEvent(lin, GDK_KEY_Up, GDK_KEY_Up,
                            GDK_SHIFT_MASK | GDK_CONTROL_MASK) ==
          key(lin, "Primary+Shift+Up"));

    // conflicts: same context and phase only, never with itself
    {
        ShortcutTable t = small(lin);
        CHECK(t.findConflict("a.undo", key(lin, "Primary+s")) == "a.save");
        CHECK(t.findConflict("a.save", key(lin, "Primary+s")).empty());
        CHECK(t.findConflict("b.save", key(lin, "Primary+z")).empty());
        CHECK(t.findConflict("a.undo", key(lin, "F2")).empty()); // other phase
        CHECK(t.findConflict("nope", key(lin, "F2")).empty());
    }

    // keys that another context of the same tab or the window also uses
    {
        ShortcutTable t(lin);
        defineDefaultShortcuts(t);
        auto has = [](const std::vector<std::string> &v, const char *id) {
            return std::find(v.begin(), v.end(), id) != v.end();
        };
        // window-level and tab-level actions can hide each other
        CHECK(has(t.findOverlaps("editor.undo", key(lin, "Primary+w")),
                  "window.close_tab"));
        CHECK(has(t.findOverlaps("queue.select_all", key(lin, "Primary+q")),
                  "window.quit"));
        // the same context is findConflict()'s business
        CHECK(!has(t.findOverlaps("filebrowser.trash", key(lin, "Primary+b")),
                   "filebrowser.queue"));
        // another tab (or a dialog) is never reached by the same press
        CHECK(!has(t.findOverlaps("queue.cancel", key(lin, "Primary+z")),
                   "editor.undo"));
        CHECK(!has(t.findOverlaps("saveas.ok", key(lin, "F11")),
                   "window.fullscreen"));
        // never with itself
        CHECK(!has(t.findOverlaps("window.close_tab", key(lin, "Primary+w")),
                   "window.close_tab"));
        CHECK(ShortcutTable::contextsOverlap("window", "editor"));
        CHECK(!ShortcutTable::contextsOverlap("editor", "filecatalog"));
        CHECK(!ShortcutTable::contextsOverlap("tool-value", "editor"));
        CHECK(!ShortcutTable::contextsOverlap("x", "y"));
    }

    // setKeys
    {
        ShortcutTable t = small(lin);
        t.setKeys("a.save", {key(lin, "F9"), key(lin, "F9")});
        CHECK(t.keys("a.save").size() == 1 && t.isCustomized("a.save"));
        t.setKeys("a.save", {key(lin, "Primary+s")});
        CHECK(!t.isCustomized("a.save"));
        t.setKeys("a.save", {});
        CHECK(t.keys("a.save").empty() && t.isCustomized("a.save"));
    }

    // the user's file is exactly the difference from the baseline, and
    // applying it on the baseline gives back the edited table
    {
        ShortcutTable base = small(lin);
        base.applyOverrides(R"({"bindings": {"a.redo": ["F7"]}})", false);
        ShortcutTable t = base;
        CHECK(t.dumpOverrides(base).find("\"a.") == std::string::npos);

        t.setKeys("a.save", {key(lin, "F9")});
        t.setKeys("a.zoom", {});                        // disabled
        t.setKeys("a.undo", {key(lin, "Primary+s")});   // swap with save...
        t.setKeys("b.save", {key(lin, "Primary+Alt+s"), key(lin, "plus")});
        t.setKeys("a.redo", base.keys("a.redo"));       // unchanged
        const std::string json = t.dumpOverrides(base);
        CHECK(json.find("a.redo") == std::string::npos);

        ShortcutTable again = base;
        again.applyOverrides(json, false);
        for (auto &w : again.warnings()) {
            std::cerr << "unexpected warning: " << w << std::endl;
        }
        CHECK(again.warnings().empty());
        for (auto &id : t.ids()) {
            CHECK(again.keys(id) == t.keys(id));
        }
        CHECK(again.keys("a.zoom").empty());
    }

    // the mouse modifier is part of the layer too
    {
        ShortcutTable base = small(lin);
        ShortcutTable t = base;
        CHECK(t.dumpOverrides(base).find("mouse_primary_modifier") ==
              std::string::npos);
        t.applyOverrides(R"({"mouse_primary_modifier": "Super"})", false);
        const std::string json = t.dumpOverrides(base);
        CHECK(json.find("\"mouse_primary_modifier\": \"Super\"") !=
              std::string::npos);
        ShortcutTable again = base;
        again.applyOverrides(json, false);
        CHECK(again.mouseIsOsKey());
        // set directly, as the editor does, and back
        ShortcutTable u = base;
        u.setMouseIsOsKey(true);
        CHECK(u.dumpOverrides(base) == json);
        u.setMouseIsOsKey(false);
        CHECK(u.dumpOverrides(base).find("mouse_primary_modifier") ==
              std::string::npos);
    }

    // the real table, on a Mac-like layout: edit, dump, reload
    {
        auto mac = macCmd();
        ShortcutTable base(mac);
        defineDefaultShortcuts(base);
        ShortcutTable t = base;
        t.setKeys("editor.zoom_fit", {key(mac, "Primary+Alt+f")});
        t.setKeys("editor.undo", {});
        const std::string json = t.dumpOverrides(base);
        ShortcutTable again = base;
        again.applyOverrides(json, false);
        CHECK(again.warnings().empty());
        for (auto &id : t.ids()) {
            CHECK(again.keys(id) == t.keys(id));
        }
    }
}

// the system shortcuts of macOS, with a made-up list and key code table
void testSystemShortcuts()
{
    // virtual key codes of the keys that are used here
    const auto keyval_of = [](int code) -> guint {
        switch (code) {
        case 49: return GDK_KEY_space;
        case 126: return GDK_KEY_Up;
        case 20: return GDK_KEY_3;
        case 0: return GDK_KEY_a;
        default: return 0;
        }
    };
    // Cmd+Space (Spotlight), Ctrl+Up (Mission Control, with the Fn flag that
    // the system adds to the arrows), Cmd+Shift+3 (screenshot)
    const std::vector<SystemHotKey> list = {
        {49, 0x100}, {126, 0x21000}, {20, 0x300}};
    auto mac = ModifierMasks::mac_like(); // Primary is Ctrl
    const auto sys = [&](const ModifierMasks &m, const char *spec) {
        return matchesSystemHotKey(key(m, spec), m, list, keyval_of);
    };
    // Primary is Ctrl here
    CHECK(sys(mac, "Primary+Up"));
    CHECK(!sys(mac, "Primary+space"));
    CHECK(!sys(mac, "Up"));
    CHECK(!sys(mac, "Primary+Shift+Up"));
    // and Cmd there
    auto cmd = macCmd();
    CHECK(sys(cmd, "Primary+space"));
    CHECK(!sys(cmd, "Primary+Up"));
    CHECK(sys(cmd, "Ctrl+Up"));
    CHECK(sys(cmd, "Primary+Shift+3"));
    CHECK(!sys(cmd, "Primary+3"));
    CHECK(!sys(cmd, "Primary+Alt+space"));
    // Fn+A (code 0) is not the plain A key
    CHECK(!matchesSystemHotKey(key(cmd, "a"), cmd, {{0, 0x20000}}, keyval_of));
    // a key code that types nothing matches nothing
    CHECK(!matchesSystemHotKey(key(cmd, "Primary+space"), cmd, {{999, 0x100}},
                               keyval_of));
    // the keys of the application menu and the window server
    CHECK(isReservedByMacOS(key(cmd, "Primary+comma"), cmd));
    CHECK(isReservedByMacOS(key(cmd, "Primary+Alt+h"), cmd));
    CHECK(isReservedByMacOS(key(cmd, "Primary+Tab"), cmd));
    CHECK(!isReservedByMacOS(key(cmd, "Primary+q"), cmd)); // our quit too
    CHECK(!isReservedByMacOS(key(cmd, "Primary+period"), cmd));
    CHECK(!isReservedByMacOS(key(mac, "Primary+comma"), mac)); // that is Ctrl
#ifndef __APPLE__
    CHECK(enabledSystemHotKeys().empty());
#endif
}

int main()
{
    testParse();
    testNormalize();
    testCandidates();
    testOverrides();
    testLayers();
    testMouseModifier();
    testPrimaryModifier();
    testLookup();
    testEditing();
    testDefaults();
    testDisplay();
    testPlaceholders();
    testSystemShortcuts();
#ifdef ART_LANGUAGES_DIR
    testLanguageStrings();
#endif
    if (failures) {
        std::cerr << failures << " check(s) failed" << std::endl;
        return 1;
    }
    std::cout << "shortcuts: all checks passed" << std::endl;
    return 0;
}
