"""Running ART's command-line renderer, art-cli.

Argument builders are pure so they can be checked without ART installed.
Every run passes ``-Y`` (the server writes only into its own temp folder) and
``-a`` (so the user's "parsed extensions" preference can't skip an input).
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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


def preview_args(image: Path, output: Path, profile: Path, resize: Path) -> list[str]:
    """A fast JPEG render of ``profile`` with the ``resize`` layer on top."""
    return [
        "-o", str(output), "-f", "-Y", "-a",
        "-p", str(profile), "-p", str(resize),
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


class ArtCliError(Exception):
    """art-cli failed or produced no output."""


class ArtCliTimeout(ArtCliError):
    """art-cli ran past its timeout and was killed."""


@dataclass(frozen=True)
class ArtCli:
    command: tuple[str, ...]
    """How to start art-cli: normally just its path; tests substitute a fake."""

    timeout: float = 60.0

    def run(self, args: list[str]) -> str:
        """Run art-cli and return its combined output."""
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            done = subprocess.run(
                [*self.command, *args],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                creationflags=flags,
            )
        except subprocess.TimeoutExpired as e:
            # subprocess.run has already killed the process.
            raise ArtCliTimeout(f"art-cli timed out after {self.timeout:g} s") from e
        except OSError as e:
            raise ArtCliError(f"cannot start art-cli: {e}") from e
        output = done.stdout + done.stderr
        if done.returncode != 0:
            raise ArtCliError(f"art-cli exited with {done.returncode}: {output.strip()}")
        return output

    def version(self) -> str:
        """``"1.26.9"`` from ``art-cli -v`` (``ART, version 1.26.9, command line.``)."""
        text = self.run(["-v"])
        if "version" not in text:
            raise ArtCliError(f"unexpected art-cli -v output: {text.strip()!r}")
        return text.split("version", 1)[1].split(",", 1)[0].strip()
