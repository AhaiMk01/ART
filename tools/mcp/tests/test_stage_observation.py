"""Staged observation of the film pipeline: sample_spots `stage` and image_stats
`stage` (art-cli -x converted|cineon and -X), on both servers, against the fake
art-cli and the fake editor. The real-engine checks are in
test_integration_stage_observation.py."""

import base64
import io
import json

import pytest
from fake_live_art import FakeEditor, answer
from mcp.client.client import Client
from PIL import Image
from test_sampling import EDITOR_PROFILE, art, image, logged, render, requests  # noqa: F401

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live
from art_mcp.sampling import (
    STAGE_UNITS,
    check_stage_stats,
    parse_spots_output,
    parse_stage_stats_output,
)

pytestmark = pytest.mark.anyio

SPOT = {"x": 10, "y": 20}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def error_text(result):
    assert result.is_error, result.structured_content
    return result.content[0].text


# -- sample_spots ---------------------------------------------------------------


@pytest.mark.parametrize("stage", ["converted", "cineon"])
async def test_render_sample_spots_stage_sends_the_stage_as_the_token(render, image, stage):  # noqa: F811
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool(
            "sample_spots", {"path": str(image), "spots": [SPOT], "size": 8, "stage": stage}
        )

    assert not result.is_error, result.content
    data = result.structured_content
    assert data["stage"] == stage and data["unit"] == STAGE_UNITS[stage]
    [call] = [a for a in logged(log) if "-x" in a]
    assert call[call.index("-x") + 1] == f"8,{stage},10,20"


async def test_render_sample_spots_default_stage_is_source(render, image):  # noqa: F811
    server, _ = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": [SPOT]})
    assert result.structured_content["stage"] == "source"
    assert result.structured_content["unit"] == "linear_65535"


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"stage": "converted", "space": "input"}, "space applies to stage source only"),
        ({"stage": "cineon", "space": "input"}, "space applies to stage source only"),
        ({"stage": "display"}, "stage must be one of source, converted, cineon"),
    ],
)
async def test_render_sample_spots_refuses_a_bad_stage_before_running(render, image, arguments, needle):  # noqa: F811
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        before = len(logged(log))
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": [SPOT], **arguments})
    assert "out_of_range:" in error_text(result) and needle in error_text(result)
    assert not [a for a in logged(log)[before:] if "-x" in a]


async def test_render_sample_spots_staged_runs_come_back_as_one_stage(render, image):  # noqa: F811
    server, log = render
    spots = [{"x": n, "y": 5} for n in range(1, 21)]
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": spots, "stage": "cineon"})
    assert not result.is_error, result.content
    assert result.structured_content["stage"] == "cineon" and len(result.structured_content["spots"]) == 20
    assert len([a for a in logged(log) if "-x" in a]) == 2


@pytest.mark.parametrize("mode", ["release", "silent", "nostage"])
async def test_render_staged_sampling_on_an_older_build_is_unsupported(render, image, monkeypatch, mode):  # noqa: F811
    server, _ = render
    monkeypatch.setenv("FAKE_SPOTS", mode)
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("sample_spots", {"path": str(image), "spots": [SPOT], "stage": "converted"})
    assert "unsupported:" in error_text(result) and "staged sampling" in error_text(result)


def test_parse_spots_output_labels_the_stage_and_unit():
    line = 'ART-SPOTS {"width":4,"height":3,"stage":"cineon","unit":"cineon_code","spots":[]}'
    parsed = parse_spots_output(line, 8, "working", "cineon")
    assert (parsed.stage, parsed.unit, parsed.space) == ("cineon", "cineon_code", "working")
    assert parsed.film is None and parsed.w is None
    line = 'ART-SPOTS {"stage":"converted","film":"disabled","w":0.9,"width":4,"height":3,"spots":[]}'
    parsed = parse_spots_output(line, 8, "working", "converted")
    assert (parsed.film, parsed.w) == ("disabled", 0.9)
    assert parsed.model_dump()["film"] == "disabled"
    assert "film" not in parse_spots_output('ART-SPOTS {"width":4,"height":3,"spots":[]}', 8, "working").model_dump()
    with pytest.raises(ValueError, match="staged sampling"):
        parse_spots_output('ART-SPOTS {"width":4,"height":3,"spots":[]}', 8, "working", "cineon")


async def test_live_sample_spots_sends_stage_only_when_not_source(art, tmp_path):  # noqa: F811
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    values = {"x": 7, "y": 9, "avg": [1.5, 2, 3], "max": [4, 5, 6]}
    art.ops["sample_spots"] = answer(
        {"width": 6000, "height": 4000, "stage": "converted", "unit": "linear_65535", "spots": [values]}
    )
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        staged = await client.call_tool(
            "sample_spots", {"path": photo, "spots": [{"x": 7, "y": 9}], "size": 16, "stage": "converted"}
        )
        await client.call_tool("sample_spots", {"path": photo, "spots": [{"x": 7, "y": 9}], "size": 16})
    assert not staged.is_error, staged.content
    assert staged.structured_content["stage"] == "converted"
    assert staged.structured_content["unit"] == "linear_65535"
    first, second = requests(art, "sample_spots")
    assert first["args"]["stage"] == "converted"
    assert "stage" not in second["args"]


async def test_live_sample_spots_an_art_that_ignores_stage_is_unsupported(art, tmp_path):  # noqa: F811
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    values = {"x": 7, "y": 9, "avg": [1, 2, 3], "max": [4, 5, 6]}
    art.ops["sample_spots"] = answer({"width": 6000, "height": 4000, "spots": [values]})
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("sample_spots", {"path": photo, "spots": [{"x": 7, "y": 9}], "stage": "cineon"})
    assert "unsupported:" in error_text(result)


async def test_live_sample_spots_refuses_space_input_with_a_stage(art, tmp_path):  # noqa: F811
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool(
            "sample_spots", {"path": photo, "spots": [{"x": 7, "y": 9}], "stage": "cineon", "space": "input"}
        )
    assert "out_of_range:" in error_text(result)
    assert not requests(art, "sample_spots")


# -- image_stats -----------------------------------------------------------------


def stage_line(stage="cineon", bins=8):
    channels = []
    for c in range(3):
        hist = [0] * bins
        hist[c + 1] = 50
        channels.append(
            {
                "min": 1.0, "max": 2.0, "mean": 1.5, "p01": 1.0, "p50": 1.5, "p99": 2.0,
                "below": 0, "above": 0, "nonfinite": 0, "hist": hist,
            }
        )  # fmt: skip
    lo, hi = (-100.0, 1100.0) if stage == "cineon" else (-6553.5, 131070.0)
    return "ART-STAGESTATS " + json.dumps(
        {
            "stage": stage, "unit": STAGE_UNITS[stage], "width": 5, "height": 10,
            "source_width": 50, "source_height": 100, "w": 1.0, "range": [lo, hi], "channels": channels,
        }
    )  # fmt: skip


def test_parse_stage_stats_output_validates_the_line():
    parsed = parse_stage_stats_output("banner\n" + stage_line("cineon"), "cineon", 8)
    assert parsed.bins == 8 and parsed.range == [-100.0, 1100.0] and len(parsed.channels) == 3
    assert parse_stage_stats_output("banner", "cineon", 8) is None
    with pytest.raises(ValueError, match="unexpected"):
        parse_stage_stats_output(stage_line("converted"), "cineon", 8)
    with pytest.raises(ValueError, match="malformed"):
        parse_stage_stats_output("ART-STAGESTATS {nope", "cineon", 8)


async def stats(render, image, **arguments):  # noqa: F811
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        return await client.call_tool("image_stats", {"path": str(image), **arguments}), log


@pytest.mark.parametrize("stage", ["converted", "cineon"])
async def test_render_image_stats_stage_runs_dash_x_with_bins_size_and_region(render, image, stage):  # noqa: F811
    result, log = await stats(
        render, image, stage=stage, bins=64, max_size=500, region={"x": 0.25, "y": 0.5, "w": 0.5, "h": 0.25}
    )
    assert not result.is_error, result.content
    data = result.structured_content
    assert data["stage"] == stage and data["unit"] == STAGE_UNITS[stage]
    assert data["range"] == ([-100.0, 1100.0] if stage == "cineon" else [-6553.5, 131070.0])
    assert (data["w"], data["bins"], data["source_width"]) == (1.0, 64, 6000)
    assert len(data["channels"]) == 3 and "hist" not in data["channels"][0]
    assert {"p01", "p50", "p99", "below", "above", "nonfinite"} <= set(data["channels"][0])
    [call] = [a for a in logged(log) if "-X" in a]
    assert call[call.index("-X") + 1] == f"{stage},64,500,0.25,0.5,0.75,0.75"
    assert "-o" not in call and "-O" not in call


async def test_render_image_stats_stage_defaults_to_256_bins_and_histogram_returns_counts(render, image):  # noqa: F811
    result, log = await stats(render, image, stage="cineon", histogram=True)
    [call] = [a for a in logged(log) if "-X" in a]
    assert call[call.index("-X") + 1].startswith("cineon,256,")
    assert all(len(c["hist"]) == 256 for c in result.structured_content["channels"])


async def test_render_image_stats_stage_histogram_image_is_a_png_chart(render, image):  # noqa: F811
    result, _ = await stats(render, image, stage="cineon", bins=64, histogram_image=True)
    assert not result.is_error, result.content
    [chart] = [c for c in result.content if c.type == "image"]
    assert chart.mime_type == "image/png"
    png = Image.open(io.BytesIO(base64.b64decode(chart.data)))
    assert png.size == (840, 400)
    # The 95 / 470 / 685 marks are drawn as vertical lines in the mark colour.
    row = [x for x in range(png.width) if png.getpixel((x, 160)) == (240, 200, 80)]
    assert len(row) == 3


async def test_render_image_stats_display_stage_is_unchanged(render, image, tmp_path, monkeypatch):  # noqa: F811
    source = tmp_path / "x.png"
    Image.new("RGB", (4, 4), (10, 20, 30)).save(source)
    monkeypatch.setenv("FAKE_PNG_SOURCE", str(source))
    plain, _ = await stats(render, image)
    explicit, _ = await stats(render, image, stage="display")
    assert not plain.is_error, plain.content
    assert plain.structured_content == explicit.structured_content
    assert "stage" not in plain.structured_content and plain.structured_content["r"]["percentiles"]


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"stage": "cineon", "detail": "full"}, "detail apply to stage display only"),
        ({"stage": "converted", "lum_min": 3}, "lum_min apply to stage display only"),
        ({"stage": "converted", "lum_max": 3, "lum_min": 1}, "lum_min, lum_max apply"),
        ({"stage": "cineon", "bins": 1}, "bins for stage cineon must be 2 to 1024"),
        ({"stage": "cineon", "bins": 2000}, "bins for stage cineon must be 2 to 1024"),
        ({"stage": "linear"}, "stage must be one of display, converted, cineon"),
        ({"stage": "display", "bins": 100}, "bins must be 8, 16, 32 or 64"),
    ],
)
async def test_render_image_stats_refuses_bad_combinations_before_running(render, image, arguments, needle):  # noqa: F811
    result, log = await stats(render, image, **arguments)
    assert "out_of_range:" in error_text(result) and needle in error_text(result)
    assert not [a for a in logged(log) if "-X" in a]


async def test_render_image_stats_stage_allows_big_bins_and_full_size(render, image):  # noqa: F811
    result, log = await stats(render, image, stage="converted", bins=1024, max_size=0)
    assert not result.is_error, result.content
    [call] = [a for a in logged(log) if "-X" in a]
    assert call[call.index("-X") + 1] == "converted,1024,0"


async def test_render_image_stats_several_paths_with_a_stage(render, image, tmp_path):  # noqa: F811
    other = tmp_path / "photos" / "IMG_2.ARW"
    other.write_bytes(b"raw")
    server, log = render
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool("open_image", {"path": str(other)})
        result = await client.call_tool(
            "image_stats", {"paths": [str(image), str(other)], "stage": "converted", "bins": 16}
        )
    assert not result.is_error, result.content
    items = result.structured_content["items"]
    assert [i["path"] for i in items] == [str(image), str(other)]
    assert all(i["stats"]["stage"] == "converted" and i["stats"]["bins"] == 16 for i in items)
    assert result.structured_content["failed"] == 0
    assert len([a for a in logged(log) if "-X" in a]) == 2


@pytest.mark.parametrize("mode", ["release", "silent"])
async def test_render_image_stats_stage_on_an_older_build_is_unsupported(render, image, monkeypatch, mode):  # noqa: F811
    monkeypatch.setenv("FAKE_SPOTS", mode)
    result, _ = await stats(render, image, stage="cineon")
    assert "unsupported:" in error_text(result) and "staged sampling" in error_text(result)


@pytest.mark.parametrize("stage", ["converted", "cineon"])
async def test_live_image_stats_refuses_a_pipeline_stage_and_points_to_render(art, tmp_path, stage):  # noqa: F811
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("image_stats", {"path": photo, "stage": stage})
    text = error_text(result)
    assert "unsupported:" in text and "Render server" in text and "stage display" in text
    assert not requests(art, "preview")


async def test_live_image_stats_bad_stage_is_out_of_range(art, tmp_path):  # noqa: F811
    photo = str(tmp_path / "a.ARW")
    FakeEditor(art).add(photo, EDITOR_PROFILE)
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("image_stats", {"path": photo, "stage": "nope"})
    assert "out_of_range:" in error_text(result)


def test_check_stage_stats_lets_display_keep_its_arguments():
    check_stage_stats("display", 16, "full", 1, 2, lambda code, msg: ValueError(msg))
