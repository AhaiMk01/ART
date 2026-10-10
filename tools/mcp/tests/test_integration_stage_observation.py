"""Staged observation against the real engine (needs ART_DIR naming a build with
art-cli ``-x converted|cineon`` and ``-X``): a small synthetic film negative of
uniform patches, read at the pre-inversion source, the recovered linear
working-space RGB, the Cineon codes and the 8-bit display, all through the
Render server.

Skipped without ART_DIR; skipped too when that build has no staged sampling.
"""

import json
import math

import pytest
from mcp.client.client import Client
from PIL import Image
from test_integration_film_negative import CLI, run_cli

from art_mcp import keyfile
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(CLI is None, reason="ART_DIR does not name an ART build"),
]

PATCHES = [(32, 24, 16), (96, 48, 32), (128, 96, 48), (200, 160, 128)]
SIZE = 32  # one patch is SIZE x SIZE pixels
BLACK, WHITE = 95.0, 685.0
SOFT_CLIP = 10 ** ((BLACK - WHITE) / 300.0)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def cineon_code(converted, reference_white=1.0):
    """Cineon code (0..1023 scale) of a linear 0..65535 value, the engine's encode."""
    x = max(0.0, converted / 65535.0) / reference_white
    return WHITE + 300.0 * math.log10(x * (1.0 - SOFT_CLIP) + SOFT_CLIP)


@pytest.fixture
def scan(tmp_path):
    path = tmp_path / "patches.png"
    image = Image.new("RGB", (SIZE * len(PATCHES), SIZE))
    for index, colour in enumerate(PATCHES):
        image.paste(colour, (index * SIZE, 0, (index + 1) * SIZE, SIZE))
    image.save(path)
    return path


@pytest.fixture
def server(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    return build_server(ArtCli((str(CLI),)), config, PreviewFolder(tmp_path / "previews"))


async def opened(client, scan):
    result = await client.call_tool("open_image", {"path": str(scan)})
    assert not result.is_error, result.content
    edited = await client.call_tool(
        "edit_profile",
        {
            "path": str(scan),
            "adjustments": {
                "film_negative": {
                    "enabled": True, "method": "density", "color_space": "working", "cineon_reference_white": 1,
                }
            },
        },
    )  # fmt: skip
    assert not edited.is_error, edited.content


def centres():
    return [{"x": index * SIZE + SIZE // 2, "y": SIZE // 2} for index in range(len(PATCHES))]


async def spots(client, scan, stage, **extra):
    result = await client.call_tool(
        "sample_spots", {"path": str(scan), "spots": centres(), "size": 8, "stage": stage, **extra}
    )
    if result.is_error and "unsupported" in result.content[0].text:
        pytest.skip(result.content[0].text)
    assert not result.is_error, result.content
    return result.structured_content


async def test_stages_are_labelled_and_cineon_spots_encode_the_converted_spots(server, scan):
    async with Client(server) as client:
        await opened(client, scan)
        source = await spots(client, scan, "source")
        converted = await spots(client, scan, "converted")
        cineon = await spots(client, scan, "cineon")

    assert (source["stage"], source["unit"]) == ("source", "linear_65535")
    assert (converted["stage"], converted["unit"]) == ("converted", "linear_65535")
    assert (cineon["stage"], cineon["unit"]) == ("cineon", "cineon_code")
    # The stages are different data: the recovered light is not the negative's source.
    assert converted["spots"][0]["avg"] != source["spots"][0]["avg"]
    for conv, cin in zip(converted["spots"], cineon["spots"], strict=True):
        assert (conv["x"], conv["y"]) == (cin["x"], cin["y"])
        for channel in range(3):
            # A uniform patch: the mean of per-pixel codes is the code of the mean.
            assert cin["avg"][channel] == pytest.approx(cineon_code(conv["avg"][channel]), abs=0.75)


async def test_source_space_does_not_apply_to_a_staged_read(server, scan):
    async with Client(server) as client:
        await opened(client, scan)
        result = await client.call_tool(
            "sample_spots", {"path": str(scan), "spots": centres()[:1], "stage": "cineon", "space": "input"}
        )
    assert result.is_error and "out_of_range:" in result.content[0].text


@pytest.mark.parametrize("stage", ["converted", "cineon"])
@pytest.mark.parametrize("max_size", [0, 16])
async def test_stage_statistics_of_a_uniform_patch_equal_the_spot(server, scan, stage, max_size):
    # The first patch is a quarter of the frame, so the fractions 0.02 to 0.23 are inside it.
    region = {"x": 0.02, "y": 0.1, "w": 0.21, "h": 0.8}
    async with Client(server) as client:
        await opened(client, scan)
        spot = (await spots(client, scan, stage))["spots"][0]["avg"]
        result = await client.call_tool(
            "image_stats",
            {"path": str(scan), "stage": stage, "bins": 1024, "max_size": max_size, "region": region},
        )
    if result.is_error and "unsupported" in result.content[0].text:
        pytest.skip(result.content[0].text)
    assert not result.is_error, result.content
    data = result.structured_content
    assert (data["stage"], data["bins"]) == (stage, 1024)
    assert data["unit"] == ("cineon_code" if stage == "cineon" else "linear_65535")
    lo, hi = data["range"]
    width = (hi - lo) / 1024
    assert (lo, hi) == ((-100.0, 1100.0) if stage == "cineon" else (-6553.5, 131070.0))
    assert data["source_width"] == SIZE * len(PATCHES) and data["source_height"] == SIZE
    for channel, stats in enumerate(data["channels"]):
        assert stats["nonfinite"] == 0 and stats["below"] == 0 and stats["above"] == 0
        assert stats["p50"] == pytest.approx(spot[channel], abs=1.5 * width)
        assert stats["mean"] == pytest.approx(spot[channel], abs=0.01 * abs(spot[channel]) + 0.75)
        assert stats["min"] == pytest.approx(stats["max"], abs=0.01 * abs(spot[channel]) + 1.0)


async def test_stage_histogram_chart_and_counts(server, scan):
    async with Client(server) as client:
        await opened(client, scan)
        result = await client.call_tool(
            "image_stats",
            {"path": str(scan), "stage": "cineon", "bins": 64, "histogram": True, "histogram_image": True},
        )
    if result.is_error and "unsupported" in result.content[0].text:
        pytest.skip(result.content[0].text)
    assert not result.is_error, result.content
    channels = result.structured_content["channels"]
    pixels = SIZE * len(PATCHES) * SIZE
    for stats in channels:
        assert len(stats["hist"]) == 64
        assert sum(stats["hist"]) == pytest.approx(pixels - stats["below"] - stats["above"], rel=0.01)
    assert any(c.type == "image" for c in result.content)


async def test_display_statistics_are_unchanged_and_not_cineon(server, scan):
    async with Client(server) as client:
        await opened(client, scan)
        plain = await client.call_tool("image_stats", {"path": str(scan)})
        display = await client.call_tool("image_stats", {"path": str(scan), "stage": "display"})
    assert not plain.is_error, plain.content
    assert plain.structured_content == display.structured_content
    assert "stage" not in plain.structured_content and "channels" not in plain.structured_content
    assert set(plain.structured_content) >= {"r", "g", "b", "lum", "width", "height"}


def test_art_cli_prints_the_documented_lines(tmp_path, scan):
    """The raw art-cli contract: ART-SPOTS stage/unit and the ART-STAGESTATS line."""
    profile = tmp_path / "p.arp"
    profile.write_text(keyfile.dumps({}))
    spots = run_cli(["-a", "-x", "8,cineon,16,16", "-p", str(profile), "-c", str(scan)], tmp_path)
    if spots.returncode != 0:
        pytest.skip("this ART has no staged sampling: " + (spots.stdout + spots.stderr)[:200])
    line = next(line for line in spots.stdout.splitlines() if line.startswith("ART-SPOTS "))
    payload = json.loads(line.removeprefix("ART-SPOTS "))
    assert (payload["stage"], payload["unit"]) == ("cineon", "cineon_code")
    stats = run_cli(["-a", "-X", "cineon,64,0", "-p", str(profile), "-c", str(scan)], tmp_path)
    assert stats.returncode == 0, stats.stdout + stats.stderr
    line = next(line for line in stats.stdout.splitlines() if line.startswith("ART-STAGESTATS "))
    payload = json.loads(line.removeprefix("ART-STAGESTATS "))
    assert payload["stage"] == "cineon" and payload["range"] == [-100, 1100]
    assert len(payload["channels"]) == 3 and len(payload["channels"][0]["hist"]) == 64
