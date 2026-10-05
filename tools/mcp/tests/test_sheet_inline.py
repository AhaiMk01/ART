"""contact_sheet and compare_passes follow the server's --inline-previews flag like render_preview does: the
sheet image comes back in the result too, for clients that cannot open the file."""

import base64
import json
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def real_jpegs(monkeypatch):
    monkeypatch.setenv("FAKE_REAL_JPEG", "1")


@pytest.fixture
def photos(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    paths = []
    for name in ("FILM_1.ARW", "FILM_2.ARW"):
        (folder / name).write_bytes(b"raw")
        paths.append(str(folder / name))
    return paths


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return str(folder)


def server_with(tmp_path, inline):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    return build_server(
        ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews"), inline_previews=inline
    )


def image_blocks(result):
    return [block for block in result.content if block.type == "image"]


async def open_all(client, photos):
    for photo in photos:
        await client.call_tool("open_image", {"path": photo})


async def test_a_sheet_has_no_image_in_the_result_unless_the_flag_is_on(tmp_path, photos, out):
    async with Client(server_with(tmp_path, inline=False)) as client:
        await open_all(client, photos)
        result = await client.call_tool("contact_sheet", {"images": photos, "folder": out})
    assert not result.is_error, result.content
    assert not image_blocks(result) and Path(result.structured_content["path"]).is_file()


async def test_a_recorded_sheet_comes_back_inline_when_the_flag_is_on(tmp_path, photos, out):
    async with Client(server_with(tmp_path, inline=True)) as client:
        await open_all(client, photos)
        result = await client.call_tool("contact_sheet", {"images": photos, "folder": out})
    assert not result.is_error, result.content
    [block] = image_blocks(result)
    assert block.mime_type == "image/jpeg"
    assert base64.b64decode(block.data) == Path(result.structured_content["path"]).read_bytes()


async def test_a_quick_look_sheet_comes_back_inline_too(tmp_path, photos):
    async with Client(server_with(tmp_path, inline=True)) as client:
        await open_all(client, photos)
        result = await client.call_tool("contact_sheet", {"images": photos, "record": False})
        jpeg = Path(result.structured_content["path"]).read_bytes()  # in the server's temp folder: read it now
    assert not result.is_error, result.content
    [block] = image_blocks(result)
    assert base64.b64decode(block.data) == jpeg
    assert result.structured_content["index"] is None  # the fields of a quick look are unchanged


async def test_the_text_of_a_sheet_result_is_its_structured_content(tmp_path, photos, out):
    async with Client(server_with(tmp_path, inline=True)) as client:
        await open_all(client, photos)
        result = await client.call_tool("contact_sheet", {"images": photos, "folder": out})
    assert json.loads(result.content[0].text) == result.structured_content


async def test_compare_passes_comes_back_inline_when_the_flag_is_on(tmp_path, photos, out):
    async with Client(server_with(tmp_path, inline=True)) as client:
        await open_all(client, photos)
        await client.call_tool("contact_sheet", {"images": photos, "folder": out, "label": "a"})
        await client.call_tool("contact_sheet", {"images": photos, "folder": out, "label": "b"})
        result = await client.call_tool("compare_passes", {"first": 1, "second": 2})
    assert not result.is_error, result.content
    [block] = image_blocks(result)
    assert block.mime_type == "image/jpeg"
    assert base64.b64decode(block.data) == Path(result.structured_content["path"]).read_bytes()


async def test_compare_passes_has_no_image_without_the_flag(tmp_path, photos, out):
    async with Client(server_with(tmp_path, inline=False)) as client:
        await open_all(client, photos)
        await client.call_tool("contact_sheet", {"images": photos, "folder": out, "label": "a"})
        await client.call_tool("contact_sheet", {"images": photos, "folder": out, "label": "b"})
        result = await client.call_tool("compare_passes", {"first": 1, "second": 2})
    assert not result.is_error, result.content
    assert not image_blocks(result)


async def test_the_descriptions_say_the_flag_returns_the_image(tmp_path):
    async with Client(server_with(tmp_path, inline=False)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    for name in ("contact_sheet", "compare_passes"):
        assert "--inline-previews" in tools[name].description, name
