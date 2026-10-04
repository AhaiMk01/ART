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
 *  along with ART.  If not, see <https://www.gnu.org/licenses/>.
 */

// The control channel: a local TCP endpoint through which the Live server
// (tools/mcp, art-mcp-live) reads and changes the images open in this editor.
//
// Listens on 127.0.0.1 on an ephemeral port, on the GTK main loop. The port
// and a random per-run token go to live-control.json in the user config dir;
// a client must send {"token": "..."} as its first line, then JSON-lines
// requests {"id", "op", "args"}, each answered by
// {"id", "ok": true, "result"} or {"id", "ok": false, "error": {"code",
// "message"}}.
//
// Everything runs on the main loop without ever blocking it: reads and writes
// are asynchronous, a slow reader only stalls its own connection, and the
// number of clients, the time to authenticate and the size of lines and
// pending replies are all bounded.

#pragma once

#include <map>
#include <memory>
#include <set>
#include <string>

#include <gio/gio.h>

namespace art { namespace gui {

class RTWindow;
class EditorPanel;

class LiveControl {
public:
    // Starts the control channel for this window; nullptr (with a message
    // on stderr) if it can't listen or write the discovery file.
    static std::unique_ptr<LiveControl> start(RTWindow *window);

    // Stops listening, drops the clients and removes the discovery file.
    ~LiveControl();

    struct Connection;

private:
    explicit LiveControl(RTWindow *window);
    LiveControl(const LiveControl &) = delete;
    LiveControl &operator=(const LiveControl &) = delete;

    static gboolean on_incoming(GSocketService *service,
                                GSocketConnection *connection,
                                GObject *source, gpointer data);
    static void on_read(GObject *source, GAsyncResult *res, gpointer data);
    static void on_write(GObject *source, GAsyncResult *res, gpointer data);
    static gboolean on_auth_timeout(gpointer data);
    static gboolean on_write_stall(gpointer data);

    void read_more(Connection *c);
    // Handles the complete lines received so far, then reads on unless the
    // client's unsent replies are over the limit. May close (and free) c.
    void pump(Connection *c);
    // Handles one complete line; false closes the connection.
    bool handle_line(Connection *c, const std::string &line);
    // Queues a reply line and starts sending it if nothing else is.
    void send(Connection *c, std::string reply);
    void start_write(Connection *c);
    // The string-valued members of a request's args (no op takes any
    // other kind yet).
    typedef std::map<std::string, std::string> Args;
    std::string dispatch(const std::string &op, const Args &args, bool &ok);
    std::string status();
    std::string get_profile(const Args &args, bool &ok);
    // Applies .arp partial-profile text to an open image as one History
    // entry described by "label".
    std::string apply_profile(const Args &args, bool &ok);
    // Undo, or redo if `forward`, one History step of an open image.
    std::string step_history(const Args &args, bool forward, bool &ok);
    // Opens an image in the editor (selects it if it is open already).
    std::string open(const Args &args, bool &ok);
    // Saves an open image's profile as the editor does (sidecar and cache).
    std::string save_sidecar(const Args &args, bool &ok);
    // The editor showing the image `op`'s "path" arg names; nullptr with
    // `error` set (an error object) otherwise.
    EditorPanel *editor_for(const std::string &op, const Args &args,
                            std::string &error);
    // The editor showing `path` (compared as the OS compares paths), or
    // nullptr.
    EditorPanel *find_editor(const std::string &path);
    void close(Connection *c);

    bool write_discovery_file();
    void remove_discovery_file();

    RTWindow *window_;
    GSocketService *service_;
    unsigned port_;
    std::string token_;
    std::string discovery_path_;
    std::set<Connection *> connections_;
};

}} // namespace art::gui
