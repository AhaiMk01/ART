"""open_image's `profile`: the working profile starts from a given .arp (full or
partial, layered over ART's default profile) instead of the sidecar."""

import sys
from pathlib import Path

import pytest
from mcp.client.client import Client
from test_artcli_run import peak_overlap

from art_mcp import keyfile
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
CTL = Path(__file__).with_name("fake_artcli_ctl.py")
pytestmark = pytest.mark.anyio

SIDECAR = "[Exposure]\nEnabled=true\nCompensation=7\nBlack=0\n"
PRESET = "[Exposure]\nCompensation=1.5\n"  # partial: nothing but one value
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


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def sidecar(image):
    path = image.with_name(image.name + ".arp")
    path.write_text(SIDECAR)
    return path


@pytest.fixture
def preset(tmp_path):
    path = tmp_path / "roll.arp"
    path.write_text(PRESET)
    return path


@pytest.fixture
def server(tmp_path):
    cli = ArtCli((sys.executable, str(FAKE)))
    config = tmp_path / "config"
    config.mkdir()
    return build_server(cli, config, PreviewFolder(tmp_path / "previews"))


def text_of(result):
    return result.content[0].text


async def open_with(client, image, profile):
    result = await client.call_tool("open_image", {"path": str(image), "profile": str(profile)})
    assert not result.is_error, result.content
    return result


async def adjustments(client, image):
    return (await client.call_tool("get_profile", {"path": str(image)})).structured_content


async def test_a_partial_profile_layers_over_arts_default_profile(server, image, preset):
    async with Client(server) as client:
        opened = await open_with(client, image, preset)
        profile = await adjustments(client, image)

    assert opened.structured_content["profile_from"] == "profile"
    assert profile["adjustments"]["exposure"]["compensation"] == 1.5  # the preset's
    assert profile["adjustments"]["white_balance"]["setting"] == "Camera"  # the default's
    assert profile["ppversion"] == 1045


async def test_a_full_profile_replaces_arts_default_profile(server, image, tmp_path):
    full = tmp_path / "full.arp"
    full.write_text(FULL)
    async with Client(server) as client:
        await open_with(client, image, full)
        profile = await adjustments(client, image)

    exposure = profile["adjustments"]["exposure"]
    assert (exposure["enabled"], exposure["compensation"]) == (False, -2.0)
    assert profile["adjustments"]["white_balance"]["setting"] == "Auto"
    assert profile["ppversion"] == 1040


async def test_the_images_own_sidecar_is_neither_used_nor_touched(server, image, sidecar, preset):
    before = (sidecar.read_bytes(), sidecar.stat().st_mtime_ns)
    async with Client(server) as client:
        opened = await open_with(client, image, preset)
        profile = await adjustments(client, image)
        await client.call_tool("edit_profile", {
            "path": str(image),
            "raw_edits": [{"group": "Exposure", "key": "Black", "value": "3"}],
        })  # fmt: skip
        await client.call_tool("render_preview", {"path": str(image)})

    assert opened.structured_content["profile_from"] == "profile"
    assert profile["adjustments"]["exposure"]["compensation"] == 1.5  # not the sidecar's 7
    assert (sidecar.read_bytes(), sidecar.stat().st_mtime_ns) == before
    assert not sidecar.with_name(sidecar.name + ".bak").exists()


async def test_saving_does_not_replace_a_sidecar_that_was_never_loaded_unasked(server, image, sidecar, preset):
    async with Client(server) as client:
        await open_with(client, image, preset)
        saved = await client.call_tool("save_sidecar", {"path": str(image)})

    assert saved.is_error and "conflict" in text_of(saved)
    assert sidecar.read_text() == SIDECAR


async def test_saving_writes_the_sidecar_when_the_image_has_none(server, image, preset):
    async with Client(server) as client:
        await open_with(client, image, preset)
        saved = await client.call_tool("save_sidecar", {"path": str(image)})

    assert not saved.is_error, saved.content
    written = keyfile.loads(image.with_name(image.name + ".arp").read_text())
    assert written["Exposure"]["Compensation"] == "1.5"
    assert written["White Balance"]["Setting"] == "Camera"  # the whole profile, not only the preset


async def test_the_partial_profile_of_a_frame_holds_what_was_changed_after_opening(server, image, preset, tmp_path):
    frame = tmp_path / "frame.arp"
    async with Client(server) as client:
        await open_with(client, image, preset)
        await client.call_tool("edit_profile", {
            "path": str(image),
            "raw_edits": [{"group": "Crop", "key": "Enabled", "value": "true"}],
        })  # fmt: skip
        saved = await client.call_tool("save_partial_profile", {"path": str(image), "dest": str(frame)})

    assert not saved.is_error, saved.content
    assert keyfile.loads(frame.read_text()) == {"Crop": {"Enabled": "true"}}  # not the preset's values


async def test_a_profile_that_does_not_exist_is_not_found(server, image, tmp_path):
    async with Client(server) as client:
        result = await client.call_tool("open_image", {"path": str(image), "profile": str(tmp_path / "nope.arp")})
        reopened = await client.call_tool("get_profile", {"path": str(image)})

    assert result.is_error and "not_found" in text_of(result)
    assert reopened.is_error and "not_open" in text_of(reopened)  # nothing was opened


async def test_opening_again_without_a_profile_goes_back_to_the_sidecar(server, image, sidecar, preset):
    async with Client(server) as client:
        await open_with(client, image, preset)
        again = await client.call_tool("open_image", {"path": str(image)})
        profile = await adjustments(client, image)

    assert again.structured_content["profile_from"] == "sidecar"
    assert profile["adjustments"]["exposure"]["compensation"] == 7.0


# -- open_image(paths): several images at once ---------------------------------------


@pytest.fixture
def roll(tmp_path):
    """Three raws in one folder; the middle one has a sidecar."""
    folder = tmp_path / "roll"
    folder.mkdir()
    frames = []
    for n in range(3):
        frame = folder / f"FILM_{n}.ARW"
        frame.write_bytes(b"raw")
        frames.append(frame)
    frames[1].with_name(frames[1].name + ".arp").write_text(SIDECAR)
    return frames


async def open_roll(client, frames, **args):
    return await client.call_tool("open_image", {"paths": [str(f) for f in frames], **args})


async def test_several_images_open_with_the_same_profile_and_the_result_is_one_compact_entry_each(server, roll, preset):
    async with Client(server) as client:
        result = await open_roll(client, roll, profile=str(preset))
        values = [(await adjustments(client, f))["adjustments"]["exposure"]["compensation"] for f in roll]

    assert not result.is_error, result.content
    assert set(result.structured_content) == {"items", "failed"} and result.structured_content["failed"] == 0
    assert result.structured_content["items"] == [{"path": str(f), "profile_from": "profile"} for f in roll]
    assert values == [1.5, 1.5, 1.5]  # the preset's value, though the middle image has a sidecar of its own


async def test_several_images_without_a_profile_each_start_from_their_sidecar_else_the_default(server, roll):
    async with Client(server) as client:
        result = await open_roll(client, roll)
        values = [(await adjustments(client, f))["adjustments"]["exposure"]["compensation"] for f in roll]

    assert [i["profile_from"] for i in result.structured_content["items"]] == ["default", "sidecar", "default"]
    assert values == [0, 7.0, 0]


async def test_an_entry_has_the_path_as_requested(server, roll):
    spelled = str(roll[0].parent / ".." / roll[0].parent.name / roll[0].name)
    async with Client(server) as client:
        result = await client.call_tool("open_image", {"paths": [spelled]})
        shown = await client.call_tool("render_preview", {"path": str(roll[0])})

    assert result.structured_content["items"] == [{"path": spelled, "profile_from": "default"}]
    assert not shown.is_error, shown.content  # opened as the image it names


async def test_an_image_that_does_not_exist_is_its_own_error_and_the_others_still_open(server, roll, tmp_path):
    gone = tmp_path / "roll" / "GONE.ARW"
    async with Client(server) as client:
        result = await open_roll(client, [roll[0], gone, roll[2]])
        opened = [await client.call_tool("get_profile", {"path": str(f)}) for f in (roll[0], roll[2])]

    ok1, missing, ok2 = result.structured_content["items"]
    assert not result.is_error, result.content
    assert set(missing) == {"path", "error"} and missing["path"] == str(gone)
    assert missing["error"].startswith("not_found") and "GONE.ARW" in missing["error"]
    assert (ok1["profile_from"], ok2["profile_from"]) == ("default", "default")
    assert result.structured_content["failed"] == 1
    assert not any(o.is_error for o in opened)


async def test_a_profile_that_does_not_exist_fails_the_call_before_any_image_opens(server, roll, tmp_path):
    async with Client(server) as client:
        result = await open_roll(client, roll, profile=str(tmp_path / "nope.arp"))
        reopened = await client.call_tool("get_profile", {"path": str(roll[0])})

    assert result.is_error and "not_found" in text_of(result) and "nope.arp" in text_of(result)
    assert reopened.is_error and "not_open" in text_of(reopened)  # one profile for all: not one image's problem


async def test_the_same_image_twice_opens_twice(server, roll):
    async with Client(server) as client:
        result = await open_roll(client, [roll[0], roll[0]])

    assert [i["profile_from"] for i in result.structured_content["items"]] == ["default", "default"]


async def test_opening_several_images_again_replaces_their_working_profiles(server, roll, preset):
    async with Client(server) as client:
        await open_roll(client, roll, profile=str(preset))
        await client.call_tool("edit_profile", {
            "paths": [str(f) for f in roll], "raw_edits": [{"group": "Exposure", "key": "Black", "value": "3"}],
        })  # fmt: skip
        await open_roll(client, roll)
        blacks = [(await adjustments(client, f))["adjustments"]["exposure"]["black"] for f in roll]

    assert blacks == [0, 0, 0]


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"path": "a.ARW", "paths": ["a.ARW"]}, "not both"),
        ({}, "path or paths"),
        ({"paths": []}, "paths is empty"),
        ({"paths": [f"{i}.ARW" for i in range(51)]}, "51 entries; the most one call takes is 50"),
    ],
)
async def test_a_bad_choice_of_images_to_open_is_out_of_range(server, image, args, text):
    async with Client(server) as client:
        result = await client.call_tool("open_image", args)
        reopened = await client.call_tool("get_profile", {"path": str(image)})

    assert result.is_error and "out_of_range" in text_of(result) and text in text_of(result)
    assert reopened.is_error and "not_open" in text_of(reopened)


async def test_opening_several_images_reports_progress_per_image(server, roll):
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total))

    async with Client(server) as client:
        await client.call_tool("open_image", {"paths": [str(f) for f in roll]}, progress_callback=on_progress)

    assert sorted(seen) == [(1, 3), (2, 3), (3, 3)]


async def test_opening_several_images_runs_through_the_bounded_pool(tmp_path, roll, monkeypatch):
    log = tmp_path / "runs"
    log.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    pooled = build_server(
        ArtCli((sys.executable, str(CTL)), max_processes=2), config, PreviewFolder(tmp_path / "previews")
    )
    monkeypatch.setenv("FAKE_ARTCLI_LOG", str(log))
    monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0.3")
    async with Client(pooled) as client:
        result = await open_roll(client, roll * 2)

    assert not result.is_error, result.content
    assert result.structured_content["failed"] == 0
    assert peak_overlap(log) == (6, 2)  # six loads, two at a time: the cap, and in parallel


async def test_the_tool_describes_paths_and_its_two_result_shapes(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    tool = next(t for t in tools.tools if t.name == "open_image")
    assert not tool.input_schema.get("required")  # one of path, paths: checked by the tool
    assert {"type": "array", "items": {"type": "string"}} in tool.input_schema["properties"]["paths"]["anyOf"]
    assert "`paths`" in tool.description and "50" in tool.description
    assert {"OpenedImage", "OpenBatch", "OpenItem"} <= tool.output_schema["$defs"].keys()
    assert tool.output_schema["type"] == "object"
