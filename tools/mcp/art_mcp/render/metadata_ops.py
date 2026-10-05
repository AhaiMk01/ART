"""Metadata operation: inspect_image, and the summary open_image returns."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import BaseModel

from art_mcp.metadata import ImagesMetadata, Metadata, MetadataProblem, check_paths, read_items, read_metadata
from art_mcp.render.artcli import Rect
from art_mcp.render.errors import RenderError, render_error
from art_mcp.render.session import RenderSession


class MetadataSummary(BaseModel):
    camera: str | None
    """Make and model, e.g. "SONY ILCE-7M3"."""
    lens: str | None
    capture_date: str | None
    width: int | None
    height: int | None


def summarize(m: Metadata) -> MetadataSummary:
    camera = " ".join(part for part in (m.make, m.model) if part)
    return MetadataSummary(
        camera=camera or None,
        lens=m.lens,
        capture_date=m.capture_date,
        width=m.width,
        height=m.height,
    )


def inspect_image(session: RenderSession, path: str, tags: list[str] | None = None) -> Metadata:
    with session.image(path) as wp:
        image = wp.image
        try:
            frame = session.whole_frame(wp)
        except RenderError:
            frame = None  # the metadata is still worth returning
    try:
        metadata = read_metadata(session.exiftool, image, tags or [])
    except MetadataProblem as e:
        raise render_error(e.code, e.message) from e  # type: ignore[arg-type]
    if frame is not None:
        metadata.frame_width, metadata.frame_height = frame.w, frame.h
    return metadata


def inspect_images(
    session: RenderSession,
    paths: list[str],
    tags: list[str] | None = None,
    frame: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> ImagesMetadata:
    """``inspect_image`` for every path in ``paths``, each of which must be
    open, with one exiftool run for all. A problem with the call as a whole
    (the number of paths, a tag name, no exiftool, an exiftool run that fails)
    fails it; a problem with one image is that image's ``error`` and the
    others still come back. The frame size costs art-cli runs the first time
    per image (up to ``session.cli.max_processes`` at once, cached), so it is
    only measured with ``frame``, else it is null. ``on_progress(done, total)``
    is called as each frame is measured."""
    check_paths(paths, render_error)
    targets: list[Path | str] = []
    for path in paths:
        try:
            with session.image(path) as wp:
                targets.append(wp.image)
        except RenderError as e:
            targets.append(str(e))
    try:
        result = read_items(session.exiftool, paths, targets, tags or [])
    except MetadataProblem as e:
        raise render_error(e.code, e.message) from e  # type: ignore[arg-type]
    if frame:
        measured = [(p, i.metadata) for p, i in zip(paths, result.items, strict=True) if i.metadata]
        measure_frames(session, measured, on_progress)
    return result


def measure_frames(
    session: RenderSession, images: list[tuple[str, Metadata]], on_progress: Callable[[int, int], None] | None
) -> None:
    """Set the frame size of each ``(path, metadata)``; left null for a frame
    art-cli can't measure."""

    def measure(path: str) -> Rect | None:
        try:
            with session.image(path) as wp:
                return session.whole_frame(wp)
        except (RenderError, OSError):
            return None  # the metadata is still worth returning

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, session.cli.max_processes)) as pool:
        futures = {pool.submit(measure, path): metadata for path, metadata in images}
        for future in as_completed(futures):
            frame = future.result()
            if frame is not None:
                futures[future].frame_width, futures[future].frame_height = frame.w, frame.h
            done += 1
            if on_progress:
                on_progress(done, len(images))
