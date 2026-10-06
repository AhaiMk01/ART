import base64
import json
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client
from test_artcli_run import peak_overlap

from art_mcp.metadata import Exiftool
from art_mcp.preview import PreviewFolder
from art_mcp.render import export_ops
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
CTL = Path(__file__).with_name("fake_artcli_ctl.py")
pytestmark = pytest.mark.anyio


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
def server(tmp_path):
    cli = ArtCli((sys.executable, str(FAKE)))
    config = tmp_path / "config"
    config.mkdir()
    return build_server(cli, config, PreviewFolder(tmp_path / "previews"))


async def test_open_then_preview_returns_a_jpeg_file(server, image, tmp_path):
    async with Client(server) as client:
        opened = await client.call_tool("open_image", {"path": str(image)})
        preview = await client.call_tool("render_preview", {"path": str(image)})

        assert not opened.is_error, opened.content
        assert opened.structured_content["art_version"] == "9.9.9"
        assert not preview.is_error, preview.content
        jpeg = Path(preview.structured_content["path"])
        assert jpeg.is_file() and jpeg.parent == tmp_path / "previews"

    assert not (tmp_path / "previews").exists()


async def test_preview_of_an_image_not_opened_is_not_open(server, image):
    async with Client(server) as client:
        result = await client.call_tool("render_preview", {"path": str(image)})

    assert result.is_error
    assert "not_open" in result.content[0].text


async def test_profile_comes_from_sidecar_when_there_is_one(server, image):
    async with Client(server) as client:
        without = await client.call_tool("open_image", {"path": str(image)})
        image.with_name(image.name + ".arp").write_text("[Exposure]\nCompensation=1\n")
        with_sidecar = await client.call_tool("open_image", {"path": str(image)})

    assert without.structured_content["profile_from"] == "default"
    assert with_sidecar.structured_content["profile_from"] == "sidecar"


async def test_same_image_by_another_spelling_is_the_same_image(server, image):
    other_spelling = str(image.parent / ".." / image.parent.name / image.name)
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        spelled = other_spelling.upper() if sys.platform == "win32" else other_spelling
        result = await client.call_tool("render_preview", {"path": spelled})

    assert not result.is_error, result.content


async def test_art_cli_timeout_is_reported_as_timeout(tmp_path, image):
    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(10)\n")
    config = tmp_path / "config"
    config.mkdir()
    server = build_server(
        ArtCli((sys.executable, str(slow)), timeout=0.5), config, PreviewFolder(tmp_path / "p")
    )
    async with Client(server) as client:
        result = await client.call_tool("open_image", {"path": str(image)})

    assert result.is_error
    assert result.content[0].text.split("Error executing tool open_image: ")[-1].startswith("timeout")


async def test_an_empty_sidecar_is_still_the_sidecar(server, image):
    image.with_name(image.name + ".arp").write_text("")
    async with Client(server) as client:
        result = await client.call_tool("open_image", {"path": str(image)})

    assert result.structured_content["profile_from"] == "sidecar"


async def test_get_profile_types_curated_tools_and_leaves_the_rest_raw(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("get_profile", {"path": str(image)})

    assert not result.is_error, result.content
    profile = result.structured_content
    assert profile["ppversion"] == 1045
    assert profile["adjustments"]["exposure"]["compensation"] == 0.0
    assert profile["adjustments"]["white_balance"]["setting"] == "Camera"
    assert profile["raw"] == {}


async def test_raw_edit_changes_the_working_profile_and_the_next_render(server, image):
    edit = {"group": "Exposure", "key": "Compensation", "value": "1.5"}
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("edit_profile", {"path": str(image), "raw_edits": [edit]})
        profile = await client.call_tool("get_profile", {"path": str(image)})
        preview = await client.call_tool("render_preview", {"path": str(image)})

        assert not result.is_error, result.content
        assert result.structured_content["changed"] == {"Exposure": {"Compensation": "1.5"}}
        assert profile.structured_content["adjustments"]["exposure"]["compensation"] == 1.5
        assert b"Compensation=1.5" in Path(preview.structured_content["path"]).read_bytes()


async def test_unknown_key_is_rejected_and_nothing_changes(server, image):
    edits = [
        {"group": "Exposure", "key": "Compensation", "value": "2"},
        {"group": "Exposure", "key": "Compensaton", "value": "2"},
    ]
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("edit_profile", {"path": str(image), "raw_edits": edits})
        profile = await client.call_tool("get_profile", {"path": str(image)})

    assert result.is_error
    assert "unknown_key" in result.content[0].text
    assert "Compensaton" in result.content[0].text
    assert profile.structured_content["adjustments"]["exposure"]["compensation"] == 0


async def export(client, image, output, **args):
    return await client.call_tool(
        "export_image", {"path": str(image), "output": str(output), "format": "jpeg", **args}
    )


async def test_export_renders_the_working_profile_to_output_with_no_arp_beside_it(server, image, tmp_path):
    out = tmp_path / "out" / "final.jpg"
    out.parent.mkdir()
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool("edit_profile", {"path": str(image), "raw_edits": [set_compensation("1.5")]})
        result = await export(client, image, out, quality=90)

        assert not result.is_error, result.content
        assert result.structured_content["path"] == str(out)
        assert b"Compensation=1.5" in out.read_bytes()
        assert sorted(p.name for p in out.parent.iterdir()) == ["final.jpg"]


async def test_export_formats_and_bit_depth_reach_art_cli(server, image, tmp_path):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        tiff = await export(client, image, tmp_path / "a.tif", format="tiff", bit_depth="16f")
        png = await export(client, image, tmp_path / "a.png", format="png", bit_depth="16")

        assert not tiff.is_error and not png.is_error, (tiff.content, png.content)
        assert (tmp_path / "a.tif").read_bytes().startswith(b"II*")
        assert (tmp_path / "a.png").read_bytes().startswith(b"\x89PNG")


async def test_export_schema_lists_the_formats(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    schema = next(t for t in tools.tools if t.name == "export_image").input_schema
    assert schema["properties"]["format"]["enum"] == ["jpeg", "tiff", "png"]


async def test_bit_depth_may_be_given_as_a_number(server, image, tmp_path):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        png = await export(client, image, tmp_path / "a.png", format="png", bit_depth=16)

    assert not png.is_error, png.content
    assert (tmp_path / "a.png").read_bytes().startswith(b"\x89PNG")


async def test_existing_output_is_refused_untouched_unless_overwrite(server, image, tmp_path):
    out = tmp_path / "final.jpg"
    out.write_bytes(b"precious")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        refused = await export(client, image, out)

        assert refused.is_error
        assert "exists" in refused.content[0].text
        assert out.read_bytes() == b"precious"

        replaced = await export(client, image, out, overwrite=True)
        assert not replaced.is_error, replaced.content
        assert out.read_bytes() != b"precious"


async def test_write_profile_puts_the_working_profile_beside_the_output(server, image, tmp_path):
    out = tmp_path / "final.jpg"
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool("edit_profile", {"path": str(image), "raw_edits": [set_compensation("1.5")]})
        result = await export(client, image, out, write_profile=True)

        assert not result.is_error, result.content
        arp = tmp_path / "final.jpg.arp"
        assert result.structured_content["profile_path"] == str(arp)
        assert "Compensation=1.5" in arp.read_text()
        assert not any(p.suffix in {".tmp"} for p in tmp_path.iterdir())


async def test_an_export_whose_profile_cannot_be_placed_leaves_no_image_behind(server, image, tmp_path, monkeypatch):
    out = tmp_path / "final.jpg"
    move = export_ops.move_over

    def refuse_the_profile(source, target):
        if target.suffix == ".arp":
            raise PermissionError("denied")
        move(source, target)

    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        monkeypatch.setattr(export_ops, "move_over", refuse_the_profile)
        failed = await export(client, image, out, write_profile=True)
        monkeypatch.setattr(export_ops, "move_over", move)

        assert failed.is_error and "render_failed" in failed.content[0].text
        assert not out.exists() and not (tmp_path / "final.jpg.arp").exists()
        retried = await export(client, image, out, write_profile=True)  # not refused as "exists"
        assert not retried.is_error, retried.content


async def test_an_image_is_never_exported_over_itself(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        refused = await export(client, image, image, overwrite=True)
        spelled_otherwise = image.parent / ".." / image.parent.name / image.name
        other_spelling = await export(client, image, spelled_otherwise, overwrite=True)

    for result in (refused, other_spelling):
        assert result.is_error and "exists" in result.content[0].text and "the image itself" in result.content[0].text
    assert image.read_bytes() == b"raw"


async def test_write_profile_respects_overwrite_for_the_arp(server, image, tmp_path):
    out = tmp_path / "final.jpg"
    (tmp_path / "final.jpg.arp").write_text("mine")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        refused = await export(client, image, out, write_profile=True)

        assert refused.is_error and "exists" in refused.content[0].text
        assert not out.exists()
        assert (tmp_path / "final.jpg.arp").read_text() == "mine"

        without = await export(client, image, out)
        assert not without.is_error, without.content
        assert (tmp_path / "final.jpg.arp").read_text() == "mine"


async def test_profile_name_source_writes_the_profile_under_the_images_name_in_the_output_folder(
    server, image, tmp_path
):
    out = tmp_path / "out"
    out.mkdir()
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool("edit_profile", {"path": str(image), "raw_edits": [set_compensation("1.5")]})
        result = await export(client, image, out / "final.jpg", write_profile=True, profile_name="source")

    assert not result.is_error, result.content
    sidecar = out / "IMG_1.ARW.arp"
    assert result.structured_content["profile_path"] == str(sidecar)
    assert "Compensation=1.5" in sidecar.read_text()
    assert sorted(p.name for p in out.iterdir()) == ["IMG_1.ARW.arp", "final.jpg"]
    assert [p.name for p in image.parent.iterdir()] == ["IMG_1.ARW"]


async def test_profile_name_source_honours_the_strip_extension_option(server, image, tmp_path):
    (tmp_path / "config" / "options").write_text("[Profiles]\nParamsSidecarStripExtension=true\n")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await export(client, image, tmp_path / "final.jpg", write_profile=True, profile_name="source")

    assert not result.is_error, result.content
    assert result.structured_content["profile_path"] == str(tmp_path / "IMG_1.arp")
    assert (tmp_path / "IMG_1.arp").is_file()
    assert not (tmp_path / "final.jpg.arp").exists()


@pytest.mark.parametrize("overwrite", [False, True])
async def test_profile_name_source_never_writes_the_images_own_sidecar(server, image, overwrite):
    real = image.parent / "IMG_1.ARW.arp"
    real.write_text("[Exposure]\nCompensation=-3\n")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await export(
            client, image, image.parent / "final.jpg", write_profile=True, profile_name="source", overwrite=overwrite
        )

    assert result.is_error and "out_of_range" in result.content[0].text
    assert real.read_text() == "[Exposure]\nCompensation=-3\n"
    assert not (image.parent / "final.jpg").exists()


async def test_profile_name_source_respects_overwrite_for_the_arp(server, image, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "IMG_1.ARW.arp").write_text("mine")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        refused = await export(client, image, out / "final.jpg", write_profile=True, profile_name="source")

        assert refused.is_error and "exists" in refused.content[0].text
        assert not (out / "final.jpg").exists()
        assert (out / "IMG_1.ARW.arp").read_text() == "mine"

        replaced = await export(
            client, image, out / "final.jpg", write_profile=True, profile_name="source", overwrite=True
        )
        assert not replaced.is_error, replaced.content
        assert (out / "IMG_1.ARW.arp").read_text() != "mine"


async def test_profile_name_source_needs_write_profile(server, image, tmp_path):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await export(client, image, tmp_path / "final.jpg", profile_name="source")

    assert result.is_error and "out_of_range" in result.content[0].text
    assert not (tmp_path / "final.jpg").exists()


async def test_profile_name_is_output_or_source(server, image, tmp_path):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        tools = await client.list_tools()
        result = await export(client, image, tmp_path / "final.jpg", write_profile=True, profile_name="raw")

    schema = next(t for t in tools.tools if t.name == "export_image").input_schema
    assert schema["properties"]["profile_name"]["enum"] == ["output", "source"]
    assert result.is_error and "out_of_range" in result.content[0].text
    assert not (tmp_path / "final.jpg").exists()


@pytest.mark.parametrize(
    "args",
    [
        {"quality": 101},
        {"quality": 0},
        {"format": "png", "quality": 90},
        {"format": "png", "bit_depth": "32"},
        {"bit_depth": "16"},
        {"format": "gif"},
    ],
)
async def test_invalid_export_options_are_out_of_range(server, image, tmp_path, args):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await export(client, image, tmp_path / "x.out", **args)

    assert result.is_error
    assert "out_of_range" in result.content[0].text
    assert not (tmp_path / "x.out").exists()


async def test_export_to_a_missing_folder_is_not_found(server, image, tmp_path):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await export(client, image, tmp_path / "nope" / "x.jpg")

    assert result.is_error and "not_found" in result.content[0].text
    assert not (tmp_path / "nope").exists()


async def test_export_of_an_image_not_opened_is_not_open(server, image, tmp_path):
    async with Client(server) as client:
        result = await export(client, image, tmp_path / "x.jpg")

    assert result.is_error and "not_open" in result.content[0].text


def set_compensation(value):
    return {"group": "Exposure", "key": "Compensation", "value": value}


async def compensation(client, image):
    profile = await client.call_tool("get_profile", {"path": str(image)})
    return profile.structured_content["adjustments"]["exposure"]["compensation"]


async def test_reset_to_sidecar_and_to_default(server, image):
    image.with_name(image.name + ".arp").write_text("[Exposure]\nEnabled=true\nCompensation=1\n")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool("edit_profile", {"path": str(image), "raw_edits": [set_compensation("3")]})

        to_sidecar = await client.call_tool("reset_profile", {"path": str(image), "to": "sidecar"})
        assert not to_sidecar.is_error, to_sidecar.content
        assert await compensation(client, image) == 1

        to_default = await client.call_tool("reset_profile", {"path": str(image), "to": "default"})
        assert not to_default.is_error, to_default.content
        assert await compensation(client, image) == 0


async def test_reset_to_sidecar_without_one_is_not_found(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("reset_profile", {"path": str(image), "to": "sidecar"})

    assert result.is_error
    assert "not_found" in result.content[0].text


# -- reset_profile(paths): several images at once ------------------------------------


@pytest.fixture
def roll(tmp_path):
    """Three raws; the first two have a sidecar (Compensation=1)."""
    folder = tmp_path / "roll"
    folder.mkdir()
    frames = []
    for n in range(3):
        frame = folder / f"FILM_{n}.ARW"
        frame.write_bytes(b"raw")
        if n < 2:
            frame.with_name(frame.name + ".arp").write_text("[Exposure]\nEnabled=true\nCompensation=1\n")
        frames.append(frame)
    return frames


async def open_roll(client, roll):
    for frame in roll:
        opened = await client.call_tool("open_image", {"path": str(frame)})
        assert not opened.is_error, opened.content


async def edit_roll(client, roll, value="3"):
    result = await client.call_tool(
        "edit_profile", {"paths": [str(f) for f in roll], "raw_edits": [set_compensation(value)]}
    )
    assert not result.is_error, result.content


async def test_reset_of_several_images_reloads_each_and_reports_one_compact_entry_per_image(server, roll):
    paths = [str(f) for f in roll]
    async with Client(server) as client:
        await open_roll(client, roll)
        await edit_roll(client, roll)
        to_default = await client.call_tool("reset_profile", {"paths": paths, "to": "default"})
        after_default = [await compensation(client, f) for f in roll]
        await edit_roll(client, roll)
        to_sidecar = await client.call_tool("reset_profile", {"paths": paths, "to": "sidecar"})
        after_sidecar = [await compensation(client, f) for f in roll]

    assert not to_default.is_error, to_default.content
    assert to_default.structured_content == {
        "items": [{"path": p, "profile_from": "default"} for p in paths], "failed": 0,
    }  # in request order, each with the path as given
    assert after_default == [0, 0, 0]
    assert not to_sidecar.is_error, to_sidecar.content
    ok1, ok2, no_sidecar = to_sidecar.structured_content["items"]
    assert (ok1, ok2) == ({"path": paths[0], "profile_from": "sidecar"}, {"path": paths[1], "profile_from": "sidecar"})
    assert set(no_sidecar) == {"path", "error"} and no_sidecar["error"].startswith("not_found")
    assert to_sidecar.structured_content["failed"] == 1
    assert after_sidecar == [1, 1, 3]  # the third one has no sidecar: its working profile is as it was


async def test_an_image_that_is_not_open_is_its_own_reset_error_and_the_others_still_reset(server, roll):
    async with Client(server) as client:
        await open_roll(client, roll[:1] + roll[2:])  # roll[1] is not open
        await edit_roll(client, roll[:1] + roll[2:])
        result = await client.call_tool("reset_profile", {"paths": [str(f) for f in roll], "to": "default"})
        after = [await compensation(client, f) for f in (roll[0], roll[2])]

    ok1, missing, ok2 = result.structured_content["items"]
    assert not result.is_error, result.content
    assert set(missing) == {"path", "error"} and missing["error"].startswith("not_open")
    assert (ok1["profile_from"], ok2["profile_from"]) == ("default", "default")
    assert result.structured_content["failed"] == 1
    assert after == [0, 0]


async def test_the_same_image_twice_in_a_reset_is_reset_twice(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("reset_profile", {"paths": [str(image), str(image)], "to": "default"})

    assert [i["profile_from"] for i in result.structured_content["items"]] == ["default", "default"]


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ({"path": "a.ARW", "paths": ["a.ARW"]}, "not both"),
        ({}, "path or paths"),
        ({"paths": []}, "paths is empty"),
        ({"paths": [f"{i}.ARW" for i in range(51)]}, "51 entries; the most one call takes is 50"),
    ],
)
async def test_a_bad_choice_of_images_to_reset_is_out_of_range_before_anything_changes(server, image, args, text):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await edit_roll(client, [image], "3")
        result = await client.call_tool("reset_profile", {"to": "default", **args})
        value = await compensation(client, image)

    assert result.is_error and "out_of_range" in result.content[0].text and text in result.content[0].text
    assert value == 3


async def test_reset_of_several_images_reports_progress_per_image(server, roll):
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total))

    async with Client(server) as client:
        await open_roll(client, roll)
        await client.call_tool(
            "reset_profile", {"paths": [str(f) for f in roll], "to": "default"}, progress_callback=on_progress
        )

    assert sorted(seen) == [(1, 3), (2, 3), (3, 3)]


def pooled_server(tmp_path, max_processes=2):
    """A server whose art-cli can be slowed down and watched (``FAKE_ARTCLI_LOG``, ``FAKE_ARTCLI_SLEEP``)."""
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    cli = ArtCli((sys.executable, str(CTL)), max_processes=max_processes)
    return build_server(cli, config, PreviewFolder(tmp_path / "previews"))


async def test_reset_of_several_images_runs_through_the_bounded_pool(tmp_path, roll, monkeypatch):
    log = tmp_path / "runs"
    log.mkdir()
    async with Client(pooled_server(tmp_path)) as client:
        await open_roll(client, roll)
        monkeypatch.setenv("FAKE_ARTCLI_LOG", str(log))
        monkeypatch.setenv("FAKE_ARTCLI_SLEEP", "0.3")
        result = await client.call_tool("reset_profile", {"paths": [str(f) for f in roll] * 2, "to": "default"})

    assert not result.is_error, result.content
    assert result.structured_content["failed"] == 0
    assert peak_overlap(log) == (6, 2)  # six resolves, two at a time: the cap, and in parallel


async def test_the_tool_describes_paths_and_its_two_result_shapes_for_reset(server):
    async with Client(server) as client:
        tools = await client.list_tools()

    tool = next(t for t in tools.tools if t.name == "reset_profile")
    assert tool.input_schema["required"] == ["to"]  # one of path, paths: checked by the tool
    assert {"type": "array", "items": {"type": "string"}} in tool.input_schema["properties"]["paths"]["anyOf"]
    assert "`paths`" in tool.description and "50" in tool.description
    assert {"ResetResult", "ResetBatch", "ResetItem"} <= tool.output_schema["$defs"].keys()
    assert tool.output_schema["type"] == "object"


FAKE_EXIFTOOL = Path(__file__).with_name("fake_exiftool.py")


def exif_server(tmp_path, exiftool=...):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    if exiftool is ...:
        exiftool = Exiftool((sys.executable, str(FAKE_EXIFTOOL)))
    return build_server(
        ArtCli((sys.executable, str(FAKE))),
        config,
        PreviewFolder(tmp_path / "previews"),
        exiftool=exiftool,
    )


@pytest.fixture
def tagged(image):
    known = {"Make": "SONY", "Model": "ILCE-7M3", "LensModel": "FE 35mm F1.8", "ISO": 400,
             "DateTimeOriginal": "2025:12:28 12:04:04", "ImageWidth": 6000, "ImageHeight": 4000,
             "Software": "v1"}  # fmt: skip
    image.with_name(image.name + ".exif.json").write_text(json.dumps(known))
    return image


async def test_inspect_open_image_returns_fixed_fields_and_requested_tags(tmp_path, tagged):
    async with Client(exif_server(tmp_path)) as client:
        await client.call_tool("open_image", {"path": str(tagged)})
        result = await client.call_tool("inspect_image", {"path": str(tagged), "tags": ["Software"]})

    assert not result.is_error, result.content
    data = result.structured_content
    assert (data["make"], data["model"], data["iso"], data["width"]) == ("SONY", "ILCE-7M3", 400, 6000)
    assert data["tags"] == {"Software": "v1"}


async def test_inspect_reports_the_frame_ART_works_in_next_to_the_recorded_size(tmp_path, tagged):
    """A Sony ARW records 6048 x 4024 but ART's frame, the space crop coordinates are in,
    is smaller (the fake art-cli's 6000 x 4000)."""
    tagged.with_name(tagged.name + ".exif.json").write_text(json.dumps({"ImageWidth": 6048, "ImageHeight": 4024}))
    async with Client(exif_server(tmp_path)) as client:
        await client.call_tool("open_image", {"path": str(tagged)})
        result = await client.call_tool("inspect_image", {"path": str(tagged)})

    assert not result.is_error, result.content
    data = result.structured_content
    assert (data["width"], data["height"]) == (6048, 4024)
    assert (data["frame_width"], data["frame_height"]) == (6000, 4000)


async def test_inspect_frame_is_null_when_art_cli_cannot_measure_it(tmp_path, tagged, monkeypatch):
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)
    server = build_server(
        ArtCli((sys.executable, str(FAKE.with_name("fake_artcli_ctl.py")))),
        config,
        PreviewFolder(tmp_path / "previews"),
        exiftool=Exiftool((sys.executable, str(FAKE_EXIFTOOL))),
    )
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(tagged)})
        monkeypatch.setenv("FAKE_ARTCLI_EXIT", "1")
        result = await client.call_tool("inspect_image", {"path": str(tagged)})

    assert not result.is_error, result.content
    assert result.structured_content["frame_width"] is None and result.structured_content["frame_height"] is None
    assert result.structured_content["width"] == 6000  # the recorded size is still there


async def test_inspect_image_not_opened_is_not_open(tmp_path, tagged):
    async with Client(exif_server(tmp_path)) as client:
        result = await client.call_tool("inspect_image", {"path": str(tagged)})

    assert result.is_error and "not_open" in result.content[0].text


async def test_inspect_without_exiftool_says_metadata_unavailable(tmp_path, tagged):
    async with Client(exif_server(tmp_path, exiftool=None)) as client:
        opened = await client.call_tool("open_image", {"path": str(tagged)})
        result = await client.call_tool("inspect_image", {"path": str(tagged)})

    assert not opened.is_error and opened.structured_content["metadata"] is None
    assert result.is_error and "metadata_unavailable" in result.content[0].text


async def test_inspect_with_a_bad_tag_name_is_invalid_tag(tmp_path, tagged):
    async with Client(exif_server(tmp_path)) as client:
        await client.call_tool("open_image", {"path": str(tagged)})
        result = await client.call_tool(
            "inspect_image", {"path": str(tagged), "tags": ["-overwrite_original"]}
        )

    assert result.is_error and "invalid_tag" in result.content[0].text


async def test_inspect_when_exiftool_fails_is_metadata_failed(tmp_path, image):
    # No .exif.json beside the image: the fake exits with a traceback.
    async with Client(exif_server(tmp_path)) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("inspect_image", {"path": str(image)})

    assert result.is_error and "metadata_failed" in result.content[0].text


async def test_open_image_includes_a_metadata_summary(tmp_path, tagged):
    async with Client(exif_server(tmp_path)) as client:
        opened = await client.call_tool("open_image", {"path": str(tagged)})

    assert opened.structured_content["metadata"] == {
        "camera": "SONY ILCE-7M3",
        "lens": "FE 35mm F1.8",
        "capture_date": "2025-12-28T12:04:04",
        "width": 6000,
        "height": 4000,
    }


async def test_open_image_still_opens_when_metadata_cannot_be_read(tmp_path, image):
    async with Client(exif_server(tmp_path)) as client:
        opened = await client.call_tool("open_image", {"path": str(image)})

    assert not opened.is_error and opened.structured_content["metadata"] is None


async def test_open_image_of_several_images_keeps_each_ones_metadata_summary(tmp_path, tagged):
    other = tagged.with_name("IMG_2.ARW")
    other.write_bytes(b"raw")  # exiftool has nothing on this one: no summary, but it opens
    async with Client(exif_server(tmp_path)) as client:
        opened = await client.call_tool("open_image", {"paths": [str(tagged), str(other)]})

    first, second = opened.structured_content["items"]
    assert not opened.is_error, opened.content
    assert first["metadata"] == {
        "camera": "SONY ILCE-7M3",
        "lens": "FE 35mm F1.8",
        "capture_date": "2025-12-28T12:04:04",
        "width": 6000,
        "height": 4000,
    }
    assert second == {"path": str(other), "profile_from": "default"}  # no `metadata`, no `error`


def error_text(result):
    return result.content[0].text


async def preview_bytes(client, image, **args):
    result = await client.call_tool("render_preview", {"path": str(image), **args})
    assert not result.is_error, result.content
    return Path(result.structured_content["path"]).read_bytes(), result


async def test_max_size_is_between_1_and_2576(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        for bad in (0, 2577):
            result = await client.call_tool("render_preview", {"path": str(image), "max_size": bad})
            assert result.is_error and "out_of_range" in error_text(result), bad
        _, ok = await preview_bytes(client, image, max_size=2576)

    assert ok.structured_content["max_size"] == 2576


async def test_max_size_sets_the_resize_layer(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        jpeg, _ = await preview_bytes(client, image, max_size=640)

    assert b"Width=640" in jpeg and b"Height=640" in jpeg


async def used_fast_export(client, image, **args):
    jpeg, _ = await preview_bytes(client, image, **args)
    return b" -f " in jpeg.split(b"args: ")[1]


async def test_fast_export_only_when_max_size_fits_the_users_fast_export_box(server, image, tmp_path):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})

        assert await used_fast_export(client, image)  # 1024, default box 1920
        assert await used_fast_export(client, image, max_size=1920)
        assert not await used_fast_export(client, image, max_size=1921)

    (tmp_path / "config" / "options").write_text(
        "[Fast Export]\nfastexport_resize_width=2400\nfastexport_resize_height=2400\n"
    )
    async with Client(server) as client:
        assert await used_fast_export(client, image, max_size=2400)
        assert not await used_fast_export(client, image, max_size=2401)


REGION = {"x": 0.25, "y": 0.5, "w": 0.5, "h": 0.25}


async def test_region_preview_crops_at_1_to_1_without_fast_export(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        jpeg, _ = await preview_bytes(client, image, region=REGION, max_size=2000)
        profile = await client.call_tool("get_profile", {"path": str(image)})

    # The fake image is 6000x4000: the region is 1500,2000 3000x1000 pixels.
    assert b"X=1500\nY=2000\nW=3000\nH=1000" in jpeg
    assert b"Width=2000" in jpeg  # the resize layer only caps at max_size
    assert b" -f " not in jpeg.split(b"args: ")[1]
    assert "Crop" not in profile.structured_content["raw"]


async def test_region_is_relative_to_the_working_crop_when_there_is_one(server, image):
    image.with_name(image.name + ".arp").write_text(
        "[Crop]\nEnabled=true\nX=1000\nY=500\nW=2000\nH=1000\nFixedRatio=false\n"
    )
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        jpeg, _ = await preview_bytes(client, image, region=REGION)

    assert b"X=1500\nY=1000\nW=1000\nH=250" in jpeg


@pytest.mark.parametrize(
    "region",
    [
        {"x": -0.1, "y": 0, "w": 0.5, "h": 0.5},
        {"x": 0, "y": 0, "w": 0, "h": 0.5},
        {"x": 0.6, "y": 0, "w": 0.5, "h": 0.5},
        {"x": 0, "y": 0.5, "w": 0.5, "h": 0.6},
        {"x": 0, "y": 0, "w": 1.5, "h": 1},
    ],
)
async def test_region_outside_the_image_is_out_of_range(server, image, region):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("render_preview", {"path": str(image), "region": region})

    assert result.is_error
    assert "out_of_range" in error_text(result)


def images(result):
    return [block for block in result.content if block.type == "image"]


@pytest.fixture
def inline_server(tmp_path):
    cli = ArtCli((sys.executable, str(FAKE)))
    config = tmp_path / "config"
    config.mkdir()
    return build_server(cli, config, PreviewFolder(tmp_path / "previews"), inline_previews=True)


async def test_previews_are_not_inline_by_default(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        default = await client.call_tool("render_preview", {"path": str(image)})
        forced = await client.call_tool("render_preview", {"path": str(image), "inline": True})
        jpeg = Path(forced.structured_content["path"]).read_bytes()  # the path is still returned

    assert not images(default)
    [block] = images(forced)
    assert base64.b64decode(block.data) == jpeg and block.mime_type == "image/jpeg"


async def test_inline_launch_flag_is_the_default_and_a_call_can_override_it(inline_server, image):
    async with Client(inline_server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        default = await client.call_tool("render_preview", {"path": str(image)})
        off = await client.call_tool("render_preview", {"path": str(image), "inline": False})

    assert len(images(default)) == 1 and default.structured_content["path"]
    assert not images(off)


# -- output: keep the preview where the caller says --------------------------


def leftovers(tmp_path):
    folder = tmp_path / "previews"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


async def test_a_preview_can_be_written_to_a_path_of_the_callers_choice(server, image, tmp_path):
    out = tmp_path / "work" / "look.jpg"
    out.parent.mkdir()
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("render_preview", {"path": str(image), "max_size": 640, "output": str(out)})

    assert not result.is_error, result.content
    assert result.structured_content == {"path": str(out), "max_size": 640}
    jpeg = out.read_bytes()
    assert jpeg.startswith(b"\xff\xd8") and b"Width=640" in jpeg
    assert leftovers(tmp_path) == []  # the server's own copy is not kept next to it


async def test_the_inline_image_is_the_file_at_output(server, image, tmp_path):
    out = tmp_path / "look.jpg"
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("render_preview", {"path": str(image), "output": str(out), "inline": True})

    [block] = images(result)
    assert base64.b64decode(block.data) == out.read_bytes()


async def test_an_existing_output_is_refused_unless_overwrite_and_nothing_renders_first(server, image, tmp_path):
    out = tmp_path / "look.jpg"
    out.write_bytes(b"keep me")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        refused = await client.call_tool("render_preview", {"path": str(image), "output": str(out)})
        kept = out.read_bytes()
        refused_leftovers = leftovers(tmp_path)
        replaced = await client.call_tool(
            "render_preview", {"path": str(image), "output": str(out), "overwrite": True}
        )

    assert refused.is_error and "exists:" in error_text(refused)
    assert kept == b"keep me" and refused_leftovers == []
    assert not replaced.is_error, replaced.content
    assert out.read_bytes().startswith(b"\xff\xd8") and leftovers(tmp_path) == []


@pytest.mark.parametrize(
    ("name", "code"),
    [("missing/look.jpg", "not_found"), ("look.png", "out_of_range"), ("look", "out_of_range")],
)
async def test_output_needs_an_existing_folder_and_a_jpeg_name(server, image, tmp_path, name, code):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("render_preview", {"path": str(image), "output": str(tmp_path / name)})

    assert result.is_error and f"{code}:" in error_text(result)
    assert leftovers(tmp_path) == [] and not (tmp_path / name).exists()


async def test_output_must_be_an_absolute_path(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("render_preview", {"path": str(image), "output": "look.jpg"})

    assert result.is_error and "out_of_range:" in error_text(result) and "absolute" in error_text(result)


async def test_a_preview_never_replaces_the_image_it_shows(server, tmp_path):
    scan = tmp_path / "photos" / "scan.JPG"
    scan.parent.mkdir()
    scan.write_bytes(b"jpeg scan")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(scan)})
        result = await client.call_tool(
            "render_preview", {"path": str(scan), "output": str(scan), "overwrite": True}
        )

    assert result.is_error and "exists:" in error_text(result)
    assert scan.read_bytes() == b"jpeg scan"


async def test_a_failed_render_leaves_nothing_at_output(server, image, tmp_path):
    out = tmp_path / "look.jpg"
    async with Client(server) as client:
        result = await client.call_tool("render_preview", {"path": str(image), "output": str(out)})  # not open

    assert result.is_error and "not_open:" in error_text(result)
    assert not out.exists()


async def test_the_description_says_what_inline_does_and_defaults_to(server):
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}

    text = tools["render_preview"].description
    assert "inline" in text and "--inline-previews" in text and "off" in text
    assert "output" in text and "overwrite" in text
