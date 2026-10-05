"""inspect_images on both servers: many images in one call, exiftool run once."""

import json
import sys
from pathlib import Path

import pytest
from fake_live_art import FakeArt, answer, fail
from mcp.client.client import Client

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live_server
from art_mcp.metadata import Exiftool
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server as build_render_server

pytestmark = pytest.mark.anyio

FAKE_ARTCLI = Path(__file__).with_name("fake_artcli.py")
FAKE_ARTCLI_CTL = Path(__file__).with_name("fake_artcli_ctl.py")
FAKE_EXIFTOOL = Path(__file__).with_name("fake_exiftool.py")
EXIFTOOL = Exiftool((sys.executable, str(FAKE_EXIFTOOL)))

# A negative photographed on a light table: the Sony records no aperture for a manual lens.
SCAN = {"Make": "SONY", "Model": "ILCE-7M3", "ISO": 100, "FNumber": 0, "ExposureTime": 0.625,
        "ImageWidth": 6048, "ImageHeight": 4024, "Software": "v1"}  # fmt: skip
SHUTTERS = (0.625, 0.5, 0.8)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def roll(tmp_path):
    """Three frames, each with its own scan shutter."""
    folder = tmp_path / "roll"
    folder.mkdir()
    frames = []
    for i, shutter in enumerate(SHUTTERS, start=1):
        frame = folder / f"FILM_{i}.ARW"
        frame.write_bytes(b"raw")
        frame.with_name(frame.name + ".exif.json").write_text(json.dumps({**SCAN, "ExposureTime": shutter}))
        frames.append(frame)
    return frames


@pytest.fixture
def exiftool_runs(tmp_path, monkeypatch):
    """A function giving the files each exiftool run was asked for."""
    log = tmp_path / "exiftool-runs.log"
    monkeypatch.setenv("FAKE_EXIFTOOL_LOG", str(log))
    return lambda: [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def paths(frames):
    return [str(f) for f in frames]


# -- Render ------------------------------------------------------------------


def render_server(tmp_path, *, exiftool=EXIFTOOL, art_cli=FAKE_ARTCLI):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    return build_render_server(
        ArtCli((sys.executable, str(art_cli))), config, PreviewFolder(tmp_path / "previews"), exiftool=exiftool
    )


async def open_all(client, frames):
    for frame in frames:
        opened = await client.call_tool("open_image", {"path": str(frame)})
        assert not opened.is_error, opened.content


async def test_render_reads_every_open_frame_with_one_exiftool_run(tmp_path, roll, exiftool_runs):
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)  # each open_image reads its own summary
        before = len(exiftool_runs())
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    assert not result.is_error, result.content
    data = result.structured_content
    assert [i["path"] for i in data["items"]] == paths(roll)
    assert [i["metadata"]["shutter_seconds"] for i in data["items"]] == list(SHUTTERS)
    assert all(i["error"] is None for i in data["items"]) and data["failed"] == 0
    assert (data["items"][0]["metadata"]["iso"], data["items"][0]["metadata"]["aperture"]) == (100, None)
    runs = exiftool_runs()[before:]
    assert [[Path(p).name for p in run] for run in runs] == [[f.name for f in roll]]  # one run for all three


async def test_render_returns_the_requested_tags_per_frame(tmp_path, roll):
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        result = await client.call_tool("inspect_images", {"paths": paths(roll), "tags": ["Software"]})

    assert [i["metadata"]["tags"] for i in result.structured_content["items"]] == [{"Software": "v1"}] * 3


async def test_render_a_frame_that_is_not_open_is_its_own_error(tmp_path, roll, exiftool_runs):
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll[:1] + roll[2:])
        before = len(exiftool_runs())
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data["failed"] == 1
    assert data["items"][1]["metadata"] is None and data["items"][1]["error"].startswith("not_open:")
    assert [i["metadata"]["shutter_seconds"] for i in (data["items"][0], data["items"][2])] == [0.625, 0.8]
    assert [Path(p).name for p in exiftool_runs()[before]] == ["FILM_1.ARW", "FILM_3.ARW"]  # the open ones only


async def test_render_a_frame_exiftool_cannot_read_is_its_own_error(tmp_path, roll):
    roll[1].with_name(roll[1].name + ".exif.json").unlink()  # the fake can't read it
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    assert not result.is_error, result.content
    items = result.structured_content["items"]
    assert items[1]["metadata"] is None and items[1]["error"].startswith("metadata_failed:")
    assert items[0]["metadata"]["shutter_seconds"] == 0.625 and items[2]["metadata"]["shutter_seconds"] == 0.8
    assert result.structured_content["failed"] == 1


async def test_render_a_path_given_twice_is_answered_twice(tmp_path, roll, exiftool_runs):
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll[:1])
        before = len(exiftool_runs())
        result = await client.call_tool("inspect_images", {"paths": paths(roll[:1] * 2)})

    items = result.structured_content["items"]
    assert [i["metadata"]["shutter_seconds"] for i in items] == [0.625, 0.625]
    assert len(exiftool_runs()[before]) == 1


async def test_render_frame_size_is_null_unless_asked(tmp_path, roll, monkeypatch):
    log = tmp_path / "art-cli.jsonl"
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    for item in result.structured_content["items"]:
        assert item["metadata"]["frame_width"] is None and item["metadata"]["frame_height"] is None
        assert (item["metadata"]["width"], item["metadata"]["height"]) == (6048, 4024)
    assert not log.exists()  # no art-cli run


async def test_render_frame_true_measures_each_frame_with_art_cli(tmp_path, roll):
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total))

    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        result = await client.call_tool("inspect_images", {"paths": paths(roll), "frame": True},
                                        progress_callback=on_progress)  # fmt: skip

    assert not result.is_error, result.content
    for item in result.structured_content["items"]:
        assert (item["metadata"]["frame_width"], item["metadata"]["frame_height"]) == (6000, 4000)
        assert (item["metadata"]["width"], item["metadata"]["height"]) == (6048, 4024)  # what the file records
    assert sorted(seen) == [(1, 3), (2, 3), (3, 3)]


async def test_render_frame_true_runs_art_cli_only_for_frames_that_have_metadata(tmp_path, roll, monkeypatch):
    log = tmp_path / "art-cli.jsonl"
    roll[1].with_name(roll[1].name + ".exif.json").unlink()
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll)
        monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
        result = await client.call_tool("inspect_images", {"paths": paths(roll), "frame": True})

    items = result.structured_content["items"]
    assert items[1]["metadata"] is None and items[0]["metadata"]["frame_width"] == 6000
    probed = {a for line in log.read_text().splitlines() for a in json.loads(line) if a.endswith(".ARW")}
    assert probed == {str(roll[0]), str(roll[2])}


async def test_render_frame_stays_null_when_art_cli_cannot_measure_it(tmp_path, roll, monkeypatch):
    async with Client(render_server(tmp_path, art_cli=FAKE_ARTCLI_CTL)) as client:
        await open_all(client, roll)
        monkeypatch.setenv("FAKE_ARTCLI_EXIT", "1")
        result = await client.call_tool("inspect_images", {"paths": paths(roll), "frame": True})

    assert not result.is_error, result.content
    for item in result.structured_content["items"]:
        assert item["error"] is None and item["metadata"]["shutter_seconds"] in SHUTTERS
        assert item["metadata"]["frame_width"] is None and item["metadata"]["frame_height"] is None


@pytest.mark.parametrize("many", [0, 101])
async def test_render_the_list_must_hold_1_to_100_paths(tmp_path, roll, many):
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll[:1])
        result = await client.call_tool("inspect_images", {"paths": paths(roll[:1]) * many})

    assert result.is_error and "out_of_range" in result.content[0].text


async def test_render_100_paths_are_accepted(tmp_path, roll):
    async with Client(render_server(tmp_path)) as client:
        await open_all(client, roll[:1])
        result = await client.call_tool("inspect_images", {"paths": paths(roll[:1]) * 100})

    assert not result.is_error, result.content
    assert len(result.structured_content["items"]) == 100


async def test_render_a_bad_tag_name_fails_the_call_even_when_no_frame_is_open(tmp_path, roll):
    async with Client(render_server(tmp_path)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll), "tags": ["-overwrite_original"]})

    assert result.is_error and "invalid_tag" in result.content[0].text


async def test_render_without_exiftool_the_call_is_metadata_unavailable(tmp_path, roll):
    async with Client(render_server(tmp_path, exiftool=None)) as client:
        await open_all(client, roll)
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    assert result.is_error and "metadata_unavailable" in result.content[0].text


# -- Live --------------------------------------------------------------------


@pytest.fixture
def art(tmp_path):
    fake = FakeArt(tmp_path / "config")
    yield fake
    fake.close()


def open_in_art(art, frames, sizes=(6016, 4016)):
    art.ops["status"] = answer({"version": "t", "images": [
        {"path": str(f), "active": i == 0, "width": sizes[0], "height": sizes[1]} for i, f in enumerate(frames)
    ]})  # fmt: skip


def live_server(art, *, exiftool=EXIFTOOL):
    return build_live_server(ControlChannel(art.config_dir), exiftool=exiftool)


async def test_live_reads_every_open_frame_with_one_exiftool_run(art, roll, exiftool_runs):
    open_in_art(art, roll)

    async with Client(live_server(art)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll), "tags": ["Software"]})

    assert not result.is_error, result.content
    data = result.structured_content
    assert [i["path"] for i in data["items"]] == paths(roll)
    assert [i["metadata"]["shutter_seconds"] for i in data["items"]] == list(SHUTTERS)
    assert [i["metadata"]["tags"] for i in data["items"]] == [{"Software": "v1"}] * 3
    assert data["failed"] == 0
    assert [[Path(p).name for p in run] for run in exiftool_runs()] == [[f.name for f in roll]]


async def test_live_frame_size_comes_from_the_editors_status(art, roll):
    art.ops["status"] = answer({"version": "t", "images": [
        {"path": str(roll[0]), "active": True, "width": 6016, "height": 4016},
        {"path": str(roll[1]), "active": False, "width": None, "height": None},
    ]})  # fmt: skip

    async with Client(live_server(art)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll[:2])})

    first, second = (i["metadata"] for i in result.structured_content["items"])
    assert (first["frame_width"], first["frame_height"]) == (6016, 4016)
    assert (first["width"], first["height"]) == (6048, 4024)
    assert second["frame_width"] is None and second["frame_height"] is None  # until the editor has the size


async def test_live_a_frame_that_is_not_open_is_its_own_error(art, roll, exiftool_runs):
    open_in_art(art, roll[:1] + roll[2:])

    async with Client(live_server(art)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    assert not result.is_error, result.content
    data = result.structured_content
    assert data["failed"] == 1
    assert data["items"][1]["metadata"] is None and data["items"][1]["error"].startswith("not_open:")
    assert [i["metadata"]["shutter_seconds"] for i in (data["items"][0], data["items"][2])] == [0.625, 0.8]
    assert [[Path(p).name for p in run] for run in exiftool_runs()] == [["FILM_1.ARW", "FILM_3.ARW"]]


async def test_live_a_frame_exiftool_cannot_read_is_its_own_error(art, roll):
    roll[1].with_name(roll[1].name + ".exif.json").unlink()
    open_in_art(art, roll)

    async with Client(live_server(art)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    items = result.structured_content["items"]
    assert items[1]["metadata"] is None and items[1]["error"].startswith("metadata_failed:")
    assert items[0]["metadata"]["shutter_seconds"] == 0.625 and items[2]["metadata"]["shutter_seconds"] == 0.8


@pytest.mark.parametrize("many", [0, 101])
async def test_live_the_list_must_hold_1_to_100_paths(art, roll, many):
    open_in_art(art, roll[:1])

    async with Client(live_server(art)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll[:1]) * many})

    assert result.is_error and "out_of_range" in result.content[0].text


async def test_live_without_exiftool_the_call_is_metadata_unavailable(art, roll):
    open_in_art(art, roll)

    async with Client(live_server(art, exiftool=None)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    assert result.is_error and "metadata_unavailable" in result.content[0].text


async def test_live_without_art_the_call_is_art_not_running(tmp_path, roll):
    async with Client(build_live_server(ControlChannel(tmp_path), exiftool=EXIFTOOL)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    assert result.is_error and "art_not_running" in result.content[0].text


async def test_live_a_bad_status_reply_is_bad_reply(art, roll):
    art.ops["status"] = fail("boom", "no")

    async with Client(live_server(art)) as client:
        result = await client.call_tool("inspect_images", {"paths": paths(roll)})

    assert result.is_error and "boom" in result.content[0].text


# -- both: whose exposure these are ------------------------------------------


@pytest.mark.parametrize("tool", ["inspect_image", "inspect_images"])
async def test_both_servers_say_the_values_are_the_digitising_cameras(tmp_path, art, tool):
    for server in (render_server(tmp_path), live_server(art)):
        async with Client(server) as client:
            listed = {t.name: t for t in (await client.list_tools()).tools}

        description = " ".join(listed[tool].description.split())
        assert "digitising camera" in description and "not the original's own exposure" in description
        assert "manual lens" in description
