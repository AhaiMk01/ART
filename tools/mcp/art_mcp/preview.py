"""Where rendered previews are written: one folder per server process."""

import itertools
import os
import shutil
import tempfile
from pathlib import Path


def default_root() -> Path:
    return Path(tempfile.gettempdir()) / f"art-mcp-{os.getpid()}"


class PreviewFolder:
    """Hands out unique file names, so earlier previews stay viewable for
    comparison; the whole folder goes away with the server."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._counter = itertools.count(1)

    def new_file(self, stem: str, suffix: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / f"{stem}-{next(self._counter):04d}{suffix}"

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
