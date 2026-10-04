"""End-to-end against a real ART started with --live-control and an image
open in its editor. Skipped unless ART_MCP_LIVE_E2E=1; set
ART_MCP_LIVE_EXPECT to an image path to also check that it is listed."""

import os
from pathlib import Path

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
