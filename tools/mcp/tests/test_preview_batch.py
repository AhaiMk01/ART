"""render_preview(paths=[...]): many frames in one call, each rendered like a single preview."""

import base64
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio
REGION = {"x": 0.25, "y": 0.5, "w": 0.5, "h": 0.25}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def photos(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    paths = []
    for index in range(1, 21):
        raw = folder / f"IMG_{index}.ARW"
        raw.write_bytes(b"raw")
        paths.append(str(raw))
    return paths


def server_with(tmp_path, inline=False):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    return build_server(
        ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews"), inline_previews=inline
    )


def image_blocks(result):
    return [block for block in result.content if block.type == "image"]


async def open_all(client, paths):
    for path in paths:
        await client.call_tool("open_image", {"path": path})


def previews_on_disk(tmp_path):
    folder = tmp_path / "previews"
    return sorted(folder.glob("*.jpg")) if folder.exists() else []


async def test_a_batch_returns_one_preview_file_per_image_in_request_order(tmp_path, photos):
    wanted = [photos[2], photos[0], photos[1]]
    async with Client(server_with(tmp_path)) as client:
        await open_all(client, wanted)
        result = await client.call_tool("render_preview", {"paths": wanted})
        assert not result.is_error, result.content
        data = result.structured_content
        assert data["failed"] == 0 and [item["path"] for item in data["items"]] == wanted
        files = [Path(item["preview_path"]) for item in data["items"]]
        assert all(file.is_file() for file in files) and len({str(file) for file in files}) == 3
        assert "path" not in data  # a batch has items, not one path
    assert not image_blocks(result)


async def test_each_frame_of_a_batch_is_rendered_from_its_own_profile(tmp_path, photos):
    first, second = photos[:2]
    Path(second + ".arp").write_text("[Exposure]\nCompensation=1\n")
    async with Client(server_with(tmp_path)) as client:
        await open_all(client, [first, second])
        result = await client.call_tool("render_preview", {"paths": [first, second]})
        a, b = (Path(item["preview_path"]).read_bytes() for item in result.structured_content["items"])
    assert b"Compensation=1" in b and b"Compensation=1" not in a


async def test_max_size_and_region_apply_to_every_frame(tmp_path, photos):
    wanted = photos[:3]
    async with Client(server_with(tmp_path)) as client:
        await open_all(client, wanted)
        result = await client.call_tool(
            "render_preview", {"paths": wanted, "max_size": 640, "region": REGION}
        )
        assert not result.is_error, result.content
        jpegs = [Path(item["preview_path"]).read_bytes() for item in result.structured_content["items"]]
    for jpeg in jpegs:  # the fake image is 6000x4000: the region is 1500,2000 3000x1000 pixels
        assert b"X=1500\nY=2000\nW=3000\nH=1000" in jpeg and b"Width=640" in jpeg


async def test_inline_returns_an_image_per_frame_in_request_order(tmp_path, photos):
    wanted = photos[:3]
    async with Client(server_with(tmp_path)) as client:
        await open_all(client, wanted)
        result = await client.call_tool("render_preview", {"paths": wanted, "inline": True})
        files = [Path(item["preview_path"]).read_bytes() for item in result.structured_content["items"]]
    blocks = image_blocks(result)
    assert len(blocks) == 3 and all(block.mime_type == "image/jpeg" for block in blocks)
    assert [base64.b64decode(block.data) for block in blocks] == files


async def test_the_launch_flag_makes_a_batch_inline_and_a_call_can_turn_it_off(tmp_path, photos):
    wanted = photos[:2]
    async with Client(server_with(tmp_path, inline=True)) as client:
        await open_all(client, wanted)
        default = await client.call_tool("render_preview", {"paths": wanted})
        off = await client.call_tool("render_preview", {"paths": wanted, "inline": False})
    assert len(image_blocks(default)) == 2 and not image_blocks(off)


async def test_an_image_that_is_not_open_is_its_items_error_and_the_others_still_render(tmp_path, photos):
    open_one, not_open, open_two = photos[0], photos[1], photos[2]
    async with Client(server_with(tmp_path, inline=True)) as client:
        await open_all(client, [open_one, open_two])
        result = await client.call_tool("render_preview", {"paths": [open_one, not_open, open_two]})
    assert not result.is_error, result.content
    data = result.structured_content
    assert data["failed"] == 1
    ok_first, bad, ok_second = data["items"]
    assert "preview_path" in ok_first and "preview_path" in ok_second
    assert bad["path"] == not_open and bad["error"].startswith("not_open:") and "preview_path" not in bad
    assert len(image_blocks(result)) == 2  # only the frames that rendered


async def test_the_most_a_batch_takes_is_16_images(tmp_path, photos):
    async with Client(server_with(tmp_path)) as client:
        await open_all(client, photos)
        sixteen = await client.call_tool("render_preview", {"paths": photos[:16]})
        seventeen = await client.call_tool("render_preview", {"paths": photos[:17]})
    assert not sixteen.is_error, sixteen.content
    assert seventeen.is_error and "out_of_range:" in seventeen.content[0].text and "16" in seventeen.content[0].text


BAD_CALLS = [
    ("path or paths", lambda p: {}),
    ("not both", lambda p: {"path": p, "paths": [p]}),
    ("empty", lambda p: {"paths": []}),
    ("marks", lambda p: {"paths": [p], "marks": [{"x": 10, "y": 10}]}),
    ("output", lambda p: {"paths": [p], "output": "C:/x/look.jpg"}),
    ("overwrite", lambda p: {"paths": [p], "overwrite": True}),
    ("max_size", lambda p: {"paths": [p], "max_size": 0}),
    ("region", lambda p: {"paths": [p], "region": {"x": 0.6, "y": 0, "w": 0.5, "h": 0.5}}),
]


@pytest.mark.parametrize("why, make", BAD_CALLS, ids=[why for why, _ in BAD_CALLS])
async def test_a_call_that_is_wrong_as_a_whole_is_out_of_range_before_anything_renders(tmp_path, photos, why, make):
    async with Client(server_with(tmp_path)) as client:
        await open_all(client, photos[:1])
        result = await client.call_tool("render_preview", make(photos[0]))
        assert not previews_on_disk(tmp_path)
    assert result.is_error and "out_of_range:" in result.content[0].text and why in result.content[0].text


async def test_marks_output_and_overwrite_still_work_with_one_path(tmp_path, photos, monkeypatch):
    monkeypatch.setenv("FAKE_REAL_JPEG", "1")  # marks are drawn on a readable JPEG
    out = tmp_path / "look.jpg"
    async with Client(server_with(tmp_path)) as client:
        await open_all(client, photos[:1])
        result = await client.call_tool(
            "render_preview", {"path": photos[0], "output": str(out), "marks": [{"x": 500, "y": 500}]}
        )
    assert not result.is_error, result.content
    assert result.structured_content["path"] == str(out) and out.is_file()


async def test_the_description_and_the_output_schema_cover_the_batch(tmp_path):
    async with Client(server_with(tmp_path)) as client:
        tool = next(t for t in (await client.list_tools()).tools if t.name == "render_preview")
    assert "paths" in tool.description and "16" in tool.description
    assert "paths" in tool.input_schema["properties"]
    assert {"items", "failed"} <= set(tool.output_schema["properties"])
