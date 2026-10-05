"""apply_preset against a real ART install: a frame's crop and a preset's keys
both end up in its working profile. Skipped unless ART is found and
ART_MCP_TEST_RAW names a raw file (copied to a temp folder, never touched)."""

import os
import shutil
from pathlib import Path

import pytest
from mcp.client.client import Client

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


async def test_a_frames_crop_and_the_presets_keys_both_end_up_in_its_working_profile(tmp_path):
    raw = tmp_path / Path(RAW).name
    shutil.copyfile(RAW, raw)
    preset = tmp_path / "group.arp"
    preset.write_text("[Film Negative]\nRedRatio=1.3\nBlueRatio=0.8\n\n[Exposure]\nCompensation=0.5\n")
    server = build_server(
        ArtCli((str(CLI),), timeout=180),
        artdir.user_config_dir(os.environ),
        PreviewFolder(tmp_path / "previews"),
    )

    async with Client(server) as client:
        opened = await client.call_tool("open_image", {"path": str(raw)})
        assert not opened.is_error, opened.content
        edit = await client.call_tool("edit_profile", {
            "path": str(raw),
            "adjustments": {"crop": {"x": 300, "y": 160, "w": 2400, "h": 1600, "fixed_ratio": False}},
        })  # fmt: skip
        assert not edit.is_error, edit.content
        before = (await client.call_tool("get_profile", {"path": str(raw)})).structured_content["adjustments"]
        applied = await client.call_tool("apply_preset", {"paths": [str(raw)], "profile": str(preset)})
        after = (await client.call_tool("get_profile", {"path": str(raw)})).structured_content["adjustments"]

    assert not applied.is_error, applied.content
    item = applied.structured_content["items"][0]
    assert item["error"] is None and item["keys_changed"] >= 3
    assert {"Exposure", "Film Negative"} <= set(item["groups"])
    assert after["crop"] == before["crop"]  # the frame's own crop is still there
    assert after["crop"]["enabled"] is True and (after["crop"]["x"], after["crop"]["w"]) == (300, 2400)
    assert after["film_negative"]["red_ratio"] == 1.3 and after["film_negative"]["blue_ratio"] == 0.8
    assert after["exposure"]["compensation"] == 0.5
    # everything the preset doesn't mention is as it was
    unchanged = {k: v for k, v in before.items() if k not in ("film_negative", "exposure")}
    assert {k: v for k, v in after.items() if k not in ("film_negative", "exposure")} == unchanged
