# Control channel options for a running ART GUI

Research for [#5](https://github.com/AhaiMk01/ART/issues/5), part of the Live server map ([#1](https://github.com/AhaiMk01/ART/issues/1)).

**Question.** What cross-platform mechanisms (Windows first, then Linux and macOS) let an external process, the Live server (a stdio MCP server in Python or TypeScript), send commands to a running ART GTKmm 3 editor and get replies? This note compares security, main-loop and threading integration, payload size, and how much C++ each needs in `src/gui/`.

This note gathers facts only. A later grilling ticket makes the choice.

Sources: ART source at `bcc187845`, GLib `main` from gitlab.gnome.org (the files are named below), Microsoft Learn, the D-Bus spec, and the Python and Node.js docs. "Inference" marks a conclusion I drew rather than one a source states.

---

## 1. What ART already does

- **Two startup paths.** `main()` sets `remote = true` by default (`src/gui/main.cc:511`). Only in that case does it run `RTApplication`, a `Gtk::Application("us.pixls.art.ART", SEND_ENVIRONMENT | HANDLES_COMMAND_LINE)` (`main.cc:277`, `main.cc:680-697`). The `-N`, `-s` and `-gimp` options set `remote = false` (`main.cc:143-163`). In that mode ART runs a plain `Gtk::Main` with no `GApplication` and so has **no D-Bus presence at all** (`main.cc:698-707`). A GApplication-based channel would not exist in those modes.
- **How GUI work is marshalled.** ART uses the deprecated GDK global lock. `gdk_threads_set_lock_functions` is backed by a recursive mutex (`main.cc:83-89`, `main.cc:673-675`), and the `GThreadLock` RAII wrapper is in `src/gui/guiutils.h:109`. Work coming from other threads is posted with `gdk_threads_add_idle` / `IdleRegister::add` (`guiutils.cc:75`, `main.cc:388`, `main.cc:417`). The existing command-line forwarding already uses this pattern: `on_command_line` runs `process_command_line`, which queues an idle callback that drives `FileCatalog`. Any channel can reuse it: receive anywhere, then hop to the main loop with an idle callback.
- **The D-Bus bus is shipped on every platform.**
  - Windows: the installer and bundler ship `gdbus.exe` (`tools/win/InnoSetup/WindowsInnoSetup.iss.in:99`, `tools/win/bundle_ART.py:145`). GLib needs it to autolaunch a session bus (section 2).
  - macOS: the app bundle ships `dbus-daemon`. The launcher starts a **private** bus at `unix:path=$TMPDIR/ART-$USER/dbus.sock`, inside a directory created with mode `0700`, and exports `DBUS_SESSION_BUS_ADDRESS` (`tools/osx/launcher.c:359-410`, `tools/osx/bundle_ART.py:89,291-294`).
  - Linux: the desktop session bus.
- **GLib version floor.** The build requires `glib-2.0 >= 2.44` and `gio-2.0 / giomm-2.4 >= 2.44` (`CMakeLists.txt:401-405`). This matters for AF_UNIX on Windows, which needs GLib ≥ 2.72 (section 3).
- **Console subsystem.** Release builds on Windows link with `-mwindows` (`src/gui/CMakeLists.txt:287-288`), so the process has no console. stdio still works when a parent passes pipe handles. The code base has about 178 `printf`/`std::cout` sites in `src/gui/*.cc`, which matters for the stdin/stdout option (section 5).

## 2. GApplication / GDBus

**How it works.** `GApplication` registration connects to the session bus. It exports `org.gtk.Application`, `org.freedesktop.Application` and `org.gtk.Actions` (the action group) at an object path derived from the application ID (`/us/pixls/art/ART`), then claims the well-known bus name (`gio/gapplicationimpl-dbus.c:439-483`).

- **Remote actions return no value.** `org.freedesktop.Application.ActivateAction(s, av, a{sv})` and `org.gtk.Actions.Activate` have no out arguments (`gapplicationimpl-dbus.c:87-90`). Plain actions are fire-and-forget. A request/reply API therefore needs a **custom D-Bus interface**. That is the intended use of the `dbus_register` vfunc: "export extra objects on the bus … passed the GDBusConnection to the session bus, and the object path" (`gio/gapplication.c:206-212`). With giomm this means `Gio::DBus::Connection::register_object` plus an introspection XML. Method calls give real replies and errors.
- **Threading.** GDBus does its I/O on a private worker thread. Method handlers run in the thread-default main context of the thread that registered the object, which for ART is the GTK main thread. GLib states this in the `g_dbus_connection_register_object` docs; I did not re-check it in source. Handlers are therefore already on the main loop. A slow reply such as a render can be deferred with `g_dbus_method_invocation_return_*` later, so the loop is not blocked.
- **Payload size.** GDBus rejects messages over 128 MiB ("exceeds maximum message length (128MiB)", `gio/gdbusmessage.c:2287`). The D-Bus spec also caps arrays at 64 MiB. A JPEG/PNG preview of a few MB fits as `ay`, but it is copied through the bus daemon. On Linux and macOS a fd could be passed instead (`h` type); the Windows transport has no fd passing.
- **No bus means no channel.** If `g_bus_get_sync(SESSION)` fails, GApplication "proceed[s] as a normal non-unique application" (`gapplicationimpl-dbus.c:651-660`), and `dbus_register` is never called.

**How the bus works on Windows** (`gio/gdbusprivate.c:2029-2400`):

- The session address is `autolaunch:`. `_g_dbus_win32_get_session_address_dbus_launch` takes named mutexes (`DBusAutolaunchMutex`, `UniqueDBusInitMutex`, `DBusDaemonMutex`) and reads the bus address from a named shared-memory section `DBusDaemonAddressInfo`. If no bus is running, it launches `gdbus.exe _win32_run_session_bus`, which it finds next to `libgio`.
- The daemon listens on **`nonce-tcp:`**, which is TCP on loopback plus a 16-byte nonce file created with `g_file_open_tmp` (`gdbusprivate.c:2263`, `gio/gdbusserver.c:887-936`).
- These kernel object names have no `Global\` prefix. They therefore live in the per-logon-session namespace (Microsoft, *Kernel object namespaces*). So one bus per interactive session, and different GLib apps in that session share it. GLib's own comment warns that different libgio versions shipped with different apps can break each other (`gdbusprivate.c:2106-2113`).
- **Authentication on Windows is weak.**
  - The server side of `EXTERNAL` cannot verify a Windows SID: "TODO: Dont know how to compare credentials on this OS" (`gio/gdbusauthmechanismexternal.c:235`). The bus therefore relies on the nonce file in `%TEMP%` plus `DBUS_COOKIE_SHA1`.
  - The `DBUS_COOKIE_SHA1` keyring dir has no permission check on Windows (`gio/gdbusauthmechanismsha1.c:345-353`).
  - `gdbusdaemon.c:1599-1603` notes that authentication "hasn't been implemented yet" on Windows for the default daemon address.
  - Inference: isolation from other users rests on the per-user ACLs on `%TEMP%` and the profile, not on D-Bus auth.
- **Clients.** Every process on the bus can call ART's custom interface. D-Bus adds no per-caller auth, so a token or sender check would still be ours to add.
  - Inference, not verified: common Python and Node D-Bus libraries (jeepney, dbus-next and similar) target `unix:` addresses. They do not implement GLib's Windows shared-memory autolaunch discovery or `nonce-tcp`. A Windows Live server would likely need PyGObject/Gio or would have to shell out to `gdbus.exe call`.

**C++ cost.** Small. Override `dbus_register`/`dbus_unregister` in `RTApplication`, add an introspection XML string, and one dispatcher. Most work is the command surface itself.

## 3. Gio sockets (`GSocketService`)

- **Main-loop integration.**
  - `GSocketService` "runs on the main loop of the thread-default context … of the thread it is created in". Its `incoming` handler "must immediately return" (`gio/gsocketservice.c:43-53`). Async reads and writes (`g_input_stream_read_async`, `g_output_stream_write_all_async`) then keep everything on the GTK main thread with no new locking.
  - `GThreadedSocketService` instead runs each connection on a thread-pool worker (`gio/gthreadedsocketservice.c:29-39`). Handlers must then hop to the main loop with `gdk_threads_add_idle`, as ART already does.
- **TCP on localhost** (`127.0.0.1`, port 0 = ephemeral).
  - Portable and trivial for any client language.
  - **Any local process of any user can connect.** Loopback TCP has no peer identity. Inference: authentication must come from a random token written to a file that only the user can read (for example under ART's config dir), which the client sends first.
  - Payload size is unlimited (a stream), and we choose the framing (length-prefixed JSON plus a binary blob).
- **Unix-domain sockets.**
  - Linux/macOS: the filesystem path is protected by a 0700 parent directory. Peer credentials are available via `g_socket_get_credentials`, which uses `SO_PEERCRED` on Linux and `LOCAL_PEERCRED`/`xucred` on macOS (`gio/gsocket.c:6339-6393`). Linux also has abstract names; other systems return `G_IO_ERROR_NOT_SUPPORTED` (`gio/gunixsocketaddress.c:43-50`).
  - Windows AF_UNIX: since GLib 2.72 "`GUnixSocketAddress` is available on all platforms. It requires underlying system support (such as Windows 10 with `AF_UNIX`)" (`gunixsocketaddress.c:52-58`). GLib gets the peer PID via `SIO_AF_UNIX_GETPEERPID` (`G_CREDENTIALS_TYPE_WIN32_PID`, `gsocket.c:6443-6456`).
  - Microsoft: AF_UNIX shipped in Insider build 17063. It has no `SOCK_DGRAM`, no ancillary data (no fd or credential passing), no abstract autobind, and no `socketpair`. Security follows filesystem permissions: bind needs write access to the directory, and connect needs write access to the socket file (*AF_UNIX comes to Windows*, devblogs.microsoft.com).
  - **Caveats on Windows:**
    - This needs GLib ≥ 2.72, above ART's current 2.44 floor.
    - **CPython's `socket` module has no `AF_UNIX` on Windows** (Python docs). A Python Live server would need TCP or named pipes there.
    - Node's `net` module maps an IPC path to a **named pipe** on Windows, not AF_UNIX (Node docs, "Identifying paths for IPC connections").
- **C++ cost.** Moderate: a listener, a framing parser, a per-connection object with async read/write, token checking and an endpoint discovery file. All of it is portable GIO, with one code path on all three OSes if TCP is used.

## 4. Windows named pipes

- **API.** `CreateNamedPipe(\\.\pipe\<name>, …)` with `PIPE_ACCESS_DUPLEX` and `PIPE_TYPE_BYTE` or `PIPE_TYPE_MESSAGE`.
  - **Default security descriptor:** "grant full control to the LocalSystem account, administrators, and the creator owner. They also grant read access to members of the Everyone group and the anonymous account." A private pipe therefore needs an explicit DACL granting only the current user SID.
  - `PIPE_REJECT_REMOTE_CLIENTS` "automatically rejects" connections from remote clients.
  - `FILE_FLAG_FIRST_PIPE_INSTANCE` makes a second creator fail with `ERROR_ACCESS_DENIED`, which guards against squatting.
  - Buffer sizes are advisory. Large writes block until the reader drains (as a system thread in overlapped mode).
  - Source: Microsoft Learn, *CreateNamedPipeA*.
- **Peer identity.** `GetNamedPipeClientProcessId` gives the client PID, and `ImpersonateNamedPipeClient` gives the client token, so the server can check that the caller is the same user.
- **GLib support.** GIO has no named-pipe listener; `gio/meson.build` has no namedpipe source. ART would write raw Win32 code: either overlapped I/O on a dedicated thread that posts to the main loop with `gdk_threads_add_idle`, or wrapping a connected handle in `GWin32InputStream`/`GWin32OutputStream` (public in `gio-win32-2.0`, `gio/meson.build:501-506`) and using the async stream API.
- **Clients.** Python can `open(r'\\.\pipe\name', 'r+b')` and asyncio's Proactor loop supports pipes. Node's `net.connect('\\\\.\\pipe\\name')` works natively.
- **Cost.** Moderate to high and **Windows-only**. Linux/macOS would still need a Unix-socket or TCP path, so there would be two transports behind one protocol.

## 5. Launch ART as a child and use its stdin/stdout

- **What it gives.** The parent (the Live server) owns both pipe ends. Only the parent can talk, so there is no endpoint, token or ACL to manage, and the strongest isolation comes for free. The payload is an unbounded byte stream.
- **Limits.**
  - **It cannot attach to an ART the user already has open.** The Live server must start ART.
  - On Windows a `-mwindows` GUI process still inherits std handles that the parent passes with `STARTF_USESTDHANDLES` (Win32 `CreateProcess`/`STARTUPINFO` semantics). Python `subprocess` and Node `child_process` do this.
  - **ART writes diagnostics to stdout** (about 178 `printf`/`cout` sites in `src/gui`). A clean protocol stream would need stdout redirected, or a dedicated extra pipe or handle instead of stdout.
  - **Uniqueness interferes.** A child launched while a primary ART runs just forwards its argv over D-Bus and exits (`main.cc:341-350`, GApplication semantics). The child would need `-N`/non-unique mode. That puts it on the `Gtk::Main` path, which has no `GApplication` (section 1).
- **Main-loop integration.**
  - On POSIX: `GUnixInputStream` on fd 0 with async reads on the main loop.
  - On Windows: `GWin32InputStream` on `GetStdHandle(STD_INPUT_HANDLE)`, or a reader thread plus idle callbacks. Anonymous pipes do not support overlapped I/O, so async reads end up on a GIO worker thread. That is inference from the Win32 anonymous pipe docs; I did not re-check it here.
- **C++ cost.** The smallest framing and no auth code. It needs startup-path changes (the `-N` interaction) and stdout hygiene.

## 6. Comparison

| | GApplication D-Bus (custom iface via `dbus_register`) | Gio TCP localhost | Gio Unix socket (AF_UNIX) | Windows named pipe | Child stdin/stdout |
|---|---|---|---|---|---|
| Attach to the user's running ART | Yes (`remote` mode only) | Yes | Yes | Yes | **No**, Live server must launch ART |
| Windows | Autolaunched `gdbus.exe` bus, `nonce-tcp`, weak auth | Yes | Win10 1803+ and GLib ≥ 2.72; **no CPython client** | Native | Yes |
| Linux / macOS | Session bus / ART's private bus | Yes | Yes (best fit) | n/a | Yes |
| Other local users | Session-scoped bus; Windows relies on %TEMP%/profile ACLs | **Open: needs token** | Dir perms + peer uid | Needs explicit DACL; default lets Everyone read | Isolated |
| Same-user other processes | Any bus client can call | Token | Can call (peer creds available) | Can call (client PID/token available) | Isolated |
| Replies | Method returns (custom iface only; actions return nothing) | Our framing | Our framing | Our framing | Our framing |
| Main loop | Handlers already on main thread | `GSocketService` on main loop | Same | Thread + idle, or `GWin32*Stream` | Async stream / reader thread |
| Payload | ≤128 MiB per message, copied via daemon | Unbounded stream | Unbounded stream | Unbounded stream | Unbounded stream |
| C++ in `src/gui/` | Small (vfunc + XML + dispatcher) | Moderate, one portable path | Moderate; `#ifdef`/GLib bump on Windows | Moderate-high, Windows-only | Small, plus startup/stdout changes |
| Client complexity | High on Windows (GLib-specific discovery) | Lowest | Low on POSIX, poor on Windows Python | Low (Python file, Node `net`) | Lowest |

## Sources

- ART: `src/gui/main.cc`, `src/gui/guiutils.{h,cc}`, `src/gui/CMakeLists.txt`, `CMakeLists.txt`, `tools/win/InnoSetup/WindowsInnoSetup.iss.in`, `tools/win/bundle_ART.py`, `tools/osx/launcher.c`, `tools/osx/bundle_ART.py`.
- GLib (gitlab.gnome.org/GNOME/glib, `main`): `gio/gapplication.c`, `gio/gapplicationimpl-dbus.c`, `gio/gdbusprivate.c`, `gio/gdbusserver.c`, `gio/gdbusdaemon.c`, `gio/gdbusauthmechanismexternal.c`, `gio/gdbusauthmechanismsha1.c`, `gio/gdbusmessage.c`, `gio/gsocketservice.c`, `gio/gthreadedsocketservice.c`, `gio/gunixsocketaddress.c`, `gio/gsocket.c`, `gio/meson.build`. API docs: https://docs.gtk.org/gio/class.Application.html
- Microsoft: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createnamedpipea ; https://devblogs.microsoft.com/commandline/af_unix-comes-to-windows/ ; https://learn.microsoft.com/en-us/windows/win32/termserv/kernel-object-namespaces
- D-Bus spec (message/array limits): https://dbus.freedesktop.org/doc/dbus-specification.html
- Python `socket`: https://docs.python.org/3/library/socket.html ; Node `net` IPC paths: https://nodejs.org/api/net.html#identifying-paths-for-ipc-connections
