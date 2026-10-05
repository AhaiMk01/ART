"""Locating an ART installation and the files ART keeps per user and per image."""

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from art_mcp import keyfile
from art_mcp.keyfile import KeyFile

Environ = Mapping[str, str]

# Binary names. ART's build names the executable ``ART-cli`` (``OUTPUT_NAME``
# in src/gui/CMakeLists.txt; ``art-cli`` is only the CMake target); the
# lowercase spelling is accepted on case-sensitive systems for hand-made links.
CLI_NAMES = {
    "windows": ("ART-cli.exe", "ART-cli"),
    "macos": ("ART-cli", "art-cli"),
    "linux": ("ART-cli", "art-cli"),
}
EXIFTOOL_NAMES = {
    "windows": ("exiftool.exe", "exiftool"),
    "macos": ("exiftool",),
    "linux": ("exiftool",),
}
# ART's Linux bundle (tools/linux/bundle_ART.py) keeps exiftool in lib/exiftool
# of the install folder, next to the ART-cli wrapper script.
BUNDLED_EXIFTOOL_SUBDIR = Path("lib") / "exiftool"


def host_system() -> str:
    """``windows``, ``macos`` or ``linux`` (any other Unix) for this machine."""
    if sys.platform in ("win32", "cygwin"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def windows_install_root(env: Environ) -> Path | None:
    """The folder whose versioned subfolders hold Windows installs
    (``%ProgramFiles%\\ART``), or None on other systems."""
    if host_system() != "windows":
        return None
    return Path(env.get("ProgramFiles", r"C:\Program Files")) / "ART"


def find_cli(folder: Path, system: str | None = None) -> Path | None:
    for name in CLI_NAMES[system or host_system()]:
        if (folder / name).is_file():
            return folder / name
    return None


def find_exiftool(folder: Path, system: str | None = None) -> Path | None:
    """The exiftool in ``folder`` (ART's Windows release ships one beside
    ART-cli, its Linux bundle one under ``lib/exiftool``)."""
    system = system or host_system()
    for name in EXIFTOOL_NAMES[system]:
        if (folder / name).is_file():
            return folder / name
    if system != "windows":
        for name in EXIFTOOL_NAMES[system]:
            if (folder / BUNDLED_EXIFTOOL_SUBDIR / name).is_file():
                return folder / BUNDLED_EXIFTOOL_SUBDIR / name
    return None


def _version_key(folder: Path) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in folder.name.split("."))
    except ValueError:
        return ()


def _loose_version_key(folder: Path) -> tuple[tuple[int, ...], str]:
    """For ``ART``, ``ART-1.26.9``, ``ART_1.26.10``: the numbers in the name."""
    return tuple(int(n) for n in re.findall(r"\d+", folder.name)), folder.name


def _home(env: Environ, home: Path | None) -> Path:
    return home or Path(env.get("HOME") or Path.home())


def standard_dirs(system: str, env: Environ, home: Path | None = None, root: Path | None = None) -> list[Path]:
    """Where ART (and exiftool) are usually installed outside PATH, most
    preferred first. ``root`` stands in for ``/`` so tests need no real
    install. Windows has none (see ``windows_install_root``).

    macOS: ``ART.app`` in /Applications and ~/Applications. The bundle script
    (tools/osx/macosx_bundle.sh) puts ART-cli in ``Contents/Frameworks`` (a
    ``cmake install`` bundle has it in ``Contents/MacOS``). Exiftool comes from
    its own pkg (/usr/local/bin), Homebrew or MacPorts, not from the bundle.

    Linux: the usual prefixes, then ``/opt/ART*`` bundles (newest first)."""
    base = root if root is not None else Path("/")
    user = _home(env, home)
    if system == "macos":
        dirs: list[Path] = []
        for apps in (base / "Applications", user / "Applications"):
            bundle = apps / "ART.app" / "Contents"
            dirs += [bundle / "Frameworks", bundle / "MacOS"]
        return dirs + [
            base / "usr" / "local" / "bin",
            base / "opt" / "homebrew" / "bin",
            base / "opt" / "local" / "bin",
            base / "usr" / "bin",
        ]
    if system == "linux":
        dirs = [base / "usr" / "local" / "bin", base / "usr" / "bin", user / ".local" / "bin"]
        opt = base / "opt"
        if opt.is_dir():
            bundles = [d for d in opt.glob("ART*") if d.is_dir()]
            dirs += sorted(bundles, key=_loose_version_key, reverse=True)
        return dirs
    return []


def _path_dirs(env: Environ) -> list[Path]:
    return [Path(entry) for entry in env.get("PATH", "").split(os.pathsep) if entry]


def find_art_dir(
    flag: str | None,
    env: Environ,
    program_files: Path | None,
    *,
    system: str | None = None,
    home: Path | None = None,
    root: Path | None = None,
) -> Path | None:
    """The folder holding ART-cli: --art-dir, else ART_DIR, else PATH, else
    the system's usual install locations (``standard_dirs``; on Windows the
    newest versioned folder under ``program_files``)."""
    system = system or host_system()
    for given in (flag, env.get("ART_DIR")):
        if given:
            return Path(given)
    for entry in _path_dirs(env):
        if find_cli(entry, system):
            return entry
    if program_files is not None and program_files.is_dir():
        installs = [d for d in program_files.iterdir() if find_cli(d, system)]
        if installs:
            return max(installs, key=_version_key)
    for folder in standard_dirs(system, env, home, root):
        if find_cli(folder, system):
            return folder
    return None


def locate_exiftool(
    art_dir: Path | None,
    env: Environ,
    program_files: Path | None,
    *,
    system: str | None = None,
    home: Path | None = None,
    root: Path | None = None,
) -> Path | None:
    """exiftool, looked for apart from ART-cli (a fork build has none): beside
    ART-cli in ``art_dir`` first, else on PATH, else beside the newest
    versioned folder under ``program_files`` that has one, else in the
    system's usual locations (``standard_dirs``)."""
    system = system or host_system()
    if art_dir is not None:
        found = find_exiftool(art_dir, system)
        if found:
            return found
    for entry in _path_dirs(env):
        found = find_exiftool(entry, system)
        if found:
            return found
    if program_files is not None and program_files.is_dir():
        installs = [d for d in program_files.iterdir() if find_exiftool(d, system)]
        if installs:
            return find_exiftool(max(installs, key=_version_key), system)
    for folder in standard_dirs(system, env, home, root):
        found = find_exiftool(folder, system)
        if found:
            return found
    return None


def user_config_dir(
    env: Environ,
    art_dir: Path | None = None,
    *,
    system: str | None = None,
    home: Path | None = None,
) -> Path:
    """ART's per-user config folder (holds the ``options`` file), by ART's
    own rules (``Options::load``): ``ART_SETTINGS`` if set; else, for an
    install whose own ``options`` says ``MultiUser=false`` (portable),
    ``<art_dir>/mysettings``; else ``ART`` in the per-user config folder:
    ``%LOCALAPPDATA%`` on Windows, elsewhere GLib's ``g_get_user_config_dir``
    (``$XDG_CONFIG_HOME`` if absolute, else ``~/.config``; macOS included).
    Builds made with a ``CACHE_NAME_SUFFIX`` use ``ART<suffix>``; point
    ``ART_SETTINGS`` at it.

    On macOS the app bundle's Info.plist sets a relative ``XDG_CONFIG_HOME``
    that GLib ignores, so ART should use ``~/.config/ART`` there too; if that
    folder is missing but ``~/Library/Application Support/ART`` exists, the
    latter is used."""
    system = system or host_system()
    if env.get("ART_SETTINGS"):
        return Path(env["ART_SETTINGS"])
    if art_dir is not None and _read_options(art_dir).get("General", {}).get("MultiUser") == "false":
        return art_dir / "mysettings"
    if system == "windows" and "LOCALAPPDATA" in env:
        return Path(env["LOCALAPPDATA"]) / "ART"
    user = _home(env, home)
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else user / ".config"
    config = base / "ART"
    if system == "macos" and not config.is_dir():
        support = user / "Library" / "Application Support" / "ART"
        if support.is_dir():
            return support
    return config


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
