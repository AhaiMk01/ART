"""Looking at images: ``preview`` and the contact ``sheet``."""

import argparse
import os
from pathlib import Path
from typing import Any

from art_mcp.axi.args import add_paths, comma_floats, mark
from art_mcp.axi.core import Context, Parser, UsageError, call
from art_mcp.axi.output import progress, prune, rows, shown


def build_preview(p: Parser) -> None:
    from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE

    add_paths(p, "images to render (up to 16)")
    p.add_argument(
        "--size",
        type=int,
        default=PREVIEW_SIZE,
        metavar=f"1..{MAX_PREVIEW_SIZE}",
        help="long edge in px (default %(default)s)",
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


def build_sheet(p: Parser) -> None:
    add_paths(p, "open images, or a folder for the open images in it")
    p.add_argument("--columns", type=int, metavar="N", help="frames per row (default 6)")
    p.add_argument("--thumb", type=int, default=None, metavar="PX", help="long edge of each frame, 32..1024")
    p.add_argument(
        "--record", metavar="FOLDER",
        help="also save it as the next numbered pass under FOLDER/sheets/ with a JSON of what changed since the "
        "last pass (default: just a sheet to look at)",
    )  # fmt: skip
    p.add_argument("--label", help="a short name for the recorded pass")


def run_sheet(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import sheet_ops

    if a.label and not a.record:
        raise UsageError("--label goes with --record", "art-axi sheet <path>... --record <folder> --label <name>")
    session = ctx.session()
    thumb = a.thumb or sheet_ops.DEFAULT_THUMB_SIZE
    result = call(
        lambda: sheet_ops.contact_sheet(
            session, a.paths, a.record, a.label, a.columns, thumb, on_progress=progress("sheet"),
            record=a.record is not None,
        )
    )  # fmt: skip
    count = len(result.images)
    if a.columns:
        columns = a.columns
    elif a.record:
        columns = min(count, sheet_ops.DEFAULT_COLUMNS)
    else:
        columns = sheet_ops.quick_columns(count, thumb)
    out: dict[str, Any] = {
        "sheet": shown(result.path),
        "frames": [f.name for f in result.images],
        "layout": f"{columns} per row, left to right then down; each frame's file name under it",
    }
    failures = [{"image": f.name, "error": f.error} for f in result.images if f.error]
    if failures:
        out["failed"] = rows(failures, ["image", "error"])
    if result.index is not None:
        out["pass"] = result.index
        out["record"] = shown(result.json_path)
        changes = prune(result.changes) if result.changes else None
        out["changes"] = changes or "first pass for these frames (nothing to compare)"
    if result.warnings:
        out["warnings"] = result.warnings
    out["help"] = ["open the sheet JPEG to look at the frames", "art-axi preview <path>  (one frame larger)"]
    return out
