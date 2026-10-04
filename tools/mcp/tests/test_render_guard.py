"""The Render server's save_sidecar refuses an image open in a
control-enabled ART (which would overwrite the sidecar on its own save)."""

import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server
from fake_live_art import FakeArt, answer, fail

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

SIDECAR = "[Exposure]\nEnabled=true\nCompensation=1\nBlack=0\n"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    img.with_name(img.name + ".arp").write_text(SIDECAR)
    return img


@pytest.fixture
def config(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    return config


@pytest.fixture
def art(config):
    fake = FakeArt(config)
    yield fake
    fake.close()


@pytest.fixture
def server(tmp_path, config):
    cli = ArtCli((sys.executable, str(FAKE)))
    return build_server(cli, config, PreviewFolder(tmp_path / "previews"))


def listing(*paths):
    return answer({"version": "t", "images": [
        {"path": str(p), "active": True, "width": None, "height": None} for p in paths]})  # fmt: skip


async def edit_and_save(client, image):
    await client.call_tool("open_image", {"path": str(image)})
    await client.call_tool("edit_profile", {
        "path": str(image), "raw_edits": [{"group": "Exposure", "key": "Compensation", "value": "2"}],
    })  # fmt: skip
    return await client.call_tool("save_sidecar", {"path": str(image)})


async def test_save_of_an_image_open_in_art_is_open_in_editor(server, art, image):
    art.ops["status"] = listing(image)

    async with Client(server) as client:
        result = await edit_and_save(client, image)

    assert result.is_error
    text = result.content[0].text
    assert "open_in_editor:" in text and "Live server" in text
    assert image.with_name(image.name + ".arp").read_text() == SIDECAR


async def test_art_names_the_image_in_another_case(server, art, image):
    if sys.platform != "win32":
        pytest.skip("paths are case-insensitive on Windows only")
    art.ops["status"] = listing(str(image).upper())

    async with Client(server) as client:
        result = await edit_and_save(client, image)

    assert result.is_error and "open_in_editor:" in result.content[0].text


async def test_save_proceeds_when_art_has_other_images_open(server, art, image, tmp_path):
    art.ops["status"] = listing(tmp_path / "other.ARW")

    async with Client(server) as client:
        result = await edit_and_save(client, image)

    assert not result.is_error, result.content
    assert "Compensation=2" in image.with_name(image.name + ".arp").read_text()


async def test_save_proceeds_when_art_answers_with_an_error(server, art, image):
    art.ops["status"] = fail("internal", "boom")

    async with Client(server) as client:
        result = await edit_and_save(client, image)

    assert not result.is_error, result.content


async def test_save_proceeds_without_a_running_art(server, image):
    async with Client(server) as client:
        result = await edit_and_save(client, image)

    assert not result.is_error, result.content
