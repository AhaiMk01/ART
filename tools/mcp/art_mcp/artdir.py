"""Locating an ART installation and the files ART keeps per user and per image."""

import os
from collections.abc import Mapping
from pathlib import Path

from art_mcp import keyfile
from art_mcp.keyfile import KeyFile

CLI_NAMES = ("ART-cli.exe", "ART-cli")
EXIFTOOL_NAMES = ("exiftool.exe", "exiftool")


def find_cli(folder: Path) -> Path | None:
    for name in CLI_NAMES:
        if (folder / name).is_file():
            return folder / name
    return None


def find_exiftool(folder: Path) -> Path | None:
    """The exiftool ART ships beside ART-cli."""
    for name in EXIFTOOL_NAMES:
        if (folder / name).is_file():
            return folder / name
    return None


def _version_key(folder: Path) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in folder.name.split("."))
    except ValueError:
        return ()


def find_art_dir(
    flag: str | None, env: Mapping[str, str], program_files: Path | None
) -> Path | None:
    """The folder holding ART-cli: --art-dir, else ART_DIR, else PATH, else the
    newest versioned folder under ``program_files``."""
    for given in (flag, env.get("ART_DIR")):
        if given:
            return Path(given)
    for entry in env.get("PATH", "").split(os.pathsep):
        if entry and find_cli(Path(entry)):
            return Path(entry)
    if program_files is not None and program_files.is_dir():
        installs = [d for d in program_files.iterdir() if find_cli(d)]
        if installs:
            return max(installs, key=_version_key)
    return None


def user_config_dir(env: Mapping[str, str], art_dir: Path | None = None) -> Path:
    """ART's per-user config folder (holds the ``options`` file), by ART's
    own rules (``Options::load``): ``ART_SETTINGS`` if set; else, for an
    install whose own ``options`` says ``MultiUser=false`` (portable),
    ``<art_dir>/mysettings``; else the per-user folder. Builds made with a
    ``CACHE_NAME_SUFFIX`` use ``ART<suffix>``; point ``ART_SETTINGS`` at it."""
    if env.get("ART_SETTINGS"):
        return Path(env["ART_SETTINGS"])
    if art_dir is not None and _read_options(art_dir).get("General", {}).get("MultiUser") == "false":
        return art_dir / "mysettings"
    if "LOCALAPPDATA" in env:
        return Path(env["LOCALAPPDATA"]) / "ART"
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ART"


def _read_options(config_dir: Path) -> KeyFile:
    try:
        return keyfile.loads((config_dir / "options").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def sidecar_path(image: Path, config_dir: Path) -> Path:
    """Where ART keeps ``image``'s sidecar, honouring the user's
    "strip extension" preference (``IMG.arp`` vs ``IMG.ARW.arp``)."""
    profiles = _read_options(config_dir).get("Profiles", {})
    if profiles.get("ParamsSidecarStripExtension") == "true":
        return image.with_suffix(".arp")
    return image.with_name(image.name + ".arp")


FAST_EXPORT_DEFAULT = 1920


def fast_export_box(config_dir: Path) -> int:
    """The long edge of the user's fast-export box (the smaller of its width
    and height; ART's default is 1920x1920). ``art-cli -f`` shrinks anything
    larger into it."""
    section = _read_options(config_dir).get("Fast Export", {})
    sides = []
    # Like ART's Options::load: the current key, else the legacy one.
    for key, legacy in (("fastexport_resize_width", "MaxWidth"), ("fastexport_resize_height", "MaxHeight")):
        try:
            sides.append(int(section.get(key, section.get(legacy, FAST_EXPORT_DEFAULT))))
        except ValueError:
            sides.append(FAST_EXPORT_DEFAULT)
    return min(sides)
