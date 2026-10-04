"""Serialising work on one image across the server's worker threads.

MCP runs synchronous tool handlers on worker threads, so two calls about the
same image can really overlap. Every tool that reads or changes an image's
working state, or renders it, runs under that image's lock; the Render
server's tools get it through ``RenderSession.image(path)``.
"""

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def image_key(image: Path) -> str:
    """Identity of a resolved image path across calls (case-folded on
    Windows)."""
    return os.path.normcase(str(image))


class ImageLocks:
    """One lock per image, however the path is spelled."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    @contextmanager
    def hold(self, path: str | Path) -> Iterator[None]:
        """Wait for and hold the lock of the image at ``path``. Reentrant, so
        a tool may call another that also holds it."""
        key = image_key(Path(path).resolve())
        with self._guard:
            lock = self._locks.setdefault(key, threading.RLock())
        with lock:
            yield
