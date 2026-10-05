"""sample_spots and image_stats on both servers, plus the pure statistics."""

import json
import sys
from pathlib import Path

import pytest
from fake_live_art import FakeArt, FakeEditor, answer, fail, write_preview
from mcp.client.client import Client
from PIL import Image

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli, Rect, region_rect
from art_mcp.render.preview_tools import Region
from art_mcp.render.server import build_server as build_render
from art_mcp.sampling import RegionTooSmall, check_stats_bins, image_stats

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


# -- a region of the image ------------------------------------------------------


def save_pixels(path, size, pixel):
    """A PNG of `size` whose pixel (x, y) is `pixel(x, y)`."""
    width, height = size
    img = Image.new("RGB", size)
    img.putdata([pixel(x, y) for y in range(height) for x in range(width)])
    img.save(path)
    return path


@pytest.fixture
def lamps(tmp_path):
    """20 x 10: a bright left half (200, the 20 pixels of its top two rows
    at 255: the lamps) and a dark right half (20, its 10 bottom-row pixels at 0)."""

    def pixel(x, y):
        if x < 10:
            return (255,) * 3 if y < 2 else (200,) * 3
        return (0,) * 3 if y == 9 else (20,) * 3

    return save_pixels(tmp_path / "lamps.png", (20, 10), pixel)


LEFT = {"x": 0, "y": 0, "w": 0.5, "h": 1}
RIGHT = {"x": 0.5, "y": 0, "w": 0.5, "h": 1}
BELOW_THE_LAMPS = {"x": 0, "y": 0.2, "w": 0.5, "h": 0.8}
LEFT_PIXELS = {"x": 0, "y": 0, "w": 10, "h": 10}
RIGHT_PIXELS = {"x": 10, "y": 0, "w": 10, "h": 10}


def check_lamp_halves(whole, left, right):
    """The results for `lamps` (as dicts): the halves differ from the whole and
    match what each half alone holds, by hand."""
    # whole: (80 * 200 + 20 * 255 + 90 * 20 + 10 * 0) / 200 pixels
    assert whole["r"]["mean"] == 114.5
    assert whole["r"]["clipped_high"] == 0.1 and whole["r"]["clipped_low"] == 0.05
    # left: (80 * 200 + 20 * 255) / 100, the lamps being 20 % of it
    assert left["r"]["mean"] == 211.0 and left["lum"]["mean"] == 211.0
    assert left["r"]["clipped_high"] == 0.2 and left["r"]["clipped_low"] == 0
    assert [left["r"]["percentiles"][p] for p in ("0.1", "50", "95", "99.9")] == [200, 200, 255, 255]
    # right: (90 * 20 + 10 * 0) / 100; nothing clipped high
    assert right["r"]["mean"] == 18.0
    assert right["r"]["clipped_high"] == 0 and right["r"]["clipped_low"] == 0.1
    assert [right["r"]["percentiles"][p] for p in ("0.1", "50", "99.9")] == [0, 20, 20]
    # the new numbers, of the part measured
    assert [left["r"][k] for k in ("std", "min", "max", "mode")] == [22.0, 200, 255, 200]
    assert [right["r"][k] for k in ("std", "min", "max", "mode")] == [6.0, 0, 20, 20]
    assert [whole["r"][k] for k in ("min", "max", "mode")] == [0, 255, 20]


def test_stats_of_a_region_are_the_stats_of_that_part_of_the_image(lamps):
    whole = image_stats(lamps).model_dump()
    left = image_stats(lamps, region=Region(**LEFT)).model_dump()
    right = image_stats(lamps, region=Region(**RIGHT)).model_dump()
    check_lamp_halves(whole, left, right)

    # width/height stay the whole rendered image's; `region` is the part, in its pixels
    for stats in (whole, left, right):
        assert (stats["width"], stats["height"]) == (20, 10)
    assert whole["region"] is None
    assert left["region"] == LEFT_PIXELS and right["region"] == RIGHT_PIXELS


def test_a_region_below_the_lamps_measures_without_them(lamps):
    stats = image_stats(lamps, histogram=True, bins=8, region=Region(**BELOW_THE_LAMPS))
    assert stats.region.model_dump() == {"x": 0, "y": 2, "w": 10, "h": 8}
    assert stats.r.mean == 200 and stats.r.clipped_high == 0 and stats.r.std == 0
    assert stats.r.histogram[200] == 80 and sum(stats.r.histogram) == 80
    assert stats.r.bins == [0, 0, 0, 0, 0, 0, 1.0, 0]  # 200 is in 192..223


def test_region_is_the_top_left_corner_and_size_rounded_like_render_preview(lamps):
    frame = Rect(0, 0, 20, 10)
    for fractions in (
        {"x": 0.3, "y": 0.1, "w": 0.45, "h": 0.6},
        {"x": 0.55, "y": 0.35, "w": 0.4, "h": 0.65},
        {"x": 0, "y": 0, "w": 1, "h": 1},
    ):
        rect = region_rect(frame, **fractions)
        stats = image_stats(lamps, region=Region(**fractions))
        assert stats.region.model_dump() == {"x": rect.x, "y": rect.y, "w": rect.w, "h": rect.h}
    # by hand: columns 0.3 * 20 = 6 up to 0.75 * 20 = 15 (9 wide), rows 1 up to 7 (6 high)
    assert image_stats(lamps, region=Region(x=0.3, y=0.1, w=0.45, h=0.6)).region.model_dump() == {
        "x": 6, "y": 1, "w": 9, "h": 6
    }  # fmt: skip


@pytest.mark.parametrize(
    "region",
    [
        {"x": 0, "y": 0, "w": 0.2, "h": 0.3},  # 4 x 3 = 12 pixels
        {"x": 0.5, "y": 0.5, "w": 0.04, "h": 0.5},  # 1 x 5 = 5 pixels
        {"x": 0.99, "y": 0.99, "w": 0.01, "h": 0.01},  # the clamp makes it 1 x 1
    ],
)
def test_a_region_of_a_few_pixels_is_too_small(lamps, region):
    with pytest.raises(RegionTooSmall, match="at least 16 pixels") as caught:
        image_stats(lamps, region=Region(**region))
    assert isinstance(caught.value, ValueError) and "20 x 10" in str(caught.value)


def test_a_region_of_exactly_the_minimum_is_measured(lamps):
    stats = image_stats(lamps, region=Region(x=0, y=0, w=0.2, h=0.4))  # 4 x 4 = 16 pixels
    assert stats.region.model_dump() == {"x": 0, "y": 0, "w": 4, "h": 4}
    assert stats.r.clipped_high == 0.5  # its top two rows are the lamps


# -- std, min, max, mode and bins ------------------------------------------------


@pytest.fixture
def shape(tmp_path):
    """100 pixels. r: 10 at 0, 30 at 64, 40 at 128, 20 at 255. g = 255 - r.
    b: 50 throughout. Luminance rounds to 186 (10), 154 (30), 122 (40), 58 (20)."""
    values = [0] * 10 + [64] * 30 + [128] * 40 + [255] * 20
    img = Image.new("RGB", (10, 10))
    img.putdata([(v, 255 - v, 50) for v in values])
    path = tmp_path / "shape.png"
    img.save(path)
    return path


def test_std_min_max_and_mode_of_a_known_histogram(shape):
    stats = image_stats(shape).model_dump()
    # population standard deviation, worked out by hand with statistics.pstdev
    assert [stats["r"][k] for k in ("mean", "std", "min", "max", "mode")] == [121.4, 77.78, 0, 255, 128]
    assert [stats["g"][k] for k in ("mean", "std", "min", "max", "mode")] == [133.6, 77.78, 0, 255, 127]
    assert [stats["b"][k] for k in ("mean", "std", "min", "max", "mode")] == [50.0, 0.0, 50, 50, 50]
    assert [stats["lum"][k] for k in ("mean", "std", "min", "max", "mode")] == [125.2, 39.06, 58, 186, 122]
    for channel in ("r", "g", "b", "lum"):  # not asked for: not there
        assert stats[channel]["bins"] is None and stats[channel]["histogram"] is None


def test_mode_is_the_lowest_value_on_a_tie(tmp_path):
    path = save_pixels(tmp_path / "tie.png", (10, 10), lambda x, y: (200,) * 3 if y < 5 else (10,) * 3)
    stats = image_stats(path)
    assert stats.r.mode == 10 and (stats.r.min, stats.r.max) == (10, 200)


def test_a_flat_image_has_no_spread(tmp_path):
    stats = image_stats(save_pixels(tmp_path / "flat.png", (4, 4), lambda x, y: (7, 7, 7)))
    assert (stats.r.std, stats.r.min, stats.r.max, stats.r.mode) == (0.0, 7, 7, 7)


@pytest.mark.parametrize(
    "bins, r, g, b, lum",
    [
        # 8 groups of 32 values: r 0 -> 0, 64 -> 2, 128 -> 4, 255 -> 7
        (
            8, {0: 0.1, 2: 0.3, 4: 0.4, 7: 0.2}, {0: 0.2, 3: 0.4, 5: 0.3, 7: 0.1},
            {1: 1.0}, {1: 0.2, 3: 0.4, 4: 0.3, 5: 0.1},
        ),
        # 16 groups of 16: r 0 -> 0, 64 -> 4, 128 -> 8, 255 -> 15
        (
            16, {0: 0.1, 4: 0.3, 8: 0.4, 15: 0.2}, {0: 0.2, 7: 0.4, 11: 0.3, 15: 0.1},
            {3: 1.0}, {3: 0.2, 7: 0.4, 9: 0.3, 11: 0.1},
        ),
        # 32 groups of 8: r 0 -> 0, 64 -> 8, 128 -> 16, 255 -> 31
        (
            32, {0: 0.1, 8: 0.3, 16: 0.4, 31: 0.2}, {0: 0.2, 15: 0.4, 23: 0.3, 31: 0.1},
            {6: 1.0}, {7: 0.2, 15: 0.4, 19: 0.3, 23: 0.1},
        ),
        # 64 groups of 4: r 0 -> 0, 64 -> 16, 128 -> 32, 255 -> 63
        (
            64, {0: 0.1, 16: 0.3, 32: 0.4, 63: 0.2}, {0: 0.2, 31: 0.4, 47: 0.3, 63: 0.1},
            {12: 1.0}, {14: 0.2, 30: 0.4, 38: 0.3, 46: 0.1},
        ),
    ],
)  # fmt: skip
def test_bins_are_the_fractions_of_pixels_in_equal_groups_of_values(shape, bins, r, g, b, lum):
    stats = image_stats(shape, bins=bins).model_dump()
    for channel, expected in (("r", r), ("g", g), ("b", b), ("lum", lum)):
        got = stats[channel]["bins"]
        assert len(got) == bins
        assert {i: v for i, v in enumerate(got) if v} == expected
        assert stats[channel]["histogram"] is None


def test_bins_and_the_raw_histogram_can_come_together(shape):
    stats = image_stats(shape, histogram=True, bins=8)
    assert len(stats.r.histogram) == 256 and len(stats.r.bins) == 8
    assert stats.r.histogram[64] == 30 and stats.r.bins[2] == 0.3


def test_bins_are_rounded_to_four_decimals(tmp_path):
    path = tmp_path / "thirds.png"
    img = Image.new("RGB", (3, 1))
    img.putdata([(0, 0, 0), (100, 100, 100), (200, 200, 200)])
    img.save(path)
    # 0 -> group 0, 100 -> group 3 (96..127), 200 -> group 6 (192..223)
    assert image_stats(path, bins=8).r.bins == [0.3333, 0, 0, 0.3333, 0, 0, 0.3333, 0]


@pytest.mark.parametrize("bins", [8, 16, 32, 64, None])
def test_check_stats_bins_accepts_what_divides_256_in_the_documented_range(bins):
    check_stats_bins(bins, lambda code, why: AssertionError(why))


@pytest.mark.parametrize("bins", [0, 1, 2, 4, 7, 12, 100, 128, 256, -8])
def test_check_stats_bins_rejects_anything_else(bins):
    with pytest.raises(ValueError, match="bins must be 8, 16, 32 or 64") as caught:
        check_stats_bins(bins, lambda code, why: ValueError(f"{code}: {why}"))
    assert str(caught.value).startswith("out_of_range: ")


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
    for needle in ("crop.x", "camera space", "0..65535", "see the skills in tools/mcp/skills"):
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


OUTSIDE_THE_IMAGE = [
    {"x": -0.1, "y": 0, "w": 0.5, "h": 0.5},
    {"x": 0, "y": 0, "w": 0, "h": 0.5},
    {"x": 0.6, "y": 0, "w": 0.5, "h": 0.5},
    {"x": 0, "y": 0.5, "w": 0.5, "h": 0.6},
    {"x": 0, "y": 0, "w": 1.5, "h": 1},
]


async def test_render_image_stats_of_a_region_is_one_render_cropped_afterwards(
    render, image, lamps, monkeypatch, tmp_path
):
    server, log = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(lamps))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        calls = {}
        for name, arguments in (("whole", {}), ("left", {"region": LEFT}), ("right", {"region": RIGHT})):
            before = len(logged(log))
            calls[name] = await client.call_tool("image_stats", {"path": str(image), **arguments})
            assert len(logged(log)) == before + 1, name  # one art-cli run: no frame probe, no crop render

    for result in calls.values():
        assert not result.is_error, result.content
    left, right = calls["left"].structured_content, calls["right"].structured_content
    check_lamp_halves(calls["whole"].structured_content, left, right)
    assert left["region"] == LEFT_PIXELS and right["region"] == RIGHT_PIXELS
    assert (left["width"], left["height"]) == (20, 10)
    for call in [a for a in logged(log) if "-b8" in a]:
        assert "-f" in call and call.count("-p") == 2  # the whole-image render, no crop layer
    assert not list((tmp_path / "previews").glob("stats-*"))


async def test_render_image_stats_region_and_bins_of_a_part(render, image, lamps, monkeypatch):
    server, _ = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(lamps))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool(
            "image_stats", {"path": str(image), "region": BELOW_THE_LAMPS, "bins": 16}
        )
    assert not result.is_error, result.content
    stats = result.structured_content
    assert stats["region"] == {"x": 0, "y": 2, "w": 10, "h": 8}
    assert stats["r"]["clipped_high"] == 0 and stats["r"]["std"] == 0
    assert stats["r"]["bins"] == [0] * 12 + [1.0, 0, 0, 0]  # 200 is in 192..207
    assert stats["lum"]["bins"] == [0] * 12 + [1.0, 0, 0, 0]


@pytest.mark.parametrize("region", OUTSIDE_THE_IMAGE)
async def test_render_image_stats_region_outside_the_image_is_out_of_range(render, image, region):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("image_stats", {"path": str(image), "region": region})
        preview = await client.call_tool("render_preview", {"path": str(image), "region": region})
        assert len(logged(log)) == before  # refused before anything ran

    assert result.is_error and "out_of_range:" in result.content[0].text
    # one rectangle, one rule: the same refusal as render_preview's
    assert result.content[0].text.partition("out_of_range:")[2] == preview.content[0].text.partition("out_of_range:")[2]


async def test_render_image_stats_region_of_a_few_pixels_is_out_of_range(render, image, lamps, monkeypatch, tmp_path):
    server, _ = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(lamps))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool(
            "image_stats", {"path": str(image), "region": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}}
        )
    assert result.is_error and "out_of_range:" in result.content[0].text
    assert "at least 16 pixels" in result.content[0].text and "max_size" in result.content[0].text
    assert not list((tmp_path / "previews").glob("stats-*"))


@pytest.mark.parametrize("bins", [0, 7, 12, 128, 256])
async def test_render_image_stats_bins_out_of_range(render, image, bins):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("image_stats", {"path": str(image), "bins": bins})
        assert len(logged(log)) == before
    assert result.is_error and "out_of_range:" in result.content[0].text and "8, 16, 32 or 64" in result.content[0].text


async def test_render_image_stats_summary_numbers_and_bins_of_a_known_image(render, image, shape, monkeypatch):
    server, _ = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(shape))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        default = await client.call_tool("image_stats", {"path": str(image)})
        binned = await client.call_tool("image_stats", {"path": str(image), "bins": 8})
    r = default.structured_content["r"]
    assert (r["std"], r["min"], r["max"], r["mode"], r["bins"]) == (77.78, 0, 255, 128, None)
    assert binned.structured_content["r"]["bins"] == [0.1, 0, 0.3, 0, 0.4, 0, 0, 0.2]
    assert binned.structured_content["region"] is None


async def test_render_image_stats_documents_region_and_bins(render):
    server, _ = render
    async with Client(server) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
    assert {"region", "bins"} <= set(tool.input_schema["properties"])
    for needle in ("`region`", "fractions", "render_preview", "`bins`", "16", "std"):
        assert needle in tool.description


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


async def test_live_image_stats_of_a_region_crops_the_one_preview(art, tmp_path, lamps):
    previews = PreviewFolder(tmp_path / "previews")
    art.ops["preview"] = write_preview(lamps.read_bytes(), width=20, height=10)
    photo = str(tmp_path / "a.ARW")

    async with Client(build_live(ControlChannel(art.config_dir), previews=previews)) as client:
        results = {
            name: await client.call_tool("image_stats", {"path": photo, **arguments})
            for name, arguments in (("whole", {}), ("left", {"region": LEFT}), ("right", {"region": RIGHT}))
        }

    for result in results.values():
        assert not result.is_error, result.content
    left, right = results["left"].structured_content, results["right"].structured_content
    check_lamp_halves(results["whole"].structured_content, left, right)
    assert left["region"] == LEFT_PIXELS and right["region"] == RIGHT_PIXELS
    assert (left["width"], left["height"]) == (20, 10)
    # ART is asked for the whole preview each time: the region is not sent to it
    previews_asked = requests(art, "preview")
    assert len(previews_asked) == 3
    assert all(set(req["args"]) == {"path", "output", "max_size"} for req in previews_asked)
    assert not list((tmp_path / "previews").glob("*.png"))


async def test_live_image_stats_region_and_bins_of_a_part(art, tmp_path, lamps):
    art.ops["preview"] = write_preview(lamps.read_bytes(), width=20, height=10)
    async with Client(build_live(ControlChannel(art.config_dir), previews=PreviewFolder(tmp_path / "p"))) as client:
        result = await client.call_tool(
            "image_stats", {"path": str(tmp_path / "a.ARW"), "region": LEFT, "bins": 8}
        )
    assert not result.is_error, result.content
    assert result.structured_content["r"]["bins"] == [0, 0, 0, 0, 0, 0, 0.8, 0.2]
    assert result.structured_content["r"]["std"] == 22.0


@pytest.mark.parametrize(
    "arguments",
    [*({"region": r} for r in OUTSIDE_THE_IMAGE), {"bins": 7}, {"bins": 256}],
)
async def test_live_image_stats_bad_region_or_bins_is_out_of_range_before_asking_art(art, tmp_path, arguments):
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("image_stats", {"path": str(tmp_path / "a.ARW"), **arguments})
    assert result.is_error and "out_of_range:" in result.content[0].text
    assert not requests(art, "preview")


async def test_live_image_stats_region_of_a_few_pixels_is_out_of_range(art, tmp_path, lamps):
    previews = PreviewFolder(tmp_path / "previews")
    art.ops["preview"] = write_preview(lamps.read_bytes(), width=20, height=10)
    async with Client(build_live(ControlChannel(art.config_dir), previews=previews)) as client:
        result = await client.call_tool(
            "image_stats",
            {"path": str(tmp_path / "a.ARW"), "region": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}},
        )
    assert result.is_error and "out_of_range:" in result.content[0].text
    assert "at least 16 pixels" in result.content[0].text
    assert not list((tmp_path / "previews").glob("*.png"))


async def test_live_image_stats_documents_region_and_bins(art):
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
    assert {"region", "bins"} <= set(tool.input_schema["properties"])
    for needle in ("`region`", "fractions", "render_preview", "`bins`", "16", "std"):
        assert needle in tool.description


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


async def test_live_sample_spots_still_busy_at_the_deadline_is_a_timeout(art, tmp_path, monkeypatch):
    import art_mcp.live.server as live_server

    monkeypatch.setattr(live_server, "ART_PREVIEW_WAIT", 0.3)
    monkeypatch.setattr(live_server, "BUSY_RETRY_SECONDS", 0.05)
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    art.ops["sample_spots"] = fail("busy", "the editor is processing")

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": [{"x": 1, "y": 1}]})

    assert result.is_error and "timeout:" in result.content[0].text, result.content


async def test_live_sample_spots_unknown_op_is_unsupported(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    art.ops["sample_spots"] = fail("unknown_op", "no such op")

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": [{"x": 1, "y": 1}]})

    assert result.is_error
    assert "unsupported: needs an ART build with spot sampling" in result.content[0].text
