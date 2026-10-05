"""Reading image metadata with the exiftool that ships with ART."""

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# A tag name, optionally group-qualified ("EXIF:ISO", "XMP-dc:Title") or with
# wildcards; never anything exiftool could take for an option or a file.
TAG_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_:*-]*")

FIXED_TAGS = (
    "Make", "Model", "LensModel", "Lens", "ISO", "ExposureTime", "FNumber",
    "FocalLength", "DateTimeOriginal", "ImageWidth", "ImageHeight", "Orientation",
)  # fmt: skip


class ExiftoolError(Exception):
    """exiftool failed or produced unusable output."""


class ExiftoolTimeout(ExiftoolError):
    """exiftool ran past its timeout and was killed."""


class InvalidTag(ValueError):
    """A requested tag name that isn't a plain exiftool tag name."""


class Metadata(BaseModel):
    """The fixed fields, None where the file has no (usable) value."""

    make: str | None = None
    model: str | None = None
    lens: str | None = None
    iso: int | None = Field(
        default=None,
        description="as recorded by the camera that took THIS file; for a re-photographed original (a negative or "
        "slide on a light table, a print) the digitising camera, not the original's own exposure",
    )
    shutter_seconds: float | None = Field(
        default=None,
        description="as recorded by the camera that took THIS file; for a re-photographed original (a negative or "
        "slide on a light table, a print) the digitising camera, not the original's own exposure",
    )
    aperture: float | None = Field(
        default=None,
        description="f-number, as recorded by the camera that took THIS file; for a re-photographed original (a "
        "negative or slide on a light table, a print) the digitising camera, not the original's own exposure; "
        "null for a manual lens (the body records 0)",
    )
    focal_length_mm: float | None = Field(
        default=None,
        description="as recorded by the camera that took THIS file; for a re-photographed original (a negative or "
        "slide on a light table, a print) the digitising camera, not the original's own exposure; null for a "
        "manual lens",
    )
    capture_date: str | None = Field(
        default=None, description="local time as recorded, ISO 8601 without zone"
    )
    width: int | None = Field(
        default=None,
        description="pixel width the file records (EXIF); NOT the space crop coordinates are in: see frame_width",
    )
    height: int | None = Field(
        default=None,
        description="pixel height the file records (EXIF); NOT the space crop coordinates are in: see frame_height",
    )
    frame_width: int | None = Field(
        default=None,
        description="width of the frame ART works in, after coarse rotation and the raw border (a Sony ARW "
        "records 6048 but ART's frame is 6016): the space `crop` and `sample_spots` coordinates are in; "
        "null when ART can't tell",
    )
    frame_height: int | None = Field(
        default=None,
        description="height of the frame ART works in (see frame_width); null when ART can't tell",
    )
    orientation: int | None = Field(default=None, description="EXIF orientation, 1-8")
    tags: dict[str, Any] = {}
    """The extra tags that were asked for and found, by exiftool tag name."""


def _date(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"^(\d{4}):(\d\d):(\d\d)[ T]", r"\1-\2-\3T", value.strip())


def _text(value: Any) -> str | None:
    """A string value, or None for blank/placeholder ("----" is what Sony
    bodies record for a lens they can't identify)."""
    if not isinstance(value, str) or not value.strip(" -"):
        return None
    return value.strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number == int(number) else None


def _positive(value: Any) -> float | None:
    """Cameras record 0 for "unknown" aperture and focal length."""
    number = _number(value)
    return number if number is not None and number > 0 else None


def parse(record: dict[str, Any]) -> Metadata:
    """A ``Metadata`` from one ``exiftool -j -n`` record."""
    return Metadata(
        make=_text(record.get("Make")),
        model=_text(record.get("Model")),
        lens=_text(record.get("LensModel")) or _text(record.get("Lens")),
        iso=_integer(record.get("ISO")),
        shutter_seconds=_number(record.get("ExposureTime")),
        aperture=_positive(record.get("FNumber")),
        focal_length_mm=_positive(record.get("FocalLength")),
        capture_date=_date(record.get("DateTimeOriginal")),
        width=_integer(record.get("ImageWidth")),
        height=_integer(record.get("ImageHeight")),
        orientation=_integer(record.get("Orientation")),
        tags={k: v for k, v in record.items() if k != "SourceFile" and k not in FIXED_TAGS},
    )


@dataclass(frozen=True)
class Exiftool:
    command: tuple[str, ...]
    """How to start exiftool: normally just its path; tests substitute a fake."""

    timeout: float = 30.0

    def read(self, image: Path, tags: Sequence[str] = ()) -> Metadata:
        """The fixed fields of ``image`` plus the named extra ``tags`` that it
        has."""
        check_tags(tags)
        if "\n" in str(image):
            raise ExiftoolError(f"cannot read a path containing a newline: {image!r}")
        status, stdout, stderr = self._run([image], tags)
        if status != 0:
            raise ExiftoolError(f"exiftool exited with {status}: {(stdout + stderr).strip()}")
        try:
            return parse(json.loads(stdout)[0])
        except (ValueError, LookupError, TypeError, AttributeError) as e:
            raise ExiftoolError(f"unexpected exiftool output: {stdout.strip()[:200]!r}") from e

    def read_many(self, images: Sequence[Path], tags: Sequence[str] = ()) -> list[Metadata | ExiftoolError]:
        """``read`` for every image in ``images`` with ONE exiftool run: per
        image, its ``Metadata`` or the ``ExiftoolError`` that is that image's
        alone (not a file, no record, an error exiftool names for it) while
        the others still read. An invalid tag, an exiftool that can't start or
        times out, or output that isn't JSON fails the whole call by raising."""
        check_tags(tags)
        results: list[Metadata | ExiftoolError | None] = [None] * len(images)
        to_read: dict[str, Path] = {}  # once per file, however it is spelled
        for i, image in enumerate(images):
            if "\n" in str(image):
                results[i] = ExiftoolError(f"cannot read a path containing a newline: {image!r}")
            elif not image.is_file():
                results[i] = ExiftoolError(f"File not found - {image}")
            else:
                to_read.setdefault(_key(image), image)
        read = self._read_files(list(to_read.values()), tags) if to_read else {}
        for i, image in enumerate(images):
            if results[i] is None:
                found = read[_key(image)]
                results[i] = found.model_copy(deep=True) if isinstance(found, Metadata) else found
        return [r for r in results if r is not None]

    def _read_files(self, files: Sequence[Path], tags: Sequence[str]) -> dict[str, Metadata | ExiftoolError]:
        """One run over existing ``files``, by ``_key``."""
        status, stdout, stderr = self._run(files, tags)
        records: dict[str, Any] = {}
        # Like exiftool, which exits 1 when any file failed, its other
        # records still printed (none at all when every file failed).
        if stdout.strip() or status == 0:
            try:
                records = {_key(r["SourceFile"]): r for r in json.loads(stdout)}
            except (ValueError, LookupError, TypeError, AttributeError) as e:
                raise ExiftoolError(f"unexpected exiftool output: {stdout.strip()[:200]!r}") from e
        errors = _errors_by_file(stderr, files)
        results: dict[str, Metadata | ExiftoolError] = {}
        for file in files:
            key = _key(file)
            if key in errors:
                results[key] = ExiftoolError(errors[key])
            elif key in records:
                results[key] = parse(records[key])
            else:
                results[key] = ExiftoolError(f"exiftool exited with {status} and read nothing: {stderr.strip()}")
        return results

    def _run(self, images: Sequence[Path], tags: Sequence[str]) -> tuple[int, str, str]:
        """One exiftool run over ``images``: its exit status, stdout and
        stderr."""
        # Everything goes through stdin as an argument file: on Windows a
        # command-line path with non-ASCII characters reaches exiftool mangled.
        lines = ["-charset", "exiftool=utf8", "-charset", "filename=utf8", "-j", "-n"]
        lines += [f"-{t}" for t in (*FIXED_TAGS, *tags)]
        lines += ["--", *(str(image) for image in images)]
        timeout = self.timeout + 0.5 * max(0, len(images) - 1)  # more files, more time
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            done = subprocess.run(
                [*self.command, "-@", "-"],
                input="\n".join(lines).encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired as e:
            raise ExiftoolTimeout(f"exiftool timed out after {timeout:g} s") from e
        except OSError as e:
            raise ExiftoolError(f"cannot start exiftool: {e}") from e
        return (
            done.returncode,
            done.stdout.decode("utf-8", errors="replace"),
            done.stderr.decode("utf-8", errors="replace"),
        )


def check_tags(tags: Sequence[str]) -> None:
    for tag in tags:
        if not TAG_NAME.fullmatch(tag):
            raise InvalidTag(f"not an exiftool tag name: {tag!r}")


def _key(path: str | Path) -> str:
    """A file's identity across spellings: exiftool echoes a path in
    ``SourceFile`` with forward slashes."""
    return os.path.normcase(os.path.normpath(str(path)))


def _errors_by_file(stderr: str, files: Sequence[Path]) -> dict[str, str]:
    """The ``Error: <what> - <file>`` lines of exiftool's stderr, by file
    (``<what> - <file>``); a file it names nothing for is left out."""
    lines = [line[len("Error: ") :] for line in stderr.splitlines() if line.startswith("Error: ")]
    named: dict[str, str] = {}
    for file in files:
        shown = str(file).replace("\\", "/")
        for line in lines:
            if line.endswith(f" - {shown}"):
                named[_key(file)] = line
                break
    return named


class MetadataProblem(Exception):
    """Why metadata couldn't be read, as a tool error code and message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@contextmanager
def _as_problems(exiftool: "Exiftool | None") -> Iterator[Exiftool]:
    """The ``exiftool`` to use, its failures raised as MetadataProblem:
    metadata_unavailable, invalid_tag, timeout or metadata_failed."""
    if exiftool is None:
        raise MetadataProblem(
            "metadata_unavailable", "exiftool was not found (beside ART-cli, on PATH, or in an ART install)"
        )
    try:
        yield exiftool
    except InvalidTag as e:
        raise MetadataProblem("invalid_tag", str(e)) from e
    except ExiftoolTimeout as e:
        raise MetadataProblem("timeout", str(e)) from e
    except ExiftoolError as e:
        raise MetadataProblem("metadata_failed", str(e)) from e


def read_metadata(exiftool: "Exiftool | None", image: Path, tags: list[str]) -> Metadata:
    """``exiftool.read`` for both servers, with failures as MetadataProblem:
    metadata_unavailable, invalid_tag, timeout or metadata_failed."""
    with _as_problems(exiftool) as tool:
        return tool.read(image, tags)


MAX_IMAGES = 100
"""The most images one ``inspect_images`` call takes."""


class ImageMetadata(BaseModel):
    path: str
    """The path as requested."""
    metadata: Metadata | None
    """As ``inspect_image`` returns it; null when this image failed."""
    error: str | None
    """`<code>: <message>` when this image failed; the others still come back."""


class ImagesMetadata(BaseModel):
    items: list[ImageMetadata]
    """One per requested path, in request order."""
    failed: int


def check_paths(paths: Sequence[str], error: Callable[[Any, str], Exception]) -> None:
    """Raise ``error("out_of_range", ...)`` unless ``paths`` holds 1 to
    ``MAX_IMAGES`` paths."""
    if not paths:
        raise error("out_of_range", "paths is empty")
    if len(paths) > MAX_IMAGES:
        raise error("out_of_range", f"paths has {len(paths)} entries; the most one call takes is {MAX_IMAGES}")


def read_items(
    exiftool: "Exiftool | None", paths: Sequence[str], targets: Sequence[Path | str], tags: list[str]
) -> ImagesMetadata:
    """``inspect_images`` for both servers, up to the frame size: ``targets[i]``
    is the file to read for ``paths[i]``, or the error text (`<code>:
    <message>`) that image already has. exiftool runs once for all the files.
    What fails the whole call (metadata_unavailable, invalid_tag, timeout, an
    unusable exiftool run) is raised as MetadataProblem; a problem with one
    image is that image's ``error``."""
    with _as_problems(exiftool) as tool:
        read = iter(tool.read_many([t for t in targets if isinstance(t, Path)], tags))
    items = []
    for path, target in zip(paths, targets, strict=True):
        if isinstance(target, str):
            items.append(ImageMetadata(path=path, metadata=None, error=target))
            continue
        found = next(read)
        if isinstance(found, Metadata):
            items.append(ImageMetadata(path=path, metadata=found, error=None))
        else:
            items.append(ImageMetadata(path=path, metadata=None, error=f"metadata_failed: {found}"))
    return ImagesMetadata(items=items, failed=sum(i.error is not None for i in items))
