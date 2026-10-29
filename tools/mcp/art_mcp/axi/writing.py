"""Writing files: ``save`` (sidecars), ``export`` and ``partial`` (presets)."""

import argparse
from pathlib import Path
from typing import Any

from art_mcp.axi.args import add_paths
from art_mcp.axi.core import Context, Failure, Parser, UsageError, call
from art_mcp.axi.output import image_labels, progress, prune, rows, shown


def build_save(p: Parser) -> None:
    add_paths(p, "open images whose sidecars to write")
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
    folder, label = image_labels(a.paths)
    how: dict[str, int] = {}
    failures = []
    example = None
    for path in a.paths:
        try:
            result = call(lambda path=path: save_ops.save_sidecar(session, path, a.on_conflict), path)
            how[result.how] = how.get(result.how, 0) + 1
            example = example or shown(result.path)
        except Failure as e:
            failures.append({"image": label[path], "error": f"{e.code}: {e}"})
    out: dict[str, Any] = {
        "saved": f"{len(a.paths) - len(failures)} of {len(a.paths)}",
        **({"folder": folder} if folder else {}),
        "how": how,
        **({"sidecar_of_first": example} if example else {}),
    }
    if failures:
        out["failed"] = rows(failures, ["image", "error"])
        out["help"] = ["art-axi save <path> --on-conflict merge|overwrite  (for a conflict)"]
    return out


FORMATS = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".tif": "tiff", ".tiff": "tiff"}


def build_export(p: Parser) -> None:
    add_paths(p, "open images to export")
    p.add_argument("--out", metavar="FILE", help="the file to write, for one image (its folder is created)")
    p.add_argument(
        "--out-dir", metavar="DIR", help="write each image into this folder (created), named by --name"
    )  # fmt: skip
    p.add_argument(
        "--name", default="{stem}", help="file name with --out-dir, {stem} = the image's name without extension; "
        "the extension comes from --format (default %(default)s)",
    )  # fmt: skip
    p.add_argument(
        "--format", choices=("jpeg", "png", "tiff"), help="default: from --out's extension; jpeg with --out-dir"
    )
    p.add_argument("--quality", type=int, metavar="1..100", help="jpeg only")
    p.add_argument("--bit-depth", choices=("8", "16", "16f", "32"), help="png 8|16, tiff 8|16|16f|32")
    p.add_argument("--write-profile", action="store_true", help="also write the .arp beside it")
    p.add_argument("--profile-name", choices=("output", "source"), default="output", help="name of that .arp")
    p.add_argument("--overwrite", action="store_true", help="replace existing files")


def run_export(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import export_ops

    if (a.out is None) == (a.out_dir is None):
        raise UsageError(
            "give --out FILE (one image) or --out-dir DIR",
            ["art-axi export <path> --out <file>", "art-axi export <path>... --out-dir <dir> [--quality 90]"],
        )
    if a.out is not None and len(a.paths) > 1:
        raise UsageError(
            "--out names one file; for several images use --out-dir", "art-axi export <path>... --out-dir <dir>"
        )
    if a.out_dir is not None:
        return export_many(ctx, a)
    a.path = a.paths[0]
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


def export_many(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    """``export --out-dir``: every image with its working profile, up to two at
    a time; one that fails is its own error and the others still export."""
    from art_mcp.render import export_ops
    from art_mcp.render.export_ops import BatchItem

    try:
        Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise Failure(f"can't create --out-dir: {e}", code="not_found") from e
    session = ctx.session()
    format = a.format or "jpeg"
    result = call(
        lambda: export_ops.export_batch(
            session, [BatchItem(path=p) for p in a.paths], a.out_dir, format, a.quality, a.bit_depth, a.name,
            a.write_profile, a.profile_name, a.overwrite, on_progress=progress("export"),
        )
    )  # fmt: skip
    _, label = image_labels(a.paths)
    labels = {shown(p): name for p, name in label.items()}
    exported = [Path(i.output).name for i in result.items if i.output]
    failures = [{"image": labels.get(shown(i.path), i.path), "error": i.error} for i in result.items if i.error]
    out: dict[str, Any] = {
        "exported": f"{result.exported} of {len(result.items)}",
        "folder": shown(a.out_dir),
        "files": exported,
    }
    if failures:
        out["failed"] = rows(failures, ["image", "error"])
    return out


def build_partial(p: Parser) -> None:
    p.add_argument("path", metavar="PATH")
    p.add_argument("--out", required=True, metavar="ARP", help="the partial profile to write (its folder is created)")
    p.add_argument(
        "--vs", choices=("opened", "default"), default="opened",
        help="which values: those changed since the image was opened, reset or saved (opened), or every value that "
        "differs from ART's default profile (default) (default %(default)s)",
    )  # fmt: skip
    p.add_argument(
        "--exclude", action="append", default=[], metavar="GROUP[/KEY]",
        help="leave this [Group] or Group/Key out (repeatable), e.g. Exposure/Compensation for a per-frame value",
    )  # fmt: skip
    p.add_argument("--keys", action="store_true", help="list every Group/Key written, not a count per group")
    p.add_argument("--overwrite", action="store_true", help="replace an existing --out file")


def run_partial(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    """Write an image's values as a partial profile: a preset for `art-axi
    preset` or for opening other frames with `open --profile`."""
    from art_mcp.render import save_ops

    session = ctx.session()
    try:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise Failure(f"can't create the folder for --out: {e}", code="not_found") from e
    result = call(
        lambda: save_ops.save_partial_profile(session, a.path, a.out, a.overwrite, a.exclude or None, a.vs, a.keys),
        a.path,
    )
    if not result.written:
        nothing = "no unsaved changes" if a.vs == "opened" else "no values differ from ART's default"
        return {"partial": f"nothing written: {nothing}", "help": [f"art-axi partial {shown(a.path)} --vs default ..."]}
    return {
        "partial": shown(result.path),
        "vs": result.vs,
        "total": result.total,
        "keys": result.keys,
        "help": [f"art-axi preset <path>... --profile {shown(result.path)}"],
    }
