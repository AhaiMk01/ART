"""End-to-end render_preview against a real ART started with --live-control.
Skipped unless ART_MCP_LIVE_E2E=1 and ART_MCP_LIVE_EXPECT names an image open
in its editor."""

import base64
import io
import os

import pytest
from mcp.client.client import Client
from PIL import Image, ImageStat

from art_mcp import artdir
from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server
from art_mcp.preview import PreviewFolder

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.environ.get("ART_MCP_LIVE_E2E") != "1", reason="ART_MCP_LIVE_E2E not set"),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_preview_of_the_expected_open_image(tmp_path):
    expected = os.environ.get("ART_MCP_LIVE_EXPECT")
    if not expected:
        pytest.skip("ART_MCP_LIVE_EXPECT not set")
    channel = ControlChannel(artdir.user_config_dir(os.environ))
    server = build_server(channel, previews=PreviewFolder(tmp_path / "previews"))
    async with Client(server) as client:
        result = await client.call_tool("render_preview", {"path": expected, "max_size": 300, "inline": True})
        missing = await client.call_tool("render_preview", {"path": expected + ".not-open"})

        assert not result.is_error, result.content
        preview = result.structured_content
        with Image.open(preview["path"]) as jpeg:
            assert jpeg.format == "JPEG"
            assert jpeg.size == (preview["width"], preview["height"])
            assert max(jpeg.size) <= 300
            assert max(ImageStat.Stat(jpeg.convert("L")).stddev) > 5  # not blank
        [inline] = [block for block in result.content if block.type == "image"]
        with Image.open(io.BytesIO(base64.b64decode(inline.data))) as decoded:
            assert decoded.size == (preview["width"], preview["height"])
    assert missing.is_error and "not_open" in missing.content[0].text
