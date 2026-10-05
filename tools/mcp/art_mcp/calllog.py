"""An opt-in record of every tool call a server handles, whatever client drives it.

Set ``ART_MCP_CALL_LOG`` to a file and both servers append one JSON line per
tool call to it (JSON Lines, UTF-8)::

    {"t": "2026-10-05T10:00:02.500Z", "server": "art-render", "tool": "edit_profile", "ms": 31.4,
     "ok": false, "error": "out_of_range", "args": {"path": "C:\\raws\\a.ARW", "raw_edits": [[...], ...]},
     "result_chars": 212, "images": 0, "in_flight": 2}

``t`` is when the call arrived (UTC); ``ms`` how long it took to complete;
``error`` the leading ``code:`` of a tool error (``exception`` for a crash,
``invalid_arguments`` for arguments the schema refused, ``unknown_tool``,
``cancelled``), null when ``ok``; ``args`` the arguments cut down (see
``shrink_args``); ``result_chars`` the length of the result's text (the compact
JSON of its structured form, else its text content; images not counted);
``images`` the image contents; ``in_flight`` how many tool calls were being
handled when this one started, itself included. A line is written when the call
ends, so the file is in order of completion; ``summarise`` sorts by arrival.

One middleware does it for every tool (``install``, called by each server's
``build_server``): nothing is added without the variable. The log never breaks
a call: a failure to write warns once on stderr and the calls carry on.

``python -m art_mcp.calllog summarise <file>`` reports on a log.
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

ENV_VAR = "ART_MCP_CALL_LOG"

STRING_LIMIT = 120
"""Characters of a string argument that are logged."""
LIST_ITEMS = 2
"""Items of a list argument that are logged."""
KEY_LIMIT = 50
"""Key names of a dict argument that are logged."""


def shrink(value: Any) -> Any:
    """``value`` cut down to a few lines of log: a long string to
    ``STRING_LIMIT`` characters (the last three being ``...``), a list to its
    first ``LIST_ITEMS`` items (each shrunk) and ``"...+<more>"``, a dict to
    its key names (``KEY_LIMIT`` at most, then ``"...+<more>"``), anything
    else as it is."""
    if isinstance(value, str):
        return value if len(value) <= STRING_LIMIT else value[: STRING_LIMIT - 3] + "..."
    if isinstance(value, Mapping):
        keys = [str(k) for k in value]
        return keys if len(keys) <= KEY_LIMIT else [*keys[:KEY_LIMIT], f"...+{len(keys) - KEY_LIMIT}"]
    if isinstance(value, list | tuple):
        shown = [shrink(v) for v in value[:LIST_ITEMS]]
        return shown if len(value) <= LIST_ITEMS else [*shown, f"...+{len(value) - LIST_ITEMS}"]
    return value


def shrink_args(arguments: Any) -> dict[str, Any]:
    """The arguments of a call by name, each ``shrink``-ed."""
    if not isinstance(arguments, Mapping):
        return {}
    return {str(name): shrink(value) for name, value in arguments.items()}


_TOOL_PREFIX = re.compile(r"Error executing tool [\w.-]+")
_VALIDATION = re.compile(r"\d+ validation errors? for ")
_CODE = re.compile(r"([a-z][a-z0-9_]*):")


def error_code(text: str) -> str:
    """The code of a tool error from its message: the leading ``code:`` (after
    the SDK's ``Error executing tool <name>: ``, if it is there)."""
    if text.startswith("Unknown tool"):
        return "unknown_tool"
    wrapped = _TOOL_PREFIX.match(text)
    if wrapped:
        text = text[wrapped.end() :]
        if not text.startswith(": "):
            return "exception"  # the SDK keeps a crash's own text to itself
        text = text[2:]
    if _VALIDATION.match(text):
        return "invalid_arguments"
    code = _CODE.match(text)
    return code.group(1) if code else "error"


def stamp(when: datetime) -> str:
    """ISO 8601 UTC with milliseconds (truncated), ``2026-10-05T10:00:02.500Z``."""
    when = when.astimezone(UTC)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def append(path: Path, data: bytes) -> None:
    """Add ``data`` to the end of the file at ``path`` (made if need be) in one
    write that other processes appending the same way cannot overwrite or
    split. Python's own append mode is not enough on Windows: the C runtime
    seeks to the end and then writes, so two writers can pick the same spot.
    There the file is opened for appending only, which NTFS serves atomically."""
    if sys.platform == "win32":
        append_windows(path, data)
        return
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
    try:
        os.write(fd, data)  # a regular file takes it whole
    finally:
        os.close(fd)


def append_windows(path: Path, data: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]  # fmt: skip
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]  # fmt: skip
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    file_append_data, share_all, open_always, normal = 0x4, 0x7, 4, 0x80
    handle = kernel32.CreateFileW(str(path), file_append_data, share_all, None, open_always, normal, None)
    if handle == ctypes.c_void_p(-1).value:  # INVALID_HANDLE_VALUE
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        written = wintypes.DWORD()
        if not kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if written.value != len(data):
            raise OSError(f"wrote {written.value} of {len(data)} bytes")
    finally:
        kernel32.CloseHandle(handle)


class Outcome:
    """What a tool result comes to in the log."""

    def __init__(self, result: Any) -> None:
        """``result`` is the tool result as the middleware sees it (the dict
        sent to the client, or its model); None counts as an empty result."""
        data = result.model_dump(mode="json", by_alias=True) if hasattr(result, "model_dump") else result
        data = data if isinstance(data, Mapping) else {}
        content = data.get("content")
        blocks = [b for b in content if isinstance(b, Mapping)] if isinstance(content, list) else []
        texts = [b["text"] for b in blocks if b.get("type") == "text" and isinstance(b.get("text"), str)]
        structured = data.get("structuredContent")
        self.is_error: bool = data.get("isError") is True
        self.text: str = texts[0] if texts else ""
        self.chars: int = len(compact(structured)) if structured is not None else sum(len(t) for t in texts)
        self.images: int = sum(1 for b in blocks if b.get("type") == "image")


class CallLog:
    """Server middleware (``async (ctx, call_next)``) that appends a line per
    ``tools/call`` to ``path``. ``server`` is the name the lines carry."""

    def __init__(self, path: str | os.PathLike[str], server: str) -> None:
        self.path = Path(path)
        self.server = server
        self._counting = threading.Lock()
        self._writing = threading.Lock()
        self._in_flight = 0
        self._warned = False

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        arrived = datetime.now(UTC)
        began = time.perf_counter()
        with self._counting:
            self._in_flight += 1
            in_flight = self._in_flight
        outcome = Outcome(None)
        raised: str | None = None
        try:
            result = await call_next(ctx)
            outcome = self._safely(Outcome, result) or outcome
            return result
        except Exception:
            raised = "exception"
            raise
        except BaseException:
            raised = "cancelled"
            raise
        finally:
            with self._counting:
                self._in_flight -= 1
            ms = (time.perf_counter() - began) * 1000
            self._safely(self._record, ctx, arrived, ms, in_flight, outcome, raised)

    def _safely(self, fn: Any, *args: Any) -> Any:
        """``fn(*args)``, or None (with the one warning) if it fails: nothing
        about the log may break a tool call."""
        try:
            return fn(*args)
        except Exception as e:
            self._warn(e)
            return None

    def _record(
        self, ctx: Any, arrived: datetime, ms: float, in_flight: int, outcome: Outcome, raised: str | None
    ) -> None:
        params = ctx.params if isinstance(ctx.params, Mapping) else {}
        self.write({
            "t": stamp(arrived),
            "server": self.server,
            "tool": str(params.get("name", "")),
            "ms": round(ms, 1),
            "ok": raised is None and not outcome.is_error,
            "error": raised or (error_code(outcome.text) if outcome.is_error else None),
            "args": shrink_args(params.get("arguments")),
            "result_chars": outcome.chars,
            "images": outcome.images,
            "in_flight": in_flight,
        })  # fmt: skip

    def write(self, record: Mapping[str, Any]) -> None:
        """Append ``record`` as one line, in one write (``append``), so servers
        and threads sharing the file don't mix their lines. The folder of the
        file is made if it is missing."""
        line = (compact(record) + "\n").encode("utf-8")
        try:
            with self._writing:
                try:
                    append(self.path, line)
                except FileNotFoundError:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    append(self.path, line)
        except OSError as e:
            self._warn(e)

    def _warn(self, error: Exception) -> None:
        if not self._warned:
            self._warned = True
            print(f"art-mcp: cannot write the call log {self.path} ({ENV_VAR}): {error}", file=sys.stderr)


def install(server: "MCPServer", environ: Mapping[str, str] | None = None) -> None:
    """Log ``server``'s tool calls to the file ``ART_MCP_CALL_LOG`` names; does
    nothing when it is unset or empty."""
    path = (os.environ if environ is None else environ).get(ENV_VAR)
    if path:
        server.middleware.insert(0, CallLog(path, server.name))


# --- the summary ---------------------------------------------------------------------------------

LARGEST = 5
"""Results listed as the largest."""
FIRST_ERRORS = 5
"""Errors listed."""


def read_calls(path: str | os.PathLike[str]) -> tuple[list[dict[str, Any]], int]:
    """The call records in the file, each with its parsed ``arrived`` time, in
    order of arrival, and the number of lines that were not records."""
    records: list[dict[str, Any]] = []
    skipped = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for text in f:
            if not text.strip():
                continue
            try:
                record = json.loads(text)
                record["arrived"] = datetime.fromisoformat(record["t"])
                if not isinstance(record["tool"], str):
                    raise TypeError("tool")
            except (ValueError, TypeError, KeyError):
                skipped += 1
                continue
            records.append(record)
    records.sort(key=lambda r: r["arrived"])  # stable: the file's order within a millisecond
    return records, skipped


def summarise(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Totals, per-tool figures, largest results, first errors and the
    collapsed sequence of the calls in the log at ``path``."""
    calls, skipped = read_calls(path)
    first = calls[0]["arrived"] if calls else None
    ended = [r["arrived"] + timedelta(milliseconds=r.get("ms") or 0) for r in calls]
    last = max(ended) if calls else None

    per_tool: dict[str, dict[str, Any]] = {}
    for r in calls:
        t = per_tool.setdefault(r["tool"], {"tool": r["tool"], "calls": 0, "errors": 0, "result_chars": 0, "ms": 0})
        t["calls"] += 1
        t["errors"] += 0 if r.get("ok", True) else 1
        t["result_chars"] += r.get("result_chars") or 0
        t["ms"] += r.get("ms") or 0
    failed = [r for r in calls if not r.get("ok", True)]
    codes = Counter(r.get("error") or "error" for r in failed)

    sequence: list[list[Any]] = []
    for r in calls:
        if sequence and sequence[-1][0] == r["tool"]:
            sequence[-1][1] += 1
        else:
            sequence.append([r["tool"], 1])

    by_size = sorted(calls, key=lambda r: -(r.get("result_chars") or 0))  # stable: earlier first
    return {
        "calls": len(calls),
        "wall_seconds": round((last - first).total_seconds(), 3) if first and last else 0,
        "first_arrival": stamp(first) if first else None,
        "last_completion": stamp(last) if last else None,
        "distinct_tools": len(per_tool),
        "errors": len(failed),
        "error_codes": dict(codes),
        "images": sum(r.get("images") or 0 for r in calls),
        "result_chars": sum(r.get("result_chars") or 0 for r in calls),
        "max_in_flight": max((r.get("in_flight") or 0 for r in calls), default=0),
        "servers": sorted({str(r["server"]) for r in calls if "server" in r}),
        "per_tool": sorted(({**t, "ms": round(t["ms"], 1)} for t in per_tool.values()), key=lambda t: -t["calls"]),
        "largest_results": [
            {"tool": r["tool"], "result_chars": r.get("result_chars") or 0, "t": r["t"]} for r in by_size[:LARGEST]
        ],
        "first_errors": [
            {"t": r["t"], "tool": r["tool"], "error": r.get("error") or "error"} for r in failed[:FIRST_ERRORS]
        ],
        "sequence": sequence,
        "skipped_lines": skipped,
    }  # fmt: skip


def clock(stamped: str) -> str:
    """The time of day of a ``stamp``."""
    return stamped[11:-1]


def sequence_text(sequence: Sequence[Sequence[Any]], width: int = 100) -> str:
    """``open_image x12, edit_profile x12, ...``: a run of one call is just its
    name; broken into lines at group boundaries."""
    groups = [name if n == 1 else f"{name} x{n}" for name, n in sequence]
    lines: list[str] = []
    for i, group in enumerate(groups):
        piece = group + ("," if i < len(groups) - 1 else "")
        if lines and len(lines[-1]) + 1 + len(piece) <= width:
            lines[-1] += " " + piece
        else:
            lines.append(piece)
    return "\n".join("  " + line for line in lines)


def count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def report(s: Mapping[str, Any]) -> str:
    """The summary as text, for a person to read or two runs to be diffed."""
    if not s["calls"]:
        return "no calls" + (f" (skipped {count(s['skipped_lines'], 'line')})" if s["skipped_lines"] else "")
    codes = ", ".join(f"{code} x{n}" for code, n in s["error_codes"].items())
    out = [
        f"{count(s['calls'], 'call')} in {s['wall_seconds']:.1f} s  ({s['first_arrival']} .. {s['last_completion']})",
        f"{count(s['distinct_tools'], 'tool')}, max in flight {s['max_in_flight']}, {count(s['images'], 'image')}, "
        f"{s['result_chars']:,} result characters, servers: {', '.join(s['servers']) or '?'}",
        count(s["errors"], "error") + (f": {codes}" if s["errors"] else ""),
        "",
        f"{'tool':<24}{'calls':>6}{'errors':>8}{'result_chars':>14}{'ms':>11}",
    ]
    out += [
        f"{t['tool']:<24}{t['calls']:>6}{t['errors']:>8}{t['result_chars']:>14,}{t['ms']:>11,.0f}"
        for t in s["per_tool"]
    ]
    out += ["", "largest results"]
    out += [f"  {r['result_chars']:>9,}  {r['tool']:<22}{clock(r['t'])}" for r in s["largest_results"]]
    if s["first_errors"]:
        out += ["", f"first errors (of {s['errors']})"]
        out += [f"  {clock(e['t'])}  {e['tool']:<22}{e['error']}" for e in s["first_errors"]]
    out += ["", "sequence", sequence_text(s["sequence"])]
    if s["skipped_lines"]:
        out += ["", f"skipped {count(s['skipped_lines'], 'line')} that were not call records"]
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m art_mcp.calllog", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summarise", help="report on a call log")
    summary.add_argument("file", help=f"the file {ENV_VAR} named")
    summary.add_argument("--json", action="store_true", help="print the summary as JSON instead")
    args = parser.parse_args(argv)
    try:
        result = summarise(args.file)
    except OSError as e:
        print(f"art-mcp calllog: cannot read {args.file}: {e.strerror or e}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
