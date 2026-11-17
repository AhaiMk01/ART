"""art-cli's ``Warning:`` lines reach the preview and export results."""

import json
import sys
from pathlib import Path

import pytest
from mcp.client.client import Client

from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli, cli_warnings
from art_mcp.render.server import build_server

FAKE = Path(__file__).with_name("fake_artcli.py")
WARNING = "cannot load the input profile x.icc; using the camera colour matrix"


def test_warnings_are_taken_without_prefix_and_once():
    output = f"ART, version 1, command line.\nWarning: {WARNING}\nother\n  Warning: {WARNING}\nWarning: second\n"

    assert cli_warnings(output) == [WARNING, "second"]


def test_no_warning_lines_means_none():
    assert cli_warnings("Processing: a.ARW\nwarning: lower case is not one\n") == []


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "FILM_1.ARW"
    path.write_bytes(b"raw")
    return path


@pytest.fixture
def server(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    return build_server(ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews"))


def data(result):
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_preview_and_export_carry_the_warning(server, image, tmp_path, monkeypatch):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        monkeypatch.setenv("FAKE_ARTCLI_WARNING", WARNING)
        monkeypatch.setenv("FAKE_REAL_JPEG", "1")  # the sheet composes real thumbnails

        preview = data(await client.call_tool("render_preview", {"path": str(image)}))
        batch = data(await client.call_tool("render_preview", {"paths": [str(image)]}))
        export = data(
            await client.call_tool(
                "export_image", {"path": str(image), "output": str(tmp_path / "o.jpg"), "format": "jpeg"}
            )
        )
        sheet = (await client.call_tool("contact_sheet", {"images": [str(image)], "record": False})).structured_content

    assert preview["warnings"] == [WARNING]
    assert f"FILM_1.ARW: {WARNING}" in sheet["warnings"]
    assert batch["items"][0]["warnings"] == [WARNING]
    assert export["warnings"] == [WARNING]


@pytest.mark.anyio
async def test_a_clean_render_has_no_warnings(server, image, tmp_path):
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        preview = data(await client.call_tool("render_preview", {"path": str(image)}))
        export = data(
            await client.call_tool(
                "export_image", {"path": str(image), "output": str(tmp_path / "o.jpg"), "format": "jpeg"}
            )
        )

    assert "warnings" not in preview
    assert export["warnings"] == []
