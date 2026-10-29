"""Commands about which images are open: the home view, ``open``, ``close``,
``reset`` and ``inspect``."""

import argparse
import sys
from pathlib import Path
from typing import Any

from art_mcp.axi.args import add_paths, names
from art_mcp.axi.core import DESCRIPTION, Context, Parser, art_cli_location, call, edit_count
from art_mcp.axi.output import as_number, home_relative, image_labels, progress, prune, rows, shown
from art_mcp.axi.state import DiskStore
from art_mcp.render.errors import RenderError


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
    p.add_argument(
        "paths", nargs="+", metavar="PATH", help="images to open (up to 50), or a folder for the images in it"
    )
    p.add_argument("--profile", metavar="ARP", help="start from this .arp over ART's default instead of the sidecar")


def run_open(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    from art_mcp.render import export_ops, profile_ops

    # A folder opens the raw, jpeg and tiff images directly in it.
    expanded: list[str] = []
    for path in a.paths:
        if Path(path).is_dir():
            expanded.extend(item.path for item in call(lambda path=path: export_ops.folder_items(path, None, None)))
        else:
            expanded.append(path)
    a.paths = expanded
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
    folder, label = image_labels(a.paths)
    sources: dict[str, int] = {}
    for i in batch.items:
        if i.profile_from:
            sources[i.profile_from] = sources.get(i.profile_from, 0) + 1
    failures = [{"image": label[i.path], "error": i.error} for i in batch.items if i.error]
    return {
        "opened": f"{len(batch.items) - batch.failed} of {len(batch.items)}",
        **({"folder": folder} if folder else {}),
        "profile_from": sources,
        **({"failed": rows(failures, ["image", "error"])} if failures else {}),
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
    add_paths(p, "images to close")


def run_close(ctx: Context, a: argparse.Namespace) -> dict[str, Any]:
    store = ctx.store()
    targets = [Path(p).resolve() for p in a.paths]
    if not targets:
        return {"closed": "0 (no images were open)"}
    folder, label = image_labels([str(t) for t in targets])
    not_open = []
    for image in targets:
        if store.get(image) is None:
            not_open.append(label[str(image)])
        store.discard(image)
    out: dict[str, Any] = {"closed": f"{len(targets) - len(not_open)} of {len(targets)}"}
    if folder:
        out["folder"] = folder
    if not_open:
        out["not_open"] = f"{' '.join(not_open)} (no-op)"
    return out


def build_reset(p: Parser) -> None:
    add_paths(p, "open images to reload")
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


def build_inspect(p: Parser) -> None:
    add_paths(p, "open images (up to 100)")
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
