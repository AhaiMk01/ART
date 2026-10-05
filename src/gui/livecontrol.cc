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
#include "../engine/procparams.h"
#include "editorpanel.h"
#include "filecatalog.h"
#include "filepanel.h"
#include "guiutils.h"
#include "options.h"
#include "rtwindow.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <iostream>
#include <locale>
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
// At most this many clients at once; more are closed as they connect.
const size_t MAX_CONNECTIONS = 8;
// A client that hasn't sent the token this long after connecting is dropped.
const guint AUTH_DEADLINE_SECONDS = 5;
// Longest line accepted before the token has been checked. Enforced before
// the line is parsed at all.
const size_t MAX_TOKEN_LINE = 1024;
// Longest request line. Plenty for status; later ops that carry bigger
// payloads (whole .arp profiles) may need to raise it.
const size_t MAX_REQUEST_LINE = 1024 * 1024;
// While more than this many bytes of replies wait for a client to read them,
// its further requests are left unread (TCP then pushes back on it).
const size_t MAX_OUTBOUND = 1024 * 1024;
// A client whose pending write makes no progress for this long is dropped,
// so one that never reads can't hold its slot forever.
const guint WRITE_STALL_SECONDS = 30;
// Deepest nesting of arrays/objects the JSON reader accepts (it recurses).
const int MAX_JSON_DEPTH = 32;

//-----------------------------------------------------------------------------
// A small, strict (RFC 8259) JSON reader: enough to take requests apart.
//
// The values live in one flat vector and refer to each other by index, so no
// type contains a container of itself and the text of nested values is never
// copied: a value knows its span in the source, and only decoded strings are
// stored.
//-----------------------------------------------------------------------------

const size_t NONE = static_cast<size_t>(-1);

struct JsonNode {
    enum Type { NUL, BOOLEAN, NUMBER, STRING, ARRAY, OBJECT };
    Type type;
    size_t begin, end; // this value's span in the source text
    size_t first;      // first element/member (ARRAY, OBJECT), or NONE
    size_t next;       // next element/member of the parent, or NONE
    std::string key;   // member name, for a value inside an OBJECT
    std::string str;   // decoded STRING

    JsonNode(): type(NUL), begin(0), end(0), first(NONE), next(NONE) {}
};

class JsonDoc {
public:
    JsonDoc(): s_(nullptr), pos_(0) {}

    // The text must outlive the document.
    bool parse(const std::string &text)
    {
        nodes_.clear();
        s_ = &text;
        pos_ = 0;
        if (!g_utf8_validate(text.data(), text.size(), nullptr)) {
            return false;
        }
        size_t root;
        if (!value(root, 0)) {
            return false;
        }
        skip_ws();
        return pos_ == text.size();
    }

    // Only after a successful parse.
    const JsonNode &root() const { return nodes_[0]; }

    const JsonNode *get(const JsonNode &obj, const std::string &key) const
    {
        if (obj.type != JsonNode::OBJECT) {
            return nullptr;
        }
        for (size_t i = obj.first; i != NONE; i = nodes_[i].next) {
            if (nodes_[i].key == key) {
                return &nodes_[i];
            }
        }
        return nullptr;
    }

    // The members of an object that are strings, decoded.
    std::map<std::string, std::string> strings(const JsonNode &obj) const
    {
        std::map<std::string, std::string> out;
        if (obj.type == JsonNode::OBJECT) {
            for (size_t i = obj.first; i != NONE; i = nodes_[i].next) {
                if (nodes_[i].type == JsonNode::STRING) {
                    out[nodes_[i].key] = nodes_[i].str;
                }
            }
        }
        return out;
    }

    // The elements of an array, or the members of an object.
    std::vector<const JsonNode *> children(const JsonNode &n) const
    {
        std::vector<const JsonNode *> out;
        if (n.type == JsonNode::ARRAY || n.type == JsonNode::OBJECT) {
            for (size_t i = n.first; i != NONE; i = nodes_[i].next) {
                out.push_back(&nodes_[i]);
            }
        }
        return out;
    }

    // The source text of a value (valid JSON, as the parse succeeded).
    std::string raw(const JsonNode &n) const
    {
        return s_->substr(n.begin, n.end - n.begin);
    }

private:
    bool at_end() const { return pos_ >= s_->size(); }
    char peek() const { return (*s_)[pos_]; }

    void skip_ws()
    {
        while (!at_end() && (peek() == ' ' || peek() == '\t' ||
                             peek() == '\n' || peek() == '\r')) {
            ++pos_;
        }
    }

    bool literal(const char *word)
    {
        size_t n = strlen(word);
        if (s_->compare(pos_, n, word) != 0) {
            return false;
        }
        pos_ += n;
        return true;
    }

    // `depth` is how many arrays/objects enclose this value.
    bool value(size_t &idx, int depth)
    {
        skip_ws();
        if (at_end()) {
            return false;
        }
        idx = nodes_.size();
        nodes_.push_back(JsonNode());
        nodes_[idx].begin = pos_;
        bool ok = false;
        char c = peek();
        if (c == '{' || c == '[') {
            ok = depth < MAX_JSON_DEPTH &&
                 (c == '{' ? object(idx, depth) : array(idx, depth));
        } else if (c == '"') {
            nodes_[idx].type = JsonNode::STRING;
            ok = string(nodes_[idx].str); // adds no nodes: no reallocation
        } else if (c == 't' || c == 'f') {
            nodes_[idx].type = JsonNode::BOOLEAN;
            ok = literal(c == 't' ? "true" : "false");
        } else if (c == 'n') {
            nodes_[idx].type = JsonNode::NUL;
            ok = literal("null");
        } else if (c == '-' || is_digit(c)) {
            nodes_[idx].type = JsonNode::NUMBER;
            ok = number();
        }
        if (ok) {
            nodes_[idx].end = pos_;
        }
        return ok;
    }

    // Links `child` as the next element/member of `parent` after `last`.
    void link(size_t parent, size_t &last, size_t child)
    {
        if (last == NONE) {
            nodes_[parent].first = child;
        } else {
            nodes_[last].next = child;
        }
        last = child;
    }

    bool object(size_t idx, int depth)
    {
        nodes_[idx].type = JsonNode::OBJECT;
        ++pos_; // {
        skip_ws();
        if (!at_end() && peek() == '}') {
            ++pos_;
            return true;
        }
        size_t last = NONE;
        while (true) {
            skip_ws();
            std::string key;
            if (at_end() || peek() != '"' || !string(key)) {
                return false;
            }
            skip_ws();
            if (at_end() || peek() != ':') {
                return false;
            }
            ++pos_;
            size_t child;
            if (!value(child, depth + 1)) {
                return false;
            }
            nodes_[child].key.swap(key);
            link(idx, last, child);
            skip_ws();
            if (!at_end() && peek() == ',') {
                ++pos_;
            } else if (!at_end() && peek() == '}') {
                ++pos_;
                return true;
            } else {
                return false;
            }
        }
    }

    bool array(size_t idx, int depth)
    {
        nodes_[idx].type = JsonNode::ARRAY;
        ++pos_; // [
        skip_ws();
        if (!at_end() && peek() == ']') {
            ++pos_;
            return true;
        }
        size_t last = NONE;
        while (true) {
            size_t child;
            if (!value(child, depth + 1)) {
                return false;
            }
            link(idx, last, child);
            skip_ws();
            if (!at_end() && peek() == ',') {
                ++pos_;
            } else if (!at_end() && peek() == ']') {
                ++pos_;
                return true;
            } else {
                return false;
            }
        }
    }

    static bool is_digit(char c) { return c >= '0' && c <= '9'; }

    // One or more digits.
    bool digits()
    {
        size_t start = pos_;
        while (!at_end() && is_digit(peek())) {
            ++pos_;
        }
        return pos_ > start;
    }

    // number = [ "-" ] ( "0" / 1-9 *DIGIT ) [ "." 1*DIGIT ]
    //          [ ( "e" / "E" ) [ "-" / "+" ] 1*DIGIT ]
    // Whatever follows is left to the caller, so "01" or "1.2.3" fail there.
    bool number()
    {
        if (peek() == '-') {
            ++pos_;
        }
        if (at_end() || !is_digit(peek())) {
            return false;
        }
        if (peek() == '0') {
            ++pos_;
        } else {
            digits();
        }
        if (!at_end() && peek() == '.') {
            ++pos_;
            if (!digits()) {
                return false;
            }
        }
        if (!at_end() && (peek() == 'e' || peek() == 'E')) {
            ++pos_;
            if (!at_end() && (peek() == '-' || peek() == '+')) {
                ++pos_;
            }
            if (!digits()) {
                return false;
            }
        }
        return true;
    }

    bool hex4(unsigned &out)
    {
        if (pos_ + 4 > s_->size()) {
            return false;
        }
        out = 0;
        for (int i = 0; i < 4; ++i) {
            int d = g_ascii_xdigit_value((*s_)[pos_++]);
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
        while (!at_end()) {
            char c = (*s_)[pos_++];
            if (c == '"') {
                return true;
            } else if (static_cast<unsigned char>(c) < 0x20) {
                return false;
            } else if (c != '\\') {
                out += c;
                continue;
            }
            if (at_end()) {
                return false;
            }
            c = (*s_)[pos_++];
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
                    if (s_->compare(pos_, 2, "\\u") != 0) {
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

    const std::string *s_;
    size_t pos_;
    std::vector<JsonNode> nodes_;
};

// Encodes UTF-8 text as a JSON string (the input must be valid UTF-8 for the
// output to be valid JSON).
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

// The `preview` op's args: the string members, plus max_size (a number) as
// its JSON text.
std::map<std::string, std::string> preview_args(const JsonDoc &doc,
                                                const JsonNode *args)
{
    std::map<std::string, std::string> out;
    if (args) {
        out = doc.strings(*args);
        const JsonNode *size = doc.get(*args, "max_size");
        if (size && size->type == JsonNode::NUMBER) {
            out["max_size"] = doc.raw(*size);
        }
    }
    return out;
}

// The `sample_spots` op's args. `spots` is an array of [x, y] pairs or of
// {"x", "y"} objects (whole numbers); `size` a whole number (default 32),
// `space` "working" (default) or "input". On failure `error` is the error
// object.
bool parse_sample_args(const JsonDoc &doc, const JsonNode *args,
                       std::string &path, art::engine::SpotRequest &req,
                       std::string &error);

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

// Constant time over strings of equal length (the token's length is no
// secret: it is always 32 hex digits).
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
    LiveControl *owner; // nullptr once closed
    GSocketConnection *conn;
    GCancellable *cancel;
    std::string in;     // received, not handled yet
    bool authenticated;
    bool discarding;    // skipping the rest of an over-long request line
    bool reading;       // a read is in flight
    bool writing;       // a write is in flight
    std::deque<std::string> out; // reply lines not fully sent yet
    size_t out_offset;  // bytes of out.front() already sent
    size_t out_bytes;   // bytes in `out` not sent yet
    guint auth_timer;   // pre-authentication deadline, or 0
    guint stall_timer;  // pending-write deadline, or 0
    char chunk[8192];
};

namespace {

// Frees a closed connection once no read or write in flight refers to it
// (their callbacks call this again as they complete).
void release_if_idle(LiveControl::Connection *c)
{
    if (c->owner || c->reading || c->writing) {
        return;
    }
    g_object_unref(c->cancel);
    g_object_unref(c->conn);
    delete c;
}

void remove_timer(guint &id)
{
    if (id) {
        g_source_remove(id);
        id = 0;
    }
}

// Closes the socket and cancels whatever is in flight; the connection is
// freed now or by the last callback.
void shut(LiveControl::Connection *c)
{
    c->owner = nullptr;
    remove_timer(c->auth_timer);
    remove_timer(c->stall_timer);
    g_cancellable_cancel(c->cancel);
    g_io_stream_close(G_IO_STREAM(c->conn), nullptr, nullptr);
    release_if_idle(c);
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
    drop_previews(nullptr);
    // A connection with a read or write in flight is freed by its callback
    // (if the main loop runs again at all).
    std::set<Connection *> all;
    all.swap(connections_);
    for (auto c : all) {
        shut(c);
    }
    remove_discovery_file();
}

bool LiveControl::write_discovery_file()
{
    std::ostringstream json;
    json << "{\"port\":" << port_ << ",\"token\":" << json_string(token_)
         << ",\"pid\":" << current_pid()
         << ",\"version\":" << json_string(RTVERSION) << "}\n";
    // Written beside and renamed over, so a reader never sees half a file.
    // The temporary name carries our pid: two ARTs starting at once must not
    // write into the same temporary file.
    std::ostringstream tmp_name;
    tmp_name << discovery_path_ << "." << current_pid() << ".tmp";
    std::string tmp = tmp_name.str();
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
    if (self->connections_.size() >= MAX_CONNECTIONS) {
        // Refused at once, so a flood of connections can't pile up.
        g_io_stream_close(G_IO_STREAM(connection), nullptr, nullptr);
        return TRUE;
    }
    Connection *c = new Connection();
    c->owner = self;
    c->conn = G_SOCKET_CONNECTION(g_object_ref(connection));
    c->cancel = g_cancellable_new();
    c->authenticated = false;
    c->discarding = false;
    c->reading = false;
    c->writing = false;
    c->out_offset = 0;
    c->out_bytes = 0;
    c->stall_timer = 0;
    c->auth_timer =
        g_timeout_add_seconds(AUTH_DEADLINE_SECONDS, on_auth_timeout, c);
    self->connections_.insert(c);
    self->read_more(c);
    return TRUE;
}

gboolean LiveControl::on_auth_timeout(gpointer data)
{
    Connection *c = static_cast<Connection *>(data);
    c->auth_timer = 0; // this source is going away
    c->owner->close(c); // a timer is only armed while the connection is open
    return G_SOURCE_REMOVE;
}

gboolean LiveControl::on_write_stall(gpointer data)
{
    Connection *c = static_cast<Connection *>(data);
    c->stall_timer = 0;
    c->owner->close(c);
    return G_SOURCE_REMOVE;
}

void LiveControl::read_more(Connection *c)
{
    GInputStream *in = g_io_stream_get_input_stream(G_IO_STREAM(c->conn));
    c->reading = true;
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
    c->reading = false;
    LiveControl *self = c->owner;
    if (!self) {
        release_if_idle(c);
        return;
    }
    if (n <= 0) {
        self->close(c);
        return;
    }
    c->in.append(c->chunk, n);
    self->pump(c);
}

void LiveControl::pump(Connection *c)
{
    GThreadLock lock; // requests touch the GUI
    size_t start = 0; // of the first line not handled yet
    while (c->out_bytes < MAX_OUTBOUND) {
        size_t eol = c->in.find('\n', start);
        size_t len = (eol == std::string::npos ? c->in.size() : eol) - start;
        if (c->discarding) {
            if (eol == std::string::npos) {
                start = c->in.size();
                break;
            }
            start = eol + 1;
            c->discarding = false;
            send(c, error_reply("null", "bad_request", "request too long"));
            continue;
        }
        // Length first, before anything looks inside the line.
        size_t limit = c->authenticated ? MAX_REQUEST_LINE : MAX_TOKEN_LINE;
        if (len > limit) {
            if (!c->authenticated) {
                close(c);
                return;
            }
            // Skip to the end of the line, then answer it.
            c->discarding = true;
            continue;
        }
        if (eol == std::string::npos) {
            break;
        }
        std::string line = c->in.substr(start, len);
        start = eol + 1;
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }
        if (!handle_line(c, line)) {
            close(c);
            return;
        }
    }
    c->in.erase(0, start);
    // Over the limit, reading stays off until on_write has drained it.
    if (!c->reading && c->out_bytes < MAX_OUTBOUND) {
        read_more(c);
    }
}

bool LiveControl::handle_line(Connection *c, const std::string &line)
{
    if (line.find_first_not_of(" \t") == std::string::npos) {
        return true;
    }

    JsonDoc doc;
    bool parsed = doc.parse(line) && doc.root().type == JsonNode::OBJECT;

    if (!c->authenticated) {
        // Nothing but the token is looked at before it has been shown; a
        // wrong one closes the connection at once.
        const JsonNode *token = parsed ? doc.get(doc.root(), "token") : nullptr;
        if (!token || token->type != JsonNode::STRING ||
            !same_token(token->str, token_)) {
            return false;
        }
        c->authenticated = true;
        remove_timer(c->auth_timer);
        return true;
    }

    std::string reply;
    if (!parsed) {
        reply = error_reply("null", "bad_request", "not a valid JSON object");
    } else {
        const JsonNode &msg = doc.root();
        const JsonNode *id = doc.get(msg, "id");
        // A number id goes back as sent (the strict grammar has vetted it),
        // a string one re-encoded: the reply is valid JSON whatever came in.
        std::string id_json = "null";
        if (id && id->type == JsonNode::NUMBER) {
            id_json = doc.raw(*id);
        } else if (id && id->type == JsonNode::STRING) {
            id_json = json_string(id->str);
        }
        const JsonNode *op = doc.get(msg, "op");
        const JsonNode *args = doc.get(msg, "args");
        if (!op || op->type != JsonNode::STRING) {
            reply = error_reply(id_json, "bad_request", "missing \"op\"");
        } else if (args && args->type != JsonNode::OBJECT &&
                   args->type != JsonNode::NUL) {
            reply = error_reply(id_json, "bad_request",
                                "\"args\" must be an object");
        } else if (op->str == "preview") {
            // Answered later, once the editor has finished processing.
            start_preview(c, id_json, preview_args(doc, args));
            return true;
        } else if (op->str == "sample_spots") {
            bool ok = false;
            std::string path, result;
            art::engine::SpotRequest req;
            if (parse_sample_args(doc, args, path, req, result)) {
                result = sample_spots(path, req, ok);
            }
            reply = "{\"id\":" + id_json + (ok ? ",\"ok\":true,\"result\":"
                                                 : ",\"ok\":false,\"error\":") +
                    result + "}";
        } else {
            bool ok = false;
            std::string result =
                dispatch(op->str, args ? doc.strings(*args) : Args(), ok);
            if (ok) {
                reply = "{\"id\":" + id_json + ",\"ok\":true,\"result\":" +
                        result + "}";
            } else {
                reply = "{\"id\":" + id_json + ",\"ok\":false,\"error\":" +
                        result + "}";
            }
        }
    }
    send(c, reply);
    return true;
}

void LiveControl::send(Connection *c, std::string reply)
{
    reply += '\n';
    c->out_bytes += reply.size();
    c->out.push_back(std::move(reply));
    if (!c->writing) {
        start_write(c);
    }
}

void LiveControl::start_write(Connection *c)
{
    // std::deque keeps its elements in place as more are queued, so this
    // buffer stays valid while the write is in flight.
    const std::string &s = c->out.front();
    GOutputStream *out = g_io_stream_get_output_stream(G_IO_STREAM(c->conn));
    c->writing = true;
    c->stall_timer =
        g_timeout_add_seconds(WRITE_STALL_SECONDS, on_write_stall, c);
    g_output_stream_write_async(out, s.data() + c->out_offset,
                                s.size() - c->out_offset, G_PRIORITY_DEFAULT,
                                c->cancel, on_write, c);
}

void LiveControl::on_write(GObject *source, GAsyncResult *res, gpointer data)
{
    Connection *c = static_cast<Connection *>(data);
    GError *err = nullptr;
    gssize n =
        g_output_stream_write_finish(G_OUTPUT_STREAM(source), res, &err);
    if (err) {
        g_error_free(err);
    }
    c->writing = false;
    remove_timer(c->stall_timer);
    LiveControl *self = c->owner;
    if (!self) {
        release_if_idle(c);
        return;
    }
    if (n <= 0) {
        self->close(c);
        return;
    }
    c->out_offset += n;
    c->out_bytes -= n;
    if (c->out_offset == c->out.front().size()) {
        c->out.pop_front();
        c->out_offset = 0;
    }
    if (!c->out.empty()) {
        self->start_write(c);
    }
    // Drained below the limit: handle what is buffered and read on.
    if (!c->reading && c->out_bytes < MAX_OUTBOUND) {
        self->pump(c);
    }
}

std::string LiveControl::dispatch(const std::string &op, const Args &args,
                                  bool &ok)
{
    if (op == "status") {
        ok = true;
        return status();
    }
    if (op == "get_profile") {
        return get_profile(args, ok);
    }
    if (op == "apply_profile") {
        return apply_profile(args, ok);
    }
    if (op == "undo" || op == "redo") {
        return step_history(args, op == "redo", ok);
    }
    if (op == "open") {
        return open(args, ok);
    }
    if (op == "save_sidecar") {
        return save_sidecar(args, ok);
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

namespace {

std::string error_object(const std::string &code, const std::string &message)
{
    return "{\"code\":" + json_string(code) +
           ",\"message\":" + json_string(message) + "}";
}

// Paths compare as the OS does: case-insensitively and with either slash
// on Windows.
std::string path_key(const std::string &path)
{
#ifdef WIN32
    std::string key = Glib::ustring(path).lowercase();
    for (char &ch : key) {
        if (ch == '/') {
            ch = '\\';
        }
    }
    return key;
#else
    return path;
#endif
}

} // namespace

namespace {

// A JSON number that is a whole number, as an int.
bool whole_number(const JsonDoc &doc, const JsonNode *n, int &out)
{
    if (!n || n->type != JsonNode::NUMBER) {
        return false;
    }
    const std::string text = doc.raw(*n);
    if (text.size() > 9 ||
        text.find_first_not_of("-0123456789") != std::string::npos) {
        return false;
    }
    out = static_cast<int>(strtol(text.c_str(), nullptr, 10));
    return true;
}

bool parse_sample_args(const JsonDoc &doc, const JsonNode *args,
                       std::string &path, art::engine::SpotRequest &req,
                       std::string &error)
{
    static const char *const SHAPE =
        "\"spots\" must be 1 to 16 [x, y] pairs or {\"x\", \"y\"} objects "
        "of whole numbers";
    static const char *const SPACE =
        "\"space\" must be \"working\" or \"input\"";
    if (!args) {
        error = error_object("bad_request", "sample_spots needs \"path\"");
        return false;
    }
    const std::map<std::string, std::string> strs = doc.strings(*args);
    std::map<std::string, std::string>::const_iterator it = strs.find("path");
    if (it == strs.end() || it->second.empty()) {
        error = error_object("bad_request", "sample_spots needs \"path\"");
        return false;
    }
    path = it->second;
    it = strs.find("space");
    if (it != strs.end()) {
        if (it->second != "working" && it->second != "input") {
            error = error_object("bad_request", SPACE);
            return false;
        }
        req.space = it->second == "working"
                        ? art::engine::SpotSpace::WORKING
                        : art::engine::SpotSpace::INPUT;
    } else if (doc.get(*args, "space")) {
        error = error_object("bad_request", SPACE);
        return false;
    }
    if (const JsonNode *sz = doc.get(*args, "size")) {
        if (!whole_number(doc, sz, req.size)) {
            error = error_object("bad_request",
                                 "\"size\" must be a whole number");
            return false;
        }
        if (req.size < 2 || req.size > 256) {
            error = error_object("out_of_range",
                                 "\"size\" must be from 2 to 256");
            return false;
        }
    }
    const JsonNode *spots = doc.get(*args, "spots");
    if (!spots || spots->type != JsonNode::ARRAY) {
        error = error_object("bad_request", SHAPE);
        return false;
    }
    const std::vector<const JsonNode *> items = doc.children(*spots);
    if (items.empty() || items.size() > 16) {
        error = error_object("bad_request", SHAPE);
        return false;
    }
    for (const JsonNode *item : items) {
        int x = 0, y = 0;
        bool ok = false;
        if (item->type == JsonNode::ARRAY) {
            const std::vector<const JsonNode *> xy = doc.children(*item);
            ok = xy.size() == 2 && whole_number(doc, xy[0], x) &&
                 whole_number(doc, xy[1], y);
        } else if (item->type == JsonNode::OBJECT) {
            ok = doc.children(*item).size() == 2 &&
                 whole_number(doc, doc.get(*item, "x"), x) &&
                 whole_number(doc, doc.get(*item, "y"), y);
        }
        if (!ok) {
            error = error_object("bad_request", SHAPE);
            return false;
        }
        req.pos.push_back(std::make_pair(x, y));
    }
    return true;
}

} // namespace

std::string
LiveControl::sample_spots(const std::string &path,
                          const art::engine::SpotRequest &req, bool &ok)
{
    ok = false;
    EditorPanel *ep = find_editor(path);
    if (!ep) {
        return error_object("not_open", path + " is not open in ART");
    }
    if (ep->getIsProcessing()) {
        return error_object("busy", path + " is still being processed");
    }
    art::engine::SpotResult res;
    switch (ep->sampleSpots(req, res)) {
    case art::engine::SpotStatus::OK:
        break;
    case art::engine::SpotStatus::OUT_OF_FRAME: {
        std::ostringstream m;
        m << "a spot is outside the " << res.width << "x" << res.height
          << " frame";
        return error_object("out_of_range", m.str());
    }
    default:
        return error_object("busy", path + " has no processed image yet");
    }
    ok = true;
    return art::engine::spotResultJson(res);
}

EditorPanel *LiveControl::find_editor(const std::string &path)
{
    const std::string key = path_key(path);
    for (EditorPanel *ep : window_->getEditorPanels()) {
        if (path_key(ep->getFileName()) == key) {
            return ep;
        }
    }
    return nullptr;
}

std::string LiveControl::get_profile(const Args &args, bool &ok)
{
    ok = false;
    Args::const_iterator path = args.find("path");
    if (path == args.end() || path->second.empty()) {
        return error_object("bad_request", "get_profile needs \"path\"");
    }
    EditorPanel *ep = find_editor(path->second);
    std::string arp;
    int position = -1;
    if (!ep) {
        return error_object("not_open", path->second + " is not open in ART");
    }
    if (!ep->getProfileText(arp, position)) {
        return error_object("not_open",
                            path->second + " is still loading in ART");
    }
    ok = true;
    std::ostringstream out;
    out << "{\"profile\":" << json_string(arp)
        << ",\"history_position\":" << position << "}";
    return out.str();
}

EditorPanel *LiveControl::editor_for(const std::string &op, const Args &args,
                                     std::string &error)
{
    Args::const_iterator path = args.find("path");
    if (path == args.end() || path->second.empty()) {
        error = error_object("bad_request", op + " needs \"path\"");
        return nullptr;
    }
    EditorPanel *ep = find_editor(path->second);
    if (!ep) {
        error = error_object("not_open", path->second + " is not open in ART");
    }
    return ep;
}

namespace {

std::string still_loading(const std::string &path)
{
    return error_object("not_open", path + " is still loading in ART");
}

std::string position_result(int position)
{
    std::ostringstream out;
    out << "{\"history_position\":" << position << "}";
    return out.str();
}

} // namespace

std::string LiveControl::apply_profile(const Args &args, bool &ok)
{
    ok = false;
    std::string error;
    EditorPanel *ep = editor_for("apply_profile", args, error);
    if (!ep) {
        return error;
    }
    Args::const_iterator profile = args.find("profile");
    Args::const_iterator label = args.find("label");
    if (profile == args.end() || label == args.end()) {
        return error_object("bad_request",
                            "apply_profile needs \"profile\" and \"label\"");
    }
    art::engine::procparams::KeyFilePartialProfile partial(profile->second);
    if (!partial.valid()) {
        return error_object("bad_request",
                            "\"profile\" is not processing-profile text");
    }
    {
        // [Version] would make the whole current profile go through the
        // loader's old-version migrations.
        Glib::KeyFile kf;
        kf.load_from_data(profile->second);
        if (kf.has_group("Version")) {
            return error_object("bad_request",
                                "[Version] can't be changed by an edit");
        }
    }
    // Tried on a copy first: a value the loader rejects must not leave a
    // half-applied profile and a History entry behind.
    if (!ep->canApply(partial)) {
        return error_object("bad_request",
                            "ART could not load these values; nothing was "
                            "changed");
    }
    int position = -1;
    if (!ep->applyPartialProfile(partial, label->second, position)) {
        return still_loading(ep->getFileName());
    }
    ok = true;
    return position_result(position);
}

std::string LiveControl::step_history(const Args &args, bool forward, bool &ok)
{
    ok = false;
    std::string error;
    EditorPanel *ep = editor_for(forward ? "redo" : "undo", args, error);
    if (!ep) {
        return error;
    }
    int position = -1;
    if (!ep->stepHistory(forward, position)) {
        return still_loading(ep->getFileName());
    }
    ok = true;
    return position_result(position);
}

std::string LiveControl::open(const Args &args, bool &ok)
{
    ok = false;
    Args::const_iterator path = args.find("path");
    if (path == args.end() || path->second.empty()) {
        return error_object("bad_request", "open needs \"path\"");
    }
    const std::string &fname = path->second;
    if (!Glib::path_is_absolute(fname)) {
        return error_object("bad_request", "open needs an absolute \"path\"");
    }
    if (EditorPanel *ep = find_editor(fname)) {
        window_->selectEditorPanel(ep->getFileName());
        ok = true;
        return "{\"already_open\":true}";
    }
    if (!Glib::file_test(fname, Glib::FILE_TEST_IS_REGULAR)) {
        return error_object("not_found", fname + " does not exist");
    }
    if (!window_->fpanel) {
        return error_object("unsupported",
                            "this ART has no file browser to open images with");
    }
    // As a file named on the command line is opened: the browser shows its
    // folder and opens it in the editor, from an idle callback.
    window_->fpanel->fileCatalog->dirSelected(Glib::path_get_dirname(fname),
                                              fname);
    ok = true;
    return "{\"already_open\":false}";
}

std::string LiveControl::save_sidecar(const Args &args, bool &ok)
{
    ok = false;
    std::string error;
    EditorPanel *ep = editor_for("save_sidecar", args, error);
    if (!ep) {
        return error;
    }
    std::string arp;
    int position;
    if (!ep->getProfileText(arp, position)) {
        return still_loading(ep->getFileName());
    }
    // Where the editor's save writes the profile: the sidecar, unless ART is
    // set to keep profiles in its cache only.
    const std::string image = ep->getFileName();
    // saveProfile reports nothing, and writes nothing when the image file
    // has gone: check for that, and that a sidecar is there afterwards.
    if (!Glib::file_test(image, Glib::FILE_TEST_IS_REGULAR)) {
        return error_object("write_failed",
                            image + " no longer exists; nothing was saved");
    }
    ep->saveProfile();
    if (!options.saveParamsFile) {
        ok = true;
        return "{\"sidecar\":null}";
    }
    const std::string sidecar = options.getParamFile(image);
    if (!Glib::file_test(sidecar, Glib::FILE_TEST_IS_REGULAR)) {
        return error_object("write_failed", "ART did not write " + sidecar);
    }
    ok = true;
    return "{\"sidecar\":" + json_string(sidecar) + "}";
}

void LiveControl::close(Connection *c)
{
    drop_previews(c);
    connections_.erase(c);
    shut(c);
}

//-----------------------------------------------------------------------------
// preview {path, output, max_size}: the editor's preview image as a JPEG or PNG
//-----------------------------------------------------------------------------

namespace {

// How long a preview waits for the editor to finish processing.
const gint64 PREVIEW_WAIT_SECONDS = 30;
// How often a waiting preview looks at its editor. The timer runs below the
// priority of the idle callbacks through which the processor reports to the
// editor, so it never sees a state those are still about to change.
const guint PREVIEW_POLL_MS = 50;
const long DEFAULT_PREVIEW_SIZE = 1024;
const long MAX_PREVIEW_SIZE = 2576;
// Most previews one connection may have waiting at once.
const size_t MAX_PENDING_PREVIEWS = 4;
const int PREVIEW_JPEG_QUALITY = 85;

// A whole number from 1 to MAX_PREVIEW_SIZE as JSON text, or -1.
long preview_size(const std::string &text)
{
    if (text.empty() || text.size() > 5 ||
        text.find_first_not_of("0123456789") != std::string::npos) {
        return -1;
    }
    long n = strtol(text.c_str(), nullptr, 10);
    return n >= 1 && n <= MAX_PREVIEW_SIZE ? n : -1;
}

} // namespace

struct LiveControl::PendingPreview {
    LiveControl *owner;
    Connection *c;
    std::string id_json;
    std::string path;
    std::string output;
    std::string format; // Pixbuf format name: "jpeg" or "png"
    int max_size;
    gint64 deadline; // g_get_monotonic_time()
    guint timer;
};

namespace {

// The Pixbuf format name for an output file name; "" if not .jpg/.jpeg/.png.
std::string image_format(const std::string &path)
{
    static const struct {
        const char *ext;
        const char *format;
    } FORMATS[] = {{".jpg", "jpeg"}, {".jpeg", "jpeg"}, {".png", "png"}};
    const std::string lower = Glib::ustring(path).lowercase();
    for (const auto &f : FORMATS) {
        const size_t n = strlen(f.ext);
        if (lower.size() > n &&
            lower.compare(lower.size() - n, n, f.ext) == 0) {
            return f.format;
        }
    }
    return "";
}

} // namespace

void LiveControl::start_preview(Connection *c, const std::string &id_json,
                                const Args &args)
{
    Args::const_iterator path = args.find("path");
    Args::const_iterator output = args.find("output");
    Args::const_iterator size = args.find("max_size");
    long max_size = size == args.end() ? DEFAULT_PREVIEW_SIZE
                                       : preview_size(size->second);
    std::string format;
    size_t waiting = 0;
    for (auto p : previews_) {
        waiting += p->c == c;
    }
    std::string code, message;
    if (path == args.end() || path->second.empty()) {
        code = "bad_request";
        message = "preview needs \"path\"";
    } else if (output == args.end() ||
               !Glib::path_is_absolute(output->second)) {
        code = "bad_request";
        message = "preview needs an absolute \"output\" path";
    } else if ((format = image_format(output->second)).empty()) {
        code = "bad_request";
        message = "preview \"output\" must end in .jpg, .jpeg or .png";
    } else if (Glib::file_test(output->second, Glib::FILE_TEST_EXISTS)) {
        // Never overwrite: the client names a new file in its own folder.
        code = "exists";
        message = output->second + " already exists";
    } else if (max_size < 0) {
        code = "bad_request";
        message = "max_size must be a whole number from 1 to 2576";
    } else if (!Glib::file_test(Glib::path_get_dirname(output->second),
                                Glib::FILE_TEST_IS_DIR)) {
        code = "not_found";
        message = "no folder for " + output->second;
    } else if (!find_editor(path->second)) {
        code = "not_open";
        message = path->second + " is not open in ART";
    } else if (waiting >= MAX_PENDING_PREVIEWS) {
        code = "busy";
        message = "too many previews waiting on this connection";
    }
    if (!code.empty()) {
        send(c, error_reply(id_json, code, message));
        return;
    }
    PendingPreview *p = new PendingPreview();
    p->owner = this;
    p->c = c;
    p->id_json = id_json;
    p->path = path->second;
    p->output = output->second;
    p->format = format;
    p->max_size = static_cast<int>(max_size);
    p->deadline =
        g_get_monotonic_time() + PREVIEW_WAIT_SECONDS * G_USEC_PER_SEC;
    p->timer = gdk_threads_add_timeout_full(G_PRIORITY_LOW, PREVIEW_POLL_MS,
                                            on_preview_poll, p, nullptr);
    previews_.insert(p);
}

gboolean LiveControl::on_preview_poll(gpointer data)
{
    PendingPreview *p = static_cast<PendingPreview *>(data);
    return p->owner->poll_preview(p) ? G_SOURCE_CONTINUE : G_SOURCE_REMOVE;
}

bool LiveControl::poll_preview(PendingPreview *p)
{
    std::string reply;
    // Looked up again each time: the editor may have closed meanwhile.
    EditorPanel *ep = find_editor(p->path);
    if (!ep) {
        reply = error_reply(p->id_json, "not_open",
                            p->path + " is not open in ART");
    } else if (!ep->getIsProcessing()) {
        Glib::RefPtr<Gdk::Pixbuf> img = ep->getPreviewImage(p->max_size);
        if (img) {
            try {
                if (p->format == "png") {
                    img->save(p->output, "png");
                } else {
                    img->save(p->output, p->format,
                              std::vector<Glib::ustring>(1, "quality"),
                              std::vector<Glib::ustring>(
                                  1, std::to_string(PREVIEW_JPEG_QUALITY)));
                }
                std::ostringstream out;
                out << "{\"id\":" << p->id_json
                    << ",\"ok\":true,\"result\":{\"path\":"
                    << json_string(p->output)
                    << ",\"width\":" << img->get_width()
                    << ",\"height\":" << img->get_height() << "}}";
                reply = out.str();
            } catch (Glib::Error &e) {
                std::string why = e.what();
                reply = error_reply(p->id_json, "write_failed",
                                    "cannot write " + p->output + ": " + why);
            }
        }
        // no preview image yet: the image is still loading
    }
    if (reply.empty()) {
        if (g_get_monotonic_time() < p->deadline) {
            return true;
        }
        std::ostringstream message;
        message << "ART was still processing " << p->path << " after "
                << PREVIEW_WAIT_SECONDS << " s";
        reply = error_reply(p->id_json, "timeout", message.str());
    }
    Connection *c = p->c;
    previews_.erase(p);
    delete p; // its timer goes away as this returns false
    send(c, reply);
    return false;
}

void LiveControl::drop_previews(Connection *c)
{
    for (auto it = previews_.begin(); it != previews_.end();) {
        PendingPreview *p = *it;
        if (c && p->c != c) {
            ++it;
            continue;
        }
        it = previews_.erase(it);
        remove_timer(p->timer);
        delete p;
    }
}

}} // namespace art::gui
