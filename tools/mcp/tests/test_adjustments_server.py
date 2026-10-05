"""edit_profile / get_profile / describe_adjustments through the MCP client,
against the fake art-cli."""

import sys
import time
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp import keyfile
from art_mcp.preview import PreviewFolder
from art_mcp.render import profile_ops
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
        assert result.structured_content["changed"]["Exposure"] == {"Compensation": "0.7"}
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

    assert result.structured_content["implied"] == {"Exposure": {"Enabled": "true"}}
    assert profile.structured_content["adjustments"]["exposure"]["enabled"] is True


async def test_explicit_disable_wins(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"exposure": {"black": 0.5, "enabled": False}}},
        )
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert result.structured_content["implied"] == {}
    assert profile.structured_content["adjustments"]["exposure"]["enabled"] is False


async def test_white_balance_temperature_implies_custom_temp(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile",
            {"path": str(image), "adjustments": {"white_balance": {"temperature": 5200}}},
        )

    assert result.structured_content["implied"] == {"White Balance": {"Setting": "CustomTemp"}}


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
    assert "#/$defs/Adjustments" in str(schema["properties"]["adjustments"])  # the models are defined once
    compensation = schema["$defs"]["Exposure"]["properties"]["compensation"]
    assert compensation["minimum"] == -12 and compensation["maximum"] == 12


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
    assert edit.structured_content["changed"] == {"ToneCurve": {
        "CurveMode": "Luminance", "Curve": "1;0;0;0.5;0.6;1;1;", "Curve2": "4;0;0;0.5;0.4;1;1;", "Contrast": "10",
    }}  # fmt: skip
    assert edit.structured_content["implied"] == {"ToneCurve": {"Enabled": "true", "HistogramMatching": "false"}}
    tone = profile.structured_content["adjustments"]["tone_curve"]
    assert edit.structured_content["drawn"] == {"curve1": tone["curve1"]["drawn"], "curve2": tone["curve2"]["drawn"]}
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
    changed = edit.structured_content["changed"]["ColorCorrection"]
    assert {"SlopeR_1": "1.1844", "PowerB_1": "0.6241", "Mode_2": "RGB", "MaskInverted_2": "true",
            "AreaMaskRoundness_2": "100", "AreaMaskShapeFeather_2": "60"}.items() <= changed.items()  # fmt: skip
    implied = edit.structured_content["implied"]["ColorCorrection"]
    assert implied == {"Mode_1": "RGB", "Enabled": "true", "AreaMaskEnabled_2": "true"}
    assert not implied.keys() & changed.keys()  # each value once
    # Region 2 and its shape are new: the keys ART writes for them are counted, not listed.
    assert edit.structured_content["created"] == {"ColorCorrection": [
        "region 2 (78 keys at their defaults)", "region 2 mask shape 0 (5 keys at their defaults)"]}  # fmt: skip
    assert "HSLGamma_2" not in changed and "AreaMaskX_2" not in changed and len(changed) < 20
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


# -- the result of one image has no `"profile": null` --------------------------------


async def test_the_result_of_one_image_has_no_profile_field_unless_full(server, image):
    async with Client(server) as client:
        await opened(client, image)
        plain = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"exposure": {"compensation": 0.7}}}
        )
        full = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"exposure": {"compensation": 0.8}}, "full": True}
        )

    assert set(plain.structured_content) == {"changed", "implied", "created", "drawn", "warnings"}
    assert '"profile"' not in plain.content[0].text
    assert full.structured_content["profile"]["adjustments"]["exposure"]["compensation"] == 0.8


# -- edit_profile(paths): the same edit for several images ---------------------------


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    paths = []
    for name in ("FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"):
        (folder / name).write_bytes(b"raw")
        paths.append(folder / name)
    return paths


async def open_all(client, images, sidecar=SIDECAR):
    for image in images:
        await opened(client, image, sidecar)


async def edit_all(client, images, **args):
    return await client.call_tool("edit_profile", {"paths": [str(p) for p in images], **args})


async def compensation(client, image):
    profile = await client.call_tool("get_profile", {"path": str(image)})
    return profile.structured_content["adjustments"]["exposure"]["compensation"]


async def test_one_edit_goes_to_every_path_and_the_result_is_one_compact_entry_per_image(server, images):
    async with Client(server) as client:
        await open_all(client, images)
        result = await edit_all(client, images, adjustments={"exposure": {"compensation": 0.7}})
        values = [await compensation(client, p) for p in images]

    assert not result.is_error, result.content
    assert set(result.structured_content) == {"items", "failed"}
    assert result.structured_content["failed"] == 0
    assert result.structured_content["items"] == [
        {"path": str(p), "changed": 1, "implied": {"Exposure": {"Enabled": "true"}}, "warnings": [], "error": None}
        for p in images
    ]  # in request order, each with the paths as given
    assert values == [0.7, 0.7, 0.7]


async def test_each_image_keeps_its_own_working_profile_and_its_own_changes(server, images, tmp_path):
    async with Client(server) as client:
        await open_all(client, images)
        await edit_all(client, images, adjustments={"exposure": {"compensation": 0.7}})
        await client.call_tool(
            "edit_profile", {"path": str(images[1]), "adjustments": {"exposure": {"compensation": 2}}}
        )
        values = [await compensation(client, p) for p in images]
        dest = tmp_path / "frame3.arp"
        saved = await client.call_tool("save_partial_profile", {"path": str(images[2]), "dest": str(dest)})

    assert values == [0.7, 2.0, 0.7]
    assert not saved.is_error, saved.content
    assert keyfile.loads(dest.read_text())["Exposure"]["Compensation"] == "0.7"  # a change of that image like any


async def test_an_image_that_already_has_the_values_counts_zero_changed(server, images):
    async with Client(server) as client:
        await open_all(client, images)
        await client.call_tool(
            "edit_profile", {"path": str(images[0]), "adjustments": {"exposure": {"compensation": 0.7}}}
        )
        result = await edit_all(client, images, adjustments={"exposure": {"compensation": 0.7}})

    first, second, third = result.structured_content["items"]
    assert (first["changed"], first["implied"]) == (0, {})
    assert (second["changed"], third["changed"]) == (1, 1)


async def test_raw_edits_go_to_every_path_too(server, images):
    async with Client(server) as client:
        await open_all(client, images)
        result = await edit_all(client, images, raw_edits=[{"group": "Exposure", "key": "Black", "value": "5"}])
        profile = await client.call_tool("get_profile", {"path": str(images[2])})

    assert [i["changed"] for i in result.structured_content["items"]] == [1, 1, 1]
    assert profile.structured_content["adjustments"]["exposure"]["black"] == 5


async def test_an_image_that_is_not_open_is_its_own_error_and_the_others_still_change(server, images):
    async with Client(server) as client:
        await open_all(client, [images[0], images[2]])  # images[1] was never opened
        result = await edit_all(client, images, adjustments={"exposure": {"compensation": 0.7}})
        first, last = await compensation(client, images[0]), await compensation(client, images[2])

    ok1, missing, ok2 = result.structured_content["items"]
    assert not result.is_error, result.content
    assert missing["error"].startswith("not_open") and missing["changed"] is None
    assert (missing["implied"], missing["warnings"]) == ({}, [])
    assert ok1["error"] is None and ok2["error"] is None and ok1["changed"] == 1
    assert result.structured_content["failed"] == 1
    assert (first, last) == (0.7, 0.7)


async def test_an_edit_one_image_refuses_is_its_own_error_and_leaves_its_profile_alone(server, images):
    async with Client(server) as client:
        await open_all(client, images[:2])
        await opened(client, images[2], SIDECAR.replace("Black=0\n", ""))  # no [Exposure] Black key
        result = await edit_all(client, images, raw_edits=[{"group": "Exposure", "key": "Black", "value": "5"}])
        blacks = []
        for p in images:
            profile = await client.call_tool("get_profile", {"path": str(p)})
            blacks.append(profile.structured_content["adjustments"]["exposure"]["black"])

    items = result.structured_content["items"]
    assert [i["error"] is None for i in items] == [True, True, False]
    assert items[2]["error"].startswith("unknown_key") and "[Exposure] Black" in items[2]["error"]
    assert result.structured_content["failed"] == 1
    assert blacks == [5, 5, 0]  # the third reads Black as ART's default 0: not changed


async def test_an_edit_every_image_refuses_fails_every_item_with_that_error_and_changes_nothing(server, images):
    async with Client(server) as client:
        await open_all(client, images)
        result = await edit_all(client, images, adjustments={"exposure": {"compensation": 99}})
        values = [await compensation(client, p) for p in images]

    assert not result.is_error, result.content
    items = result.structured_content["items"]
    assert [i["error"].startswith("out_of_range") for i in items] == [True, True, True]
    assert "-12..12" in items[0]["error"] and result.structured_content["failed"] == 3
    assert values == [0, 0, 0]


async def test_a_crop_is_checked_per_image_with_paths(server, images):
    async with Client(server) as client:
        await open_all(client, images)
        result = await edit_all(client, images, adjustments={"crop": {"x": 100, "y": 100, "w": 6000, "h": 3900}})

    assert [i["error"] is not None and "out_of_range" in i["error"] for i in result.structured_content["items"]] == [
        True, True, True,
    ]


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"path": "a.ARW", "paths": ["a.ARW"]}, "not both"),
        ({}, "path or paths"),
        ({"paths": []}, "paths is empty"),
        ({"paths": [f"{i}.ARW" for i in range(51)]}, "51 entries; the most one call takes is 50"),
        ({"paths": ["a.ARW"], "full": True}, "full"),
    ],
)
async def test_a_bad_choice_of_images_is_out_of_range_before_anything_changes(server, image, args, text):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool(
            "edit_profile", {"adjustments": {"exposure": {"compensation": 1}}, **args}
        )
        value = await compensation(client, image)

    assert result.is_error and "out_of_range" in error_text(result) and text in error_text(result)
    assert value == 0


async def test_fifty_paths_are_accepted(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await edit_all(client, [image] * 50, adjustments={"exposure": {"compensation": 1}})

    assert not result.is_error, result.content
    assert len(result.structured_content["items"]) == 50


async def test_the_tool_describes_paths_and_its_two_result_shapes(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    tool = next(t for t in tools.tools if t.name == "edit_profile")
    assert "path" not in tool.input_schema.get("required", [])  # one of path, paths
    assert {"type": "array", "items": {"type": "string"}} in tool.input_schema["properties"]["paths"]["anyOf"]
    assert "`paths`" in tool.description and "50" in tool.description
    assert {"EditResult", "EditBatch", "ImageEdit"} <= tool.output_schema["$defs"].keys()
    assert tool.output_schema["type"] == "object"  # a tool's output schema is an object either way


# -- edit_profile(items): its own edit for each image --------------------------------


async def edit_items(client, items):
    return await client.call_tool("edit_profile", {"items": items})


def exposure_item(image, value, **extra):
    return {"path": str(image), "adjustments": {"exposure": {"compensation": value}}, **extra}


async def test_items_give_each_image_its_own_edit_and_the_result_is_the_compact_per_image_shape(server, images):
    async with Client(server) as client:
        await open_all(client, images)
        result = await edit_items(client, [
            exposure_item(images[0], 0.7),
            exposure_item(images[1], 2, raw_edits=[{"group": "Exposure", "key": "Black", "value": "5"}]),
            {"path": str(images[2]), "raw_edits": [{"group": "Exposure", "key": "Black", "value": "3"}]},
        ])  # fmt: skip
        values = [await compensation(client, p) for p in images]
        blacks = []
        for p in images:
            profile = await client.call_tool("get_profile", {"path": str(p)})
            blacks.append(profile.structured_content["adjustments"]["exposure"]["black"])

    assert not result.is_error, result.content
    assert set(result.structured_content) == {"items", "failed"}  # the shape of the `paths` form
    assert result.structured_content["failed"] == 0
    enabled = {"Exposure": {"Enabled": "true"}}
    assert result.structured_content["items"] == [
        {"path": str(images[0]), "changed": 1, "implied": enabled, "warnings": [], "error": None},
        {"path": str(images[1]), "changed": 2, "implied": enabled, "warnings": [], "error": None},
        {"path": str(images[2]), "changed": 1, "implied": {}, "warnings": [], "error": None},
    ]  # in request order, each with the path as given
    assert values == [0.7, 2.0, 0]
    assert blacks == [0, 5, 3]


async def test_two_items_for_one_image_are_applied_in_order_among_other_images(server, images, monkeypatch):
    first, other, *_ = images
    edit_one = profile_ops.edit_one

    def slow_start(session, path, adjustments, raw_edits, full):
        if adjustments and adjustments["exposure"]["compensation"] == 1:
            time.sleep(0.3)  # a worker that takes a later item of the image meanwhile would overtake it
        return edit_one(session, path, adjustments, raw_edits, full)

    monkeypatch.setattr(profile_ops, "edit_one", slow_start)
    async with Client(server) as client:
        await open_all(client, images[:2])
        result = await edit_items(client, [
            item for n in range(1, 11) for item in (exposure_item(first, n), exposure_item(other, 12 - n))
        ])  # fmt: skip
        values = [await compensation(client, p) for p in (first, other)]

    items = result.structured_content["items"]
    assert [i["path"] for i in items] == [str(p) for n in range(10) for p in (first, other)]
    assert [i["changed"] for i in items] == [1] * 20  # each one changes the value the one before it left
    assert values == [10, 2]  # the last of each image's items won


async def test_the_same_edit_twice_for_one_image_changes_nothing_the_second_time(server, images):
    async with Client(server) as client:
        await open_all(client, images[:1])
        result = await edit_items(client, [exposure_item(images[0], 0.7), exposure_item(images[0], 0.7)])

    assert [i["changed"] for i in result.structured_content["items"]] == [1, 0]


async def test_an_item_that_fails_is_its_own_error_and_the_others_still_change(server, images):
    async with Client(server) as client:
        await open_all(client, images[:1] + images[2:])  # images[1] is not open
        await opened(client, images[2], SIDECAR.replace("Black=0\n", ""))  # no [Exposure] Black key
        result = await edit_items(client, [
            exposure_item(images[0], 0.7),
            exposure_item(images[1], 0.7),
            exposure_item(images[0], 99),
            {"path": str(images[2]), "raw_edits": [{"group": "Exposure", "key": "Black", "value": "5"}]},
            exposure_item(images[2], 1.5),
        ])  # fmt: skip
        values = [await compensation(client, p) for p in (images[0], images[2])]

    assert not result.is_error, result.content
    ok, not_open, too_big, no_key, last = result.structured_content["items"]
    assert not_open["error"].startswith("not_open") and not_open["changed"] is None
    assert too_big["error"].startswith("out_of_range") and "-12..12" in too_big["error"]
    assert no_key["error"].startswith("unknown_key") and "[Exposure] Black" in no_key["error"]
    assert (ok["error"], last["error"], ok["changed"], last["changed"]) == (None, None, 1, 1)
    assert result.structured_content["failed"] == 3
    assert values == [0.7, 1.5]


async def test_a_crop_is_checked_per_item(server, images):
    async with Client(server) as client:
        await open_all(client, images[:2])
        result = await edit_items(client, [
            {"path": str(images[0]), "adjustments": {"crop": {"x": 100, "y": 100, "w": 5000, "h": 3000}}},
            {"path": str(images[1]), "adjustments": {"crop": {"x": 100, "y": 100, "w": 6000, "h": 3900}}},
        ])  # fmt: skip

    ok, too_big = result.structured_content["items"]
    assert ok["error"] is None and ok["changed"] >= 1
    assert too_big["error"].startswith("out_of_range")


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"path": "a.ARW"}, "not path and items"),
        ({"paths": ["a.ARW"]}, "not paths and items"),
        ({"adjustments": {"exposure": {"compensation": 1}}}, "in each item"),
        ({"raw_edits": [{"group": "Exposure", "key": "Black", "value": "5"}]}, "in each item"),
        ({"full": True}, "full is for one image"),
        ({"items": []}, "items is empty"),
        ({"items": [{"path": f"{i}.ARW"} for i in range(51)]}, "items has 51 entries; the most one call takes is 50"),
    ],
)
async def test_a_bad_call_with_items_is_out_of_range_before_anything_changes(server, image, args, text):
    async with Client(server) as client:
        await opened(client, image)
        result = await client.call_tool("edit_profile", {"items": [exposure_item(image, 1)], **args})
        value = await compensation(client, image)

    assert result.is_error and "out_of_range" in error_text(result) and text in error_text(result)
    assert value == 0


async def test_fifty_items_are_accepted(server, image):
    async with Client(server) as client:
        await opened(client, image)
        result = await edit_items(client, [exposure_item(image, n / 10) for n in range(50)])

    assert not result.is_error, result.content
    assert len(result.structured_content["items"]) == 50
    assert [i["changed"] for i in result.structured_content["items"]].count(1) == 49  # the first one is 0.0: no change


async def test_an_item_the_schema_refuses_fails_the_call_as_a_schema_error(server, image):
    async with Client(server) as client:
        await opened(client, image)
        no_path = await edit_items(client, [{"adjustments": {"exposure": {"compensation": 1}}}])
        stray = await edit_items(client, [{"path": str(image), "adjusments": {"exposure": {"compensation": 1}}}])

    assert no_path.is_error and "path" in error_text(no_path)
    assert stray.is_error and "adjusments" in error_text(stray)


async def test_the_tool_describes_items_as_a_third_alternative(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    tool = next(t for t in tools.tools if t.name == "edit_profile")
    schema = tool.input_schema
    assert "path" not in schema.get("required", []) and "items" not in schema.get("required", [])
    item = schema["$defs"]["EditItem"]
    assert item["required"] == ["path"] and set(item["properties"]) == {"path", "adjustments", "raw_edits"}
    assert item["properties"]["adjustments"] == {"$ref": "#/$defs/Adjustments"}
    assert "`items`" in tool.description and "its own" in tool.description and "50" in tool.description
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(schema)
    assert not list(validator.iter_errors({"items": [exposure_item("a.ARW", 1), {"path": "b.ARW"}]}))
    assert list(validator.iter_errors({"items": [exposure_item("a.ARW", 13)]}))  # the range travels into the item
