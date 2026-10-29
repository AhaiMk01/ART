"""``art-axi``: the Render server's operations as a command-line tool for
agents, following AXI (https://axi.md): TOON on stdout, errors on stdout in
the same format, exit codes 0 / 1 (the operation failed) / 2 (bad usage),
progress on stderr, no prompts.

Each run is its own process, so the working profiles live in a state folder
(``state.py``) and an image stays open from one run to the next until
``close``. The operations are the MCP server's (``render/*_ops.py``); this
module parses flags, calls them and shapes their results.
"""

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

from pydantic import BaseModel

from art_mcp import artdir
from art_mcp.axi import toon
from art_mcp.axi.state import DiskStore, FileImageLocks, StatePreviews, default_home
from art_mcp.render.errors import RenderError

DESCRIPTION = "Edit and render raw images with ART headlessly"
TRUNCATE = 1200
"""Characters of long text a detail view shows before `--full`."""

GLOBAL_FLAGS = ("--art-dir", "--timeout")
"""Flags every command takes (with a value), before or after the command."""

EXIT_OK = 0


class Failure(Exception):
    """An operation that can't do what was asked: printed, exit code 1."""

    exit_code = 1

    def __init__(self, message: str, help: list[str] | str | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.help = help
        self.code = code


class UsageError(Failure):
    """A command line that asks for nothing that can be done: exit code 2."""

    exit_code = 2

    def __init__(self, message: str, help: list[str] | str | None = None) -> None:
        super().__init__(message, help, "usage")


# -- output ------------------------------------------------------------------


def emit(data: dict[str, Any]) -> None:
    print(toon.encode(data))


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


def progress(verb: str) -> Callable[[int, int], None]:
    def report(done: int, total: int) -> None:
        print(f"{verb} {done}/{total}", file=sys.stderr, flush=True)

    return report


# -- the session ---------------------------------------------------------------


@dataclass
class Context:
    home: Path
    art_dir: str | None
    timeout: float | None
    session_factory: Callable[["Context"], Any] | None = None
    """Builds the session instead of finding art-cli (tests)."""
    _session: Any = None

    def store(self) -> DiskStore:
        return DiskStore(self.home)

    def session(self) -> Any:
        """The Render session over the state folder; finds art-cli first."""
        if self._session is None and self.session_factory is not None:
            self._session = self.session_factory(self)
        if self._session is None:
            from art_mcp.metadata import Exiftool
            from art_mcp.render.artcli import ArtCli
            from art_mcp.render.session import RenderSession

            program_files = artdir.windows_install_root(os.environ)
            folder = artdir.find_art_dir(self.art_dir, os.environ, program_files)
            cli_path = artdir.find_cli(folder) if folder else None
            if cli_path is None:
                raise Failure(
                    "ART-cli not found",
                    ["set ART_DIR to the folder holding ART-cli", "or pass --art-dir <folder> to any command"],
                    "art_not_found",
                )
            exiftool = artdir.locate_exiftool(folder, os.environ, program_files)
            previews = StatePreviews(self.home / "previews")
            previews.sweep()
            self._session = RenderSession(
                ArtCli((str(cli_path),), timeout=self.timeout or 60.0, export_timeout=self.timeout or 120.0),
                artdir.user_config_dir(os.environ, art_dir=folder),
                previews,
                Exiftool((str(exiftool),)) if exiftool else None,
                inline_previews=False,
                store=self.store(),
                locks=FileImageLocks(self.home / "locks"),
            )
        return self._session


def art_cli_location(art_dir: str | None) -> str:
    folder = artdir.find_art_dir(art_dir, os.environ, artdir.windows_install_root(os.environ))
    cli = artdir.find_cli(folder) if folder else None
    return shown(cli) if cli else "not found (set ART_DIR or pass --art-dir)"


def edit_count(wp: Any) -> int:
    """How many values the agent changed since the image was loaded."""
    profile = wp.changes.profile
    return sum(1 for group, key, loaded in wp.changes.loaded_values() if profile.get(group, {}).get(key) != loaded)


# -- error translation ---------------------------------------------------------

ERROR_HELP = {
    "not_open": ["art-axi open {path}"],
    "not_found": ["check the path; `art-axi` lists the open images"],
    "conflict": ["art-axi save {path} --on-conflict merge", "art-axi save {path} --on-conflict overwrite"],
    "exists": ["add --overwrite, or choose another --out"],
    "unknown_key": ["art-axi profile {path} --all  (lists every [Group] Key)"],
    "unsupported": ["point ART_DIR (or --art-dir) at an ART build with spot sampling (art-cli -x)"],
    "timeout": ["retry with --timeout <seconds>"],
    "open_in_editor": ["close the image in ART's editor, then retry"],
    "metadata_unavailable": ["install exiftool, or put it beside ART-cli or on PATH"],
    "out_of_range": [],
}


TOOL_NAMES = {
    "open_image": "open",
    "reset_profile": "reset",
    "get_profile": "profile",
    "edit_profile": "edit",
    "describe_adjustments": "describe",
    "render_preview": "preview",
    "image_stats": "stats",
    "sample_spots": "sample",
    "save_sidecar": "save",
    "export_image": "export",
    "inspect_image": "inspect",
}
"""The MCP tool names the operations' messages use -> this CLI's commands."""

_TOOL_NAME = re.compile(r"\b(" + "|".join(TOOL_NAMES) + r")\b")


_TRUE_ARGUMENT = re.compile(r"\b([a-z_]+)=true\b")


def in_cli_terms(message: str) -> str:
    """An operation's message with the MCP tool and argument names it uses
    (``open_image``, ``overwrite=true``) as this CLI's (``art-axi open``,
    ``--overwrite``)."""
    message = _TOOL_NAME.sub(lambda m: f"`art-axi {TOOL_NAMES[m[1]]}`", message)
    return _TRUE_ARGUMENT.sub(lambda m: "--" + m[1].replace("_", "-"), message)


def failure_from(error: RenderError, path: str | None) -> Failure:
    hints = [h.format(path=path or "<path>") for h in ERROR_HELP.get(error.code, [])]
    return Failure(in_cli_terms(error.message), hints or None, error.code)


# -- flag parsing ----------------------------------------------------------------


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        usage = " ".join(self.format_usage().split()).removeprefix("usage: ")
        raise UsageError(message, [usage, f"art-axi {self.prog.split()[-1]} --help  (flags and examples)"])


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


@dataclass
class Command:
    name: str
    summary: str
    build: Callable[[Parser], None]
    run: Callable[[Context, argparse.Namespace], dict[str, Any]]
    examples: list[str]
    renamed: dict[str, str] = field(default_factory=dict)
    """Flags an agent may guess (the MCP tool's argument names) -> the hint."""

    def parser(self) -> Parser:
        epilog = "examples:\n" + "\n".join(f"  {e}" for e in self.examples)
        parser = Parser(
            prog=f"art-axi {self.name}",
            description=self.summary,
            epilog=epilog,
            allow_abbrev=False,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        self.build(parser)
        return parser

    def usage(self) -> str:
        """The one-line usage, without the leading ``usage:``."""
        return " ".join(self.parser().format_usage().split()).removeprefix("usage: ")

    def valid_flags(self) -> list[str]:
        flags = []
        for action in self.parser()._actions:
            flags.extend(s for s in action.option_strings if s.startswith("--") and s != "--help")
        return flags


# -- commands ----------------------------------------------------------------------


def run_home(ctx: Context) -> dict[str, Any]:
    open_images = ctx.store().all()
    out: dict[str, Any] = {
        "bin": home_relative(Path(sys.argv[0]).resolve()),
        "description": DESCRIPTION,
        "art_cli": art_cli_location(ctx.art_dir),
    }
    if open_images:
        out["images"] = rows(
            [{"path": shown(wp.image), "edits": edit_count(wp)} for wp in open_images], ["path", "edits"]
        )
        out["help"] = [
            "art-axi preview <path>  (renders a JPEG to look at)",
            "art-axi edit <path> --set Group/Key=value",
            "art-axi save <path>  (writes the sidecar)",
            "art-axi close <path>|--all",
        ]
    else:
        out["images"] = "0 open"
        out["help"] = ["art-axi open <path>...  (raw, jpeg or tiff)", "art-axi <command> --help"]
    return out


def build_open(p: Parser) -> None:
    p.add_argument("paths", nargs="+", metavar="PATH", help="images to open (up to 50)")
    p.add_argument("--profile", metavar="ARP", help="start from this .arp over ART's default instead of the sidecar")


def run_open(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import profile_ops

    session = ctx.session()
    if len(a.paths) == 1:
        opened = call(lambda: profile_ops.open_image(session, a.paths[0], a.profile), a.paths[0])
        path = shown(opened.path)
        image: dict[str, Any] = {"path": path, "from": opened.profile_from}
        if opened.metadata is not None:
            image.update(prune(opened.metadata))
        frame = frame_size(session, opened.path)
        if frame:
            image["frame"] = frame
        return {
            "image": image,
            "help": [
                f"art-axi preview {path}",
                f"art-axi stats {path}  (clipping)",
                f"art-axi edit {path} --set Group/Key=value",
            ],
        }
    batch = call(lambda: profile_ops.open_image(session, None, a.profile, a.paths, on_progress=progress("open")))
    items = [{"path": shown(i.path), "from": i.profile_from, "error": i.error} for i in batch.items]
    return {
        "opened": f"{len(items) - batch.failed} of {len(items)}",
        "images": rows(items, ["path", "from", "error"]),
        "help": [
            "art-axi preview <path>",
            "art-axi stats <path>...",
            "art-axi inspect <path>... --frame  (frame sizes: the pixels --spot and --mark use)",
        ],
    }


def frame_size(session: Any, path: str) -> str | None:
    """``"<w>x<h>"`` of the frame --spot and --mark address (measured with
    art-cli the first time, about a second), or None if that fails."""
    try:
        with session.image(path) as wp:
            frame = session.whole_frame(wp)
    except (RenderError, OSError):
        return None
    return f"{frame.w}x{frame.h}"


def build_close(p: Parser) -> None:
    p.add_argument("paths", nargs="*", metavar="PATH")
    p.add_argument("--all", action="store_true", help="close every open image")


def run_close(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    store = ctx.store()
    if a.all == bool(a.paths):
        raise UsageError("give image paths or --all", "art-axi close <path>... | art-axi close --all")
    targets = [wp.image for wp in store.all()] if a.all else [Path(p).resolve() for p in a.paths]
    if not targets:
        return {"closed": "0 (no images were open)"}
    items = []
    for image in targets:
        was_open = store.get(image) is not None
        store.discard(image)
        items.append({"path": shown(image), "state": "closed" if was_open else "not open (no-op)"})
    return {"closed": rows(items, ["path", "state"])}


def build_reset(p: Parser) -> None:
    p.add_argument("paths", nargs="+", metavar="PATH")
    p.add_argument("--to", required=True, choices=("sidecar", "default"), help="where to reload the profile from")


def run_reset(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import profile_ops

    session = ctx.session()
    store = ctx.store()
    before = {path: unsaved_values(store, path) for path in a.paths}

    def discarded(path: str) -> list[dict[str, Any]]:
        """The edits the reset dropped: their value and the one now loaded."""
        wp = store.get(Path(path).resolve())
        now = wp.changes.profile if wp else {}
        return [
            {"key": f"{group}/{key}", "edited": as_number(value), "now": as_number(now.get(group, {}).get(key))}
            for (group, key), value in before[path].items()
        ]

    if len(a.paths) == 1:
        path = a.paths[0]
        result = call(lambda: profile_ops.reset_profile(session, a.to, path), path)
        dropped = discarded(path)
        out: dict[str, Any] = {"reset": {"path": shown(path), "from": result.profile_from}}
        out["discarded"] = rows(dropped, ["key", "edited", "now"]) if dropped else "no unsaved edits"
        out["unsaved_edits"] = 0
        return out
    batch = call(lambda: profile_ops.reset_profile(session, a.to, None, a.paths, on_progress=progress("reset")))
    items = [
        {"path": shown(i.path), "from": i.profile_from,
         "discarded": None if i.error else " ".join(f"{d['key']}={d['edited']}" for d in discarded(i.path)) or "-",
         "error": i.error}
        for i in batch.items
    ]  # fmt: skip
    return {"reset": rows(items, ["path", "from", "discarded", "error"]), "failed": batch.failed}


def unsaved_values(store: DiskStore, path: str) -> dict[tuple[str, str], str | None]:
    """(group, key) -> current value of each value changed since the image
    was opened, reset or saved."""
    wp = store.get(Path(path).resolve())
    if wp is None:
        return {}
    profile = wp.changes.profile
    return {
        (group, key): profile.get(group, {}).get(key)
        for group, key, loaded in wp.changes.loaded_values()
        if profile.get(group, {}).get(key) != loaded
    }


def build_profile(p: Parser) -> None:
    p.add_argument("path", metavar="PATH")
    p.add_argument("--groups", type=names, metavar="G,G", help="only these [Group]s, e.g. Exposure,ToneCurve")
    p.add_argument(
        "--all", action="store_true",
        help="every value, not only those that differ from ART's default (about 15k tokens without --groups)",
    )  # fmt: skip


def run_profile(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import profile_ops

    session = ctx.session()
    view = call(lambda: profile_ops.get_profile(session, a.path, a.groups, changed_only=not a.all), a.path)
    with session.image(a.path) as wp:
        edits = edit_count(wp)
        stored = wp.changes.profile
    values, structured = profile_rows(prune(view.adjustments), view.raw, stored)
    out: dict[str, Any] = {"path": shown(a.path), "ppversion": view.ppversion, "unsaved_edits": edits}
    if not values and not structured:
        scope = f" in {','.join(a.groups)}" if a.groups else ""
        out["profile"] = f"no values{scope} differ from ART's default for this image"
        out["help"] = [
            f"art-axi profile {shown(a.path)} --all" + (f" --groups {','.join(a.groups)}" if a.groups else "")
        ]
    else:
        if values:
            out["values"] = rows(values, ["key", "stored", "name", "value"])
        if structured:
            out["structured"] = structured
    if view.warnings:
        out["warnings"] = view.warnings
    return out


def profile_rows(
    adjustments: dict[str, dict[str, Any]], raw: dict[str, dict[str, str]], stored: dict[str, dict[str, str]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A profile view as one table: per value its `Group/Key` and the stored
    value (what `edit --set` takes) and, for a curated tool's field, its name
    and typed value (what `edit --adjust` takes). Curated values that aren't
    one number or word (curves, regions) come back apart, as they are."""
    from art_mcp.schema import describe_adjustments

    tools = describe_adjustments().tools
    table: list[dict[str, Any]] = []
    structured: dict[str, Any] = {}
    for tool, fields in adjustments.items():
        for attr, value in fields.items():
            described = tools[tool].fields.get(attr) if tool in tools else None
            if described is None or not toon.is_primitive(value):
                structured.setdefault(tool, {})[attr] = value
                continue
            table.append(
                {
                    "key": f"{described.group}/{described.key}",
                    "stored": as_number(stored.get(described.group, {}).get(described.key)),
                    "name": f"{tool}.{attr}",
                    "value": value,
                }
            )
    for group, entries in raw.items():
        for key, value in entries.items():
            table.append({"key": f"{group}/{key}", "stored": as_number(value)})
    return table, structured


def changes_table(changes: dict[str, dict[str, str]], before: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """[Group] -> Key -> new value as rows `Group/Key, old, new`."""
    return [
        {"key": f"{group}/{key}", "old": as_number(before.get(group, {}).get(key)), "new": as_number(new)}
        for group, entries in changes.items()
        for key, new in entries.items()
    ]


def build_edit(p: Parser) -> None:
    p.add_argument("paths", nargs="+", metavar="PATH", help="images to change the same way (up to 50)")
    p.add_argument(
        "--set", dest="raw", action="append", type=raw_edit, default=[], metavar="GROUP/KEY=VALUE",
        help="set one stored [Group] Key (repeatable); the key must exist (art-axi profile <path> --all)",
    )  # fmt: skip
    p.add_argument(
        "--adjust", metavar="JSON",
        help='curated adjustments as a JSON object, e.g. \'{"exposure":{"compensation":0.5}}\' (art-axi describe)',
    )  # fmt: skip
    p.add_argument("--full", action="store_true", help="also print the groups touched (one image only)")


def run_edit(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import profile_ops
    from art_mcp.schema import RawEdit

    if not a.raw and a.adjust is None:
        raise UsageError("nothing to change: give --set and/or --adjust", "art-axi edit <path> --set Group/Key=value")
    adjustments = adjustments_arg(a.adjust)
    raw = [RawEdit(**r) for r in a.raw] or None
    session = ctx.session()
    if a.full and len(a.paths) > 1:
        raise UsageError("--full goes with one image", "art-axi edit <path> --full ...")
    # One image at a time, each all-or-nothing: an image that fails is its own
    # error and the others still change, and every result lists its keys.
    results: list[tuple[str, dict[str, Any] | None, str | None]] = []
    for path in a.paths:
        try:
            before = call(lambda path=path: profile_before(session, path), path)
            result = call(lambda path=path: profile_ops.edit_profile(session, path, adjustments, raw, a.full), path)
        except Failure as e:
            if len(a.paths) == 1:
                raise
            results.append((path, None, f"{e.code}: {e}"))
            continue
        out = prune(result)
        for name in ("changed", "implied"):
            if name in out:
                out[name] = rows(changes_table(out[name], before), ["key", "old", "new"])
        if not out.get("changed") and not out.get("implied") and not out.get("created"):
            out = {"edit": "no change (the values were already set)", **out}
        results.append((path, out, None))
    if len(a.paths) == 1:
        return results[0][1] or {}
    done = [out for _, out, _ in results if out is not None]
    failed = len(results) - len(done)
    if done and all(out == done[0] for out in done):
        # The same change to every image: said once.
        images = [{"path": shown(path), "error": error} for path, _, error in results]
        return {**done[0], "images": rows(images, ["path", "error"]), "failed": failed}
    items = [
        {"path": shown(path), **(out or {}), **({"error": error} if error else {})} for path, out, error in results
    ]
    return {"edited": items, "failed": failed}


def profile_before(session: Any, path: str) -> dict[str, dict[str, str]]:
    """A copy of the image's stored values, to show what an edit replaced."""
    with session.image(path) as wp:
        return {group: dict(entries) for group, entries in wp.changes.profile.items()}


def build_describe(p: Parser) -> None:
    p.add_argument("tool", nargs="?", metavar="TOOL", help="one adjustment's fields (default: list them all)")
    p.add_argument("--full", action="store_true", help="the tool's whole description, untruncated")


def run_describe(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.schema import describe_adjustments

    description = describe_adjustments()
    if a.tool is None:
        tools = [
            {"name": name, "group": t.group, "fields": " ".join(t.fields)} for name, t in description.tools.items()
        ]
        return {
            "schema_ppversion": description.schema_ppversion,
            "tools": rows(tools, ["name", "group", "fields"]),
            "help": ["art-axi describe <tool>  (its fields, ranges and keys)", "art-axi edit <path> --adjust '<json>'"],
        }
    tool = description.tools.get(a.tool)
    if tool is None:
        raise Failure(f"no adjustment {a.tool!r}", f"valid: {', '.join(description.tools)}", "unknown_tool")
    fields = []
    for name, f in tool.fields.items():
        fields.append(
            {
                "name": name,
                "key": f"{f.group}/{f.key}",
                "type": f.type if not f.enum else "|".join(f.enum),
                "min": f.minimum,
                "max": f.maximum,
                "unit": f.unit,
                "art_default": f.default if toon.is_primitive(f.default) else json.dumps(f.default),
            }
        )
    out: dict[str, Any] = {
        "tool": a.tool,
        "group": tool.group,
        "description": truncated(tool.description, a.full),
        "fields": rows(fields, ["name", "key", "type", "min", "max", "unit", "art_default"]),
        "note": "art_default is ART's built-in value; an image starts from its processing profile, which can "
        "differ (art-axi profile <path> --all shows it)",
    }
    if len(tool.description) > TRUNCATE and not a.full:
        out["help"] = [f"art-axi describe {a.tool} --full"]
    return out


def build_preview(p: Parser) -> None:
    from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE

    p.add_argument("paths", nargs="+", metavar="PATH", help="images to render (up to 16)")
    p.add_argument(
        "--size", type=int, default=PREVIEW_SIZE, help=f"long edge in px, 1..{MAX_PREVIEW_SIZE} (default %(default)s)"
    )
    p.add_argument(
        "--region", type=comma_floats(4, "--region"), metavar="X,Y,W,H", help="image fractions, rendered 1:1"
    )
    p.add_argument("--out", metavar="JPG", help="write the JPEG here (one image); default: the state folder")
    p.add_argument("--overwrite", action="store_true", help="replace an existing --out file")
    p.add_argument(
        "--mark", dest="marks", action="append", type=mark, default=[], metavar="X,Y[,SIZE[,LABEL]]",
        help="draw a box at a frame pixel (repeatable, up to 64; one image)",
    )  # fmt: skip
    p.add_argument("--zoom", action="store_true", help="one enlarged tile per --mark instead of the whole image")
    p.add_argument("--stage", default="display", choices=("display", "converted"), help="default %(default)s")


def run_preview(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.marks import Mark
    from art_mcp.render import preview_ops
    from art_mcp.render.preview_ops import Region

    region = Region(**dict(zip("xywh", a.region, strict=True))) if a.region else None
    marks = [Mark(**m) for m in a.marks] or None
    session = ctx.session()
    if len(a.paths) == 1:
        path = a.paths[0]
        result = call(
            lambda: preview_ops.render_preview(
                session, path, a.size, region, a.out, a.overwrite, marks, a.stage, a.zoom
            ),
            path,
        )
        file = result.path if a.out else named_after(result.path, path)
        out: dict[str, Any] = {
            "preview": prune(
                {"file": shown(file), "width": result.width, "height": result.height, "shown": result.shown}
            )
        }
        if result.tiles:
            out["tiles"] = rows(
                [{"label": t.label, **{f"window_{k}": v for k, v in t.window.items()}} for t in result.tiles],
                ["label", "window_x", "window_y", "window_w", "window_h"],
            )
        if result.warnings:
            out["warnings"] = result.warnings
        out["help"] = ["open the JPEG file to look at it", "frame_x = shown.x + px * shown.w / width (y alike)"]
        return out
    if a.stage != "display" or a.zoom:
        raise UsageError("--stage and --zoom go with one image", "art-axi preview <path> --stage converted")
    call(lambda: preview_ops.check_preview_call(None, a.paths, a.out, a.overwrite, marks))
    batch = call(lambda: preview_ops.render_previews(session, a.paths, a.size, region, on_progress=progress("preview")))
    items = [
        {"path": shown(i.path), "file": shown(named_after(i.preview_path, i.path)), "error": i.error}
        for i in batch.items
    ]
    return {
        "previews": rows(items, ["path", "file", "error"]),
        "failed": batch.failed,
        "help": ["open each JPEG file to look at it"],
    }


def named_after(file: str | None, image: str) -> str | None:
    """A preview in the state folder renamed ``<image name>-<random>.jpg``, so
    which image it shows can be read from its name."""
    if file is None:
        return None
    rendered = Path(file)
    target = rendered.with_name(f"{Path(image).name}-{rendered.name.rsplit('-', 1)[-1]}")
    try:
        os.replace(rendered, target)
    except OSError:
        return file
    return str(target)


def build_stats(p: Parser) -> None:
    from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE

    p.add_argument("paths", nargs="+", metavar="PATH", help="images to measure (up to 50)")
    p.add_argument("--detail", choices=("compact", "standard", "full"), help="default standard (compact for several)")
    p.add_argument("--region", type=comma_floats(4, "--region"), metavar="X,Y,W,H", help="image fractions")
    p.add_argument("--bins", type=int, choices=(8, 16, 32, 64), help="fractions of pixels in equal groups of values")
    p.add_argument("--histogram", action="store_true", help="256 counts per channel")
    p.add_argument("--lum-min", type=int, metavar="0..255", help="measure only pixels at least this bright")
    p.add_argument("--lum-max", type=int, metavar="0..255", help="measure only pixels at most this bright")
    p.add_argument(
        "--size",
        type=int,
        default=PREVIEW_SIZE,
        help=f"long edge of the render measured, 1..{MAX_PREVIEW_SIZE} (default %(default)s)",
    )
    p.add_argument("--stage", default="display", choices=("display", "converted"), help="default %(default)s")
    p.add_argument(
        "--set", dest="raw", action="append", type=raw_edit, default=[], metavar="GROUP/KEY=VALUE",
        help="measure with this value instead of the stored one, without storing it (repeatable)",
    )  # fmt: skip
    p.add_argument("--adjust", metavar="JSON", help="the same with curated adjustments, as `edit --adjust`")
    p.add_argument(
        "--sweep", type=sweep, metavar="GROUP/KEY=V1,V2,...",
        help="measure each value of one key (one image, up to 50 values, nothing stored), one row per value: "
        "Exposure/Compensation=0.4,0.5 or =0:2:0.1; --detail adds the percentiles",
    )  # fmt: skip


MAX_SWEEP = 50
"""Values one --sweep measures at most (about a second each)."""


def sweep(text: str) -> tuple[str, str, list[str]]:
    """``Group/Key=v1,v2,...`` or ``Group/Key=start:stop:step`` (both ends
    included)."""
    edit = raw_edit(text)
    spec = edit["value"]
    usage = f"--sweep takes Group/Key=v1,v2,... or Group/Key=start:stop:step, not {text!r}"
    if ":" in spec:
        try:
            start, stop, step = (Decimal(v) for v in spec.split(":"))
        except (ValueError, ArithmeticError):
            raise argparse.ArgumentTypeError(usage) from None
        if step <= 0 or stop < start:
            raise argparse.ArgumentTypeError(f"{usage} (step above 0, stop not below start)")
        count = int((stop - start) / step) + 1
        if count > MAX_SWEEP:
            raise argparse.ArgumentTypeError(f"--sweep {spec} is {count} values; at most {MAX_SWEEP}")
        values = [str((start + i * step).normalize()) for i in range(count)]
    else:
        values = [v for v in spec.split(",") if v]
    if not values or len(values) > MAX_SWEEP:
        raise argparse.ArgumentTypeError(f"{usage} (1 to {MAX_SWEEP} values)")
    return edit["group"], edit["key"], values


def adjustments_arg(text: str | None) -> dict[str, Any] | None:
    """``--adjust``'s JSON object (None without one)."""
    if text is None:
        return None
    try:
        adjustments = json.loads(text)
    except json.JSONDecodeError as e:
        raise UsageError(f"--adjust is not JSON: {e}", "art-axi describe  (the adjustments and their fields)") from e
    if not isinstance(adjustments, dict):
        raise UsageError("--adjust takes a JSON object", "art-axi describe")
    return adjustments


def scratch_session(session: Any, paths: list[str]) -> Any:
    """A session over copies of ``paths``' working profiles held in memory:
    edits to it render like the real ones and are never stored."""
    import copy

    from art_mcp.render.session import RenderSession
    from art_mcp.render.store import MemoryStore

    store = MemoryStore()
    for path in paths:
        with session.image(path) as wp:
            store.put(copy.deepcopy(wp))
    return RenderSession(
        session.cli, session.config_dir, session.previews, session.exiftool, session.inline_previews, store=store
    )


def channel_table(stats: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Per-channel statistics as one table (percentiles as `p<rank>` columns),
    and the per-channel lists (`bins`, `histogram`) apart."""
    table, lists = [], {}
    for ch in ("r", "g", "b", "lum"):
        values = stats.get(ch)
        if not isinstance(values, dict):
            continue
        row: dict[str, Any] = {"ch": ch}
        for key, value in values.items():
            if key == "percentiles":
                row.update({f"p{rank}": v for rank, v in value.items()})
            elif isinstance(value, list):
                lists.setdefault(key, {})[ch] = value
            else:
                row[key] = value
        table.append(row)
    rest = {k: v for k, v in stats.items() if k not in ("r", "g", "b", "lum")}
    if table:
        columns = list(dict.fromkeys(k for row in table for k in row))
        rest["channels"] = rows(table, columns)
    return rest, lists


def sweep_row(stats: dict[str, Any], full: bool) -> dict[str, Any]:
    """One swept value's statistics as one row: the clipped fractions per
    channel and, with ``full``, every other statistic as `<name>_<channel>`."""
    row: dict[str, Any] = {}
    for name in ("clipped_high", "clipped_low"):
        for ch in ("r", "g", "b", "lum"):
            row[f"{name}_{ch}"] = stats.get(ch, {}).get(name)
    if full:
        for ch in ("r", "g", "b", "lum"):
            for name, value in stats.get(ch, {}).items():
                if name == "percentiles":
                    row.update({f"p{rank}_{ch}": v for rank, v in value.items()})
                elif toon.is_primitive(value) and not name.startswith("clipped_"):
                    row[f"{name}_{ch}"] = value
    return row


def run_stats(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import profile_ops, sampling_ops
    from art_mcp.render.preview_ops import Region
    from art_mcp.schema import RawEdit

    region = Region(**dict(zip("xywh", a.region, strict=True))) if a.region else None
    adjustments = adjustments_arg(a.adjust)
    if a.sweep and len(a.paths) > 1:
        raise UsageError("--sweep goes with one image", "art-axi stats <path> --sweep Group/Key=v1,v2,...")
    session = ctx.session()
    if a.raw or adjustments is not None or a.sweep:
        session = call(lambda: scratch_session(ctx.session(), a.paths), a.paths[0])

    def override(path: str, raw: list[dict[str, str]]) -> None:
        edits = [RawEdit(**r) for r in raw] or None
        if edits or adjustments is not None:
            call(lambda: profile_ops.edit_profile(session, path, adjustments, edits), path)

    def measure(path: str | None, paths: list[str] | None, detail: str | None = a.detail) -> Any:
        return sampling_ops.image_stats(
            session, path, paths, a.size, a.histogram, region, a.bins, detail, a.lum_min, a.lum_max,
            on_progress=progress("stats") if paths else None, stage=a.stage,
        )  # fmt: skip

    for path in a.paths:
        override(path, a.raw)
    if a.sweep:
        path = a.paths[0]
        group, key, values = a.sweep
        table: list[dict[str, Any]] = []
        render = None
        for value in values:
            override(path, [{"group": group, "key": key, "value": value}])
            stats = prune(call(lambda: measure(path, None, a.detail or "compact"), path))
            render = f"{stats.get('width')}x{stats.get('height')}"
            table.append({"value": as_number(value), **sweep_row(stats, full=a.detail is not None)})
        columns = list(dict.fromkeys(k for row in table for k in row))
        return {
            "path": shown(path),
            "sweep": f"{group}/{key} (nothing stored)",
            "render": f"{render} (--size {a.size}; raise it to confirm small clipped areas)",
            "results": rows(table, columns),
            "help": [f"art-axi edit {shown(path)} --set {group}/{key}=<chosen value>"],
        }
    if len(a.paths) == 1:
        stats = prune(call(lambda: measure(a.paths[0], None), a.paths[0]))
        rest, lists = channel_table(stats)
        return {"path": shown(a.paths[0]), **rest, **lists}
    batch = call(lambda: measure(None, a.paths))
    items = []
    for item in batch.items:
        if item.error:
            items.append({"path": shown(item.path), "error": item.error})
            continue
        rest, lists = channel_table(prune(item.stats))
        items.append({"path": shown(item.path), **rest, **lists})
    return {"items": items, "failed": batch.failed}


def build_sample(p: Parser) -> None:
    p.add_argument("path", metavar="PATH")
    p.add_argument(
        "--spot", dest="spots", action="append", type=spot, required=True, metavar="X,Y[,SIZE]",
        help="centre of a square to sample, in frame pixels (repeatable, up to 64); "
        "the frame size is `art-axi inspect <path>`'s frame_width x frame_height",
    )  # fmt: skip
    p.add_argument("--size", type=int, default=32, help="square side in px, 2..256 (default %(default)s)")
    p.add_argument("--space", default="working", choices=("working", "input"), help="default %(default)s")
    p.add_argument("--stage", default="source", choices=("source", "converted"), help="default %(default)s")


def run_sample(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import sampling_ops
    from art_mcp.sampling import Spot

    session = ctx.session()
    spots = [Spot(**s) for s in a.spots]
    result = call(lambda: sampling_ops.sample_spots(session, a.path, spots, a.size, a.space, a.stage), a.path)
    data = prune(result)
    data.pop("size", None)  # each spot's row has the size it was sampled at
    spot_rows = []
    for s in data.pop("spots"):
        row = {"x": s["x"], "y": s["y"], "size": s["size"]}
        for name in ("avg", "max", "sd"):
            if name in s:
                row.update({f"{name}_{c}": round(v, 1) for c, v in zip("rgb", s[name], strict=True)})
        spot_rows.append(row)
    columns = list(dict.fromkeys(k for row in spot_rows for k in row))
    return {"path": shown(a.path), **data, "spots": rows(spot_rows, columns)}


def build_save(p: Parser) -> None:
    p.add_argument("paths", nargs="+", metavar="PATH", help="open images whose sidecars to write")
    p.add_argument(
        "--on-conflict", choices=("merge", "overwrite"),
        help="when the sidecar changed on disk since it was loaded (default: fail with `conflict`)",
    )  # fmt: skip


def run_save(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import save_ops

    session = ctx.session()
    if len(a.paths) == 1:
        result = call(lambda: save_ops.save_sidecar(session, a.paths[0], a.on_conflict), a.paths[0])
        return {"saved": {"sidecar": shown(result.path), "how": result.how}}
    # One after the other: a failure (a conflict) is that image's error and the
    # others are still saved.
    items = []
    for path in a.paths:
        try:
            result = call(lambda path=path: save_ops.save_sidecar(session, path, a.on_conflict), path)
            items.append({"path": shown(path), "sidecar": shown(result.path), "how": result.how})
        except Failure as e:
            items.append({"path": shown(path), "error": f"{e.code}: {e}"})
    failed = sum(1 for i in items if "error" in i)
    out: dict[str, Any] = {"saved": rows(items, ["path", "sidecar", "how", "error"]), "failed": failed}
    if failed:
        out["help"] = ["art-axi save <path> --on-conflict merge|overwrite  (for a conflict)"]
    return out


FORMATS = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".tif": "tiff", ".tiff": "tiff"}


def build_export(p: Parser) -> None:
    p.add_argument("path", metavar="PATH")
    p.add_argument("--out", required=True, metavar="FILE", help="the image to write (its folder is created)")
    p.add_argument("--format", choices=("jpeg", "png", "tiff"), help="default: from --out's extension")
    p.add_argument("--quality", type=int, metavar="1..100", help="jpeg only")
    p.add_argument("--bit-depth", choices=("8", "16", "16f", "32"), help="png 8|16, tiff 8|16|16f|32")
    p.add_argument("--write-profile", action="store_true", help="also write the .arp beside it")
    p.add_argument("--profile-name", choices=("output", "source"), default="output", help="name of that .arp")
    p.add_argument("--overwrite", action="store_true", help="replace an existing --out file")


def run_export(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import export_ops

    format = a.format or FORMATS.get(Path(a.out).suffix.lower())
    if format is None:
        raise UsageError(f"can't tell the format from {a.out!r}", "add --format jpeg|png|tiff")
    session = ctx.session()
    try:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise Failure(f"can't create the folder for --out: {e}", code="not_found") from e
    result = call(
        lambda: export_ops.export_image(
            session, a.path, a.out, format, a.quality, a.bit_depth, a.write_profile, a.profile_name, a.overwrite
        ),
        a.path,
    )
    return {"exported": prune({"file": shown(result.path), "profile": shown(result.profile_path)})}


def build_inspect(p: Parser) -> None:
    p.add_argument("paths", nargs="+", metavar="PATH", help="open images (up to 100)")
    p.add_argument("--tags", type=names, metavar="TAG,TAG", help="extra exiftool tags, e.g. Software")
    p.add_argument("--frame", action="store_true", help="measure the frame size for several images (~1 s each)")


def run_inspect(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import metadata_ops

    session = ctx.session()
    if len(a.paths) == 1:
        return {"metadata": prune(call(lambda: metadata_ops.inspect_image(session, a.paths[0], a.tags), a.paths[0]))}
    batch = call(
        lambda: metadata_ops.inspect_images(session, a.paths, a.tags, a.frame, on_progress=progress("inspect"))
    )
    items = [
        {"path": shown(i.path), **(prune(i.metadata) if i.metadata else {}), "error": i.error} for i in batch.items
    ]
    columns = list(dict.fromkeys(k for item in items for k in item if not isinstance(item[k], dict)))
    return {"images": rows(items, columns), "failed": batch.failed}


COMMANDS = {
    c.name: c
    for c in (
        Command(
            "open",
            "Open images: load each one's sidecar (else ART's default) as its working profile.",
            build_open,
            run_open,
            ["art-axi open ~/raw/IMG_1.ARW", "art-axi open ~/raw/*.ARW --profile look.arp"],
            {"--path": "give paths as arguments: art-axi open <path>..."},
        ),
        Command(
            "close",
            "Forget images' working profiles (unsaved edits are dropped).",
            build_close,
            run_close,
            ["art-axi close ~/raw/IMG_1.ARW", "art-axi close --all"],
        ),
        Command(
            "reset",
            "Reload working profiles from the sidecar or ART's default.",
            build_reset,
            run_reset,
            ["art-axi reset IMG_1.ARW --to sidecar"],
        ),
        Command(
            "profile",
            "Read an open image's working profile (default: values that differ from ART's default). Each value "
            "has its Group/Key and stored value (what edit --set takes) and, for a curated tool, its name and value "
            "(what edit --adjust takes). unsaved_edits: values changed since the image was opened, reset or saved.",
            build_profile,
            run_profile,
            ["art-axi profile IMG_1.ARW", "art-axi profile IMG_1.ARW --all --groups Exposure,ToneCurve"],
            {
                "--changed-only": "that is the default; --all reads every value",
                "--changed": "that is the default; --all reads every value",
            },
        ),
        Command(
            "edit",
            "Change working-profile values; prints only what changed.",
            build_edit,
            run_edit,
            [
                "art-axi edit IMG_1.ARW --set Exposure/Compensation=0.5",
                'art-axi edit a.ARW b.ARW --adjust \'{"exposure":{"compensation":0.5}}\'',
            ],
            {"--raw-edits": "use --set Group/Key=value (repeatable)", "--adjustments": "use --adjust '<json>'"},
        ),
        Command(
            "describe",
            "The curated adjustments `edit --adjust` takes.",
            build_describe,
            run_describe,
            ["art-axi describe", "art-axi describe exposure"],
        ),
        Command(
            "preview",
            "Render the working profile as a JPEG and print its path.",
            build_preview,
            run_preview,
            [
                "art-axi preview IMG_1.ARW",
                "art-axi preview IMG_1.ARW --region 0.4,0.4,0.2,0.2",
                "art-axi preview IMG_1.ARW --mark 3000,2000 --mark 1200,800,64,A --zoom",
            ],
            {"--max-size": "use --size", "--output": "use --out", "--marks": "use --mark (repeatable)"},
        ),
        Command(
            "stats",
            "Clipping and percentiles of a rendered image, per channel. clipped_high/clipped_low are fractions "
            "(0..1) of the pixels at 255 / 0 of a render whose long edge is --size (raise it to catch small clipped "
            "areas); percentiles are 8-bit values. --set measures values without storing them; --sweep measures "
            "several values of one key in one call.",
            build_stats,
            run_stats,
            [
                "art-axi stats IMG_1.ARW",
                "art-axi stats *.ARW --detail compact --lum-max 250",
                "art-axi stats IMG_1.ARW --sweep Exposure/Compensation=0.4,0.5,0.6,0.7",
            ],
            {"--max-size": "use --size"},
        ),
        Command(
            "sample",
            "Linear RGB averages of squares of frame pixels, as ART's spot pickers read.",
            build_sample,
            run_sample,
            ["art-axi sample IMG_1.ARW --spot 3000,2000 --spot 1200,800,64"],
            {"--spots": "use --spot x,y[,size] (repeatable)"},
        ),
        Command(
            "save",
            "Write the working profile to the image's sidecar (the old one kept as .bak).",
            build_save,
            run_save,
            ["art-axi save IMG_1.ARW", "art-axi save IMG_1.ARW --on-conflict merge"],
        ),
        Command(
            "export",
            "Render the working profile at full size to a file.",
            build_export,
            run_export,
            [
                "art-axi export IMG_1.ARW --out ~/out/IMG_1.jpg --quality 92",
                "art-axi export IMG_1.ARW --out ~/out/IMG_1.tif --bit-depth 16",
            ],
            {"--output": "use --out"},
        ),
        Command(
            "inspect",
            "Camera metadata and frame size of open images.",
            build_inspect,
            run_inspect,
            ["art-axi inspect IMG_1.ARW", "art-axi inspect *.ARW --tags Software"],
        ),
    )  # fmt: skip
}


# -- dispatch ------------------------------------------------------------------------


def call(operation: Callable[[], Any], path: str | None = None) -> Any:
    """Run an operation, turning its errors into a ``Failure``."""
    try:
        return operation()
    except RenderError as e:
        raise failure_from(e, path) from e
    except OSError as e:
        raise Failure(str(e), code="render_failed") from e


def split_globals(argv: list[str]) -> tuple[list[str], dict[str, str]]:
    rest, found = [], {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        name, eq, value = arg.partition("=")
        if name in GLOBAL_FLAGS:
            if not eq:
                if i + 1 >= len(argv):
                    raise UsageError(f"{name} needs a value", f"art-axi {name} <value> ...")
                value = argv[i + 1]
                i += 1
            found[name] = value
        else:
            rest.append(arg)
        i += 1
    return rest, found


def unknown_flag_check(command: Command, argv: list[str]) -> None:
    """Reject flags the command doesn't take by name, with the valid ones, before
    argparse's own message."""
    valid = command.valid_flags()
    for arg in argv:
        if arg == "--":
            return
        if not arg.startswith("--") or arg == "--help":
            continue
        name = arg.split("=", 1)[0]
        if name in valid:
            continue
        if name in command.renamed:
            raise UsageError(f"unknown flag {name} for `{command.name}`: {command.renamed[name]}")
        raise UsageError(
            f"unknown flag {name} for `{command.name}`",
            f"valid flags for `{command.name}`: {', '.join(valid)} (--help always allowed)",
        )


def top_help() -> dict[str, Any]:
    return {
        "usage": "art-axi [<command>] [flags]   (no command: the open images)",
        "workflow": "open -> stats/preview -> edit -> preview -> save -> export -> close",
        "commands": rows(
            [{"name": c.name, "summary": c.summary, "usage": c.usage()} for c in COMMANDS.values()],
            ["name", "summary", "usage"],
        ),
        "globals": "--art-dir <folder> (ART-cli's folder; default ART_DIR, PATH, newest install), --timeout <s>",
        "state": "working profiles persist between runs in ART_AXI_HOME (default: per-user state folder)",
        "help": ["art-axi <command> --help"],
    }


def run(argv: list[str], session_factory: Callable[[Context], Any] | None = None) -> int:
    try:
        argv, globals_ = split_globals(argv)
        timeout = None
        if "--timeout" in globals_:
            try:
                timeout = float(globals_["--timeout"])
            except ValueError:
                raise UsageError(f"--timeout takes seconds, not {globals_['--timeout']!r}") from None
        ctx = Context(default_home(), globals_.get("--art-dir"), timeout, session_factory)
        if not argv:
            emit(run_home(ctx))
            return EXIT_OK
        if argv[0] in ("--help", "-h", "help"):
            emit(top_help())
            return EXIT_OK
        command = COMMANDS.get(argv[0])
        if command is None:
            kind = "flag" if argv[0].startswith("-") else "command"
            raise UsageError(f"unknown {kind} {argv[0]}", f"commands: {', '.join(COMMANDS)}; art-axi --help")
        args = argv[1:]
        if "--help" in args or "-h" in args:
            print(command.parser().format_help().rstrip())
            return EXIT_OK
        unknown_flag_check(command, args)
        emit(command.run(ctx, command.parser().parse_args(args)))
        return EXIT_OK
    except Failure as e:
        emit(error_output(e))
        return e.exit_code


def error_output(e: Failure) -> dict[str, Any]:
    out: dict[str, Any] = {"error": str(e)}
    if e.code:
        out["code"] = e.code
    if e.help:
        out["help"] = e.help
    return out
