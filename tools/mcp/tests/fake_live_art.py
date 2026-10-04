"""A stand-in for ART's control channel: a loopback TCP server speaking the
JSON-lines protocol, with its discovery file in a temp config folder."""

import json
import os
import socket
import time
import struct
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

Reply = Callable[[dict[str, Any]], bytes | None]
"""Given a request, the raw bytes to send back (None: send nothing)."""


def answer(result: Any) -> Reply:
    return lambda req: (json.dumps({"id": req.get("id"), "ok": True, "result": result}) + "\n").encode()


def fail(code: str, message: str) -> Reply:
    return lambda req: (
        json.dumps({"id": req.get("id"), "ok": False, "error": {"code": code, "message": message}}) + "\n"
    ).encode()


class FakeArt:
    def __init__(self, config_dir: Path, token: str = "s3cret", pid: int | None = None) -> None:
        self.config_dir = config_dir
        self.token = token
        self.ops: dict[str, Reply] = {
            "status": answer({"version": "1.26.test", "images": []}),
        }
        self.received: list[bytes] = []
        self.rejected = 0
        self.reset_on_reject = False
        """Close a refused connection with a TCP reset, as Windows may."""
        self._sock = socket.create_server(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self.write_discovery(pid if pid is not None else os.getpid())

    def write_discovery(self, pid: int, token: str | None = None) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "live-control.json").write_text(
            json.dumps({"port": self.port, "token": token or self.token, "pid": pid, "version": "1.26.test"})
        )

    def close(self) -> None:
        self._stop.set()
        self._sock.close()
        self._thread.join(timeout=5)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            self._converse(conn)
        except OSError:
            pass  # the client gave up (e.g. after its timeout): nothing to do

    def _converse(self, conn: socket.socket) -> None:
        with conn, conn.makefile("rb") as lines:
            first = lines.readline()
            self.received.append(first)
            try:
                ok = json.loads(first).get("token") == self.token
            except ValueError:
                ok = False
            if not ok:
                self.rejected += 1
                if self.reset_on_reject:
                    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                return  # like ART: close on a wrong token
            for line in lines:
                self.received.append(line)
                req = json.loads(line)
                reply = self.ops.get(req["op"], fail("unknown_op", f"unknown op: {req['op']}"))(req)
                if isinstance(reply, list):  # trickle: one chunk every 0.3 s
                    for chunk in reply:
                        time.sleep(0.3)
                        conn.sendall(chunk)
                elif reply is not None:
                    conn.sendall(reply)
