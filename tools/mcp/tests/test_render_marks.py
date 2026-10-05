"""Marks on the Render server's previews: render_preview(marks=...) and suggest_neutrals(preview=true), against
the fake art-cli with decodable JPEGs (FAKE_REAL_JPEG: the fake 6000 x 4000 frame, clamped to the crop and fitted
into the resize box, in one flat colour)."""

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.client.client import Client
from PIL import Image
from test_marks import square
from test_neutrals import patch_of, scene

import art_mcp.render.neutrals_ops as neutrals_ops
from art_mcp.marks import Mark
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli, Rect
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

FRAME = Rect(0, 0, 6000, 4000)
CROP = {"x": 1000, "y": 500, "w": 4000, "h": 2000}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def real_jpegs(monkeypatch):
    monkeypatch.setenv("FAKE_REAL_JPEG", "1")


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "args.log"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(path))
    return path


def make_server(tmp_path, **options):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    return build_server(ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews"), **options)


@pytest.fixture
def server(tmp_path, log):
    return make_server(tmp_path)


def renders(log):
    """The preview renders (a JPEG with -j85) art-cli was asked for so far."""
    return [a for a in map(json.loads, log.read_text().splitlines()) if "-j85" in a]


async def prepare(client, image, *, crop=None):
    await client.call_tool("open_image", {"path": str(image)})
    if crop:
        adjustments = {"crop": {"enabled": True, "fixed_ratio": False, **crop}}
        result = await client.call_tool("edit_profile", {"path": str(image), "adjustments": adjustments})
        assert not result.is_error, result.content


def picture_at(path):
    with Image.open(path) as opened:
        return opened.convert("RGB")


def snap(result):
    """What a preview tool answered, with the picture it names read now: the server removes its preview folder
    when it exits."""
    data = result.structured_content
    path = data.get("path") or data.get("preview_path")
    return SimpleNamespace(
        data=data,
        content=result.content,
        text=result.content[0].text,
        picture=picture_at(path) if path else None,
        bytes=Path(path).read_bytes() if path else None,
    )


async def marked(client, image, marks, **args):
    result = await client.call_tool("render_preview", {"path": str(image), "marks": marks, **args})
    assert not result.is_error, result.content
    return snap(result)


def is_light(pixel):
    return min(pixel) > 190


def is_dark(pixel):
    return max(pixel) < 70


def assert_rings(picture, box):
    """A light ring and a dark one outside the square ``box`` = (left, right, top, bottom)."""
    left, right, top, bottom = box
    middle_x, middle_y = (left + right) // 2, (top + bottom) // 2
    for point in ((left - 1, middle_y), (right, middle_y), (middle_x, top - 1), (middle_x, bottom)):
        assert is_light(picture.getpixel(point)), (box, point, picture.getpixel(point))
    for point in ((left - 2, middle_y), (right + 1, middle_y), (middle_x, top - 2), (middle_x, bottom + 1)):
        assert is_dark(picture.getpixel(point)), (box, point, picture.getpixel(point))


def assert_boxed(picture, box):
    """The rings, and the inside of the square is the (flat) picture's own colour."""
    assert_rings(picture, box)
    left, right, top, bottom = box
    ground = picture.getpixel((2, picture.height - 3))
    centre = picture.getpixel(((left + right) // 2, (top + bottom) // 2))
    assert all(abs(c - g) <= 6 for c, g in zip(centre, ground, strict=True)), (centre, ground)


# -- render_preview --------------------------------------------------------------


async def test_a_mark_is_drawn_where_its_frame_pixels_are_in_the_preview(server, image):
    async with Client(server) as client:
        await prepare(client, image)
        result = await marked(client, image, [{"x": 3000, "y": 2000, "size": 200}], max_size=600)

    assert result.picture.size == (600, 400)  # the fake frame is 6000 x 4000: one preview pixel is ten frame pixels
    assert_boxed(result.picture, (290, 310, 190, 210))  # the square 2900..3100 x 1900..2100
    assert "warnings" not in result.data


async def test_several_marks_at_once_and_the_default_size_is_the_sample_spots_one(server, image):
    async with Client(server) as client:
        await prepare(client, image)
        result = await marked(
            client, image, [{"x": 1000, "y": 1000}, {"x": 5000, "y": 3000, "label": "ref"}], max_size=1200
        )

    assert result.picture.size == (1200, 800)  # 0.2 px per frame px: a square of 32 is 6.4 px
    for mark in (Mark(x=1000, y=1000), Mark(x=5000, y=3000)):
        box = square(mark, FRAME, result.picture.size)
        assert_boxed(result.picture, box)
        assert box[1] - box[0] in (6, 7)


async def test_the_working_profiles_crop_shifts_the_marks(server, image):
    async with Client(server) as client:
        await prepare(client, image, crop=CROP)
        result = await marked(client, image, [{"x": 3000, "y": 1500, "size": 200}], max_size=600)

    assert result.picture.size == (600, 300)  # the crop 4000 x 2000 at 0.15 px per frame px
    # the square 2900..3100 x 1400..1600 is 1900..2100 and 900..1100 from the crop's corner
    assert_boxed(result.picture, (285, 315, 135, 165))
    assert "warnings" not in result.data


async def test_a_region_preview_puts_the_marks_where_the_region_shows_them_and_counts_those_outside(server, image):
    region = {"x": 0.5, "y": 0.5, "w": 0.25, "h": 0.25}  # of the crop: the frame pixels 3000..4000 x 1500..2000
    marks = [{"x": 100, "y": 100}, {"x": 3500, "y": 1750, "size": 100}]
    async with Client(server) as client:
        await prepare(client, image, crop=CROP)
        result = await marked(client, image, marks, region=region, max_size=600)

    picture = result.picture
    assert picture.size == (600, 300)  # 1000 x 500 frame pixels at 0.6 px each
    assert_boxed(picture, (270, 330, 120, 180))
    [warning] = result.data["warnings"]
    assert "1 of 2 marks (1 in request order)" in warning and "not drawn" in warning
    assert "x 3000, y 1500, w 1000, h 500" in warning
    ground = picture.getpixel((2, 2))
    assert all(picture.getpixel((x, y)) == ground for x in range(0, 200, 7) for y in range(0, 300, 7))


async def test_a_mark_in_the_frame_but_outside_the_crop_is_not_drawn_and_not_an_error(server, image):
    async with Client(server) as client:
        await prepare(client, image, crop=CROP)
        result = await marked(client, image, [{"x": 500, "y": 300}], max_size=600)

    [warning] = result.data["warnings"]
    assert "1 of 1 mark " in warning and "x 1000, y 500, w 4000, h 2000" in warning


async def test_a_preview_without_marks_is_what_it_was(server, image):
    async with Client(server) as client:
        await prepare(client, image)
        plain = snap(await client.call_tool("render_preview", {"path": str(image), "max_size": 600}))
        empty = await marked(client, image, [], max_size=600)

    for result in (plain, empty):
        assert set(result.data) == {"path", "max_size"}
        assert result.picture.getpixel((300, 200)) == result.picture.getpixel((0, 0))  # the fake's flat colour
    assert plain.bytes == empty.bytes


@pytest.mark.parametrize(
    ("marks", "word"),
    [
        ([{"x": 1, "y": 1}] * 65, "64"),
        ([{"x": 1, "y": 1, "size": 1}], "size"),
        ([{"x": 1, "y": 1, "size": 257}], "size"),
        ([{"x": 1, "y": 1, "label": "abcde"}], "label"),
        ([{"x": 1, "y": 1}, {"x": 6000, "y": 10}], "mark 2"),
        ([{"x": 10, "y": 4000}], "outside"),
        ([{"x": -1, "y": 10}], "outside"),
    ],
)
async def test_marks_out_of_range_are_refused_before_anything_is_rendered(server, image, log, marks, word):
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("render_preview", {"path": str(image), "marks": marks})

    assert result.is_error and "out_of_range:" in result.content[0].text and word in result.content[0].text
    assert renders(log) == []


async def test_suggest_neutrals_candidates_can_be_given_as_marks_unchanged(server, image):
    candidate = {"x": 3000, "y": 2000, "level": 120, "saturation": 0.01, "flatness": 0.02, "why": "flat, neutral"}
    async with Client(server) as client:
        await prepare(client, image)
        result = await marked(client, image, [candidate], max_size=600)

    assert_boxed(result.picture, square(Mark(x=3000, y=2000), FRAME, (600, 400)))


async def test_marks_go_into_the_file_at_output_and_the_inline_image(server, image, tmp_path):
    out = tmp_path / "work" / "look.jpg"
    out.parent.mkdir()
    async with Client(server) as client:
        await prepare(client, image)
        result = await marked(
            client, image, [{"x": 3000, "y": 2000, "size": 200}], max_size=600, output=str(out), inline=True
        )
        left = sorted(p.name for p in (tmp_path / "previews").iterdir())

    assert result.data["path"] == str(out)
    assert_boxed(picture_at(out), (290, 310, 190, 210))
    [block] = [b for b in result.content if b.type == "image"]
    assert base64.b64decode(block.data) == out.read_bytes()
    assert left == []  # the render was moved to output


async def test_the_marked_preview_is_the_one_file_in_the_preview_folder(server, image, tmp_path):
    async with Client(server) as client:
        await prepare(client, image)
        result = await marked(client, image, [{"x": 3000, "y": 2000}], max_size=600)
        left = sorted(p.name for p in (tmp_path / "previews").iterdir())

    assert left == [Path(result.data["path"]).name]


async def test_a_rendering_that_cannot_be_read_back_is_render_failed_and_leaves_nothing(
    server, image, tmp_path, monkeypatch
):
    monkeypatch.delenv("FAKE_REAL_JPEG")  # the fake's JPEG is then a few bytes, not an image
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("render_preview", {"path": str(image), "marks": [{"x": 1, "y": 1}]})
        left = list((tmp_path / "previews").iterdir())

    assert result.is_error and "render_failed:" in result.content[0].text
    assert left == []


async def test_the_description_says_what_marks_are_in_generic_words(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    tool = tools["render_preview"]
    text = " ".join(tool.description.split())
    for needle in ("marks", "FRAME-pixel", "sample_spots", "suggest_neutrals", "label", "1..n", "64", "out_of_range"):
        assert needle in text, needle
    mark = tool.input_schema["$defs"]["Mark"]
    assert set(mark["properties"]) == {"x", "y", "size", "label"} and mark["required"] == ["x", "y"]
    wording = (text + json.dumps(tool.input_schema)).lower()
    for word in ("film", "negative", "roll", "invert", "holder"):
        assert word not in wording, word


# -- suggest_neutrals(preview=true) ----------------------------------------------


@pytest.fixture
def greys(tmp_path, monkeypatch):
    """The 600 x 400 rendering the fake art-cli returns for the analysis (test_neutrals.scene)."""
    picture, boxes = scene()
    path = tmp_path / "scene.png"
    picture.save(path)
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(path))
    return boxes


async def neutrals(client, image, **args):
    result = await client.call_tool("suggest_neutrals", {"path": str(image), "preview": True, **args})
    assert not result.is_error, result.content
    return snap(result)


async def test_the_preview_is_the_analysed_rendering_with_every_candidate_marked(server, image, greys, tmp_path):
    async with Client(server) as client:
        await prepare(client, image)
        result = await neutrals(client, image, count=8)

    data = result.data
    jpeg = Path(data["preview_path"])
    assert jpeg.parent == tmp_path / "previews" and jpeg.suffix == ".jpg"
    assert result.picture.size == (600, 400)  # the rendering that was analysed
    assert len(data["candidates"]) == 8
    for c in data["candidates"]:
        box = square(Mark(x=c["x"], y=c["y"], size=data["size"]), Rect(*data["area"]), result.picture.size)
        assert_rings(result.picture, box)


async def test_the_candidates_are_marked_in_the_order_of_the_result(server, image, greys, monkeypatch):
    drawn = []
    real = neutrals_ops.draw_marks

    def spy(picture, marks, area):
        drawn.append((list(marks), area))
        return real(picture, marks, area)

    monkeypatch.setattr(neutrals_ops, "draw_marks", spy)
    async with Client(server) as client:
        await prepare(client, image)
        result = await neutrals(client, image, count=6, size=40)

    [(marks, area)] = drawn
    candidates = result.data["candidates"]
    assert [(m.x, m.y, m.size, m.label) for m in marks] == [(c["x"], c["y"], 40, None) for c in candidates]
    assert area == FRAME  # draw_marks numbers them 1..n in this order


async def test_with_a_crop_the_candidates_are_marked_relative_to_it(server, image, greys):
    async with Client(server) as client:
        await prepare(client, image, crop=CROP)
        result = await neutrals(client, image, count=6)

    data = result.data
    assert data["area"] == [1000, 500, 4000, 2000] and data["candidates"]
    for c in data["candidates"]:
        # the fake's rendering is the same 600 x 400 picture, whatever the crop
        assert_rings(result.picture, square(Mark(x=c["x"], y=c["y"]), Rect(1000, 500, 4000, 2000), (600, 400)))
        seen = SimpleNamespace(x=(c["x"] - 1000) * 600 / 4000 * 10, y=(c["y"] - 500) * 400 / 2000 * 10)
        assert patch_of(seen, greys) is not None


async def test_without_preview_there_is_no_preview_path_and_no_file(server, image, greys, tmp_path):
    async with Client(server) as client:
        await prepare(client, image)
        plain = snap(await client.call_tool("suggest_neutrals", {"path": str(image), "count": 4}))
        no = snap(await client.call_tool("suggest_neutrals", {"path": str(image), "count": 4, "preview": False}))
        left = [p.name for p in (tmp_path / "previews").iterdir()]

    for answer in (plain, no):
        assert "preview_path" not in answer.data and "preview_path" not in answer.text and answer.picture is None
    assert not [name for name in left if name.endswith(".jpg")]


async def test_the_image_comes_with_the_result_when_the_server_serves_previews_inline(tmp_path, image, greys):
    async with Client(make_server(tmp_path, inline_previews=True)) as client:
        await prepare(client, image)
        plain = snap(await client.call_tool("suggest_neutrals", {"path": str(image), "count": 4}))
        result = await neutrals(client, image, count=4)

    assert not [b for b in plain.content if b.type == "image"]
    [block] = [b for b in result.content if b.type == "image"]
    assert base64.b64decode(block.data) == result.bytes and block.mime_type == "image/jpeg"


async def test_no_image_comes_with_the_result_unless_the_server_serves_previews_inline(server, image, greys):
    async with Client(server) as client:
        await prepare(client, image)
        result = await neutrals(client, image, count=4)

    assert not [b for b in result.content if b.type == "image"]
    assert result.data["preview_path"]


async def test_with_no_candidates_the_preview_is_still_the_rendering(server, image, tmp_path, monkeypatch):
    flat = tmp_path / "flat.png"
    Image.new("RGB", (600, 400), (255, 0, 0)).save(flat)  # all strongly coloured: no candidate
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(flat))
    async with Client(server) as client:
        await prepare(client, image)
        result = await neutrals(client, image)

    assert result.data["candidates"] == []
    assert result.picture.size == (600, 400) and result.picture.getpixel((300, 200))[0] > 240


async def test_the_description_names_preview_in_generic_words(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    tool = tools["suggest_neutrals"]
    text = " ".join(tool.description.split())
    for needle in ("`preview`", "`preview_path`", "1..n", "boxed"):
        assert needle in text, needle
    assert tool.input_schema["properties"]["preview"]["type"] == "boolean"
    for word in ("film", "negative", "roll", "invert", "holder"):
        assert word not in text.lower(), word
