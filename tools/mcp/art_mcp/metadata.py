"""Reading image metadata with the exiftool that ships with ART."""

import json
import re
import subprocess
import sys
from collections.abc import Sequence
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
    iso: int | None = None
    shutter_seconds: float | None = None
    aperture: float | None = Field(default=None, description="f-number")
    focal_length_mm: float | None = None
    capture_date: str | None = Field(
        default=None, description="local time as recorded, ISO 8601 without zone"
    )
    width: int | None = None
    height: int | None = None
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
        for tag in tags:
            if not TAG_NAME.fullmatch(tag):
                raise InvalidTag(f"not an exiftool tag name: {tag!r}")
        # Everything goes through stdin as an argument file: on Windows a
        # command-line path with non-ASCII characters reaches exiftool mangled.
        if "\n" in str(image):
            raise ExiftoolError(f"cannot read a path containing a newline: {image!r}")
        lines = ["-charset", "exiftool=utf8", "-charset", "filename=utf8", "-j", "-n"]
        lines += [f"-{t}" for t in (*FIXED_TAGS, *tags)]
        lines += ["--", str(image)]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            done = subprocess.run(
                [*self.command, "-@", "-"],
                input="\n".join(lines).encode("utf-8"),
                capture_output=True,
                timeout=self.timeout,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired as e:
            raise ExiftoolTimeout(f"exiftool timed out after {self.timeout:g} s") from e
        except OSError as e:
            raise ExiftoolError(f"cannot start exiftool: {e}") from e
        stdout = done.stdout.decode("utf-8", errors="replace")
        if done.returncode != 0:
            stderr = done.stderr.decode("utf-8", errors="replace")
            raise ExiftoolError(f"exiftool exited with {done.returncode}: {(stdout + stderr).strip()}")
        try:
            return parse(json.loads(stdout)[0])
        except (ValueError, LookupError, TypeError, AttributeError) as e:
            raise ExiftoolError(f"unexpected exiftool output: {stdout.strip()[:200]!r}") from e


class MetadataProblem(Exception):
    """Why metadata couldn't be read, as a tool error code and message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def read_metadata(exiftool: "Exiftool | None", image: Path, tags: list[str]) -> Metadata:
    """``exiftool.read`` for both servers, with failures as MetadataProblem:
    metadata_unavailable, invalid_tag, timeout or metadata_failed."""
    if exiftool is None:
        raise MetadataProblem("metadata_unavailable", "exiftool was not found beside ART-cli")
    try:
        return exiftool.read(image, tags)
    except InvalidTag as e:
        raise MetadataProblem("invalid_tag", str(e)) from e
    except ExiftoolTimeout as e:
        raise MetadataProblem("timeout", str(e)) from e
    except ExiftoolError as e:
        raise MetadataProblem("metadata_failed", str(e)) from e
