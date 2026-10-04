"""The Live server: read and change the images open in a running ART editor.

ART must have been started with ``--live-control``; the Live server never
launches ART.
"""

import argparse
import base64
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent
from pydantic import BaseModel

from art_mcp import artdir, keyfile
from art_mcp.live.channel import ArtNotRunning, ChannelError, ChannelTimeout, ControlChannel
from art_mcp.metadata import Exiftool, Metadata, MetadataProblem, read_metadata
from art_mcp.preview import PreviewFolder, default_root, sweep_stale
from art_mcp.render.preview_tools import MAX_PREVIEW_SIZE, PREVIEW_SIZE, Preview
from art_mcp.profile import Conflict as EditConflict
from art_mcp.profile import (
    ProfileView,
    RawEdit,
    UnknownKey,
    WorkingChanges,
    crop_problem,
    edit_warnings,
    read_format,
)
from art_mcp.schema import (
    TOOLS,
    AdjustmentError,
    Adjustments,
    AdjustmentsArg,
    AdjustmentsDescription,
    parse_adjustments,
)
from art_mcp.schema import describe_adjustments as schema_description

OPEN_POLL_SECONDS = 0.25


def tool_error(code: str, message: str) -> ToolError:
    """``code`` is art_not_running, timeout, bad_reply, or an error code ART
    itself returned."""
    return ToolError(f"{code}: {message}")


class OpenImage(BaseModel):
    path: str
    active: bool
    """The editor the user is looking at."""
    width: int | None
    height: int | None
    """The image's size as the editor processes it (before cropping); null
    until ART has computed its first preview."""


class LiveProfile(ProfileView):
    history_position: int | None
    """The selected row of ART's History panel (0 = the oldest entry); null
    if no row is selected."""


class Status(BaseModel):
    art_version: str
    images: list[OpenImage]
    """The images open in ART's editor."""


class LiveEditResult(BaseModel):
    changed: list[RawEdit]
    """Each [Group] Key whose value this call changed, with its new value
    (re-setting a value is not a change)."""
    implied: list[RawEdit]
    """The part of `changed` that was not asked for: a disabled tool enabled
    because it was adjusted, White Balance switched to CustomTemp."""
    warnings: list[str]
    history_position: int | None
    """The selected History row afterwards: the new entry (the same row as
    before when nothing changed, as no entry is made then)."""


class HistoryStep(BaseModel):
    history_position: int | None
    """The selected History row afterwards (0 = the oldest entry)."""


class OpenedInEditor(BaseModel):
    path: str
    """The image, as ART names it."""
    already_open: bool


class SidecarSaved(BaseModel):
    saved: bool
    sidecar: str | None
    """The sidecar file written; null when ART is set to keep processing
    profiles in its cache only."""


TOOL_TITLES = {name: name.replace("_", " ").title() for name in TOOLS} | {
    "vignetting": "Vignetting Correction"
}
"""How an edit names a curated tool in ART's History (``Agent: ...``)."""


def history_label(adjustments: Adjustments | None, raw_edits: list[RawEdit]) -> str:
    """``Agent: <tools touched>``: the adjusted curated tools, then the
    groups of raw edits not already named, each once, in request order."""
    names: list[str] = []
    if adjustments is not None:
        names += [TOOL_TITLES[n] for n in TOOLS if getattr(adjustments, n) is not None]
    for edit in raw_edits:
        named = next((TOOL_TITLES[n] for n, (g, _) in TOOLS.items() if g == edit.group), edit.group)
        if named not in names:
            names.append(named)
    return "Agent: " + ", ".join(names)


class LivePreview(Preview):
    width: int
    height: int
    """The JPEG's size: the editor's preview image shrunk to fit `max_size`
    (never enlarged, so it can be smaller)."""


ART_PREVIEW_WAIT = 30.0
"""How long ART waits for its processing to drain before a preview fails
with `timeout`."""


def art_path(path: str) -> str:
    """How to name an image to ART: absolute, but with links, junctions and
    subst drives left as they are, since ART keeps the name it opened the
    file under (it compares case-insensitively on Windows itself)."""
    return os.path.abspath(path)


def same_image(a: str, b: str) -> bool:
    """Whether two paths name the same file, by the rule ART uses."""
    return os.path.normcase(art_path(a)) == os.path.normcase(art_path(b))


def build_server(
    channel: ControlChannel,
    *,
    exiftool: Exiftool | None = None,
    open_timeout: float = 60.0,
    previews: PreviewFolder | None = None,
    inline_previews: bool = False,
) -> MCPServer:
    """``open_timeout``: how long open_image waits for ART to load an image."""
    preview_folder = previews or PreviewFolder(default_root())

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            preview_folder.remove()

    server = MCPServer(
        "art-live",
        instructions=(
            "Work with the images open in a running ART editor (started with "
            "--live-control). Call status to see which images are open."
        ),
        lifespan=lifespan,
    )

    def call(op: str, args: dict[str, Any] | None = None, timeout: float | None = None) -> object:
        try:
            return channel.request(op, args, timeout=timeout)
        except ArtNotRunning as e:
            raise tool_error("art_not_running", str(e)) from e
        except ChannelTimeout as e:
            raise tool_error("timeout", str(e)) from e
        except ChannelError as e:
            raise tool_error(e.code, e.message) from e

    @server.tool()
    def status() -> Status:
        """Whether a control-enabled ART is running, its version, and the
        images open in its editor (absolute paths and sizes). Fails with
        art_not_running when there is none."""
        result = call("status")
        try:
            if not isinstance(result, dict):
                raise TypeError("not an object")
            return Status.model_validate({"art_version": result["version"], "images": result["images"]})
        except (KeyError, TypeError, ValueError) as e:
            raise tool_error("bad_reply", f"unexpected status from ART: {result!r}") from e

    @server.tool()
    def get_profile(path: str) -> LiveProfile:
        """The processing profile of an image open in ART's editor, as the
        editor has it now: curated tools typed under `adjustments`, every
        other `[Group] Key` as a string under `raw`, plus the selected
        History row. Fails with not_open if ART doesn't have it open."""
        result = call("get_profile", {"path": art_path(path)})
        try:
            if not isinstance(result, dict):
                raise TypeError("not an object")
            view = read_format(keyfile.loads(result["profile"]))
            position = result["history_position"]
            if not isinstance(position, int):
                raise TypeError("history_position is not a number")
            return LiveProfile(**view.model_dump(), history_position=position if position >= 0 else None)
        except (KeyError, TypeError, ValueError) as e:
            raise tool_error("bad_reply", f"unexpected get_profile reply from ART: {result!r:.300}") from e

    @server.tool()
    def describe_adjustments() -> AdjustmentsDescription:
        """The curated adjustments: each tool's fields with type, range,
        unit and the `[Group] Key` it sets (the same schema as the Render
        server's)."""
        return schema_description()

    @server.tool()
    def inspect_image(path: str, tags: list[str] | None = None) -> Metadata:
        """The metadata of an image open in ART (read with ART's exiftool):
        make, model, lens, ISO, shutter, aperture, focal length, capture
        date, pixel dimensions and orientation, plus any extra exiftool
        `tags` named. Fails with not_open if ART doesn't have it open."""
        result = call("status")
        images = result.get("images", []) if isinstance(result, dict) else []
        if not any(isinstance(i, dict) and same_image(str(i.get("path", "")), path) for i in images):
            raise tool_error("not_open", f"{path} is not open in ART")
        try:
            return read_metadata(exiftool, Path(art_path(path)), tags or [])
        except MetadataProblem as e:
            raise tool_error(e.code, e.message) from e

    def history_position(op: str, result: object) -> int | None:
        if not isinstance(result, dict) or not isinstance(result.get("history_position"), int):
            raise tool_error("bad_reply", f"unexpected {op} reply from ART: {result!r:.300}")
        position: int = result["history_position"]
        return position if position >= 0 else None

    def open_images() -> list[dict[str, Any]]:
        result = call("status")
        images = result.get("images") if isinstance(result, dict) else None
        if not isinstance(images, list):
            raise tool_error("bad_reply", f"unexpected status from ART: {result!r:.300}")
        return [i for i in images if isinstance(i, dict)]

    def get_profile_text(path: str) -> dict[str, Any]:
        result = call("get_profile", {"path": art_path(path)})
        if not isinstance(result, dict) or not isinstance(result.get("profile"), str):
            raise tool_error("bad_reply", f"unexpected get_profile reply from ART: {result!r:.300}")
        return result

    def image_size(path: str) -> tuple[int, int] | None:
        for image in open_images():
            if same_image(str(image.get("path", "")), path):
                w, h = image.get("width"), image.get("height")
                return (w, h) if isinstance(w, int) and isinstance(h, int) else None
        return None

    @server.tool()
    def edit_profile(
        path: str,
        adjustments: AdjustmentsArg = None,
        raw_edits: list[RawEdit] | None = None,
    ) -> LiveEditResult:
        """Change the processing profile of an image open in ART's editor,
        with typed `adjustments` of curated tools (range-checked; see
        describe_adjustments) and/or `raw_edits`, each setting one
        `[Group] Key` (as shown by get_profile) to a string value; the group
        and key must already exist. All changes apply, or none do. An
        adjustment and a raw edit may not set the same key. Adjusting a
        disabled tool also enables it (listed under `implied`).

        The user sees the change at once, as one History entry labelled
        `Agent: <tools>` that undo reverts. Only the changed values are sent,
        so the user's other settings are left alone. Returns once the History
        entry exists (the preview may still be processing)."""
        current = get_profile_text(path)
        changes = WorkingChanges(keyfile.loads(current["profile"]))
        warnings: list[str] = []
        try:
            parsed = parse_adjustments(adjustments) if adjustments else None
            if parsed is not None and parsed.crop is not None:
                size = image_size(path)
                if size is None:
                    warnings.append(
                        "the crop was not checked against the image size: "
                        "ART hasn't reported it yet"
                    )
                else:
                    problem = crop_problem(changes.profile, parsed.crop, lambda: size)
                    if problem:
                        raise AdjustmentError("out_of_range", problem)
            outcome = changes.edit(parsed, raw_edits or [])
        except AdjustmentError as e:
            raise tool_error(e.code, str(e)) from e
        except UnknownKey as e:
            raise tool_error("unknown_key", str(e)) from e
        except EditConflict as e:
            raise tool_error("conflict", str(e)) from e
        warnings += edit_warnings(parsed, changes.profile)
        partial = changes.partial_profile()
        # ART applies the partial profile over the profile it holds then: a
        # change the user made since get_profile stays, unless it is to one
        # of these keys.
        if not partial:
            # Nothing to change: no empty History entry.
            position = history_position("get_profile", current)
        else:
            reply = call("apply_profile", {
                "path": art_path(path),
                "profile": keyfile.dumps(partial),
                "label": history_label(parsed, raw_edits or []),
            })  # fmt: skip
            position = history_position("apply_profile", reply)
        return LiveEditResult(
            changed=outcome.changed, implied=outcome.implied, warnings=warnings,
            history_position=position,
        )  # fmt: skip

    @server.tool()
    def undo(path: str) -> HistoryStep:
        """Step back one entry in the History of an image open in ART (as
        the user's Undo does). At the oldest entry nothing changes."""
        return HistoryStep(history_position=history_position("undo", call("undo", {"path": art_path(path)})))

    @server.tool()
    def redo(path: str) -> HistoryStep:
        """Step forward one entry in the History of an image open in ART (as
        the user's Redo does). At the newest entry nothing changes."""
        return HistoryStep(history_position=history_position("redo", call("redo", {"path": art_path(path)})))

    @server.tool()
    def open_image(path: str) -> OpenedInEditor:
        """Open an image in ART's editor (or bring it to the front if it is
        open already), as opening it from ART's file browser does. Returns
        once ART has loaded it. Fails with not_found if there is no such
        file."""
        reply = call("open", {"path": art_path(path)})
        already = isinstance(reply, dict) and reply.get("already_open") is True
        deadline = time.monotonic() + open_timeout
        while True:
            for image in open_images():
                listed = str(image.get("path", ""))
                if same_image(listed, path) and image.get("width") is not None:
                    return OpenedInEditor(path=listed, already_open=already)
            if time.monotonic() >= deadline:
                raise tool_error(
                    "timeout",
                    f"ART did not finish opening {path} within {open_timeout:g} s "
                    "(it may still be loading; call status to check)",
                )
            time.sleep(OPEN_POLL_SECONDS)

    @server.tool()
    def save_sidecar(path: str) -> SidecarSaved:
        """Save the processing profile of an image open in ART as the
        editor's own save does (to its sidecar file, and ART's cache)."""
        reply = call("save_sidecar", {"path": art_path(path)})
        if not isinstance(reply, dict) or not isinstance(reply.get("sidecar"), (str, type(None))):
            raise tool_error("bad_reply", f"unexpected save_sidecar reply from ART: {reply!r:.300}")
        return SidecarSaved(saved=True, sidecar=reply["sidecar"])

    @server.tool()
    def render_preview(
        path: str, max_size: int = PREVIEW_SIZE, inline: bool | None = None
    ) -> Annotated[CallToolResult, LivePreview]:
        """The image open in ART's editor as the editor shows it now, as a
        JPEG (long edge at most `max_size` px, 1 to 2576; the editor's preview
        is often smaller, and is never enlarged); returns its path. Waits
        until ART has finished processing the latest edits (fails with
        timeout after 30 s). The colours are in the monitor colour space
        ART displays with, not sRGB output. `inline` also returns the image
        itself (default: the server's --inline-previews setting). Fails with
        not_open if ART doesn't have the image open."""
        if not 1 <= max_size <= MAX_PREVIEW_SIZE:
            raise tool_error("out_of_range", f"max_size must be 1 to {MAX_PREVIEW_SIZE}")
        output = preview_folder.new_file("live", ".jpg")
        args = {"path": art_path(path), "output": str(output), "max_size": max_size}
        try:
            result = call("preview", args, timeout=channel.timeout + ART_PREVIEW_WAIT)
            try:
                if not isinstance(result, dict):
                    raise TypeError("not an object")
                preview = LivePreview(
                    path=str(output), max_size=max_size, width=result["width"], height=result["height"]
                )
                jpeg = output.read_bytes()
            except (KeyError, TypeError, ValueError, OSError) as e:
                raise tool_error("bad_reply", f"unexpected preview reply from ART: {result!r:.300}") from e
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        content: list[ContentBlock] = [TextContent(text=preview.model_dump_json())]
        if inline if inline is not None else inline_previews:
            content.append(ImageContent(data=base64.b64encode(jpeg).decode("ascii"), mime_type="image/jpeg"))
        return CallToolResult(content=content, structured_content=preview.model_dump(mode="json"))

    return server


def main() -> None:
    parser = argparse.ArgumentParser(prog="art-mcp-live", description=__doc__)
    parser.add_argument(
        "--timeout", type=float, default=30.0, metavar="SECONDS",
        help="how long to wait for ART to answer a request (default 30)",
    )  # fmt: skip
    parser.add_argument(
        "--art-dir",
        help="ART's install folder, only to find the settings of a portable "
        "(MultiUser=false) install (default: ART_DIR, PATH, newest install)",
    )
    parser.add_argument(
        "--inline-previews",
        action="store_true",
        help="return preview images inline (base64) as well as by path; "
        "render_preview's `inline` argument overrides this per call",
    )
    args = parser.parse_args()
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ART"
    art_dir = artdir.find_art_dir(args.art_dir, os.environ, program_files)
    channel = ControlChannel(artdir.user_config_dir(os.environ, art_dir=art_dir), timeout=args.timeout)
    exiftool_path = artdir.find_exiftool(art_dir) if art_dir else None
    sweep_stale()
    build_server(
        channel,
        exiftool=Exiftool((str(exiftool_path),)) if exiftool_path else None,
        previews=PreviewFolder(default_root()),
        inline_previews=args.inline_previews,
    ).run()
