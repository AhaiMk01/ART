import json
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server
from art_mcp.metadata import Exiftool
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


SAMPLE_ARP = """[Version]
AppVersion=1.26.test
Version=1045

[Exposure]
Enabled=true
Compensation=0.7
Black=0

[ToneCurve]
Enabled=false
"""


async def test_get_profile_returns_the_read_format_and_history_position(art, tmp_path):
    image = tmp_path / "a.ARW"
    art.ops["get_profile"] = answer({"profile": SAMPLE_ARP, "history_position": 3})

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("get_profile", {"path": str(image)})

    assert not result.is_error, result.content
    profile = result.structured_content
    assert profile["ppversion"] == 1045
    assert profile["history_position"] == 3
    assert profile["adjustments"]["exposure"]["compensation"] == 0.7
    assert profile["adjustments"]["tone_curve"]["enabled"] is False
    assert "ToneCurve" not in profile["raw"]
    sent = json.loads(art.received[-1])
    assert sent["op"] == "get_profile" and sent["args"] == {"path": str(image)}


async def test_get_profile_of_an_image_not_open_in_art_is_not_open(art, tmp_path):
    art.ops["get_profile"] = fail("not_open", "C:/x.ARW is not open in ART")

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("get_profile", {"path": str(tmp_path / "x.ARW")})

    assert result.is_error and "not_open" in result.content[0].text


async def test_describe_adjustments_is_the_shared_schema(art):
    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("describe_adjustments", {})

    assert not result.is_error, result.content
    assert {"exposure", "white_balance", "crop", "lens_profile"} <= result.structured_content["tools"].keys()


def live_with_exiftool(art):
    fake = Path(__file__).with_name("fake_exiftool.py")
    return build_server(ControlChannel(art.config_dir), exiftool=Exiftool((sys.executable, str(fake))))


async def test_inspect_image_reads_metadata_of_an_image_open_in_art(art, tmp_path):
    image = tmp_path / "a.ARW"
    image.write_bytes(b"raw")
    image.with_name("a.ARW.exif.json").write_text(json.dumps({"Make": "SONY", "Model": "ILCE-7M3"}))
    art.ops["status"] = answer({"version": "t", "images": [
        {"path": str(image), "active": True, "width": None, "height": None}]})  # fmt: skip

    async with Client(live_with_exiftool(art)) as client:
        result = await client.call_tool("inspect_image", {"path": str(image)})
        other = await client.call_tool("inspect_image", {"path": str(tmp_path / "b.ARW")})

    assert not result.is_error, result.content
    assert (result.structured_content["make"], result.structured_content["model"]) == ("SONY", "ILCE-7M3")
    assert other.is_error and "not_open" in other.content[0].text


async def test_no_selected_history_row_is_null(art, tmp_path):
    art.ops["get_profile"] = answer({"profile": SAMPLE_ARP, "history_position": -1})

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("get_profile", {"path": str(tmp_path / "a.ARW")})

    assert result.structured_content["history_position"] is None


async def test_a_get_profile_reply_without_a_profile_is_bad_reply(art, tmp_path):
    art.ops["get_profile"] = answer({"history_position": 0})

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("get_profile", {"path": str(tmp_path / "a.ARW")})

    assert result.is_error and "bad_reply" in result.content[0].text


async def test_relative_paths_are_made_absolute_but_links_are_not_resolved(art, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    art.ops["get_profile"] = answer({"profile": SAMPLE_ARP, "history_position": 0})

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        await client.call_tool("get_profile", {"path": "a.ARW"})

    assert json.loads(art.received[-1])["args"] == {"path": str(tmp_path / "a.ARW")}


async def test_inspect_without_exiftool_is_metadata_unavailable(art, tmp_path):
    image = tmp_path / "a.ARW"
    image.write_bytes(b"raw")
    art.ops["status"] = answer({"version": "t", "images": [
        {"path": str(image), "active": True, "width": None, "height": None}]})  # fmt: skip

    async with Client(build_server(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("inspect_image", {"path": str(image)})

    assert result.is_error and "metadata_unavailable" in result.content[0].text
