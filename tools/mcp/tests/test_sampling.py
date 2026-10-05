"""sample_spots and image_stats on both servers, plus the pure statistics."""

import json
import random
import sys
from pathlib import Path

import pytest
from fake_live_art import FakeArt, FakeEditor, answer, fail, write_preview
from mcp.client.client import Client
from PIL import Image
from test_artcli_run import peak_overlap

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli, Rect, region_rect
from art_mcp.render.preview_tools import Region
from art_mcp.render.server import build_server as build_render
from art_mcp.sampling import (
    IMAGE_STATS_DOC,
    MAX_SPOTS,
    MAX_SPOTS_PER_CALL,
    RegionTooSmall,
    check_spots,
    check_stats_band,
    check_stats_bins,
    check_stats_detail,
    check_stats_paths,
    image_stats,
    spot_runs,
)

FAKE = Path(__file__).with_name("fake_artcli.py")
CTL = Path(__file__).with_name("fake_artcli_ctl.py")
pytestmark = pytest.mark.anyio

EDITOR_PROFILE = "[Exposure]\nCompensation=0\n"

STATS_SHAPE = (
    "with `path` the statistics are the result's top level (`r`, `g`, `b`, `lum`, `width`, `height`, ...); "
    "with `paths` they are under `items[i].stats` (each item `{path, stats}` or `{path, error}`)"
)
"""What image_stats says about where its statistics are, whichever of `path` and `paths` is given."""


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
        assert "histogram" not in r and "histogram" not in lum
    assert all("bins" not in channel for channel in (r, g, b, lum))  # not asked for: left out, not null
    assert "region" not in stats


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
    assert stats.r.clipped_low == 0.003906  # 4 of 1024 pixels, rounded to 6 decimals


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
    whole = image_stats(lamps, detail="full").model_dump()
    left = image_stats(lamps, region=Region(**LEFT), detail="full").model_dump()
    right = image_stats(lamps, region=Region(**RIGHT), detail="full").model_dump()
    check_lamp_halves(whole, left, right)

    # width/height stay the whole rendered image's; `region` is the part, in its pixels
    for stats in (whole, left, right):
        assert (stats["width"], stats["height"]) == (20, 10)
    assert "region" not in whole  # no region asked for: no null
    assert left["region"] == LEFT_PIXELS and right["region"] == RIGHT_PIXELS


def test_a_region_below_the_lamps_measures_without_them(lamps):
    stats = image_stats(lamps, histogram=True, bins=8, region=Region(**BELOW_THE_LAMPS), detail="full")
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
    stats = image_stats(shape, detail="full").model_dump()
    # population standard deviation, worked out by hand with statistics.pstdev
    assert [stats["r"][k] for k in ("mean", "std", "min", "max", "mode")] == [121.4, 77.78, 0, 255, 128]
    assert [stats["g"][k] for k in ("mean", "std", "min", "max", "mode")] == [133.6, 77.78, 0, 255, 127]
    assert [stats["b"][k] for k in ("mean", "std", "min", "max", "mode")] == [50.0, 0.0, 50, 50, 50]
    assert [stats["lum"][k] for k in ("mean", "std", "min", "max", "mode")] == [125.2, 39.06, 58, 186, 122]
    for channel in ("r", "g", "b", "lum"):  # not asked for: not there
        assert "bins" not in stats[channel] and "histogram" not in stats[channel]


def test_mode_is_the_lowest_value_on_a_tie(tmp_path):
    path = save_pixels(tmp_path / "tie.png", (10, 10), lambda x, y: (200,) * 3 if y < 5 else (10,) * 3)
    stats = image_stats(path, detail="full")
    assert stats.r.mode == 10 and (stats.r.min, stats.r.max) == (10, 200)


def test_a_flat_image_has_no_spread(tmp_path):
    stats = image_stats(save_pixels(tmp_path / "flat.png", (4, 4), lambda x, y: (7, 7, 7)), detail="full")
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
        assert "histogram" not in stats[channel]


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


# -- detail levels and omitted fields ----------------------------------------------

CHANNELS = ("r", "g", "b", "lum")
STANDARD_PERCENTILES = ["0.1", "1", "5", "50", "95", "99", "99.9"]
COMPACT_PERCENTILES = ["0.1", "50", "99.9"]


def test_standard_detail_is_what_image_stats_returned_before_the_extras(shape):
    stats = image_stats(shape).model_dump()
    assert set(stats) == {"width", "height", "r", "g", "b", "lum"}
    for channel in CHANNELS:
        assert set(stats[channel]) == {"mean", "clipped_high", "clipped_low", "percentiles"}
        assert list(stats[channel]["percentiles"]) == STANDARD_PERCENTILES
    assert image_stats(shape, detail="standard").model_dump() == stats


def test_compact_detail_is_clipping_and_three_percentiles_only(shape):
    stats = image_stats(shape, detail="compact").model_dump()
    assert set(stats) == {"width", "height", "r", "g", "b", "lum"}
    for channel in CHANNELS:
        assert set(stats[channel]) == {"clipped_high", "clipped_low", "percentiles"}  # no mean
        assert list(stats[channel]["percentiles"]) == COMPACT_PERCENTILES
    # by hand (N = 100, nearest rank): r is 10 x 0, 30 x 64, 40 x 128, 20 x 255; g = 255 - r; b is 50
    # throughout; luminance is 58 (20), 122 (40), 154 (30), 186 (10)
    assert stats["r"] == {"clipped_high": 0.2, "clipped_low": 0.1, "percentiles": {"0.1": 0, "50": 128, "99.9": 255}}
    assert stats["g"] == {"clipped_high": 0.1, "clipped_low": 0.2, "percentiles": {"0.1": 0, "50": 127, "99.9": 255}}
    assert stats["b"] == {"clipped_high": 0, "clipped_low": 0, "percentiles": {"0.1": 50, "50": 50, "99.9": 50}}
    assert stats["lum"] == {"clipped_high": 0, "clipped_low": 0, "percentiles": {"0.1": 58, "50": 122, "99.9": 186}}


def test_full_detail_is_standard_plus_std_min_max_and_mode(shape):
    standard = image_stats(shape).model_dump()
    full = image_stats(shape, detail="full").model_dump()
    for channel in CHANNELS:
        assert full[channel].keys() - standard[channel].keys() == {"std", "min", "max", "mode"}
        assert {k: v for k, v in full[channel].items() if k in standard[channel]} == standard[channel]
    assert [full["r"][k] for k in ("std", "min", "max", "mode")] == [77.78, 0, 255, 128]


@pytest.mark.parametrize("detail", ["compact", "standard", "full"])
def test_bins_and_the_histogram_add_their_fields_at_any_detail(shape, detail):
    plain = image_stats(shape, detail=detail).model_dump()
    asked = image_stats(shape, histogram=True, bins=16, detail=detail).model_dump()
    for channel in CHANNELS:
        assert asked[channel].keys() - plain[channel].keys() == {"bins", "histogram"}
        assert len(asked[channel]["bins"]) == 16 and len(asked[channel]["histogram"]) == 256
        assert {k: v for k, v in asked[channel].items() if k in plain[channel]} == plain[channel]
    only_bins = image_stats(shape, bins=8, detail=detail).model_dump()
    assert only_bins["r"].keys() - plain["r"].keys() == {"bins"}


def test_a_result_leaves_out_what_carries_nothing_in_every_serialised_form(shape, lamps):
    for stats in (image_stats(shape), image_stats(shape, detail="full"), image_stats(lamps, region=Region(**LEFT))):
        assert "null" not in stats.model_dump_json()
        assert None not in stats.model_dump().values() and None not in stats.model_dump(mode="json").values()
        for channel in CHANNELS:
            assert None not in stats.model_dump(mode="json")[channel].values()
    assert "region" not in image_stats(shape).model_dump()
    assert image_stats(lamps, region=Region(**LEFT)).model_dump()["region"] == LEFT_PIXELS


@pytest.mark.parametrize("detail", ["compact", "standard", "full", None])
def test_check_stats_detail_accepts_the_three_levels_and_none(detail):
    check_stats_detail(detail, lambda code, why: AssertionError(why))


@pytest.mark.parametrize("detail", ["", "Compact", "huge", "short", "all"])
def test_check_stats_detail_rejects_anything_else(detail):
    with pytest.raises(ValueError, match="detail must be compact, standard or full") as caught:
        check_stats_detail(detail, lambda code, why: ValueError(f"{code}: {why}"))
    assert str(caught.value).startswith("out_of_range: ")


def stats_problem(path, paths):
    """The refusal check_stats_paths raises for (path, paths), or None."""
    try:
        check_stats_paths(path, paths, lambda code, why: ValueError(f"{code}: {why}"))
    except ValueError as e:
        return str(e)
    return None


def test_check_stats_paths_takes_exactly_one_of_path_and_paths_of_one_to_fifty():
    assert stats_problem("a.ARW", None) is None
    assert stats_problem(None, ["a.ARW"]) is None
    assert stats_problem(None, [f"{n}.ARW" for n in range(50)]) is None
    both = stats_problem("a.ARW", ["a.ARW"])
    assert both.startswith("out_of_range: ") and "not both" in both
    neither = stats_problem(None, None)
    assert neither.startswith("out_of_range: ") and "path or paths" in neither and "not both" not in neither
    assert stats_problem(None, []) == "out_of_range: paths is empty"
    many = stats_problem(None, [f"{n}.ARW" for n in range(51)])
    assert many.startswith("out_of_range: ") and "51" in many and "50" in many



# -- sample_spots takes up to 64 spots, in runs of at most 16 -----------------------------


def spot_error(code, why):
    return RuntimeError(f"{code}: {why}")


def test_a_call_takes_1_to_64_spots_and_a_run_16():
    assert (MAX_SPOTS, MAX_SPOTS_PER_CALL) == (16, 64)
    for count in (1, 16, 17, 64):
        check_spots([(1, 1)] * count, 32, "working", (6000, 4000), spot_error)
    for count in (0, 65):
        with pytest.raises(RuntimeError) as caught:
            check_spots([(1, 1)] * count, 32, "working", None, spot_error)
        assert str(caught.value) == f"out_of_range: give 1 to 64 spots, not {count}"


@pytest.mark.parametrize(
    ("count", "runs"),
    [
        (1, [(0, 1)]),
        (16, [(0, 16)]),
        (17, [(0, 16), (16, 17)]),
        (40, [(0, 16), (16, 32), (32, 40)]),
        (64, [(0, 16), (16, 32), (32, 48), (48, 64)]),
    ],
)
def test_spot_runs_split_a_request_in_order_into_at_most_16(count, runs):
    assert [(r.start, r.stop) for r in spot_runs(count)] == runs


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
        {"spots": [{"x": 1, "y": 1}] * 65},
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


def forty_spots():
    """40 distinct spots, x = 1..40 (the fake's avg is [x, y, size], so a result shows its spot)."""
    return [{"x": n, "y": 100 + n} for n in range(1, 41)]


def sampling_runs(log):
    """The x of every spot of each art-cli run that sampled, in the order the runs started."""
    runs = []
    for call in logged(log):
        if "-x" in call:
            coords = call[call.index("-x") + 1].split(",")[2:]
            runs.append([int(v) for v in coords[::2]])
    return runs


async def test_render_sample_spots_40_spots_make_3_runs_and_come_back_in_order(render, image, monkeypatch):
    server, log = render
    # the first run is the slowest: it finishes last, the answer still follows the request
    monkeypatch.setenv("FAKE_SPOTS_SLOW_X", "1")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": forty_spots(), "size": 8})

    assert not result.is_error, result.content
    runs = sampling_runs(log)
    assert sorted(len(r) for r in runs) == [8, 16, 16]
    assert sorted(sum(runs, [])) == list(range(1, 41))
    sampled = result.structured_content
    assert (sampled["width"], sampled["height"], sampled["space"], sampled["size"]) == (6000, 4000, "working", 8)
    assert [(s["x"], s["y"]) for s in sampled["spots"]] == [(n, 100 + n) for n in range(1, 41)]
    assert [s["avg"] for s in sampled["spots"]] == [[n, 100 + n, 8] for n in range(1, 41)]
    assert [s["max"] for s in sampled["spots"]] == [[n + 1, 101 + n, 9] for n in range(1, 41)]
    # the frame is measured once (a row and a column probe), not per run
    assert len([a for a in logged(log)[before:] if "-x" not in a]) == 2


async def test_render_sample_spots_takes_64_spots_in_4_runs_and_17_in_2(render, image):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        many = [{"x": n, "y": 5} for n in range(1, 65)]
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": many})
        assert not result.is_error, result.content
        assert [s["x"] for s in result.structured_content["spots"]] == list(range(1, 65))
        assert sorted(len(r) for r in sampling_runs(log)) == [16, 16, 16, 16]
        start = len(sampling_runs(log))
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": many[:17]})
        assert not result.is_error and len(result.structured_content["spots"]) == 17
        assert sorted(len(r) for r in sampling_runs(log)[start:]) == [1, 16]


async def test_render_sample_spots_16_spots_stay_one_run_with_the_plain_error(render, image, monkeypatch):
    server, log = render
    monkeypatch.setenv("FAKE_SPOTS_FAIL_X", "3")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": forty_spots()[:16]})

    assert len(sampling_runs(log)) == 1
    assert result.is_error and "render_failed: art-cli exited with 3: sampling failed" in result.content[0].text
    assert "spots " not in result.content[0].text


async def test_render_sample_spots_a_failing_run_fails_the_call_and_says_which_spots(render, image, monkeypatch):
    server, _ = render
    monkeypatch.setenv("FAKE_SPOTS_FAIL_X", "20")  # spot 20 is in the second run, spots 17 to 32
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": forty_spots()})

    assert result.is_error and not result.structured_content
    text = result.content[0].text
    assert "render_failed: art-cli exited with 3: sampling failed" in text
    assert "(spots 17 to 32 of 40; no result returned)" in text


async def test_render_sample_spots_40_spots_without_spot_sampling_is_unsupported(render, image, monkeypatch):
    server, _ = render
    monkeypatch.setenv("FAKE_SPOTS", "release")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": forty_spots()})

    assert result.is_error and "unsupported: needs an ART build with spot sampling" in result.content[0].text


async def test_sample_spots_description_is_generic_and_points_at_the_skills(render):
    server, _ = render
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    text = tools["sample_spots"].description
    for needle in ("crop.x", "camera space", "0..65535", "see the skills in tools/mcp/skills"):
        assert needle in text
    for gone in ("RedRatio", "RefInput", "RefOutput", "65535/24"):
        assert gone not in text
    assert "1 to 64 spots per call" in text and "1 to 16" not in text


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
            calls[name] = await client.call_tool("image_stats", {"path": str(image), "detail": "full", **arguments})
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
            "image_stats", {"path": str(image), "region": BELOW_THE_LAMPS, "bins": 16, "detail": "full"}
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
    assert r["mean"] == 121.4 and "bins" not in r  # the default level: no std, min, max or mode
    assert binned.structured_content["r"]["bins"] == [0.1, 0, 0.3, 0, 0.4, 0, 0, 0.2]
    assert "region" not in binned.structured_content


async def test_render_image_stats_documents_region_and_bins(render):
    server, _ = render
    async with Client(server) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
    assert {"region", "bins"} <= set(tool.input_schema["properties"])
    for needle in ("`region`", "fractions", "render_preview", "`bins`", "16", "std"):
        assert needle in tool.description


# -- Render: detail levels and several images -------------------------------------


def render_server(tmp_path, *, cli=FAKE, max_processes=2):
    """A Render server without the argument log (the fake's appends are not safe for several runs at once)."""
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    return build_render(
        ArtCli((sys.executable, str(cli)), max_processes=max_processes), config, PreviewFolder(tmp_path / "previews")
    )


async def open_all(client, frames):
    for frame in frames:
        opened = await client.call_tool("open_image", {"path": str(frame)})
        assert not opened.is_error, opened.content


def level(low, high, p01, p50, p999):
    """A channel at the compact detail."""
    return {"clipped_low": low, "clipped_high": high, "percentiles": {"0.1": p01, "50": p50, "99.9": p999}}


FULL_KEYS = {"mean", "std", "min", "max", "mode", "clipped_high", "clipped_low", "percentiles"}
STANDARD_KEYS = FULL_KEYS - {"std", "min", "max", "mode"}


@pytest.fixture
def roll(tmp_path, monkeypatch):
    """Three raws of 10 x 10 pixels, each 'rendered' by the fake art-cli from a PNG of its own:
    1 is (100, 150, 200) throughout; 2 has 10 black pixels in 100, the rest grey 50; 3 has 5 white
    pixels in 100, the rest grey 200."""
    folder, pngs = tmp_path / "roll", tmp_path / "pngs"
    folder.mkdir()
    pngs.mkdir()
    looks = [
        lambda x, y: (100, 150, 200),
        lambda x, y: (0, 0, 0) if y == 0 else (50, 50, 50),
        lambda x, y: (255, 255, 255) if y == 0 and x < 5 else (200, 200, 200),
    ]
    frames = []
    for n, look in enumerate(looks, start=1):
        frame = folder / f"FILM_{n}.ARW"
        frame.write_bytes(b"raw")
        save_pixels(pngs / f"FILM_{n}.png", (10, 10), look)
        frames.append(frame)
    monkeypatch.setenv("FAKE_PNG_DIR", str(pngs))
    return frames


def check_roll_compact(items):
    """What the compact detail says of the three frames of `roll`, worked out by hand (N = 100, nearest rank)."""
    first, second, third = (item["stats"] for item in items)
    assert [first[c] for c in CHANNELS] == [
        level(0, 0, 100, 100, 100), level(0, 0, 150, 150, 150), level(0, 0, 200, 200, 200), level(0, 0, 143, 143, 143)
    ]  # fmt: skip
    for channel in CHANNELS:
        assert second[channel] == level(0.1, 0, 0, 50, 50)
        assert third[channel] == level(0, 0.05, 200, 200, 255)


async def test_render_image_stats_default_is_standard_detail_without_nulls(render, image, known_png, monkeypatch):
    server, _ = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(known_png))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("image_stats", {"path": str(image)})

    assert not result.is_error, result.content
    stats = result.structured_content
    assert set(stats) == {"width", "height", "r", "g", "b", "lum"}  # no `region`, `items` or `failed`
    for channel in CHANNELS:
        assert set(stats[channel]) == STANDARD_KEYS
        assert list(stats[channel]["percentiles"]) == STANDARD_PERCENTILES
    assert "null" not in result.content[0].text  # the text form leaves them out too
    assert json.loads(result.content[0].text) == stats


@pytest.mark.parametrize(
    "detail, keys, percentiles",
    [
        ("compact", {"clipped_high", "clipped_low", "percentiles"}, COMPACT_PERCENTILES),
        ("standard", STANDARD_KEYS, STANDARD_PERCENTILES),
        ("full", FULL_KEYS, STANDARD_PERCENTILES),
    ],
)
async def test_render_image_stats_detail_levels(render, image, known_png, monkeypatch, detail, keys, percentiles):
    server, _ = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(known_png))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("image_stats", {"path": str(image), "detail": detail})

    assert not result.is_error, result.content
    for channel in CHANNELS:
        assert set(result.structured_content[channel]) == keys
        assert list(result.structured_content[channel]["percentiles"]) == percentiles
    assert "null" not in result.content[0].text


async def test_render_image_stats_output_schema_keeps_the_omitted_fields_optional(render, image, lamps, monkeypatch):
    jsonschema = pytest.importorskip("jsonschema")
    server, _ = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(lamps))
    everything = {"detail": "full", "bins": 8, "histogram": True, "region": LEFT}
    async with Client(server) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
        await client.call_tool("open_image", {"path": str(image)})
        results = [
            await client.call_tool("image_stats", {"path": str(image), **arguments})
            for arguments in ({}, {"detail": "compact"}, everything)
        ]

    schema = tool.output_schema
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    for result in results:
        assert not result.is_error, result.content
        assert not list(validator.iter_errors(result.structured_content))
    channel = schema["$defs"]["ChannelStats"]
    for optional in ("mean", "std", "min", "max", "mode", "histogram", "bins"):
        assert optional in channel["properties"] and optional not in channel.get("required", [])
    assert {"clipped_high", "clipped_low", "percentiles"} <= set(channel["required"])
    assert "region" in schema["properties"] and "region" not in schema.get("required", [])


async def test_render_image_stats_unknown_detail_is_out_of_range_before_rendering(render, image):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("image_stats", {"path": str(image), "detail": "huge"})
        several = await client.call_tool("image_stats", {"paths": [str(image)], "detail": "huge"})
        assert len(logged(log)) == before

    for refused in (result, several):
        assert refused.is_error and "out_of_range:" in refused.content[0].text
        assert "detail must be compact, standard or full" in refused.content[0].text


@pytest.mark.parametrize(
    "arguments, words",
    [
        (lambda image: {}, "path or paths"),
        (lambda image: {"path": str(image), "paths": [str(image)]}, "not both"),
        (lambda image: {"paths": []}, "paths is empty"),
        (lambda image: {"paths": [str(image)] * 51}, "51 entries"),
        (lambda image: {"paths": [str(image)], "max_size": 0}, "max_size"),
        (lambda image: {"paths": [str(image)], "bins": 7}, "8, 16, 32 or 64"),
        (lambda image: {"paths": [str(image)], "region": {"x": 0.6, "y": 0, "w": 0.5, "h": 0.5}}, "fractions"),
    ],
)
async def test_render_image_stats_refuses_a_bad_call_before_rendering_anything(render, image, arguments, words):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("image_stats", arguments(image))
        assert len(logged(log)) == before

    assert result.is_error and "out_of_range:" in result.content[0].text and words in result.content[0].text


async def test_render_image_stats_of_several_images_is_an_item_per_image_in_order_and_compact(tmp_path, roll):
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in roll]})

    assert not result.is_error, result.content
    data = result.structured_content
    assert set(data) == {"items", "failed"} and data["failed"] == 0
    assert [item["path"] for item in data["items"]] == [str(f) for f in roll]
    for item in data["items"]:
        assert set(item) == {"path", "stats"}  # no null `error`
        assert (item["stats"]["width"], item["stats"]["height"]) == (10, 10)
        assert "region" not in item["stats"]
    check_roll_compact(data["items"])
    assert "null" not in result.content[0].text
    assert json.loads(result.content[0].text) == data


@pytest.mark.parametrize("detail, keys", [("standard", STANDARD_KEYS), ("full", FULL_KEYS)])
async def test_render_image_stats_of_several_images_keeps_a_detail_the_caller_gives(tmp_path, roll, detail, keys):
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in roll], "detail": detail})

    assert not result.is_error, result.content
    for item in result.structured_content["items"]:
        for channel in CHANNELS:
            assert set(item["stats"][channel]) == keys


async def test_render_image_stats_of_several_images_gives_each_the_same_options(tmp_path, roll):
    arguments = {"detail": "standard", "bins": 8, "histogram": True, "region": {"x": 0, "y": 0, "w": 0.5, "h": 1}}
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in roll], **arguments})

    assert not result.is_error, result.content
    items = result.structured_content["items"]
    for item in items:
        stats = item["stats"]
        assert stats["region"] == {"x": 0, "y": 0, "w": 5, "h": 10}  # each image's own pixels
        assert (stats["width"], stats["height"]) == (10, 10)
        assert len(stats["r"]["bins"]) == 8 and len(stats["lum"]["histogram"]) == 256
    # the left half: the first frame is flat, the second has 5 black and the third 5 white pixels of 50
    assert items[0]["stats"]["r"]["mean"] == 100 and items[0]["stats"]["r"]["clipped_low"] == 0
    assert items[1]["stats"]["r"]["clipped_low"] == 0.1 and items[2]["stats"]["r"]["clipped_high"] == 0.1


async def test_render_image_stats_one_image_that_fails_is_its_own_error_and_the_others_come_back(tmp_path, roll):
    unopened = str(roll[0].with_name("FILM_9.ARW"))
    unreadable = roll[0].with_name("FILM_4.ARW")  # no PNG of its own: the fake's render does not decode
    unreadable.write_bytes(b"raw")
    paths = [str(roll[0]), unopened, str(roll[2]), str(unreadable)]
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, [roll[0], roll[2], unreadable])
        result = await client.call_tool("image_stats", {"paths": paths})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data["failed"] == 2 and [item["path"] for item in data["items"]] == paths
    first, missing, third, broken = data["items"]
    assert set(first) == {"path", "stats"} and set(third) == {"path", "stats"}
    assert set(missing) == {"path", "error"} and missing["error"].startswith("not_open:")
    assert set(broken) == {"path", "error"} and broken["error"].startswith("render_failed:")
    assert first["stats"]["r"]["percentiles"]["50"] == 100 and third["stats"]["r"]["clipped_high"] == 0.05


async def test_render_image_stats_a_region_too_small_for_an_image_is_that_images_error(tmp_path, roll):
    small = {"x": 0, "y": 0, "w": 0.2, "h": 0.2}  # 2 x 2 pixels of a 10 x 10 render
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in roll], "region": small})

    assert not result.is_error, result.content
    assert result.structured_content["failed"] == 3
    for item in result.structured_content["items"]:
        assert item["error"].startswith("out_of_range:") and "at least 16 pixels" in item["error"]


async def test_render_image_stats_of_several_images_reports_progress_per_image(tmp_path, roll):
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total))

    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        result = await client.call_tool(
            "image_stats", {"paths": [str(f) for f in roll]}, progress_callback=on_progress
        )

    assert not result.is_error, result.content
    assert sorted(seen) == [(1, 3), (2, 3), (3, 3)]


async def test_render_image_stats_of_several_images_runs_through_the_bounded_pool(tmp_path, roll, monkeypatch):
    log = tmp_path / "runs"
    log.mkdir()
    many = []
    for n in range(6):
        frame = roll[0].with_name(f"FILM_{n + 10}.ARW")
        frame.write_bytes(b"raw")
        many.append(frame)
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(tmp_path / "pngs" / "FILM_1.png"))
    async with Client(render_server(tmp_path, cli=CTL, max_processes=2)) as client:
        await open_all(client, many)
        monkeypatch.setenv("FAKE_ARTCLI_LOG", str(log))
        monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0.3")
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in many]})

    assert not result.is_error, result.content
    assert result.structured_content["failed"] == 0
    assert peak_overlap(log) == (6, 2)  # six renders, two at a time: the cap, and in parallel


async def test_render_image_stats_documents_detail_and_paths(render):
    server, _ = render
    async with Client(server) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
    properties = tool.input_schema["properties"]
    assert {"path", "paths", "detail"} <= set(properties)
    assert not tool.input_schema.get("required")  # exactly one of path and paths: checked by the tool
    assert json.dumps(properties["detail"]).count("compact") == 1 and '"full"' in json.dumps(properties["detail"])
    for needle in ('"compact"', '"standard"', '"full"', "`detail`", "`paths`", "`items`", "request order", "default"):
        assert needle in tool.description


async def test_render_image_stats_says_where_the_statistics_are_for_path_and_for_paths(render):
    server, _ = render
    async with Client(server) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
    assert STATS_SHAPE in " ".join(tool.description.split())


async def test_render_image_stats_results_are_small(tmp_path, monkeypatch):
    """The default result is about 700 characters, the compact one about 450 (370 with nothing clipped: the
    fractions are not rounded), twelve compact ones about 5 KB."""
    rng = random.Random(7)
    photo = tmp_path / "photo.png"
    img = Image.new("RGB", (97, 61))  # an awkward pixel count: the fractions have all their decimals
    img.putdata([tuple(min(255, max(0, int(rng.gauss(mid, 70)))) for mid in (90, 120, 150)) for _ in range(97 * 61)])
    img.save(photo)
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(photo))
    frames = []
    for n in range(12):
        frame = tmp_path / "roll" / f"FILM_{n}.ARW"
        frame.parent.mkdir(exist_ok=True)
        frame.write_bytes(b"raw")
        frames.append(frame)

    def size(result):
        assert not result.is_error, result.content
        return len(json.dumps(result.structured_content, separators=(",", ":")))

    async with Client(render_server(tmp_path)) as client:
        await open_all(client, frames)
        standard = size(await client.call_tool("image_stats", {"path": str(frames[0])}))
        compact = size(await client.call_tool("image_stats", {"path": str(frames[0]), "detail": "compact"}))
        twelve = size(await client.call_tool("image_stats", {"paths": [str(f) for f in frames]}))

    assert standard <= 800 and compact <= 560 and compact <= 0.8 * standard
    assert twelve <= 12 * (compact + len(json.dumps(str(frames[0]))) + 30)  # an item adds its path, not more


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
        {"spots": [{"x": 1, "y": 1}] * 65},
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
            name: await client.call_tool("image_stats", {"path": photo, "detail": "full", **arguments})
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
            "image_stats", {"path": str(tmp_path / "a.ARW"), "region": LEFT, "bins": 8, "detail": "full"}
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


async def test_live_image_stats_says_where_the_statistics_are_for_path_and_for_paths(art):
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
    assert STATS_SHAPE in " ".join(tool.description.split())


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


def echo_spots(req):
    """ART's sample_spots op answering with one value per spot asked for: avg [x, y, size]."""
    args = req["args"]
    size = args["size"]
    spots = [
        {"x": x, "y": y, "avg": [x, y, size], "max": [x + 1, y + 1, size + 1]} for x, y in args["spots"]
    ]
    return answer({"width": 6000, "height": 4000, "spots": spots})(req)


async def test_live_sample_spots_40_spots_make_3_requests_and_come_back_in_order(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    art.ops["sample_spots"] = echo_spots
    spots = [{"x": n, "y": 100 + n} for n in range(1, 41)]

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": spots, "size": 8, "space": "input"})

    assert not result.is_error, result.content
    asked = requests(art, "sample_spots")
    assert [[x for x, _ in req["args"]["spots"]] for req in asked] == [
        list(range(1, 17)), list(range(17, 33)), list(range(33, 41))
    ]  # fmt: skip
    assert all(req["args"]["size"] == 8 and req["args"]["space"] == "input" for req in asked)
    sampled = result.structured_content
    assert (sampled["width"], sampled["height"], sampled["space"], sampled["size"]) == (6000, 4000, "input", 8)
    assert [(s["x"], s["y"]) for s in sampled["spots"]] == [(n, 100 + n) for n in range(1, 41)]
    assert [s["avg"] for s in sampled["spots"]] == [[n, 100 + n, 8] for n in range(1, 41)]


async def test_live_sample_spots_17_spots_take_2_requests_and_64_take_4(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    art.ops["sample_spots"] = echo_spots
    spots = [{"x": n, "y": 5} for n in range(1, 65)]

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": spots[:17]})
        assert not result.is_error and len(result.structured_content["spots"]) == 17
        assert [len(req["args"]["spots"]) for req in requests(art, "sample_spots")] == [16, 1]
        result = await client.call_tool("sample_spots", {"path": photo, "spots": spots})
        assert not result.is_error and [s["x"] for s in result.structured_content["spots"]] == list(range(1, 65))
        assert [len(req["args"]["spots"]) for req in requests(art, "sample_spots")[2:]] == [16] * 4


async def test_live_sample_spots_a_failing_request_fails_the_call_and_says_which_spots(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    failing = fail("render_failed", "the editor lost the image")
    art.ops["sample_spots"] = lambda req: failing(req) if req["args"]["spots"][0][0] == 17 else echo_spots(req)
    spots = [{"x": n, "y": 5} for n in range(1, 41)]

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": spots})

    assert result.is_error and not result.structured_content
    text = result.content[0].text
    assert "render_failed: the editor lost the image" in text
    assert text.endswith("(spots 17 to 32 of 40; no result returned)")
    assert len(requests(art, "sample_spots")) == 2  # the third was not asked for


async def test_live_sample_spots_16_spots_keep_the_plain_error(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    art.ops["sample_spots"] = fail("render_failed", "the editor lost the image")

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": [{"x": 1, "y": 1}] * 16})

    assert result.is_error and result.content[0].text.endswith("render_failed: the editor lost the image")


async def test_live_sample_spots_each_request_waits_for_a_busy_editor_by_itself(art, tmp_path):
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    busy = fail("busy", "the editor is processing")
    replies = [echo_spots, busy, echo_spots]  # the second request finds it busy once, then it settles
    art.ops["sample_spots"] = lambda req: replies.pop(0)(req)
    spots = [{"x": n, "y": 5} for n in range(1, 33)]

    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": spots})

    assert not result.is_error, result.content
    assert [s["x"] for s in result.structured_content["spots"]] == list(range(1, 33))
    assert len(requests(art, "sample_spots")) == 3


# -- Live: detail levels and several images ----------------------------------------


def live_stats_server(art, tmp_path):
    return build_live(ControlChannel(art.config_dir), previews=PreviewFolder(tmp_path / "previews"))


def previews_of_the_roll(art, tmp_path, roll):
    """ART's preview op answering with the PNG of the frame asked for, `not_open` for any other."""
    pngs = {frame.name: tmp_path / "pngs" / f"{frame.stem}.png" for frame in roll}

    def reply(req):
        path = req["args"]["path"]
        png = pngs.get(Path(path).name)
        if png is None:
            return fail("not_open", f"{path} is not open in ART")(req)
        return write_preview(png.read_bytes(), width=10, height=10)(req)

    art.ops["preview"] = reply


async def test_live_image_stats_default_is_standard_detail_without_nulls(art, tmp_path, known_png):
    art.ops["preview"] = write_preview(known_png.read_bytes(), width=10, height=10)
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", {"path": str(tmp_path / "a.ARW")})

    assert not result.is_error, result.content
    stats = result.structured_content
    assert set(stats) == {"width", "height", "r", "g", "b", "lum"}
    for channel in CHANNELS:
        assert set(stats[channel]) == STANDARD_KEYS
        assert list(stats[channel]["percentiles"]) == STANDARD_PERCENTILES
    assert "null" not in result.content[0].text
    assert json.loads(result.content[0].text) == stats


@pytest.mark.parametrize(
    "detail, keys, percentiles",
    [
        ("compact", {"clipped_high", "clipped_low", "percentiles"}, COMPACT_PERCENTILES),
        ("standard", STANDARD_KEYS, STANDARD_PERCENTILES),
        ("full", FULL_KEYS, STANDARD_PERCENTILES),
    ],
)
async def test_live_image_stats_detail_levels(art, tmp_path, known_png, detail, keys, percentiles):
    art.ops["preview"] = write_preview(known_png.read_bytes(), width=10, height=10)
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", {"path": str(tmp_path / "a.ARW"), "detail": detail})

    assert not result.is_error, result.content
    for channel in CHANNELS:
        assert set(result.structured_content[channel]) == keys
        assert list(result.structured_content[channel]["percentiles"]) == percentiles
    assert "null" not in result.content[0].text


async def test_live_image_stats_output_schema_keeps_the_omitted_fields_optional(art, tmp_path, lamps):
    jsonschema = pytest.importorskip("jsonschema")
    art.ops["preview"] = write_preview(lamps.read_bytes(), width=20, height=10)
    everything = {"detail": "full", "bins": 8, "histogram": True, "region": LEFT}
    async with Client(live_stats_server(art, tmp_path)) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
        results = [
            await client.call_tool("image_stats", {"path": str(tmp_path / "a.ARW"), **arguments})
            for arguments in ({}, {"detail": "compact"}, everything)
        ]

    validator = jsonschema.Draft202012Validator(tool.output_schema)
    for result in results:
        assert not result.is_error, result.content
        assert not list(validator.iter_errors(result.structured_content))
    channel = tool.output_schema["$defs"]["ChannelStats"]
    for optional in ("mean", "std", "min", "max", "mode", "histogram", "bins"):
        assert optional not in channel.get("required", [])


async def test_live_image_stats_unknown_detail_is_out_of_range_before_asking_art(art, tmp_path):
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", {"path": str(tmp_path / "a.ARW"), "detail": "huge"})
        several = await client.call_tool("image_stats", {"paths": [str(tmp_path / "a.ARW")], "detail": "huge"})

    for refused in (result, several):
        assert refused.is_error and "out_of_range:" in refused.content[0].text
        assert "detail must be compact, standard or full" in refused.content[0].text
    assert not requests(art, "preview")


@pytest.mark.parametrize(
    "arguments, words",
    [
        (lambda photo: {}, "path or paths"),
        (lambda photo: {"path": photo, "paths": [photo]}, "not both"),
        (lambda photo: {"paths": []}, "paths is empty"),
        (lambda photo: {"paths": [photo] * 51}, "51 entries"),
        (lambda photo: {"paths": [photo], "max_size": 0}, "max_size"),
        (lambda photo: {"paths": [photo], "bins": 7}, "8, 16, 32 or 64"),
        (lambda photo: {"paths": [photo], "region": {"x": 0.6, "y": 0, "w": 0.5, "h": 0.5}}, "fractions"),
    ],
)
async def test_live_image_stats_refuses_a_bad_call_before_asking_art(art, tmp_path, arguments, words):
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", arguments(str(tmp_path / "a.ARW")))

    assert result.is_error and "out_of_range:" in result.content[0].text and words in result.content[0].text
    assert not requests(art, "preview")


async def test_live_image_stats_of_several_images_asks_art_for_each_in_order_and_is_compact(art, tmp_path, roll):
    previews_of_the_roll(art, tmp_path, roll)
    paths = [str(f) for f in roll]
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", {"paths": paths, "max_size": 800})

    assert not result.is_error, result.content
    data = result.structured_content
    assert set(data) == {"items", "failed"} and data["failed"] == 0
    assert [item["path"] for item in data["items"]] == paths
    for item in data["items"]:
        assert set(item) == {"path", "stats"} and (item["stats"]["width"], item["stats"]["height"]) == (10, 10)
    check_roll_compact(data["items"])
    asked = requests(art, "preview")
    assert [req["args"]["path"] for req in asked] == paths
    assert all(req["args"]["max_size"] == 800 for req in asked)
    assert "null" not in result.content[0].text and json.loads(result.content[0].text) == data
    assert not list((tmp_path / "previews").glob("*.png"))


@pytest.mark.parametrize("detail, keys", [("standard", STANDARD_KEYS), ("full", FULL_KEYS)])
async def test_live_image_stats_of_several_images_keeps_a_detail_the_caller_gives(art, tmp_path, roll, detail, keys):
    previews_of_the_roll(art, tmp_path, roll)
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in roll], "detail": detail})

    assert not result.is_error, result.content
    for item in result.structured_content["items"]:
        for channel in CHANNELS:
            assert set(item["stats"][channel]) == keys


async def test_live_image_stats_of_several_images_gives_each_the_same_options(art, tmp_path, roll):
    previews_of_the_roll(art, tmp_path, roll)
    arguments = {"detail": "standard", "bins": 8, "histogram": True, "region": {"x": 0, "y": 0, "w": 0.5, "h": 1}}
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in roll], **arguments})

    assert not result.is_error, result.content
    items = result.structured_content["items"]
    for item in items:
        assert item["stats"]["region"] == {"x": 0, "y": 0, "w": 5, "h": 10}
        assert len(item["stats"]["r"]["bins"]) == 8 and len(item["stats"]["lum"]["histogram"]) == 256
    assert items[0]["stats"]["r"]["mean"] == 100
    assert items[1]["stats"]["r"]["clipped_low"] == 0.1 and items[2]["stats"]["r"]["clipped_high"] == 0.1


async def test_live_image_stats_one_image_that_fails_is_its_own_error_and_the_others_come_back(art, tmp_path, roll):
    previews_of_the_roll(art, tmp_path, roll)
    unopened = str(tmp_path / "roll" / "FILM_9.ARW")
    paths = [str(roll[0]), unopened, str(roll[2])]
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", {"paths": paths})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data["failed"] == 1 and [item["path"] for item in data["items"]] == paths
    first, missing, third = data["items"]
    assert set(first) == {"path", "stats"} and set(third) == {"path", "stats"}
    assert set(missing) == {"path", "error"} and missing["error"].startswith("not_open:")
    assert first["stats"]["r"]["percentiles"]["50"] == 100 and third["stats"]["r"]["clipped_high"] == 0.05
    assert len(requests(art, "preview")) == 3  # the others were still asked for


async def test_live_image_stats_a_preview_that_is_not_an_image_is_that_images_bad_reply(art, tmp_path, roll):
    previews_of_the_roll(art, tmp_path, roll)
    good = art.ops["preview"]
    art.ops["preview"] = lambda req: (
        write_preview(b"not a png", width=1, height=1)(req) if req["args"]["path"] == str(roll[1]) else good(req)
    )
    async with Client(live_stats_server(art, tmp_path)) as client:
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in roll]})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data["failed"] == 1 and data["items"][1]["error"].startswith("bad_reply:")
    assert "stats" in data["items"][0] and "stats" in data["items"][2]
    assert not list((tmp_path / "previews").glob("*.png"))


async def test_live_image_stats_of_several_images_without_art_fails_the_call(tmp_path, roll):
    async with Client(build_live(ControlChannel(tmp_path / "no-art"))) as client:
        result = await client.call_tool("image_stats", {"paths": [str(f) for f in roll]})

    assert result.is_error and "art_not_running:" in result.content[0].text


async def test_live_image_stats_documents_detail_and_paths(art):
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        tool = {t.name: t for t in (await client.list_tools()).tools}["image_stats"]
    properties = tool.input_schema["properties"]
    assert {"path", "paths", "detail"} <= set(properties)
    assert not tool.input_schema.get("required")
    assert json.dumps(properties["detail"]).count("compact") == 1 and '"full"' in json.dumps(properties["detail"])
    for needle in ('"compact"', '"standard"', '"full"', "`detail`", "`paths`", "`items`", "request order", "default"):
        assert needle in tool.description


# -- a luminance band --------------------------------------------------------------
# `lamps` (grey, so lum = value): 20 pixels at 255, 80 at 200, 90 at 20, 10 at 0.


def test_a_band_below_the_lamps_leaves_them_out_of_every_statistic(lamps):
    stats = image_stats(lamps, histogram=True, detail="full", lum_max=254)
    # by hand: (80 * 200 + 90 * 20) / 180 pixels, nothing at 255, 10 of 180 at 0
    assert stats.r.mean == 98.89 and stats.r.clipped_high == 0 and stats.r.clipped_low == 0.055556
    assert stats.r.max == 200 and sum(stats.r.histogram) == 180 and sum(stats.lum.histogram) == 180
    assert stats.in_band == 0.9
    assert (stats.width, stats.height) == (20, 10) and stats.region is None


def test_a_band_above_the_blacks_leaves_them_out(lamps):
    stats = image_stats(lamps, lum_min=1)
    assert stats.r.clipped_low == 0 and stats.r.clipped_high == 0.105263  # 20 of 190
    assert stats.in_band == 0.95


def test_a_band_with_both_limits_measures_only_the_values_between_them(lamps):
    stats = image_stats(lamps, lum_min=100, lum_max=254, detail="full")
    assert (stats.r.mean, stats.r.std, stats.r.min, stats.r.max) == (200, 0, 200, 200)
    assert stats.lum.percentiles == {"0.1": 200, "1": 200, "5": 200, "50": 200, "95": 200, "99": 200, "99.9": 200}
    assert stats.in_band == 0.4


@pytest.mark.parametrize("value, pixels", [(200, 80), (20, 90), (255, 20)])
def test_the_limits_of_a_band_are_inclusive(lamps, value, pixels):
    stats = image_stats(lamps, lum_min=value, lum_max=value)
    assert stats.in_band == pixels / 200 and stats.r.percentiles["50"] == value


def test_a_band_is_cut_from_the_region_and_in_band_counts_that_part(lamps):
    stats = image_stats(lamps, region=Region(**LEFT), lum_max=254, detail="full")
    assert stats.region.model_dump() == LEFT_PIXELS
    assert stats.r.mean == 200 and stats.r.clipped_high == 0
    assert stats.in_band == 0.8  # 80 of the 100 pixels of the left half


def test_no_band_leaves_in_band_out(lamps):
    assert "in_band" not in image_stats(lamps).model_dump()
    assert image_stats(lamps, lum_max=255).in_band == 1.0  # a band that holds everything still says so


def test_a_band_with_too_few_pixels_is_too_small(lamps):
    with pytest.raises(RegionTooSmall, match="band.*at least 16 pixels"):
        image_stats(lamps, lum_min=21, lum_max=199)  # nothing is there
    with pytest.raises(RegionTooSmall, match="at least 16 pixels"):
        image_stats(lamps, lum_max=0)  # 10 pixels


@pytest.mark.parametrize(
    "lum_min, lum_max", [(None, None), (0, 255), (255, 255), (0, 0), (10, 10), (None, 100), (5, None)]
)
def test_check_stats_band_accepts_a_band_inside_0_to_255(lum_min, lum_max):
    check_stats_band(lum_min, lum_max, lambda code, why: AssertionError(why))


@pytest.mark.parametrize(
    "lum_min, lum_max, why",
    [(-1, None, "0 to 255"), (None, 256, "0 to 255"), (300, None, "0 to 255"), (200, 100, "lum_min is above lum_max")],
)
def test_check_stats_band_rejects_anything_else(lum_min, lum_max, why):
    with pytest.raises(ValueError, match=why) as caught:
        check_stats_band(lum_min, lum_max, lambda code, message: ValueError(f"{code}: {message}"))
    assert str(caught.value).startswith("out_of_range:")


async def test_render_image_stats_with_a_band_leaves_the_lamps_out(render, image, lamps, monkeypatch):
    server, log = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(lamps))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("image_stats", {"path": str(image), "lum_max": 254, "detail": "full"})
        assert len(logged(log)) == before + 1  # one render, the band is cut from it
    assert not result.is_error, result.content
    stats = result.structured_content
    assert stats["r"]["clipped_high"] == 0 and stats["r"]["mean"] == 98.89 and stats["in_band"] == 0.9


async def test_render_image_stats_many_images_share_the_band(render, image, lamps, monkeypatch):
    server, _ = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(lamps))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("image_stats", {"paths": [str(image)], "lum_min": 100, "lum_max": 254})
    assert not result.is_error, result.content
    [item] = result.structured_content["items"]
    assert item["stats"]["in_band"] == 0.4 and item["stats"]["r"]["clipped_high"] == 0


@pytest.mark.parametrize("arguments", [{"lum_min": -1}, {"lum_max": 256}, {"lum_min": 200, "lum_max": 100}])
async def test_render_image_stats_bad_band_is_out_of_range_before_rendering(render, image, arguments):
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("image_stats", {"path": str(image), **arguments})
        assert len(logged(log)) == before
    assert result.is_error and "out_of_range:" in result.content[0].text


async def test_render_image_stats_an_empty_band_is_out_of_range(render, image, lamps, monkeypatch, tmp_path):
    server, _ = render
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(lamps))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("image_stats", {"path": str(image), "lum_min": 21, "lum_max": 199})
    assert result.is_error and "out_of_range:" in result.content[0].text and "band" in result.content[0].text
    assert not list((tmp_path / "previews").glob("stats-*"))


async def test_live_image_stats_with_a_band_leaves_the_lamps_out(art, tmp_path, lamps):
    art.ops["preview"] = write_preview(lamps.read_bytes(), width=20, height=10)
    async with Client(build_live(ControlChannel(art.config_dir), previews=PreviewFolder(tmp_path / "p"))) as client:
        result = await client.call_tool(
            "image_stats", {"path": str(tmp_path / "a.ARW"), "lum_max": 254, "detail": "full"}
        )
        bad = await client.call_tool("image_stats", {"path": str(tmp_path / "a.ARW"), "lum_min": 256})
    assert not result.is_error, result.content
    assert result.structured_content["r"]["clipped_high"] == 0 and result.structured_content["in_band"] == 0.9
    assert bad.is_error and "out_of_range:" in bad.content[0].text
    assert len(requests(art, "preview")) == 1  # the bad band was refused before asking ART


def test_the_image_stats_doc_explains_the_band():
    assert "lum_min" in IMAGE_STATS_DOC and "lum_max" in IMAGE_STATS_DOC and "in_band" in IMAGE_STATS_DOC
