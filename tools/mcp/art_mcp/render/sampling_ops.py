"""Sampling operations: sample_spots (art-cli's fork-only ``-x``, runs of up to 16
spots) and image_stats."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from art_mcp import artdir, keyfile
from art_mcp.render.artcli import (
    ArtCliError,
    ArtCliTimeout,
    looks_like_help,
    resize_profile,
    spots_args,
    stage_stats_args,
    stats_args,
)
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE, Region
from art_mcp.render.session import RenderSession
from art_mcp.render.store import WorkingProfile
from art_mcp.sampling import (
    DEFAULT_SIZE,
    UNSUPPORTED_SPOTS,
    UNSUPPORTED_STAGE,
    ImageStats,
    RegionTooSmall,
    Spot,
    SpotSamples,
    StageStats,
    StageUnsupported,
    StatsBatch,
    StatsItem,
    check_spots,
    check_stage_stats,
    check_stats_call,
    covering,
    merge_planned,
    parse_spots_output,
    parse_stage_stats_output,
    plan_runs,
    stats_detail,
)
from art_mcp.sampling import image_stats as compute_stats

STAGE_MAX_SIZE = 16384
"""The largest `max_size` for a pipeline stage (art-cli ``-X`` box-downscales; 0 would be full size)."""
DEFAULT_STAGE_BINS = 256


def sample_spots(
    session: RenderSession,
    path: str,
    spots: list[Spot],
    size: int = DEFAULT_SIZE,
    space: str = "working",
    stage: str = "source",
) -> SpotSamples:
    points = [(s.x, s.y) for s in spots]
    own = [s.size for s in spots]
    # Cheap checks first; the frame is measured only for a request that
    # could be valid.
    check_spots(points, size, space, None, render_error, stage, own)
    with session.image(path) as wp:
        frame = session.whole_frame(wp)
        check_spots(points, size, space, (frame.w, frame.h), render_error, stage, own)
        return sample_in_runs(session, wp, points, [size if v is None else v for v in own], space, stage, size)


def sample_in_runs(
    session: RenderSession,
    wp: WorkingProfile,
    points: list[tuple[int, int]],
    sizes: list[int],
    space: str,
    stage: str = "source",
    size: int = DEFAULT_SIZE,
) -> SpotSamples:
    """Sample ``points`` (up to ``MAX_SPOTS_PER_CALL``, each with its own square
    side from ``sizes``) of an open image's working profile in art-cli runs of
    at most ``MAX_SPOTS`` spots of one size, up to ``session.cli.max_processes``
    at once, and combine them in request order. A failing run fails the whole
    call with its error, naming the spots it covered (the first such run in
    plan order). Call with the image's lock held."""
    plan = plan_runs(sizes)

    def sample(run: tuple[int, list[int]]) -> SpotSamples:
        size, indices = run
        return sample_working_profile(session, wp, [points[i] for i in indices], size, space, stage)

    if len(plan) == 1:
        return merge_planned(plan, [sample(plan[0])], len(points), size)
    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = [pool.submit(sample, run) for run in plan]
        parts = []
        for (_, indices), future in zip(plan, futures, strict=True):
            try:
                parts.append(future.result())
            except RenderError as e:
                for pending in futures:
                    pending.cancel()
                raise render_error(e.code, f"{e.message} ({covering(indices, len(points))})") from e
    return merge_planned(plan, parts, len(points), size)


def sample_working_profile(
    session: RenderSession,
    wp: WorkingProfile,
    points: list[tuple[int, int]],
    size: int,
    space: str,
    stage: str = "source",
) -> SpotSamples:
    """Sample ``points`` (at most ``MAX_SPOTS``) of an open image's working
    profile in one art-cli run (call with the image's lock held; the request
    is already checked)."""
    previews = session.previews
    profile = previews.new_file("profile", ".arp")
    try:
        profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
        try:
            output = session.cli.run(spots_args(wp.image, profile, size, space, points, stage))
        except ArtCliTimeout as e:
            raise render_error("timeout", str(e)) from e
        except ArtCliError as e:
            # A release art-cli doesn't know -x: it prints its help
            # and exits -1.
            if e.returncode == -1 and looks_like_help(str(e)):
                raise render_error("unsupported", UNSUPPORTED_SPOTS if stage == "source" else UNSUPPORTED_STAGE) from e
            raise render_error("render_failed", str(e)) from e
    finally:
        profile.unlink(missing_ok=True)
    try:
        result = parse_spots_output(output, size, space, stage)
    except StageUnsupported as e:
        raise render_error("unsupported", UNSUPPORTED_STAGE) from e
    except ValueError as e:
        raise render_error("render_failed", str(e)) from e
    if result is None:
        raise render_error("unsupported", UNSUPPORTED_SPOTS if stage == "source" else UNSUPPORTED_STAGE)
    return result


def image_stats(
    session: RenderSession,
    path: str | None = None,
    paths: list[str] | None = None,
    max_size: int = PREVIEW_SIZE,
    histogram: bool = False,
    region: Region | None = None,
    bins: int | None = None,
    detail: str | None = None,
    lum_min: int | None = None,
    lum_max: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    stage: str = "display",
) -> ImageStats | StageStats | StatsBatch:
    """Statistics of the working profile's whole-image render of ``path``, or
    of every image in ``paths`` (exactly one of them; 1 to 50): then one item
    per image, in request order, each its statistics or its own error (not
    open, a render error, a region too small for that render) while the
    others still come back, up to ``session.cli.max_processes`` renders at
    once; ``on_progress(done, total)`` is called as each finishes. A problem
    with the call as a whole fails it before anything renders. ``region`` is
    cut from each render's PNG (fractions of the image as it shows, the
    working crop applied), not rendered separately. ``detail`` defaults to
    "standard" for one image and "compact" for several."""
    check_stage_stats(stage, bins, detail, lum_min, lum_max, render_error)
    if stage == "display":
        check_stats_call(path, paths, max_size, MAX_PREVIEW_SIZE, region, bins, detail, lum_min, lum_max, render_error)
    else:
        # bins are the stage histogram's (2..1024), not the display's 8..64.
        check_stats_call(path, paths, max_size or 1, STAGE_MAX_SIZE, region, None, None, None, None, render_error)
    level = stats_detail(detail, paths is not None)

    def measure(image: str) -> ImageStats | StageStats:
        if stage == "display":
            return render_stats(session, image, max_size, histogram, region, bins, level, lum_min, lum_max)
        return render_stage_stats(session, image, stage, max_size, region, bins)

    if paths is None:
        assert path is not None  # check_stats_call: one of the two
        return measure(path)

    items = [StatsItem(path=p) for p in paths]

    def run(item: StatsItem) -> None:
        measured = measure(item.path)
        # A pipeline stage's statistics travel as a plain object in the item.
        item.stats = measured.model_dump(mode="json") if isinstance(measured, StageStats) else measured

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = {pool.submit(run, item): item for item in items}
        for future in as_completed(futures):
            try:
                future.result()
            except RenderError as e:
                futures[future].error = str(e)
            except OSError as e:
                futures[future].error = f"render_failed: {e}"
            done += 1
            if on_progress:
                on_progress(done, len(items))
    return StatsBatch(items=items, failed=sum(item.error is not None for item in items))


def render_stats(
    session: RenderSession,
    path: str,
    max_size: int,
    histogram: bool,
    region: Region | None,
    bins: int | None,
    detail: str,
    lum_min: int | None,
    lum_max: int | None,
) -> ImageStats:
    """One image's statistics (the request is already checked)."""
    previews = session.previews
    with session.image(path) as wp:
        fast = max_size <= artdir.fast_export_box(session.config_dir)
        profile = previews.new_file("profile", ".arp")
        resize = previews.new_file("resize", ".arp")
        output = previews.new_file("stats", ".png")
        try:
            profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
            resize.write_text(resize_profile(max_size), encoding="utf-8")
            session.run(stats_args(wp.image, output, profile, resize, fast=fast), output)
            try:
                return compute_stats(output, histogram, region, bins, detail, lum_min, lum_max)
            except RegionTooSmall as e:
                raise render_error("out_of_range", str(e)) from e
            except ValueError as e:
                raise render_error("render_failed", str(e)) from e
        finally:
            for temporary in (profile, resize, output):
                temporary.unlink(missing_ok=True)


def render_stage_stats(
    session: RenderSession,
    path: str,
    stage: str,
    max_size: int,
    region: Region | None,
    bins: int | None,
) -> StageStats:
    """One image's statistics of a film pipeline stage (art-cli ``-X``, no
    output file; the request is already checked)."""
    count = DEFAULT_STAGE_BINS if bins is None else bins
    box = None if region is None else (region.x, region.y, min(region.x + region.w, 1.0), min(region.y + region.h, 1.0))
    with session.image(path) as wp:
        profile = session.previews.new_file("profile", ".arp")
        try:
            profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
            try:
                output = session.cli.run(stage_stats_args(wp.image, profile, stage, count, max_size, box))
            except ArtCliTimeout as e:
                raise render_error("timeout", str(e)) from e
            except ArtCliError as e:
                if e.returncode == -1 and looks_like_help(str(e)):
                    raise render_error("unsupported", UNSUPPORTED_STAGE) from e
                raise render_error("render_failed", str(e)) from e
        finally:
            profile.unlink(missing_ok=True)
    try:
        result = parse_stage_stats_output(output, stage, count)
    except ValueError as e:
        raise render_error("render_failed", str(e)) from e
    if result is None:
        raise render_error("unsupported", UNSUPPORTED_STAGE)
    return result
