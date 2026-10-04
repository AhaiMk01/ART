"""Saving sidecars safely: change detection, merging and atomic writes.

Pure logic, no MCP: the Render server's ``save_sidecar`` is built on it.
"""

import hashlib
import os
import shutil
from pathlib import Path

from art_mcp.keyfile import KeyFile


def write_with_backup(target: Path, text: str, backup: bool = True) -> None:
    """Replace ``target`` atomically (temp file, then rename), first copying
    an existing ``target`` to ``<target>.bak`` (replacing any older backup)."""
    temp = target.with_name(target.name + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8", newline="")
        if backup and target.is_file():
            shutil.copyfile(target, target.with_name(target.name + ".bak"))
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
