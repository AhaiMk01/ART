"""Reading and changing working profiles: ``profile``, ``edit`` and ``describe``."""

import argparse
import json
from typing import Any

from art_mcp.axi import toon
from art_mcp.axi.args import add_paths, names, raw_edit
from art_mcp.axi.core import Context, Failure, Parser, UsageError, adjustments_arg, call, edit_count
from art_mcp.axi.output import TRUNCATE, as_number, image_labels, prune, rows, shown, truncated


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
    add_paths(p, "images to change the same way (up to 50)")
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
    folder, label = image_labels(a.paths)
    failures = [{"image": label[path], "error": error} for path, _, error in results if error]
    summary = {"edited": f"{len(done)} of {len(results)}", **({"folder": folder} if folder else {})}
    if failures:
        summary["failed"] = rows(failures, ["image", "error"])
    if done and all(out == done[0] for out in done):
        # The same change to every image: said once.
        return {**summary, **done[0]}
    items = [{"image": label[path], **out} for path, out, _ in results if out is not None]
    return {**summary, "images": items}


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
