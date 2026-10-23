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
#include "dialogs.h"
#include <gtkmm.h>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <memory>
#include <sstream>
#include <mutex>
#include <thread>
#ifndef WIN32
#include <signal.h>
#include <unistd.h>
#else
#include <io.h>
#endif

namespace art { namespace dialogs {

namespace {

// response id used when --timeout expires
constexpr int RESPONSE_TIMEOUT = EXIT_TIMEOUT;


// zenity runs --text through g_strcompress-like processing for these
Glib::ustring unescape(const Glib::ustring &s)
{
    std::string res;
    const std::string src = s;
    for (size_t i = 0; i < src.size(); ++i) {
        if (src[i] == '\\' && i + 1 < src.size()) {
            char c = src[i + 1];
            if (c == 'n') {
                res += '\n';
                ++i;
                continue;
            } else if (c == 't') {
                res += '\t';
                ++i;
                continue;
            } else if (c == '\\') {
                res += '\\';
                ++i;
                continue;
            }
        }
        res += src[i];
    }
    return res;
}


// Text is Pango markup unless --no-markup. Error output captured from
// scripts often contains stray '<' or '&'; in that case show it verbatim
// rather than an empty label.
bool useMarkup(const Args &args, const Glib::ustring &text)
{
    if (args.no_markup) {
        return false;
    }
    GError *err = nullptr;
    bool ok = pango_parse_markup(text.c_str(), -1, 0, nullptr, nullptr,
                                 nullptr, &err);
    if (err) {
        g_error_free(err);
    }
    return ok;
}


void setupWindow(Gtk::Window &w, const Args &args, const char *default_title)
{
    w.set_title(args.title.empty() ? Glib::ustring(default_title)
                                   : args.title);
    if (args.width > 0 || args.height > 0) {
        w.set_default_size(args.width, args.height);
    }
    w.set_position(Gtk::WIN_POS_CENTER);
}


void setupTimeout(Gtk::Dialog &d, const Args &args)
{
    if (args.timeout > 0) {
        Glib::signal_timeout().connect_seconds_once(
            [&d]() { d.response(RESPONSE_TIMEOUT); }, args.timeout);
    }
}


int mapResponse(int resp, int ok_resp = Gtk::RESPONSE_OK)
{
    if (resp == ok_resp || resp == Gtk::RESPONSE_YES) {
        return EXIT_OK;
    } else if (resp == RESPONSE_TIMEOUT) {
        return EXIT_TIMEOUT;
    }
    return EXIT_CANCEL;
}


void unwrapLabels(Gtk::Container &c)
{
    for (auto w : c.get_children()) {
        if (auto l = dynamic_cast<Gtk::Label *>(w)) {
            l->set_line_wrap(false);
        } else if (auto cc = dynamic_cast<Gtk::Container *>(w)) {
            unwrapLabels(*cc);
        }
    }
}


Gtk::Label *makeLabel(const Args &args, Gtk::Box &box)
{
    if (args.text.empty()) {
        return nullptr;
    }
    auto text = unescape(args.text);
    auto l = Gtk::manage(new Gtk::Label());
    if (useMarkup(args, text)) {
        l->set_markup(text);
    } else {
        l->set_text(text);
    }
    l->set_xalign(0);
    l->set_line_wrap(!args.no_wrap);
    l->set_selectable(false);
    box.pack_start(*l, Gtk::PACK_SHRINK);
    return l;
}


Glib::ustring joinStrings(const std::vector<Glib::ustring> &v,
                          const Glib::ustring &sep)
{
    Glib::ustring res;
    for (size_t i = 0; i < v.size(); ++i) {
        if (i) {
            res += sep;
        }
        res += v[i];
    }
    return res;
}


void killParent()
{
#ifndef WIN32
    ::kill(getppid(), SIGTERM);
#endif
}

} // namespace


//-----------------------------------------------------------------------------
// info / warning / error / question
//-----------------------------------------------------------------------------

int runMessage(const Args &args)
{
    Gtk::MessageType type = Gtk::MESSAGE_INFO;
    const char *title = "Information";
    switch (args.kind) {
    case Kind::WARNING:
        type = Gtk::MESSAGE_WARNING;
        title = "Warning";
        break;
    case Kind::ERROR:
        type = Gtk::MESSAGE_ERROR;
        title = "Error";
        break;
    case Kind::QUESTION:
        type = Gtk::MESSAGE_QUESTION;
        title = "Question";
        break;
    default:
        break;
    }
    const bool question = args.kind == Kind::QUESTION;

    auto text = unescape(args.text);
    Gtk::MessageDialog dlg(text, useMarkup(args, text), type,
                           Gtk::BUTTONS_NONE, true);
    setupWindow(dlg, args, title);

    if (question) {
        dlg.add_button(args.cancel_label.empty() ? Glib::ustring("_No")
                                                 : args.cancel_label,
                       Gtk::RESPONSE_NO);
        dlg.add_button(args.ok_label.empty() ? Glib::ustring("_Yes")
                                             : args.ok_label,
                       Gtk::RESPONSE_YES);
    } else {
        dlg.add_button(args.ok_label.empty() ? Glib::ustring("_OK")
                                             : args.ok_label,
                       Gtk::RESPONSE_OK);
    }
    dlg.set_default_response(question ? Gtk::RESPONSE_YES : Gtk::RESPONSE_OK);
    if (args.no_wrap) {
        unwrapLabels(*dlg.get_message_area());
    }
    setupTimeout(dlg, args);
    dlg.show_all();
    dlg.present();
    return mapResponse(dlg.run());
}


//-----------------------------------------------------------------------------
// progress
//-----------------------------------------------------------------------------

namespace {

// Reads stdin in a helper thread (a blocking read is the only portable way,
// polling a pipe does not work on Windows) and hands complete lines over to
// the GTK main loop.
class StdinReader {
public:
    StdinReader()
    {
        disp_.connect([this]() { drain(); });
        std::thread([this]() { loop(); }).detach();
    }

    // line == nullptr means EOF
    sigc::slot<void, const std::string *> on_line;

private:
    void loop()
    {
        std::string buf;
        char tmp[4096];
        for (;;) {
#ifdef WIN32
            int n = _read(0, tmp, sizeof(tmp));
#else
            ssize_t n = ::read(0, tmp, sizeof(tmp));
#endif
            if (n <= 0) {
                break;
            }
            buf.append(tmp, n);
            size_t pos;
            while ((pos = buf.find('\n')) != std::string::npos) {
                push(buf.substr(0, pos));
                buf.erase(0, pos + 1);
            }
        }
        if (!buf.empty()) {
            push(buf);
        }
        {
            std::lock_guard<std::mutex> lck(mutex_);
            eof_ = true;
        }
        disp_.emit();
    }

    void push(const std::string &line)
    {
        {
            std::lock_guard<std::mutex> lck(mutex_);
            lines_.push_back(line);
        }
        disp_.emit();
    }

    void drain()
    {
        for (;;) {
            std::string line;
            bool eof = false;
            {
                std::lock_guard<std::mutex> lck(mutex_);
                if (!lines_.empty()) {
                    line = lines_.front();
                    lines_.pop_front();
                } else if (eof_ && !eof_sent_) {
                    eof_sent_ = true;
                    eof = true;
                } else {
                    return;
                }
            }
            if (eof) {
                on_line(nullptr);
                return;
            }
            on_line(&line);
        }
    }

    std::mutex mutex_;
    std::deque<std::string> lines_;
    bool eof_ = false;
    bool eof_sent_ = false;
    Glib::Dispatcher disp_;
};

} // namespace


int runProgress(const Args &args)
{
    Gtk::Dialog dlg;
    setupWindow(dlg, args, "Progress");
    if (args.width <= 0) {
        dlg.set_default_size(400, -1);
    }
    dlg.set_resizable(false);

    auto box = dlg.get_content_area();
    box->set_spacing(12);
    box->set_border_width(12);
    auto label = makeLabel(args, *box);
    Gtk::ProgressBar bar;
    box->pack_start(bar, Gtk::PACK_SHRINK);

    Gtk::Button *cancel = nullptr;
    if (!args.no_cancel) {
        cancel = dlg.add_button(args.cancel_label.empty()
                                    ? Glib::ustring("_Cancel")
                                    : args.cancel_label,
                                Gtk::RESPONSE_CANCEL);
    }
    auto ok = dlg.add_button(args.ok_label.empty() ? Glib::ustring("_OK")
                                                   : args.ok_label,
                             Gtk::RESPONSE_OK);
    ok->set_sensitive(false);

    bool pulsating = args.pulsate;
    auto set_fraction = [&](int pct) {
        if (pct < 0) {
            pct = 0;
        } else if (pct > 100) {
            pct = 100;
        }
        bar.set_fraction(pct / 100.0);
        bar.set_show_text(true);
        bar.set_text(Glib::ustring::compose("%1%%", pct));
    };
    if (!pulsating) {
        set_fraction(args.percentage);
    }

    sigc::connection pulse;
    if (pulsating) {
        pulse = Glib::signal_timeout().connect(
            [&bar]() {
                bar.pulse();
                return true;
            },
            100);
    }

    auto finish = [&](bool complete) {
        // complete == the producer is done (100% or EOF)
        if (pulse) {
            pulse.disconnect();
        }
        if (pulsating) {
            pulsating = false;
        }
        if (complete) {
            if (args.auto_close) {
                dlg.response(Gtk::RESPONSE_OK);
            } else {
                ok->set_sensitive(true);
                if (cancel) {
                    cancel->set_sensitive(false);
                }
                ok->grab_default();
            }
        }
    };

    StdinReader reader;
    reader.on_line = [&](const std::string *line) {
        if (!line) { // EOF
            finish(true);
            return;
        }
        std::string s = *line;
        while (!s.empty() && (s.back() == '\r' || s.back() == ' ')) {
            s.pop_back();
        }
        if (!s.empty() && s[0] == '#') {
            if (label) {
                size_t i = 1;
                while (i < s.size() && s[i] == ' ') {
                    ++i;
                }
                auto txt = unescape(s.substr(i));
                if (useMarkup(args, txt)) {
                    label->set_markup(txt);
                } else {
                    label->set_text(txt);
                }
            }
            return;
        }
        if (!s.empty() &&
            s.find_first_not_of("0123456789") == std::string::npos) {
            if (args.pulsate) {
                return; // numbers do not make sense when pulsating
            }
            int pct = std::atoi(s.c_str());
            set_fraction(pct);
            if (pct >= 100) {
                finish(true);
            }
        }
    };

    setupTimeout(dlg, args);
    dlg.show_all();
    dlg.present();
    int resp = dlg.run();
    if (resp == Gtk::RESPONSE_OK) {
        return EXIT_OK;
    }
    if (resp == RESPONSE_TIMEOUT) {
        return EXIT_TIMEOUT;
    }
    // cancelled or window closed
    if (args.auto_kill) {
        killParent();
    }
    return EXIT_CANCEL;
}


//-----------------------------------------------------------------------------
// file selection
//-----------------------------------------------------------------------------

namespace {

Glib::RefPtr<Gtk::FileFilter> parseFilter(const Glib::ustring &spec)
{
    auto f = Gtk::FileFilter::create();
    Glib::ustring name = spec;
    Glib::ustring pats;
    auto pos = spec.find('|');
    if (pos != Glib::ustring::npos) {
        name = spec.substr(0, pos);
        pats = spec.substr(pos + 1);
    }
    auto trim = [](Glib::ustring s) {
        auto b = s.find_first_not_of(" \t");
        if (b == Glib::ustring::npos) {
            return Glib::ustring();
        }
        return s.substr(b, s.find_last_not_of(" \t") - b + 1);
    };
    name = trim(name);
    f->set_name(name.empty() ? spec : name);
    std::istringstream is(pats.raw());
    std::string p;
    bool any = false;
    while (is >> p) {
        f->add_pattern(p);
        any = true;
    }
    if (!any) {
        f->add_pattern("*");
    }
    return f;
}

} // namespace


int runFileSelection(const Args &args)
{
    Gtk::FileChooserAction action;
    if (args.directory) {
        action = args.save ? Gtk::FILE_CHOOSER_ACTION_CREATE_FOLDER
                           : Gtk::FILE_CHOOSER_ACTION_SELECT_FOLDER;
    } else {
        action = args.save ? Gtk::FILE_CHOOSER_ACTION_SAVE
                           : Gtk::FILE_CHOOSER_ACTION_OPEN;
    }
    Gtk::FileChooserDialog dlg("", action);
    setupWindow(dlg, args,
                args.save ? "Select a file to save" : "Select a file");
    if (args.width <= 0 && args.height <= 0) {
        dlg.set_default_size(800, 500);
    }
    dlg.add_button(args.cancel_label.empty() ? Glib::ustring("_Cancel")
                                             : args.cancel_label,
                   Gtk::RESPONSE_CANCEL);
    dlg.add_button(args.ok_label.empty()
                       ? Glib::ustring(args.save ? "_Save" : "_Open")
                       : args.ok_label,
                   Gtk::RESPONSE_OK);
    dlg.set_default_response(Gtk::RESPONSE_OK);
    dlg.set_select_multiple(args.multiple && !args.save);
    dlg.set_do_overwrite_confirmation(args.confirm_overwrite);

    bool first = true;
    for (auto &spec : args.filters) {
        auto f = parseFilter(spec);
        dlg.add_filter(f);
        if (first) {
            dlg.set_filter(f);
            first = false;
        }
    }

    if (!args.filename.empty()) {
        auto fn = args.filename;
        if (!Glib::path_is_absolute(fn)) {
            fn = Glib::build_filename(Glib::get_current_dir(), fn);
        }
        if (Glib::file_test(fn, Glib::FILE_TEST_IS_DIR)) {
            dlg.set_current_folder(fn);
        } else if (args.save) {
            dlg.set_current_folder(Glib::path_get_dirname(fn));
            dlg.set_current_name(Glib::path_get_basename(fn));
        } else {
            dlg.set_filename(fn);
        }
    }

    setupTimeout(dlg, args);
    dlg.show_all();
    dlg.present();
    int resp = dlg.run();
    int ret = mapResponse(resp);
    if (ret == EXIT_OK) {
        std::vector<Glib::ustring> files;
        for (auto &f : dlg.get_filenames()) {
            files.push_back(f);
        }
        if (files.empty()) {
            return EXIT_CANCEL;
        }
        std::string out = joinStrings(files, args.separator);
        std::printf("%s\n", out.c_str());
        std::fflush(stdout);
    }
    return ret;
}


//-----------------------------------------------------------------------------
// entry
//-----------------------------------------------------------------------------

int runEntry(const Args &args)
{
    Gtk::Dialog dlg;
    setupWindow(dlg, args, "Add a new entry");
    dlg.set_resizable(false);
    auto box = dlg.get_content_area();
    box->set_spacing(12);
    box->set_border_width(12);
    makeLabel(args, *box);
    Gtk::Entry entry;
    entry.set_text(args.entry_text);
    entry.set_visibility(!args.hide_text);
    entry.set_activates_default(true);
    box->pack_start(entry, Gtk::PACK_SHRINK);
    dlg.add_button(args.cancel_label.empty() ? Glib::ustring("_Cancel")
                                             : args.cancel_label,
                   Gtk::RESPONSE_CANCEL);
    dlg.add_button(args.ok_label.empty() ? Glib::ustring("_OK")
                                         : args.ok_label,
                   Gtk::RESPONSE_OK);
    dlg.set_default_response(Gtk::RESPONSE_OK);
    setupTimeout(dlg, args);
    dlg.show_all();
    dlg.present();
    int ret = mapResponse(dlg.run());
    if (ret == EXIT_OK) {
        std::string out = entry.get_text();
        std::printf("%s\n", out.c_str());
        std::fflush(stdout);
    }
    return ret;
}


//-----------------------------------------------------------------------------
// list
//-----------------------------------------------------------------------------

int runList(const Args &args)
{
    const bool toggles = args.checklist || args.radiolist;
    const size_t ncols = args.columns.size();
    if (ncols == 0) {
        std::fprintf(stderr, "ART-dialogs: --list requires --column\n");
        return EXIT_ERROR;
    }
    if (toggles && ncols < 2) {
        std::fprintf(stderr,
                     "ART-dialogs: --checklist/--radiolist need a toggle "
                     "column followed by at least one more\n");
        return EXIT_ERROR;
    }

    Gtk::TreeModelColumnRecord rec;
    std::vector<std::unique_ptr<Gtk::TreeModelColumn<Glib::ustring>>> cols;
    for (size_t i = 0; i < ncols; ++i) {
        if (toggles && i == 0) {
            cols.emplace_back(); // placeholder, the toggle uses a bool column
            continue;
        }
        cols.emplace_back(new Gtk::TreeModelColumn<Glib::ustring>());
        rec.add(*cols.back());
    }
    Gtk::TreeModelColumn<bool> toggle_col;
    if (toggles) {
        rec.add(toggle_col);
    }
    auto store = Gtk::ListStore::create(rec);

    size_t idx = 0;
    bool radio_set = false;
    while (idx + ncols <= args.rows.size()) {
        auto row = *store->append();
        for (size_t i = 0; i < ncols; ++i) {
            auto &v = args.rows[idx + i];
            if (toggles && i == 0) {
                bool on = v == "TRUE" || v == "true" || v == "1";
                if (args.radiolist && on) {
                    if (radio_set) {
                        on = false;
                    }
                    radio_set = on || radio_set;
                }
                row[toggle_col] = on;
            } else {
                row[*cols[i]] = v;
            }
        }
        idx += ncols;
    }

    Gtk::Dialog dlg;
    setupWindow(dlg, args, "Select items from the list");
    if (args.width <= 0 && args.height <= 0) {
        dlg.set_default_size(400, 300);
    }
    auto box = dlg.get_content_area();
    box->set_spacing(12);
    box->set_border_width(12);
    makeLabel(args, *box);

    Gtk::TreeView view(store);
    view.set_headers_visible(!args.hide_header);
    auto hidden = [&](size_t i) {
        for (int h : args.hide_columns) {
            if (h == int(i) + 1) {
                return true;
            }
        }
        return false;
    };
    for (size_t i = 0; i < ncols; ++i) {
        if (toggles && i == 0) {
            auto r = Gtk::manage(new Gtk::CellRendererToggle());
            r->set_radio(args.radiolist);
            r->property_activatable() = true;
            r->signal_toggled().connect([&](const Glib::ustring &path) {
                auto it = store->get_iter(path);
                if (!it) {
                    return;
                }
                bool v = (*it)[toggle_col];
                if (args.radiolist) {
                    for (auto &o : store->children()) {
                        o[toggle_col] = false;
                    }
                    (*it)[toggle_col] = true;
                } else {
                    (*it)[toggle_col] = !v;
                }
            });
            auto c = Gtk::manage(new Gtk::TreeViewColumn(args.columns[0]));
            c->pack_start(*r, false);
            c->add_attribute(r->property_active(), toggle_col);
            c->set_visible(!hidden(0));
            view.append_column(*c);
        } else {
            auto n = view.append_column(args.columns[i], *cols[i]);
            auto c = view.get_column(n - 1);
            c->set_resizable(true);
            c->set_visible(!hidden(i));
        }
    }
    view.get_selection()->set_mode(args.multiple && !toggles
                                       ? Gtk::SELECTION_MULTIPLE
                                       : Gtk::SELECTION_SINGLE);
    view.signal_row_activated().connect(
        [&](const Gtk::TreeModel::Path &, Gtk::TreeViewColumn *) {
            dlg.response(Gtk::RESPONSE_OK);
        });
    Gtk::ScrolledWindow sw;
    sw.set_shadow_type(Gtk::SHADOW_IN);
    sw.add(view);
    box->pack_start(sw, Gtk::PACK_EXPAND_WIDGET);

    dlg.add_button(args.cancel_label.empty() ? Glib::ustring("_Cancel")
                                             : args.cancel_label,
                   Gtk::RESPONSE_CANCEL);
    dlg.add_button(args.ok_label.empty() ? Glib::ustring("_OK")
                                         : args.ok_label,
                   Gtk::RESPONSE_OK);
    dlg.set_default_response(Gtk::RESPONSE_OK);
    setupTimeout(dlg, args);
    dlg.show_all();
    dlg.present();
    int ret = mapResponse(dlg.run());
    if (ret != EXIT_OK) {
        return ret;
    }

    auto format = [&](const Gtk::TreeModel::Row &row) {
        std::vector<Glib::ustring> out;
        for (size_t i = 0; i < ncols; ++i) {
            if (toggles && i == 0) {
                continue;
            }
            if (args.print_column == 0 || size_t(args.print_column) == i + 1) {
                out.push_back(row[*cols[i]]);
            }
        }
        return joinStrings(out, args.separator);
    };
    std::vector<Glib::ustring> results;
    if (toggles) {
        for (auto &row : store->children()) {
            if (row[toggle_col]) {
                results.push_back(format(row));
            }
        }
    } else {
        for (auto &path : view.get_selection()->get_selected_rows()) {
            results.push_back(format(*store->get_iter(path)));
        }
    }
    std::string out = joinStrings(results, args.separator);
    std::printf("%s\n", out.c_str());
    std::fflush(stdout);
    return EXIT_OK;
}


//-----------------------------------------------------------------------------
// scale
//-----------------------------------------------------------------------------

int runScale(const Args &args)
{
    Gtk::Dialog dlg;
    setupWindow(dlg, args, "Select a value");
    if (args.width <= 0) {
        dlg.set_default_size(350, -1);
    }
    dlg.set_resizable(false);
    auto box = dlg.get_content_area();
    box->set_spacing(12);
    box->set_border_width(12);
    makeLabel(args, *box);
    Gtk::Scale scale(Gtk::ORIENTATION_HORIZONTAL);
    scale.set_range(args.min_value, args.max_value);
    scale.set_increments(args.step, args.step * 10);
    scale.set_digits(0);
    scale.set_value(args.value);
    box->pack_start(scale, Gtk::PACK_SHRINK);
    dlg.add_button(args.cancel_label.empty() ? Glib::ustring("_Cancel")
                                             : args.cancel_label,
                   Gtk::RESPONSE_CANCEL);
    dlg.add_button(args.ok_label.empty() ? Glib::ustring("_OK")
                                         : args.ok_label,
                   Gtk::RESPONSE_OK);
    dlg.set_default_response(Gtk::RESPONSE_OK);
    setupTimeout(dlg, args);
    dlg.show_all();
    dlg.present();
    int ret = mapResponse(dlg.run());
    if (ret == EXIT_OK) {
        std::printf("%d\n", int(scale.get_value()));
        std::fflush(stdout);
    }
    return ret;
}

} } // namespace art::dialogs
