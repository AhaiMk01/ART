"""Smaller profile reads and edit echoes: get_profile's `groups` and
`changed_only`, edit_profile's change-set result and its `full` echo, on both
servers, against a complete ART profile (``data/art_profile.arp``: 640 lines,
as ART writes them, with the tools at their defaults)."""

import json
import re
import sys
from pathlib import Path

import pytest
from fake_live_art import FakeArt, FakeEditor
from mcp.client.client import Client

from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live
from art_mcp.preview import PreviewFolder
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server as build_render

FAKE = Path(__file__).with_name("fake_artcli.py")
PROFILE = Path(__file__).with_name("data") / "art_profile.arp"
pytestmark = pytest.mark.anyio

FILM_BASE = {
    "exposure": {"enabled": False},
    "tone_curve": {
        "mode": "Standard", "histogram_matching": False,
        "curve1": {"type": "linear"}, "curve2": {"type": "linear"},
    },
    "sharpening": {"enabled": False},
    "film_negative": {"enabled": True, "color_space": "working", "red_ratio": 1.335, "blue_ratio": 0.759},
}  # fmt: skip
"""The film-negative skill's base settings (its step 2)."""
FILM_RAW = [
    {"group": "RAW Bayer", "key": "Method", "value": "amaze"},
    {"group": "RAW", "key": "CAEnabled", "value": "false"},
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def tokens(result) -> int:
    """A rough token count of the text a client reads: its words, numbers and
    punctuation (the ratio between two results is what the tests use)."""
    return len(re.findall(r"\w+|[^\w\s]", result.content[0].text))


def edit_request(path, **more):
    return {"path": path, "adjustments": FILM_BASE, "raw_edits": FILM_RAW, **more}


# -- Render -------------------------------------------------------------------


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


@pytest.fixture
def args_log(tmp_path, monkeypatch):
    log = tmp_path / "args.log"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
    return log


@pytest.fixture
def render(tmp_path, monkeypatch, args_log):
    monkeypatch.setenv("FAKE_DEFAULT_PROFILE", str(PROFILE))
    config = tmp_path / "config"
    config.mkdir()
    return build_render(ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews"))


def default_runs(log):
    """How many times art-cli was asked for ART's default profile."""
    return sum("-d" in json.loads(line) for line in log.read_text().splitlines())


async def test_get_profile_of_chosen_groups_holds_only_those(render, image):
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        whole = await client.call_tool("get_profile", {"path": str(image)})
        chosen = await client.call_tool("get_profile", {"path": str(image), "groups": ["Film Negative", "ToneCurve"]})

    assert not chosen.is_error, chosen.content
    view = chosen.structured_content
    assert set(view["adjustments"]) == {"film_negative", "tone_curve"}
    assert set(view["raw"]) == {"ToneCurve"}  # what the tool doesn't type
    assert view["adjustments"]["film_negative"]["red_ratio"] == 1.36
    assert view["ppversion"] == 1045
    assert tokens(chosen) * 10 < tokens(whole)


async def test_an_unknown_group_is_unknown_key_and_lists_the_valid_ones(render, image):
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("get_profile", {"path": str(image), "groups": ["Film negative"]})

    assert result.is_error
    text = result.content[0].text
    assert text.split("Error executing tool get_profile: ")[-1].startswith("unknown_key")
    assert "Film negative" in text and "Film Negative" in text and "RAW Bayer" in text


async def test_changed_only_holds_what_differs_from_arts_default_profile(render, image):
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        untouched = await client.call_tool("get_profile", {"path": str(image), "changed_only": True})
        await client.call_tool("edit_profile", edit_request(str(image)))
        whole = await client.call_tool("get_profile", {"path": str(image)})
        changed = await client.call_tool("get_profile", {"path": str(image), "changed_only": True})

    assert untouched.structured_content["adjustments"] == {} and untouched.structured_content["raw"] == {}
    view = changed.structured_content
    assert view["adjustments"]["film_negative"] == {
        "enabled": True, "color_space": "working", "red_ratio": 1.335, "blue_ratio": 0.759,
    }  # fmt: skip
    assert view["adjustments"]["exposure"] == {"enabled": False}
    assert view["raw"]["RAW Bayer"] == {"Method": "amaze"} and view["raw"]["RAW"] == {"CAEnabled": "false"}
    assert view["adjustments"]["sharpening"] == {"enabled": False}
    assert "local_contrast" not in view["adjustments"]
    assert tokens(changed) * 10 < tokens(whole)


async def test_changed_only_compares_with_the_default_not_the_sidecar(render, image):
    sidecar = PROFILE.read_text().replace("RedRatio=1.3600000000000001", "RedRatio=1.5")
    image.with_name(image.name + ".arp").write_text(sidecar)
    async with Client(render) as client:
        opened = await client.call_tool("open_image", {"path": str(image)})
        changed = await client.call_tool("get_profile", {"path": str(image), "changed_only": True})

    assert opened.structured_content["profile_from"] == "sidecar"
    assert changed.structured_content["adjustments"] == {"film_negative": {"red_ratio": 1.5}}


async def test_the_default_profile_is_resolved_once_per_opened_image(render, image, args_log):
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool("get_profile", {"path": str(image), "changed_only": True})
        resolved = default_runs(args_log)
        await client.call_tool("get_profile", {"path": str(image), "changed_only": True})
        await client.call_tool("get_profile", {"path": str(image)})

        assert default_runs(args_log) == resolved

        await client.call_tool("open_image", {"path": str(image)})
        await client.call_tool("get_profile", {"path": str(image), "changed_only": True})

    assert default_runs(args_log) > resolved


async def test_changed_only_is_render_failed_when_art_cli_cannot_resolve_the_default(tmp_path, image, monkeypatch):
    flaky = tmp_path / "flaky.py"
    flaky.write_text(
        "import os, runpy, sys\n"
        "if os.path.exists(os.environ['FLAKY_FLAG']) and '-d' in sys.argv:\n"
        "    sys.exit(3)\n"
        f"runpy.run_path({str(FAKE)!r}, run_name='__main__')\n"
    )
    flag = tmp_path / "fail"
    monkeypatch.setenv("FLAKY_FLAG", str(flag))
    config = tmp_path / "config"
    config.mkdir()
    server = build_render(ArtCli((sys.executable, str(flaky))), config, PreviewFolder(tmp_path / "p"))
    async with Client(server) as client:
        await client.call_tool("open_image", {"path": str(image)})
        flag.write_text("")
        result = await client.call_tool("get_profile", {"path": str(image), "changed_only": True})
        plain = await client.call_tool("get_profile", {"path": str(image)})

    assert result.is_error and "render_failed" in result.content[0].text
    assert not plain.is_error  # only the read that needs the default fails


async def test_edit_profile_reports_the_change_set_and_nothing_else(render, image):
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("edit_profile", edit_request(str(image)))

    assert not result.is_error, result.content
    out = result.structured_content
    assert out["changed"] == {
        "Exposure": {"Enabled": "false"},
        "ToneCurve": {"HistogramMatching": "false"},
        "Sharpening": {"Enabled": "false"},
        "Film Negative": {"Enabled": "true", "ColorSpace": "1", "RedRatio": "1.335", "BlueRatio": "0.759"},
        "RAW Bayer": {"Method": "amaze"},
        "RAW": {"CAEnabled": "false"},
    }
    assert out["implied"] == {} and out["drawn"] == {} and out["warnings"] == []
    assert out["profile"] is None


async def test_implied_changes_are_listed_apart_with_their_values(render, image):
    adjustments = {"local_contrast": {"contrast": 20}, "white_balance": {"temperature": 6500}}
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("edit_profile", {"path": str(image), "adjustments": adjustments})

    out = result.structured_content
    assert out["changed"] == {"Local Contrast": {"Contrast": "20"}, "White Balance": {"Temperature": "6500"}}
    assert out["implied"] == {"Local Contrast": {"Enabled": "true"}, "White Balance": {"Setting": "CustomTemp"}}


async def test_edit_profile_reads_back_the_curves_it_set(render, image):
    spline = {"type": "spline", "points": [[0.25, 0], [0.6, 0.6], [1, 1]]}
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool(
            "edit_profile", {"path": str(image), "adjustments": {"tone_curve": {"curve1": spline}}}
        )
        profile = await client.call_tool("get_profile", {"path": str(image), "groups": ["ToneCurve"]})

    out = result.structured_content
    assert list(out["drawn"]) == ["curve1"] and len(out["drawn"]["curve1"]) == 9
    assert out["drawn"]["curve1"] == profile.structured_content["adjustments"]["tone_curve"]["curve1"]["drawn"]


async def test_full_echo_returns_the_touched_groups_in_the_read_format(render, image):
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        result = await client.call_tool("edit_profile", edit_request(str(image), full=True))
        touched = ["Exposure", "ToneCurve", "Sharpening", "Film Negative", "RAW Bayer", "RAW"]
        profile = await client.call_tool("get_profile", {"path": str(image), "groups": touched})

    out = result.structured_content
    assert out["changed"]["Film Negative"]["RedRatio"] == "1.335"
    assert out["profile"] == profile.structured_content
    assert out["profile"]["adjustments"]["film_negative"]["red_ratio"] == 1.335


async def test_a_film_negative_edit_result_is_over_five_times_smaller_than_its_full_echo(render, image):
    async with Client(render) as client:
        await client.call_tool("open_image", {"path": str(image)})
        full = await client.call_tool("edit_profile", edit_request(str(image), full=True))
        await client.call_tool("open_image", {"path": str(image)})
        brief = await client.call_tool("edit_profile", edit_request(str(image)))

    assert tokens(full) > 5 * tokens(brief), (tokens(full), tokens(brief))


# -- Live ---------------------------------------------------------------------


@pytest.fixture
def art(tmp_path):
    fake = FakeArt(tmp_path / "config")
    yield fake
    fake.close()


@pytest.fixture
def live_image(tmp_path):
    img = tmp_path / "a.ARW"
    img.write_bytes(b"raw")  # art-cli, which resolves the default profile, reads it
    return str(img)


@pytest.fixture
def editor(art, live_image):
    editor = FakeEditor(art)
    editor.add(live_image, PROFILE.read_text())
    return editor


@pytest.fixture
def live(art, tmp_path, monkeypatch, args_log):
    monkeypatch.setenv("FAKE_DEFAULT_PROFILE", str(PROFILE))
    return build_live(
        ControlChannel(art.config_dir),
        cli=ArtCli((sys.executable, str(FAKE))),
        previews=PreviewFolder(tmp_path / "previews"),
    )


async def test_live_get_profile_of_chosen_groups_holds_only_those(live, editor, live_image):
    async with Client(live) as client:
        whole = await client.call_tool("get_profile", {"path": live_image})
        chosen = await client.call_tool("get_profile", {"path": live_image, "groups": ["Film Negative", "ToneCurve"]})

    assert not chosen.is_error, chosen.content
    view = chosen.structured_content
    assert set(view["adjustments"]) == {"film_negative", "tone_curve"} and set(view["raw"]) == {"ToneCurve"}
    assert view["history_position"] == 0
    assert tokens(chosen) * 10 < tokens(whole)


async def test_live_unknown_group_is_unknown_key_and_lists_the_valid_ones(live, editor, live_image):
    async with Client(live) as client:
        result = await client.call_tool("get_profile", {"path": live_image, "groups": ["Film negative"]})

    assert result.is_error
    text = result.content[0].text
    assert text.split("Error executing tool get_profile: ")[-1].startswith("unknown_key")
    assert "Film negative" in text and "Film Negative" in text and "RAW Bayer" in text


async def test_live_changed_only_holds_what_differs_from_arts_default_profile(live, editor, live_image):
    async with Client(live) as client:
        untouched = await client.call_tool("get_profile", {"path": live_image, "changed_only": True})
        await client.call_tool("edit_profile", edit_request(live_image))
        whole = await client.call_tool("get_profile", {"path": live_image})
        changed = await client.call_tool("get_profile", {"path": live_image, "changed_only": True})

    assert untouched.structured_content["adjustments"] == {} and untouched.structured_content["raw"] == {}
    view = changed.structured_content
    assert view["adjustments"]["film_negative"]["red_ratio"] == 1.335
    assert view["adjustments"]["exposure"] == {"enabled": False}
    assert view["raw"]["RAW Bayer"] == {"Method": "amaze"} and view["history_position"] == 1
    assert tokens(changed) * 10 < tokens(whole)


async def test_live_resolves_the_default_profile_once_per_image(live, editor, live_image, args_log):
    async with Client(live) as client:
        await client.call_tool("get_profile", {"path": live_image, "changed_only": True})
        await client.call_tool("get_profile", {"path": live_image, "changed_only": True})
        await client.call_tool("get_profile", {"path": live_image})

    assert default_runs(args_log) == 1


async def test_live_changed_only_without_art_cli_is_unsupported(art, editor, live_image):
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        result = await client.call_tool("get_profile", {"path": live_image, "changed_only": True})
        plain = await client.call_tool("get_profile", {"path": live_image})

    assert result.is_error
    text = result.content[0].text
    assert text.split("Error executing tool get_profile: ")[-1].startswith("unsupported") and "--art-dir" in text
    assert not plain.is_error


async def test_live_edit_profile_reports_the_change_set_and_the_history_position(live, editor, live_image):
    async with Client(live) as client:
        result = await client.call_tool("edit_profile", edit_request(live_image))

    assert not result.is_error, result.content
    out = result.structured_content
    assert out["changed"]["Film Negative"] == {
        "Enabled": "true", "ColorSpace": "1", "RedRatio": "1.335", "BlueRatio": "0.759",
    }  # fmt: skip
    assert out["implied"] == {} and out["warnings"] == [] and out["profile"] is None
    assert out["history_position"] == 1


async def test_live_edit_profile_reads_back_the_curves_and_lists_implied_changes(live, editor, live_image):
    spline = {"type": "spline", "points": [[0.25, 0], [0.6, 0.6], [1, 1]]}
    adjustments = {"tone_curve": {"curve1": spline}, "local_contrast": {"contrast": 20}}
    async with Client(live) as client:
        result = await client.call_tool("edit_profile", {"path": live_image, "adjustments": adjustments})
        profile = await client.call_tool("get_profile", {"path": live_image, "groups": ["ToneCurve"]})

    out = result.structured_content
    assert out["implied"] == {"Local Contrast": {"Enabled": "true"}, "ToneCurve": {"HistogramMatching": "false"}}
    assert out["drawn"]["curve1"] == profile.structured_content["adjustments"]["tone_curve"]["curve1"]["drawn"]


async def test_live_full_echo_and_its_size(live, editor, live_image):
    async with Client(live) as client:
        full = await client.call_tool("edit_profile", edit_request(live_image, full=True))
        await client.call_tool("undo", {"path": live_image})
        brief = await client.call_tool("edit_profile", edit_request(live_image))

    assert full.structured_content["profile"]["adjustments"]["film_negative"]["red_ratio"] == 1.335
    assert set(full.structured_content["profile"]["raw"]) >= {"RAW", "RAW Bayer"}
    assert tokens(full) > 5 * tokens(brief), (tokens(full), tokens(brief))
