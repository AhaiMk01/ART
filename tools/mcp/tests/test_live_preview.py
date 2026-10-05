import base64
import json
import time
from pathlib import Path

import pytest
from fake_live_art import FakeArt, fail, write_preview
from mcp.client.client import Client

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server
from art_mcp.preview import PreviewFolder

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
def previews(tmp_path):
    return PreviewFolder(tmp_path / "previews")


def requests(art, op):
    return [json.loads(line) for line in art.received[1:] if json.loads(line).get("op") == op]


def images(result):
    return [block for block in result.content if block.type == "image"]


async def test_preview_is_a_jpeg_art_wrote_into_the_servers_preview_folder(art, previews, tmp_path):
    art.ops["preview"] = write_preview(b"\xff\xd8fake jpeg\xff\xd9", width=600, height=400)
    image = tmp_path / "a.ARW"

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "max_size": 800})

    assert not result.is_error, result.content
    out = Path(result.structured_content["path"])
    assert out.parent == previews.root and out.suffix == ".jpg"
    assert result.structured_content == {"path": str(out), "max_size": 800, "width": 600, "height": 400}
    [req] = requests(art, "preview")
    assert req["args"] == {"path": str(image), "output": str(out), "max_size": 800}
    assert not images(result)


async def test_default_max_size_is_1024(art, previews, tmp_path):
    art.ops["preview"] = write_preview(b"jpeg", width=600, height=400)

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW")})

    assert not result.is_error, result.content
    assert requests(art, "preview")[0]["args"]["max_size"] == 1024


@pytest.mark.parametrize("size", [0, 2577])
async def test_max_size_is_between_1_and_2576(art, previews, tmp_path, size):
    art.ops["preview"] = write_preview(b"jpeg", width=1, height=1)

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW"), "max_size": size})

    assert result.is_error and "out_of_range:" in result.content[0].text
    assert not requests(art, "preview")


async def test_image_not_open_is_not_open_and_leaves_no_file(art, previews, tmp_path):
    art.ops["preview"] = fail("not_open", "a.ARW is not open in ART")

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW")})

    assert result.is_error and "not_open:" in result.content[0].text
    assert not list(previews.root.glob("*"))


async def test_art_giving_up_on_a_busy_editor_is_timeout(art, previews, tmp_path):
    art.ops["preview"] = fail("timeout", "ART was still processing after 30 s")

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW")})

    assert result.is_error and result.content[0].text.endswith("timeout: ART was still processing after 30 s")


async def test_the_server_waits_for_art_to_drain_its_queue_beyond_the_channel_timeout(art, previews, tmp_path):
    reply = write_preview(b"jpeg", width=2, height=1)

    def slow(req):
        time.sleep(1.0)  # ART waits for its processing to finish
        return reply(req)

    art.ops["preview"] = slow
    channel = ControlChannel(art.config_dir, timeout=0.5)

    async with Client(build_server(channel, previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW")})

    assert not result.is_error, result.content


async def test_a_reply_without_the_file_is_bad_reply(art, previews, tmp_path):
    art.ops["preview"] = lambda req: (
        json.dumps({"id": req["id"], "ok": True, "result": {"path": req["args"]["output"], "width": 1, "height": 1}})
        + "\n"
    ).encode()

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW")})

    assert result.is_error and "bad_reply:" in result.content[0].text


async def test_previews_are_not_inline_by_default_but_a_call_can_ask(art, previews, tmp_path):
    art.ops["preview"] = write_preview(b"\xff\xd8inline\xff\xd9", width=2, height=1)

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        forced = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW"), "inline": True})

    [block] = images(forced)
    assert base64.b64decode(block.data) == b"\xff\xd8inline\xff\xd9" and block.mime_type == "image/jpeg"
    assert forced.structured_content["path"]


async def test_inline_launch_flag_is_the_default_and_a_call_can_override_it(art, previews, tmp_path):
    art.ops["preview"] = write_preview(b"jpeg", width=2, height=1)
    server = build_server(ControlChannel(art.config_dir), previews=previews, inline_previews=True)

    async with Client(server) as client:
        default = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW")})
        off = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW"), "inline": False})

    assert len(images(default)) == 1
    assert not images(off)


async def test_each_preview_is_a_new_file_and_the_folder_goes_with_the_server(art, previews, tmp_path):
    art.ops["preview"] = write_preview(b"jpeg", width=2, height=1)

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        first = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW")})
        second = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW")})
        assert first.structured_content["path"] != second.structured_content["path"]
        assert Path(first.structured_content["path"]).exists()

    assert not previews.root.exists()


# -- output: keep the preview where the caller says --------------------------


def leftovers(previews):
    return sorted(p.name for p in previews.root.iterdir()) if previews.root.exists() else []


async def test_a_preview_can_be_written_to_a_path_of_the_callers_choice(art, previews, tmp_path):
    art.ops["preview"] = write_preview(b"\xff\xd8look\xff\xd9", width=600, height=400)
    out = tmp_path / "work" / "look.jpg"
    out.parent.mkdir()

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool(
            "render_preview", {"path": str(tmp_path / "a.ARW"), "max_size": 800, "output": str(out), "inline": True}
        )

    assert not result.is_error, result.content
    assert result.structured_content == {"path": str(out), "max_size": 800, "width": 600, "height": 400}
    assert out.read_bytes() == b"\xff\xd8look\xff\xd9"
    [req] = requests(art, "preview")
    assert Path(req["args"]["output"]).parent == previews.root  # ART writes into the server's folder
    assert leftovers(previews) == []  # and the server moved it
    [block] = images(result)
    assert base64.b64decode(block.data) == out.read_bytes()


async def test_an_existing_output_is_refused_unless_overwrite_and_ART_is_not_asked_first(art, previews, tmp_path):
    art.ops["preview"] = write_preview(b"new", width=2, height=1)
    out = tmp_path / "look.jpg"
    out.write_bytes(b"keep me")

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        refused = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW"), "output": str(out)})
        kept = out.read_bytes()
        asked = len(requests(art, "preview"))
        replaced = await client.call_tool(
            "render_preview", {"path": str(tmp_path / "a.ARW"), "output": str(out), "overwrite": True}
        )

    assert refused.is_error and "exists:" in refused.content[0].text
    assert kept == b"keep me" and asked == 0
    assert not replaced.is_error, replaced.content
    assert out.read_bytes() == b"new" and leftovers(previews) == []


@pytest.mark.parametrize(
    ("name", "code"),
    [("missing/look.jpg", "not_found"), ("look.png", "out_of_range"), ("look.jpg", "out_of_range")],
)
async def test_output_needs_an_existing_folder_a_jpeg_name_and_an_absolute_path(art, previews, tmp_path, name, code):
    art.ops["preview"] = write_preview(b"jpeg", width=2, height=1)
    output = name if name == "look.jpg" else str(tmp_path / name)  # "look.jpg" alone is relative

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW"), "output": output})

    assert result.is_error and f"{code}:" in result.content[0].text
    assert not requests(art, "preview")


async def test_a_preview_never_replaces_the_image_it_shows(art, previews, tmp_path):
    art.ops["preview"] = write_preview(b"jpeg", width=2, height=1)
    scan = tmp_path / "scan.JPG"
    scan.write_bytes(b"jpeg scan")

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool(
            "render_preview", {"path": str(scan), "output": str(scan), "overwrite": True}
        )

    assert result.is_error and "exists:" in result.content[0].text
    assert scan.read_bytes() == b"jpeg scan" and not requests(art, "preview")


async def test_art_failing_leaves_nothing_at_output(art, previews, tmp_path):
    art.ops["preview"] = fail("not_open", "a.ARW is not open in ART")
    out = tmp_path / "look.jpg"

    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(tmp_path / "a.ARW"), "output": str(out)})

    assert result.is_error and "not_open:" in result.content[0].text
    assert not out.exists() and leftovers(previews) == []


async def test_the_description_says_what_inline_does_and_defaults_to(art, previews):
    async with Client(build_server(ControlChannel(art.config_dir), previews=previews)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    text = tools["render_preview"].description
    assert "inline" in text and "--inline-previews" in text and "off" in text
    assert "output" in text and "overwrite" in text
