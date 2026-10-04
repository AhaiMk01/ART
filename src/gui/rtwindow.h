/* -*- C++ -*-
 *
 *  This file is part of RawTherapee.
 *
 *
 *  RawTherapee is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, either version 3 of the License, or
 *  (at your option) any later version.
 *
 *  RawTherapee is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with RawTherapee.  If not, see <http://www.gnu.org/licenses/>.
 */
#pragma once

#include "batchqueuepanel.h"
#include "editorpanel.h"
#include "filepanel.h"
#include "progressconnector.h"
#include "splash.h"
#include <gtkmm.h>
#include <memory>
#include <set>

namespace art { namespace gui {


class EditWindow;
class LiveControl;

class MessageWindow: public Gtk::Window {
public:
    MessageWindow();
    virtual ~MessageWindow();

    virtual void showInfo(const Glib::ustring &msg, double duration);
    virtual void showError(const Glib::ustring &msg);

protected:
    void init(Gtk::Widget *main_widget);

    void show_info_msg(const Glib::ustring &msg, bool is_error, double duration,
                       size_t padding);
    bool hide_info_msg();

    Gtk::Overlay *main_overlay_;
    Gtk::Revealer *msg_revealer_;
    Gtk::Label *info_label_;
    Gtk::Box *info_box_;
    RTImage *info_image_;
    std::set<Glib::ustring> unique_info_msg_;
    std::vector<Glib::ustring> info_msg_;
    int info_msg_num_;
    sigc::connection reveal_conn_;
};

class RTWindow: public MessageWindow, public art::engine::ProgressListener {
public:
    RTWindow();
    ~RTWindow() override;

    void addEditorPanel(EditorPanel *ep, const std::string &name);
    void remEditorPanel(EditorPanel *ep);
    bool selectEditorPanel(const std::string &name);
    // The editor the user is looking at, or nullptr if none has an image.
    EditorPanel *getActiveEditorPanel();
    // Every editor that has an image open.
    std::vector<EditorPanel *> getEditorPanels();

    void addBatchQueueJob(BatchQueueEntry *bqe, bool head = false);
    void addBatchQueueJobs(const std::vector<BatchQueueEntry *> &entries);

    bool keyPressed(GdkEventKey *event);
    bool keyPressedBefore(GdkEventKey *event);
    bool keyReleased(GdkEventKey *event);
    bool scrollPressed(GdkEventScroll *event);

    bool on_configure_event(GdkEventConfigure *event) override;
    bool on_delete_event(GdkEventAny *event) override;
    bool on_window_state_event(GdkEventWindowState *event) override;
    void on_mainNB_switch_page(Gtk::Widget *widget, guint page_num);

    void showPreferences();
    void on_realize() override;
    bool on_draw(const ::Cairo::RefPtr<::Cairo::Context> &cr) override;
    void toggle_fullscreen();

    void setProgress(double p) override;
    void setProgressStr(const Glib::ustring &str) override;
    void setProgressState(bool inProcessing) override;
    void error(const Glib::ustring &descr) override;

    void showInfo(const Glib::ustring &msg, double duration) override;
    void showError(const Glib::ustring &msg) override;

    art::engine::ProgressListener *getProgressListener() { return pldBridge; }

    EditorPanel *epanel;
    FilePanel *fpanel;

    void SetEditorCurrent();
    void SetMainCurrent();
    void MoveFileBrowserToEditor();
    void MoveFileBrowserToMain();

    void updateProfiles(const Glib::ustring &printerProfile,
                        art::engine::RenderingIntent printerIntent,
                        bool printerBPC);
    void updateTPVScrollbar(bool hide);
    void updateHistogramPosition(int oldPosition, int newPosition);
    void updateFBQueryTB(bool singleRow);
    void updateFBToolBarVisibility(bool showFilmStripToolBar);
    bool getIsFullscreen() { return is_fullscreen; }
    void set_title_decorated(Glib::ustring fname);
    void closeOpenEditors();
    void setEditorMode(bool tabbedUI);
    void createSetmEditor();

    void writeToolExpandedStatus(std::vector<int> &tpOpen);

    // void showInfo(const Glib::ustring &msg, double duration=0.0);
    void setApplication(bool yes) { is_application_ = yes; }
    bool isApplication() const { return is_application_; }

    Gtk::Label *getFileBrowserTabLabel() { return browser_tab_label_; }

    void quit();

    // The control channel (see livecontrol.h). It runs when the Preferences
    // option is on or ART was started with --live-control ("flag").
    // initLiveControl is called once at startup; setLiveControl by the
    // Preferences dialog when the option changes (off stops the channel even
    // if the flag started it).
    void initLiveControl(bool flag);
    void setLiveControl(bool on);
    unsigned liveControlPort() const; // 0 if not running
    bool liveControlFailed() const { return live_control_failed_; }

private:
    // void show_info_msg(const Glib::ustring &msg, bool is_error, double
    // duration, size_t padding); bool hide_info_msg(); Gtk::Overlay
    // *main_overlay_; Gtk::Revealer *msg_revealer_; Gtk::Label *info_label_;
    // Gtk::Box *info_box_;
    // RTImage *info_image_;
    // std::set<Glib::ustring> unique_info_msg_;
    // std::vector<Glib::ustring> info_msg_;
    // int info_msg_num_;
    // sigc::connection reveal_conn_;

    Gtk::Notebook *mainNB;
    BatchQueuePanel *bpanel;
    std::set<Glib::ustring> filesEdited;
    std::map<Glib::ustring, EditorPanel *> epanels;

    Splash *splash;
    Gtk::ProgressBar prProgBar;
    PLDBridge *pldBridge;
    bool is_fullscreen;
    bool on_delete_has_run;
    Gtk::Button *btn_fullscreen;

    Gtk::Image *iFullscreen, *iFullscreen_exit;

    Gtk::Label *browser_tab_label_;

    bool isSingleTabMode()
    {
        return !options.tabbedUI && !(options.multiDisplayMode > 0);
    };

    bool on_expose_event_epanel(GdkEventExpose *event);
    bool on_expose_event_fpanel(GdkEventExpose *event);
    bool splashClosed(GdkEventAny *event);
    bool isEditorPanel(Widget *panel);
    bool isEditorPanel(guint pageNum);
    void showErrors();

    Glib::ustring versionStr;

    IdleRegister idle_register;
    bool is_application_;
    std::unique_ptr<LiveControl> live_control_;
    bool live_control_failed_;
};


} } // namespace art::gui
