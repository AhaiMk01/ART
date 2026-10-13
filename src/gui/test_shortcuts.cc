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

// Unit tests for the shortcut table (no display needed): ctest -R shortcuts

#include "../utils/multilangmgr.h"
#include "shortcutdefs.h"
#include "shortcuttable.h"

#include <cstdio>
#include <cstdlib>
#include <glib/gstdio.h>
#include <glibmm.h>
#include <gtk/gtk.h>
#include <iostream>

using namespace art::gui;
namespace sm = art::gui::shortcut_mod;

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
    for (auto m : {ModifierMasks::linux_like(), ModifierMasks::mac_like()}) {
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
    auto mac = ModifierMasks::mac_like();
    CHECK(key(lin, "Ctrl+s") == key(lin, "Primary+s"));
    CHECK(key(mac, "Ctrl+s") != key(mac, "Primary+s"));
    CHECK(key(mac, "Ctrl+s").mods == sm::Ctrl);
    CHECK(formatShortcutKey(key(mac, "Ctrl+s"), mac) == "Ctrl+S");
}

void testNormalize()
{
    auto lin = ModifierMasks::linux_like();
    auto mac = ModifierMasks::mac_like();
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
    for (auto m : {ModifierMasks::linux_like(), ModifierMasks::mac_like()}) {
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
    ShortcutTable mac(ModifierMasks::mac_like());
    defineDefaultShortcuts(lin);
    defineDefaultShortcuts(mac);
    lin.applyOverrides(lin.dumpJson());
    mac.applyOverrides(lin.dumpJson());
    CHECK(mac.warnings().empty());
    CHECK(mac.keys("editor.undo")[0] == key(ModifierMasks::mac_like(), "Primary+z"));
    CHECK(mac.keys("editor.undo")[0].mods == sm::Primary);
}

// what the user sees in tooltips must be what GTK shows in menus
void testDisplay()
{
    auto lin = ModifierMasks::linux_like();
    auto mac = ModifierMasks::mac_like();
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
    // the modifier alone, for "%primary%-click"
    for (auto m : {lin, mac}) {
        const std::string n = primaryModifierName(m);
        CHECK(!n.empty());
        CHECK(n.back() != '+');
        CHECK(d(m, "Primary+s").compare(0, n.size(), n) == 0);
    }
    // the spelling used in shortcuts.json is not affected
    CHECK(formatShortcutKey(key(lin, "plus"), lin) == "plus");
    CHECK(formatShortcutKey(key(lin, "Primary+Return"), lin) ==
          "Primary+Return");
    CHECK(formatShortcutKey(key(mac, "Primary+Ctrl+Alt+Shift+F5"), mac) ==
          "Primary+Ctrl+Alt+Shift+F5");

    // handy when looking at what the user gets
    if (getenv("SHORTCUTS_TEST_LABELS")) {
#ifdef __APPLE__
        ShortcutTable t(ModifierMasks::mac_like());
#else
        ShortcutTable t(ModifierMasks::linux_like());
#endif
        defineDefaultShortcuts(t);
        for (auto &id : t.ids()) {
            std::cout << id << "\t" << t.label(id) << std::endl;
        }
    }
}

// "%shortcut(id)%" and "%primary%" in translated strings
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
              "PRIM;<b>%primary%</b>-click, %primary%+drag\n"
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
    langMgr.setPrimaryModifierName(primaryModifierName(t.masks()));

    const std::string save = gtkLabel(ModifierMasks::linux_like(), "Primary+s");
    const std::string undo = gtkLabel(ModifierMasks::linux_like(), "Primary+z");
    const std::string prim = primaryModifierName(ModifierMasks::linux_like());
    CHECK(langMgr.getStr("PLAIN") == "no placeholders here");
    CHECK(langMgr.getStr("ONE") == "Save: <b>" + save + "</b>.");
    CHECK(langMgr.getStr("TWO") == undo + " and " + save + ", then &lt;");
    CHECK(langMgr.getStr("PRIM") == "<b>" + prim + "</b>-click, " + prim + "+drag");
    CHECK(langMgr.getStr("BAD") == "? %shortcut(a.undo");
    CHECK(langMgr.getStr("DISABLED") == "[-]");
    CHECK(langMgr.getStr("MISSING") == "MISSING");

    // leave the global as it was
    langMgr.setShortcutLabeler(nullptr);
    langMgr.setPrimaryModifierName("");
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

int main()
{
    testParse();
    testNormalize();
    testCandidates();
    testOverrides();
    testLookup();
    testDefaults();
    testDisplay();
    testPlaceholders();
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
