"""Measuring rendered images: ``stats`` (with ``--set`` and ``--sweep``) and
``sample``."""

import argparse
from decimal import Decimal
from typing import Any

from art_mcp.axi import toon
from art_mcp.axi.args import add_paths, comma_floats, raw_edit, spot
from art_mcp.axi.core import Context, Parser, adjustments_arg, call
from art_mcp.axi.output import as_number, image_labels, progress, prune, rows, shown


def build_stats(p: Parser) -> None:
    from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE

    add_paths(p, "images to measure (up to 50)")
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
        metavar=f"1..{MAX_PREVIEW_SIZE}",
        help="long edge of the render measured (default %(default)s)",
    )
    p.add_argument("--stage", default="display", choices=("display", "converted"), help="default %(default)s")
    p.add_argument(
        "--set", dest="raw", action="append", type=raw_edit, default=[], metavar="GROUP/KEY=VALUE",
        help="measure with this value instead of the stored one, without storing it (repeatable)",
    )  # fmt: skip
    p.add_argument("--adjust", metavar="JSON", help="the same with curated adjustments, as `edit --adjust`")
    p.add_argument(
        "--sweep", type=sweep, metavar="GROUP/KEY=V1,V2,...",
        help="measure each value of one key (up to 50 values, nothing stored), one row per value; with several "
        "images each row is the worst image's: Exposure/Compensation=0.4,0.5 or =0:2:0.1; --detail adds percentiles",
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


def image_row(stats: dict[str, Any]) -> dict[str, Any]:
    """One image's statistics as one row: the clipped fractions per channel,
    p99.9 per colour channel (how close the highlights are to 255) and the
    median brightness."""
    row = sweep_row(stats, full=False)
    for ch in ("r", "g", "b"):
        row[f"p99.9_{ch}"] = stats.get(ch, {}).get("percentiles", {}).get("99.9")
    row["p50_lum"] = stats.get("lum", {}).get("percentiles", {}).get("50")
    return row


def worst_row(measured: dict[str, dict[str, Any]], label: dict[str, str], several: bool, full: bool) -> dict[str, Any]:
    """One swept value's row: per channel the largest clipped fraction over
    the images and, for several, the image with the most clipping at each end."""
    each = {path: sweep_row(stats, full) for path, stats in measured.items()}
    row: dict[str, Any] = {}
    columns = list(dict.fromkeys(k for r in each.values() for k in r))
    for column in columns:
        values = [r[column] for r in each.values() if r.get(column) is not None]
        row[column] = max(values) if values else None
    if several:
        for end in ("high", "low"):
            score = {p: max(r.get(f"clipped_{end}_{c}") or 0 for c in "rgb") for p, r in each.items()}
            worst = max(score, key=lambda p: score[p], default=None)
            row[f"worst_{end}"] = label[worst] if worst is not None and score[worst] > 0 else None
    return row


def run_stats(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import profile_ops, sampling_ops
    from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, Region
    from art_mcp.schema import RawEdit

    region = Region(**dict(zip("xywh", a.region, strict=True))) if a.region else None
    adjustments = adjustments_arg(a.adjust)
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
    folder, label = image_labels(a.paths)
    if a.sweep:
        group, key, values = a.sweep
        several = len(a.paths) > 1
        table: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        render = None
        for value in values:
            for path in a.paths:
                override(path, [{"group": group, "key": key, "value": value}])
            if several:
                batch = call(lambda: measure(None, a.paths, a.detail or "compact"))
                measured = {i.path: prune(i.stats) for i in batch.items if not i.error}
                errors.update({label[i.path]: i.error for i in batch.items if i.error})
            else:
                measured = {a.paths[0]: prune(call(lambda: measure(a.paths[0], None, a.detail or "compact")))}
            if measured:
                first = next(iter(measured.values()))
                render = f"{first.get('width')}x{first.get('height')}"
            table.append({"value": as_number(value), **worst_row(measured, label, several, a.detail is not None)})
        columns = list(dict.fromkeys(k for row in table for k in row))
        out: dict[str, Any] = {
            **({"folder": folder} if folder else {}),
            "images": len(a.paths) if several else shown(a.paths[0]),
            "sweep": f"{group}/{key} (nothing stored)",
            "render": f"{render} (--size {a.size}, max {MAX_PREVIEW_SIZE}; raise it to confirm small clipped areas)",
            "results": rows(table, columns),
        }
        if several:
            out["note"] = "clipped_* is the worst image's fraction for that value; worst_* names that image"
        for end in ("high", "low"):
            clean = [row["value"] for row in table if all(not row.get(f"clipped_{end}_{c}") for c in "rgb")]
            out[f"no_clipping_{end}"] = clean if clean else "none of the values"
        if errors:
            out["errors"] = errors
        target = "<path>..." if several else shown(a.paths[0])
        out["help"] = [f"art-axi edit {target} --set {group}/{key}=<chosen value>"]
        return out
    if len(a.paths) == 1:
        stats = prune(call(lambda: measure(a.paths[0], None), a.paths[0]))
        rest, lists = channel_table(stats)
        return {"path": shown(a.paths[0]), **rest, **lists}
    batch = call(lambda: measure(None, a.paths))
    table = []
    for item in batch.items:
        row: dict[str, Any] = {"image": label[item.path]}
        if item.error:
            row["error"] = item.error
        else:
            row.update(image_row(prune(item.stats)))
        table.append(row)
    columns = list(dict.fromkeys(k for row in table for k in row))
    out = {**({"folder": folder} if folder else {}), "images": rows(table, columns), "failed": batch.failed}
    for end in ("high", "low"):
        clipped = [row["image"] for row in table if any(row.get(f"clipped_{end}_{c}") for c in "rgb")]
        out[f"clipped_{end}"] = f"{len(clipped)} of {len(table)}" + (f": {' '.join(clipped)}" if clipped else "")
    return out


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
