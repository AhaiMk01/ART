"""Contact-sheet operations: contact_sheet and compare_passes.

A sheet is one numbered *pass* over a set of images: ``<folder>/sheets/
pass-03-black-point.jpg`` with ``pass-03-black-point.json`` beside it. Passes
are never overwritten. ``sheets/profiles.json`` keeps each image's complete
working profile as of the last pass it was in, which the next pass is
compared with (it is bookkeeping, not a pass record). A comparison of two
passes is saved beside them as ``compare-03-05.jpg``, never overwritten either.
"""

import json
import math
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image
from pydantic import BaseModel

from art_mcp import artdir, keyfile, sidecar
from art_mcp.concurrency import image_key
from art_mcp.contactsheet import PAD, Cell, compose, side_by_side
from art_mcp.keyfile import KeyFile
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, render_jpeg
from art_mcp.render.session import RenderSession
from art_mcp.render.sheet_changes import MAX_SHARED_CHANGES, ChangeSummary, KeyChange, changes_between, summarise

SHEETS_DIR = "sheets"
PROFILES_FILE = "profiles.json"
JPEG_QUALITY = 85
DEFAULT_THUMB_SIZE = 400
MIN_THUMB_SIZE = 32
MAX_THUMB_SIZE = 1024
DEFAULT_COLUMNS = 6
DEFAULT_PAIR_COLUMNS = 2
MAX_COLUMNS = 20
MAX_LABEL_SLUG = 40

_PASS_FILE = re.compile(r"pass-(\d+)(?:-.*)?\.(?:jpg|json)", re.IGNORECASE)


class Pass(BaseModel):
    """What a pass's JSON file and the result of the call that made it have in common."""

    index: int
    label: str | None
    time: str
    """ISO 8601, local time."""
    sheet: str
    """The sheet's file name, beside the JSON file."""
    thumb_size: int
    columns: int
    width: int
    height: int


class SheetImage(BaseModel):
    """One frame, as the pass's JSON file has it, with every change."""

    path: str
    name: str
    box: list[int] | None
    """[x, y, w, h] of its frame on the sheet; null when it could not be rendered."""
    error: str | None
    """`<code>: <message>` when this image could not be rendered; the sheet shows a placeholder."""
    since_pass: int | None
    """The pass `changes` is measured from: the last one this image was in. Null for its first."""
    changes: list[KeyChange] | None
    """The profile values that differ from that pass, numbers with at most 7 significant digits; null for the
    image's first pass (or when its profile couldn't be read)."""


class PassRecord(Pass):
    """What the pass's JSON file holds."""

    images: list[SheetImage]


class SheetFrame(BaseModel):
    """One frame, as the result of ``contact_sheet`` has it: the number of changes, not the changes."""

    path: str
    name: str
    box: list[int] | None
    """[x, y, w, h] of its frame on the sheet; null when it could not be rendered."""
    error: str | None
    """`<code>: <message>` when this image could not be rendered; the sheet shows a placeholder."""
    since_pass: int | None
    """The pass `changed` is measured from: the last one this image was in. Null for its first."""
    changed: int | None
    """How many profile values differ from that pass (0 when none); null when there is nothing to
    compare with. Which ones: `changes` for the whole set, the pass JSON per frame."""


class SheetResult(Pass):
    index: int | None
    """The pass number; null for a sheet made with `record=false`, which is not a pass."""
    images: list[SheetFrame]
    changes: ChangeSummary | None
    """What changed since the last pass, the same change on several frames being one entry with their
    file names (`groups`: the most shared first, then by name; a change made on every frame of a
    pass of more than 4 frames has `images` null instead of the names; `more`: how many further
    ones are not listed). Null when no frame had an earlier pass to compare with (a first pass), and
    with `record=false`. Every change per frame is in the JSON."""
    path: str
    """The sheet (a JPEG); open it to look at the frames. With `record=false` it is a file in the
    server's own temp folder."""
    json_path: str | None
    """The pass's record: per image `changes`, every profile value that differs. Null with `record=false`."""
    rendered: int
    failed: int
    warnings: list[str] = []


@dataclass
class Frame:
    image: Path
    profile: KeyFile | None = None
    error: str | None = None
    thumbnail: Path | None = None


def label_slug(label: str) -> str:
    """``label`` as a file-name part: runs of anything but letters, digits and
    ``_`` become ``-``."""
    slug = re.sub(r"[^A-Za-z0-9_]+", "-", label).strip("-")[:MAX_LABEL_SLUG].strip("-")
    if not slug:
        raise render_error("out_of_range", f"label {label!r} has no letters or digits to name the file by")
    return slug


def sheets_folder(session: RenderSession, folder: str | None) -> Path:
    """Where the passes go: ``sheets`` in ``folder``, which defaults to the
    folder the last recorded ``contact_sheet`` call used. With neither the call
    fails: it never guesses a folder (not the exports', the source images' or
    the temp folder)."""
    if folder is None:
        if session.last_sheets_folder is None:
            raise render_error(
                "out_of_range",
                "folder is required: it is where a `sheets` subfolder is created to keep the passes. Give any "
                "existing folder you choose, for example your work folder; not the exports folder, the passes "
                "would mix with the exports. Once a contact_sheet call has used a folder, later calls default to it",
            )
        base = session.last_sheets_folder
    else:
        base = Path(folder).resolve()
    if not base.is_dir():
        raise render_error("not_found", f"folder {base} does not exist")
    return base / SHEETS_DIR


def expand(session: RenderSession, entries: list[str]) -> list[Path]:
    """The images an ``images`` argument names, once each: its paths, with a
    folder standing for the open images directly in it (by name)."""
    paths: list[Path] = []
    seen: set[str] = set()
    for entry in entries:
        given = Path(entry).resolve()
        if given.is_dir():
            found = sorted(
                (wp.image for wp in session.store.all() if image_key(wp.image.parent) == image_key(given)),
                key=lambda p: p.name.casefold(),
            )
            if not found:
                raise render_error("not_open", f"no image in {given} is open; call open_image first")
        else:
            found = [given]
        for path in found:
            if image_key(path) not in seen:
                seen.add(image_key(path))
                paths.append(path)
    return paths


def next_index(sheets: Path) -> int:
    numbers = [int(m[1]) for p in sheets.iterdir() if (m := _PASS_FILE.fullmatch(p.name))]
    return max(numbers, default=0) + 1


def read_profiles(sheets: Path) -> dict[str, dict]:
    """``profiles.json``: per image (``image_key``) ``{"pass": n, "profile":
    {group: {key: value}}}``. A missing or damaged file, or entry, is no
    earlier pass."""
    try:
        data = json.loads((sheets / PROFILES_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: entry
        for key, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("pass"), int) and isinstance(entry.get("profile"), dict)
    }


def render_all(
    session: RenderSession,
    frames: list[Frame],
    thumb_size: int,
    on_progress: Callable[[int, int], None] | None,
) -> None:
    """Render a thumbnail for every frame that has a profile, up to
    ``session.cli.max_processes`` at once; a failure is that frame's error."""
    fast = thumb_size <= artdir.fast_export_box(session.config_dir)
    jobs = [f for f in frames if f.profile is not None]

    def run(frame: Frame) -> None:
        assert frame.profile is not None
        frame.thumbnail = render_jpeg(session, frame.image, keyfile.dumps(frame.profile), thumb_size, fast=fast)

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = {pool.submit(run, frame): frame for frame in jobs}
        for future in as_completed(futures):
            try:
                future.result()
            except RenderError as e:
                futures[future].error = str(e)
            except OSError as e:
                futures[future].error = f"render_failed: {e}"
            done += 1
            if on_progress:
                on_progress(done, len(jobs))


def contact_sheet(
    session: RenderSession,
    images: list[str],
    folder: str | None = None,
    label: str | None = None,
    columns: int | None = None,
    thumb_size: int = DEFAULT_THUMB_SIZE,
    on_progress: Callable[[int, int], None] | None = None,
    record: bool = True,
) -> SheetResult:
    """Render ``images`` from their working profiles as small thumbnails,
    compose them into a labelled grid and save it as the next pass in
    ``<folder>/sheets``. A problem with the call as a whole fails it before
    anything renders; a problem with one image is that image's error, with a
    placeholder on the sheet. Working profiles are copied when the call
    starts. ``on_progress(done, total)`` is called as each render finishes.

    Without ``record`` the same sheet is a quick look, not a pass: a new JPEG in
    the previews folder (like ``render_preview``'s) and nothing else. No number,
    JSON, bookkeeping or comparison, and ``folder`` is not used. ``columns``
    defaults to ``quick_columns``."""
    if not MIN_THUMB_SIZE <= thumb_size <= MAX_THUMB_SIZE:
        raise render_error("out_of_range", f"thumb_size must be {MIN_THUMB_SIZE} to {MAX_THUMB_SIZE}")
    if columns is not None and not 1 <= columns <= MAX_COLUMNS:
        raise render_error("out_of_range", f"columns must be 1 to {MAX_COLUMNS}")
    slug = label_slug(label) if record and label is not None else None
    sheets = sheets_folder(session, folder) if record else None
    paths = expand(session, images)
    if not paths:
        raise render_error("out_of_range", "images is empty")

    frames = [Frame(path) for path in paths]
    for frame in frames:
        try:
            with session.image(frame.image) as wp:
                frame.profile = {group: dict(entries) for group, entries in wp.changes.profile.items()}
        except RenderError as e:
            frame.error = str(e)
    try:
        render_all(session, frames, thumb_size, on_progress)
        if all(f.thumbnail is None for f in frames):
            first_error = next((f.error for f in frames if f.error), "")
            raise render_error("render_failed", f"no image could be rendered; the first: {first_error}")
        if sheets is None:
            return save_look(session, frames, label, columns or quick_columns(len(frames), thumb_size), thumb_size)
        with session.locked_folder(sheets):
            saved = save_pass(sheets, frames, label, slug, columns or min(len(frames), DEFAULT_COLUMNS), thumb_size)
        session.last_sheets_folder = sheets.parent
        return saved
    finally:
        for frame in frames:
            if frame.thumbnail is not None:
                frame.thumbnail.unlink(missing_ok=True)


def quick_columns(count: int, thumb_size: int) -> int:
    """``columns`` for an unrecorded sheet of ``count`` frames when the caller
    names none: a grid about as wide as it is high (``ceil(sqrt(count))``),
    narrowed so its width stays within what Claude shows without shrinking
    (``MAX_PREVIEW_SIZE``). A few big frames come out as one readable image:
    4 frames of 1000 px make 2 by 2, 6 of 700 px make 3 by 2. (A pass keeps
    its default of 6.)"""
    square = math.ceil(math.sqrt(count))
    fitting = (MAX_PREVIEW_SIZE - PAD) // (thumb_size + PAD)
    return max(1, min(square, fitting, MAX_COLUMNS))


def frame_cells(frames: list[Frame]) -> list[Cell]:
    return [Cell(f.image.name, f.thumbnail, (f.error or "").partition(":")[0]) for f in frames]


def size_warnings(grid: Image.Image) -> list[str]:
    """A warning when ``grid`` is longer than Claude shows without shrinking it."""
    if max(grid.size) <= MAX_PREVIEW_SIZE:
        return []
    return [
        f"the sheet is {grid.width}x{grid.height} px and gets shown at most {MAX_PREVIEW_SIZE} px on its "
        "long edge, so the frames look smaller than thumb_size: use fewer images or a smaller thumb_size"
    ]


def save_look(
    session: RenderSession, frames: list[Frame], label: str | None, columns: int, thumb_size: int
) -> SheetResult:
    """Compose the sheet and save it as a new file in the previews folder (which goes
    with the server); nothing of a pass is kept: no number, JSON or bookkeeping."""
    now = datetime.now().astimezone()
    title = (label or "preview") + f" - {now:%Y-%m-%d %H:%M}"
    grid, boxes = compose(frame_cells(frames), columns, thumb_size, title)
    jpeg = session.previews.new_file("sheet", ".jpg")
    try:
        save_new_jpeg(jpeg, grid)
    except OSError as e:
        raise render_error("render_failed", f"cannot write the sheet {jpeg}: {e}") from e
    rendered = sum(f.thumbnail is not None for f in frames)
    return SheetResult(
        index=None,
        label=label,
        time=now.isoformat(timespec="seconds"),
        sheet=jpeg.name,
        thumb_size=thumb_size,
        columns=max(1, min(columns, len(frames))),
        width=grid.width,
        height=grid.height,
        images=[
            SheetFrame(
                path=str(f.image),
                name=f.image.name,
                box=[box.x, box.y, box.w, box.h] if box else None,
                error=f.error,
                since_pass=None,
                changed=None,
            )
            for f, box in zip(frames, boxes, strict=True)
        ],
        changes=None,
        path=str(jpeg),
        json_path=None,
        rendered=rendered,
        failed=len(frames) - rendered,
        warnings=size_warnings(grid),
    )


def save_new_jpeg(target: Path, grid: Image.Image) -> None:
    """Save ``grid`` as ``target``, which must not exist yet (else
    ``FileExistsError``: sheets are never overwritten); a failed write leaves
    nothing behind."""
    try:
        with target.open("xb") as f:
            grid.save(f, "JPEG", quality=JPEG_QUALITY)
    except FileExistsError:
        raise
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def save_pass(
    sheets: Path,
    frames: list[Frame],
    label: str | None,
    slug: str | None,
    columns: int,
    thumb_size: int,
) -> SheetResult:
    """Compose the sheet and write the next pass. Caller holds the folder's lock."""
    try:
        sheets.mkdir(exist_ok=True)
        index = next_index(sheets)
        now = datetime.now().astimezone()
        title = f"pass {index:02d}" + (f" - {label}" if label else "") + f" - {now:%Y-%m-%d %H:%M}"
        grid, boxes = compose(frame_cells(frames), columns, thumb_size, title)
        profiles = read_profiles(sheets)
        images: list[SheetImage] = []
        for frame, box in zip(frames, boxes, strict=True):
            before = profiles.get(image_key(frame.image))
            compared = frame.profile is not None and before is not None
            images.append(
                SheetImage(
                    path=str(frame.image),
                    name=frame.image.name,
                    box=[box.x, box.y, box.w, box.h] if box else None,
                    error=frame.error,
                    since_pass=before["pass"] if compared else None,
                    changes=changes_between(before["profile"], frame.profile) if compared else None,
                )
            )
            if frame.profile is not None:
                profiles[image_key(frame.image)] = {"pass": index, "profile": frame.profile}

        stem = f"pass-{index:02d}" + (f"-{slug}" if slug else "")
        record = PassRecord(
            index=index,
            label=label,
            time=now.isoformat(timespec="seconds"),
            sheet=stem + ".jpg",
            thumb_size=thumb_size,
            columns=max(1, min(columns, len(frames))),
            width=grid.width,
            height=grid.height,
            images=images,
        )
        jpeg, record_file = sheets / record.sheet, sheets / (stem + ".json")
        created: list[Path] = []
        try:
            save_new_jpeg(jpeg, grid)
            created.append(jpeg)
            with record_file.open("x", encoding="utf-8") as f:  # "x": a pass is never overwritten
                created.append(record_file)
                f.write(record.model_dump_json(indent=2))
            sidecar.write_atomic(sheets / PROFILES_FILE, json.dumps(profiles))
        except BaseException:
            for path in created:  # no half a pass is left behind
                path.unlink(missing_ok=True)
            raise
    except FileExistsError as e:
        raise render_error("exists", f"{e.filename} already exists") from e
    except OSError as e:
        raise render_error("render_failed", f"cannot write the pass into {sheets}: {e}") from e

    rendered = sum(f.thumbnail is not None for f in frames)
    warnings = size_warnings(grid)
    summary = summarise(((i.name, i.changes) for i in images), MAX_SHARED_CHANGES)
    if summary is not None and summary.more:
        warnings.append(
            f"changes lists the {len(summary.groups)} most shared of {len(summary.groups) + summary.more} "
            f"different changes ({summary.more} more not listed): every change per frame is in {record_file}"
        )
    return SheetResult(
        **record.model_dump(exclude={"images"}),
        images=[
            SheetFrame(**i.model_dump(exclude={"changes"}), changed=None if i.changes is None else len(i.changes))
            for i in images
        ],
        changes=summary,
        path=str(jpeg),
        json_path=str(record_file),
        rendered=rendered,
        failed=len(frames) - rendered,
        warnings=warnings,
    )


class Comparison(BaseModel):
    path: str
    """The side-by-side sheet (a JPEG): the first pass's frame left, the second's right."""
    first: int
    second: int
    images: list[str]
    """File names of the frames shown, in sheet order."""
    width: int
    height: int


def load_pass(sheets: Path, index: int) -> PassRecord:
    """The record of pass ``index`` (``not_found`` if there is none)."""
    candidates = sheets.iterdir() if sheets.is_dir() else []
    for file in sorted(candidates):
        m = _PASS_FILE.fullmatch(file.name)
        if m and file.suffix.lower() == ".json" and int(m[1]) == index:
            try:
                return PassRecord.model_validate_json(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise render_error("render_failed", f"{file} is not a readable pass record: {e}") from e
    raise render_error("not_found", f"there is no pass {index} in {sheets}")


def pass_title(record: PassRecord) -> str:
    return f"pass {record.index:02d}" + (f" ({record.label})" if record.label else "")


Pair = tuple[SheetImage, SheetImage]


def chosen_frames(entries: list[str] | None, first: PassRecord, second: PassRecord) -> list[Pair]:
    """The frames to compare as (in ``first``, in ``second``): ``entries`` (paths
    or file names) in that order, else every frame that was rendered in both
    passes. A named frame that was not is ``not_found``."""
    in_second = {image_key(Path(i.path)): i for i in second.images if i.box}
    both = [
        (i, in_second[image_key(Path(i.path))])
        for i in first.images
        if i.box and image_key(Path(i.path)) in in_second
    ]
    if entries is None:
        return both

    def find(entry: str) -> Pair | None:
        key = image_key(Path(entry).resolve())
        return next(
            (p for p in both if image_key(Path(p[0].path)) == key or p[0].name.casefold() == entry.casefold()),
            None,
        )

    chosen: list[Pair] = []
    missing: list[str] = []
    for entry in entries:
        found = find(entry)
        if found is None:
            missing.append(entry)
        elif found not in chosen:
            chosen.append(found)
    if missing:
        raise render_error(
            "not_found",
            f"not rendered in both pass {first.index} and pass {second.index}: {', '.join(missing)}",
        )
    return chosen


def cut_out(sheet: Image.Image, frame: SheetImage) -> Image.Image:
    """The frame's thumbnail, cut from its pass's sheet."""
    assert frame.box is not None
    x, y, w, h = frame.box
    return sheet.crop((x, y, x + w, y + h))


def compare_passes(
    session: RenderSession,
    first: int,
    second: int,
    folder: str | None = None,
    images: list[str] | None = None,
    columns: int = DEFAULT_PAIR_COLUMNS,
) -> Comparison:
    """Put the frames of two passes side by side (cut from their sheets) and
    save the result as ``compare-<first>-<second>.jpg`` in the sheets folder
    (``-2``, ``-3`` ... when that exists)."""
    if first == second:
        raise render_error("out_of_range", "first and second must be different passes")
    if not 1 <= columns <= MAX_COLUMNS:
        raise render_error("out_of_range", f"columns must be 1 to {MAX_COLUMNS}")
    sheets = sheets_folder(session, folder)
    one, two = load_pass(sheets, first), load_pass(sheets, second)
    pairs = chosen_frames(images, one, two)
    if not pairs:
        raise render_error("not_found", f"no image was rendered in both pass {first} and pass {second}")

    size = min(one.thumb_size, two.thumb_size)
    cells: list[Cell] = []
    try:
        with Image.open(sheets / Path(one.sheet).name) as left, Image.open(sheets / Path(two.sheet).name) as right:
            for a, b in pairs:
                cells.append(Cell(a.name, side_by_side(cut_out(left, a), cut_out(right, b), size)))
    except OSError as e:
        raise render_error("not_found", f"cannot read the sheets of pass {first} and {second}: {e}") from e
    title = f"{pass_title(one)}  |  {pass_title(two)}"
    grid, _ = compose(cells, columns, size, title, cell_width=2 * size + PAD)

    stem = f"compare-{first:02d}-{second:02d}"
    with session.locked_folder(sheets):
        for attempt in range(1, 1000):
            target = sheets / (stem + (f"-{attempt}" if attempt > 1 else "") + ".jpg")
            try:
                save_new_jpeg(target, grid)
            except FileExistsError:
                continue
            except OSError as e:
                raise render_error("render_failed", f"cannot write {target}: {e}") from e
            break
        else:
            raise render_error("exists", f"every name from {stem}.jpg on is taken in {sheets}")
    return Comparison(
        path=str(target),
        first=first,
        second=second,
        images=[a.name for a, _ in pairs],
        width=grid.width,
        height=grid.height,
    )
