"""Shaping results before they are printed: paths, pruning, numbers, tables
and progress. Imports nothing else of ``art-axi``."""

import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

TRUNCATE = 1200
"""Characters of long text a detail view shows before `--full`."""


def shown(path: str | Path | None) -> str | None:
    """A path as output shows it: forward slashes, which Windows takes too and
    TOON need not escape. Kept absolute: an agent passes it to tools that
    don't expand ``~``."""
    return None if path is None else Path(path).resolve().as_posix()


def home_relative(path: Path) -> str:
    """``path`` with the home folder as ``~`` (the home view's ``bin``)."""
    text, home = path.as_posix(), Path.home().as_posix()
    if text.lower().startswith(home.lower() + "/"):
        return "~" + text[len(home) :]
    return text


def prune(value: Any) -> Any:
    """``value`` without None, empty dicts and empty lists (recursively): a
    field that carries nothing costs tokens and says nothing."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        pruned = {k: prune(v) for k, v in value.items()}
        return {k: v for k, v in pruned.items() if v is not None and v != {} and v != []}
    if isinstance(value, list):
        return [prune(v) for v in value]
    return value


def typed(groups: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Stored ``[Group] Key`` values (strings in the .arp) with the ones that
    are numbers as numbers, so they print unquoted."""
    return {group: {key: as_number(value) for key, value in entries.items()} for group, entries in groups.items()}


def as_number(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    for kind in (int, float):
        try:
            number = kind(value)
        except ValueError:
            continue
        return number if math.isfinite(number) else value
    return value


def rows(items: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    """``items`` with exactly ``fields`` each (missing ones null), so they
    print as one table."""
    return [{f: item.get(f) for f in fields} for item in items]


def truncated(text: str, full: bool) -> str:
    if full or len(text) <= TRUNCATE:
        return text
    return f"{text[:TRUNCATE]}... (truncated, {len(text)} chars total)"


def progress(verb: str) -> Callable[[int, int], None] | None:
    """A progress reporter on stderr, only when stderr is a terminal: an agent
    that captures both streams would read it as output."""
    if not sys.stderr.isatty():
        return None

    def report(done: int, total: int) -> None:
        print(f"{verb} {done}/{total}", file=sys.stderr, flush=True)

    return report


def image_labels(paths: list[str]) -> tuple[str | None, dict[str, str]]:
    """How tables name images: their file name when all are in one folder
    (given once, as `folder`), else their absolute path."""
    resolved = {p: Path(p).resolve() for p in paths}
    parents = {r.parent for r in resolved.values()}
    if len(parents) == 1 and len({r.name for r in resolved.values()}) == len(resolved):
        return shown(parents.pop()), {p: r.name for p, r in resolved.items()}
    return None, {p: shown(r) or p for p, r in resolved.items()}
