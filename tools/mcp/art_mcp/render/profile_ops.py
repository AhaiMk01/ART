"""Working-profile operations: open_image, reset_profile, get_profile,
edit_profile, describe_adjustments.

Plain functions: the session first, then the tool's arguments; they return
the tool's result model and raise ``RenderError``. ``profile_tools.py`` wraps
them as MCP tools.
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel, ConfigDict, RootModel

from art_mcp.concurrency import image_key
from art_mcp.filmnegative import Estimate, SamplingUnsupported, estimate_for
from art_mcp.metadata import ExiftoolError
from art_mcp.profile import Conflict as EditConflict
from art_mcp.profile import (
    EditBatch,
    EditResult,
    ImageEdit,
    ProfileView,
    UnknownKey,
    check_batch_paths,
    check_groups,
    edit_item,
    edit_requests,
    edit_result,
    edit_warnings,
    failed_edit,
    read_format,
    version_warnings,
)
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.metadata_ops import MetadataSummary, summarize
from art_mcp.render.sampling_ops import sample_working_profile
from art_mcp.render.session import OpenSource, ProfileSource, RenderSession
from art_mcp.render.store import WorkingProfile
from art_mcp.sampling import OmitNone, SpotSamples
from art_mcp.schema import (
    AdjustmentError,
    Adjustments,
    AdjustmentsArg,
    AdjustmentsDescription,
    EditItem,
    RawEdit,
    parse_adjustments,
)
from art_mcp.schema import describe_adjustments as schema_description

Job = TypeVar("Job")
Result = TypeVar("Result")


class OpenedImage(BaseModel):
    path: str
    profile_from: OpenSource
    """Where the working profile came from: the image's `sidecar`, ART's
    `default` profile, or the `profile` file given (over ART's default)."""
    art_version: str
    metadata: MetadataSummary | None = None
    """None when exiftool is unavailable or couldn't read the file; call
    inspect_image for the reason."""


class OpenItem(OmitNone):
    """One image's part of an ``open_image`` call with `paths`."""

    path: str
    """The path as requested."""
    profile_from: OpenSource | None = None
    """As the single-image result; left out when this image failed."""
    metadata: MetadataSummary | None = None
    """As the single-image result (the same `metadata` summary); left out when
    exiftool is unavailable or couldn't read the file, and when this image
    failed."""
    error: str | None = None
    """`<code>: <message>` when this image failed (`not_found`, a render
    failure; the others still open); left out otherwise."""


class OpenBatch(BaseModel):
    items: list[OpenItem]
    """One per requested path, in request order."""
    failed: int


class OpenOutput(RootModel[OpenedImage | OpenBatch]):
    """The output schema of ``open_image``: one image's ``OpenedImage`` (with
    `path`) or an ``OpenBatch`` (with `paths`). It is an object either way,
    which is what a tool's output schema must be."""

    model_config = ConfigDict(json_schema_extra={"type": "object"})


class ResetResult(BaseModel):
    profile_from: ProfileSource


class ResetItem(OmitNone):
    """One image's part of a ``reset_profile`` call with `paths`."""

    path: str
    """The path as requested."""
    profile_from: ProfileSource | None = None
    """As the single-image result; left out when this image failed."""
    error: str | None = None
    """`<code>: <message>` when this image failed (its working profile is then
    as it was and the others still reset); left out otherwise."""


class ResetBatch(BaseModel):
    items: list[ResetItem]
    """One per requested path, in request order."""
    failed: int


class ResetOutput(RootModel[ResetResult | ResetBatch]):
    """The output schema of ``reset_profile``: one image's ``ResetResult`` (with
    `path`) or a ``ResetBatch`` (with `paths`). It is an object either way,
    which is what a tool's output schema must be."""

    model_config = ConfigDict(json_schema_extra={"type": "object"})


def image_file(path: str) -> Path:
    image = Path(path).resolve()
    if not image.is_file():
        raise render_error("not_found", f"{image} does not exist")
    return image


def profile_file(profile: str | None) -> Path | None:
    if profile is None:
        return None
    preset = Path(profile).resolve()
    if not preset.is_file():
        raise render_error("not_found", f"profile {preset} does not exist")
    return preset


def load_image(session: RenderSession, image: Path, preset: Path | None) -> tuple[OpenSource, MetadataSummary | None]:
    """Open ``image`` (``preset``: the ``.arp`` to start from, if any); where
    its working profile came from and its metadata summary."""
    source = session.open(image, preset)
    summary = None
    if session.exiftool is not None:
        try:
            summary = summarize(session.exiftool.read(image))
        except ExiftoolError:
            pass  # opening still works; inspect_image reports the reason
    return source, summary


def open_image(
    session: RenderSession,
    path: str | None = None,
    profile: str | None = None,
    paths: list[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> OpenedImage | OpenBatch:
    """Open the image ``path``, or each image in ``paths`` (exactly one of the
    two), up to ``session.cli.max_processes`` at once; ``profile`` (one
    ``.arp``) is the start of every one. With ``paths`` a problem with one
    image is that image's ``error`` and the others still open; a ``profile``
    that is no file fails the call before any image opens."""
    targets = check_batch_paths(path, paths, render_error)
    if targets is None:
        assert path is not None
        image = image_file(path)
        source, summary = load_image(session, image, profile_file(profile))
        return OpenedImage(path=str(image), profile_from=source, art_version=session.art_version(), metadata=summary)

    preset = profile_file(profile)

    def open_one(target: str) -> OpenItem:
        try:
            source, summary = load_image(session, image_file(target), preset)
        except (RenderError, OSError) as e:
            return OpenItem(path=target, error=failure_text(e))
        return OpenItem(path=target, profile_from=source, metadata=summary)

    items = run_in_pool(session, targets, open_one, on_progress)
    return OpenBatch(items=items, failed=sum(i.error is not None for i in items))


def failure_text(error: RenderError | OSError) -> str:
    """What a failed image of a batch reports as its ``error``."""
    return str(error) if isinstance(error, RenderError) else f"render_failed: {error}"


def reset_profile(
    session: RenderSession,
    to: ProfileSource,
    path: str | None = None,
    paths: list[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> ResetResult | ResetBatch:
    """Reload the working profile of the open image ``path`` from ``to``, or
    that of each open image in ``paths`` (exactly one of the two), up to
    ``session.cli.max_processes`` at once; with ``paths`` a problem with one
    image is that image's ``error`` and the others still reset."""
    targets = check_batch_paths(path, paths, render_error)
    if targets is None:
        assert path is not None
        return ResetResult(profile_from=session.reset(path, to))

    def reset(target: str) -> ResetItem:
        try:
            return ResetItem(path=target, profile_from=session.reset(target, to))
        except (RenderError, OSError) as e:
            return ResetItem(path=target, error=failure_text(e))

    items = run_in_pool(session, targets, reset, on_progress)
    return ResetBatch(items=items, failed=sum(i.error is not None for i in items))


def get_profile(
    session: RenderSession, path: str, groups: list[str] | None = None, changed_only: bool = False
) -> ProfileView:
    with session.image(path) as wp:
        profile = wp.changes.profile
        try:
            if groups is not None:
                check_groups(profile, groups)  # before art-cli is asked for the default
            default = session.default_profile(wp) if changed_only else None
            return read_format(profile, groups=groups, default=default)
        except UnknownKey as e:
            raise render_error("unknown_key", str(e)) from e


def film_estimate(
    session: RenderSession, wp: WorkingProfile, adjustments: Adjustments | None
) -> Estimate | None:
    """ART's current Film Negative medians, sampled with art-cli ``-x`` from
    the working profile as it is before the edit, when the edit needs them."""

    def frame() -> tuple[int, int] | None:
        whole = session.whole_frame(wp)
        return whole.w, whole.h

    def fetch(spots: list[tuple[int, int]], size: int, space: str) -> SpotSamples:
        try:
            return sample_working_profile(session, wp, spots, size, space)
        except RenderError as e:
            if e.code == "unsupported":
                raise SamplingUnsupported(e.message) from e
            raise

    return estimate_for(adjustments, wp.changes.profile, frame, fetch)


def edit_profile(
    session: RenderSession,
    path: str | None = None,
    adjustments: AdjustmentsArg = None,
    raw_edits: list[RawEdit] | None = None,
    full: bool = False,
    paths: list[str] | None = None,
    items: list[EditItem] | None = None,
) -> EditResult | EditBatch:
    """Edit the working profile of the open image ``path``, or the same edit
    of every open image in ``paths``, or each ``items`` entry's own edit of
    its image (exactly one of the three): the single image's change set, or an
    ``EditBatch``. With ``paths`` or ``items`` a problem with one image is that
    image's ``error`` and the others still change, whatever it is (not open, a
    key it lacks, a crop outside its frame); a problem with the call
    (``edit_requests``) fails it before anything changes."""
    requests = edit_requests(path, paths, items, adjustments, raw_edits, full, render_error)
    if requests is None:
        assert path is not None
        return edit_one(session, path, adjustments, raw_edits, full)
    return edit_many(session, requests)


def run_in_pool(
    session: RenderSession,
    jobs: Sequence[Job],
    work: Callable[[Job], Result],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[Result]:
    """``work(job)`` for each of ``jobs``, up to ``session.cli.max_processes``
    at once (what an operation on an image may ask of art-cli), the results in
    the order of ``jobs``; ``on_progress(done, total)`` after each. ``work``
    reports a failure of its own job in its result."""
    results: list[Result | None] = [None] * len(jobs)
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = {pool.submit(work, job): i for i, job in enumerate(jobs)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            done += 1
            if on_progress:
                on_progress(done, len(jobs))
    return cast("list[Result]", results)


def image_identity(path: str) -> str:
    """What names the image at ``path`` for the image locks: two spellings of
    one file have one identity."""
    try:
        return image_key(Path(path).resolve())
    except (OSError, ValueError):
        return path


def edit_many(session: RenderSession, requests: list[EditItem]) -> EditBatch:
    """Each of ``requests``, an edit of one image, up to
    ``session.cli.max_processes`` images at once (an edit may need art-cli to
    measure the frame or sample the picture); each image is edited under its
    own lock, and the requests for one image are applied in request order."""
    by_image: dict[str, list[int]] = {}  # each image's requests, as positions in request order
    for position, request in enumerate(requests):
        by_image.setdefault(image_identity(request.path), []).append(position)

    def edit(request: EditItem) -> ImageEdit:
        try:
            return edit_item(
                request.path, edit_one(session, request.path, request.adjustments, request.raw_edits, False)
            )
        except (RenderError, OSError) as e:
            return failed_edit(request.path, failure_text(e))

    def edit_image(positions: list[int]) -> list[tuple[int, ImageEdit]]:
        return [(position, edit(requests[position])) for position in positions]

    edited = dict(pair for chunk in run_in_pool(session, list(by_image.values()), edit_image) for pair in chunk)
    items = [edited[position] for position in range(len(requests))]
    return EditBatch(items=items, failed=sum(i.error is not None for i in items))


def edit_one(
    session: RenderSession,
    path: str,
    adjustments: AdjustmentsArg,
    raw_edits: list[RawEdit] | None,
    full: bool,
) -> EditResult:
    with session.image(path) as wp:
        try:
            parsed = parse_adjustments(adjustments) if adjustments else None
            if parsed is not None and parsed.crop is not None:
                session.check_crop(wp, parsed.crop)
            outcome = wp.changes.edit(parsed, raw_edits or [], film_estimate(session, wp, parsed))
        except AdjustmentError as e:
            raise render_error(e.code, str(e)) from e
        except UnknownKey as e:
            raise render_error("unknown_key", str(e)) from e
        except EditConflict as e:
            raise render_error("conflict", str(e)) from e
        session.commit(wp)
        warnings = edit_warnings(parsed, wp.changes.profile) + outcome.warnings
        return edit_result(outcome, wp.changes.profile, parsed, raw_edits or [], warnings, full=full)


def describe_adjustments(session: RenderSession) -> AdjustmentsDescription:
    description = schema_description()
    for ppversion in session.open_ppversions():
        for warning in version_warnings(ppversion):
            if warning not in description.warnings:
                description.warnings.append(warning)
    return description
