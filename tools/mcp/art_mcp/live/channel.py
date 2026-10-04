"""Client for ART's control channel (ART started with ``--live-control``).

ART listens on 127.0.0.1 and writes ``{port, token, pid, version}`` to
``live-control.json`` in its config folder. The protocol is JSON lines: the
first line is ``{"token": ...}``, then each request ``{"id", "op", "args"}`` is
answered by ``{"id", "ok": true, "result"}`` or
``{"id", "ok": false, "error": {"code", "message"}}``. ART closes the
connection on a wrong token.

Each request uses a fresh connection, read from the discovery file at that
moment, so an ART restarted meanwhile (new port and token) is picked up.
"""

import itertools
import json
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from art_mcp.preview import pid_alive

DISCOVERY_FILE = "live-control.json"
START_HINT = "start ART with --live-control"
MAX_REPLY = 64 * 1024 * 1024


class ArtNotRunning(Exception):
    """No control-enabled ART to talk to."""


class ChannelTimeout(Exception):
    """ART accepted the request but didn't answer in time."""


class ChannelError(Exception):
    """ART answered with an error (or something that isn't the protocol)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Discovery:
    port: int
    token: str
    pid: int
    version: str


def read_discovery(config_dir: Path) -> Discovery:
    """The discovery file's content; ArtNotRunning when there is none or it
    can't be understood."""
    path = config_dir / DISCOVERY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ArtNotRunning(f"no {path}: ART isn't running with its control channel; {START_HINT}") from None
    except (OSError, ValueError) as e:
        raise ArtNotRunning(f"can't read {path} ({e}); {START_HINT}") from None
    try:
        return Discovery(
            port=int(data["port"]), token=str(data["token"]),
            pid=int(data["pid"]), version=str(data.get("version", "")),
        )  # fmt: skip
    except (KeyError, TypeError, ValueError):
        raise ArtNotRunning(f"{path} is not a control-channel discovery file; {START_HINT}") from None


class ControlChannel:
    def __init__(
        self,
        config_dir: Path,
        *,
        timeout: float = 30.0,
        host: str = "127.0.0.1",
        is_alive: Callable[[int], bool] = pid_alive,
    ) -> None:
        self.config_dir = config_dir
        self.timeout = timeout
        self.host = host
        self.is_alive = is_alive
        self._ids = itertools.count(1)

    def discover(self) -> Discovery:
        """The running ART's discovery entry; ArtNotRunning if there is none
        or its process is gone (a stale file left by a crash)."""
        found = read_discovery(self.config_dir)
        if not self.is_alive(found.pid):
            raise ArtNotRunning(
                f"the ART that wrote {self.config_dir / DISCOVERY_FILE} (pid {found.pid}) "
                f"is no longer running; {START_HINT}"
            )
        return found

    def request(self, op: str, args: dict[str, Any] | None = None) -> Any:
        """Send one request and return its ``result``. Raises ArtNotRunning,
        ChannelTimeout or ChannelError (ART's error code and message)."""
        found = self.discover()
        request_id = next(self._ids)
        try:
            sock = socket.create_connection((self.host, found.port), timeout=self.timeout)
        except TimeoutError:
            raise ArtNotRunning(f"ART (pid {found.pid}) did not accept a connection on port {found.port}; {START_HINT}") from None
        except OSError as e:
            raise ArtNotRunning(f"can't connect to ART on port {found.port} ({e}); {START_HINT}") from None
        refused = ArtNotRunning(
            "ART closed the connection without answering: the token in "
            f"{self.config_dir / DISCOVERY_FILE} was refused (stale file?); {START_HINT}"
        )
        with sock:
            try:
                sock.sendall(encode({"token": found.token}) + encode({"id": request_id, "op": op, "args": args or {}}))
                line = read_line(sock, deadline=time.monotonic() + self.timeout)
            except TimeoutError:
                raise ChannelTimeout(f"ART did not answer `{op}` within {self.timeout:g} s") from None
            except ConnectionError:
                # ART drops a connection whose token it refuses; on Windows
                # that can arrive as a reset rather than a clean close.
                raise refused from None
            except OSError as e:
                raise ArtNotRunning(f"the connection to ART failed ({e}); {START_HINT}") from None
        if line is None:
            raise refused
        return parse_reply(line, request_id)


def encode(message: dict[str, Any]) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def read_line(sock: socket.socket, deadline: float | None = None) -> bytes | None:
    """One line from ``sock`` (without the newline), or None if the peer
    closes first. ``deadline`` (``time.monotonic()``) bounds the whole read,
    not each ``recv``: a peer trickling bytes can't stretch it."""
    buf = bytearray()
    while True:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            sock.settimeout(remaining)
        chunk = sock.recv(65536)
        if not chunk:
            return None
        buf += chunk
        end = buf.find(b"\n")
        if end >= 0:
            return bytes(buf[:end])
        if len(buf) > MAX_REPLY:
            raise ChannelError("bad_reply", f"reply longer than {MAX_REPLY} bytes")


def parse_reply(line: bytes, request_id: int) -> Any:
    try:
        reply = json.loads(line)
    except ValueError:
        raise ChannelError("bad_reply", f"not JSON: {line[:200]!r}") from None
    if not isinstance(reply, dict) or reply.get("id") != request_id:
        raise ChannelError("bad_reply", f"not the reply to request {request_id}: {line[:200]!r}")
    if reply.get("ok") is True:
        return reply.get("result")
    error = reply.get("error")
    if isinstance(error, dict):
        raise ChannelError(str(error.get("code", "error")), str(error.get("message", "")))
    raise ChannelError("bad_reply", f"neither a result nor an error: {line[:200]!r}")
