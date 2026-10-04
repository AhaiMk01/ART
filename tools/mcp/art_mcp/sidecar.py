"""Saving sidecars safely: change detection, merging and atomic writes.

Pure logic, no MCP: the Render server's ``save_sidecar`` is built on it.
"""

import hashlib
import os
import shutil
from pathlib import Path

from art_mcp import keyfile
from art_mcp.keyfile import KeyFile


def write_atomic(target: Path, text: str) -> None:
    """Replace ``target`` atomically: temp file, then rename."""
    temp = target.with_name(target.name + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8", newline="")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def write_with_backup(target: Path, text: str) -> None:
    """``write_atomic``, first copying an existing ``target`` to
    ``<target>.bak`` (replacing any older backup)."""
    if target.is_file():
        shutil.copyfile(target, target.with_name(target.name + ".bak"))
    write_atomic(target, text)


def read(path: Path) -> bytes | None:
    """A sidecar's bytes, or None if there is none."""
    return path.read_bytes() if path.is_file() else None


def parse(data: bytes | None) -> KeyFile:
    """A sidecar's keys; empty if there is none or it doesn't parse."""
    try:
        return keyfile.loads(data.decode("utf-8")) if data is not None else {}
    except ValueError:
        return {}


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_or_none(data: bytes | None) -> str | None:
    return file_hash(data) if data is not None else None


def changed_keys(before: KeyFile, after: KeyFile) -> list[str]:
    """``[Group] Key`` of every value that differs between the two profiles
    (changed, added or removed), in file order."""
    names: list[str] = []
    for group in [*before, *(g for g in after if g not in before)]:
        old, new = before.get(group, {}), after.get(group, {})
        for key in [*old, *(k for k in new if k not in old)]:
            if old.get(key) != new.get(key):
                names.append(f"[{group}] {key}")
    return names


def merge(current: KeyFile, partial: KeyFile) -> KeyFile:
    """``current`` with the values of ``partial`` set (``current`` is left
    untouched)."""
    merged = {group: dict(entries) for group, entries in current.items()}
    for group, entries in partial.items():
        merged.setdefault(group, {}).update(entries)
    return merged
