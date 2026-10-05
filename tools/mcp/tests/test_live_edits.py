"""The Live server's edits, undo/redo, open and save, against a fake ART
editor, through an in-process MCP client."""

import json

import pytest
from mcp.client.client import Client

from art_mcp import keyfile
from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server
from fake_live_art import FakeArt, FakeEditor

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
    assert result.structured_content["changed"] == [
        {"group": "Exposure", "key": "Compensation", "value": "1"}
    ]
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
    implied = result.structured_content["implied"]
    assert {"group": "White Balance", "key": "Setting", "value": "CustomTemp"} in implied
    assert {"group": "Local Contrast", "key": "Enabled", "value": "true"} in implied
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
    assert result.structured_content["changed"] == []
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
    assert result.structured_content == {"path": path, "already_open": False}


async def test_open_image_of_an_open_image_says_so(art, editor, image):
    async with Client(live(art)) as client:
        result = await client.call_tool("open_image", {"path": image})

    assert result.structured_content == {"path": image, "already_open": True}


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
    assert {"group": "ToneCurve", "key": "Enabled", "value": "true"} in result.structured_content["implied"]
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
    implied = {(c["key"], c["value"]) for c in result.structured_content["implied"]}
    assert implied == {("Mode_1", "RGB"), ("Enabled", "true"), ("AreaMaskEnabled_2", "true")}
    sent = keyfile.loads(editor.applied[0]["profile"])["ColorCorrection"]
    assert sent["Mode_2"] == "RGB" and sent["AreaMaskType_2"] == "rectangle"
    assert sent["SlopeR_1"] == "1" and sent["HSLGamma_1"] == "2.3999999999999999"  # region 1 whole
    assert editor.applied[0]["label"] == "Agent: Color Correction"
    typed = json.loads(text_of(profile))["adjustments"]["color_correction"]
    assert typed["regions"][0]["b"]["slope"] == 0.9239
    assert typed["regions"][1]["mask"]["shapes"][0]["roundness"] == 100
