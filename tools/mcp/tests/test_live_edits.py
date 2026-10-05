"""The Live server's edits, undo/redo, open and save, against a fake ART
editor, through an in-process MCP client."""

import json

import pytest
from fake_live_art import FakeArt, FakeEditor, fail
from mcp.client.client import Client

from art_mcp import keyfile
from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server

pytestmark = pytest.mark.anyio

PROFILE = """[Version]
AppVersion=1.26.test
Version=1045

[Exposure]
Enabled=true
Compensation=0
Black=0

[White Balance]
Enabled=true
Setting=Camera
Temperature=5000
Green=1

[Crop]
Enabled=false
X=0
Y=0
W=6000
H=4000

[Local Contrast]
Enabled=false
Contrast=0

[ToneCurve]
Enabled=false
"""


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def art(tmp_path):
    fake = FakeArt(tmp_path / "config")
    yield fake
    fake.close()


@pytest.fixture
def editor(art, tmp_path):
    editor = FakeEditor(art)
    editor.add(str(tmp_path / "a.ARW"), PROFILE)
    return editor


@pytest.fixture
def image(tmp_path):
    return str(tmp_path / "a.ARW")


def live(art, **kwargs):
    return build_server(ControlChannel(art.config_dir), **kwargs)


def text_of(result):
    return result.content[0].text


async def test_edit_sends_only_the_changed_keys_as_one_labelled_entry(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "path": image, "adjustments": {"exposure": {"compensation": 1.0}},
        })  # fmt: skip

    assert not result.is_error, result.content
    assert result.structured_content["changed"] == {"Exposure": {"Compensation": "1"}}
    assert result.structured_content["history_position"] == 1
    assert len(editor.applied) == 1
    sent = editor.applied[0]
    assert keyfile.loads(sent["profile"]) == {"Exposure": {"Compensation": "1"}}
    assert sent["label"] == "Agent: Exposure"
    assert editor.labels(image) == ["Photo loaded", "Agent: Exposure"]
    assert editor.profile(image)["Exposure"]["Compensation"] == "1"


async def test_implied_changes_are_sent_and_reported(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "path": image,
            "adjustments": {"white_balance": {"temperature": 6500}, "local_contrast": {"contrast": 20}},
        })  # fmt: skip

    assert not result.is_error, result.content
    assert result.structured_content["implied"] == {
        "White Balance": {"Setting": "CustomTemp"}, "Local Contrast": {"Enabled": "true"},
    }
    sent = keyfile.loads(editor.applied[0]["profile"])
    assert sent["White Balance"] == {"Temperature": "6500", "Setting": "CustomTemp"}
    assert sent["Local Contrast"] == {"Contrast": "20", "Enabled": "true"}
    assert editor.applied[0]["label"] == "Agent: White Balance, Local Contrast"


async def test_raw_edit_groups_are_named_in_the_label(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "path": image,
            "adjustments": {"exposure": {"compensation": 0.5}},
            "raw_edits": [
                {"group": "ToneCurve", "key": "Enabled", "value": "true"},
                {"group": "Exposure", "key": "Black", "value": "10"},
            ],
        })  # fmt: skip

    assert not result.is_error, result.content
    assert editor.applied[0]["label"] == "Agent: Exposure, Tone Curve"


@pytest.mark.parametrize(
    ("args", "code"),
    [
        ({"adjustments": {"exposure": {"compensation": 99}}}, "out_of_range"),
        ({"adjustments": {"exposure": {"nope": 1}}}, "unknown_key"),
        ({"raw_edits": [{"group": "Nope", "key": "X", "value": "1"}]}, "unknown_key"),
        (
            {
                "adjustments": {"exposure": {"compensation": 1}},
                "raw_edits": [{"group": "Exposure", "key": "Compensation", "value": "2"}],
            },
            "conflict",
        ),
        ({"adjustments": {"crop": {"x": 100, "w": 6000}}}, "out_of_range"),
        ({"raw_edits": [{"group": "Version", "key": "Version", "value": "1000"}]}, "unknown_key"),
    ],
)
async def test_a_bad_edit_changes_nothing_in_art(art, editor, image, args, code):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {"path": image, **args})

    assert result.is_error and f"{code}:" in text_of(result), text_of(result)
    assert editor.applied == []


async def test_a_crop_inside_the_image_is_accepted(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "path": image, "adjustments": {"crop": {"x": 100, "w": 5900}},
        })  # fmt: skip

    assert not result.is_error, result.content
    assert keyfile.loads(editor.applied[0]["profile"])["Crop"] == {"X": "100", "W": "5900", "Enabled": "true"}


async def test_a_crop_of_an_image_of_unknown_size_is_applied_with_a_warning(art, editor, tmp_path):
    other = str(tmp_path / "b.ARW")
    editor.add(other, PROFILE, width=None, height=None)
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "path": other, "adjustments": {"crop": {"x": 100}},
        })  # fmt: skip

    assert not result.is_error, result.content
    assert any("not checked" in w for w in result.structured_content["warnings"])


async def test_an_edit_that_changes_nothing_makes_no_history_entry(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "path": image, "adjustments": {"exposure": {"compensation": 0}},
        })  # fmt: skip

    assert not result.is_error, result.content
    assert result.structured_content["changed"] == {}
    assert result.structured_content["history_position"] == 0
    assert editor.applied == []


async def test_edit_of_an_image_not_open_is_not_open(art, editor, tmp_path):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "path": str(tmp_path / "x.ARW"), "adjustments": {"exposure": {"compensation": 1}},
        })  # fmt: skip

    assert result.is_error and "not_open:" in text_of(result)


async def test_undo_and_redo_move_through_the_history(art, editor, image):
    async with Client(live(art)) as client:
        await client.call_tool("edit_profile", {
            "path": image, "adjustments": {"exposure": {"compensation": 1}},
        })  # fmt: skip
        undone = await client.call_tool("undo", {"path": image})
        after_undo = await client.call_tool("get_profile", {"path": image})
        redone = await client.call_tool("redo", {"path": image})
        after_redo = await client.call_tool("get_profile", {"path": image})

    assert undone.structured_content == {"history_position": 0}
    assert after_undo.structured_content["adjustments"]["exposure"]["compensation"] == 0
    assert redone.structured_content == {"history_position": 1}
    assert after_redo.structured_content["adjustments"]["exposure"]["compensation"] == 1
    assert sum(json.loads(line).get("op") == "undo" for line in art.received) == 1


async def test_undo_of_an_image_not_open_is_not_open(art, editor, tmp_path):
    async with Client(live(art)) as client:
        result = await client.call_tool("undo", {"path": str(tmp_path / "x.ARW")})

    assert result.is_error and "not_open:" in text_of(result)


async def test_open_image_waits_until_art_lists_it(art, editor, tmp_path):
    path = str(tmp_path / "new.ARW")
    editor.loadable.add(path)
    editor.open_delay = 0.5
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": path})

    assert not result.is_error, result.content
    assert result.structured_content == {"path": path, "already_open": False, "profile_applied": None}


async def test_open_image_of_an_open_image_says_so(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": image})

    assert result.structured_content == {"path": image, "already_open": True, "profile_applied": None}
    assert editor.applied == []


async def test_open_image_with_a_profile_applies_it_once_art_has_loaded_the_image(art, editor, tmp_path):
    path = str(tmp_path / "new.ARW")
    editor.loadable.add(path)
    editor.open_delay = 0.3
    preset = tmp_path / "roll.arp"
    preset.write_text("[Exposure]\nCompensation=1.5\n")
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": path, "profile": str(preset)})

    assert not result.is_error, result.content
    assert result.structured_content == {"path": path, "already_open": False, "profile_applied": str(preset)}
    assert len(editor.applied) == 1
    assert keyfile.loads(editor.applied[0]["profile"]) == {"Exposure": {"Compensation": "1.5"}}
    assert editor.applied[0]["label"] == "Agent: roll.arp"
    assert editor.labels(path) == ["Photo loaded", "Agent: roll.arp"]  # one History entry: undo reverts it
    assert editor.profile(path)["Exposure"]["Compensation"] == "1.5"


async def test_a_full_profile_is_applied_without_its_version_group(art, editor, tmp_path):
    path = str(tmp_path / "new.ARW")
    editor.loadable.add(path)
    full = tmp_path / "full.arp"
    full.write_text(PROFILE.replace("Compensation=0", "Compensation=-2"))  # a sidecar: [Version] and all
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": path, "profile": str(full)})

    assert not result.is_error, result.content  # ART refuses an edit with [Version]
    sent = keyfile.loads(editor.applied[0]["profile"])
    assert "Version" not in sent
    assert sent["Exposure"]["Compensation"] == "-2" and sent["White Balance"]["Setting"] == "Camera"
    assert editor.profile(path)["Exposure"]["Compensation"] == "-2"


async def test_a_profile_is_applied_over_an_image_already_open(art, editor, image, tmp_path):
    preset = tmp_path / "roll.arp"
    preset.write_text("[Exposure]\nBlack=5\n")
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": image, "profile": str(preset)})

    assert result.structured_content["already_open"] is True
    assert editor.profile(image)["Exposure"] == {"Enabled": "true", "Compensation": "0", "Black": "5"}


async def test_a_profile_art_refuses_leaves_the_image_open_and_says_so(art, editor, tmp_path):
    path = str(tmp_path / "new.ARW")
    editor.loadable.add(path)
    preset = tmp_path / "roll.arp"
    preset.write_text("[Exposure]\nCompensation=1.5\n")
    art.ops["apply_profile"] = fail("bad_request", "ART could not load these values; nothing was changed")
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": path, "profile": str(preset)})
        status = await client.call_tool("status", {})

    assert result.is_error and "bad_request:" in text_of(result)
    assert "the image is open" in text_of(result)
    assert path in [i["path"] for i in status.structured_content["images"]]


@pytest.mark.parametrize(("text", "code"), [(None, "not_found"), ("not a profile", "bad_request")])
async def test_an_unusable_profile_fails_before_the_image_is_opened(art, editor, tmp_path, text, code):
    path = str(tmp_path / "new.ARW")
    editor.loadable.add(path)
    preset = tmp_path / "roll.arp"
    if text is not None:
        preset.write_text(text)
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": path, "profile": str(preset)})
        status = await client.call_tool("status", {})

    assert result.is_error and f"{code}:" in text_of(result), text_of(result)
    assert status.structured_content["images"][0]["path"] != path  # only a.ARW is open
    assert editor.applied == []


async def test_open_image_of_a_missing_file_is_not_found(art, editor, tmp_path):
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": str(tmp_path / "missing.ARW")})

    assert result.is_error and "not_found:" in text_of(result)


async def test_open_image_gives_up_after_its_timeout(art, editor, tmp_path):
    path = str(tmp_path / "slow.ARW")
    editor.loadable.add(path)
    editor.open_delay = 5
    async with Client(live(art, open_timeout=0.5)) as client:
        result = await client.call_tool("open_image", {"path": path})

    assert result.is_error and "timeout:" in text_of(result)


async def test_save_sidecar_is_the_editors_own_save(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("save_sidecar", {"path": image})

    assert not result.is_error, result.content
    assert result.structured_content == {"saved": True, "sidecar": image + ".arp"}
    assert editor.saved == [image]


async def test_save_sidecar_of_an_image_not_open_is_not_open(art, editor, tmp_path):
    async with Client(live(art)) as client:
        result = await client.call_tool("save_sidecar", {"path": str(tmp_path / "x.ARW")})

    assert result.is_error and "not_open:" in text_of(result)


async def test_tone_curve_edit_sends_the_curve_keys(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "path": image,
            "adjustments": {"tone_curve": {
                "curve1": {"type": "spline", "points": [[0, 0], [0.25, 0.2], [1, 1]]},
                "mode": "Standard",
            }},
        })  # fmt: skip

    assert not result.is_error, result.content
    sent = keyfile.loads(editor.applied[0]["profile"])
    assert sent == {
        "ToneCurve": {"Curve": "1;0;0;0.25;0.2;1;1;", "CurveMode": "Standard", "Enabled": "true"}
    }
    assert result.structured_content["implied"]["ToneCurve"] == {"Enabled": "true"}
    assert len(result.structured_content["drawn"]["curve1"]) == 9
    assert editor.applied[0]["label"] == "Agent: Tone Curve"


CC_PROFILE = PROFILE + "\n" + (
    __import__("pathlib").Path(__file__).parent / "data" / "art_default_colorcorrection.arp"
).read_text()


async def test_color_correction_regions_are_sent_whole_and_read_back_typed(art, tmp_path):
    editor = FakeEditor(art)
    path = str(tmp_path / "slide.ARW")
    editor.add(path, CC_PROFILE)
    request = {"color_correction": {"regions": [
        {"b": {"slope": 0.9239, "power": 0.6241}},
        {"b": {"slope": 0.85}, "mask": {"inverted": True, "shapes": [
            {"type": "rectangle", "width": 110, "height": 110, "roundness": 100, "feather": 60}]}},
    ]}}  # fmt: skip

    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {"path": path, "adjustments": request})
        profile = await client.call_tool("get_profile", {"path": path})

    assert not result.is_error, result.content
    assert result.structured_content["implied"] == {
        "ColorCorrection": {"Mode_1": "RGB", "Enabled": "true", "AreaMaskEnabled_2": "true"}
    }
    assert result.structured_content["created"] == {"ColorCorrection": [
        "region 2 (78 keys at their defaults)", "region 2 mask shape 0 (5 keys at their defaults)"]}  # fmt: skip
    assert "HSLGamma_2" not in result.structured_content["changed"]["ColorCorrection"]
    sent = keyfile.loads(editor.applied[0]["profile"])["ColorCorrection"]
    assert sent["Mode_2"] == "RGB" and sent["AreaMaskType_2"] == "rectangle"
    assert sent["HSLGamma_2"] == "2.3999999999999999" and sent["AreaMaskShapeBlur_2"] == "0"  # sent whole all the same
    assert sent["SlopeR_1"] == "1" and sent["HSLGamma_1"] == "2.3999999999999999"  # region 1 whole
    assert editor.applied[0]["label"] == "Agent: Color Correction"
    typed = json.loads(text_of(profile))["adjustments"]["color_correction"]
    assert typed["regions"][0]["b"]["slope"] == 0.9239
    assert typed["regions"][1]["mask"]["shapes"][0]["roundness"] == 100


async def test_the_result_of_one_image_has_no_profile_field_unless_full(art, editor, image):
    async with Client(live(art)) as client:
        plain = await client.call_tool("edit_profile", {
            "path": image, "adjustments": {"exposure": {"compensation": 1.0}},
        })  # fmt: skip
        full = await client.call_tool("edit_profile", {
            "path": image, "adjustments": {"exposure": {"compensation": 2.0}}, "full": True,
        })  # fmt: skip

    assert set(plain.structured_content) == {
        "changed", "implied", "created", "drawn", "warnings", "history_position",
    }
    assert '"profile"' not in text_of(plain)
    assert full.structured_content["profile"]["adjustments"]["exposure"]["compensation"] == 2.0


# -- edit_profile(paths): the same edit for several images ---------------------------


@pytest.fixture
def images(editor, tmp_path):
    """Three open images (the first is `image`), the last with a smaller frame."""
    paths = [str(tmp_path / "a.ARW"), str(tmp_path / "b.ARW"), str(tmp_path / "c.ARW")]
    editor.add(paths[1], PROFILE)
    editor.add(paths[2], PROFILE, width=3000, height=2000)
    return paths


async def test_one_edit_goes_to_every_path_each_as_its_own_labelled_history_entry(art, editor, images):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "paths": images, "adjustments": {"exposure": {"compensation": 1.0}},
        })  # fmt: skip

    assert not result.is_error, result.content
    assert set(result.structured_content) == {"items", "failed"}
    assert result.structured_content["failed"] == 0
    assert result.structured_content["items"] == [
        {"path": p, "changed": 1, "implied": {}, "warnings": [], "error": None, "history_position": 1} for p in images
    ]  # in request order
    assert len(editor.applied) == 3
    assert all(a["label"] == "Agent: Exposure" for a in editor.applied)
    for p in images:
        assert editor.labels(p) == ["Photo loaded", "Agent: Exposure"]
        assert editor.profile(p)["Exposure"]["Compensation"] == "1"


async def test_an_image_that_is_not_open_is_its_own_error_and_the_others_still_change(art, editor, images, tmp_path):
    gone = str(tmp_path / "gone.ARW")
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "paths": [images[0], gone, images[1]], "adjustments": {"exposure": {"compensation": 1.0}},
        })  # fmt: skip

    assert not result.is_error, result.content
    ok1, missing, ok2 = result.structured_content["items"]
    assert missing["path"] == gone and missing["error"].startswith("not_open:") and missing["changed"] is None
    assert (missing["implied"], missing["warnings"], missing["history_position"]) == ({}, [], None)
    assert (ok1["error"], ok2["error"], ok1["changed"], ok2["changed"]) == (None, None, 1, 1)
    assert result.structured_content["failed"] == 1
    assert [a["label"] for a in editor.applied] == ["Agent: Exposure", "Agent: Exposure"]


async def test_an_edit_one_image_refuses_is_its_own_error_and_sends_nothing_for_it(art, editor, images):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "paths": images, "adjustments": {"crop": {"x": 100, "y": 100, "w": 5900, "h": 3900}},
        })  # fmt: skip

    items = result.structured_content["items"]
    assert [i["error"] is None for i in items] == [True, True, False]  # the third image is 3000x2000
    assert items[2]["error"].startswith("out_of_range:") and "3000x2000" in items[2]["error"]
    assert result.structured_content["failed"] == 1
    assert len(editor.applied) == 2
    assert editor.labels(images[2]) == ["Photo loaded"]


async def test_an_image_that_has_the_values_already_gets_no_history_entry_and_counts_zero(art, editor, images):
    async with Client(live(art)) as client:
        await client.call_tool("edit_profile", {
            "path": images[1], "adjustments": {"exposure": {"compensation": 1.0}},
        })  # fmt: skip
        result = await client.call_tool("edit_profile", {
            "paths": images[:2], "adjustments": {"exposure": {"compensation": 1.0}},
        })  # fmt: skip

    first, second = result.structured_content["items"]
    assert (first["changed"], first["history_position"]) == (1, 1)
    assert (second["changed"], second["history_position"]) == (0, 1)  # the row it was on, no new entry
    assert editor.labels(images[1]) == ["Photo loaded", "Agent: Exposure"]


async def test_raw_edits_go_to_every_path_too(art, editor, images):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {
            "paths": images[:2], "raw_edits": [{"group": "Exposure", "key": "Black", "value": "5"}],
        })  # fmt: skip

    assert [i["changed"] for i in result.structured_content["items"]] == [1, 1]
    assert editor.applied[0]["label"] == "Agent: Exposure"
    assert editor.profile(images[1])["Exposure"]["Black"] == "5"


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
async def test_a_bad_choice_of_images_is_out_of_range_and_sends_nothing(art, editor, args, text):
    async with Client(live(art)) as client:
        result = await client.call_tool("edit_profile", {"adjustments": {"exposure": {"compensation": 1.0}}, **args})

    assert result.is_error and "out_of_range:" in text_of(result) and text in text_of(result)
    assert editor.applied == []


async def test_the_tool_describes_paths_and_its_two_result_shapes(art, editor):
    async with Client(live(art)) as client:
        tools = await client.list_tools()

    tool = next(t for t in tools.tools if t.name == "edit_profile")
    assert "path" not in tool.input_schema.get("required", [])
    assert {"type": "array", "items": {"type": "string"}} in tool.input_schema["properties"]["paths"]["anyOf"]
    assert "`paths`" in tool.description and "50" in tool.description and "History entry" in tool.description
    assert {"LiveEditResult", "LiveEditBatch", "LiveImageEdit"} <= tool.output_schema["$defs"].keys()
    assert tool.output_schema["type"] == "object"
