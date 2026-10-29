"""What every ``art-axi`` command shares: its errors, the session over the
state folder, the ``Command`` record and the translation of the operations'
errors into this CLI's terms."""

import argparse
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from art_mcp import artdir
from art_mcp.axi import toon
from art_mcp.axi.output import shown
from art_mcp.axi.state import DiskStore, FileImageLocks, StatePreviews
from art_mcp.render.errors import RenderError

DESCRIPTION = "Edit and render raw images with ART headlessly"

GLOBAL_FLAGS = ("--art-dir", "--timeout")
"""Flags every command takes (with a value), before or after the command."""

EXIT_OK = 0
EXIT_FAILED = 1


class Failure(Exception):
    """An operation that can't do what was asked: printed, exit code 1."""

    exit_code = 1

    def __init__(self, message: str, help: list[str] | str | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.help = help
        self.code = code


class UsageError(Failure):
    """A command line that asks for nothing that can be done: exit code 2."""

    exit_code = 2

    def __init__(self, message: str, help: list[str] | str | None = None) -> None:
        super().__init__(message, help, "usage")


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        usage = " ".join(self.format_usage().split()).removeprefix("usage: ")
        raise UsageError(message, [usage, f"art-axi {self.prog.split()[-1]} --help  (flags and examples)"])


@dataclass
class Context:
    home: Path
    art_dir: str | None
    timeout: float | None
    session_factory: Callable[["Context"], Any] | None = None
    """Builds the session instead of finding art-cli (tests)."""
    _session: Any = None

    def store(self) -> DiskStore:
        return DiskStore(self.home)

    def session(self) -> Any:
        """The Render session over the state folder; finds art-cli first."""
        if self._session is None and self.session_factory is not None:
            self._session = self.session_factory(self)
        if self._session is None:
            from art_mcp.metadata import Exiftool
            from art_mcp.render.artcli import ArtCli
            from art_mcp.render.session import RenderSession

            program_files = artdir.windows_install_root(os.environ)
            folder = artdir.find_art_dir(self.art_dir, os.environ, program_files)
            cli_path = artdir.find_cli(folder) if folder else None
            if cli_path is None:
                raise Failure(
                    "ART-cli not found",
                    ["set ART_DIR to the folder holding ART-cli", "or pass --art-dir <folder> to any command"],
                    "art_not_found",
                )
            exiftool = artdir.locate_exiftool(folder, os.environ, program_files)
            previews = StatePreviews(self.home / "previews")
            previews.sweep()
            self._session = RenderSession(
                ArtCli((str(cli_path),), timeout=self.timeout or 60.0, export_timeout=self.timeout or 120.0),
                artdir.user_config_dir(os.environ, art_dir=folder),
                previews,
                Exiftool((str(exiftool),)) if exiftool else None,
                inline_previews=False,
                store=self.store(),
                locks=FileImageLocks(self.home / "locks"),
            )
        return self._session


def art_cli_location(art_dir: str | None) -> str:
    folder = artdir.find_art_dir(art_dir, os.environ, artdir.windows_install_root(os.environ))
    cli = artdir.find_cli(folder) if folder else None
    return shown(cli) if cli else "not found (set ART_DIR or pass --art-dir)"


def edit_count(wp: Any) -> int:
    """How many values the agent changed since the image was loaded."""
    profile = wp.changes.profile
    return sum(1 for group, key, loaded in wp.changes.loaded_values() if profile.get(group, {}).get(key) != loaded)


ERROR_HELP = {
    "not_open": ["art-axi open {path}"],
    "not_found": ["check the path; `art-axi` lists the open images"],
    "conflict": ["art-axi save {path} --on-conflict merge", "art-axi save {path} --on-conflict overwrite"],
    "exists": ["add --overwrite, or choose another --out"],
    "unknown_key": ["art-axi profile {path} --all  (lists every [Group] Key)"],
    "unsupported": ["point ART_DIR (or --art-dir) at an ART build with spot sampling (art-cli -x)"],
    "timeout": ["retry with --timeout <seconds>"],
    "open_in_editor": ["close the image in ART's editor, then retry"],
    "metadata_unavailable": ["install exiftool, or put it beside ART-cli or on PATH"],
    "out_of_range": [],
}

TOOL_NAMES = {
    "open_image": "open",
    "reset_profile": "reset",
    "get_profile": "profile",
    "edit_profile": "edit",
    "describe_adjustments": "describe",
    "render_preview": "preview",
    "image_stats": "stats",
    "sample_spots": "sample",
    "save_sidecar": "save",
    "export_image": "export",
    "inspect_image": "inspect",
    "export_batch": "export",
    "contact_sheet": "sheet",
}
"""The MCP tool names the operations' messages use -> this CLI's commands."""

_TOOL_NAME = re.compile(r"\b(" + "|".join(TOOL_NAMES) + r")\b")

_TRUE_ARGUMENT = re.compile(r"\b([a-z_]+)=true\b")


def in_cli_terms(message: str) -> str:
    """An operation's message with the MCP tool and argument names it uses
    (``open_image``, ``overwrite=true``) as this CLI's (``art-axi open``,
    ``--overwrite``)."""
    message = _TOOL_NAME.sub(lambda m: f"`art-axi {TOOL_NAMES[m[1]]}`", message)
    return _TRUE_ARGUMENT.sub(lambda m: "--" + m[1].replace("_", "-"), message)


def failure_from(error: RenderError, path: str | None) -> Failure:
    hints = [h.format(path=path or "<path>") for h in ERROR_HELP.get(error.code, [])]
    return Failure(in_cli_terms(error.message), hints or None, error.code)


@dataclass
class Command:
    name: str
    summary: str
    build: Callable[[Parser], None]
    run: Callable[[Context, argparse.Namespace], dict[str, Any]]
    examples: list[str]
    renamed: dict[str, str] = field(default_factory=dict)
    """Flags an agent may guess (the MCP tool's argument names) -> the hint."""

    def parser(self) -> Parser:
        epilog = "examples:\n" + "\n".join(f"  {e}" for e in self.examples)
        parser = Parser(
            prog=f"art-axi {self.name}",
            description=self.summary,
            epilog=epilog,
            allow_abbrev=False,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        self.build(parser)
        return parser

    def usage(self) -> str:
        """The one-line usage, without the leading ``usage:``."""
        return " ".join(self.parser().format_usage().split()).removeprefix("usage: ")

    def valid_flags(self) -> list[str]:
        flags = []
        for action in self.parser()._actions:
            flags.extend(s for s in action.option_strings if s.startswith("--") and s != "--help")
        return flags


def call(operation: Callable[[], Any], path: str | None = None) -> Any:
    """Run an operation, turning its errors into a ``Failure``."""
    try:
        return operation()
    except RenderError as e:
        raise failure_from(e, path) from e
    except OSError as e:
        raise Failure(str(e), code="render_failed") from e


def error_output(e: Failure) -> dict[str, Any]:
    out: dict[str, Any] = {"error": str(e)}
    if e.code:
        out["code"] = e.code
    if e.help:
        out["help"] = e.help
    return out


def adjustments_arg(text: str | None) -> dict[str, Any] | None:
    """``--adjust``'s JSON object (None without one)."""
    if text is None:
        return None
    try:
        adjustments = json.loads(text)
    except json.JSONDecodeError as e:
        raise UsageError(f"--adjust is not JSON: {e}", "art-axi describe  (the adjustments and their fields)") from e
    if not isinstance(adjustments, dict):
        raise UsageError("--adjust takes a JSON object", "art-axi describe")
    return adjustments


def emit(data: dict[str, Any]) -> None:
    print(toon.encode(cli_errors(data)))


def cli_errors(value: Any) -> Any:
    """``value`` with every `error` text (a batch item's too) in this CLI's
    terms (see ``in_cli_terms``)."""
    if isinstance(value, dict):
        return {k: in_cli_terms(v) if k == "error" and isinstance(v, str) else cli_errors(v) for k, v in value.items()}
    if isinstance(value, list):
        return [cli_errors(v) for v in value]
    return value
