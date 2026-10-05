"""Neutral finder: suggest_neutrals (candidate spots for ``sample_spots``)."""

from pathlib import Path

from PIL import Image

from art_mcp import artdir, keyfile
from art_mcp.marks import Mark, draw_marks, save_jpeg
from art_mcp.neutrals import (
    ANALYSIS_SIZE,
    BORDER_CROPPED,
    BORDER_UNCROPPED,
    DEFAULT_COUNT,
    NeutralCandidate,
    NeutralCandidates,
    check_request,
    result_warnings,
    suggest_candidates,
)
from art_mcp.render.artcli import Rect, resize_profile, stats_args
from art_mcp.render.errors import render_error
from art_mcp.render.session import RenderSession
from art_mcp.render.store import WorkingProfile
from art_mcp.sampling import DEFAULT_SIZE


def suggest_neutrals(
    session: RenderSession, path: str, count: int = DEFAULT_COUNT, size: int = DEFAULT_SIZE, preview: bool = False
) -> NeutralCandidates:
    check_request(count, size, render_error)
    with session.image(path) as wp:
        whole = session.whole_frame(wp)
        area = session.frame_of(wp)
        cropped = area != whole
        picture = render_rgb(session, wp)
        try:
            found = suggest_candidates(
                picture,
                (area.x, area.y, area.w, area.h),
                size,
                count,
                BORDER_CROPPED if cropped else BORDER_UNCROPPED,
            )
        except ValueError as e:
            raise render_error("out_of_range", str(e)) from e
        marked = save_marked(session, picture, found.candidates, area, size) if preview else None
    return NeutralCandidates(
        area=[area.x, area.y, area.w, area.h],
        size=size,
        cell=found.cell,
        candidates=found.candidates,
        warnings=result_warnings(cropped=cropped, found=len(found.candidates), count=count),
        preview_path=str(marked) if marked else None,
    )


def save_marked(
    session: RenderSession, picture: Image.Image, candidates: list[NeutralCandidate], area: Rect, size: int
) -> Path:
    """``picture`` (the analysed rendering of ``area``) with the sampling
    square of every candidate marked, numbered 1..n in the order of
    ``candidates``, as a new JPEG in the previews folder."""
    draw_marks(picture, [Mark(x=c.x, y=c.y, size=size) for c in candidates], area)
    jpeg = session.previews.new_file("neutrals", ".jpg")
    try:
        save_jpeg(picture, jpeg)
    except OSError as e:
        jpeg.unlink(missing_ok=True)
        raise render_error("render_failed", f"cannot write the marked picture: {e}") from e
    return jpeg


def render_rgb(session: RenderSession, wp: WorkingProfile) -> Image.Image:
    """The working profile as an 8-bit picture ``ANALYSIS_SIZE`` px on its long
    edge, crop applied (what a whole-image preview shows; the same render as
    ``image_stats``). Call with the image's lock held."""
    previews = session.previews
    fast = ANALYSIS_SIZE <= artdir.fast_export_box(session.config_dir)
    profile = previews.new_file("profile", ".arp")
    resize = previews.new_file("resize", ".arp")
    output = previews.new_file("neutrals", ".png")
    try:
        profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
        resize.write_text(resize_profile(ANALYSIS_SIZE), encoding="utf-8")
        session.run(stats_args(wp.image, output, profile, resize, fast=fast), output)
        try:
            with Image.open(output) as opened:
                return opened.convert("RGB")
        except (OSError, ValueError) as e:
            raise render_error("render_failed", f"cannot read the rendered image: {e}") from e
    finally:
        for temporary in (profile, resize, output):
            temporary.unlink(missing_ok=True)
