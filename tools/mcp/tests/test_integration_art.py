"""End-to-end against a real ART install. Skipped unless ART is found and
ART_MCP_TEST_RAW names a raw file (copied to a temp folder, never touched)."""

import os
import shutil
from pathlib import Path

import pytest
from mcp.client.client import Client
from PIL import Image

from art_mcp import artdir
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ART"
ART_DIR = artdir.find_art_dir(None, os.environ, PROGRAM_FILES)
CLI = artdir.find_cli(ART_DIR) if ART_DIR else None
RAW = os.environ.get("ART_MCP_TEST_RAW")

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
    sidecar = artdir.sidecar_path(bright, artdir.user_config_dir(os.environ))
    sidecar.write_text("[Exposure]\nEnabled=true\nCompensation=2\n")
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
        assert "Exposure" in profile.structured_content["raw"]
        assert not edited.is_error, edited.content
        plain = mean_brightness(before.structured_content["path"])
        assert mean_brightness(after.structured_content["path"]) > plain + 20
        assert abs(mean_brightness(reset.structured_content["path"]) - plain) < 2
