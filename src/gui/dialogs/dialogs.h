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
#pragma once

#include <glibmm.h>
#include <string>
#include <vector>

namespace art { namespace dialogs {

// exit codes, as in zenity
enum ExitCode {
    EXIT_OK = 0,
    EXIT_CANCEL = 1,
    EXIT_TIMEOUT = 5,
    EXIT_ERROR = 255
};

enum class Kind {
    NONE,
    INFO,
    WARNING,
    ERROR,
    QUESTION,
    PROGRESS,
    FILE_SELECTION,
    ENTRY,
    LIST,
    SCALE
};

struct Args {
    Kind kind = Kind::NONE;

    // common
    Glib::ustring title;
    Glib::ustring text;
    Glib::ustring ok_label;
    Glib::ustring cancel_label;
    int width = -1;
    int height = -1;
    int timeout = 0; // seconds, 0 = none
    bool no_wrap = false;
    bool no_markup = false;

    // --progress
    int percentage = 0;
    bool pulsate = false;
    bool auto_close = false;
    bool auto_kill = false;
    bool no_cancel = false;

    // --file-selection
    bool save = false;
    bool directory = false;
    bool multiple = false;
    bool confirm_overwrite = false;
    Glib::ustring filename;
    std::vector<Glib::ustring> filters; // "Name | *.ext *.ext2"

    // --entry
    Glib::ustring entry_text;
    bool hide_text = false;

    // --list
    std::vector<Glib::ustring> columns;
    bool checklist = false;
    bool radiolist = false;
    bool hide_header = false;
    int print_column = 1; // 1-based; 0 = all
    std::vector<int> hide_columns; // 1-based
    std::vector<Glib::ustring> rows; // remaining positional arguments

    // --scale
    double value = 0;
    double min_value = 0;
    double max_value = 100;
    double step = 1;

    // --file-selection and --list
    Glib::ustring separator = "|";
};

// Each of these runs the dialog (blocking), prints the result (if any) to
// stdout and returns the process exit code.
int runMessage(const Args &args);
int runProgress(const Args &args);
int runFileSelection(const Args &args);
int runEntry(const Args &args);
int runList(const Args &args);
int runScale(const Args &args);

} } // namespace art::dialogs
