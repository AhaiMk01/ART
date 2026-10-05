"""The typed film_negative adjustment: the profile seam (keys, read-back,
picker rule, estimate of ART's medians) and both servers with fakes.

Expected numbers are worked out by hand from ART's formula
(``src/engine/filmnegativeproc.cc``): out_c = mult_c * in_c^exp_c with
exp = -(G * (RedRatio, 1, BlueRatio)) and mult_c = RefOutput_c / RefInput_c^exp_c.
Throughout, G = 2, RedRatio = 1, BlueRatio = 0.5, so exp = (-2, -2, -1).
"""

import json
import sys
from pathlib import Path

import pytest
from fake_live_art import FakeArt, FakeEditor, answer
from mcp.client.client import Client

from art_mcp import keyfile
from art_mcp.filmnegative import (
    Estimate,
    SamplingUnsupported,
    current_estimate,
    grid_spots,
)
from art_mcp.live.channel import ControlChannel
from art_mcp.live.server import build_server as build_live
from art_mcp.preview import PreviewFolder
from art_mcp.profile import RawEdit, WorkingChanges, read_format
from art_mcp.render.artcli import ArtCli
from art_mcp.render.server import build_server as build_render
from art_mcp.schema import AdjustmentError, describe_adjustments, parse_adjustments

FAKE = Path(__file__).with_name("fake_artcli.py")
pytestmark = pytest.mark.anyio

# Luminance of (250, 4000, 250) with the Rec.709 weights, by hand:
# 0.2126729*250 + 0.7151521*4000 + 0.072175*250 = 53.168225 + 2860.6084 + 18.04375
SET_L = 2931.820375
# Medians (100, 100, 100) and ref_output unset (65535/24 = 2730.625): the new spot
# (200, 50, 400) renders (682.65625, 10922.5, 682.65625); its luminance by hand.
ESTIMATED_L = 8005.702011484375
# Medians (3000, 2000, 64) and the new spot (3000, 4000, 64): (2730.625, 682.65625, 2730.625).
SERVER_L = 1266.015847703125

BASE = """[Version]
Version=1045

[Film Negative]
Enabled=true
RedRatio=1
GreenExponent=2
BlueRatio=0.5
ColorSpace=1
RefInput={ref_in}
RefOutput={ref_out}
"""


def profile(ref_in="100;100;100", ref_out="1000;1000;1000", extra=""):
    return keyfile.loads(BASE.format(ref_in=ref_in, ref_out=ref_out) + extra)


def adj(**fields):
    return parse_adjustments({"film_negative": fields})


def values(result):
    return {e.key: e.value for e in result.changed}


def triple(text):
    return [float(v) for v in text.split(";")]


# -- schema and read-back ------------------------------------------------------


def test_describe_lists_the_fields_with_ranges_and_keys():
    tool = describe_adjustments().tools["film_negative"]

    assert tool.group == "Film Negative"
    assert {n: f.key for n, f in tool.fields.items()} == {
        "enabled": "Enabled", "color_space": "ColorSpace", "red_ratio": "RedRatio",
        "green_exponent": "GreenExponent", "blue_ratio": "BlueRatio",
        "ref_input": "RefInput", "ref_output": "RefOutput",
    }  # fmt: skip
    ranges = {n: (f.minimum, f.maximum) for n, f in tool.fields.items()}
    assert ranges["red_ratio"] == (0.3, 5) and ranges["blue_ratio"] == (0.3, 5)
    assert ranges["green_exponent"] == (0.3, 4)
    assert tool.fields["color_space"].enum == ["working", "input"]
    for needle in ("mult_c", "65535/24", "0.2126729", "ref_output", "Legacy"):
        assert needle in tool.description


def test_edits_write_the_stored_keys():
    changes = WorkingChanges(profile())

    result = changes.edit(
        adj(
            color_space="input", red_ratio=1.334, green_exponent=1.5, blue_ratio=0.737,
            ref_input=[8656.9248, 4344.5332, 2811.6162], ref_output=[10672, 10672, 10672],
        ),
        [],
    )  # fmt: skip

    assert values(result) == {
        "ColorSpace": "0", "RedRatio": "1.334", "GreenExponent": "1.5", "BlueRatio": "0.737",
        "RefInput": "8656.9248;4344.5332;2811.6162", "RefOutput": "10672;10672;10672",
    }  # fmt: skip
    assert result.implied == []


def test_get_profile_reads_it_back_typed_and_consumes_the_keys():
    view = read_format(profile("8656.9248;4344.5332;2811.6162", "10672.1363;10672.1363;10672.1363"))

    assert view.adjustments["film_negative"] == {
        "enabled": True, "color_space": "working", "red_ratio": 1.0, "green_exponent": 2.0,
        "blue_ratio": 0.5, "ref_input": [8656.9248, 4344.5332, 2811.6162],
        "ref_output": [10672.1363] * 3,
    }  # fmt: skip
    assert "Film Negative" not in view.raw


def test_a_typed_edit_round_trips_through_the_read_format():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_space="input", ref_input=[1, 2, 3]), [])

    typed = read_format(changes.profile).adjustments["film_negative"]

    assert typed["color_space"] == "input" and typed["ref_input"] == [1.0, 2.0, 3.0]


@pytest.mark.parametrize("extra", ["BackCompat=1\n", "BackCompat=2\nRedBase=5\n"])
def test_legacy_profiles_stay_raw(extra):
    legacy = profile(extra=extra)
    view = read_format(legacy)

    assert "film_negative" not in view.adjustments
    assert view.raw["Film Negative"]["RefInput"] == "100;100;100"
    assert view.raw["Film Negative"]["BackCompat"] == extra.split("\n")[0].split("=")[1]
    with pytest.raises(AdjustmentError, match="legacy"):
        WorkingChanges(legacy).edit(adj(ref_input=[1, 2, 3]), [])
    # turning it off is fine
    assert values(WorkingChanges(legacy).edit(adj(enabled=False), [])) == {"Enabled": "false"}


def test_a_value_outside_the_schema_stays_raw():
    odd = profile("100;100;100", "1000;1000;1000")
    odd["Film Negative"]["RefInput"] = "100;100"
    odd["Film Negative"]["RefOutput"] = "1;-2;3"

    view = read_format(odd)

    assert "ref_input" not in view.adjustments["film_negative"]
    assert "ref_output" not in view.adjustments["film_negative"]
    assert view.raw["Film Negative"] == {"RefInput": "100;100", "RefOutput": "1;-2;3"}


@pytest.mark.parametrize(
    "fields",
    [
        {"red_ratio": 0.29}, {"red_ratio": 5.1}, {"green_exponent": 4.1}, {"blue_ratio": 0.2},
        {"ref_input": [1, 2]}, {"ref_input": [1, 2, 3, 4]}, {"ref_output": [1, -1, 3]},
        {"color_space": "srgb"},
    ],
)  # fmt: skip
def test_out_of_range_values_are_refused(fields):
    with pytest.raises(AdjustmentError) as e:
        parse_adjustments({"film_negative": fields})
    assert e.value.code == "out_of_range"


def test_enabling_is_implied_on_a_disabled_tool():
    base = profile()
    base["Film Negative"]["Enabled"] = "false"

    result = WorkingChanges(base).edit(adj(red_ratio=1.3), [])

    assert [(e.key, e.value) for e in result.implied] == [("Enabled", "true")]


# -- the picker rule -------------------------------------------------------------


def test_new_ref_input_alone_keeps_brightness_by_the_rec709_luminance():
    changes = WorkingChanges(profile())

    # out = (250, 4000, 250) now: mult = (1000/100^-2, 1000/100^-2, 1000/100^-1)
    result = changes.edit(adj(ref_input=[200, 50, 400]), [])

    assert values(result)["RefInput"] == "200;50;400"
    assert triple(values(result)["RefOutput"]) == pytest.approx([SET_L] * 3)
    assert [e.key for e in result.implied] == ["RefOutput"]
    assert result.warnings == []


def test_an_explicit_ref_output_wins_and_implies_nothing():
    changes = WorkingChanges(profile())

    result = changes.edit(adj(ref_input=[200, 50, 400], ref_output=[900, 800, 700]), [])

    assert values(result)["RefOutput"] == "900;800;700" and result.implied == []


def test_a_ref_input_equal_to_the_stored_one_is_no_change():
    changes = WorkingChanges(profile("100;100;100"))

    result = changes.edit(adj(ref_input=[100, 100, 100]), [])

    assert result.changed == [] and result.implied == []


def test_the_rule_uses_the_exponents_as_they_are_before_the_request():
    """L comes from the current exponents; a ratio changed in the same request
    does not alter it (the new reference maps to grey L whatever they are)."""
    changes = WorkingChanges(profile())

    result = changes.edit(adj(ref_input=[200, 50, 400], red_ratio=3, green_exponent=1), [])

    assert triple(values(result)["RefOutput"]) == pytest.approx([SET_L] * 3)
    assert values(result)["RedRatio"] == "3"


def test_a_clipped_rendering_is_clipped_in_the_luminance():
    changes = WorkingChanges(profile())

    # new spot (1, 1, 1): out = (1e7, 1e7, 1e5), every channel clips to 65535, and
    # the weights sum to 1
    result = changes.edit(adj(ref_input=[1, 1, 1]), [])

    assert triple(values(result)["RefOutput"]) == pytest.approx([65535] * 3)


def test_an_unset_ref_input_uses_the_estimated_medians_and_warns():
    changes = WorkingChanges(profile("0;0;0", "0;0;0"))

    result = changes.edit(adj(ref_input=[200, 50, 400]), [], Estimate((100.0, 100.0, 100.0)))

    assert triple(values(result)["RefOutput"]) == pytest.approx([ESTIMATED_L] * 3)
    [warning] = result.warnings
    assert "estimat" in warning and "median of block means" in warning
    assert [e.key for e in result.implied] == ["RefOutput"]


def test_an_unset_ref_input_without_sampling_falls_back_to_grey_65535_24():
    for estimate in (None, Estimate(None, "needs an ART build with spot sampling")):
        changes = WorkingChanges(profile("0;0;0", "0;0;0"))

        result = changes.edit(adj(ref_input=[200, 50, 400]), [], estimate)

        assert values(result)["RefOutput"] == "2730.625;2730.625;2730.625"
        [warning] = result.warnings
        assert "brightness may change" in warning


def test_no_picker_when_ref_input_is_not_given_or_is_unset():
    changes = WorkingChanges(profile())

    assert changes.edit(adj(red_ratio=1.2), []).implied == []
    assert changes.edit(adj(ref_input=[0, 0, 0]), []).implied == []


def test_a_raw_ref_output_overrides_the_computed_one_and_its_note():
    changes = WorkingChanges(profile("0;0;0", "0;0;0"))

    result = changes.edit(
        adj(ref_input=[200, 50, 400]),
        [RawEdit(group="Film Negative", key="RefOutput", value="5;5;5")],
        Estimate(None, "x"),
    )

    assert values(result)["RefOutput"] == "5;5;5" and result.implied == [] and result.warnings == []


# -- the estimate ------------------------------------------------------------------


def test_the_grid_is_64_spots_in_the_central_60_percent():
    spots = grid_spots(6000, 4000)

    assert len(spots) == 64 and len(set(spots)) == 64
    assert {x for x, _ in spots} == {1425 + 450 * i for i in range(8)}
    assert {y for _, y in spots} == {950 + 300 * j for j in range(8)}
    assert min(x for x, _ in spots) > 1200 and max(x for x, _ in spots) < 4800


def fake_sampler(calls):
    def sample(spots, size, space):
        calls.append((len(spots), size, space))
        return [(float(x), float(y), float(size)) for x, y in spots]

    return sample


def test_the_estimate_is_the_median_of_the_block_means_in_batches_of_16():
    calls = []
    entries = profile("0;0;0")["Film Negative"]
    tool = adj(ref_input=[1, 2, 3]).film_negative

    estimate = current_estimate(tool, entries, lambda: (6000, 4000), fake_sampler(calls))

    # x occurs 8 times per grid column: the 32nd/33rd of 64 sorted are 2775+450... by hand:
    # columns 1425, 1875, 2325, 2775, 3225, ...: median = (2775 + 3225) / 2 = 3000;
    # rows 950, 1250, 1550, 1850, 2150, ...: median = (1850 + 2150) / 2 = 2000; b is the size.
    assert estimate == Estimate((3000.0, 2000.0, 64.0))
    assert calls == [(16, 64, "working")] * 4


def test_the_estimate_is_sampled_in_the_profiles_color_space():
    calls = []
    base = profile("0;0;0")["Film Negative"] | {"ColorSpace": "0"}

    current_estimate(adj(ref_input=[1, 2, 3]).film_negative, base, lambda: (6000, 4000), fake_sampler(calls))

    assert {space for _, _, space in calls} == {"input"}


@pytest.mark.parametrize(
    "fields, ref_in",
    [({"red_ratio": 1.2}, "0;0;0"), ({"ref_input": [1, 2, 3]}, "100;100;100"),
     ({"ref_input": [1, 2, 3], "ref_output": [1, 1, 1]}, "0;0;0")],
)  # fmt: skip
def test_no_sampling_when_the_request_does_not_need_the_estimate(fields, ref_in):
    calls = []

    result = current_estimate(
        adj(**fields).film_negative, profile(ref_in)["Film Negative"],
        lambda: (6000, 4000), fake_sampler(calls),
    )  # fmt: skip

    assert result is None and calls == []


def test_unsupported_sampling_is_an_estimate_without_medians():
    def unsupported(spots, size, space):
        raise SamplingUnsupported("no -x")

    estimate = current_estimate(
        adj(ref_input=[1, 2, 3]).film_negative, profile("0;0;0")["Film Negative"],
        lambda: (6000, 4000), unsupported,
    )  # fmt: skip

    assert estimate == Estimate(None, "no -x")


# -- Render server (fake art-cli) ----------------------------------------------------


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def image(tmp_path):
    img = tmp_path / "photos" / "IMG_1.ARW"
    img.parent.mkdir()
    img.write_bytes(b"raw")
    return img


def render_server(tmp_path, monkeypatch, image, ref_in="0;0;0", ref_out="0;0;0", extra=""):
    log = tmp_path / "args.log"
    monkeypatch.setenv("FAKE_ARGS_LOG", str(log))
    config = tmp_path / "config"
    config.mkdir()
    image.with_name(image.name + ".arp").write_text(BASE.format(ref_in=ref_in, ref_out=ref_out) + extra)
    server = build_render(ArtCli((sys.executable, str(FAKE))), config, PreviewFolder(tmp_path / "previews"))
    return server, log


def sampling_calls(log):
    runs = [json.loads(line) for line in log.read_text().splitlines()]
    return [r[r.index("-x") + 1].split(",")[:2] for r in runs if "-x" in r]


async def edit_ref_input(client, image, ref_input, **more):
    await client.call_tool("open_image", {"path": str(image)})
    return await client.call_tool(
        "edit_profile",
        {"path": str(image), "adjustments": {"film_negative": {"ref_input": ref_input, **more}}},
    )


async def test_render_estimates_the_medians_through_art_cli_x(tmp_path, monkeypatch, image):
    server, log = render_server(tmp_path, monkeypatch, image)

    async with Client(server) as client:
        result = await edit_ref_input(client, image, [3000, 4000, 64])
        profile_after = await client.call_tool("get_profile", {"path": str(image)})

    assert not result.is_error, result.content
    out = result.structured_content
    assert triple({e["key"]: e["value"] for e in out["implied"]}["RefOutput"]) == pytest.approx([SERVER_L] * 3)
    assert len(out["warnings"]) == 1 and "estimat" in out["warnings"][0]
    assert sampling_calls(log) == [["64", "working"]] * 4
    typed = profile_after.structured_content["adjustments"]["film_negative"]
    assert typed["ref_input"] == [3000.0, 4000.0, 64.0]
    assert typed["ref_output"] == pytest.approx([SERVER_L] * 3)


async def test_render_samples_in_the_input_space_when_the_profile_says_so(tmp_path, monkeypatch, image):
    server, log = render_server(tmp_path, monkeypatch, image)
    sidecar = image.with_name(image.name + ".arp")
    sidecar.write_text(sidecar.read_text().replace("ColorSpace=1", "ColorSpace=0"))

    async with Client(server) as client:
        await edit_ref_input(client, image, [3000, 4000, 64])

    assert {space for _, space in sampling_calls(log)} == {"input"}


async def test_render_with_a_set_reference_does_not_sample(tmp_path, monkeypatch, image):
    server, log = render_server(tmp_path, monkeypatch, image, "100;100;100", "1000;1000;1000")

    async with Client(server) as client:
        result = await edit_ref_input(client, image, [200, 50, 400])

    out = result.structured_content
    assert triple({e["key"]: e["value"] for e in out["implied"]}["RefOutput"]) == pytest.approx([SET_L] * 3)
    assert out["warnings"] == [] and sampling_calls(log) == []


async def test_render_falls_back_to_grey_when_art_cli_cannot_sample(tmp_path, monkeypatch, image):
    server, _ = render_server(tmp_path, monkeypatch, image)
    monkeypatch.setenv("FAKE_SPOTS", "release")

    async with Client(server) as client:
        result = await edit_ref_input(client, image, [3000, 4000, 64])

    assert not result.is_error, result.content
    out = result.structured_content
    assert {e["key"]: e["value"] for e in out["implied"]}["RefOutput"] == "2730.625;2730.625;2730.625"
    assert "brightness may change" in out["warnings"][0]


async def test_render_with_an_explicit_ref_output_does_not_sample(tmp_path, monkeypatch, image):
    server, log = render_server(tmp_path, monkeypatch, image)

    async with Client(server) as client:
        result = await edit_ref_input(client, image, [3000, 4000, 64], ref_output=[900, 900, 900])

    assert result.structured_content["implied"] == [] and sampling_calls(log) == []


# -- Live server (fake ART) ------------------------------------------------------------


def sample_spots_reply(req):
    args = req["args"]
    spots = [
        {"x": x, "y": y, "avg": [x, y, args["size"]], "max": [x, y, args["size"]]}
        for x, y in args["spots"]
    ]
    return answer({"width": 6000, "height": 4000, "spots": spots})(req)


@pytest.fixture
def art(tmp_path):
    fake = FakeArt(tmp_path / "config")
    yield fake
    fake.close()


def live_editor(art, tmp_path, ref_in, ref_out):
    editor = FakeEditor(art)
    editor.add(str(tmp_path / "a.ARW"), BASE.format(ref_in=ref_in, ref_out=ref_out))
    return editor, str(tmp_path / "a.ARW")


async def live_edit(art, path, ref_input, **more):
    async with Client(build_live(ControlChannel(art.config_dir))) as client:
        return await client.call_tool(
            "edit_profile",
            {"path": path, "adjustments": {"film_negative": {"ref_input": ref_input, **more}}},
        )


async def test_live_estimates_the_medians_through_the_channels_sample_spots(art, tmp_path):
    editor, path = live_editor(art, tmp_path, "0;0;0", "0;0;0")
    art.ops["sample_spots"] = sample_spots_reply

    result = await live_edit(art, path, [3000, 4000, 64])

    assert not result.is_error, result.content
    out = result.structured_content
    assert "estimat" in out["warnings"][0]
    [applied] = editor.applied
    assert triple(keyfile.loads(applied["profile"])["Film Negative"]["RefOutput"]) == pytest.approx([SERVER_L] * 3)
    asked = [json.loads(m) for m in art.received if b"sample_spots" in m]
    assert len(asked) == 4 and {a["args"]["space"] for a in asked} == {"working"}
    assert all(a["args"]["size"] == 64 and len(a["args"]["spots"]) == 16 for a in asked)


async def test_live_uses_the_editors_current_reference_without_sampling(art, tmp_path):
    editor, path = live_editor(art, tmp_path, "100;100;100", "1000;1000;1000")
    art.ops["sample_spots"] = sample_spots_reply

    result = await live_edit(art, path, [200, 50, 400])

    assert result.structured_content["warnings"] == []
    [applied] = editor.applied
    assert triple(keyfile.loads(applied["profile"])["Film Negative"]["RefOutput"]) == pytest.approx([SET_L] * 3)
    assert not [m for m in art.received if b"sample_spots" in m]


async def test_live_falls_back_when_the_editor_cannot_sample(art, tmp_path):
    editor, path = live_editor(art, tmp_path, "0;0;0", "0;0;0")  # no sample_spots op: unknown_op

    result = await live_edit(art, path, [3000, 4000, 64])

    assert not result.is_error, result.content
    assert "brightness may change" in result.structured_content["warnings"][0]
    [applied] = editor.applied
    assert keyfile.loads(applied["profile"])["Film Negative"]["RefOutput"] == "2730.625;2730.625;2730.625"
