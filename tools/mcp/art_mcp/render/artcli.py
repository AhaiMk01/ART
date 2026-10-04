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
