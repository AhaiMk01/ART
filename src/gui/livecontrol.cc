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

#ifdef WIN32
#define _CRT_RAND_S // rand_s, before any include of stdlib.h
#endif

#include "livecontrol.h"
#include "../utils/version.h"
#include "editorpanel.h"
#include "guiutils.h"
#include "options.h"
#include "rtwindow.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <vector>

#include <fcntl.h>
#include <glib/gstdio.h>
#include <glibmm/miscutils.h>

#ifdef WIN32
#include <windows.h>
#else
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace art { namespace gui {

namespace {

const char *const DISCOVERY_FILE = "live-control.json";
// Longest line accepted before the token is checked, and after.
const size_t MAX_TOKEN_LINE = 1024;
const size_t MAX_REQUEST_LINE = 16 * 1024 * 1024;

//-----------------------------------------------------------------------------
// A small JSON reader: enough to take requests apart. Every value keeps its
// source text, so an id can be echoed back as it came.
//-----------------------------------------------------------------------------

struct JsonValue {
    enum Type { NUL, BOOLEAN, NUMBER, STRING, ARRAY, OBJECT };
    Type type = NUL;
    std::string str; // decoded STRING
    std::string raw; // the source text of this value
    std::vector<std::pair<std::string, JsonValue>> members; // OBJECT
    std::vector<JsonValue> items;                          // ARRAY

    const JsonValue *get(const std::string &key) const
    {
        for (auto &m : members) {
            if (m.first == key) {
                return &m.second;
            }
        }
        return nullptr;
    }
};

class JsonReader {
public:
    explicit JsonReader(const std::string &text): s_(text), pos_(0) {}

    bool parse(JsonValue &out)
    {
        if (!value(out, 0)) {
            return false;
        }
        skip_ws();
        return pos_ == s_.size();
    }

private:
    static const int MAX_DEPTH = 64;

    void skip_ws()
    {
        while (pos_ < s_.size() && (s_[pos_] == ' ' || s_[pos_] == '\t' ||
                                    s_[pos_] == '\n' || s_[pos_] == '\r')) {
            ++pos_;
        }
    }

    bool literal(const char *word)
    {
        size_t n = strlen(word);
        if (s_.compare(pos_, n, word) != 0) {
            return false;
        }
        pos_ += n;
        return true;
    }

    bool value(JsonValue &out, int depth)
    {
        if (depth > MAX_DEPTH) {
            return false;
        }
        skip_ws();
        if (pos_ >= s_.size()) {
            return false;
        }
        size_t start = pos_;
        bool ok = false;
        char c = s_[pos_];
        if (c == '{') {
            out.type = JsonValue::OBJECT;
            ok = object(out, depth);
        } else if (c == '[') {
            out.type = JsonValue::ARRAY;
            ok = array(out, depth);
        } else if (c == '"') {
            out.type = JsonValue::STRING;
            ok = string(out.str);
        } else if (c == 't' || c == 'f') {
            out.type = JsonValue::BOOLEAN;
            ok = literal(c == 't' ? "true" : "false");
        } else if (c == 'n') {
            out.type = JsonValue::NUL;
            ok = literal("null");
        } else {
            out.type = JsonValue::NUMBER;
            ok = number();
        }
        if (ok) {
            out.raw = s_.substr(start, pos_ - start);
        }
        return ok;
    }

    bool object(JsonValue &out, int depth)
    {
        ++pos_; // {
        skip_ws();
        if (pos_ < s_.size() && s_[pos_] == '}') {
            ++pos_;
            return true;
        }
        while (true) {
            skip_ws();
            std::string key;
            if (pos_ >= s_.size() || s_[pos_] != '"' || !string(key)) {
                return false;
            }
            skip_ws();
            if (pos_ >= s_.size() || s_[pos_] != ':') {
                return false;
            }
            ++pos_;
            JsonValue v;
            if (!value(v, depth + 1)) {
                return false;
            }
            out.members.emplace_back(key, std::move(v));
            skip_ws();
            if (pos_ < s_.size() && s_[pos_] == ',') {
                ++pos_;
            } else if (pos_ < s_.size() && s_[pos_] == '}') {
                ++pos_;
                return true;
            } else {
                return false;
            }
        }
    }

    bool array(JsonValue &out, int depth)
    {
        ++pos_; // [
        skip_ws();
        if (pos_ < s_.size() && s_[pos_] == ']') {
            ++pos_;
            return true;
        }
        while (true) {
            JsonValue v;
            if (!value(v, depth + 1)) {
                return false;
            }
            out.items.push_back(std::move(v));
            skip_ws();
            if (pos_ < s_.size() && s_[pos_] == ',') {
                ++pos_;
            } else if (pos_ < s_.size() && s_[pos_] == ']') {
                ++pos_;
                return true;
            } else {
                return false;
            }
        }
    }

    bool number()
    {
        size_t start = pos_;
        if (pos_ < s_.size() && s_[pos_] == '-') {
            ++pos_;
        }
        while (pos_ < s_.size() &&
               (isdigit(static_cast<unsigned char>(s_[pos_])) ||
                s_[pos_] == '.' || s_[pos_] == 'e' || s_[pos_] == 'E' ||
                s_[pos_] == '+' || s_[pos_] == '-')) {
            ++pos_;
        }
        if (pos_ == start) {
            return false;
        }
        char *end = nullptr;
        std::string text = s_.substr(start, pos_ - start);
        g_ascii_strtod(text.c_str(), &end);
        return end && *end == '\0';
    }

    bool hex4(unsigned &out)
    {
        if (pos_ + 4 > s_.size()) {
            return false;
        }
        out = 0;
        for (int i = 0; i < 4; ++i) {
            int d = g_ascii_xdigit_value(s_[pos_++]);
            if (d < 0) {
                return false;
            }
            out = out * 16 + d;
        }
        return true;
    }

    bool string(std::string &out)
    {
        ++pos_; // opening quote
        while (pos_ < s_.size()) {
            char c = s_[pos_++];
            if (c == '"') {
                return true;
            } else if (static_cast<unsigned char>(c) < 0x20) {
                return false;
            } else if (c != '\\') {
                out += c;
                continue;
            }
            if (pos_ >= s_.size()) {
                return false;
            }
            c = s_[pos_++];
            switch (c) {
            case '"':
            case '\\':
            case '/':
                out += c;
                break;
            case 'b':
                out += '\b';
                break;
            case 'f':
                out += '\f';
                break;
            case 'n':
                out += '\n';
                break;
            case 'r':
                out += '\r';
                break;
            case 't':
                out += '\t';
                break;
            case 'u': {
                unsigned cp;
                if (!hex4(cp)) {
                    return false;
                }
                if (cp >= 0xD800 && cp < 0xDC00) {
                    unsigned lo;
                    if (s_.compare(pos_, 2, "\\u") != 0) {
                        return false;
                    }
                    pos_ += 2;
                    if (!hex4(lo) || lo < 0xDC00 || lo >= 0xE000) {
                        return false;
                    }
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                } else if (cp >= 0xDC00 && cp < 0xE000) {
                    return false;
                }
                char buf[6];
                int n = g_unichar_to_utf8(cp, buf);
                out.append(buf, n);
                break;
            }
            default:
                return false;
            }
        }
        return false;
    }

    const std::string &s_;
    size_t pos_;
};

std::string json_string(const std::string &s)
{
    std::string out = "\"";
    for (unsigned char c : s) {
        switch (c) {
        case '"':
            out += "\\\"";
            break;
        case '\\':
            out += "\\\\";
            break;
        case '\n':
            out += "\\n";
            break;
        case '\r':
            out += "\\r";
            break;
        case '\t':
            out += "\\t";
            break;
        default:
            if (c < 0x20) {
                char buf[8];
                snprintf(buf, sizeof(buf), "\\u%04x", c);
                out += buf;
            } else {
                out += static_cast<char>(c);
            }
        }
    }
    out += "\"";
    return out;
}

std::string error_reply(const std::string &id, const std::string &code,
                        const std::string &message)
{
    return "{\"id\":" + id + ",\"ok\":false,\"error\":{\"code\":" +
           json_string(code) + ",\"message\":" + json_string(message) + "}}";
}

//-----------------------------------------------------------------------------

std::string random_token()
{
    unsigned char bytes[16];
    bool ok = true;
#ifdef WIN32
    for (size_t i = 0; i < sizeof(bytes); i += sizeof(unsigned int)) {
        unsigned int v;
        if (rand_s(&v) != 0) {
            ok = false;
            break;
        }
        memcpy(bytes + i, &v, sizeof(v));
    }
#else
    FILE *f = fopen("/dev/urandom", "rb");
    ok = f && fread(bytes, 1, sizeof(bytes), f) == sizeof(bytes);
    if (f) {
        fclose(f);
    }
#endif
    if (!ok) {
        return "";
    }
    std::string out;
    for (unsigned char b : bytes) {
        char buf[3];
        snprintf(buf, sizeof(buf), "%02x", b);
        out += buf;
    }
    return out;
}

// Compares without stopping at the first difference.
bool same_token(const std::string &a, const std::string &b)
{
    if (a.size() != b.size() || a.empty()) {
        return false;
    }
    unsigned char diff = 0;
    for (size_t i = 0; i < a.size(); ++i) {
        diff |= static_cast<unsigned char>(a[i] ^ b[i]);
    }
    return diff == 0;
}

unsigned long current_pid()
{
#ifdef WIN32
    return GetCurrentProcessId();
#else
    return static_cast<unsigned long>(getpid());
#endif
}

// Writes `content` to `path`, readable by the user only where the OS lets us
// say so (on Windows the per-user config dir's ACL already restricts it).
bool write_private_file(const std::string &path, const std::string &content)
{
#ifdef WIN32
    int fd = g_open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_BINARY,
                    0600);
#else
    int fd = g_open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd >= 0) {
        fchmod(fd, 0600);
    }
#endif
    if (fd < 0) {
        return false;
    }
    FILE *f = fdopen(fd, "wb");
    if (!f) {
        g_close(fd, nullptr);
        return false;
    }
    bool ok = fwrite(content.data(), 1, content.size(), f) == content.size();
    ok = (fclose(f) == 0) && ok;
    return ok;
}

} // namespace

//-----------------------------------------------------------------------------

struct LiveControl::Connection {
    LiveControl *owner; // nullptr once the channel is gone
    GSocketConnection *conn;
    GCancellable *cancel;
    std::string buf;
    bool authenticated;
    char chunk[8192];
};

namespace {

void destroy_connection(LiveControl::Connection *c)
{
    g_object_unref(c->cancel);
    g_object_unref(c->conn);
    delete c;
}

} // namespace

LiveControl::LiveControl(RTWindow *window):
    window_(window), service_(nullptr), port_(0)
{
}

std::unique_ptr<LiveControl> LiveControl::start(RTWindow *window)
{
    std::unique_ptr<LiveControl> lc(new LiveControl(window));

    lc->token_ = random_token();
    if (lc->token_.empty()) {
        std::cerr << "live control: no random source for the token"
                  << std::endl;
        return nullptr;
    }

    lc->service_ = g_socket_service_new();
    GInetAddress *loopback =
        g_inet_address_new_loopback(G_SOCKET_FAMILY_IPV4);
    GSocketAddress *addr = g_inet_socket_address_new(loopback, 0);
    g_object_unref(loopback);
    GSocketAddress *effective = nullptr;
    GError *err = nullptr;
    bool ok = g_socket_listener_add_address(
        G_SOCKET_LISTENER(lc->service_), addr, G_SOCKET_TYPE_STREAM,
        G_SOCKET_PROTOCOL_TCP, nullptr, &effective, &err);
    g_object_unref(addr);
    if (!ok) {
        std::cerr << "live control: cannot listen: "
                  << (err ? err->message : "?") << std::endl;
        if (err) {
            g_error_free(err);
        }
        return nullptr; // the destructor releases the service
    }
    lc->port_ =
        g_inet_socket_address_get_port(G_INET_SOCKET_ADDRESS(effective));
    g_object_unref(effective);

    g_signal_connect(lc->service_, "incoming", G_CALLBACK(on_incoming),
                     lc.get());

    lc->discovery_path_ =
        Glib::build_filename(Options::user_config_dir, DISCOVERY_FILE);
    if (!lc->write_discovery_file()) {
        std::cerr << "live control: cannot write " << lc->discovery_path_
                  << std::endl;
        lc->discovery_path_.clear();
        return nullptr;
    }

    g_socket_service_start(lc->service_);
    if (options.rtSettings.verbose) {
        std::cout << "live control: listening on 127.0.0.1:" << lc->port_
                  << std::endl;
    }
    return lc;
}

LiveControl::~LiveControl()
{
    if (service_) {
        g_socket_service_stop(service_);
        g_socket_listener_close(G_SOCKET_LISTENER(service_));
        g_signal_handlers_disconnect_by_data(service_, this);
        g_object_unref(service_);
    }
    for (auto c : connections_) {
        // A read is pending on each: its callback frees the connection once
        // it sees the cancellation (if the main loop runs again at all).
        c->owner = nullptr;
        g_cancellable_cancel(c->cancel);
        g_io_stream_close(G_IO_STREAM(c->conn), nullptr, nullptr);
    }
    connections_.clear();
    remove_discovery_file();
}

bool LiveControl::write_discovery_file()
{
    std::ostringstream json;
    json << "{\"port\":" << port_ << ",\"token\":" << json_string(token_)
         << ",\"pid\":" << current_pid()
         << ",\"version\":" << json_string(RTVERSION) << "}\n";
    // Written beside and renamed over, so a reader never sees half a file.
    std::string tmp = discovery_path_ + ".tmp";
    if (!write_private_file(tmp, json.str())) {
        g_remove(tmp.c_str());
        return false;
    }
    if (g_rename(tmp.c_str(), discovery_path_.c_str()) != 0) {
        g_remove(tmp.c_str());
        return false;
    }
    return true;
}

void LiveControl::remove_discovery_file()
{
    if (discovery_path_.empty()) {
        return;
    }
    // Only if it is still ours: another ART may have replaced it since.
    gchar *content = nullptr;
    if (g_file_get_contents(discovery_path_.c_str(), &content, nullptr,
                            nullptr)) {
        std::string text(content);
        g_free(content);
        if (text.find(json_string(token_)) != std::string::npos) {
            g_remove(discovery_path_.c_str());
        }
    }
}

gboolean LiveControl::on_incoming(GSocketService *service,
                                  GSocketConnection *connection,
                                  GObject *source, gpointer data)
{
    LiveControl *self = static_cast<LiveControl *>(data);
    Connection *c = new Connection();
    c->owner = self;
    c->conn = G_SOCKET_CONNECTION(g_object_ref(connection));
    c->cancel = g_cancellable_new();
    c->authenticated = false;
    self->connections_.insert(c);
    self->read_more(c);
    return TRUE;
}

void LiveControl::read_more(Connection *c)
{
    GInputStream *in = g_io_stream_get_input_stream(G_IO_STREAM(c->conn));
    g_input_stream_read_async(in, c->chunk, sizeof(c->chunk),
                              G_PRIORITY_DEFAULT, c->cancel, on_read, c);
}

void LiveControl::on_read(GObject *source, GAsyncResult *res, gpointer data)
{
    Connection *c = static_cast<Connection *>(data);
    GError *err = nullptr;
    gssize n = g_input_stream_read_finish(G_INPUT_STREAM(source), res, &err);
    if (err) {
        g_error_free(err);
    }
    LiveControl *self = c->owner;
    if (!self) {
        destroy_connection(c);
        return;
    }
    if (n <= 0) {
        self->close(c);
        return;
    }

    GThreadLock lock; // requests touch the GUI
    c->buf.append(c->chunk, n);
    size_t eol;
    while ((eol = c->buf.find('\n')) != std::string::npos) {
        std::string line = c->buf.substr(0, eol);
        c->buf.erase(0, eol + 1);
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        if (!self->handle_line(c, line)) {
            self->close(c);
            return;
        }
    }
    if (c->buf.size() >
        (c->authenticated ? MAX_REQUEST_LINE : MAX_TOKEN_LINE)) {
        self->close(c);
        return;
    }
    self->read_more(c);
}

bool LiveControl::handle_line(Connection *c, const std::string &line)
{
    if (line.find_first_not_of(" \t") == std::string::npos) {
        return true;
    }
    JsonValue msg;
    bool parsed = JsonReader(line).parse(msg) &&
                  msg.type == JsonValue::OBJECT;

    if (!c->authenticated) {
        const JsonValue *token = parsed ? msg.get("token") : nullptr;
        if (!token || token->type != JsonValue::STRING ||
            !same_token(token->str, token_)) {
            return false;
        }
        c->authenticated = true;
        return true;
    }

    std::string reply;
    if (!parsed) {
        reply = error_reply("null", "bad_request", "not a JSON object");
    } else {
        const JsonValue *id = msg.get("id");
        std::string id_json = "null";
        if (id && (id->type == JsonValue::NUMBER ||
                   id->type == JsonValue::STRING)) {
            id_json = id->raw;
        }
        const JsonValue *op = msg.get("op");
        const JsonValue *args = msg.get("args");
        if (!op || op->type != JsonValue::STRING) {
            reply = error_reply(id_json, "bad_request", "missing \"op\"");
        } else if (args && args->type != JsonValue::OBJECT &&
                   args->type != JsonValue::NUL) {
            reply = error_reply(id_json, "bad_request",
                                "\"args\" must be an object");
        } else {
            bool ok = false;
            std::string result =
                dispatch(op->str, args ? args->raw : "{}", ok);
            if (ok) {
                reply = "{\"id\":" + id_json + ",\"ok\":true,\"result\":" +
                        result + "}";
            } else {
                reply = "{\"id\":" + id_json + ",\"ok\":false,\"error\":" +
                        result + "}";
            }
        }
    }

    reply += '\n';
    GOutputStream *out = g_io_stream_get_output_stream(G_IO_STREAM(c->conn));
    return g_output_stream_write_all(out, reply.data(), reply.size(), nullptr,
                                     c->cancel, nullptr);
}

std::string LiveControl::dispatch(const std::string &op,
                                  const std::string &args_json, bool &ok)
{
    (void)args_json; // no op takes arguments yet
    if (op == "status") {
        ok = true;
        return status();
    }
    ok = false;
    return "{\"code\":\"unknown_op\",\"message\":" +
           json_string("unknown op: " + op) + "}";
}

std::string LiveControl::status()
{
    std::ostringstream out;
    out << "{\"version\":" << json_string(RTVERSION) << ",\"images\":[";
    EditorPanel *active = window_->getActiveEditorPanel();
    bool first = true;
    for (EditorPanel *ep : window_->getEditorPanels()) {
        int w = 0, h = 0;
        out << (first ? "" : ",") << "{\"path\":"
            << json_string(ep->getFileName()) << ",\"active\":"
            << (ep == active ? "true" : "false");
        if (ep->getImageSize(w, h)) {
            out << ",\"width\":" << w << ",\"height\":" << h;
        } else {
            out << ",\"width\":null,\"height\":null";
        }
        out << "}";
        first = false;
    }
    out << "]}";
    return out.str();
}

void LiveControl::close(Connection *c)
{
    connections_.erase(c);
    g_cancellable_cancel(c->cancel);
    g_io_stream_close(G_IO_STREAM(c->conn), nullptr, nullptr);
    destroy_connection(c);
}

}} // namespace art::gui
