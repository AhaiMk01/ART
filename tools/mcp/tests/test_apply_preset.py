"""apply_preset: an `.arp` (partial or full) laid over the working profiles of
images that are already open, keeping what the frame has set that the file
doesn't."""

import json
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp import keyfile
from art_mcp.preview import PreviewFolder
from art_mcp.profile import RawEdit, WorkingChanges
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

PRESET = "[Exposure]\nCompensation=1.5\n\n[Film Negative]\nEnabled=true\nRedRatio=1.3\n"
FULL = """[Version]
AppVersion=1.0.0
Version=1040

[Exposure]
Enabled=false
Compensation=-2
Black=0

[White Balance]
Enabled=true
Setting=Auto

[Crop]
Enabled=false
X=-1
Y=-1
W=-1
H=-1

[LensProfile]
LcMode=none
UseDistortion=true
UseVignette=true
UseCA=false
"""
SIDECAR = "[Exposure]\nEnabled=true\nCompensation=7\nBlack=0\n"
CROP = [
    {"group": "Crop", "key": "Enabled", "value": "true"},
    {"group": "Crop", "key": "X", "value": "100"},
    {"group": "Crop", "key": "Y", "value": "200"},
    {"group": "Crop", "key": "W", "value": "3000"},
    {"group": "Crop", "key": "H", "value": "2000"},
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    paths = []
    for name in ("FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"):
        (folder / name).write_bytes(b"raw")
        paths.append(folder / name)
    return paths


@pytest.fixture
def preset(tmp_path):
    path = tmp_path / "group.arp"
    path.write_text(PRESET)
    return path


@pytest.fixture
def args_log(tmp_path, monkeypatch):
    log = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
    return log


@pytest.fixture
def server(tmp_path):
    cli = ArtCli((sys.executable, str(FAKE)))
    config = tmp_path / "config"
    config.mkdir()
    return build_server(cli, config, PreviewFolder(tmp_path / "previews"))


def text_of(result):
    return result.content[0].text


def sidecar_of(image):
    return image.with_name(image.name + ".arp")


async def open_all(client, images):
    for image in images:
        opened = await client.call_tool("open_image", {"path": str(image)})
        assert not opened.is_error, opened.content


async def edit(client, image, raw_edits):
    result = await client.call_tool("edit_profile", {"path": str(image), "raw_edits": raw_edits})
    assert not result.is_error, result.content


async def apply(client, paths, preset, **args):
    return await client.call_tool(
        "apply_preset", {"paths": [str(p) for p in paths], "profile": str(preset), **args}
    )


async def adjustments_of(client, image):
    result = await client.call_tool("get_profile", {"path": str(image)})
    assert not result.is_error, result.content
    return result.structured_content["adjustments"]


async def test_the_presets_keys_land_and_the_frames_own_crop_stays(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await edit(client, images[0], CROP)
        result = await apply(client, images[:1], preset)
        profile = await adjustments_of(client, images[0])

    assert not result.is_error, result.content
    assert profile["exposure"]["compensation"] == 1.5  # the preset's
    assert profile["film_negative"]["enabled"] is True  # a group the frame did not have
    assert profile["white_balance"]["setting"] == "Camera"  # not in the preset: untouched
    crop = profile["crop"]
    assert (crop["enabled"], crop["x"], crop["y"], crop["w"], crop["h"]) == (True, 100, 200, 3000, 2000)  # its own
    item = result.structured_content["items"][0]
    assert item["path"] == str(images[0]) and item["error"] is None
    assert item["keys_changed"] == 3  # Compensation, Enabled, RedRatio
    assert item["groups"] == ["Exposure", "Film Negative"]


async def test_a_complete_profile_works_too_and_sets_every_key_it_has(server, images, tmp_path):
    full = tmp_path / "full.arp"
    full.write_text(FULL)
    async with Client(server) as client:
        await open_all(client, images[:1])
        await edit(client, images[0], CROP)
        result = await apply(client, images[:1], full)
        profile = await adjustments_of(client, images[0])

    assert not result.is_error, result.content
    assert (profile["exposure"]["enabled"], profile["exposure"]["compensation"]) == (False, -2.0)  # the file's
    assert profile["white_balance"]["setting"] == "Auto"
    assert profile["crop"]["enabled"] is False  # the file has a [Crop] too, so its keys win there as well
    assert result.structured_content["items"][0]["groups"] == ["Exposure", "White Balance", "Crop"]


async def test_the_preset_wins_over_what_the_frame_set_and_the_rest_stays(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await edit(client, images[0], [
            {"group": "Exposure", "key": "Compensation", "value": "3"},
            {"group": "Exposure", "key": "Black", "value": "0.5"},
        ])  # fmt: skip
        await apply(client, images[:1], preset)
        exposure = (await adjustments_of(client, images[0]))["exposure"]

    assert exposure["compensation"] == 1.5  # the preset's, not the frame's 3
    assert exposure["black"] == 0.5  # not in the preset


async def test_the_working_profile_is_the_first_layer_and_no_default_profile_goes_under(
    server, images, preset, args_log
):
    async with Client(server) as client:
        await open_all(client, images[:1])
        args_log.write_text("")  # only the layering run
        await apply(client, images[:1], preset)

    (args,) = (json.loads(line) for line in args_log.read_text().splitlines())
    assert "-d" not in args
    layers = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
    assert len(layers) == 2 and layers[1] == str(preset.resolve())  # the preset last, over the working profile
    assert args[-2] == "-c" and Path(args[-1]).resolve() == images[0].resolve()  # -c comes last: files only after


async def test_several_frames_in_one_call_each_keep_their_own_state(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images)
        for i, image in enumerate(images):
            await edit(client, image, [{"group": "Crop", "key": "X", "value": str(10 * (i + 1))}])
        result = await apply(client, images, preset)
        profiles = [await adjustments_of(client, p) for p in images]

    assert not result.is_error, result.content
    data = result.structured_content
    assert [i["path"] for i in data["items"]] == [str(p) for p in images]
    assert [i["keys_changed"] for i in data["items"]] == [3, 3, 3]
    assert (data["applied"], data["failed"]) == (3, 0)
    assert [p["crop"]["x"] for p in profiles] == [10, 20, 30]
    assert [p["exposure"]["compensation"] for p in profiles] == [1.5] * 3


async def test_a_frame_that_is_not_open_is_its_own_error_and_the_others_still_apply(server, images, preset):
    async with Client(server) as client:
        await open_all(client, [images[0], images[2]])
        result = await apply(client, images, preset)  # images[1] was never opened
        first = (await adjustments_of(client, images[0]))["exposure"]["compensation"]
        last = (await adjustments_of(client, images[2]))["exposure"]["compensation"]

    assert not result.is_error, result.content
    ok1, missing, ok2 = result.structured_content["items"]
    assert missing["error"].startswith("not_open") and missing["keys_changed"] is None and missing["groups"] == []
    assert ok1["error"] is None and ok2["error"] is None
    assert (result.structured_content["applied"], result.structured_content["failed"]) == (2, 1)
    assert (first, last) == (1.5, 1.5)


async def test_a_failing_render_leaves_that_frames_profile_alone_and_the_others_apply(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images[:2])
        images[0].unlink()  # art-cli can't find the input any more
        result = await apply(client, images[:2], preset)
        broken = (await adjustments_of(client, images[0]))["exposure"]["compensation"]
        fine = (await adjustments_of(client, images[1]))["exposure"]["compensation"]

    first, second = result.structured_content["items"]
    assert first["error"].startswith("render_failed") and first["keys_changed"] is None
    assert second["error"] is None
    assert (broken, fine) == (0.0, 1.5)


async def test_a_missing_preset_fails_the_whole_call_and_changes_nothing(server, images, tmp_path):
    async with Client(server) as client:
        await open_all(client, images[:1])
        result = await apply(client, images[:1], tmp_path / "nope.arp")
        exposure = (await adjustments_of(client, images[0]))["exposure"]["compensation"]

    assert result.is_error and "not_found: " in text_of(result)
    assert exposure == 0.0


async def test_a_preset_that_is_a_folder_is_not_found_too(server, images, tmp_path):
    async with Client(server) as client:
        await open_all(client, images[:1])
        result = await apply(client, images[:1], tmp_path)

    assert result.is_error and "not_found: " in text_of(result)


async def test_no_paths_is_out_of_range(server, preset):
    async with Client(server) as client:
        result = await apply(client, [], preset)

    assert result.is_error and "out_of_range: " in text_of(result)


async def test_a_preset_the_frame_already_has_changes_nothing(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await apply(client, images[:1], preset)
        again = await apply(client, images[:1], preset)

    item = again.structured_content["items"][0]
    assert (item["keys_changed"], item["groups"], item["error"]) == (0, [], None)


async def test_the_result_counts_the_changed_values_and_does_not_list_them(server, images, tmp_path):
    big = tmp_path / "big.arp"
    big.write_text("[Exposure]\n" + "".join(f"Extra{i}={i}\n" for i in range(100)))
    async with Client(server) as client:
        await open_all(client, images[:1])
        result = await apply(client, images[:1], big)

    assert result.structured_content["items"][0]["keys_changed"] == 100
    assert "Extra50" not in text_of(result)


async def test_saving_afterwards_writes_over_the_unchanged_sidecar_without_a_conflict(server, images, preset):
    sidecar_of(images[0]).write_text(SIDECAR)
    async with Client(server) as client:
        await open_all(client, images[:1])
        await apply(client, images[:1], preset)
        saved = await client.call_tool("save_sidecar", {"path": str(images[0])})

    assert not saved.is_error, saved.content
    assert saved.structured_content["how"] == "written"  # the baseline is still the sidecar that was loaded
    written = keyfile.loads(sidecar_of(images[0]).read_text())
    assert written["Exposure"]["Compensation"] == "1.5"
    assert written["Film Negative"]["RedRatio"] == "1.3"


async def test_a_sidecar_that_changed_meanwhile_conflicts_and_merges_only_the_presets_changes(server, images, preset):
    sidecar = sidecar_of(images[0])
    sidecar.write_text(SIDECAR)
    async with Client(server) as client:
        await open_all(client, images[:1])
        await apply(client, images[:1], preset)
        sidecar.write_text("[Exposure]\nEnabled=true\nCompensation=7\nBlack=2\n")  # someone else's edit
        conflict = await client.call_tool("save_sidecar", {"path": str(images[0])})
        merged = await client.call_tool("save_sidecar", {"path": str(images[0]), "on_conflict": "merge"})

    assert conflict.is_error and "conflict: " in text_of(conflict)
    assert "[Exposure] Compensation, [Film Negative] Enabled, [Film Negative] RedRatio" in text_of(conflict)
    assert not merged.is_error, merged.content
    written = keyfile.loads(sidecar.read_text())
    assert written["Exposure"] == {"Enabled": "true", "Compensation": "1.5", "Black": "2"}  # theirs + the preset's
    assert written["Film Negative"]["RedRatio"] == "1.3"


async def test_the_partial_profile_of_a_frame_includes_what_the_preset_changed(server, images, preset, tmp_path):
    frame = tmp_path / "frame.arp"
    async with Client(server) as client:
        await open_all(client, images[:1])
        await apply(client, images[:1], preset)
        await edit(client, images[0], CROP)
        saved = await client.call_tool("save_partial_profile", {"path": str(images[0]), "dest": str(frame)})

    assert not saved.is_error, saved.content
    partial = keyfile.loads(frame.read_text())
    assert partial["Exposure"] == {"Compensation": "1.5"}
    assert partial["Film Negative"] == {"Enabled": "true", "RedRatio": "1.3"}
    assert partial["Crop"]["X"] == "100"


async def test_a_reset_forgets_the_preset(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await apply(client, images[:1], preset)
        await client.call_tool("reset_profile", {"path": str(images[0]), "to": "default"})
        exposure = (await adjustments_of(client, images[0]))["exposure"]["compensation"]

    assert exposure == 0.0


# -- exclude: what of the preset is left out before it is laid over the frames ---------

TWO_EXPOSURE_KEYS = "[Exposure]\nCompensation=1.5\nBlack=0.5\n\n[Film Negative]\nEnabled=true\nRedRatio=1.3\n"


async def set_compensation(client, image, value):
    await edit(client, image, [{"group": "Exposure", "key": "Compensation", "value": value}])


async def test_excluding_a_group_leaves_the_frames_own_values_of_it(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images[:1])
        await set_compensation(client, images[0], "3")
        result = await apply(client, images[:1], preset, exclude=["Exposure"])
        profile = await adjustments_of(client, images[0])

    assert not result.is_error, result.content
    assert profile["exposure"]["compensation"] == 3  # the frame's own, not the preset's 1.5
    assert profile["film_negative"]["red_ratio"] == 1.3  # the rest of the preset landed
    item = result.structured_content["items"][0]
    assert (item["keys_changed"], item["groups"], item["error"]) == (2, ["Film Negative"], None)
    assert result.structured_content["excluded"] == {"Exposure": 1}  # what each entry took out of the preset


async def test_excluding_one_key_leaves_the_frames_own_value_of_that_key_only(server, images, tmp_path):
    two = tmp_path / "two.arp"
    two.write_text(TWO_EXPOSURE_KEYS)
    async with Client(server) as client:
        await open_all(client, images[:1])
        await set_compensation(client, images[0], "3")
        result = await apply(client, images[:1], two, exclude=["Exposure/Compensation"])
        exposure = (await adjustments_of(client, images[0]))["exposure"]

    assert not result.is_error, result.content
    assert (exposure["compensation"], exposure["black"]) == (3, 0.5)  # Black came from the preset
    assert result.structured_content["excluded"] == {"Exposure/Compensation": 1}


async def test_the_same_exclusions_apply_to_every_frame_and_each_keeps_its_own_values(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images)
        for i, image in enumerate(images):
            await set_compensation(client, image, str(i + 1))
        result = await apply(client, images, preset, exclude=["Exposure"])
        profiles = [await adjustments_of(client, p) for p in images]

    assert [p["exposure"]["compensation"] for p in profiles] == [1, 2, 3]
    assert [p["film_negative"]["red_ratio"] for p in profiles] == [1.3] * 3
    assert [i["keys_changed"] for i in result.structured_content["items"]] == [2, 2, 2]


async def test_art_cli_layers_a_filtered_copy_and_the_preset_file_is_left_alone(
    server, images, preset, args_log
):
    async with Client(server) as client:
        await open_all(client, images[:1])
        args_log.write_text("")
        await apply(client, images[:1], preset, exclude=["Exposure"])

    (args,) = (json.loads(line) for line in args_log.read_text().splitlines())
    layers = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
    assert len(layers) == 2 and layers[1] != str(preset.resolve())
    assert not Path(layers[1]).exists()  # the copy is gone once the call is over
    assert preset.read_text() == PRESET


async def test_without_exclude_the_preset_itself_is_layered_and_nothing_is_reported_excluded(
    server, images, preset, args_log
):
    async with Client(server) as client:
        await open_all(client, images[:1])
        args_log.write_text("")
        result = await apply(client, images[:1], preset)

    (args,) = (json.loads(line) for line in args_log.read_text().splitlines())
    assert [args[i + 1] for i, a in enumerate(args) if a == "-p"][1] == str(preset.resolve())
    assert result.structured_content["excluded"] == {}


async def test_an_entry_the_preset_does_not_have_is_a_no_op_reported_with_zero(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images[:1])
        result = await apply(client, images[:1], preset, exclude=["Crop", "Exposure/Black"])  # both in the profile

    assert not result.is_error, result.content
    assert result.structured_content["excluded"] == {"Crop": 0, "Exposure/Black": 0}
    assert result.structured_content["items"][0]["keys_changed"] == 3  # the whole preset


async def test_an_entry_that_is_nowhere_is_unknown_key_for_every_frame_and_nothing_applies(server, images, preset):
    async with Client(server) as client:
        await open_all(client, images[:2])
        result = await apply(client, images[:2], preset, exclude=["Exposure/Compensaton"])  # a typo
        values = [(await adjustments_of(client, p))["exposure"]["compensation"] for p in images[:2]]

    assert not result.is_error, result.content
    items = result.structured_content["items"]
    assert all(i["error"].startswith("unknown_key") and "Exposure/Compensaton" in i["error"] for i in items)
    assert (result.structured_content["applied"], result.structured_content["failed"]) == (0, 2)
    assert values == [0.0, 0.0]


async def test_excluding_the_whole_preset_changes_nothing(server, images, tmp_path):
    only = tmp_path / "only.arp"
    only.write_text("[Exposure]\nCompensation=1.5\n")
    async with Client(server) as client:
        await open_all(client, images[:1])
        result = await apply(client, images[:1], only, exclude=["Exposure"])
        exposure = (await adjustments_of(client, images[0]))["exposure"]["compensation"]

    assert not result.is_error, result.content
    item = result.structured_content["items"][0]
    assert (item["keys_changed"], item["groups"], item["error"]) == (0, [], None)
    assert exposure == 0.0


async def test_a_complete_profile_without_the_per_frame_groups_is_a_group_preset(server, images, tmp_path):
    full = tmp_path / "full.arp"
    full.write_text(FULL)
    async with Client(server) as client:
        await open_all(client, images[:1])
        await edit(client, images[0], CROP)
        result = await apply(client, images[:1], full, exclude=["Crop", "Version"])
        profile = await adjustments_of(client, images[0])

    assert not result.is_error, result.content
    assert profile["exposure"]["compensation"] == -2.0  # the file's
    crop = profile["crop"]
    assert (crop["enabled"], crop["x"], crop["w"]) == (True, 100, 3000)  # the frame's own


async def test_a_preset_that_is_not_a_profile_cannot_be_filtered(server, images, tmp_path):
    junk = tmp_path / "junk.arp"
    junk.write_text("this is not a key file\n")
    async with Client(server) as client:
        await open_all(client, images[:1])
        result = await apply(client, images[:1], junk, exclude=["Exposure"])

    assert result.is_error and "out_of_range: " in text_of(result) and "junk.arp" in text_of(result)


async def test_the_tool_describes_exclude(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    tool = next(t for t in tools.tools if t.name == "apply_preset")
    assert "exclude" in tool.input_schema["properties"]
    assert "`exclude`" in tool.description and "save_partial_profile" in tool.description


def test_layering_a_resolved_profile_drops_what_it_lacks_and_a_partial_profile_still_works():
    before = {"Version": {"Version": "1045"}, "ColorCorrection": {"A_1": "a", "A_2": "b"}, "Exposure": {"Black": "0"}}
    after = {"Version": {"Version": "1046"}, "ColorCorrection": {"A_1": "a"}, "Exposure": {"Black": "4"}}
    changes = WorkingChanges(before)
    changes.apply([RawEdit(group="Exposure", key="Black", value="4")])

    changed = changes.layer(after)

    assert changed == [("ColorCorrection", "A_2")]  # Version is nobody's edit; Black already had that value
    assert changes.profile == after
    assert changes.partial_profile() == {"Exposure": {"Black": "4"}, "ColorCorrection": {"A_1": "a"}}
