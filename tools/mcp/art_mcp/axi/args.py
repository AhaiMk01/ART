"""Parsing a command line: the parser, the value types of flags, and which
open images a command's PATHs (or ``--all``) stand for."""

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from art_mcp.axi.core import Command, Context, Failure, Parser, UsageError
from art_mcp.axi.output import shown


def comma_floats(count: int, name: str) -> Callable[[str], list[float]]:
    def parse(text: str) -> list[float]:
        try:
            values = [float(v) for v in text.split(",")]
        except ValueError:
            raise argparse.ArgumentTypeError(f"{name} takes {count} comma-separated numbers, not {text!r}") from None
        if len(values) != count:
            raise argparse.ArgumentTypeError(f"{name} takes {count} comma-separated numbers, not {text!r}")
        return values

    return parse


def raw_edit(text: str) -> dict[str, str]:
    """``Group/Key=value`` as a raw edit."""
    target, sep, value = text.partition("=")
    group, slash, key = target.partition("/")
    if not sep or not slash or not group or not key:
        raise argparse.ArgumentTypeError(f"--set takes Group/Key=value, not {text!r}")
    return {"group": group, "key": key, "value": value}


def mark(text: str) -> dict[str, Any]:
    """``x,y[,size[,label]]``."""
    parts = text.split(",", 3)
    try:
        spec: dict[str, Any] = {"x": int(parts[0]), "y": int(parts[1])}
        if len(parts) > 2 and parts[2]:
            spec["size"] = int(parts[2])
    except (ValueError, IndexError):
        raise argparse.ArgumentTypeError(f"--mark takes x,y[,size[,label]] in frame pixels, not {text!r}") from None
    if len(parts) > 3:
        spec["label"] = parts[3]
    return spec


def spot(text: str) -> dict[str, int]:
    """``x,y[,size]``."""
    try:
        values = [int(v) for v in text.split(",")]
    except ValueError:
        values = []
    if len(values) not in (2, 3):
        raise argparse.ArgumentTypeError(f"--spot takes x,y[,size] in frame pixels, not {text!r}")
    return dict(zip(("x", "y", "size"), values, strict=False))


def names(text: str) -> list[str]:
    return [n.strip() for n in text.split(",") if n.strip()]


SIDECAR_SUFFIXES = (".arp", ".bak")
"""Files a shell glob over a roll's folder picks up beside the images."""

CHANGING = ("edit", "reset", "save", "export", "preset")
"""Commands that change or write something: their --all must stay in one folder."""


def add_paths(p: Parser, help: str) -> None:
    """The PATH arguments of a command that works on open images, and --all."""
    p.add_argument(
        "paths", nargs="*", metavar="PATH",
        help=f"{help}; a folder stands for the open images in it; sidecar files (.arp, .bak) are skipped",
    )  # fmt: skip
    p.add_argument(
        "--all", action="store_true",
        help="every open image in art-axi, from any folder (changing commands refuse when that is more than one "
        "folder: give the roll's folder instead)",
    )  # fmt: skip


def open_in(ctx: Context, folder: Path) -> list[str]:
    """The open images directly in ``folder``, by name."""
    key = os.path.normcase(str(folder.resolve()))
    found = [wp.image for wp in ctx.store().all() if os.path.normcase(str(wp.image.parent)) == key]
    return [str(image) for image in sorted(found, key=lambda image: image.name.lower())]


def select_paths(ctx: Context, command: Command, a: argparse.Namespace) -> str | None:
    """Settle ``a.paths``: the open images with --all, else the PATHs given
    without sidecar files. Returns a note on what was skipped, if anything."""
    if not hasattr(a, "paths"):
        return None
    if getattr(a, "all", False):
        if a.paths:
            raise UsageError("give PATHs or --all, not both", f"art-axi {command.name} --all")
        a.paths = [str(wp.image) for wp in ctx.store().all()]
        if not a.paths and command.name != "close":
            raise Failure("no images are open", "art-axi open <path>...", "not_open")
        folders = sorted({shown(Path(p).parent) or "" for p in a.paths})
        if command.name in CHANGING and len(folders) > 1:
            raise UsageError(
                f"--all would {command.name} open images in {len(folders)} folders: {' '.join(folders)}",
                [f"art-axi {command.name} <roll folder>  (the open images in it)",
                 "art-axi close <folder>  (close a roll you are done with)"],
            )  # fmt: skip
        return None
    kept: list[str] = []
    for path in a.paths:
        if path.lower().endswith(SIDECAR_SUFFIXES):
            continue
        if command.name != "open" and Path(path).is_dir():
            inside = open_in(ctx, Path(path))
            if not inside and command.name != "close":
                raise Failure(f"no open images in {shown(path)}", f"art-axi open {shown(path)}/*", "not_open")
            kept.extend(inside)
        else:
            kept.append(path)
    skipped = sum(1 for path in a.paths if path.lower().endswith(SIDECAR_SUFFIXES))
    if not kept:
        if command.name == "close" and a.paths:
            return None
        what = "only sidecar files given" if a.paths else "no images given"
        raise UsageError(
            what, [f"art-axi {command.name} <image>... | <folder>", f"art-axi {command.name} --all  (every open image)"]
        )
    a.paths = kept
    return f"{skipped} sidecar file(s) among the paths (.arp or .bak)" if skipped else None


def has_failures(out: dict[str, Any]) -> bool:
    """Whether a batch result reports an image that failed (exit code 1)."""
    failed = out.get("failed")
    if isinstance(failed, bool):
        return False
    return bool(failed) or bool(out.get("errors"))
