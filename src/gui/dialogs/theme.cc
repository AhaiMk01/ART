/* -*- C++ -*-
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
#include "theme.h"
#include "../utils/config.h"
#include "../../utils/pathutils.h"
#include "../utils/version.h"
#include <gtkmm.h>
#include <sstream>
#include <string>
#include <vector>

namespace art { namespace dialogs {

namespace {

const char *const DEFAULT_THEME = "Default";

struct Settings {
    Glib::ustring theme = DEFAULT_THEME;
    std::vector<int> bg = {72, 72, 72};
    std::vector<int> fg = {170, 170, 170};
    std::vector<int> hl = {227, 146, 67};
    Glib::ustring font_family = "default";
    int font_size = 10;
    bool multi_user = true;
};


bool loadKeyFile(Glib::KeyFile &kf, const Glib::ustring &fname)
{
    try {
        return Glib::file_test(fname, Glib::FILE_TEST_IS_REGULAR) &&
               kf.load_from_file(fname);
    } catch (Glib::Error &) {
        return false;
    }
}


std::vector<int> colour(Glib::KeyFile &kf, const char *key,
                        const std::vector<int> &dflt)
{
    try {
        std::vector<int> res = kf.get_integer_list("Theme Colors", key);
        if (res.size() >= 3) {
            res.resize(3);
            return res;
        }
    } catch (Glib::Error &) {
    }
    return dflt;
}


// same keys, and same precedence, as Options::readFromFile
void readOptions(const Glib::ustring &fname, Settings &s)
{
    Glib::KeyFile kf;
    if (!loadKeyFile(kf, fname)) {
        return;
    }
    try {
        if (kf.has_key("General", "Theme")) {
            s.theme = kf.get_string("General", "Theme");
        }
        if (kf.has_key("General", "MultiUser")) {
            s.multi_user = kf.get_boolean("General", "MultiUser");
        }
        if (kf.has_key("GUI", "FontFamily")) {
            s.font_family = kf.get_string("GUI", "FontFamily");
        }
        if (kf.has_key("GUI", "FontSize")) {
            s.font_size = kf.get_integer("GUI", "FontSize");
        }
        if (kf.has_group("Theme Colors")) {
            s.bg = colour(kf, "Background", s.bg);
            s.fg = colour(kf, "Foreground", s.fg);
            s.hl = colour(kf, "Highlight", s.hl);
        }
    } catch (Glib::Error &) {
    }
}


Glib::ustring baseDir(const char *argv0)
{
#ifdef BUILD_BUNDLE
    Glib::ustring exe = art::utils::getExecutablePath(argv0);
    if (Glib::path_is_absolute(DATA_SEARCH_PATH)) {
        return DATA_SEARCH_PATH;
    } else if (std::string(DATA_SEARCH_PATH) == ".") {
        return exe;
    } else {
        return Glib::build_filename(exe, DATA_SEARCH_PATH);
    }
#else
    (void)argv0;
    return DATA_SEARCH_PATH;
#endif
}


// mirrors Options::load
Glib::ustring userConfigDir(const Glib::ustring &base, bool multi_user)
{
    auto env = Glib::getenv("ART_SETTINGS");
    if (!env.empty()) {
        return env;
    }
    if (!multi_user) {
        return Glib::build_filename(base, "mysettings");
    }
#ifdef WIN32
    // Options::load uses CSIDL_LOCAL_APPDATA, which is not what
    // g_get_user_config_dir() returns
    auto local = Glib::getenv("LOCALAPPDATA");
    if (!local.empty()) {
        return Glib::build_filename(local, CACHEFOLDERNAME);
    }
#endif
    return Glib::build_filename(Glib::ustring(g_get_user_config_dir()),
                                CACHEFOLDERNAME);
}


std::string cssPath(std::string s)
{
#ifdef WIN32
    for (auto &c : s) {
        if (c == '\\') {
            c = '/';
        }
    }
#endif
    return s;
}


// same as Preferences::switchThemeTo for the Default theme
std::string defaultThemeCss(const Settings &s, const Glib::ustring &base)
{
    const auto &bg = s.bg;
    const auto &fg = s.fg;
    const auto &hl = s.hl;
    // art::engine::Color::rgbLuminance
    double lum = (bg[0] * 0.2126729 + bg[1] * 0.7151521 + bg[2] * 0.0721750) /
                 255.0;
    float factor = 0.1;
    if (lum < 0.2) {
        factor = 2 + (0.2 - lum) / 0.2;
    } else if (lum > 0.5) {
        factor = 0.2 + 0.6 * (lum - 0.5) / 0.5;
    }
    std::ostringstream buf;
    buf << "@define-color ART-bg rgb(" << bg[0] << "," << bg[1] << ","
        << bg[2] << ");\n"
        << "@define-color ART-fg rgb(" << fg[0] << "," << fg[1] << ","
        << fg[2] << ");\n"
        << "@define-color ART-hl rgb(" << hl[0] << "," << hl[1] << ","
        << hl[2] << ");\n"
        << "@define-color ART-dark rgb(" << int(bg[0] * factor) << ","
        << int(bg[1] * factor) << "," << int(bg[2] * factor) << ");\n"
        << "@import \""
        << cssPath(Glib::build_filename(base, "themes", "_ART.css")) << "\";\n";
    return buf.str();
}


void addProvider(const Glib::RefPtr<Gdk::Screen> &screen,
                 const Glib::ustring &css, bool is_path, guint priority)
{
    try {
        auto prov = Gtk::CssProvider::create();
        if (is_path) {
            prov->load_from_path(css);
        } else {
            prov->load_from_data(css);
        }
        Gtk::StyleContext::add_provider_for_screen(screen, prov, priority);
    } catch (Glib::Error &) {
    } catch (...) {
    }
}



// The window icon of the main window (see RTWindow), found in the same
// "images" directory: the PNG sizes are what ART itself uses, and the SVG
// (images/ART-logo.svg, installed together with them) is the fallback
// should those be missing. In the bundles that directory is
// Contents/Resources/images (macOS) and <app dir>/images (Linux, Windows).
void setWindowIcon(const Glib::ustring &base)
{
#ifndef WIN32 // there the icon is embedded in the executable (myicon.rc)
    const auto imgdir = Glib::build_filename(base, "images");
    std::vector<Glib::RefPtr<Gdk::Pixbuf>> icons;
    for (int sz : {16, 24, 48, 128, 256}) {
        try {
            icons.push_back(Gdk::Pixbuf::create_from_file(Glib::build_filename(
                imgdir, Glib::ustring::compose("ART-logo-%1.png", sz))));
        } catch (Glib::Error &) {
        }
    }
    if (icons.empty()) {
        try {
            icons.push_back(Gdk::Pixbuf::create_from_file(
                Glib::build_filename(imgdir, "ART-logo.svg"), 256, 256, true));
        } catch (Glib::Error &) {
        }
    }
    if (!icons.empty()) {
        Gtk::Window::set_default_icon_list(icons);
    }
#else
    (void)base;
#endif
}

// ART's own folder icons in place of the stock ones: reuse the theme that the
// main application generates in the user config dir (see
// updateFolderIconTheme), if there is one, otherwise leave the default icons
void setIconTheme(const Glib::ustring &user_dir)
{
    const auto root = Glib::build_filename(user_dir, "icons");
    if (!Glib::file_test(
            Glib::build_filename(root, "ART-folders", "index.theme"),
            Glib::FILE_TEST_IS_REGULAR)) {
        return;
    }
    try {
        Gtk::IconTheme::get_default()->append_search_path(root);
        Gtk::Settings::get_default()->property_gtk_icon_theme_name() =
            "ART-folders";
    } catch (...) {
    }
}

} // namespace


void applyTheme(const char *argv0)
{
    auto screen = Gdk::Screen::get_default();
    if (!screen) {
        return;
    }
    Gtk::Settings::get_for_screen(screen)->property_gtk_theme_name() =
        "Adwaita";
    Gtk::Settings::get_for_screen(screen)
        ->property_gtk_application_prefer_dark_theme() = true;

    const Glib::ustring base = baseDir(argv0);

    Settings s;
    readOptions(Glib::build_filename(base, "options"), s);
    readOptions(Glib::build_filename(userConfigDir(base, s.multi_user),
                                     "options"),
                s);

    bool done = false;
    if (s.theme != DEFAULT_THEME) {
        auto fname = Glib::build_filename(base, "themes", s.theme + ".css");
        if (Glib::file_test(fname, Glib::FILE_TEST_EXISTS)) {
            addProvider(screen, fname, true, GTK_STYLE_PROVIDER_PRIORITY_USER);
            done = true;
        }
    }
    if (!done) {
        addProvider(screen, defaultThemeCss(s, base), false,
                    GTK_STYLE_PROVIDER_PRIORITY_USER);
    }

    Glib::ustring css;
    if (s.font_family != "default") {
        css = Glib::ustring::compose("* { font-family: %1; font-size: %2pt}",
                                     s.font_family, s.font_size);
    } else {
        css = Glib::ustring::compose("* { font-size: %1pt}", s.font_size);
    }
    addProvider(screen, css, false, GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);

    try {
        Gtk::IconTheme::get_default()->append_search_path(
            Glib::build_filename(base, "images"));
    } catch (...) {
    }
    setIconTheme(userConfigDir(base, s.multi_user));
    setWindowIcon(base);
}

} } // namespace art::dialogs
