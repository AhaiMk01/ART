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

#include "shortcutdefs.h"

namespace art { namespace gui {

/*
 * Every keyboard shortcut of the GUI, with the keys it has by default.
 *
 * Key specs are "[Primary+][Ctrl+][Alt+][Shift+]<GDK key name>" (see
 * parseShortcutKey). "Primary" is Ctrl, unless the user chose the OS key
 * (Cmd on macOS, the Windows key elsewhere) in the shortcuts editor.
 * Symbols that need Shift on some layouts ("plus", "less", "underscore",
 * ...) are written as the symbol itself and match however the layout types
 * them; letters and digits use an explicit Shift.
 *
 * Contexts say where an action is active. Two actions of the same context
 * and phase must not share a key (the unit test checks it); the same key in
 * different contexts is fine, the window decides the order in which it asks
 * the contexts. The ones in use are:
 *   window            F11, close tab (RTWindow and EditWindow)
 *   mainwindow        quit, switching main tabs (RTWindow only)
 *   editor            EditorPanel
 *   editor-scroll     EditorPanel, before the focus widget
 *   editor-before     EditorPanel, before the focus widget (masks)
 *   toolbar           the tool buttons next to the preview
 *   toolpanel         the tool notebook tabs
 *   tool              held-key adjuster shortcuts + F1 help
 *   tool-value        +/-/reset, only while an adjuster key is held
 *   filepanel         FilePanel
 *   filecatalog       FileCatalog (filters, panels, trash...)
 *   filecatalog-session  session buttons; they fall through to "filecatalog"
 *   filebrowser       FileBrowser (thumbnails)
 *   filebrowser-inspector  FileBrowser, while the inspector is active
 *   inspector, inspector-popover
 *   queuepanel, queue BatchQueuePanel, BatchQueue
 *   drawnmask
 *   saveas
 */
void defineDefaultShortcuts(ShortcutTable &t)
{
    using Phase = ShortcutPhase;
    const auto add = [&t](const char *id, const char *ctx,
                          std::vector<std::string> keys,
                          Phase phase = Phase::After) {
        t.define(ShortcutAction{id, ctx, std::move(keys), phase});
    };
    const auto digit = [](int i) { return std::to_string(i); };

    // ---- windows
    add("window.fullscreen", "window", {"F11"});
    add("window.close_tab", "window", {"Primary+w"});
    add("window.quit", "mainwindow", {"Primary+q"});
    add("window.show_file_browser", "mainwindow", {"Primary+F2"});
    add("window.show_queue", "mainwindow", {"Primary+F3"});
    add("window.show_editor", "mainwindow", {"Primary+F4"});

    // ---- editor
    add("editor.toggle_top_panel", "editor", {"Shift+l"});
    add("editor.toggle_history_panel", "editor", {"l"});
    add("editor.toggle_history_and_right_panels", "editor", {"Alt+l"});
    add("editor.toggle_right_panel", "editor", {"Primary+l"});
    add("editor.maximize_preview", "editor", {"m"});
    add("editor.maximize_preview_fit", "editor", {"Shift+m"});
    add("editor.toggle_preview_background", "editor", {"9"});
    add("editor.rotate_right", "editor", {"bracketright"});
    add("editor.rotate_left", "editor", {"bracketleft"});
    add("editor.toggle_info", "editor", {"Shift+i"});
    add("editor.toggle_before_after", "editor", {"Shift+a"});
    add("editor.zoom_in", "editor", {"plus", "equal", "KP_Add"});
    add("editor.zoom_out", "editor", {"minus", "underscore", "KP_Subtract"});
    add("editor.zoom_100", "editor", {"z"});
    add("editor.zoom_fit", "editor", {"f"});
    add("editor.toggle_red_preview", "editor", {"Shift+r"});
    add("editor.toggle_green_preview", "editor", {"Shift+g"});
    add("editor.toggle_blue_preview", "editor", {"Shift+b"});
    add("editor.toggle_luminosity_preview", "editor", {"Shift+v"});
    add("editor.toggle_sharpening_mask", "editor", {"Shift+o"});
    add("editor.toggle_focus_mask", "editor", {"Shift+f"});
    add("editor.toggle_false_colors", "editor", {"Shift+e"});
    add("editor.toggle_shadow_clipping", "editor", {"less"});
    add("editor.toggle_highlight_clipping", "editor", {"greater"});
    add("editor.sync_file_browser", "editor", {"y"});
    add("editor.sync_file_browser_clear_filters", "editor", {"x"});
    add("editor.save", "editor", {"Primary+s"});
    add("editor.save_fast", "editor", {"Primary+Shift+s"});
    add("editor.queue", "editor", {"Primary+b"});
    add("editor.queue_fast", "editor", {"Primary+Shift+b"});
    add("editor.send_to_external_editor", "editor", {"Primary+e"});
    add("editor.send_to_external_editor_alt", "editor", {"Primary+Shift+e"});
    add("editor.undo", "editor", {"Primary+z"});
    add("editor.redo", "editor", {"Primary+Shift+z", "Primary+y"});
    add("editor.previous_snapshot", "editor", {"Primary+comma"});
    add("editor.next_snapshot", "editor", {"Primary+period"});
    add("editor.toggle_grid", "editor", {"Primary+g"});
    add("editor.add_snapshot", "editor", {"Alt+s"});
    add("editor.previous_image", "editor", {"Shift+F3"});
    add("editor.next_image", "editor", {"Shift+F4"});
    add("editor.scroll_up", "editor-scroll", {"Primary+Up", "Primary+KP_Up"},
        Phase::Before);
    add("editor.scroll_down", "editor-scroll",
        {"Primary+Down", "Primary+KP_Down"}, Phase::Before);
    add("editor.scroll_left", "editor-scroll",
        {"Primary+Left", "Primary+KP_Left"}, Phase::Before);
    add("editor.scroll_right", "editor-scroll",
        {"Primary+Right", "Primary+KP_Right"}, Phase::Before);

    // ---- tool selection and tool panel tabs
    add("toolbar.white_balance_picker", "toolbar", {"Shift+w"});
    add("toolbar.crop", "toolbar", {"Shift+c"});
    add("toolbar.straighten", "toolbar", {"Shift+s"});
    add("toolbar.hand", "toolbar", {"h", "Shift+h"});
    add("toolbar.perspective", "toolbar", {"Shift+p"});

    add("toolpanel.tab_favorites", "toolpanel", {"Alt+u"});
    add("toolpanel.tab_exposure", "toolpanel", {"Alt+e"});
    add("toolpanel.tab_details", "toolpanel", {"Alt+d"});
    add("toolpanel.tab_color", "toolpanel", {"Alt+c"});
    add("toolpanel.tab_transform", "toolpanel", {"Alt+t"});
    add("toolpanel.tab_raw", "toolpanel", {"Alt+r"});
    add("toolpanel.tab_effects", "toolpanel", {"Alt+f"});
    add("toolpanel.tab_local", "toolpanel", {"Alt+x"});
    add("toolpanel.tab_metadata", "toolpanel", {"Alt+m"});

    // ---- held-key adjuster shortcuts: hold the key and use +/-/scroll
    add("tool.help", "tool", {"F1"});
    add("tool.exposure.compensation", "tool", {"e"});
    add("tool.exposure.black", "tool", {"q"});
    add("tool.tonecurve.contrast", "tool", {"c"});
    add("tool.saturation.saturation", "tool", {"s"});
    add("tool.saturation.vibrance", "tool", {"v"});
    add("tool.labcurve.brightness", "tool", {"i"});
    add("tool.labcurve.contrast", "tool", {"j"});
    add("tool.labcurve.chromaticity", "tool", {"n"});
    add("tool.whitebalance.temperature", "tool", {"t"});
    // was "i" too, but ToolShortcutManager keeps one adjuster per key and
    // LabCurve registers after WhiteBalance, so "i" has always been
    // brightness; bind this one to a free key in shortcuts.json if wanted
    add("tool.whitebalance.tint", "tool", {});
    add("tool.logencoding.gain", "tool", {"g"});
    add("tool.logencoding.target_gray", "tool", {"b"});
    add("tool.logencoding.white_ev", "tool", {"w"});
    add("tool.logencoding.black_ev", "tool", {"d"});
    add("tool.logencoding.highlight_compression", "tool", {"k"});
    for (int i = 1; i <= 5; ++i) {
        add(("tool.toneequalizer.band." + digit(i)).c_str(), "tool",
            {digit(i)});
    }
    add("tool.softlight.strength", "tool", {"o"});
    add("tool.value_up", "tool-value", {"plus", "equal", "KP_Add"});
    add("tool.value_down", "tool-value", {"minus", "KP_Subtract"});
    add("tool.value_zero", "tool-value", {"asterisk", "KP_Multiply", "0"});
    add("tool.value_initial", "tool-value", {"slash", "KP_Divide"});

    // ---- file panel and file catalog
    add("filepanel.toggle_right_notebook", "filepanel",
        {"Primary+i", "Primary+Shift+i"});

    add("filecatalog.toggle_left_panel", "filecatalog", {"l"});
    add("filecatalog.toggle_right_panel", "filecatalog", {"Primary+l"});
    add("filecatalog.toggle_left_and_right_panels", "filecatalog",
        {"Primary+Alt+l"});
    add("filecatalog.maximize", "filecatalog", {"m"});
    add("filecatalog.reset_path", "filecatalog", {"Escape"});
    // the Primary variants add to the current filter instead of replacing it
    add("filecatalog.filter_unranked", "filecatalog", {"0", "Primary+0"});
    for (int i = 1; i <= 5; ++i) {
        add(("filecatalog.filter_rank." + digit(i)).c_str(), "filecatalog",
            {digit(i), "Primary+" + digit(i)});
    }
    add("filecatalog.filter_not_edited", "filecatalog", {"6", "Primary+6"});
    add("filecatalog.filter_edited", "filecatalog", {"7", "Primary+7"});
    add("filecatalog.filter_no_label", "filecatalog",
        {"Alt+0", "Primary+Alt+0"});
    for (int i = 1; i <= 5; ++i) {
        add(("filecatalog.filter_label." + digit(i)).c_str(), "filecatalog",
            {"Alt+" + digit(i), "Primary+Alt+" + digit(i)});
    }
    add("filecatalog.filter_not_recently_saved", "filecatalog",
        {"Alt+6", "Primary+Alt+6"});
    add("filecatalog.filter_recently_saved", "filecatalog",
        {"Alt+7", "Primary+Alt+7"});
    add("filecatalog.filter_clear", "filecatalog", {"d", "Shift+d"});
    add("filecatalog.browse", "filecatalog", {"Return", "KP_Enter"});
    add("filecatalog.toggle_exif", "filecatalog", {"i", "Alt+i"});
    add("filecatalog.zoom_in", "filecatalog",
        {"plus", "equal", "Alt+plus", "Alt+equal"});
    add("filecatalog.zoom_out", "filecatalog",
        {"minus", "underscore", "Alt+minus", "Alt+underscore"});
    add("filecatalog.focus_path", "filecatalog",
        {"Primary+o", "Primary+Shift+o"});
    add("filecatalog.focus_query", "filecatalog", {"Primary+f"});
    add("filecatalog.toggle_trash", "filecatalog",
        {"Primary+t", "Primary+Shift+t"});
    add("filecatalog.empty_trash", "filecatalog", {"Primary+Shift+Delete"});
    add("filecatalog.toggle_toolbar", "filecatalog", {"t", "Shift+t"});
    add("filecatalog.refresh", "filecatalog", {"F5"});
    // each is only active while its button is visible, otherwise the key is
    // passed on (Primary+o to filecatalog.focus_path)
    add("filecatalog.session_load", "filecatalog-session", {"Primary+o"});
    add("filecatalog.session_add", "filecatalog-session", {"Primary+plus"});
    add("filecatalog.session_remove", "filecatalog-session",
        {"Primary+minus"});
    add("filecatalog.session_save", "filecatalog-session", {"Primary+s"});

    // ---- file browser (thumbnails)
    add("filebrowser.inspector_popover", "filebrowser", {"Primary+space"});
    add("filebrowser.copy_to", "filebrowser", {"Primary+Shift+c"});
    add("filebrowser.move_to", "filebrowser", {"Primary+Shift+m"});
    add("filebrowser.copy_profile", "filebrowser",
        {"Primary+c", "Primary+Insert"});
    add("filebrowser.paste_profile", "filebrowser",
        {"Primary+v", "Shift+Insert"});
    add("filebrowser.paste_profile_partial", "filebrowser",
        {"Primary+Shift+v"});
    add("filebrowser.trash", "filebrowser", {"Delete"});
    add("filebrowser.untrash", "filebrowser", {"Shift+Delete"});
    add("filebrowser.remove", "filebrowser", {"Primary+Shift+Delete"});
    add("filebrowser.queue", "filebrowser", {"Primary+b"});
    add("filebrowser.queue_fast", "filebrowser", {"Primary+Shift+b"});
    add("filebrowser.select_all", "filebrowser", {"Primary+a"});
    add("filebrowser.rename", "filebrowser", {"F2"});
    add("filebrowser.add_to_session", "filebrowser", {"Primary+Shift+s"});
    add("filebrowser.open_previous", "filebrowser", {"F3"});
    add("filebrowser.open_next", "filebrowser", {"F4"});
    add("filebrowser.select_previous", "filebrowser",
        {"Left", "BackSpace", "Shift+Left", "Shift+BackSpace"});
    add("filebrowser.select_next", "filebrowser",
        {"Right", "space", "Shift+Right", "Shift+space"});
    add("filebrowser.select_row_up", "filebrowser", {"Up", "Shift+Up"});
    add("filebrowser.select_row_down", "filebrowser", {"Down", "Shift+Down"});
    add("filebrowser.select_first", "filebrowser", {"Home", "Shift+Home"});
    add("filebrowser.select_last", "filebrowser", {"End", "Shift+End"});
    add("filebrowser.open", "filebrowser", {"Return", "KP_Enter"});
    add("filebrowser.page_up", "filebrowser", {"Page_Up"});
    add("filebrowser.page_down", "filebrowser", {"Page_Down"});
    for (int i = 0; i <= 5; ++i) {
        add(("filebrowser.set_rank." + digit(i)).c_str(), "filebrowser",
            {"Shift+" + digit(i)});
        add(("filebrowser.set_label." + digit(i)).c_str(), "filebrowser",
            {"Primary+Shift+" + digit(i)});
    }

    // while the inspector is shown the bare digit ranks and Primary+digit
    // sets the colour label (the file catalog's filter keys do not get here
    // when the thumbnails have the focus)
    for (int i = 0; i <= 5; ++i) {
        add(("filebrowser.inspector_set_rank." + digit(i)).c_str(),
            "filebrowser-inspector", {digit(i)});
        add(("filebrowser.inspector_set_label." + digit(i)).c_str(),
            "filebrowser-inspector", {"Primary+" + digit(i)});
    }

    // ---- inspector
    add("inspector.toggle_histogram", "inspector", {"h"});
    add("inspector.toggle_cms", "inspector", {"c"});
    add("inspector.zoom_100", "inspector", {"z"});
    add("inspector.zoom_fit", "inspector", {"x"});
    add("inspector.mode_jpeg", "inspector", {"j"});
    add("inspector.mode_raw_linear", "inspector", {"r"});
    add("inspector.mode_raw_film_curve", "inspector", {"f"});
    add("inspector.mode_raw_shadow_boost", "inspector", {"s"});
    add("inspector.mode_raw_clip_warning", "inspector", {"w"});
    add("inspector.toggle_split", "inspector", {"y"});
    add("inspector.switch_pane", "inspector", {"Tab"});
    add("inspector.toggle_focus_mask", "inspector", {"Shift+f"});
    add("inspector.toggle_info", "inspector", {"Shift+i"});
    add("inspector.popover.mode_jpeg", "inspector-popover", {"j"});
    add("inspector.popover.mode_raw_linear", "inspector-popover", {"r"});
    add("inspector.popover.mode_raw_film_curve", "inspector-popover", {"f"});
    add("inspector.popover.mode_raw_shadow_boost", "inspector-popover",
        {"s"});
    add("inspector.popover.mode_raw_clip_warning", "inspector-popover",
        {"w"});

    // ---- batch queue
    add("queue.start_stop", "queuepanel", {"Primary+s"});
    add("queue.select_all", "queue", {"Primary+a"});
    add("queue.open_in_editor", "queue", {"Primary+e"});
    add("queue.select_first", "queue", {"Home", "Shift+Home"});
    add("queue.select_last", "queue", {"End", "Shift+End"});
    add("queue.move_to_head", "queue", {"Primary+Home"});
    add("queue.move_to_tail", "queue", {"Primary+End"});
    add("queue.cancel", "queue", {"Delete"});
    add("queue.select_previous", "queue", {"Left", "Shift+Left"});
    add("queue.select_next", "queue", {"Right", "Shift+Right"});
    add("queue.select_row_up", "queue", {"Up", "Shift+Up"});
    add("queue.select_row_down", "queue", {"Down", "Shift+Down"});

    // ---- masks and dialogs
    // the drawn mask panel sees the key before the focused widget does
    add("drawnmask.undo", "drawnmask", {"Primary+z"}, Phase::Before);
    add("drawnmask.reset", "drawnmask", {"Primary+Shift+z"}, Phase::Before);
    // the mask panel that the user last worked on, if its tool is visible, and
    // wherever the focus is in the editor (the panels keep track of it). Ctrl+X is asked before the focused widget: the
    // masks list would pass it to its search box, which cuts. A text field
    // that has the focus keeps its keys.
    add("masks.toggle_show", "editor", {"Primary+m"});
    add("masks.toggle_selected_enabled", "editor-before", {"Primary+x"},
        Phase::Before);
    add("saveas.ok", "saveas", {"Primary+Return", "Primary+KP_Enter"});
}

} } // namespace art::gui
