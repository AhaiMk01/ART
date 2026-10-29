"""The Render server's tools and ``art-axi``'s commands stay in step: every
MCP tool has a CLI command, or is listed here as MCP-only on purpose. A new
tool that is neither fails, so whoever adds it decides."""

import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp.axi import cli
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

MCP_ONLY = {
    "inspect_images": "`art-axi inspect` takes several paths",
    "apply_preset": "not in the CLI yet",
    "save_partial_profile": "not in the CLI yet",
    "compare_passes": "not in the CLI yet",
}
"""Tool -> why it has no command of its own."""


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def mcp_tool_names(tmp_path) -> set[str]:
    server = build_server(ArtCli((sys.executable, str(FAKE))), tmp_path, PreviewFolder(tmp_path / "previews"))
    async with Client(server) as client:
        return {tool.name for tool in (await client.list_tools()).tools}


async def test_every_tool_has_a_command_or_is_mcp_only(tmp_path):
    tools = await mcp_tool_names(tmp_path)

    unaccounted = tools - set(cli.TOOL_NAMES) - set(MCP_ONLY)
    assert not unaccounted, f"add a command to art-axi (and TOOL_NAMES) or list these in MCP_ONLY: {unaccounted}"


async def test_the_lists_name_only_real_tools(tmp_path):
    tools = await mcp_tool_names(tmp_path)

    assert set(cli.TOOL_NAMES) <= tools, set(cli.TOOL_NAMES) - tools
    assert set(MCP_ONLY) <= tools, set(MCP_ONLY) - tools
    assert not set(MCP_ONLY) & set(cli.TOOL_NAMES)


def test_mapped_commands_exist():
    assert set(cli.TOOL_NAMES.values()) <= set(cli.COMMANDS)
