"""What ``art-axi`` keeps between its runs, in one state folder.

Each run is its own process, so the working profiles the MCP server holds in
memory live on disk here instead: one JSON file per open image under
``images/``, one per measured frame under ``frames/``, a lock file per image
under ``locks/`` (so two runs about one image wait for each other) and the
rendered previews under ``previews/``, kept a day so an agent can open them
after the run that wrote them has exited.
"""

import dataclasses
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from art_mcp.concurrency import ImageLocks, image_key
from art_mcp.preview import PreviewFolder
from art_mcp.profile import WorkingChanges
from art_mcp.render.artcli import Rect
from art_mcp.render.store import FrameKey, WorkingProfile

PREVIEW_LIFETIME = 24 * 3600
"""Seconds a preview stays in the state folder."""


def default_home(environ: dict[str, str] | os._Environ[str] = os.environ) -> Path:
    """``ART_AXI_HOME``, else the platform's per-user state folder."""
    if environ.get("ART_AXI_HOME"):
        return Path(environ["ART_AXI_HOME"])
    if sys.platform == "win32" and environ.get("LOCALAPPDATA"):
        return Path(environ["LOCALAPPDATA"]) / "art-axi"
    base = environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "art-axi"


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _write_atomic(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(text, encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(temp, target)
            return
        except PermissionError:
            # Windows refuses while another run has the target open to read.
            if attempt == 19:
                temp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


class DiskStore:
    """A ``ProfileStore`` in the state folder (see ``render.store``)."""

    def __init__(self, home: Path) -> None:
        self.images = home / "images"
        self.frames = home / "frames"

    def _image_file(self, image: Path) -> Path:
        return self.images / f"{_digest(image_key(image))}.json"

    def get(self, image: Path) -> WorkingProfile | None:
        data = _read_json(self._image_file(image))
        return None if data is None else _from_json(data)

    def put(self, profile: WorkingProfile) -> None:
        _write_atomic(self._image_file(profile.image), json.dumps(_to_json(profile)))

    def discard(self, image: Path) -> None:
        self._image_file(image).unlink(missing_ok=True)

    def all(self) -> list[WorkingProfile]:
        if not self.images.is_dir():
            return []
        found = []
        for file in sorted(self.images.glob("*.json")):
            data = _read_json(file)
            if data is not None:
                found.append(_from_json(data))
        return sorted(found, key=lambda wp: str(wp.image).lower())

    def get_frame(self, key: FrameKey) -> Rect | None:
        data = _read_json(self.frames / f"{_digest(json.dumps(list(key)))}.json")
        return None if data is None else Rect(*data)

    def put_frame(self, key: FrameKey, frame: Rect) -> None:
        _write_atomic(self.frames / f"{_digest(json.dumps(list(key)))}.json", json.dumps(dataclasses.astuple(frame)))


def _to_json(wp: WorkingProfile) -> dict[str, Any]:
    return {
        "image": str(wp.image),
        "profile": wp.changes.profile,
        "loaded": wp.changes.loaded_values(),
        "sidecar_hash": wp.sidecar_hash,
        "sidecar_keys": wp.sidecar_keys,
        "token": wp.token,
        "default": wp.default,
    }


def _from_json(data: dict[str, Any]) -> WorkingProfile:
    return WorkingProfile(
        image=Path(data["image"]),
        changes=WorkingChanges.restore(data["profile"], [tuple(t) for t in data["loaded"]]),
        sidecar_hash=data["sidecar_hash"],
        sidecar_keys=data["sidecar_keys"],
        token=data["token"],
        default=data["default"],
    )


class FileImageLocks(ImageLocks):
    """``ImageLocks`` that also hold a lock file per image, so runs in other
    processes wait too. Reentrant within a thread, as ``ImageLocks`` is."""

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.folder = folder
        self._depth = threading.local()

    @contextmanager
    def hold(self, path: str | Path) -> Iterator[None]:
        key = image_key(Path(path).resolve())
        with super().hold(path):
            depths: dict[str, int] = self._depth.__dict__.setdefault("by_key", {})
            if depths.get(key, 0):
                depths[key] += 1
                try:
                    yield
                finally:
                    depths[key] -= 1
                return
            self.folder.mkdir(parents=True, exist_ok=True)
            with open(self.folder / f"{_digest(key)}.lock", "a+b") as handle:
                _lock(handle.fileno())
                depths[key] = 1
                try:
                    yield
                finally:
                    depths[key] = 0
                    _unlock(handle.fileno())


if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # retries for ~10 s, then raises
                return
            except OSError:
                continue

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class StatePreviews(PreviewFolder):
    """Preview files that outlive the run: names unique across processes, and
    files older than ``PREVIEW_LIFETIME`` swept when a run starts."""

    def new_file(self, stem: str, suffix: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / f"{stem}-{uuid.uuid4().hex[:10]}{suffix}"

    def sweep(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_file() and now - entry.stat().st_mtime > PREVIEW_LIFETIME:
                    entry.unlink()
            except OSError:
                pass
