"""Export operations: export_image and export_batch."""

import os
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from pydantic import BaseModel

from art_mcp import artdir, keyfile
from art_mcp.concurrency import image_key
from art_mcp.render.artcli import export_args
from art_mcp.render.errors import RenderError, no_profile_written, render_error
from art_mcp.render.session import RenderSession

EXPORT_SUFFIXES = {"jpeg": ".jpg", "tiff": ".tif", "png": ".png"}
PROFILE_NAMES = ("output", "source")


class ExportResult(BaseModel):
    path: str
    """The exported image."""
    profile_path: str | None
    """The `.arp` written, when `write_profile` was set."""


class BatchItem(BaseModel):
    path: str
    """The image to export."""
    profiles: list[str] | None = None
    """`.arp` files layered in order over ART's default profile (a roll
    preset, then this image's own partial profile); the image need not be
    open. Without them the image's working profile is exported (it must be
    open)."""


class BatchItemResult(BaseModel):
    path: str
    output: str | None
    """The exported image; null when this item failed."""
    profile_path: str | None
    """The `.arp` written, when `write_profile` was set."""
    error: str | None
    """`<code>: <message>` when this item failed; the others still run."""


class BatchResult(BaseModel):
    items: list[BatchItemResult]
    """One per requested item, in request order."""
    exported: int
    failed: int


@dataclass(frozen=True)
class OutputFormat:
    format: str
    quality: int | None
    bit_depth: str | None
    write_profile: bool
    profile_name: str = "output"


def move_over(source: Path, target: Path) -> None:
    """Move ``source`` to ``target``, replacing it; works across drives."""
    try:
        os.replace(source, target)
    except OSError:
        shutil.copyfile(source, target)  # temp folder on another drive
        source.unlink()


def output_format(
    format: str,
    quality: int | None,
    bit_depth: int | str | None,
    write_profile: bool,
    profile_name: str = "output",
) -> OutputFormat:
    """The export settings, checked against what art-cli takes
    (``out_of_range`` otherwise)."""
    depth = None if bit_depth is None else str(bit_depth)  # 8 and "8" alike
    try:
        export_args(Path("x"), Path("y"), [], format, quality, depth, write_profile)
    except ValueError as e:
        raise render_error("out_of_range", str(e)) from e
    if profile_name not in PROFILE_NAMES:
        raise render_error(
            "out_of_range", f"profile_name must be one of {', '.join(PROFILE_NAMES)}, not {profile_name!r}"
        )
    if profile_name != "output" and not write_profile:
        raise render_error("out_of_range", f"profile_name {profile_name!r} applies with write_profile only")
    return OutputFormat(format, quality, depth, write_profile, profile_name)


def profile_target(session: RenderSession, image: Path, dest: Path, out: OutputFormat) -> Path | None:
    """Where the `.arp` goes (None without ``write_profile``): ``<dest>.arp``,
    or with ``profile_name="source"`` the name ART gives ``image``'s own
    sidecar, in ``dest``'s folder. That one must not be the image's real
    sidecar, which happens when ``dest`` is in the image's folder
    (``out_of_range``, even with ``overwrite``)."""
    if not out.write_profile:
        return None
    if out.profile_name != "source":
        return Path(str(dest) + ".arp")
    sidecar = artdir.sidecar_path(image, session.config_dir)
    target = dest.with_name(sidecar.name)
    if image_key(target) == image_key(sidecar):
        raise render_error(
            "out_of_range",
            f"{target} is {image.name}'s own sidecar; export to another folder to name the profile after the image",
        )
    return target


def refuse_existing(dest: Path, profile: Path | None) -> None:
    for target in [dest] if profile is None else [dest, profile]:
        if target.exists():
            raise render_error("exists", f"{target} already exists; pass overwrite=true to replace it")


def render_to(
    session: RenderSession,
    image: Path,
    dest: Path,
    profile_dest: Path | None,
    out: OutputFormat,
    *,
    profile_text: str | None = None,
    layers: list[Path] | None = None,
) -> None:
    """Render ``image`` at full size into a temp file, then move it to
    ``dest`` (and its `.arp` to ``profile_dest``). The profile is
    ``profile_text`` (complete), or ``layers`` over ART's default profile."""
    previews = session.previews
    profile = previews.new_file("profile", ".arp")
    temp = previews.new_file("export", EXPORT_SUFFIXES.get(out.format, ".out"))
    temp_arp = Path(str(temp) + ".arp")
    try:
        if profile_text is not None:
            profile.write_text(profile_text, encoding="utf-8")
            args = export_args(image, temp, [profile], out.format, out.quality, out.bit_depth, out.write_profile)
        else:
            args = export_args(
                image, temp, layers or [], out.format, out.quality, out.bit_depth, out.write_profile,
                default_base=True,
            )  # fmt: skip
        session.run(args, temp, timeout=session.cli.export_timeout)
        if out.write_profile and not temp_arp.is_file():
            raise no_profile_written()
        move_over(temp, dest)
        if profile_dest is not None:
            move_over(temp_arp, profile_dest)
    finally:
        for leftover in (profile, temp, temp_arp):
            leftover.unlink(missing_ok=True)


def export_image(
    session: RenderSession,
    path: str,
    output: str,
    format: str,
    quality: int | None = None,
    bit_depth: int | str | None = None,
    write_profile: bool = False,
    profile_name: str = "output",
    overwrite: bool = False,
) -> ExportResult:
    out = output_format(format, quality, bit_depth, write_profile, profile_name)
    with session.image(path) as wp:
        dest = Path(output).resolve()
        if not dest.parent.is_dir():
            raise render_error("not_found", f"folder {dest.parent} does not exist")
        profile = profile_target(session, wp.image, dest, out)
        if not overwrite:
            refuse_existing(dest, profile)
        render_to(session, wp.image, dest, profile, out, profile_text=keyfile.dumps(wp.changes.profile))
    return ExportResult(path=str(dest), profile_path=str(profile) if profile else None)


def output_name(name: str, image: Path, suffix: str) -> str:
    """``name`` with ``{stem}`` replaced by the image's file name without
    extension, plus the format's suffix (``out_of_range`` for any other
    placeholder or a path separator)."""
    try:
        base = name.format(stem=image.stem)
    except (KeyError, IndexError, ValueError) as e:
        raise render_error("out_of_range", f"name {name!r}: the only placeholder is {{stem}}") from e
    if not base or any(sep in base for sep in "/\\") or base in (".", ".."):
        raise render_error("out_of_range", f"name {name!r} must give a file name, not a path")
    return base + suffix


IMAGE_SUFFIXES = frozenset(
    ".3fr .arw .arq .cr2 .cr3 .crf .crw .dcr .dng .fff .iiq .jpg .jpeg .kdc .mef .mos .mrw .nef .nrw .orf .pef"
    " .raf .raw .rw2 .rwl .rwz .sr2 .srf .srw .tif .tiff .x3f".split()
)
"""The extensions of ART's default "parsed extensions" (Preferences; png is
off there): what a source folder's images are."""


def folder_items(source: str, pattern: str | None, profiles: list[str] | None) -> list[BatchItem]:
    """One item per image directly in ``source``, by file name; ``pattern``
    (a glob on the file name, any case) keeps only the images it matches.
    Each item gets ``profiles``."""
    folder = Path(source).resolve()
    if not folder.is_dir():
        raise render_error("not_found", f"folder {folder} does not exist")
    images = sorted(
        (
            p
            for p in folder.iterdir()
            if p.suffix.lower() in IMAGE_SUFFIXES
            and (pattern is None or fnmatchcase(p.name.lower(), pattern.lower()))
            and p.is_file()
        ),
        key=lambda p: (p.name.lower(), p.name),
    )
    if not images:
        raise render_error("not_found", f"no images in {folder}" + (f" matching {pattern!r}" if pattern else ""))
    return [BatchItem(path=str(p), profiles=profiles) for p in images]


def batch_items(
    items: list[BatchItem] | None, source: str | None, pattern: str | None, profiles: list[str] | None
) -> list[BatchItem]:
    """The items to export: ``items`` or the images of ``source`` (exactly
    one of them; ``pattern`` and ``profiles`` go with ``source`` only)."""
    if source is None:
        if pattern is not None or profiles is not None:
            raise render_error("out_of_range", "pattern and profiles go with source; for items use their own profiles")
        if items is None:
            raise render_error("out_of_range", "give items or source")
        if not items:
            raise render_error("out_of_range", "items is empty")
        return items
    if items is not None:
        raise render_error("out_of_range", "give items or source, not both")
    return folder_items(source, pattern, profiles)


@dataclass
class Job:
    index: int
    image: Path
    dest: Path
    profile_text: str | None = None
    layers: list[Path] | None = None
    profile_dest: Path | None = None


def export_batch(
    session: RenderSession,
    items: list[BatchItem] | None,
    folder: str,
    format: str,
    quality: int | None = None,
    bit_depth: int | str | None = None,
    name: str = "{stem}",
    write_profile: bool = False,
    profile_name: str = "output",
    overwrite: bool = False,
    source: str | None = None,
    pattern: str | None = None,
    profiles: list[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> BatchResult:
    """Export every item, or every image of the ``source`` folder (each
    with ``profiles`` layered over ART's default, else its working profile),
    into ``folder``. Problems with the call as a whole (format, folder,
    items and source, names that collide) fail it before anything renders;
    a problem with one item is that item's error and the others still run,
    up to ``session.cli.max_processes`` at once. Working profiles are
    copied when the call starts, so later edits don't reach this export.
    ``on_progress(done, total)`` is called as each render finishes."""
    out = output_format(format, quality, bit_depth, write_profile, profile_name)
    target = Path(folder).resolve()
    if not target.is_dir():
        raise render_error("not_found", f"folder {target} does not exist")
    items = batch_items(items, source, pattern, profiles)
    suffix = EXPORT_SUFFIXES[out.format]
    dests = [target / output_name(name, Path(item.path), suffix) for item in items]
    seen: dict[str, int] = {}
    for i, dest in enumerate(dests):
        key = image_key(dest)
        if key in seen:
            raise render_error(
                "out_of_range",
                f"{items[seen[key]].path} and {items[i].path} would both export to {dest.name}; "
                "use a name pattern with {stem}, or export them in separate calls",
            )
        seen[key] = i

    results = [BatchItemResult(path=item.path, output=None, profile_path=None, error=None) for item in items]
    jobs: list[Job] = []
    for i, (item, dest) in enumerate(zip(items, dests, strict=True)):
        try:
            jobs.append(prepare(session, i, item, dest, out, overwrite))
        except RenderError as e:
            results[i].error = str(e)

    def run(job: Job) -> None:
        render_to(
            session, job.image, job.dest, job.profile_dest, out, profile_text=job.profile_text, layers=job.layers
        )

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = {pool.submit(run, job): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                future.result()
                results[job.index].output = str(job.dest)
                results[job.index].profile_path = str(job.profile_dest) if job.profile_dest else None
            except RenderError as e:
                results[job.index].error = str(e)
            except OSError as e:
                results[job.index].error = f"render_failed: {e}"
            done += 1
            if on_progress:
                on_progress(done, len(jobs))

    failed = sum(r.error is not None for r in results)
    if failed < len(results):
        session.last_export_folder = target
    return BatchResult(items=results, exported=len(results) - failed, failed=failed)


def prepare(session: RenderSession, index: int, item: BatchItem, dest: Path, out: OutputFormat, overwrite: bool) -> Job:
    """One item's render job; raises the item's error."""
    if image_key(Path(item.path).resolve()) == image_key(dest):
        raise render_error("exists", f"{dest} is the image itself; export into another folder or format")
    if item.profiles is not None:
        image = Path(item.path).resolve()
        if not image.is_file():
            raise render_error("not_found", f"{image} does not exist")
        profile = profile_target(session, image, dest, out)
        if not overwrite:
            refuse_existing(dest, profile)
        layers = [Path(p).resolve() for p in item.profiles]
        for layer in layers:
            if not layer.is_file():
                raise render_error("not_found", f"profile {layer} does not exist")
        return Job(index, image, dest, layers=layers, profile_dest=profile)
    with session.image(item.path) as wp:
        profile = profile_target(session, wp.image, dest, out)
        if not overwrite:
            refuse_existing(dest, profile)
        return Job(index, wp.image, dest, profile_text=keyfile.dumps(wp.changes.profile), profile_dest=profile)
