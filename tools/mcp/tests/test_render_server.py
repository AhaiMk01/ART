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
        result = await client.call_tool("render_preview", {"path": other_spelling.upper() if sys.platform == "win32" else other_spelling})

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


async def test_get_profile_returns_every_value_as_raw_strings(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("get_profile", {"path": str(image)})

    assert not result.is_error, result.content
    profile = result.structured_content
    assert profile["ppversion"] == 1045
    assert profile["adjustments"] == {}
    assert profile["raw"]["Exposure"] == {"Enabled": "true", "Compensation": "0", "Black": "0"}
    assert profile["raw"]["White Balance"]["Setting"] == "Camera"


async def test_raw_edit_changes_the_working_profile_and_the_next_render(server, image):
    edit = {"group": "Exposure", "key": "Compensation", "value": "1.5"}
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("edit_profile", {"path": str(image), "raw_edits": [edit]})
        profile = await client.call_tool("get_profile", {"path": str(image)})
        preview = await client.call_tool("render_preview", {"path": str(image)})

        assert not result.is_error, result.content
        assert result.structured_content["changed"] == [edit]
        assert profile.structured_content["raw"]["Exposure"]["Compensation"] == "1.5"
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
    assert profile.structured_content["raw"]["Exposure"]["Compensation"] == "0"


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
    return profile.structured_content["raw"]["Exposure"]["Compensation"]


async def test_reset_to_sidecar_and_to_default(server, image):
    image.with_name(image.name + ".arp").write_text("[Exposure]\nEnabled=true\nCompensation=1\n")
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool("edit_profile", {"path": str(image), "raw_edits": [set_compensation("3")]})

        to_sidecar = await client.call_tool("reset_profile", {"path": str(image), "to": "sidecar"})
        assert not to_sidecar.is_error, to_sidecar.content
        assert await compensation(client, image) == "1"

        to_default = await client.call_tool("reset_profile", {"path": str(image), "to": "default"})
        assert not to_default.is_error, to_default.content
        assert await compensation(client, image) == "0"


async def test_reset_to_sidecar_without_one_is_not_found(server, image):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("reset_profile", {"path": str(image), "to": "sidecar"})

    assert result.is_error
    assert "not_found" in result.content[0].text
