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
    stats_args,
)
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE, Region
from art_mcp.render.session import RenderSession
from art_mcp.render.store import WorkingProfile
from art_mcp.sampling import (
    DEFAULT_SIZE,
    UNSUPPORTED_SPOTS,
    ImageStats,
    RegionTooSmall,
    Spot,
    SpotSamples,
    StatsBatch,
    StatsItem,
    check_spots,
    check_stats_call,
    covering,
    merge_samples,
    parse_spots_output,
    spot_runs,
    stats_detail,
)
from art_mcp.sampling import image_stats as compute_stats


def sample_spots(
    session: RenderSession,
    path: str,
    spots: list[Spot],
    size: int = DEFAULT_SIZE,
    space: str = "working",
) -> SpotSamples:
    points = [(s.x, s.y) for s in spots]
    # Cheap checks first; the frame is measured only for a request that
    # could be valid.
    check_spots(points, size, space, None, render_error)
    with session.image(path) as wp:
        frame = session.whole_frame(wp)
        check_spots(points, size, space, (frame.w, frame.h), render_error)
        return sample_in_runs(session, wp, points, size, space)


def sample_in_runs(
    session: RenderSession,
    wp: WorkingProfile,
    points: list[tuple[int, int]],
    size: int,
    space: str,
) -> SpotSamples:
    """Sample ``points`` (up to ``MAX_SPOTS_PER_CALL``) of an open image's working
    profile in art-cli runs of at most ``MAX_SPOTS`` spots, up to
    ``session.cli.max_processes`` at once, and combine them in request order. A
    failing run fails the whole call with its error, naming the spots it covered
    (the first such run in request order). Call with the image's lock held."""
    runs = spot_runs(len(points))
    if len(runs) == 1:
        return sample_working_profile(session, wp, points, size, space)

    def sample(run: range) -> SpotSamples:
        return sample_working_profile(session, wp, points[run.start : run.stop], size, space)

    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = [pool.submit(sample, run) for run in runs]
        parts = []
        for run, future in zip(runs, futures, strict=True):
            try:
                parts.append(future.result())
            except RenderError as e:
                for pending in futures:
                    pending.cancel()
                raise render_error(e.code, f"{e.message} ({covering(run, len(points))})") from e
    return merge_samples(parts)


def sample_working_profile(
    session: RenderSession,
    wp: WorkingProfile,
    points: list[tuple[int, int]],
    size: int,
    space: str,
) -> SpotSamples:
    """Sample ``points`` (at most ``MAX_SPOTS``) of an open image's working
    profile in one art-cli run (call with the image's lock held; the request
    is already checked)."""
    previews = session.previews
    profile = previews.new_file("profile", ".arp")
    try:
        profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
        try:
            output = session.cli.run(spots_args(wp.image, profile, size, space, points))
        except ArtCliTimeout as e:
            raise render_error("timeout", str(e)) from e
        except ArtCliError as e:
            # A release art-cli doesn't know -x: it prints its help
            # and exits -1.
            if e.returncode == -1 and looks_like_help(str(e)):
                raise render_error("unsupported", UNSUPPORTED_SPOTS) from e
            raise render_error("render_failed", str(e)) from e
    finally:
        profile.unlink(missing_ok=True)
    try:
        result = parse_spots_output(output, size, space)
    except ValueError as e:
        raise render_error("render_failed", str(e)) from e
    if result is None:
        raise render_error("unsupported", UNSUPPORTED_SPOTS)
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
    on_progress: Callable[[int, int], None] | None = None,
) -> ImageStats | StatsBatch:
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
    check_stats_call(path, paths, max_size, MAX_PREVIEW_SIZE, region, bins, detail, render_error)
    level = stats_detail(detail, paths is not None)
    if paths is None:
        assert path is not None  # check_stats_call: one of the two
        return render_stats(session, path, max_size, histogram, region, bins, level)

    items = [StatsItem(path=p) for p in paths]

    def run(item: StatsItem) -> None:
        item.stats = render_stats(session, item.path, max_size, histogram, region, bins, level)

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
                return compute_stats(output, histogram, region, bins, detail)
            except RegionTooSmall as e:
                raise render_error("out_of_range", str(e)) from e
            except ValueError as e:
                raise render_error("render_failed", str(e)) from e
        finally:
            for temporary in (profile, resize, output):
                temporary.unlink(missing_ok=True)
