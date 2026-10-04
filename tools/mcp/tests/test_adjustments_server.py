"""edit_profile / get_profile / describe_adjustments through the MCP client,
against the fake art-cli."""

import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

SIDECAR = """[Version]
Version=1045

[Exposure]
Enabled=false
Compensation=0
Black=0
HLRecovery=Off
HLRecoveryBlur=0

[White Balance]
Enabled=true
Setting=Camera
Temperature=6504
Green=1
Multipliers=1;1;1
"""


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "IMG_1.ARW"
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def server(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    return build_server(
        ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews")
    )


def error_text(result):
    return result.content[0].text.split("Error executing tool edit_profile: ")[-1]


async def opened(client, image, sidecar=SIDECAR):
    if sidecar is not None:
        image.with_name(image.name + ".arp").write_text(sidecar)
    await client.call_tool("open_image", {"path": str(image)})


async def test_exposure_adjustment_changes_the_render_and_reads_back_typed(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"exposure": {"compensation": 0.7}}}
        )
        profile = await client.call_tool("get_profile", {"path": str(image)})
        preview = await client.call_tool("render_preview", {"path": str(image)})

        assert not result.is_error, result.content
        assert {"group": "Exposure", "key": "Compensation", "value": "0.7"} in (
            result.structured_content["changed"]
        )
        assert profile.structured_content["adjustments"]["exposure"]["compensation"] == 0.7
        assert "Compensation" not in profile.structured_content["raw"].get("Exposure", {})
        assert b"Compensation=0.7" in Path(preview.structured_content["path"]).read_bytes()


async def test_out_of_range_names_the_range_and_changes_nothing(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"white_balance": {"temperature": 100000}}},
        )
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert result.is_error
    assert error_text(result).startswith("out_of_range")
    assert "1500..60000" in error_text(result)
    assert profile.structured_content["adjustments"]["white_balance"]["temperature"] == 6504


async def test_unknown_adjustment_field_is_unknown_key(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"exposure": {"gain": 1}}}
        )

    assert result.is_error
    assert error_text(result).startswith("unknown_key")


async def test_adjustment_and_raw_edit_on_one_key_conflict(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile",
            {
                "path": str(image),
                "adjustments": {"exposure": {"compensation": 1}},
                "raw_edits": [{"group": "Exposure", "key": "Compensation", "value": "2"}],
            },
        )

    assert result.is_error
    assert error_text(result).startswith("conflict")
    assert "[Exposure] Compensation" in error_text(result)


async def test_adjusting_a_disabled_tool_lists_the_implied_enable(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"exposure": {"black": 0.5}}}
        )
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert result.structured_content["implied"] == [
        {"group": "Exposure", "key": "Enabled", "value": "true"}
    ]
    assert profile.structured_content["adjustments"]["exposure"]["enabled"] is True


async def test_explicit_disable_wins(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"exposure": {"black": 0.5, "enabled": False}}},
        )
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert result.structured_content["implied"] == []
    assert profile.structured_content["adjustments"]["exposure"]["enabled"] is False


async def test_white_balance_temperature_implies_custom_temp(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"white_balance": {"temperature": 5200}}},
        )

    assert result.structured_content["implied"] == [
        {"group": "White Balance", "key": "Setting", "value": "CustomTemp"}
    ]


async def test_describe_adjustments_lists_both_tools_with_ranges_and_units(server):
    async with Client(server) as client:
        result = await client.call_tool("describe_adjustments", {})

    assert not result.is_error, result.content
    described = result.structured_content
    assert described["schema_ppversion"] == 1045
    comp = described["tools"]["exposure"]["fields"]["compensation"]
    assert (comp["minimum"], comp["maximum"], comp["unit"]) == (-12, 12, "EV")
    assert comp["key"] == "Compensation" and comp["description"]
    temp = described["tools"]["white_balance"]["fields"]["temperature"]
    assert (temp["minimum"], temp["maximum"], temp["unit"]) == (1500, 60000, "K")
    assert described["tools"]["exposure"]["fields"]["hl_recovery"]["enum"] == [
        "Off", "Blend", "Color", "Balanced",
    ]
    assert described["warnings"] == []


async def test_newer_art_profile_version_adds_a_warning(server, image):
    async with Client(server) as client:
        await opened(client, image, SIDECAR.replace("Version=1045", "Version=1099"))
        profile = await client.call_tool("get_profile", {"path": str(image)})
        edit = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"exposure": {"black": 0.5}}}
        )
        described = await client.call_tool("describe_adjustments", {})

    for result in (profile, edit, described):
        assert "1099" in result.structured_content["warnings"][0]


async def test_edit_profile_input_schema_shows_the_adjustments(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    schema = next(t for t in tools.tools if t.name == "edit_profile").input_schema
    exposure = schema["properties"]["adjustments"]
    assert "compensation" in str(exposure) and "-12" in str(exposure)
