"""edit_profile / get_profile / describe_adjustments through the MCP client,
against the fake art-cli."""

import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp import keyfile
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


async def test_crop_is_checked_against_the_image_frame(server, image):
    """The fake art-cli's frame is 6000x4000."""
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        inside = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"crop": {"x": 100, "y": 100, "w": 5900, "h": 3900}}},
        )
        outside = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"crop": {"x": 101}}},
        )

    assert not inside.is_error, inside.content
    assert outside.is_error and "out_of_range" in outside.content[0].text
    assert "6000x4000" in outside.content[0].text


async def test_a_partial_crop_on_an_unset_crop_asks_for_the_whole_rectangle(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"crop": {"x": 10}}}
        )

    assert result.is_error and "out_of_range" in result.content[0].text
    assert "x, y, w and h" in result.content[0].text


async def test_a_non_numeric_stored_crop_value_is_treated_as_unset(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool(
            "edit_profile",
            {"path": str(image), "raw_edits": [{"group": "Crop", "key": "W", "value": "wide"}]},
        )
        result = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"crop": {"x": 10}}}
        )

    assert result.is_error and "x, y, w and h" in result.content[0].text


async def test_lens_options_while_lens_profile_is_off_carry_a_warning(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"lens_profile": {"use_ca": True}}}
        )

    assert not result.is_error, result.content
    assert any("lc_mode" in w for w in result.structured_content["warnings"])


TONE_SIDECAR = SIDECAR + """
[ToneCurve]
Enabled=false
CurveMode=Neutral
HistogramMatching=true
Curve=0;
Curve2=0;
"""


async def test_tone_curve_edit_writes_art_keys_and_lists_what_it_implied(server, image):
    async with Client(server) as client:
        await opened(client, image, TONE_SIDECAR)
        edit = await client.call_tool(
            "edit_profile",
            {
                "path": str(image),
                "adjustments": {
                    "tone_curve": {
                        "mode": "Luminance",
                        "curve1": {"type": "spline", "points": [[0, 0], [0.5, 0.6], [1, 1]]},
                        "contrast": 10,
                        "curve2": {"type": "catmull_rom", "points": [[0, 0], [0.5, 0.4], [1, 1]]},
                    }
                },
            },
        )
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert not edit.is_error, edit.content
    changed = {(c["key"], c["value"]) for c in edit.structured_content["changed"]}
    assert changed == {
        ("CurveMode", "Luminance"), ("Curve", "1;0;0;0.5;0.6;1;1;"),
        ("Curve2", "4;0;0;0.5;0.4;1;1;"), ("Contrast", "10"), ("Enabled", "true"), ("HistogramMatching", "false"),
    }  # fmt: skip
    assert {(c["key"], c["value"]) for c in edit.structured_content["implied"]} == {
        ("Enabled", "true"), ("HistogramMatching", "false"),
    }  # fmt: skip
    tone = profile.structured_content["adjustments"]["tone_curve"]
    drawn = tone["curve1"].pop("drawn")
    assert tone["curve1"] == {"type": "spline", "points": [[0, 0], [0.5, 0.6], [1, 1]]}
    assert len(drawn) == 9 and drawn[0] == [0, 0] and drawn[4] == [0.5, 0.6]
    assert tone["curve2"]["type"] == "catmull_rom" and tone["mode2"] == "Luminance"
    assert "ToneCurve" not in profile.structured_content["raw"]


async def test_a_bad_tone_curve_is_out_of_range_and_changes_nothing(server, image):
    async with Client(server) as client:
        await opened(client, image, TONE_SIDECAR)
        bad = await client.call_tool(
            "edit_profile",
            {
                "path": str(image),
                "adjustments": {"tone_curve": {"curve1": {"type": "spline", "points": [[0, 0], [2, 1]]}}},
            },
        )
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert bad.is_error and "out_of_range" in bad.content[0].text
    assert profile.structured_content["adjustments"]["tone_curve"]["curve1"] == {"type": "linear"}


async def test_a_parametric_tone_curve_stays_raw_in_get_profile(server, image):
    async with Client(server) as client:
        await opened(client, image, TONE_SIDECAR.replace("Curve=0;", "Curve=2;0;0;1;0.5;"))
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert profile.structured_content["raw"]["ToneCurve"] == {"Curve": "2;0;0;1;0.5;"}
    assert "curve1" not in profile.structured_content["adjustments"]["tone_curve"]


async def test_describe_adjustments_and_input_schema_carry_tone_curve(server):
    async with Client(server) as client:
        described = await client.call_tool("describe_adjustments", {})
        tools = await client.list_tools()

    tone = described.structured_content["tools"]["tone_curve"]
    assert "sRGB" in tone["description"] and tone["fields"]["curve1"]["key"] == "Curve"
    schema = next(t for t in tools.tools if t.name == "edit_profile").input_schema
    assert "catmull_rom" in str(schema) and "contrast" in str(schema)


CC_SIDECAR = (
    SIDECAR + "\n" + (Path(__file__).parent / "data" / "art_default_colorcorrection.arp").read_text()
)
FADED_SLIDE = {
    "color_correction": {
        "regions": [
            {"r": {"slope": 1.1844, "power": 1.0204}, "b": {"slope": 0.9239, "power": 0.6241}},
            {
                "b": {"slope": 0.85},
                "mask": {
                    "inverted": True,
                    "shapes": [{"type": "rectangle", "width": 110, "height": 110, "roundness": 100, "feather": 60}],
                },
            },
        ]
    }
}


async def test_color_correction_regions_edit_render_and_read_back_typed(server, image):
    async with Client(server) as client:
        await opened(client, image, CC_SIDECAR)
        edit = await client.call_tool("edit_profile", {"path": str(image), "adjustments": FADED_SLIDE})
        profile = await client.call_tool("get_profile", {"path": str(image)})
        preview = await client.call_tool("render_preview", {"path": str(image)})
        rendered = Path(preview.structured_content["path"]).read_bytes()

    assert not edit.is_error, edit.content
    changed = {(c["key"], c["value"]) for c in edit.structured_content["changed"]}
    assert {("Mode_1", "RGB"), ("SlopeR_1", "1.1844"), ("PowerB_1", "0.6241"), ("Enabled", "true")} <= changed
    assert {("Mode_2", "RGB"), ("MaskInverted_2", "true"), ("AreaMaskRoundness_2", "100"),
            ("AreaMaskShapeFeather_2", "60")} <= changed  # fmt: skip
    implied = {(c["key"], c["value"]) for c in edit.structured_content["implied"]}
    assert implied == {("Mode_1", "RGB"), ("Enabled", "true"), ("AreaMaskEnabled_2", "true")}
    typed = profile.structured_content["adjustments"]["color_correction"]
    assert typed["enabled"] is True
    assert typed["regions"][0]["b"] == {"slope": 0.9239, "offset": 0.0, "power": 0.6241}
    assert typed["regions"][1]["mask"]["inverted"] is True
    assert typed["regions"][1]["mask"]["shapes"][0]["width"] == 110
    raw = profile.structured_content["raw"]["ColorCorrection"]
    assert "SlopeR_1" not in raw and "AreaMaskType_2" not in raw
    assert b"Mode_2=RGB" in rendered and b"AreaMaskType_2=rectangle" in rendered
    assert b"AreaMaskShapeBlur_2=0" in rendered and b"ExternalMaskFeather_2=0" in rendered


async def test_a_saved_partial_profile_carries_whole_color_correction_regions(server, image):
    async with Client(server) as client:
        await opened(client, image, CC_SIDECAR)
        await client.call_tool("edit_profile", {"path": str(image), "adjustments": FADED_SLIDE})
        dest = image.with_name("preset.arp")
        saved = await client.call_tool(
            "save_partial_profile", {"path": str(image), "dest": str(dest)}
        )

    assert not saved.is_error, saved.content
    group = keyfile.loads(dest.read_text())["ColorCorrection"]
    assert group["Mode_2"] == "RGB" and group["SlopeG_1"] == "1" and group["HSLGamma_2"] == "2.3999999999999999"


async def test_a_color_correction_gap_or_unsupported_mask_is_out_of_range(server, image):
    async with Client(server) as client:
        await opened(client, image, CC_SIDECAR)
        gap = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"color_correction": {"regions": [None, None, {}]}}},
        )
        slope = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"color_correction": {"regions": [{"r": {"slope": 11}}]}}},
        )
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert gap.is_error and "out_of_range" in gap.content[0].text and "index 1" in gap.content[0].text
    assert slope.is_error and "out_of_range" in slope.content[0].text and "regions.0.r.slope" in slope.content[0].text
    assert profile.structured_content["adjustments"]["color_correction"]["regions"] == [None]


async def test_describe_and_input_schema_carry_color_correction(server):
    async with Client(server) as client:
        described = await client.call_tool("describe_adjustments", {})
        tools = await client.list_tools()

    tool = described.structured_content["tools"]["color_correction"]
    assert "v*slope + offset/2" in tool["description"] and "inverse" in tool["description"]
    schema = next(t for t in tools.tools if t.name == "edit_profile").input_schema
    text = str(schema)
    assert "roundness" in text and "strength_start" in text and "intersect" in text
