"""open_image's `profile`: the working profile starts from a given .arp (full or
partial, layered over ART's default profile) instead of the sidecar."""

import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp import keyfile
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
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
