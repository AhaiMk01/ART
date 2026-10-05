"""The Live server's export queue tools, against a fake ART editor and queue,
through an in-process MCP client."""

import pytest
from fake_live_art import FakeArt, FakeEditor
from mcp.client.client import Client

from art_mcp import keyfile
from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def art(tmp_path):
    fake = FakeArt(tmp_path / "config")
    yield fake
    fake.close()


@pytest.fixture
def editor(art, tmp_path):
    editor = FakeEditor(art)
    editor.add(str(tmp_path / "FILM_1.ARW"), "[Exposure]\nCompensation=0\n")
    editor.add(str(tmp_path / "FILM_2.ARW"), "[Exposure]\nCompensation=0\n")
    return editor


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def live(art):
    return build_server(ControlChannel(art.config_dir))


def text_of(result):
    return result.content[0].text


async def test_queue_export_queues_the_open_image_with_its_output_and_format(art, editor, tmp_path, out):
    async with Client(live(art)) as client:
        result = await client.call_tool("queue_export", {
            "path": str(tmp_path / "FILM_1.ARW"), "folder": str(out), "format": "jpeg", "quality": 90,
        })  # fmt: skip

    assert not result.is_error, result.content
    assert result.structured_content == {"queued": 1, "running": False}
    sent = editor.queue[0]["args"]
    assert sent["path"] == str(tmp_path / "FILM_1.ARW")
    assert sent["output"] == str(out / "FILM_1.jpg")
    assert sent["format"] == "jpg" and sent["quality"] == "90"
    assert "profile" not in sent


async def test_queue_export_without_a_folder_leaves_naming_to_the_queue(art, editor, tmp_path):
    async with Client(live(art)) as client:
        result = await client.call_tool("queue_export", {"path": str(tmp_path / "FILM_1.ARW")})

    assert not result.is_error, result.content
    assert editor.queue[0]["args"] == {"path": str(tmp_path / "FILM_1.ARW")}


async def test_name_pattern_and_tiff_depth(art, editor, tmp_path, out):
    async with Client(live(art)) as client:
        await client.call_tool("queue_export", {
            "path": str(tmp_path / "FILM_2.ARW"), "folder": str(out), "format": "tiff",
            "name": "{stem}-v2", "bit_depth": "16f",
        })  # fmt: skip

    sent = editor.queue[0]["args"]
    assert sent["output"] == str(out / "FILM_2-v2.tif")
    assert sent["format"] == "tif" and sent["bit_depth"] == "16f"


async def test_a_profile_file_goes_over_the_working_profile(art, editor, tmp_path):
    preset = tmp_path / "roll.arp"
    preset.write_text("[Film Negative]\nEnabled=true\n")
    async with Client(live(art)) as client:
        await client.call_tool("queue_export", {"path": str(tmp_path / "FILM_1.ARW"), "profile": str(preset)})

    assert keyfile.loads(editor.queue[0]["args"]["profile"]) == {"Film Negative": {"Enabled": "true"}}


async def test_bad_requests_are_refused_before_ART_sees_them(art, editor, tmp_path, out):
    image = str(tmp_path / "FILM_1.ARW")
    async with Client(live(art)) as client:
        no_folder = await client.call_tool(
            "queue_export", {"path": image, "folder": str(tmp_path / "nope"), "format": "png"}
        )
        no_format = await client.call_tool("queue_export", {"path": image, "folder": str(out)})
        bad_quality = await client.call_tool("queue_export", {"path": image, "format": "png", "quality": 90})
        no_profile = await client.call_tool("queue_export", {"path": image, "profile": str(tmp_path / "x.arp")})
        bad_name = await client.call_tool(
            "queue_export", {"path": image, "folder": str(out), "format": "png", "name": "a/b"}
        )

    assert no_folder.is_error and "not_found" in text_of(no_folder)
    assert no_format.is_error and "out_of_range" in text_of(no_format)
    assert bad_quality.is_error and "out_of_range" in text_of(bad_quality)
    assert no_profile.is_error and "not_found" in text_of(no_profile)
    assert bad_name.is_error and "out_of_range" in text_of(bad_name)
    assert editor.queue == []


async def test_an_image_that_is_not_open_is_ARTs_error(art, editor, tmp_path):
    async with Client(live(art)) as client:
        result = await client.call_tool("queue_export", {"path": str(tmp_path / "other.ARW")})

    assert result.is_error and "not_open" in text_of(result)


async def test_queue_start_and_status(art, editor, tmp_path):
    image = str(tmp_path / "FILM_1.ARW")
    async with Client(live(art)) as client:
        empty = await client.call_tool("queue_start", {})
        await client.call_tool("queue_export", {"path": image})
        before = await client.call_tool("queue_status", {})
        started = await client.call_tool("queue_start", {})
        again = await client.call_tool("queue_start", {})

    assert empty.is_error and "empty_queue" in text_of(empty)
    assert before.structured_content == {
        "running": False, "auto_start": False,
        "entries": [{"path": image, "output": None, "state": "queued", "progress": 0.0, "error": None}],
    }  # fmt: skip
    assert started.structured_content == {"running": True, "already_running": False}
    assert again.structured_content == {"running": True, "already_running": True}


async def test_status_reports_a_failed_entry_with_its_error(art, editor, tmp_path):
    image = str(tmp_path / "FILM_1.ARW")
    async with Client(live(art)) as client:
        await client.call_tool("queue_export", {"path": image})
        editor.queue[0].update(state="failed", error="Cannot save: disk full")
        status = await client.call_tool("queue_status", {})

    entry = status.structured_content["entries"][0]
    assert entry["state"] == "failed" and entry["error"] == "Cannot save: disk full"
