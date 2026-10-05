"""render_preview(marks=...) on the Live server: the editor's preview always shows the whole frame, whose size
comes from the editor's status."""

import base64
import io
import json
from pathlib import Path

import pytest
from fake_live_art import FakeArt, FakeEditor, fail, write_preview
from mcp.client.client import Client
from PIL import Image
from test_marks import square
from test_render_marks import assert_boxed

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server
from art_mcp.marks import Mark
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import Rect

pytestmark = pytest.mark.anyio

GREY = (128, 128, 128)
FRAME = Rect(0, 0, 6000, 4000)


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


@pytest.fixture
def image(tmp_path):
    return tmp_path / "a.ARW"


def requests(art, op):
    return [json.loads(line) for line in art.received[1:] if json.loads(line).get("op") == op]


def jpeg(size):
    buffer = io.BytesIO()
    Image.new("RGB", size, GREY).save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def open_in_editor(art, image, width=6000, height=4000):
    """ART has ``image`` open, with a frame of ``width`` x ``height``."""
    FakeEditor(art).add(str(image), "[Exposure]\nCompensation=0\n", width=width, height=height)


def serve(art, previews, **options):
    return build_server(ControlChannel(art.config_dir), previews=previews, **options)


def picture(result):
    with Image.open(result.structured_content["path"]) as opened:
        return opened.convert("RGB")


async def test_a_mark_is_drawn_where_its_frame_pixels_are_in_the_editors_preview(art, previews, image):
    open_in_editor(art, image)
    art.ops["preview"] = write_preview(jpeg((600, 400)), width=600, height=400)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool(
            "render_preview", {"path": str(image), "marks": [{"x": 3000, "y": 2000, "size": 200}]}
        )
        shown = picture(result)

    assert not result.is_error, result.content
    assert_boxed(shown, (290, 310, 190, 210))  # the square 2900..3100 x 1900..2100 at one pixel per ten
    assert set(result.structured_content) == {"path", "max_size", "width", "height"}


async def test_a_preview_smaller_than_asked_for_scales_the_marks_with_it(art, previews, image):
    open_in_editor(art, image)
    art.ops["preview"] = write_preview(jpeg((300, 200)), width=300, height=200)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool(
            "render_preview", {"path": str(image), "marks": [{"x": 3000, "y": 2000, "size": 200}]}
        )
        shown = picture(result)

    assert square(Mark(x=3000, y=2000, size=200), FRAME, (300, 200)) == (145, 155, 95, 105)
    assert_boxed(shown, (145, 155, 95, 105))


async def test_the_frame_is_the_editors_not_a_guess_from_the_preview(art, previews, image):
    open_in_editor(art, image, width=6016, height=4016)
    art.ops["preview"] = write_preview(jpeg((1024, 684)), width=1024, height=684)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "marks": [{"x": 3008, "y": 2008}]})
        shown = picture(result)

    assert "warnings" not in result.structured_content  # 6016 x 4016 shrunk to 1024 x 684 is the same shape
    assert_boxed(shown, square(Mark(x=3008, y=2008), Rect(0, 0, 6016, 4016), (1024, 684)))


async def test_a_preview_of_another_shape_than_the_frame_is_warned_about(art, previews, image):
    open_in_editor(art, image)
    art.ops["preview"] = write_preview(jpeg((600, 300)), width=600, height=300)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "marks": [{"x": 3000, "y": 2000}]})

    [warning] = result.structured_content["warnings"]
    assert "shape" in warning and "misplaced" in warning


@pytest.mark.parametrize(
    ("marks", "word"),
    [
        ([{"x": 1, "y": 1}] * 65, "64"),
        ([{"x": 1, "y": 1, "size": 1}], "size"),
        ([{"x": 1, "y": 1, "label": "abcde"}], "label"),
    ],
)
async def test_marks_that_are_wrong_in_themselves_are_refused_before_ART_is_asked(art, previews, image, marks, word):
    open_in_editor(art, image)
    art.ops["preview"] = write_preview(jpeg((600, 400)), width=600, height=400)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "marks": marks})

    assert result.is_error and "out_of_range:" in result.content[0].text and word in result.content[0].text
    assert not requests(art, "preview")


async def test_a_mark_outside_the_frame_is_out_of_range_and_leaves_no_file(art, previews, image):
    open_in_editor(art, image)
    art.ops["preview"] = write_preview(jpeg((600, 400)), width=600, height=400)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool(
            "render_preview", {"path": str(image), "marks": [{"x": 10, "y": 10}, {"x": 6000, "y": 10}]}
        )
        left = list(previews.root.iterdir())

    assert result.is_error and "out_of_range:" in result.content[0].text
    assert "mark 2" in result.content[0].text and "6000 x 4000" in result.content[0].text
    assert left == []


async def test_without_a_frame_size_from_the_editor_the_marks_cannot_be_placed(art, previews, image):
    open_in_editor(art, image, width=None, height=None)
    art.ops["preview"] = write_preview(jpeg((600, 400)), width=600, height=400)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "marks": [{"x": 10, "y": 10}]})
        left = list(previews.root.iterdir())

    assert result.is_error and "bad_reply:" in result.content[0].text and "size" in result.content[0].text
    assert left == []


async def test_an_image_ART_does_not_have_open_is_not_open(art, previews, image):
    art.ops["preview"] = fail("not_open", "a.ARW is not open in ART")

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "marks": [{"x": 10, "y": 10}]})

    assert result.is_error and "not_open:" in result.content[0].text
    assert not previews.root.exists() or not list(previews.root.iterdir())


async def test_a_preview_that_is_not_an_image_is_bad_reply_and_leaves_nothing(art, previews, image):
    open_in_editor(art, image)
    art.ops["preview"] = write_preview(b"\xff\xd8not a jpeg\xff\xd9", width=600, height=400)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "marks": [{"x": 10, "y": 10}]})
        left = list(previews.root.iterdir())

    assert result.is_error and "bad_reply:" in result.content[0].text
    assert left == []


async def test_marks_go_into_the_file_at_output_and_the_inline_image(art, previews, image, tmp_path):
    open_in_editor(art, image)
    art.ops["preview"] = write_preview(jpeg((600, 400)), width=600, height=400)
    out = tmp_path / "work" / "look.jpg"
    out.parent.mkdir()

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool(
            "render_preview",
            {"path": str(image), "marks": [{"x": 3000, "y": 2000, "size": 200}], "output": str(out), "inline": True},
        )
        left = sorted(p.name for p in previews.root.iterdir())

    assert not result.is_error, result.content
    assert result.structured_content["path"] == str(out)
    with Image.open(out) as saved:
        assert_boxed(saved.convert("RGB"), (290, 310, 190, 210))
    [block] = [b for b in result.content if b.type == "image"]
    assert base64.b64decode(block.data) == out.read_bytes()
    assert left == []


async def test_candidates_of_suggest_neutrals_can_be_given_as_marks_unchanged(art, previews, image):
    open_in_editor(art, image)
    art.ops["preview"] = write_preview(jpeg((600, 400)), width=600, height=400)
    candidate = {"x": 3000, "y": 2000, "level": 120, "saturation": 0.01, "flatness": 0.02, "why": "flat, neutral"}

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "marks": [candidate]})
        shown = picture(result)

    assert not result.is_error, result.content
    assert_boxed(shown, square(Mark(x=3000, y=2000), FRAME, (600, 400)))


async def test_a_preview_without_marks_is_not_decoded_or_changed(art, previews, image):
    art.ops["preview"] = write_preview(b"\xff\xd8not decoded\xff\xd9", width=600, height=400)

    async with Client(serve(art, previews)) as client:
        result = await client.call_tool("render_preview", {"path": str(image)})
        written = Path(result.structured_content["path"]).read_bytes()

    assert not result.is_error and written == b"\xff\xd8not decoded\xff\xd9"
    assert not requests(art, "status")  # nor is the frame asked for


async def test_the_description_says_what_marks_are(art, previews):
    async with Client(serve(art, previews)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    text = " ".join(tools["render_preview"].description.split())
    for needle in ("marks", "FRAME-pixel", "sample_spots", "label", "1..n", "64", "out_of_range", "whole frame"):
        assert needle in text, needle
