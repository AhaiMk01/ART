"""Where rendered previews are written: one folder per server process."""

import itertools
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


def default_root() -> Path:
    return Path(tempfile.gettempdir()) / f"art-mcp-{os.getpid()}"


def pid_alive(pid: int) -> bool:
    """Whether a process with this pid is running."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            # Access denied means it exists (another user's); anything else, gone.
            return bool(ctypes.get_last_error() == 5)
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return bool(code.value == 259)  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


_FOLDER_NAME = re.compile(r"art-mcp-(\d+)")


def sweep_stale(temp_dir: Path | None = None) -> None:
    """Remove ``art-mcp-<pid>`` preview folders left in ``temp_dir`` by
    servers that are no longer running. Never touches this process's folder or
    any other name."""
    temp_dir = temp_dir or Path(tempfile.gettempdir())
    try:
        entries = list(temp_dir.iterdir())
    except OSError:
        return
    for entry in entries:
        m = _FOLDER_NAME.fullmatch(entry.name)
        if m and entry.is_dir() and int(m[1]) != os.getpid() and not pid_alive(int(m[1])):
            shutil.rmtree(entry, ignore_errors=True)


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
