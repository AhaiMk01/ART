"""Locating an ART installation and the files ART keeps per user and per image."""

import os
from collections.abc import Mapping
from pathlib import Path

from art_mcp import keyfile
from art_mcp.keyfile import KeyFile

CLI_NAMES = ("ART-cli.exe", "ART-cli")


def find_cli(folder: Path) -> Path | None:
    for name in CLI_NAMES:
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


def user_config_dir(env: Mapping[str, str]) -> Path:
    """ART's per-user config folder (holds the ``options`` file)."""
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
