"""Export tool: export_image."""

import os
import shutil
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from art_mcp import keyfile
from art_mcp.render.artcli import export_args
from art_mcp.render.session import RenderSession, no_profile_written, tool_error

EXPORT_SUFFIXES = {"jpeg": ".jpg", "tiff": ".tif", "png": ".png"}


class ExportResult(BaseModel):
    path: str
    """The exported image."""
    profile_path: str | None
    """The `.arp` written beside it, when `write_profile` was set."""


def move_over(source: Path, target: Path) -> None:
    """Move ``source`` to ``target``, replacing it; works across drives."""
    try:
        os.replace(source, target)
    except OSError:
        shutil.copyfile(source, target)  # temp folder on another drive
        source.unlink()


def register(server: MCPServer, session: RenderSession) -> None:
    previews = session.previews

    @server.tool()
    def export_image(
        path: str,
        output: str,
        format: str,
        quality: int | None = None,
        bit_depth: int | str | None = None,
        write_profile: bool = False,
        overwrite: bool = False,
    ) -> ExportResult:
        """Render the working profile (saved or not) at full size to `output`.
        `quality` (1..100) is for jpeg; `bit_depth` is 8 for jpeg, 8|16 for
        png, 8|16|"16f"|32 for tiff (default: ART's). An existing `output` (or
        `.arp`) is refused with `exists` unless `overwrite`. With
        `write_profile`, the working profile is also saved as `<output>.arp`;
        otherwise no `.arp` is written. The folder of `output` must exist."""
        with session.image(path) as wp:
            dest = Path(output).resolve()
            dest_arp = Path(str(dest) + ".arp")
            profile = previews.new_file("profile", ".arp")
            temp = previews.new_file("export", EXPORT_SUFFIXES.get(format, ".out"))
            temp_arp = Path(str(temp) + ".arp")
            depth = None if bit_depth is None else str(bit_depth)  # 8 and "8" alike
            try:
                args = export_args(wp.image, temp, profile, format, quality, depth, write_profile)
            except ValueError as e:
                raise tool_error("out_of_range", str(e)) from e
            if not dest.parent.is_dir():
                raise tool_error("not_found", f"folder {dest.parent} does not exist")
            targets = [dest, dest_arp] if write_profile else [dest]
            if not overwrite:
                for target in targets:
                    if target.exists():
                        raise tool_error("exists", f"{target} already exists; pass overwrite=true to replace it")
            try:
                profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
                session.run(args, temp, timeout=session.cli.export_timeout)
                if write_profile and not temp_arp.is_file():
                    raise no_profile_written()
                moves = [(temp, dest), (temp_arp, dest_arp)] if write_profile else [(temp, dest)]
                for source, target in moves:
                    move_over(source, target)
            finally:
                for leftover in (profile, temp, temp_arp):
                    leftover.unlink(missing_ok=True)
            return ExportResult(path=str(dest), profile_path=str(dest_arp) if write_profile else None)
