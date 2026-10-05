"""Sampling operations: sample_spots (art-cli's fork-only ``-x``) and image_stats."""

from art_mcp import artdir, keyfile
from art_mcp.render.artcli import (
    ArtCliError,
    ArtCliTimeout,
    looks_like_help,
    resize_profile,
    spots_args,
    stats_args,
)
from art_mcp.render.errors import render_error
from art_mcp.render.preview_ops import MAX_PREVIEW_SIZE, PREVIEW_SIZE
from art_mcp.render.session import RenderSession
from art_mcp.render.store import WorkingProfile
from art_mcp.sampling import (
    DEFAULT_SIZE,
    UNSUPPORTED_SPOTS,
    ImageStats,
    Spot,
    SpotSamples,
    check_spots,
    check_stats_size,
    parse_spots_output,
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
        return sample_working_profile(session, wp, points, size, space)


def sample_working_profile(
    session: RenderSession,
    wp: WorkingProfile,
    points: list[tuple[int, int]],
    size: int,
    space: str,
) -> SpotSamples:
    """Sample ``points`` of an open image's working profile (call with the
    image's lock held; the request is already checked)."""
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
    session: RenderSession, path: str, max_size: int = PREVIEW_SIZE, histogram: bool = False
) -> ImageStats:
    previews = session.previews
    check_stats_size(max_size, MAX_PREVIEW_SIZE, render_error)
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
                return compute_stats(output, histogram)
            except ValueError as e:
                raise render_error("render_failed", str(e)) from e
        finally:
            for temporary in (profile, resize, output):
                temporary.unlink(missing_ok=True)
