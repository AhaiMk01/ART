import pytest
from mcp.client.client import Client

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server
from fake_live_art import FakeArt, answer, fail

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def art(tmp_path):
    fake = FakeArt(tmp_path / "config")
    yield fake
    fake.close()


async def test_status_lists_the_images_open_in_the_editor(art):
    art.ops["status"] = answer({
        "version": "1.26.test",
        "images": [
            {"path": "C:/photos/a.ARW", "active": True, "width": 6000, "height": 4000},
            {"path": "C:/photos/b.ARW", "active": False, "width": None, "height": None},
        ],
    })  # fmt: skip

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("status", {})

    assert not result.is_error, result.content
    assert result.structured_content == {
        "art_version": "1.26.test",
        "images": [
            {"path": "C:/photos/a.ARW", "active": True, "width": 6000, "height": 4000},
            {"path": "C:/photos/b.ARW", "active": False, "width": None, "height": None},
        ],
    }


async def test_status_without_art_is_art_not_running_with_a_hint(tmp_path):
    async with Client(build_server(ControlChannel(tmp_path))) as client:
        result = await client.call_tool("status", {})

    assert result.is_error
    text = result.content[0].text
    assert "art_not_running:" in text and "--live-control" in text


async def test_status_with_a_dead_art_is_art_not_running(art):
    channel = ControlChannel(art.config_dir, is_alive=lambda pid: False)
    async with Client(build_server(channel)) as client:
        result = await client.call_tool("status", {})

    assert result.is_error and "art_not_running:" in result.content[0].text


async def test_error_from_art_keeps_its_code(art):
    art.ops["status"] = fail("internal", "boom")

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("status", {})

    assert result.is_error and result.content[0].text.endswith("internal: boom")


async def test_malformed_status_is_bad_reply(art):
    art.ops["status"] = answer({"images": "nope"})

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("status", {})

    assert result.is_error and "bad_reply:" in result.content[0].text
