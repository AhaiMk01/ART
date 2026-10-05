import json
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio


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
def out(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def server(tmp_path):
    cli = ArtCli((sys.executable, str(FAKE)))
    config = tmp_path / "config"
    config.mkdir()
    return build_server(cli, config, PreviewFolder(tmp_path / "previews"))


MINE = "[Exposure]\nCompensation=-3\n"


def compensation(value):
    return [{"group": "Exposure", "key": "Compensation", "value": value}]


async def batch(client, items, folder, **kwargs):
    args = {"items": items, "folder": str(folder), "format": "jpeg", **kwargs}
    return await client.call_tool("export_batch", args)


async def test_exports_each_open_image_with_its_own_working_profile(server, images, out):
    async with Client(server) as client:
        for i, image in enumerate(images[:2]):
            await client.call_tool("open_image", {"path": str(image)})
            await client.call_tool("edit_profile", {"path": str(image), "raw_edits": compensation(f"{i}.5")})
        result = await batch(client, [{"path": str(p)} for p in images[:2]], out)

    assert not result.is_error, result.content
    items = result.structured_content["items"]
    assert [i["output"] for i in items] == [str(out / "FILM_1.jpg"), str(out / "FILM_2.jpg")]
    assert all(i["error"] is None for i in items)
    assert b"Compensation=0.5" in (out / "FILM_1.jpg").read_bytes()
    assert b"Compensation=1.5" in (out / "FILM_2.jpg").read_bytes()
    assert sorted(p.name for p in out.iterdir()) == ["FILM_1.jpg", "FILM_2.jpg"]


async def test_profiles_layer_over_arts_default_without_opening(server, images, out, tmp_path):
    preset = tmp_path / "roll.arp"
    preset.write_text("[Film Negative]\nEnabled=true\n")
    frame = tmp_path / "frame1.arp"
    frame.write_text("[Film Negative]\nRefInput=1;2;3;\n")
    async with Client(server) as client:
        result = await batch(client, [{"path": str(images[0]), "profiles": [str(preset), str(frame)]}], out)

    assert not result.is_error, result.content
    data = (out / "FILM_1.jpg").read_bytes()
    assert data.index(b"Enabled=true") < data.index(b"RefInput=1;2;3;")
    assert b" -d " in data


async def test_one_failing_item_does_not_stop_the_others(server, images, out):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(images[0])})
        result = await batch(client, [{"path": str(images[1])}, {"path": str(images[0])}], out)

    assert not result.is_error, result.content
    first, second = result.structured_content["items"]
    assert first["error"].startswith("not_open")
    assert first["output"] is None
    assert second["error"] is None and (out / "FILM_1.jpg").is_file()
    assert result.structured_content["exported"] == 1
    assert result.structured_content["failed"] == 1


async def test_existing_outputs_are_refused_per_image_unless_overwrite(server, images, out):
    (out / "FILM_1.jpg").write_bytes(b"keep")
    async with Client(server) as client:
        for image in images[:2]:
            await client.call_tool("open_image", {"path": str(image)})
        items = [{"path": str(p)} for p in images[:2]]
        refused = await batch(client, items, out)
        kept = (out / "FILM_1.jpg").read_bytes()
        replaced = await batch(client, items, out, overwrite=True)

    first, second = refused.structured_content["items"]
    assert first["error"].startswith("exists") and kept == b"keep"
    assert second["error"] is None
    assert all(i["error"] is None for i in replaced.structured_content["items"])
    assert (out / "FILM_1.jpg").read_bytes() != b"keep"


async def test_name_pattern_and_write_profile(server, images, out):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(images[0])})
        result = await batch(client, [{"path": str(images[0])}], out, name="{stem}-v2", write_profile=True)

    item = result.structured_content["items"][0]
    assert item["output"] == str(out / "FILM_1-v2.jpg")
    assert item["profile_path"] == str(out / "FILM_1-v2.jpg.arp")
    assert Path(item["profile_path"]).is_file()


async def test_profile_name_source_leaves_a_sidecar_set_in_the_output_folder(server, images, out, tmp_path):
    preset = tmp_path / "roll.arp"
    preset.write_text("[Film Negative]\nEnabled=true\n")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(images[0])})
        result = await batch(
            client,
            [{"path": str(images[0])}, {"path": str(images[1]), "profiles": [str(preset)]}],
            out,
            name="{stem}-v2",
            write_profile=True,
            profile_name="source",
        )

    assert not result.is_error, result.content
    first, second = result.structured_content["items"]
    assert first["profile_path"] == str(out / "FILM_1.ARW.arp")
    assert second["profile_path"] == str(out / "FILM_2.ARW.arp")
    assert "Enabled=true" in (out / "FILM_2.ARW.arp").read_text()
    assert sorted(p.name for p in out.iterdir()) == [
        "FILM_1-v2.jpg", "FILM_1.ARW.arp", "FILM_2-v2.jpg", "FILM_2.ARW.arp",
    ]  # fmt: skip
    assert sorted(p.name for p in images[0].parent.iterdir()) == ["FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW"]


async def test_profile_name_source_spares_the_sidecar_of_an_image_in_the_output_folder(server, images, out):
    inside = out / "FILM_9.ARW"
    inside.write_bytes(b"raw")
    real = out / "FILM_9.ARW.arp"
    real.write_text(MINE)
    async with Client(server) as client:
        for image in (images[0], inside):
            await client.call_tool("open_image", {"path": str(image)})
        result = await batch(
            client, [{"path": str(images[0])}, {"path": str(inside)}], out,
            write_profile=True, profile_name="source", overwrite=True,
        )  # fmt: skip

    assert not result.is_error, result.content
    first, second = result.structured_content["items"]
    assert first["error"] is None and (out / "FILM_1.ARW.arp").is_file()
    assert second["error"].startswith("out_of_range") and second["output"] is None
    assert real.read_text() == MINE
    assert not (out / "FILM_9.jpg").exists()


async def test_profile_name_source_refuses_an_existing_sidecar_unless_overwrite(server, images, out):
    (out / "FILM_1.ARW.arp").write_text("keep")
    async with Client(server) as client:
        for image in images[:2]:
            await client.call_tool("open_image", {"path": str(image)})
        items = [{"path": str(p)} for p in images[:2]]
        refused = await batch(client, items, out, write_profile=True, profile_name="source")
        kept = (out / "FILM_1.ARW.arp").read_text()
        rendered = (out / "FILM_1.jpg").exists()
        replaced = await batch(client, items, out, write_profile=True, profile_name="source", overwrite=True)

    first, second = refused.structured_content["items"]
    assert first["error"].startswith("exists") and kept == "keep" and not rendered
    assert second["error"] is None
    assert all(i["error"] is None for i in replaced.structured_content["items"])
    assert (out / "FILM_1.ARW.arp").read_text() != "keep"


async def test_colliding_output_names_fail_before_anything_renders(server, images, out):
    async with Client(server) as client:
        for image in images[:2]:
            await client.call_tool("open_image", {"path": str(image)})
        result = await batch(client, [{"path": str(p)} for p in images[:2]], out, name="same")

    assert result.is_error and "out_of_range" in result.content[0].text
    assert list(out.iterdir()) == []


async def test_missing_folder_or_profile(server, images, out, tmp_path):
    async with Client(server) as client:
        no_folder = await batch(client, [{"path": str(images[0])}], tmp_path / "nope")
        no_profile = await batch(client, [{"path": str(images[0]), "profiles": [str(tmp_path / "x.arp")]}], out)

    assert no_folder.is_error and "not_found" in no_folder.content[0].text
    assert no_profile.structured_content["items"][0]["error"].startswith("not_found")


async def test_reports_progress_per_image(server, images, out):
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total))

    async with Client(server) as client:
        for image in images:
            await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool(
            "export_batch",
            {"items": [{"path": str(p)} for p in images], "folder": str(out), "format": "jpeg"},
            progress_callback=on_progress,
        )

    assert sorted(seen) == [(1, 3), (2, 3), (3, 3)]


async def test_renders_full_size_with_the_given_quality(server, images, out, tmp_path, monkeypatch):
    log = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(images[0])})
        await batch(client, [{"path": str(images[0])}], out, quality=90)

    runs = [json.loads(line) for line in log.read_text().splitlines()]
    export_runs = [r for r in runs if "-j90" in r]
    assert len(export_runs) == 1
    assert "-f" not in export_runs[0]  # full size


async def batch_folder(client, source, folder, **kwargs):
    args = {"source": str(source), "folder": str(folder), "format": "jpeg", **kwargs}
    return await client.call_tool("export_batch", args)


@pytest.fixture
def preset(tmp_path):
    path = tmp_path / "roll.arp"
    path.write_text("[Film Negative]\nEnabled=true\n")
    return path


async def test_source_folder_exports_its_images_in_sorted_order(server, images, out, preset):
    source = images[0].parent
    (source / "frame_0.arw").write_bytes(b"raw")  # sorts by name whatever the case
    (source / "FILM_1.ARW.arp").write_text("[Exposure]\n")  # a sidecar is not an image
    (source / "notes.txt").write_text("not an image")
    (source / "sub").mkdir()
    (source / "sub" / "FILM_9.ARW").write_bytes(b"raw")  # not recursive
    async with Client(server) as client:
        result = await batch_folder(client, source, out, profiles=[str(preset)])

    assert not result.is_error, result.content
    items = result.structured_content["items"]
    names = ["FILM_1.ARW", "FILM_2.ARW", "FILM_3.ARW", "frame_0.arw"]
    assert [i["path"] for i in items] == [str(source / n) for n in names]
    assert [Path(i["output"]).name for i in items] == ["FILM_1.jpg", "FILM_2.jpg", "FILM_3.jpg", "frame_0.jpg"]
    assert all(i["error"] is None for i in items)
    assert result.structured_content["exported"] == 4
    assert sorted(p.name for p in out.iterdir()) == ["FILM_1.jpg", "FILM_2.jpg", "FILM_3.jpg", "frame_0.jpg"]
    for item in items:  # the preset layers over ART's default on every image
        data = Path(item["output"]).read_bytes()
        assert b"Enabled=true" in data and b" -d " in data


async def test_source_folder_without_profiles_exports_working_profiles(server, images, out):
    async with Client(server) as client:
        for i, image in enumerate(images[:2]):
            await client.call_tool("open_image", {"path": str(image)})
            await client.call_tool("edit_profile", {"path": str(image), "raw_edits": compensation(f"{i}.5")})
        result = await batch_folder(client, images[0].parent, out)

    assert not result.is_error, result.content
    first, second, third = result.structured_content["items"]
    assert first["error"] is None and second["error"] is None
    assert b"Compensation=0.5" in (out / "FILM_1.jpg").read_bytes()
    assert b"Compensation=1.5" in (out / "FILM_2.jpg").read_bytes()
    assert third["error"].startswith("not_open") and third["output"] is None  # FILM_3 was never opened
    assert result.structured_content["exported"] == 2
    assert result.structured_content["failed"] == 1


async def test_source_folder_pattern_narrows_the_images(server, images, out, preset):
    source = images[0].parent
    (source / "FILM_1.ARW.arp").write_text("[Exposure]\n")  # matches the pattern but is no image
    (source / "other.TIF").write_bytes(b"tif")
    async with Client(server) as client:
        film = await batch_folder(client, source, out, profiles=[str(preset)], pattern="film_[12]*")
        tif = await batch_folder(client, source, out, profiles=[str(preset)], pattern="*.tif")

    assert [Path(i["path"]).name for i in film.structured_content["items"]] == ["FILM_1.ARW", "FILM_2.ARW"]
    assert [Path(i["path"]).name for i in tif.structured_content["items"]] == ["other.TIF"]
    assert sorted(p.name for p in out.iterdir()) == ["FILM_1.jpg", "FILM_2.jpg", "other.jpg"]


async def test_source_folder_without_matching_images_or_missing_fails_the_call(server, images, out, tmp_path):
    (tmp_path / "empty").mkdir()
    async with Client(server) as client:
        missing = await batch_folder(client, tmp_path / "nope", out)
        empty = await batch_folder(client, tmp_path / "empty", out)
        unmatched = await batch_folder(client, images[0].parent, out, pattern="*.nef")

    for result in (missing, empty, unmatched):
        assert result.is_error and "not_found" in result.content[0].text
    assert "no images" in empty.content[0].text and "*.nef" in unmatched.content[0].text
    assert list(out.iterdir()) == []


async def test_items_and_source_are_exclusive(server, images, out, preset):
    source = images[0].parent
    async with Client(server) as client:
        both = await batch_folder(client, source, out, items=[{"path": str(images[0])}])
        neither = await client.call_tool("export_batch", {"folder": str(out), "format": "jpeg"})
        pattern = await batch(client, [{"path": str(images[0])}], out, pattern="*.arw")
        profiles = await batch(client, [{"path": str(images[0])}], out, profiles=[str(preset)])

    for result in (both, neither, pattern, profiles):
        assert result.is_error and "out_of_range" in result.content[0].text
    assert list(out.iterdir()) == []


async def test_source_folder_refuses_existing_outputs_per_image_unless_overwrite(server, images, out, preset):
    (out / "FILM_2.jpg").write_bytes(b"keep")
    async with Client(server) as client:
        refused = await batch_folder(client, images[0].parent, out, profiles=[str(preset)])
        replaced = await batch_folder(client, images[0].parent, out, profiles=[str(preset)], overwrite=True)

    first, second, third = refused.structured_content["items"]
    assert second["error"].startswith("exists")
    assert first["error"] is None and third["error"] is None
    assert all(i["error"] is None for i in replaced.structured_content["items"])
    assert (out / "FILM_2.jpg").read_bytes() != b"keep"


async def test_source_folder_images_with_the_same_stem_collide_before_anything_renders(server, images, out, preset):
    source = images[0].parent
    (source / "FILM_1.jpg").write_bytes(b"jpg")
    async with Client(server) as client:
        result = await batch_folder(client, source, out, profiles=[str(preset)])

    assert result.is_error and "out_of_range" in result.content[0].text
    assert "FILM_1.ARW" in result.content[0].text and "FILM_1.jpg" in result.content[0].text
    assert list(out.iterdir()) == []


async def test_an_image_is_never_exported_over_itself(server, images, preset):
    source = images[0].parent
    (source / "scan.jpg").write_bytes(b"original")
    async with Client(server) as client:
        result = await batch_folder(client, source, source, profiles=[str(preset)], pattern="scan*", overwrite=True)

    assert result.structured_content["items"][0]["error"].startswith("exists")
    assert (source / "scan.jpg").read_bytes() == b"original"
