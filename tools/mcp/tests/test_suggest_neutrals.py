"""suggest_neutrals on the Render server, against the fake art-cli (FAKE_PNG_SOURCE
makes the 8-bit rendering a picture of our choosing)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.client.client import Client
from test_neutrals import patch_of, scene

from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
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
def greys(tmp_path, monkeypatch):
    """The rendering the fake art-cli returns: noise, flat greys, colours
    (test_neutrals.scene); returns the grey patches in preview pixels."""
    picture, boxes = scene()
    path = tmp_path / "scene.png"
    picture.save(path)
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(path))
    return boxes


@pytest.fixture
def render(tmp_path, monkeypatch):
    log = tmp_path / "args.log"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
    config = tmp_path / "config"
    config.mkdir()
    return build_server(ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews")), log


def logged(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


async def prepare(client, image, *, crop=None):
    await client.call_tool("open_image", {"path": str(image)})
    if crop:
        adjustments = {"crop": {"enabled": True, "fixed_ratio": False, **crop}}
        result = await client.call_tool("edit_profile", {"path": str(image), "adjustments": adjustments})
        assert not result.is_error, result.content


async def test_candidates_are_in_the_flat_grey_patches_of_the_rendering(render, image, greys):
    server, log = render
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("suggest_neutrals", {"path": str(image), "count": 8})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data["area"] == [0, 0, 6000, 4000] and data["size"] == 32
    assert len(data["candidates"]) == 8
    levels = [c["level"] for c in data["candidates"]]
    assert levels == sorted(levels) and min(levels) < 70 and max(levels) > 180

    patches = [patch_of(SimpleNamespace(x=c["x"], y=c["y"]), greys) for c in data["candidates"]]
    assert None not in patches and len(set(patches)) >= 4
    [call] = [a for a in logged(log) if "-b8" in a]
    assert "-n" in call and "-f" in call and call[call.index("-o") + 1].endswith(".png")


async def test_the_crop_is_the_area_and_candidates_map_back_to_frame_pixels(render, image, greys):
    server, _ = render
    crop = {"x": 1000, "y": 500, "w": 4000, "h": 2000}
    async with Client(server) as client:
        await prepare(client, image, crop=crop)
        result = await client.call_tool("suggest_neutrals", {"path": str(image), "count": 6})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data["area"] == [1000, 500, 4000, 2000]
    assert data["candidates"]
    for c in data["candidates"]:
        assert 1000 <= c["x"] < 5000 and 500 <= c["y"] < 2500
        # the fake's rendering is the same 600 x 400 picture, so it covers the crop
        px, py = (c["x"] - 1000) * 600 / 4000, (c["y"] - 500) * 400 / 2000
        assert patch_of(SimpleNamespace(x=px * 10, y=py * 10), greys) is not None, (c, px, py)
    assert not [w for w in data["warnings"] if "crop" in w]


async def test_warns_when_there_is_no_crop(render, image, greys):
    server, _ = render
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("suggest_neutrals", {"path": str(image)})

    warnings = result.structured_content["warnings"]
    assert len(warnings) == 1 and "no crop" in warnings[0], warnings


async def test_no_warning_with_a_crop(render, image, greys):
    server, _ = render
    async with Client(server) as client:
        await prepare(client, image, crop={"x": 500, "y": 300, "w": 5000, "h": 3400})
        result = await client.call_tool("suggest_neutrals", {"path": str(image), "count": 4})

    assert result.structured_content["warnings"] == []


async def test_says_so_when_fewer_candidates_than_asked_for_were_found(render, image, tmp_path, monkeypatch):
    from PIL import Image

    flat = tmp_path / "flat.png"
    Image.new("RGB", (600, 400), (255, 0, 0)).save(flat)  # all strongly coloured
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(flat))
    server, _ = render
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("suggest_neutrals", {"path": str(image)})

    data = result.structured_content
    assert not result.is_error and data["candidates"] == []
    assert any("0 of 16" in w for w in data["warnings"]), data["warnings"]


async def test_candidates_can_be_given_to_sample_spots_as_they_are(render, image, greys):
    server, _ = render
    async with Client(server) as client:
        await prepare(client, image)
        found = await client.call_tool("suggest_neutrals", {"path": str(image), "count": 6, "size": 40})
        sampled = await client.call_tool(
            "sample_spots", {"path": str(image), "spots": found.structured_content["candidates"], "size": 40}
        )

    assert not sampled.is_error, sampled.content
    assert [(s["x"], s["y"]) for s in sampled.structured_content["spots"]] == [
        (c["x"], c["y"]) for c in found.structured_content["candidates"]
    ]


async def test_a_candidate_is_about_forty_tokens(render, image, greys):
    server, _ = render
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("suggest_neutrals", {"path": str(image), "count": 16})

    candidates = result.structured_content["candidates"]
    assert len(candidates) == 16
    per = len(json.dumps(candidates, separators=(",", ":"))) / 4 / len(candidates)
    assert per < 45, per


@pytest.mark.parametrize(
    "arguments",
    [{"count": 0}, {"count": 17}, {"size": 1}, {"size": 257}],
)
async def test_validates_before_rendering(render, image, greys, arguments):
    server, log = render
    async with Client(server) as client:
        await prepare(client, image)
        before = len(logged(log))
        result = await client.call_tool("suggest_neutrals", {"path": str(image), **arguments})

    assert result.is_error and "out_of_range:" in result.content[0].text
    assert not [a for a in logged(log)[before:] if "-b8" in a]


async def test_a_size_larger_than_the_area_is_out_of_range(render, image, greys):
    server, _ = render
    async with Client(server) as client:
        await prepare(client, image, crop={"x": 0, "y": 0, "w": 150, "h": 150})
        result = await client.call_tool("suggest_neutrals", {"path": str(image), "size": 200})
    assert result.is_error and "out_of_range:" in result.content[0].text


async def test_not_open(render, image, greys):
    server, _ = render
    async with Client(server) as client:
        result = await client.call_tool("suggest_neutrals", {"path": str(image)})
    assert result.is_error and "not_open" in result.content[0].text


async def test_an_unreadable_rendering_is_render_failed_and_leaves_nothing(render, image, tmp_path, monkeypatch):
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not a png")
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(junk))
    server, _ = render
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("suggest_neutrals", {"path": str(image)})

    assert result.is_error and "render_failed:" in result.content[0].text
    assert not list((tmp_path / "previews").glob("neutrals-*"))


async def test_leaves_no_temporary_files(render, image, greys, tmp_path):
    server, _ = render
    async with Client(server) as client:
        await prepare(client, image)
        await client.call_tool("suggest_neutrals", {"path": str(image)})
        left = [p for p in (tmp_path / "previews").iterdir() if p.name.startswith(("neutrals", "profile", "resize"))]
        assert not left


async def test_the_description_calls_it_a_pre_filter_and_leaves_the_material_to_the_agent(render):
    server, _ = render
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    text = " ".join(tools["suggest_neutrals"].description.split())
    for needle in ("PRE-FILTER", "MATERIAL", "sample_spots", "crop", "dark to light", "roughly colour-correct"):
        assert needle in text, needle


async def test_the_tool_is_generic_nothing_in_it_is_about_film(render, image, greys):
    server, _ = render
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        await prepare(client, image)
        result = await client.call_tool("suggest_neutrals", {"path": str(image)})

    tool = tools["suggest_neutrals"]
    wording = " ".join([tool.name, tool.description, json.dumps(tool.input_schema), json.dumps(tool.output_schema)])
    wording += json.dumps(result.structured_content)
    for word in ("film", "negative", "roll", "invert", "RedRatio", "RefInput", "holder"):
        assert word.lower() not in wording.lower(), word
