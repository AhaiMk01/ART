"""Where a Render session keeps what it knows about an image.

A ``ProfileStore`` holds, per image, the working profile with the record of
the changes made to it, the baseline it was loaded against (for the save
conflict check), and the frame-size cache. ``MemoryStore`` keeps all that in
the process, which is what the MCP server wants; another store (a session
directory for a command-line front end) can keep it between processes.

An operation that changes a ``WorkingProfile`` hands it back with ``put``, so
a store that copies state can write it back; ``MemoryStore`` hands out the
same object every time. The session holds the image's lock around all of it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from art_mcp.concurrency import image_key
from art_mcp.keyfile import KeyFile
from art_mcp.profile import WorkingChanges
from art_mcp.render.artcli import Rect

FrameKey = tuple[str, int, int, str]
"""(image, mtime in ns, size, frame-defining profile layer)."""


@dataclass
class WorkingProfile:
    image: Path
    changes: WorkingChanges
    sidecar_hash: str | None
    """SHA-256 of the sidecar on disk when this working profile was loaded
    (whichever source it was loaded from), or None if there was none: the
    baseline for detecting that someone else changed the sidecar."""
    sidecar_keys: KeyFile
    """That sidecar's content, to tell what someone else changed in it."""
    token: str
    """Identifies one load (open or reset) of the image; a save compares it to
    notice that the image was reloaded meanwhile."""


class ProfileStore(Protocol):
    def get(self, image: Path) -> WorkingProfile | None:
        """The working profile of ``image`` (a resolved path), if it is open."""
        ...

    def put(self, profile: WorkingProfile) -> None:
        """Store ``profile`` (new, or changed since ``get``) for its image."""
        ...

    def discard(self, image: Path) -> None:
        """Forget ``image``; nothing if it isn't open."""
        ...

    def all(self) -> list[WorkingProfile]:
        """Every open image's working profile."""
        ...

    def get_frame(self, key: FrameKey) -> Rect | None: ...

    def put_frame(self, key: FrameKey, frame: Rect) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._working: dict[str, WorkingProfile] = {}
        self._frames: dict[FrameKey, Rect] = {}

    def get(self, image: Path) -> WorkingProfile | None:
        return self._working.get(image_key(image))

    def put(self, profile: WorkingProfile) -> None:
        self._working[image_key(profile.image)] = profile

    def discard(self, image: Path) -> None:
        self._working.pop(image_key(image), None)

    def all(self) -> list[WorkingProfile]:
        return list(self._working.values())

    def get_frame(self, key: FrameKey) -> Rect | None:
        return self._frames.get(key)

    def put_frame(self, key: FrameKey, frame: Rect) -> None:
        self._frames[key] = frame
