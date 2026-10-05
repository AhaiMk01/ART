"""End-to-end against a real ART started with --live-control and an image
open in its editor. Skipped unless ART_MCP_LIVE_E2E=1; set
ART_MCP_LIVE_EXPECT to an image path to also check that it is listed."""

import os
from pathlib import Path

import anyio
import pytest
from mcp.client.client import Client

from art_mcp import artdir
from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.environ.get("ART_MCP_LIVE_E2E") != "1", reason="ART_MCP_LIVE_E2E not set"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_status_of_the_running_art():
    channel = ControlChannel(artdir.user_config_dir(os.environ))
    async with Client(build_server(channel)) as client:
        result = await client.call_tool("status", {})

    assert not result.is_error, result.content
    status = result.structured_content
    print(status)
    assert status["art_version"]
    expected = os.environ.get("ART_MCP_LIVE_EXPECT")
    if expected:
        paths = [Path(image["path"]).resolve() for image in status["images"]]
        assert Path(expected).resolve() in paths


async def test_get_profile_of_the_expected_open_image():
    expected = os.environ.get("ART_MCP_LIVE_EXPECT")
    if not expected:
        pytest.skip("ART_MCP_LIVE_EXPECT not set")
    channel = ControlChannel(artdir.user_config_dir(os.environ))
    async with Client(build_server(channel)) as client:
        result = await client.call_tool("get_profile", {"path": expected})
        missing = await client.call_tool("get_profile", {"path": expected + ".not-open"})

    assert not result.is_error, result.content
    profile = result.structured_content
    assert profile["ppversion"] and profile["history_position"] is not None
    assert {"exposure", "white_balance"} <= profile["adjustments"].keys()
    assert missing.is_error and "not_open" in missing.content[0].text


async def test_queue_exports_the_expected_open_image(tmp_path):
    expected = os.environ.get("ART_MCP_LIVE_EXPECT")
    if not expected:
        pytest.skip("ART_MCP_LIVE_EXPECT not set")
    channel = ControlChannel(artdir.user_config_dir(os.environ))
    output = tmp_path / f"{Path(expected).stem}.jpg"
    async with Client(build_server(channel)) as client:
        queued = await client.call_tool(
            "queue_export", {"path": expected, "folder": str(tmp_path), "format": "jpeg", "quality": 80}
        )
        assert not queued.is_error, queued.content
        if not queued.structured_content["running"]:
            started = await client.call_tool("queue_start", {})
            assert not started.is_error, started.content
        for _ in range(240):
            status = (await client.call_tool("queue_status", {})).structured_content
            mine = [e for e in status["entries"] if e["output"] and Path(e["output"]) == output]
            assert not any(e["state"] == "failed" for e in mine), mine
            if not mine:
                break
            await anyio.sleep(0.5)

    assert output.is_file() and output.stat().st_size > 0


async def test_a_failed_queue_entry_does_not_stop_the_others(tmp_path):
    """Leaves one failed entry in ART's queue: run it against a throwaway ART."""
    expected = os.environ.get("ART_MCP_LIVE_EXPECT")
    if not expected:
        pytest.skip("ART_MCP_LIVE_EXPECT not set")
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, so nothing can be created under it")
    good = tmp_path / f"{Path(expected).stem}.jpg"
    channel = ControlChannel(artdir.user_config_dir(os.environ))
    channel.request("queue_add", {"path": expected, "output": str(blocker / "x" / "y.jpg"), "format": "jpg"})
    async with Client(build_server(channel)) as client:
        await client.call_tool("queue_export", {"path": expected, "folder": str(tmp_path), "format": "jpeg"})
        await client.call_tool("queue_start", {})
        for _ in range(240):
            status = (await client.call_tool("queue_status", {})).structured_content
            if good.is_file() and not status["running"]:
                break
            await anyio.sleep(0.5)

    assert good.is_file()
    failed = [e for e in status["entries"] if e["state"] == "failed" and str(blocker) in (e["error"] or "")]
    assert len(failed) == 1
