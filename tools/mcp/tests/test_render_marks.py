"""Marks on the Render server's previews: render_preview(marks=...), against
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
        assert set(result.data) == {"path", "max_size", "width", "height", "shown"}
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


async def test_extra_fields_of_a_mark_are_ignored(server, image):
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
    for needle in ("marks", "FRAME-pixel", "sample_spots", "label", "1..n", "64", "out_of_range"):
        assert needle in text, needle
    mark = tool.input_schema["$defs"]["Mark"]
    assert set(mark["properties"]) == {"x", "y", "size", "label"} and mark["required"] == ["x", "y"]
    wording = (text + json.dumps(tool.input_schema)).lower()
    for word in ("film", "negative", "roll", "invert", "holder"):
        assert word not in wording, word


# -- the mapping a preview returns (width, height, shown) -----------------------


def mapped(data, px, py):
    """The frame pixel a JPEG pixel is, by the documented formula."""
    shown = data["shown"]
    return shown["x"] + px * shown["w"] / data["width"], shown["y"] + py * shown["h"] / data["height"]


async def test_a_whole_image_preview_says_which_frame_pixels_it_shows(server, image):
    async with Client(server) as client:
        await prepare(client, image)
        result = snap(await client.call_tool("render_preview", {"path": str(image), "max_size": 600}))

    assert result.data["shown"] == {"x": 0, "y": 0, "w": 6000, "h": 4000}
    assert (result.data["width"], result.data["height"]) == result.picture.size == (600, 400)
    assert mapped(result.data, 300, 200) == (3000, 2000)


async def test_a_cropped_preview_shows_the_crop_and_a_region_part_of_it(server, image):
    async with Client(server) as client:
        await prepare(client, image, crop=CROP)
        whole = snap(await client.call_tool("render_preview", {"path": str(image), "max_size": 800}))
        part = snap(
            await client.call_tool(
                "render_preview", {"path": str(image), "region": {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}}
            )
        )

    assert whole.data["shown"] == CROP and (whole.data["width"], whole.data["height"]) == (800, 400)
    assert mapped(whole.data, 400, 200) == (3000, 1500)
    assert part.data["shown"] == {"x": 3000, "y": 1500, "w": 2000, "h": 1000}
    assert (part.data["width"], part.data["height"]) == part.picture.size


async def test_a_batch_item_and_a_stage_view_carry_their_own_mapping(server, image):
    async with Client(server) as client:
        await prepare(client, image, crop=CROP)
        batch = await client.call_tool("render_preview", {"paths": [str(image)], "max_size": 400})
        stage = await client.call_tool("render_preview", {"path": str(image), "stage": "converted", "max_size": 400})

    [item] = batch.structured_content["items"]
    assert item["shown"] == CROP and (item["width"], item["height"]) == (400, 200)
    if not stage.is_error:  # the fake art-cli may not write a stage JPEG
        assert stage.structured_content["shown"] == CROP


# -- zoom: a sheet of enlarged tiles, one per mark ------------------------------


async def zoomed(client, image, marks, **args):
    result = await client.call_tool("render_preview", {"path": str(image), "marks": marks, "zoom": True, **args})
    return result


async def test_zoom_returns_one_sheet_with_a_tile_per_mark_and_one_full_size_render(server, image, log):
    marks = [{"x": 3000, "y": 2000, "size": 40}, {"x": 100, "y": 50, "size": 20, "label": "ab"}]
    async with Client(server) as client:
        await prepare(client, image)
        result = await zoomed(client, image, marks, max_size=100)
        assert not result.is_error, result.content
        data = snap(result)

    assert len(renders(log)) == 1  # one render for all tiles
    first, second = data.data["tiles"]
    assert first["label"] == "1" and second["label"] == "ab"
    assert first["window"] == {"x": 2840, "y": 1840, "w": 320, "h": 320}  # 8 x 40, centred
    assert second["window"] == {"x": 20, "y": 0, "w": 160, "h": 160}  # at least 160, moved inside the frame
    assert first["size"] == 320 and (first["left"], first["top"]) != (second["left"], second["top"])
    assert "shown" not in data.data and (data.data["width"], data.data["height"]) == data.picture.size
    # the first mark's square is 40 frame px = 40 tile px at one frame pixel per tile pixel: boxed in the tile
    tile = data.picture.crop((first["left"], first["top"], first["left"] + 320, first["top"] + 320))
    assert_boxed(tile, (140, 180, 140, 180))


async def test_zoom_tiles_wrap_into_rows_of_four(server, image):
    marks = [{"x": 500 + 100 * n, "y": 500} for n in range(5)]
    async with Client(server) as client:
        await prepare(client, image)
        data = snap(await zoomed(client, image, marks))

    tiles = data.data["tiles"]
    lefts = [t["left"] for t in tiles[:4]]
    assert lefts == sorted(set(lefts)) and tiles[4]["left"] == lefts[0]
    assert tiles[4]["top"] > tiles[0]["top"] == tiles[3]["top"]


@pytest.mark.parametrize(
    "args",
    [
        {"marks": []},
        {"marks": [{"x": 5, "y": 5}], "region": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}},
        {"marks": [{"x": 5, "y": 5}], "stage": "converted"},
    ],
)
async def test_zoom_needs_marks_and_neither_region_nor_stage(server, image, args):
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("render_preview", {"path": str(image), "zoom": True, **args})

    assert result.is_error and "out_of_range" in result.content[0].text


async def test_zoom_with_paths_is_refused(server, image):
    async with Client(server) as client:
        await prepare(client, image)
        result = await client.call_tool("render_preview", {"paths": [str(image)], "zoom": True})

    assert result.is_error and "out_of_range" in result.content[0].text


async def test_zoom_refuses_a_mark_outside_the_cropped_area(server, image):
    async with Client(server) as client:
        await prepare(client, image, crop=CROP)
        result = await zoomed(client, image, [{"x": 10, "y": 10}])

    assert result.is_error and "out_of_range" in result.content[0].text and "mark 1" in result.content[0].text
