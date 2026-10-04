"""The Render server against a slow, hanging or failing fake art-cli."""

import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp.client.client import Client

from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

CTL = Path(__file__).with_name("fake_artcli_ctl.py")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def server(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    return build_server(
        ArtCli((sys.executable, str(CTL)), timeout=1.0), config, PreviewFolder(tmp_path / "previews")
    )


def error_text(result):
    return result.content[0].text.split("Error executing tool ")[-1].split(": ", 1)[-1]


async def test_a_hung_render_is_killed_and_reported_as_timeout(server, image, monkeypatch):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "30")
        started = time.monotonic()
        result = await client.call_tool("render_preview", {"path": str(image)})

    assert result.is_error
    assert error_text(result).startswith("timeout")
    assert time.monotonic() - started < 10


async def test_a_skipped_output_is_render_failed(server, image, monkeypatch):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        monkeypatch.setenv("FAKE_ARTCLI_SKIP", "1")
        result = await client.call_tool("render_preview", {"path": str(image)})

    assert result.is_error
    assert error_text(result).startswith("render_failed")
    assert "no output" in error_text(result)


async def test_a_failing_art_cli_explains_its_exit_code(server, image, monkeypatch):
    monkeypatch.setenv("FAKE_ARTCLI_EXIT", "-2")
    async with Client(server) as client:
        result = await client.call_tool("open_image", {"path": str(image)})

    assert result.is_error
    assert error_text(result).startswith("render_failed")
    assert "load or save" in error_text(result)


EDITS = [
    {"group": "Exposure", "key": "Compensation", "value": "1.5"},
    {"group": "Exposure", "key": "Black", "value": "0.5"},
]


async def test_an_edit_during_a_render_waits_and_never_shows_half_of_itself(server, image, monkeypatch):
    done: dict[str, float] = {}
    previews: list[bytes] = []

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0.8")

        async def render():
            result = await client.call_tool("render_preview", {"path": str(image)})
            done["render"] = time.monotonic()
            previews.append(Path(result.structured_content["path"]).read_bytes())

        async def edit():
            await anyio.sleep(0.3)  # the render is under way
            result = await client.call_tool("edit_profile", {"path": str(image), "raw_edits": EDITS})
            assert not result.is_error, result.content
            done["edit"] = time.monotonic()

        async with anyio.create_task_group() as tg:
            tg.start_soon(render)
            tg.start_soon(edit)

        monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0")
        after = await client.call_tool("render_preview", {"path": str(image)})
        previews.append(Path(after.structured_content["path"]).read_bytes())

    assert done["edit"] >= done["render"]
    during, later = previews
    assert b"Compensation=1.5" not in during and b"Black=0.5" not in during
    assert b"Compensation=1.5" in later and b"Black=0.5" in later
