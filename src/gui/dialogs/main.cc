/* -*- C++ -*-
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
// ART-dialogs: a small replacement for the subset of zenity that ART user
// commands need, with the look of the main ART window.
#include "dialogs.h"
#include "theme.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <gtkmm.h>
#include <string>

using namespace art::dialogs;

namespace {

void usage(FILE *out)
{
    std::fprintf(out, "%s",
        "Usage: ART-dialogs <dialog> [options] [rows...]\n"
        "\n"
        "A zenity-like dialog tool. Dialogs:\n"
        "  --info | --warning | --error | --question   message dialogs\n"
        "  --progress        read percentages (\"NN\") and labels (\"# text\") on stdin\n"
        "  --file-selection  print the chosen path(s) to stdout\n"
        "  --entry           print the entered text to stdout\n"
        "  --list            print the selected row(s) to stdout\n"
        "  --scale           print the chosen value to stdout\n"
        "\n"
        "Common options: --title= --text= --width= --height= --ok-label=\n"
        "  --cancel-label= --timeout= --no-wrap --no-markup\n"
        "--progress:  --percentage= --pulsate --auto-close --auto-kill --no-cancel\n"
        "--file-selection:  --save --directory --multiple --separator= --filename=\n"
        "  --file-filter=\"Name | *.ext *.ext2\" (repeatable) --confirm-overwrite\n"
        "--entry:  --entry-text= --hide-text\n"
        "--list:  --column= (repeatable) --checklist --radiolist --multiple\n"
        "  --print-column=N|ALL --hide-column=N --hide-header --separator=\n"
        "--scale:  --value= --min-value= --max-value= --step=\n"
        "\n"
        "Exit status: 0 OK/yes, 1 cancel/no/closed, 5 timeout, 255 error.\n");
}


[[noreturn]] void fail(const std::string &msg)
{
    std::fprintf(stderr, "ART-dialogs: %s\n", msg.c_str());
    std::exit(EXIT_ERROR);
}


bool toInt(const std::string &s, int &out)
{
    char *end = nullptr;
    long v = std::strtol(s.c_str(), &end, 10);
    if (s.empty() || *end) {
        return false;
    }
    out = int(v);
    return true;
}


bool toDouble(const std::string &s, double &out)
{
    char *end = nullptr;
    double v = std::strtod(s.c_str(), &end);
    if (s.empty() || *end) {
        return false;
    }
    out = v;
    return true;
}


void setKind(Args &args, Kind k)
{
    if (args.kind != Kind::NONE && args.kind != k) {
        fail("only one dialog type can be given");
    }
    args.kind = k;
}


Args parse(int argc, char **argv)
{
    Args args;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a.size() < 3 || a[0] != '-' || a[1] != '-') {
            args.rows.push_back(a);
            continue;
        }
        std::string name = a.substr(2);
        std::string val;
        bool has_val = false;
        auto eq = name.find('=');
        if (eq != std::string::npos) {
            val = name.substr(eq + 1);
            name = name.substr(0, eq);
            has_val = true;
        }
        // options taking a value accept both "--opt=value" and "--opt value"
        auto value = [&]() -> std::string {
            if (has_val) {
                return val;
            }
            if (i + 1 >= argc) {
                fail("option --" + name + " requires a value");
            }
            return argv[++i];
        };
        auto intval = [&]() {
            int r;
            auto v = value();
            if (!toInt(v, r)) {
                fail("invalid number for --" + name + ": " + v);
            }
            return r;
        };
        auto dblval = [&]() {
            double r;
            auto v = value();
            if (!toDouble(v, r)) {
                fail("invalid number for --" + name + ": " + v);
            }
            return r;
        };
        auto noval = [&]() {
            if (has_val) {
                fail("option --" + name + " does not take a value");
            }
        };

        if (name == "help" || name == "usage" || name == "help-all") {
            usage(stdout);
            std::exit(EXIT_OK);
        } else if (name == "version") {
            std::printf("ART-dialogs\n");
            std::exit(EXIT_OK);
        }
        // dialog types
        else if (name == "info") {
            noval();
            setKind(args, Kind::INFO);
        } else if (name == "warning") {
            noval();
            setKind(args, Kind::WARNING);
        } else if (name == "error") {
            noval();
            setKind(args, Kind::ERROR);
        } else if (name == "question") {
            noval();
            setKind(args, Kind::QUESTION);
        } else if (name == "progress") {
            noval();
            setKind(args, Kind::PROGRESS);
        } else if (name == "file-selection") {
            noval();
            setKind(args, Kind::FILE_SELECTION);
        } else if (name == "entry") {
            noval();
            setKind(args, Kind::ENTRY);
        } else if (name == "list") {
            noval();
            setKind(args, Kind::LIST);
        } else if (name == "scale") {
            noval();
            setKind(args, Kind::SCALE);
        }
        // common
        else if (name == "title") {
            args.title = value();
        } else if (name == "text") {
            args.text = value();
        } else if (name == "width") {
            args.width = intval();
        } else if (name == "height") {
            args.height = intval();
        } else if (name == "ok-label") {
            args.ok_label = value();
        } else if (name == "cancel-label") {
            args.cancel_label = value();
        } else if (name == "timeout") {
            args.timeout = intval();
        } else if (name == "no-wrap") {
            noval();
            args.no_wrap = true;
        } else if (name == "no-markup") {
            noval();
            args.no_markup = true;
        }
        // accepted for zenity compatibility, no effect
        else if (name == "modal" || name == "ellipsize" ||
                 name == "no-selection") {
            noval();
        } else if (name == "window-icon" || name == "icon-name" ||
                   name == "icon" || name == "display" || name == "class" ||
                   name == "name" || name == "attach" || name == "width-chars") {
            value();
        }
        // progress
        else if (name == "percentage") {
            args.percentage = intval();
        } else if (name == "pulsate") {
            noval();
            args.pulsate = true;
        } else if (name == "auto-close") {
            noval();
            args.auto_close = true;
        } else if (name == "auto-kill") {
            noval();
            args.auto_kill = true;
        } else if (name == "no-cancel") {
            noval();
            args.no_cancel = true;
        }
        // file selection
        else if (name == "save") {
            noval();
            args.save = true;
        } else if (name == "directory") {
            noval();
            args.directory = true;
        } else if (name == "multiple") {
            noval();
            args.multiple = true;
        } else if (name == "confirm-overwrite") {
            noval();
            args.confirm_overwrite = true;
        } else if (name == "filename") {
            args.filename = value();
        } else if (name == "file-filter") {
            args.filters.push_back(value());
        } else if (name == "separator") {
            args.separator = value();
        }
        // entry
        else if (name == "entry-text") {
            args.entry_text = value();
        } else if (name == "hide-text") {
            noval();
            args.hide_text = true;
        }
        // list
        else if (name == "column") {
            args.columns.push_back(value());
        } else if (name == "checklist") {
            noval();
            args.checklist = true;
        } else if (name == "radiolist") {
            noval();
            args.radiolist = true;
        } else if (name == "hide-header") {
            noval();
            args.hide_header = true;
        } else if (name == "print-column") {
            auto v = value();
            if (v == "ALL" || v == "all") {
                args.print_column = 0;
            } else if (!toInt(v, args.print_column) || args.print_column < 1) {
                fail("invalid value for --print-column: " + v);
            }
        } else if (name == "hide-column") {
            args.hide_columns.push_back(intval());
        }
        // scale
        else if (name == "value") {
            args.value = dblval();
        } else if (name == "min-value") {
            args.min_value = dblval();
        } else if (name == "max-value") {
            args.max_value = dblval();
        } else if (name == "step") {
            args.step = dblval();
        } else {
            fail("unknown option --" + name);
        }
    }

    if (args.kind == Kind::NONE) {
        usage(stderr);
        std::exit(EXIT_ERROR);
    }
    return args;
}

} // namespace


int main(int argc, char **argv)
{
    Args args = parse(argc, argv);

    // our own options are already parsed, do not let GTK see them
    int gargc = 1;
    char *gargv_arr[] = {argv[0], nullptr};
    char **gargv = gargv_arr;
    Glib::init();
    Gio::init();
    try {
        Gtk::Main kit(gargc, gargv);
        applyTheme(argv[0]);

        switch (args.kind) {
        case Kind::INFO:
        case Kind::WARNING:
        case Kind::ERROR:
        case Kind::QUESTION:
            return runMessage(args);
        case Kind::PROGRESS:
            return runProgress(args);
        case Kind::FILE_SELECTION:
            return runFileSelection(args);
        case Kind::ENTRY:
            return runEntry(args);
        case Kind::LIST:
            return runList(args);
        case Kind::SCALE:
            return runScale(args);
        default:
            break;
        }
    } catch (Glib::Error &e) {
        std::fprintf(stderr, "ART-dialogs: %s\n", e.what().c_str());
    }
    return EXIT_ERROR;
}
