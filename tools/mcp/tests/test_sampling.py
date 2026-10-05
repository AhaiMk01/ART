"""sample_spots and image_stats on both servers, plus the pure statistics."""

import json
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client
from PIL import Image

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server as build_render
from art_mcp.sampling import image_stats
from fake_live_art import FakeArt, FakeEditor, answer, fail, write_preview

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

EDITOR_PROFILE = "[Exposure]\nCompensation=0\n"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def known_png(tmp_path):
    """100 pixels: 5 white, 10 black, 85 of (100, 150, 200)."""
    img = Image.new("RGB", (10, 10))
    img.putdata([(255, 255, 255)] * 5 + [(0, 0, 0)] * 10 + [(100, 150, 200)] * 85)
    path = tmp_path / "known.png"
    img.save(path)
    return path


def check_known_stats(stats, histogram):
    assert (stats["width"], stats["height"]) == (10, 10)
    r, g, b, lum = stats["r"], stats["g"], stats["b"], stats["lum"]
    for channel in (r, g, b, lum):
        assert channel["clipped_high"] == 0.05 and channel["clipped_low"] == 0.10
        # N=100, nearest rank: 10 zeros, then 85 mid values, then 5 at 255.
        assert [channel["percentiles"][p] for p in ("0.1", "1", "5")] == [0, 0, 0]
    # means by hand: (85 * v + 5 * 255) / 100
    assert (r["mean"], g["mean"], b["mean"]) == (97.75, 140.25, 182.75)
    # mid luma 0.2126*100 + 0.7152*150 + 0.0722*200 = 142.98 -> 143; (85*143 + 1275)/100
    assert lum["mean"] == 134.3
    assert [r["percentiles"][p] for p in ("50", "95", "99", "99.9")] == [100, 100, 255, 255]
    assert [g["percentiles"][p] for p in ("50", "95", "99", "99.9")] == [150, 150, 255, 255]
    assert [lum["percentiles"][p] for p in ("50", "95", "99", "99.9")] == [143, 143, 255, 255]
    if histogram:
        assert len(r["histogram"]) == 256
        assert (r["histogram"][0], r["histogram"][100], r["histogram"][255]) == (10, 85, 5)
        assert lum["histogram"][143] == 85
    else:
        assert r["histogram"] is None and lum["histogram"] is None


def test_stats_of_a_known_image(known_png):
    check_known_stats(image_stats(known_png, histogram=True).model_dump(), True)
    check_known_stats(image_stats(known_png).model_dump(), False)


def test_percentile_nearest_rank_on_a_ramp(tmp_path):
    img = Image.new("L", (256, 4))
    img.putdata([v for v in range(256) for _ in range(4)])  # each value 4 times, N=1024
    path = tmp_path / "ramp.png"
    img.save(path)
    stats = image_stats(path)
    # rank ceil(0.5 * 1024) = 512 -> value 127; 99.9%: rank 1024 -> 255;
    # 1%: rank ceil(10.24) = 11 -> value 2
    assert stats.r.percentiles["50"] == 127 and stats.r.percentiles["99.9"] == 255
    assert stats.r.percentiles["1"] == 2
    assert stats.r.clipped_low == 4 / 1024


def test_unreadable_image_is_a_value_error(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    with pytest.raises(ValueError):
        image_stats(bad)


# -- Render server ---------------------------------------------------------------


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def render(tmp_path, monkeypatch):
    log = tmp_path / "args.log"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
    config = tmp_path / "config"
    config.mkdir()
    server = build_render(
        ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews")
    )
    return server, log


def logged(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


async def test_render_sample_spots_runs_x_without_an_output_file(render, image):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool(
            "sample_spots",
            {"path": str(image), "spots": [{"x": 10, "y": 20}, {"x": 5999, "y": 3999}], "size": 8},
        )

    assert not result.is_error, result.content
    assert result.structured_content == {
        "width": 6000, "height": 4000, "space": "working", "size": 8,
        "spots": [
            {"x": 10, "y": 20, "avg": [10, 20, 8], "max": [11, 21, 9]},
            {"x": 5999, "y": 3999, "avg": [5999, 3999, 8], "max": [6000, 4000, 9]},
        ],
    }  # fmt: skip
    [call] = [a for a in logged(log) if "-x" in a]
    assert call[call.index("-x") + 1] == "8,working,10,20,5999,3999"
    assert "-o" not in call and "-O" not in call and "-p" in call
    assert call[call.index("-c") + 1] == str(image)


async def test_render_sample_spots_default_size_and_input_space(render, image):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool(
            "sample_spots", {"path": str(image), "spots": [{"x": 1, "y": 2}], "space": "input"}
        )

    assert result.structured_content["size"] == 32 and result.structured_content["space"] == "input"
    [call] = [a for a in logged(log) if "-x" in a]
    assert call[call.index("-x") + 1] == "32,input,1,2"


@pytest.mark.parametrize(
    "arguments",
    [
        {"spots": [{"x": 6000, "y": 0}]},
        {"spots": [{"x": 0, "y": 4000}]},
        {"spots": [{"x": -1, "y": 0}]},
        {"spots": []},
        {"spots": [{"x": 1, "y": 1}] * 17},
        {"spots": [{"x": 1, "y": 1}], "size": 1},
        {"spots": [{"x": 1, "y": 1}], "size": 257},
        {"spots": [{"x": 1, "y": 1}], "space": "srgb"},
    ],
)
async def test_render_sample_spots_validates_before_running(render, image, arguments):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("sample_spots", {"path": str(image), **arguments})

    assert result.is_error and "out_of_range:" in result.content[0].text
    assert not [a for a in logged(log)[before:] if "-x" in a]


@pytest.mark.parametrize("mode", ["release", "silent"])
async def test_render_sample_spots_without_fork_support_is_unsupported(render, image, monkeypatch, mode):
    server, _ = render
    monkeypatch.setenv("FAKE_SPOTS", mode)
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": [{"x": 1, "y": 1}]})

    assert result.is_error
    assert "unsupported: needs an ART build" in result.content[0].text
    assert "needs an ART build with spot sampling" in result.content[0].text


async def test_render_sample_spots_not_open(render, image):
    server, _ = render
    async with Client(server) as client:
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": [{"x": 1, "y": 1}]})
    assert result.is_error and "not_open" in result.content[0].text


async def test_sample_spots_description_is_generic_and_points_at_the_skills(render):
    server, _ = render
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    text = tools["sample_spots"].description
    for needle in ("crop.x", "ColorSpace", "0..65535", "film-negative and faded-slide skills"):
        assert needle in text
    for gone in ("RedRatio", "RefInput", "RefOutput", "65535/24"):
        assert gone not in text


@pytest.mark.parametrize("histogram", [False, True])
async def test_render_image_stats_of_a_known_image(render, image, known_png, monkeypatch, histogram, tmp_path):
    server, log = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(known_png))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("image_stats", {"path": str(image), "histogram": histogram})

    assert not result.is_error, result.content
    check_known_stats(result.structured_content, histogram)
    [call] = [a for a in logged(log) if "-b8" in a]
    assert "-f" in call and "-n" in call and call[call.index("-o") + 1].endswith(".png")
    assert not list((tmp_path / "previews").glob("stats-*"))


async def test_render_image_stats_beyond_the_fast_box_does_not_use_f(render, image, known_png, monkeypatch):
    server, log = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(known_png))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("image_stats", {"path": str(image), "max_size": 2000})

    assert not result.is_error, result.content
    [call] = [a for a in logged(log) if "-b8" in a]
    assert "-f" not in call


@pytest.mark.parametrize("size", [0, 2577])
async def test_render_image_stats_max_size_range(render, image, size):
    server, _ = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("image_stats", {"path": str(image), "max_size": size})
    assert result.is_error and "out_of_range:" in result.content[0].text


# -- Live server --------------------------------------------------------------------


@pytest.fixture
def art(tmp_path):
    fake = FakeArt(tmp_path / "config")
    yield fake
    fake.close()


def requests(art, op):
    return [json.loads(line) for line in art.received[1:] if json.loads(line).get("op") == op]


async def test_live_sample_spots_sends_the_op_and_returns_its_result(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    values = {"x": 7, "y": 9, "avg": [100.5, 200, 300], "max": [110, 210, 310]}
    art.ops["sample_spots"] = answer({"width": 6000, "height": 4000, "spots": [values]})

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool(
            "sample_spots", {"path": photo, "spots": [{"x": 7, "y": 9}], "size": 16, "space": "input"}
        )

    assert not result.is_error, result.content
    assert result.structured_content == {
        "width": 6000, "height": 4000, "space": "input", "size": 16, "spots": [values],
    }  # fmt: skip
    [req] = requests(art, "sample_spots")
    assert req["args"] == {"path": photo, "spots": [[7, 9]], "size": 16, "space": "input"}


@pytest.mark.parametrize(
    "arguments",
    [
        {"spots": [{"x": 6000, "y": 0}]},
        {"spots": []},
        {"spots": [{"x": 1, "y": 1}], "size": 1},
        {"spots": [{"x": 1, "y": 1}], "space": "srgb"},
    ],
)
async def test_live_sample_spots_validates_before_asking_art(art, tmp_path, arguments):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    art.ops["sample_spots"] = answer({"width": 1, "height": 1, "spots": []})

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, **arguments})

    assert result.is_error and "out_of_range:" in result.content[0].text
    assert not requests(art, "sample_spots")


async def test_live_sample_spots_skips_the_frame_check_while_size_unknown(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE, width=None, height=None)
    art.ops["sample_spots"] = answer({"width": 100, "height": 100, "spots": []})

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": [{"x": 99999, "y": 1}]})

    assert not result.is_error, result.content
    assert requests(art, "sample_spots")


async def test_live_sample_spots_art_errors_pass_through(art, tmp_path):
    art.ops["sample_spots"] = fail("not_open", "a.ARW is not open in ART")
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool(
            "sample_spots", {"path": str(tmp_path / "a.ARW"), "spots": [{"x": 1, "y": 1}]}
        )
    assert result.is_error and "not_open:" in result.content[0].text


async def test_live_sample_spots_garbled_reply_is_bad_reply(art, tmp_path):
    art.ops["sample_spots"] = answer("nonsense")
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool(
            "sample_spots", {"path": str(tmp_path / "a.ARW"), "spots": [{"x": 1, "y": 1}]}
        )
    assert result.is_error and "bad_reply:" in result.content[0].text


@pytest.mark.parametrize("histogram", [False, True])
async def test_live_image_stats_asks_for_a_png_preview(art, tmp_path, known_png, histogram):
    previews = PreviewFolder(tmp_path / "previews")
    art.ops["preview"] = write_preview(known_png.read_bytes(), width=10, height=10)

    async with Client(build_live(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool(
            "image_stats", {"path": str(tmp_path / "a.ARW"), "max_size": 800, "histogram": histogram}
        )

    assert not result.is_error, result.content
    check_known_stats(result.structured_content, histogram)
    [req] = requests(art, "preview")
    assert req["args"]["output"].endswith(".png") and req["args"]["max_size"] == 800
    assert not list((tmp_path / "previews").glob("*.png"))


async def test_live_image_stats_unreadable_preview_is_bad_reply(art, tmp_path):
    previews = PreviewFolder(tmp_path / "previews")
    art.ops["preview"] = write_preview(b"not a png", width=1, height=1)
    async with Client(build_live(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool("image_stats", {"path": str(tmp_path / "a.ARW")})
    assert result.is_error and "bad_reply:" in result.content[0].text
    assert not list((tmp_path / "previews").glob("*.png"))


async def test_live_sample_spots_retries_while_art_is_busy(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    busy = fail("busy", "the editor is processing")
    ready = answer({"width": 6000, "height": 4000, "spots": []})
    replies = [busy, busy, ready]
    art.ops["sample_spots"] = lambda req: replies.pop(0)(req)

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": [{"x": 1, "y": 1}]})

    assert not result.is_error, result.content
    assert len(requests(art, "sample_spots")) == 3


async def test_live_sample_spots_unknown_op_is_unsupported(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    art.ops["sample_spots"] = fail("unknown_op", "no such op")

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": [{"x": 1, "y": 1}]})

    assert result.is_error
    assert "unsupported: needs an ART build with spot sampling" in result.content[0].text
