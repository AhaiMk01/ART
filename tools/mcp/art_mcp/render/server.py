"""The Render server: open images and render previews headlessly via art-cli.

Edits live in a per-image *working profile* held in memory, seeded from the
image's sidecar (or ART's default profile) and never written back by renders.
"""

import argparse
import functools
import hashlib
import os
import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import NoBackChannelError
from mcp_types import ClientCapabilities, ElicitationCapability
from pydantic import BaseModel

from art_mcp import artdir, keyfile, sidecar
from art_mcp.keyfile import KeyFile
from art_mcp.preview import PreviewFolder, default_root
from art_mcp.profile import ProfileView, RawEdit, UnknownKey, WorkingChanges, read_format
from art_mcp.render.artcli import (
    ArtCli,
    ArtCliError,
    ArtCliTimeout,
    export_args,
    preview_args,
    resize_profile,
    resolve_profile_args,
)

PREVIEW_SIZE = 1024

ErrorCode = Literal[
    "not_open", "not_found", "unknown_key", "render_failed", "timeout",
    "conflict", "exists", "out_of_range",
]

EXPORT_SUFFIXES = {"jpeg": ".jpg", "tiff": ".tif", "png": ".png"}


ProfileSource = Literal["sidecar", "default"]


@dataclass
class WorkingProfile:
    image: Path
    changes: WorkingChanges
    sidecar_hash: str | None
    """SHA-256 of the sidecar on disk when this working profile was loaded
    (whichever source it was loaded from), or None if there was none: the
    baseline for detecting that someone else changed the sidecar."""
    sidecar_keys: KeyFile
    """That sidecar's content, to tell what someone else changed in it."""


def parse_sidecar(data: bytes | None) -> KeyFile:
    """A sidecar's keys; empty if there is none or it doesn't parse."""
    try:
        return keyfile.loads(data.decode("utf-8")) if data is not None else {}
    except ValueError:
        return {}


class OpenedImage(BaseModel):
    path: str
    profile_from: ProfileSource
    art_version: str


class ResetResult(BaseModel):
    profile_from: ProfileSource


class EditResult(BaseModel):
    changed: list[RawEdit]
    """Each [Group] Key whose value this call changed, with its new value
    (re-setting a value is not a change)."""


class ExportResult(BaseModel):
    path: str
    """The exported image."""
    profile_path: str | None
    """The `.arp` written beside it, when `write_profile` was set."""


Conflict = Literal["merge", "overwrite", "cancel"]
SaveHow = Literal["written", "merged", "overwritten", "cancelled"]


class ConflictChoice(BaseModel):
    choice: Conflict


class SaveResult(BaseModel):
    saved: bool
    path: str
    """The sidecar file."""
    how: SaveHow
    """`written` (nothing had changed there), `merged`, `overwritten` or
    `cancelled` (nothing saved)."""


class PartialProfileResult(BaseModel):
    written: bool
    """False when the agent has changed nothing: no file is written."""
    path: str
    keys: list[str]
    """The `[Group] Key` entries written."""


class Preview(BaseModel):
    path: str
    """JPEG file; open it to look at the preview."""
    max_size: int


def image_key(image: Path) -> str:
    """Identity of a resolved image path across calls (case-folded on
    Windows)."""
    return os.path.normcase(str(image))


def move_over(source: Path, target: Path) -> None:
    """Move ``source`` to ``target``, replacing it; works across drives."""
    try:
        os.replace(source, target)
    except OSError:
        shutil.copyfile(source, target)  # temp folder on another drive
        source.unlink()


def tool_error(code: ErrorCode, message: str) -> ToolError:
    return ToolError(f"{code}: {message}")


def build_server(cli: ArtCli, config_dir: Path, previews: PreviewFolder) -> MCPServer:
    working: dict[str, WorkingProfile] = {}

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            previews.remove()

    server = MCPServer(
        "art-render",
        instructions=(
            "Process raw images with ART without its editor. Call open_image "
            "first; render_preview returns a JPEG path to open and look at."
        ),
        lifespan=lifespan,
    )

    @functools.cache
    def art_version() -> str:
        return cli.version()

    def run(args: list[str], output: Path) -> None:
        try:
            cli.run(args)
        except ArtCliTimeout as e:
            raise tool_error("timeout", str(e)) from e
        except ArtCliError as e:
            raise tool_error("render_failed", str(e)) from e
        if not output.is_file():
            raise tool_error("render_failed", f"art-cli wrote no output to {output}")

    def opened(path: str) -> WorkingProfile:
        wp = working.get(image_key(Path(path).resolve()))
        if wp is None:
            raise tool_error("not_open", f"{path} is not open; call open_image first")
        return wp

    def load_working_profile(image: Path, source: ProfileSource | None) -> ProfileSource:
        """Resolve ``image``'s complete processing profile with one art-cli
        run and make it the working profile. ``source`` None means the sidecar
        if there is one, else ART's default profile."""
        sidecar = artdir.sidecar_path(image, config_dir)
        sidecar_bytes = sidecar.read_bytes() if sidecar.is_file() else None
        if source == "sidecar" and sidecar_bytes is None:
            raise tool_error("not_found", f"{image.name} has no sidecar ({sidecar})")
        source = source or ("sidecar" if sidecar_bytes is not None else "default")

        output = previews.new_file("resolve", ".jpg")
        arp = Path(str(output) + ".arp")
        # art-cli reads a copy of exactly the bytes that are hashed, so a
        # sidecar changing meanwhile can't make the two disagree.
        sidecar_copy = previews.new_file("sidecar", ".arp")
        try:
            base = None
            if source == "sidecar" and sidecar_bytes is not None:
                sidecar_copy.write_bytes(sidecar_bytes)
                base = sidecar_copy
            run(resolve_profile_args(image, output, base), output)
            if not arp.is_file():
                raise tool_error(
                    "render_failed",
                    "art-cli wrote no profile beside its output; turn off "
                    '"Embed processing parameters in metadata" in ART\'s preferences',
                )
            profile = keyfile.loads(arp.read_text(encoding="utf-8"))
        finally:
            output.unlink(missing_ok=True)
            arp.unlink(missing_ok=True)
            sidecar_copy.unlink(missing_ok=True)

        working[image_key(image)] = WorkingProfile(
            image=image,
            changes=WorkingChanges(profile),
            sidecar_keys=parse_sidecar(sidecar_bytes),
            sidecar_hash=(
                hashlib.sha256(sidecar_bytes).hexdigest() if sidecar_bytes is not None else None
            ),
        )
        return source

    async def ask_user(
        ctx: Context, target: Path, theirs: list[str], ours: list[str]
    ) -> Conflict | None:
        """The user's choice about a changed sidecar, or None if the client
        can't ask. Declining or dismissing the question is `cancel`."""
        asks = ClientCapabilities(elicitation=ElicitationCapability())
        if not ctx.request_context.session.check_client_capability(asks):
            return None
        try:
            answer = await ctx.elicit(
                f"{target.name} was changed since the agent loaded it "
                f"(changed there: {', '.join(theirs) or 'unknown'}). The agent changed: "
                f"{', '.join(ours) or 'nothing'}. Merge = keep the sidecar's values and "
                "apply only the agent's changes; overwrite = replace the sidecar with "
                "the agent's profile (a backup is kept).",
                ConflictChoice,
            )
        except NoBackChannelError:
            return None  # newer protocol versions: a tool can't ask mid-call
        return answer.data.choice if answer.action == "accept" else "cancel"

    @server.tool()
    def open_image(path: str) -> OpenedImage:
        """Open an image and load its processing profile (from its sidecar,
        else ART's default profile) as the working profile."""
        image = Path(path).resolve()
        if not image.is_file():
            raise tool_error("not_found", f"{image} does not exist")
        source = load_working_profile(image, None)
        return OpenedImage(path=str(image), profile_from=source, art_version=art_version())

    @server.tool()
    def reset_profile(path: str, to: ProfileSource) -> ResetResult:
        """Discard working-profile changes: reload the profile from the
        image's sidecar, or from ART's default profile."""
        return ResetResult(profile_from=load_working_profile(opened(path).image, to))

    @server.tool()
    def render_preview(path: str) -> Preview:
        """Render the working profile as a JPEG (long edge 1024 px) and return
        its path."""
        wp = opened(path)
        profile = previews.new_file("profile", ".arp")
        resize = previews.new_file("resize", ".arp")
        output = previews.new_file("preview", ".jpg")
        try:
            profile.write_text(keyfile.dumps(wp.changes.profile), encoding="utf-8")
            resize.write_text(resize_profile(PREVIEW_SIZE), encoding="utf-8")
            run(preview_args(wp.image, output, profile, resize), output)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        finally:
            profile.unlink(missing_ok=True)
            resize.unlink(missing_ok=True)
        return Preview(path=str(output), max_size=PREVIEW_SIZE)

    @server.tool()
    def get_profile(path: str) -> ProfileView:
        """The image's working profile: curated tools under `adjustments`,
        every other `[Group] Key` as a string under `raw`."""
        return read_format(opened(path).changes.profile)

    @server.tool()
    def edit_profile(path: str, raw_edits: list[RawEdit] | None = None) -> EditResult:
        """Change values of the working profile. Each raw edit sets one
        `[Group] Key` (as shown by get_profile) to a string value; the group
        and key must already exist. All edits apply, or none do."""
        wp = opened(path)
        try:
            changed = wp.changes.apply(raw_edits or [])
        except UnknownKey as e:
            raise tool_error("unknown_key", str(e)) from e
        return EditResult(changed=changed)

    @server.tool()
    def export_image(
        path: str,
        output: str,
        format: str,
        quality: int | None = None,
        bit_depth: str | None = None,
        write_profile: bool = False,
        overwrite: bool = False,
    ) -> ExportResult:
        """Render the working profile (saved or not) at full size to `output`.
        `quality` (1..100) is for jpeg; `bit_depth` is 8 for jpeg, 8|16 for
        png, 8|16|16f|32 for tiff (default: ART's). An existing `output` (or
        `.arp`) is refused with `exists` unless `overwrite`. With
        `write_profile`, the working profile is also saved as `<output>.arp`;
        otherwise no `.arp` is written. The folder of `output` must exist."""
        wp = opened(path)
        dest = Path(output).resolve()
        dest_arp = Path(str(dest) + ".arp")
        profile = previews.new_file("profile", ".arp")
        temp = previews.new_file("export", EXPORT_SUFFIXES.get(format, ".out"))
        temp_arp = Path(str(temp) + ".arp")
        try:
            args = export_args(wp.image, temp, profile, format, quality, bit_depth, write_profile)
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
            run(args, temp)
            if write_profile and not temp_arp.is_file():
                raise tool_error(
                    "render_failed",
                    "art-cli wrote no profile beside its output; turn off "
                    '"Embed processing parameters in metadata" in ART\'s preferences',
                )
            moves = [(temp, dest), (temp_arp, dest_arp)] if write_profile else [(temp, dest)]
            for source, target in moves:
                move_over(source, target)
        finally:
            for leftover in (profile, temp, temp_arp):
                leftover.unlink(missing_ok=True)
        return ExportResult(path=str(dest), profile_path=str(dest_arp) if write_profile else None)


    @server.tool()
    async def save_sidecar(
        path: str, ctx: Context, on_conflict: Conflict | None = None
    ) -> SaveResult:
        """Write the working profile to the image's sidecar (the only tool
        that writes it); the previous sidecar is kept as `<sidecar>.bak`.

        If the sidecar changed on disk since it was loaded, the user is asked
        (when the client supports it) whether to `merge` the agent's changes
        onto the current sidecar, `overwrite` it, or `cancel`; otherwise a
        `conflict` error lists the changed keys and the agent should ask the
        user, then call again with `on_conflict`."""
        wp = opened(path)
        target = artdir.sidecar_path(wp.image, config_dir)
        current = target.read_bytes() if target.is_file() else None
        profile = wp.changes.profile
        how: SaveHow = "written"
        text: str | None = None
        if (sidecar.file_hash(current) if current is not None else None) != wp.sidecar_hash:
            theirs = sidecar.changed_keys(wp.sidecar_keys, parse_sidecar(current))
            ours = sidecar.changed_keys({}, wp.changes.partial_profile())
            if on_conflict is None:
                on_conflict = await ask_user(ctx, target, theirs, ours)
            if on_conflict is None:
                raise tool_error(
                    "conflict",
                    "the sidecar changed since it was loaded. Changed in the sidecar: "
                    f"{', '.join(theirs) or '(nothing that parses)'}. Changed by the agent: "
                    f"{', '.join(ours) or '(nothing)'}. Ask the user, then call again with "
                    "on_conflict: merge (agent's changes onto the current sidecar), "
                    "overwrite, or cancel.",
                )
            if on_conflict == "cancel":
                return SaveResult(saved=False, path=str(target), how="cancelled")
            if on_conflict == "merge" and current is not None:
                merged = sidecar.merge(parse_sidecar(current), wp.changes.partial_profile())
                # The working profile follows the file, so later saves and
                # renders include what the user changed there.
                profile = sidecar.merge(profile, merged)
                how = "merged"
                text = keyfile.dumps(merged)
            else:
                how = "overwritten"
        if text is None:
            text = keyfile.dumps(profile)
        data = text.encode("utf-8")
        sidecar.write_with_backup(target, text)
        wp.changes = WorkingChanges(profile)
        wp.sidecar_hash = sidecar.file_hash(data)
        wp.sidecar_keys = parse_sidecar(data)
        return SaveResult(saved=True, path=str(target), how=how)

    @server.tool()
    def save_partial_profile(
        path: str, dest: str, overwrite: bool = False
    ) -> PartialProfileResult:
        """Write only the values the agent changed since the profile was
        loaded or last saved to `dest`, as a partial processing profile
        (.arp) that can be applied on top of other images. Refuses an
        existing `dest` unless `overwrite`. Nothing is written when nothing
        changed."""
        partial = opened(path).changes.partial_profile()
        target = Path(dest)
        if not target.parent.is_dir():
            raise tool_error("not_found", f"folder {target.parent} does not exist")
        if target.exists() and not overwrite:
            raise tool_error("exists", f"{target} exists; pass overwrite=true to replace it")
        if not partial:
            return PartialProfileResult(written=False, path=str(target), keys=[])
        sidecar.write_with_backup(target, keyfile.dumps(partial), backup=False)
        return PartialProfileResult(
            written=True, path=str(target), keys=sidecar.changed_keys({}, partial)
        )

    return server


def main() -> None:
    parser = argparse.ArgumentParser(prog="art-mcp-render", description=__doc__)
    parser.add_argument("--art-dir", help="folder holding ART-cli (default: ART_DIR, PATH, newest install)")
    args = parser.parse_args()

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ART"
    folder = artdir.find_art_dir(args.art_dir, os.environ, program_files)
    cli_path = artdir.find_cli(folder) if folder else None
    if cli_path is None:
        sys.exit("art-mcp-render: ART-cli not found; pass --art-dir or set ART_DIR")

    server = build_server(
        ArtCli((str(cli_path),)),
        artdir.user_config_dir(os.environ),
        PreviewFolder(default_root()),
    )
    server.run()
