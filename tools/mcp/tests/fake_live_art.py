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

from art_mcp import keyfile

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


class FakeEditor:
    """Images open in a fake ART's editor, each with a processing profile and
    a History, behind the ops that read and change them (status, get_profile,
    apply_profile, undo, redo, open, save_sidecar)."""

    def __init__(self, art: FakeArt) -> None:
        self.art = art
        self.images: dict[str, dict[str, Any]] = {}
        self.applied: list[dict[str, str]] = []
        """The args of every apply_profile received."""
        self.saved: list[str] = []
        self.loadable: set[str] = set()
        """Paths `open` can open; they are listed `open_delay` s later."""
        self.open_delay = 0.0
        art.ops.update({
            "status": self._status,
            "get_profile": self._get_profile,
            "apply_profile": self._apply,
            "undo": lambda req: self._step(req, -1),
            "redo": lambda req: self._step(req, +1),
            "open": self._open,
            "save_sidecar": self._save,
        })  # fmt: skip

    def add(self, path: str, profile: str, width: int | None = 6000, height: int | None = 4000) -> None:
        self.images[os.path.normcase(path)] = {
            "path": path, "width": width, "height": height,
            "history": [("Photo loaded", keyfile.loads(profile))], "position": 0,
        }  # fmt: skip

    def profile(self, path: str) -> keyfile.KeyFile:
        image = self.images[os.path.normcase(path)]
        result: keyfile.KeyFile = image["history"][image["position"]][1]
        return result

    def labels(self, path: str) -> list[str]:
        return [label for label, _ in self.images[os.path.normcase(path)]["history"]]

    def _image(self, req: dict[str, Any]) -> dict[str, Any] | None:
        return self.images.get(os.path.normcase(req["args"].get("path", "")))

    def _status(self, req: dict[str, Any]) -> bytes | None:
        images = [
            {"path": i["path"], "active": n == 0, "width": i["width"], "height": i["height"]}
            for n, i in enumerate(list(self.images.values()))
        ]
        return answer({"version": "1.26.test", "images": images})(req)

    def _not_open(self, req: dict[str, Any]) -> bytes | None:
        return fail("not_open", f"{req['args'].get('path')} is not open in ART")(req)

    def _get_profile(self, req: dict[str, Any]) -> bytes | None:
        image = self._image(req)
        if image is None:
            return self._not_open(req)
        text = keyfile.dumps(image["history"][image["position"]][1])
        return answer({"profile": text, "history_position": image["position"]})(req)

    def _apply(self, req: dict[str, Any]) -> bytes | None:
        image = self._image(req)
        if image is None:
            return self._not_open(req)
        self.applied.append(req["args"])
        merged = {g: dict(keys) for g, keys in image["history"][image["position"]][1].items()}
        for group, keys in keyfile.loads(req["args"]["profile"]).items():
            merged.setdefault(group, {}).update(keys)
        del image["history"][image["position"] + 1 :]
        image["history"].append((req["args"]["label"], merged))
        image["position"] = len(image["history"]) - 1
        return answer({"history_position": image["position"]})(req)

    def _step(self, req: dict[str, Any], by: int) -> bytes | None:
        image = self._image(req)
        if image is None:
            return self._not_open(req)
        image["position"] = min(max(image["position"] + by, 0), len(image["history"]) - 1)
        return answer({"history_position": image["position"]})(req)

    def _open(self, req: dict[str, Any]) -> bytes | None:
        path = req["args"]["path"]
        if self._image(req) is not None:
            return answer({"already_open": True})(req)
        if path not in self.loadable:
            return fail("not_found", f"{path} does not exist")(req)

        def load() -> None:
            time.sleep(self.open_delay)
            self.add(path, "[Exposure]\nCompensation=0\n")

        threading.Thread(target=load, daemon=True).start()
        return answer({"already_open": False})(req)

    def _save(self, req: dict[str, Any]) -> bytes | None:
        image = self._image(req)
        if image is None:
            return self._not_open(req)
        self.saved.append(image["path"])
        return answer({"sidecar": image["path"] + ".arp"})(req)
