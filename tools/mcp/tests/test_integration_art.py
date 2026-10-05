"""End-to-end against a real ART install. Skipped unless ART is found and
ART_MCP_TEST_RAW names a raw file (copied to a temp folder, never touched)."""

import os
import shutil
from pathlib import Path

import pytest
from mcp.client.client import Client
from PIL import Image

from art_mcp import artdir
from art_mcp.metadata import Exiftool
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ART"
ART_DIR = artdir.find_art_dir(None, os.environ, PROGRAM_FILES)
CLI = artdir.find_cli(ART_DIR) if ART_DIR else None
RAW = os.environ.get("ART_MCP_TEST_RAW")
EXIFTOOL = os.environ.get("ART_MCP_EXIFTOOL") or (artdir.find_exiftool(ART_DIR) if ART_DIR else None)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(CLI is None, reason="ART not installed"),
    pytest.mark.skipif(not RAW or not Path(RAW).is_file(), reason="ART_MCP_TEST_RAW not set"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_real_raw_opens_and_previews_at_1024(tmp_path):
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    server = build_server(
        ArtCli((str(CLI),), timeout=120),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )

    async with Client(server) as client:
        opened = await client.call_tool("open_image", {"path": str(raw)})
        preview = await client.call_tool("render_preview", {"path": str(raw)})

        assert not opened.is_error, opened.content
        assert opened.structured_content["profile_from"] == "default"
        assert not preview.is_error, preview.content
        with Image.open(preview.structured_content["path"]) as jpeg:
            assert jpeg.format == "JPEG"
            assert max(jpeg.size) == 1024


def mean_brightness(path):
    with Image.open(path) as jpeg:
        pixels = list(jpeg.convert("L").resize((64, 64)).get_flattened_data())
    return sum(pixels) / len(pixels)


async def test_working_profile_from_sidecar_is_what_renders(tmp_path):
    plain = tmp_path / "plain" / Path(RAW).name
    bright = tmp_path / "bright" / Path(RAW).name
    for copy in (plain, bright):
        copy.parent.mkdir()
        shutil.copyfile(RAW, copy)
    # Both get a sidecar, so they share a baseline whatever the user's default
    # profile does (e.g. histogram matching); only the compensation differs.
    for copy, ev in ((plain, 0), (bright, 2)):
        sidecar = artdir.sidecar_path(copy, artdir.user_config_dir(os.environ))
        sidecar.write_text(f"[Exposure]\nEnabled=true\nCompensation={ev}\n")
    server = build_server(
        ArtCli((str(CLI),), timeout=120),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )

    async with Client(server) as client:
        brightness = {}
        for copy in (plain, bright):
            await client.call_tool("open_image", {"path": str(copy)})
            preview = await client.call_tool("render_preview", {"path": str(copy)})
            brightness[copy] = mean_brightness(preview.structured_content["path"])

    assert brightness[bright] > brightness[plain] + 20


async def test_raw_edit_and_reset_change_the_real_render(tmp_path):
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    server = build_server(
        ArtCli((str(CLI),), timeout=120),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )
    brighter = [
        {"group": "Exposure", "key": "Enabled", "value": "true"},
        {"group": "Exposure", "key": "Compensation", "value": "2"},
    ]

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(raw)})
        profile = await client.call_tool("get_profile", {"path": str(raw)})
        before = await client.call_tool("render_preview", {"path": str(raw)})
        edited = await client.call_tool("edit_profile", {"path": str(raw), "raw_edits": brighter})
        after = await client.call_tool("render_preview", {"path": str(raw)})
        await client.call_tool("reset_profile", {"path": str(raw), "to": "default"})
        reset = await client.call_tool("render_preview", {"path": str(raw)})

        assert profile.structured_content["ppversion"] >= 1045
        assert "exposure" in profile.structured_content["adjustments"]
        assert not edited.is_error, edited.content
        plain = mean_brightness(before.structured_content["path"])
        assert mean_brightness(after.structured_content["path"]) > plain + 20
        assert abs(mean_brightness(reset.structured_content["path"]) - plain) < 2


async def test_real_export_in_all_formats_is_full_size_and_leaves_no_arp(tmp_path):
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    out = tmp_path / "out"
    out.mkdir()
    server = build_server(
        ArtCli((str(CLI),), timeout=300),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )
    cases = [
        ("jpeg", "a.jpg", {"quality": 90}, "JPEG"),
        ("tiff", "a.tif", {"bit_depth": "16"}, "TIFF"),
        ("png", "a.png", {"bit_depth": "8"}, "PNG"),
    ]

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(raw)})
        sizes = set()
        for fmt, name, extra, pil_format in cases:
            result = await client.call_tool(
                "export_image",
                {"path": str(raw), "output": str(out / name), "format": fmt, **extra},
            )
            assert not result.is_error, result.content
            with Image.open(out / name) as image:
                assert image.format == pil_format
                sizes.add(image.size)
        assert len(sizes) == 1 and max(next(iter(sizes))) > 1024
        assert sorted(p.name for p in out.iterdir()) == ["a.jpg", "a.png", "a.tif"]

        with_arp = await client.call_tool(
            "export_image",
            {"path": str(raw), "output": str(out / "b.jpg"), "format": "jpeg", "write_profile": True},
        )
        assert not with_arp.is_error, with_arp.content
        assert "[Exposure]" in (out / "b.jpg.arp").read_text()


async def test_adjustments_change_the_real_render_and_read_back_typed(tmp_path):
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    server = build_server(
        ArtCli((str(CLI),), timeout=120),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(raw)})
        before = await client.call_tool("render_preview", {"path": str(raw)})
        edited = await client.call_tool(
            "edit_profile",
            {
                "path": str(raw),
                "adjustments": {
                    "exposure": {"compensation": 1.5},
                    "white_balance": {"temperature": 4500, "equal": 1.1},
                },
            },
        )
        profile = await client.call_tool("get_profile", {"path": str(raw)})
        after = await client.call_tool("render_preview", {"path": str(raw)})

        assert not edited.is_error, edited.content
        adjustments = profile.structured_content["adjustments"]
        assert adjustments["exposure"]["compensation"] == 1.5
        assert adjustments["exposure"]["enabled"] is True
        assert adjustments["white_balance"]["setting"] == "CustomTemp"
        assert adjustments["white_balance"]["temperature"] == 4500
        assert adjustments["white_balance"]["equal"] == 1.1
        assert profile.structured_content["raw"]["White Balance"].keys() <= {"Multipliers"}
        brighter = mean_brightness(after.structured_content["path"])
        assert brighter > mean_brightness(before.structured_content["path"]) + 10


async def test_real_region_preview_is_1_to_1_and_capped_at_max_size(tmp_path):
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    server = build_server(
        ArtCli((str(CLI),), timeout=120),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(raw)})
        whole = await client.call_tool("render_preview", {"path": str(raw), "max_size": 2576})
        small = await client.call_tool(
            "render_preview",
            {"path": str(raw), "region": {"x": 0.25, "y": 0.25, "w": 0.1, "h": 0.1}},
        )
        large = await client.call_tool(
            "render_preview",
            {"path": str(raw), "region": {"x": 0, "y": 0, "w": 0.75, "h": 0.75}, "max_size": 2576},
        )
        assert not small.is_error and not large.is_error, (small.content, large.content)
        with Image.open(whole.structured_content["path"]) as full:
            whole_size = full.size
        with Image.open(small.structured_content["path"]) as jpeg:
            small_size = jpeg.size
        with Image.open(large.structured_content["path"]) as jpeg:
            large_size = jpeg.size

    # The whole image is shrunk to the 2576 cap, while a tenth of the frame is
    # rendered at 1:1: for any raw over ~5000 px wide that is clearly more than
    # a tenth of the shrunk whole (602 px for a 6016 px frame, 865 for 8652).
    assert max(whole_size) == 2576
    assert small_size[0] / small_size[1] == pytest.approx(whole_size[0] / whole_size[1], rel=0.02)
    assert 0.2 * whole_size[0] < small_size[0] <= 2576, small_size
    assert max(large_size) == 2576


async def test_all_curated_tools_round_trip_through_real_art(tmp_path):
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    server = build_server(
        ArtCli((str(CLI),), timeout=120),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )
    adjustments = {
        "crop": {"x": 100, "y": 80, "w": 3000, "h": 2000},
        "rotation": {"degree": 1.5, "auto_fill": False},
        "local_contrast": {"contrast": 25},
        "sharpening": {"method": "usm", "amount": 300, "radius": 0.8},
        "denoise": {"luminance": 20, "chrominance_method": "manual", "chrominance": 30},
        "vignetting": {"amount": 20, "center_x": 10},
        "lens_profile": {"lc_mode": "lfauto", "use_ca": True},
    }

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(raw)})
        edited = await client.call_tool("edit_profile", {"path": str(raw), "adjustments": adjustments})
        preview = await client.call_tool("render_preview", {"path": str(raw)})
        profile = await client.call_tool("get_profile", {"path": str(raw)})
        too_wide = await client.call_tool(
            "edit_profile", {"path": str(raw), "adjustments": {"crop": {"x": 0, "w": 100000}}}
        )

        assert not edited.is_error, edited.content
        assert not preview.is_error, preview.content
        typed = profile.structured_content["adjustments"]
        for tool, fields in adjustments.items():
            for field, value in fields.items():
                assert typed[tool][field] == value, (tool, field)
        assert typed["crop"]["enabled"] is True and typed["rotation"]["enabled"] is True
        with Image.open(preview.structured_content["path"]) as jpeg:
            assert abs(jpeg.size[0] / jpeg.size[1] - 3000 / 2000) < 0.02
        assert too_wide.is_error and "out_of_range" in too_wide.content[0].text


def column_means(path, columns=20):
    """Mean brightness of each of ``columns`` equal-width strips of the image."""
    with Image.open(path) as jpeg:
        pixels = list(jpeg.convert("L").resize((columns, 4)).get_flattened_data())
    return [sum(pixels[i::columns]) / 4 for i in range(columns)]


async def test_a_mask_shape_is_placed_in_percent_of_half_the_width(tmp_path):
    """ART puts a shape's centre at w/2 + x/100 * w/2: x=100 is the right edge,
    x=50 three quarters of the way, and width is % of the whole width."""
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    server = build_server(
        ArtCli((str(CLI),), timeout=120),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )
    dark = {"slope": 0.1}

    def region(x):
        shape = {
            "type": "rectangle", "x": x, "y": 0, "width": 20, "height": 100,
            "angle": 0, "roundness": 0, "feather": 0, "blur": 0, "mode": "add",
        }  # fmt: skip
        mask = {"enabled": True, "inverted": False, "feather": 0, "blur": 0, "shapes": [shape]}
        return {"color_correction": {"regions": [{"r": dark, "g": dark, "b": dark, "mask": mask}]}}

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(raw)})
        base = column_means((await client.call_tool("render_preview", {"path": str(raw)})).structured_content["path"])
        darkened = {}
        for x in (100, 50):
            edited = await client.call_tool("edit_profile", {"path": str(raw), "adjustments": region(x)})
            assert not edited.is_error, edited.content
            preview = await client.call_tool("render_preview", {"path": str(raw)})
            after = column_means(preview.structured_content["path"])
            darkened[x] = [i for i, (b, a) in enumerate(zip(base, after, strict=True)) if a < b * 0.7]

    # 20 strips of 5% each: the centre on the right edge covers the last 10%
    assert darkened[100] == [18, 19]
    # the centre at 75% of the width, 20% wide: strips 13 to 16 (65% to 85%)
    assert darkened[50] == [13, 14, 15, 16]


async def test_a_crop_of_the_reported_frame_size_covers_the_whole_frame(tmp_path):
    """inspect_image's frame_width/height are the space crop coordinates are in: a crop of exactly
    that size fits (and renders as the whole frame), one pixel more does not."""
    if not EXIFTOOL:
        pytest.skip("exiftool not found (beside ART-cli, or ART_MCP_EXIFTOOL)")
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    server = build_server(
        ArtCli((str(CLI),), timeout=120),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
        exiftool=Exiftool((str(EXIFTOOL),), timeout=60),
    )

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(raw)})
        inspected = await client.call_tool("inspect_image", {"path": str(raw)})
        assert not inspected.is_error, inspected.content
        frame_w, frame_h = inspected.structured_content["frame_width"], inspected.structured_content["frame_height"]
        assert frame_w and frame_h
        whole = {"x": 0, "y": 0, "w": frame_w, "h": frame_h, "fixed_ratio": False}
        cropped = await client.call_tool("edit_profile", {"path": str(raw), "adjustments": {"crop": whole}})
        too_wide = await client.call_tool(
            "edit_profile", {"path": str(raw), "adjustments": {"crop": {**whole, "w": frame_w + 1}}}
        )
        preview = await client.call_tool("render_preview", {"path": str(raw)})
        with Image.open(preview.structured_content["path"]) as jpeg:
            shown = jpeg.width / jpeg.height

    assert not cropped.is_error, cropped.content
    assert too_wide.is_error and "out_of_range" in too_wide.content[0].text
    assert abs(shown - frame_w / frame_h) < 0.01  # the whole frame, not a part of it
