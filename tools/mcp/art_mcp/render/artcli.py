"""Running ART's command-line renderer, art-cli.

Argument builders are pure so they can be checked without ART installed.
Every run passes ``-Y`` (the server writes only into its own temp folder) and
``-a`` (so the user's "parsed extensions" preference can't skip an input).
"""

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from art_mcp import keyfile

JPEG_QUALITY = 85

EXPORT_BIT_DEPTHS = {
    "jpeg": ("8",),
    "png": ("8", "16"),
    "tiff": ("8", "16", "16f", "32"),
}
"""Export formats and the bit depths art-cli takes for each."""


def resolve_profile_args(image: Path, output: Path, sidecar: Path | None) -> list[str]:
    """A fast render whose only purpose is the ``.arp`` that ``-O`` writes
    beside ``output``: the image's complete processing profile, built from its
    sidecar or, without one, from ART's default profile. No other layer is
    added, so nothing leaks into that profile."""
    base = ["-p", str(sidecar)] if sidecar else ["-d"]
    return ["-O", str(output), "-f", "-Y", "-a", *base, "-c", str(image)]


def preview_args(
    image: Path,
    output: Path,
    profile: Path,
    resize: Path,
    *,
    fast: bool,
    crop: Path | None = None,
) -> list[str]:
    """A JPEG render of ``profile`` with the optional ``crop`` layer (a region
    preview) and then the ``resize`` layer on top. ``fast`` adds ``-f``."""
    layers = [profile, *([crop] if crop else []), resize]
    return [
        "-o", str(output), *(["-f"] if fast else []), "-Y", "-a",
        *(arg for layer in layers for arg in ("-p", str(layer))),
        f"-j{JPEG_QUALITY}", "-c", str(image),
    ]  # fmt: skip


def export_args(
    image: Path,
    output: Path,
    profile: Path,
    format: str,
    quality: int | None,
    bit_depth: str | None,
    write_profile: bool,
) -> list[str]:
    """A full-size render of ``profile`` (no ``-f``). With ``write_profile``,
    ``-O`` also writes ``<output>.arp``. Raises ValueError for a format,
    quality or bit depth art-cli doesn't take."""
    if format not in EXPORT_BIT_DEPTHS:
        raise ValueError(f"format must be one of {', '.join(EXPORT_BIT_DEPTHS)}, not {format!r}")
    if quality is not None and format != "jpeg":
        raise ValueError(f"quality applies to jpeg only, not {format}")
    if quality is not None and not 1 <= quality <= 100:
        raise ValueError(f"quality must be 1..100, not {quality}")
    allowed = EXPORT_BIT_DEPTHS[format]
    if bit_depth is not None and bit_depth not in allowed:
        raise ValueError(f"bit_depth for {format} must be one of {', '.join(allowed)}, not {bit_depth!r}")

    if format == "jpeg":
        format_flags = [f"-j{quality}" if quality is not None else "-j"]
    else:
        format_flags = ["-t" if format == "tiff" else "-n"]
    if bit_depth is not None:
        format_flags.append(f"-b{bit_depth}")
    return [
        "-O" if write_profile else "-o", str(output), "-Y", "-a",
        "-p", str(profile), *format_flags, "-c", str(image),
    ]  # fmt: skip


def resize_profile(long_edge: int) -> str:
    """A partial profile fitting the image into a ``long_edge`` box."""
    return keyfile.dumps({
        "Resize": {
            "Enabled": "true",
            "DataSpecified": "3",
            "Width": str(long_edge),
            "Height": str(long_edge),
        }
    })  # fmt: skip


EXIT_MEANINGS = {
    -3: "bad arguments: art-cli rejected the command line",
    -2: "could not load or save a file (or load ART's options)",
    -1: "unknown option or help requested",
    1: "stray argument on the command line",
    2: "no input, or the input's extension was skipped",
}


def exit_code(returncode: int) -> int:
    """Windows reports art-cli's ``-3`` as 4294967293; fold it back."""
    return returncode - 2**32 if returncode >= 2**31 else returncode


def describe_exit(returncode: int, output: str) -> str:
    code = exit_code(returncode)
    meaning = EXIT_MEANINGS.get(code)
    text = f"art-cli exited with {code}"
    if meaning:
        text += f" ({meaning})"
    return f"{text}: {output.strip()}" if output.strip() else text


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


def crop_profile(rect: Rect) -> str:
    """A partial profile cropping to ``rect``, in the pixels of the frame
    ART's ``[Crop]`` group addresses (see ``frame_probe_layer``)."""
    return keyfile.dumps({
        "Crop": {
            "Enabled": "true",
            "X": str(rect.x),
            "Y": str(rect.y),
            "W": str(rect.w),
            "H": str(rect.h),
            "FixedRatio": "false",
        }
    })  # fmt: skip


def region_rect(frame: Rect, *, x: float, y: float, w: float, h: float) -> Rect:
    """The pixel rectangle of a region given as fractions of ``frame``,
    always at least 1x1 and inside the frame."""

    def span(start: float, length: float, extent: int) -> tuple[int, int]:
        first = min(round(start * extent), extent - 1)
        last = min(round((start + length) * extent), extent)
        return first, max(1, last - first)

    left, width = span(x, w, frame.w)
    top, height = span(y, h, frame.h)
    return Rect(frame.x + left, frame.y + top, width, height)


FRAME_GROUPS = ("Coarse Transformation", "RAW")
"""Profile groups (by name or prefix) that change the size of the frame
``[Crop]`` addresses: coarse rotation/flip and the raw border."""


def frame_probe_layer(profile: keyfile.KeyFile, *, strip: Literal["row", "column"]) -> str:
    """A partial profile that renders a 1-pixel strip of the whole frame: the
    frame-defining groups of ``profile``, a crop far larger than any image
    (ART clamps it to the frame, so the strip's length is the frame's width
    or height) and no resize."""
    groups = {
        name: values
        for name, values in profile.items()
        if any(name == g or name.startswith(g + " ") for g in FRAME_GROUPS)
    }
    huge = "1000000"
    groups["Crop"] = {
        "Enabled": "true", "X": "0", "Y": "0",
        "W": huge if strip == "row" else "1",
        "H": "1" if strip == "row" else huge,
        "FixedRatio": "false",
    }  # fmt: skip
    groups["Resize"] = {"Enabled": "false"}
    return keyfile.dumps(groups)


def probe_args(image: Path, output: Path, layer: Path) -> list[str]:
    """Render ``layer`` (a ``frame_probe_layer``) to a PNG, whose header
    holds the strip's size. No ``-d``/sidecar: only ``layer`` applies."""
    return ["-o", str(output), "-n", "-Y", "-a", "-p", str(layer), "-c", str(image)]


def png_size(path: Path) -> tuple[int, int]:
    """(width, height) from a PNG's IHDR chunk."""
    with path.open("rb") as f:
        header = f.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ArtCliError(f"{path} is not a PNG")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


class ArtCliError(Exception):
    """art-cli failed or produced no output."""


class ArtCliTimeout(ArtCliError):
    """art-cli ran past its timeout and was killed."""


@dataclass(frozen=True)
class ArtCli:
    command: tuple[str, ...]
    """How to start art-cli: normally just its path; tests substitute a fake."""

    timeout: float = 60.0
    """Default limit on one run: the preview timeout."""

    export_timeout: float = 120.0
    """Limit for exports: pass it as ``run(..., timeout=cli.export_timeout)``."""

    max_processes: int = 2
    """How many art-cli processes may run at once through this instance."""

    _slots: threading.Semaphore = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_slots", threading.Semaphore(self.max_processes))

    def run(self, args: list[str], timeout: float | None = None) -> str:
        """Run art-cli and return its combined output. ``timeout`` (seconds)
        overrides the instance's for this call."""
        limit = self.timeout if timeout is None else timeout
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            with self._slots:  # waiting for a slot doesn't count against the timeout
                done = subprocess.run(
                    [*self.command, *args],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=limit,
                    creationflags=flags,
                )
        except subprocess.TimeoutExpired as e:
            # subprocess.run has already killed the process.
            raise ArtCliTimeout(f"art-cli timed out after {limit:g} s") from e
        except OSError as e:
            raise ArtCliError(f"cannot start art-cli: {e}") from e
        output = done.stdout + done.stderr
        if done.returncode != 0:
            raise ArtCliError(describe_exit(done.returncode, output))
        return output

    def version(self) -> str:
        """``"1.26.9"`` from ``art-cli -v`` (``ART, version 1.26.9, command line.``)."""
        text = self.run(["-v"])
        if "version" not in text:
            raise ArtCliError(f"unexpected art-cli -v output: {text.strip()!r}")
        return text.split("version", 1)[1].split(",", 1)[0].strip()
