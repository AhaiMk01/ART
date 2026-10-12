"""The typed film_negative adjustment: the profile seam (keys, read-back,
picker rule, estimate of ART's medians) and both servers with fakes.

Expected numbers are worked out by hand from ART's formula
(``src/engine/filmnegativeproc.cc``): out_c = mult_c * in_c^exp_c with
exp = -(G * (RedRatio, 1, BlueRatio)) and mult_c = RefOutput_c / RefInput_c^exp_c.
Throughout, G = 2, RedRatio = 1, BlueRatio = 0.5, so exp = (-2, -2, -1).

The pure-math tests (reference matrix, black offset, input gamma, density
negative) are reference-formula checks on literals: they do not call the
engine. Engine coverage lives in test_integration_film_negative.py.
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
Version=1055

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
    ranges = {n: (f.minimum, f.maximum) for n, f in tool.fields.items()}
    assert ranges["red_ratio"] == (0.3, 5) and ranges["blue_ratio"] == (0.3, 5)
    assert ranges["green_exponent"] == (0.3, 4)
    assert ranges["density_gamma"] == (0.1, 4.0)
    assert ranges["density_dmax"] == (0.0, 4.8)
    assert ranges["output_black_offset"] == (0.0, 0.05)
    assert ranges["input_gamma"] == (0.5, 2.8)
    assert tool.fields["method"].enum == ["power_law", "density", "namicolor"]
    assert tool.fields["film_type"].enum == ["negative", "reversal"]
    assert tool.fields["color_space"].enum == ["working", "input"]
    assert tool.fields["matrix_preset"].enum == ["identity", "status_m_reference", "custom"]
    for removed in (
        "target_mode", "cineon_primaries", "paper_curve", "paper_basis",
        "cineon_lut", "cineon_lut_stage", "cineon_lut_sha256",
    ):  # fmt: skip
        assert removed not in tool.fields
    assert ranges["namicolor_input_gain"] == (0.0, 2.0)
    assert ranges["namicolor_master_gain"] == (-0.5, 0.5)
    assert ranges["namicolor_master_shift"] == (-1.0, 1.0)
    assert tool.fields["cineon_reference_white"].minimum == 1e-6
    assert tool.fields["cineon_reference_white"].maximum == 1e6
    for needle in ("sample_spots", "NamiColor", "Legacy", "skill"):
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

    typed = view.adjustments["film_negative"]
    assert typed["ref_input"] == [8656.9248, 4344.5332, 2811.6162]
    assert typed["ref_output"] == [10672.1363] * 3
    assert "Film Negative" not in view.raw


def test_a_typed_edit_round_trips_through_the_read_format():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_space="input", ref_input=[1, 2, 3]), [])

    typed = read_format(changes.profile).adjustments["film_negative"]

    assert typed["color_space"] == "input" and typed["ref_input"] == [1.0, 2.0, 3.0]


@pytest.mark.parametrize("method", ["namicolor", "2"])
def test_namicolor_effective_settings_round_trip_without_reference_inference(method):
    changes = WorkingChanges(profile("0;0;0", "0;0;0", extra=f"Method={method}\n"))
    fields = {
        "namicolor_input_gain": 1.2,
        "namicolor_master_gain": 0.1,
        "namicolor_master_shift": -0.2,
        "namicolor_black": [-0.1, 0.0, 0.1],
        "namicolor_gain": [0.2, -0.2, 0.0],
        "namicolor_shift": [0.1, 0.0, -0.1],
        "namicolor_fit_base": True,
        "fit_base_anchor": "code95",
        "ref_input": [100, 200, 300],
    }
    result = changes.edit(adj(**fields), [])
    typed = read_format(changes.profile).adjustments["film_negative"]

    assert typed["method"] == "namicolor"
    assert {name: typed[name] for name in fields} == fields
    assert typed["ref_output"] == [0.0, 0.0, 0.0]
    assert result.implied == [] and result.warnings == []
    assert "Film Negative" not in read_format(changes.profile).raw
    # Consumers may send get_profile's complete typed result back unchanged.
    changes.edit(adj(**typed), [])
    assert read_format(changes.profile).adjustments["film_negative"] == typed
    assert changes.edit(adj(**typed), []).changed == []


@pytest.mark.parametrize(
    "stored, fields",
    [
        ("", {"method": "namicolor", "namicolor_gain": [1, 0, 0]}),
        ("NamiColorMasterGain=0.5\n", {"namicolor_black": [-0.5, 0, 0]}),
        ("NamiColorGain=0.75;0;0\n", {"namicolor_master_gain": 0.5}),
        ("NamiColorBlack=-0.25;0;0\n", {"namicolor_gain": [0.75, 0, 0]}),
    ],
)
def test_namicolor_nonpositive_coupled_denominator_rejects_the_entire_edit(stored, fields):
    changes = WorkingChanges(profile(extra="Method=namicolor\n" + stored))
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="denominator") as rejected:
        changes.edit(adj(**fields), [])
    assert rejected.value.code == "out_of_range"
    assert keyfile.dumps(changes.profile) == before
    assert changes.partial_profile() == {}


@pytest.mark.parametrize(
    "stored",
    ["NamiColorMasterShift=nan\n", "NamiColorGain=0;inf;0\n", "NamiColorBlack=bad\n"],
)
def test_entering_namicolor_rejects_nonfinite_or_malformed_inactive_settings(stored):
    changes = WorkingChanges(profile(extra=stored))
    with pytest.raises(AdjustmentError, match="finite"):
        changes.edit(adj(method="namicolor"), [])
    assert "Method" not in changes.profile["Film Negative"]


@pytest.mark.parametrize(
    "current, requested",
    [
        ("power_law", "namicolor"),
        ("namicolor", "power_law"),
        ("density", "namicolor"),
        ("namicolor", "density"),
        ("density", "density"),
        ("namicolor", None),
    ],
)
def test_only_power_law_to_power_law_uses_reference_picker(current, requested):
    entries = profile("0;0;0", "1000;1000;1000", extra=f"Method={current}\n")
    fields = {"ref_input": [200, 50, 400]}
    if requested is not None:
        fields["method"] = requested
    tool = adj(**fields)
    calls = []
    assert (
        current_estimate(
            tool.film_negative,
            entries["Film Negative"],
            lambda: (6000, 4000),
            fake_sampler(calls),
        )
        is None
    )
    changes = WorkingChanges(entries)
    result = changes.edit(tool, [])
    assert calls == [] and result.implied == [] and result.warnings == []
    assert changes.profile["Film Negative"]["RefOutput"] == "1000;1000;1000"


def test_namicolor_transition_preserves_inactive_density_settings():
    changes = WorkingChanges(
        profile(extra="Method=density\nRGBGains=0.5;-0.5;1\nOutputBlackOffset=0.01\n")
    )
    changes.edit(adj(method="namicolor"), [])
    typed = read_format(changes.profile).adjustments["film_negative"]
    assert typed["rgb_gains"] == [0.5, -0.5, 1]
    assert typed["output_black_offset"] == 0.01
    changes.edit(adj(method="density"), [])
    assert read_format(changes.profile).adjustments["film_negative"]["rgb_gains"] == [0.5, -0.5, 1]


def test_namicolor_mask_opt_in_is_refused_below_1055():
    basis = '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}'
    old = profile(extra=f"Method=namicolor\nMatrixBasis={basis}\n")
    old["Version"]["Version"] = "1054"
    changes = WorkingChanges(old)
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="Version 1054"):
        changes.edit(adj(matrix_preset="custom", matrix=[1, 0.2, 0, 0, 1, 0, 0, 0, 1], matrix_basis=basis), [])
    assert keyfile.dumps(changes.profile) == before


def test_namicolor_coupled_edit_can_repair_a_stored_denominator():
    changes = WorkingChanges(profile(extra=("Method=namicolor\nNamiColorGain=0.75;0;0\nNamiColorMasterGain=0.5\n")))
    changes.edit(adj(namicolor_black=[0.5, 0, 0]), [])
    assert read_format(changes.profile).adjustments["film_negative"]["namicolor_black"] == [0.5, 0, 0]


@pytest.mark.parametrize("backcompat", ["1", "2"])
def test_legacy_power_law_cannot_be_silently_reinterpreted_as_namicolor(backcompat):
    changes = WorkingChanges(profile(extra=f"BackCompat={backcompat}\n"))
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="legacy"):
        changes.edit(adj(method="namicolor"), [])
    assert keyfile.dumps(changes.profile) == before


@pytest.mark.parametrize("method", ["power_law", "density"])
def test_namicolor_settings_remain_inactive_in_old_methods(method):
    changes = WorkingChanges(profile(extra=f"Method={method}\n"))
    changes.edit(adj(namicolor_gain=[1, 1, 1]), [])
    assert read_format(changes.profile).adjustments["film_negative"]["method"] == method
    with pytest.raises(AdjustmentError, match="denominator"):
        changes.edit(adj(method="namicolor"), [])


@pytest.mark.parametrize(
    "fields",
    [
        {"namicolor_input_gain": float("inf")},
        {"namicolor_master_gain": float("nan")},
        {"namicolor_master_shift": 1.1},
        {"namicolor_black": [-0.6, 0, 0]},
        {"namicolor_gain": [0, 0]},
        {"namicolor_shift": [0, 0, float("nan")]},
    ],
)
def test_invalid_namicolor_typed_values_are_rejected(fields):
    with pytest.raises(AdjustmentError):
        adj(method="namicolor", **fields)


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
        {"density_gamma": 0.05}, {"density_gamma": 4.1},
        {"density_dmax": -0.1}, {"density_dmax": 4.9},
        {"input_gamma": 0.49}, {"input_gamma": 2.81},
        {"method": "unknown"}, {"film_type": "unknown"},
        {"rgb_gains": [-3.1, 0, 0]}, {"rgb_gains": [0, 3.1, 0]},
        {"channel_gamma": [0.4, 1, 1]}, {"channel_gamma": [1, 2.1, 1]},
        {"rgb_gains": [1, 2]}, {"channel_gamma": [1, 2, 3, 4]},
        {"output_black_offset": -0.001}, {"output_black_offset": 0.051},
        {"matrix": [1, 0, 0, 0, 1, 0, 0, 0]},
        {"matrix": [11, 0, 0, 0, 1, 0, 0, 0, 1]},
        {"matrix_preset": "status_m"},
    ],
)  # fmt: skip
def test_out_of_range_values_are_refused(fields):
    with pytest.raises(AdjustmentError) as e:
        parse_adjustments({"film_negative": fields})
    assert e.value.code == "out_of_range"


def test_density_fields_round_trip():
    changes = WorkingChanges(profile())
    result = changes.edit(
        adj(
            method="density",
            film_type="reversal",
            density_gamma=1.5,
            density_dmax=3.0,
            rgb_gains=[-0.5, 0.2, 1.0],
            channel_gamma=[0.8, 1.2, 1.5],
        ),
        [],
    )
    assert values(result) == {
        "Method": "density",
        "FilmType": "reversal",
        "DensityGamma": "1.5",
        "DensityDmax": "3",
        "RGBGains": "-0.5;0.2;1",
        "ChannelGamma": "0.8;1.2;1.5",
    }
    typed = read_format(changes.profile).adjustments["film_negative"]
    assert typed["method"] == "density"
    assert typed["film_type"] == "reversal"
    assert typed["density_gamma"] == 1.5
    assert typed["density_dmax"] == 3.0
    assert typed["rgb_gains"] == [-0.5, 0.2, 1.0]
    assert typed["channel_gamma"] == [0.8, 1.2, 1.5]


def test_custom_matrix_round_trips():
    basis = '{"v":1,"color_space":"working","profile":"ProPhoto"}'
    changes = WorkingChanges(profile())
    result = changes.edit(
        adj(
            matrix_preset="custom",
            matrix=[1.1, 0.2, 0, 0, 0.9, 0, 0, 0, 1],
            matrix_basis=basis,
            calibration_note="Portra, tungsten, Epson",
        ),
        [],
    )
    assert values(result)["MatrixPreset"] == "custom"
    assert values(result)["Matrix"] == "1.1;0.2;0;0;0.9;0;0;0;1"
    assert values(result)["MatrixBasis"] == basis
    assert values(result)["CalibrationNote"] == "Portra, tungsten, Epson"
    typed = read_format(changes.profile).adjustments["film_negative"]
    assert typed["matrix_preset"] == "custom"
    assert typed["matrix"] == [1.1, 0.2, 0.0, 0.0, 0.9, 0.0, 0.0, 0.0, 1.0]
    assert typed["matrix_basis"] == basis
    assert typed["calibration_note"] == "Portra, tungsten, Epson"


@pytest.mark.parametrize("method", ["power_law", "density", "namicolor"])
def test_matrix_coefficients_are_refused_unless_preset_is_custom(method):
    with pytest.raises(AdjustmentError, match="custom") as e:
        WorkingChanges(profile(extra=f"Method={method}\n")).edit(adj(matrix=[0.2, 0, 0, 0, 1, 0, 0, 0, 1]), [])
    assert e.value.code == "out_of_range"
    with pytest.raises(AdjustmentError, match="custom"):
        WorkingChanges(profile(extra=f"Method={method}\n")).edit(
            adj(matrix_preset="status_m_reference", matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1]),
            [],
        )
    # the preset's own coefficients are not a coefficient change
    result = WorkingChanges(profile(extra=f"Method={method}\n")).edit(adj(matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1]), [])
    assert "Matrix" not in values(result)


def test_reference_matrix_is_row_vector_times_rows():
    # Independent of the engine: R displacement (1, 0, 0) times the DiVERE
    # rows is the first column of the row-major matrix.
    rows = (
        (1.0197, 0.0317, 0.0091),
        (-0.0052, 0.8933, 0.0521),
        (0.0131, -0.0011, 0.9712),
    )
    delta = (1.0, 0.0, 0.0)
    got = tuple(sum(rows[i][j] * delta[j] for j in range(3)) for i in range(3))
    assert got == (1.0197, -0.0052, 0.0131)
    # Identity leaves channel slopes unmixed: C_i uses only A_i.
    P = 1.6
    A = (1.0, 2.0, 3.0)
    h = (1.5, 0.5, 2.0)
    g = (0.1, 0.0, -0.2)
    C = tuple(P + h[i] * (A[i] - P) - g[i] for i in range(3))
    assert C == (P + 1.5 * (1.0 - P) - 0.1, P + 0.5 * (2.0 - P), P + 2.0 * (3.0 - P) + 0.2)


def test_output_black_offset_round_trips():
    changes = WorkingChanges(profile())
    result = changes.edit(adj(output_black_offset=0.02), [])
    assert values(result) == {"OutputBlackOffset": "0.02"}
    typed = read_format(changes.profile).adjustments["film_negative"]
    assert typed["output_black_offset"] == 0.02


def test_output_black_offset_math():
    # Hand literals for negative density, Dmax 2.5, gamma 1, identity matrix,
    # unit slope, zero gain, T=0.1: L = 10^(-2.5) / 0.1 = 0.0316227766.
    # 0.0316227766 * 65535 = 1966.05 + 106.34866401 = 2072.39866401.
    # Offset 0.01: 0.0216227766 * 65535 = 1417.04866401. Offset 0.05 floors at 0.
    linear = 0.0316227766
    assert round(max(0.0, linear - 0.0) * 65535.0, 5) == 2072.39866
    assert round(max(0.0, linear - 0.01) * 65535.0, 5) == 1417.04866
    assert max(0.0, linear - 0.05) == 0.0
    # Above full scale is kept: 1.5 * 65535 = 98302.5, not clipped to 65535.
    assert max(0.0, 1.5 - 0.0) * 65535.0 == 98302.5


def test_input_gamma_round_trips_and_defaults_to_one():
    changes = WorkingChanges(profile())
    result = changes.edit(adj(method="density", input_gamma=1.8), [])
    assert values(result)["InputGamma"] == "1.8"
    assert values(result)["Method"] == "density"
    typed = read_format(changes.profile).adjustments["film_negative"]
    assert typed["input_gamma"] == 1.8
    # a profile that omits the key keeps the unity default
    assert read_format(profile()).adjustments["film_negative"]["input_gamma"] == 1.0


def test_integer_enum_sidecars_still_read_as_names():
    stored = profile(extra="Method=1\nFilmType=1\nMatrixPreset=2\n")
    typed = read_format(stored).adjustments["film_negative"]
    assert typed["method"] == "density"
    assert typed["film_type"] == "reversal"
    assert typed["matrix_preset"] == "custom"


def test_input_gamma_linearizes_a_power_encoded_scan_once():
    """sign(x)*abs(x)^InputGamma before density inversion.

    A gamma-1.8 encoded mid grey (linear 0.18 stored as 0.18**(1/1.8)) must
    come back to 0.18. Unity gamma leaves that encoded value unchanged.
    Expected numbers are literals, not the implementation under test.
    """
    import math

    encoded = 0.385711424751  # 0.18 ** (1/1.8)
    linear = math.copysign(abs(encoded) ** 1.8, encoded)
    assert math.isclose(linear, 0.18, rel_tol=1e-9)
    assert math.copysign(abs(-encoded) ** 1.8, -encoded) == -linear
    assert math.copysign(abs(encoded) ** 1.0, encoded) == encoded

    dmax = 2.5
    p = 0.7
    anchor = 4.1 - dmax
    Tc = linear
    Dc = -math.log10(Tc)
    Ac = dmax - p - 1.0 * (Dc - p)
    Ci = anchor + 1.0 * (Ac - anchor)
    Lc = 10.0 ** (-Ci)
    assert math.isclose(Lc, (10.0 ** (-dmax)) / Tc, rel_tol=1e-9)
    assert math.isclose(65535.0 * Lc, 1151.33259144, rel_tol=1e-7)


def test_density_negative_math():
    import math

    dmax = 2.5
    gamma = 1.0
    p = 0.7
    anchor = 4.1 - dmax
    expected_outputs = []
    for Tc in [0.01, 0.1, 1.0]:
        Dc = -math.log10(Tc)
        Ac = dmax - p - gamma * (Dc - p)
        Ci = anchor + 1.0 * (Ac - anchor) - 0.0
        expected_outputs.append(10.0 ** (-Ci))  # checked against literals below

    assert math.isclose(expected_outputs[0], 0.316227766, rel_tol=1e-6)
    assert math.isclose(expected_outputs[1], 0.031622777, rel_tol=1e-6)
    assert math.isclose(expected_outputs[2], 0.003162278, rel_tol=1e-6)


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
    assert triple(out["implied"]["Film Negative"]["RefOutput"]) == pytest.approx([SERVER_L] * 3)
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
    assert triple(out["implied"]["Film Negative"]["RefOutput"]) == pytest.approx([SET_L] * 3)
    assert out["warnings"] == [] and sampling_calls(log) == []


async def test_render_falls_back_to_grey_when_art_cli_cannot_sample(tmp_path, monkeypatch, image):
    server, _ = render_server(tmp_path, monkeypatch, image)
    monkeypatch.setenv("FAKE_SPOTS", "release")

    async with Client(server) as client:
        result = await edit_ref_input(client, image, [3000, 4000, 64])

    assert not result.is_error, result.content
    out = result.structured_content
    assert out["implied"]["Film Negative"]["RefOutput"] == "2730.625;2730.625;2730.625"
    assert "brightness may change" in out["warnings"][0]


async def test_render_with_an_explicit_ref_output_does_not_sample(tmp_path, monkeypatch, image):
    server, log = render_server(tmp_path, monkeypatch, image)

    async with Client(server) as client:
        result = await edit_ref_input(client, image, [3000, 4000, 64], ref_output=[900, 900, 900])

    assert result.structured_content["implied"] == {} and sampling_calls(log) == []


# -- Live server (fake ART) ------------------------------------------------------------


def sample_spots_reply(req):
    args = req["args"]
    spots = [{"x": x, "y": y, "avg": [x, y, args["size"]], "max": [x, y, args["size"]]} for x, y in args["spots"]]
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


def test_film_base_pick_sets_all_three_gains_to_c_minus_four():
    # Identity, gamma 1, Dmax 2.5, slope 1: Tc=0.1 -> C=1.5 -> gains=-2.5.
    changes = WorkingChanges(profile())
    sample = 0.1 * 65535
    result = changes.edit(adj(method="density", film_base_sample=[sample, sample, sample]), [])

    assert values(result)["RGBGains"] == "-2.5;-2.5;-2.5"
    assert "DensityDmax" not in values(result)
    assert "DensityGamma" not in values(result)
    assert "Matrix" not in values(result)
    assert "ChannelGamma" not in values(result)
    assert changes.profile["Film Negative"]["RGBGains"] == "-2.5;-2.5;-2.5"


def test_film_base_pick_refuses_reversal_and_an_out_of_range_gain():
    reversal = WorkingChanges(profile())
    with pytest.raises(AdjustmentError, match="reversal") as denied:
        reversal.edit(
            adj(method="density", film_type="reversal", film_base_sample=[6553.5] * 3),
            [],
        )
    assert denied.value.code == "out_of_range"
    assert "RGBGains" not in reversal.profile["Film Negative"]

    # Green is near the floor, so its gain falls outside -3..3. Nothing is written.
    dark = WorkingChanges(profile())
    with pytest.raises(AdjustmentError, match="outside -3"):
        dark.edit(adj(method="density", film_base_sample=[65535, 1, 65535]), [])
    assert "RGBGains" not in dark.profile["Film Negative"]
    assert dark.profile["Film Negative"]["RedRatio"] == "1"


@pytest.mark.parametrize("backend", ["render", "live"])
async def test_namicolor_consumer_edit_get_describe_and_atomic_rejection(
    backend, tmp_path, monkeypatch, image, request
):
    if backend == "render":
        server, log = render_server(tmp_path, monkeypatch, image)
        path = str(image)
    else:
        art = request.getfixturevalue("art")
        editor, path = live_editor(art, tmp_path, "0;0;0", "0;0;0")
        server = build_live(ControlChannel(art.config_dir))
    fields = {
        "method": "namicolor",
        "film_type": "reversal",
        "namicolor_input_gain": 0.9,
        "namicolor_master_gain": 0.2,
        "namicolor_master_shift": -0.1,
        "namicolor_black": [-0.1, 0.2, 0],
        "namicolor_gain": [0.1, 0, -0.2],
        "namicolor_shift": [0, -0.1, 0.2],
        "namicolor_fit_base": True,
        "fit_base_anchor": "code95",
        "ref_input": [3000, 4000, 64],
    }
    async with Client(server) as client:
        if backend == "render":
            await client.call_tool("open_image", {"path": path})
        described = await client.call_tool("describe_adjustments", {})
        edited = await client.call_tool("edit_profile", {"path": path, "adjustments": {"film_negative": fields}})
        got = await client.call_tool("get_profile", {"path": path})
        rejected = await client.call_tool(
            "edit_profile",
            {"path": path, "adjustments": {"film_negative": {"namicolor_gain": [1, 0, 0]}}},
        )
        after = await client.call_tool("get_profile", {"path": path})

    assert not edited.is_error, edited.content
    description = described.structured_content["tools"]["film_negative"]["fields"]
    assert "namicolor" in description["method"]["enum"]
    typed = got.structured_content["adjustments"]["film_negative"]
    assert {name: typed[name] for name in fields} == fields
    assert typed["ref_output"] == [0.0, 0.0, 0.0]
    assert edited.structured_content["implied"] == {}
    assert rejected.is_error and "denominator" in str(rejected.content)
    assert after.structured_content["adjustments"]["film_negative"] == typed
    if backend == "render":
        assert sampling_calls(log) == []
    else:
        assert len(editor.applied) == 1
        assert not [request for request in art.received if b"sample_spots" in request]


@pytest.mark.parametrize("method", ["density", "1", "namicolor", "2"])
def test_inactive_power_law_compatibility_data_does_not_hide_other_methods(method):
    changes = WorkingChanges(profile(extra=f"Method={method}\nBackCompat=2\nRedBase=5\n"))
    typed = read_format(changes.profile).adjustments["film_negative"]
    assert typed["method"] in ("density", "namicolor")
    result = changes.edit(adj(ref_input=[200, 50, 400]), [])
    assert result.implied == [] and result.warnings == []
    raw = read_format(changes.profile).raw["Film Negative"]
    assert raw["BackCompat"] == "2" and raw["RedBase"] == "5"


def test_namicolor_round_trip_preserves_active_matrix_and_inactive_density_keys():
    basis = '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}'
    changes = WorkingChanges(
        profile(
            extra=(
                "Method=namicolor\nMatrixPreset=custom\nMatrix=1;0.2;0;0;1;0;0;0;1\n"
                f"MatrixBasis={basis}\nOutputBlackOffset=0.01\n"
            )
        )
    )
    typed = read_format(changes.profile).adjustments["film_negative"]
    changes.edit(adj(**typed), [])
    assert read_format(changes.profile).adjustments["film_negative"] == typed
    with pytest.raises(AdjustmentError, match="custom"):
        changes.edit(adj(matrix_preset="identity", matrix=typed["matrix"]), [])


@pytest.mark.parametrize("stored", ["", "Matrix=1;0;0\n", "Matrix=nan;0;0;0;1;0;0;0;1\n"])
def test_namicolor_rejects_invalid_stored_custom_matrix_atomically(stored):
    changes = WorkingChanges(profile(extra=f"Method=namicolor\nMatrixPreset=custom\n{stored}"))
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="nine finite"):
        changes.edit(adj(namicolor_master_shift=-0.2), [])
    assert keyfile.dumps(changes.profile) == before
    # A coupled edit can repair the coefficients without losing other controls.
    changes.edit(adj(
        matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1], namicolor_master_shift=-0.2,
        matrix_basis='{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}',
    ), [])
    assert changes.profile["Film Negative"]["NamiColorMasterShift"] == "-0.2"


@pytest.mark.parametrize("fields", [
    {"matrix_preset": "custom"},
    {"matrix": [1, 0.2, 0, 0, 1, 0, 0, 0, 1]},
    {"matrix_basis": '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}'},
    {"matrix_preset": "status_m_reference"},
])
def test_explicit_namicolor_mask_opt_in_is_refused_on_an_old_profile_version(fields):
    old = profile(extra=(
        "Method=namicolor\nMatrixPreset=custom\nMatrix=1;0.2;0;0;1;0;0;0;1\n"
        'MatrixBasis={"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}\n'
    ))
    old["Version"]["Version"] = "1054"
    changes = WorkingChanges(old)
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="re-save the sidecar in ART"):
        changes.edit(adj(**fields), [])
    assert keyfile.dumps(changes.profile) == before  # [Version] is never raised


def test_unrelated_namicolor_edit_preserves_old_dormant_preset_version():
    old = profile(extra="Method=namicolor\nMatrixPreset=custom\nMatrix=nan\nMatrixBasis=old basis\n")
    old["Version"]["Version"] = "1054"
    changes = WorkingChanges(old)
    changes.edit(adj(namicolor_master_shift=-0.2), [])
    assert changes.profile["Version"]["Version"] == "1054"
    assert changes.profile["Film Negative"]["MatrixBasis"] == "old basis"


@pytest.mark.parametrize("basis", [
    "",
    '{"v":2,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}',
    '{"v":1,"color_space":"input","profile":"Rec2020","input_gamma":"1","source":"Unknown"}',
    '{"v":1,"color_space":"working","profile":"ProPhoto","input_gamma":"1","source":"Unknown"}',
    '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1.2","source":"Unknown"}',
    '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"nan","source":"Unknown"}',
    '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":""}',
])
def test_namicolor_typed_mask_binding_rejection_is_atomic(basis):
    changes = WorkingChanges(profile(extra="Method=namicolor\n"))
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="matching matrix_basis"):
        changes.edit(adj(matrix_preset="custom", matrix=[1, 0.2, 0, 0, 1, 0, 0, 0, 1], matrix_basis=basis), [])
    assert keyfile.dumps(changes.profile) == before


# -- [Version] is never raised; keys ART ignores at the stored Version refuse ----

OLD_BASIS = '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}'


@pytest.mark.parametrize("version", ["1040", "1045"])
@pytest.mark.parametrize("fields", [
    {"density_gamma": 1.3},
    {"rgb_gains": [0.1, 0, 0]},
    {"film_type": "reversal"},
    {"matrix_preset": "custom"},
    {"output_black_offset": 0.01},
    {"calibration_note": "x"},
])
def test_density_keys_are_refused_below_version_1046_and_version_is_untouched(version, fields):
    old = profile()
    old["Version"]["Version"] = version
    changes = WorkingChanges(old)
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="re-save the sidecar in ART"):
        changes.edit(adj(method="density", **fields), [])
    assert keyfile.dumps(changes.profile) == before


def test_a_method_only_edit_below_1046_is_allowed_and_leaves_version_alone():
    old = profile()
    old["Version"]["Version"] = "1045"
    changes = WorkingChanges(old)
    changes.edit(adj(method="density"), [])
    assert changes.profile["Version"]["Version"] == "1045"


def test_density_keys_are_accepted_from_1046():
    old = profile()
    old["Version"]["Version"] = "1046"
    changes = WorkingChanges(old)
    changes.edit(adj(method="density", density_gamma=1.3), [])
    assert changes.profile["Version"]["Version"] == "1046"
    assert changes.profile["Film Negative"]["DensityGamma"] == "1.3"


def test_a_sidecar_without_a_version_is_current_like_art_and_not_refused():
    old = profile()
    del old["Version"]
    changes = WorkingChanges(old)
    changes.edit(adj(method="density", density_gamma=1.3), [])
    assert "Version" not in changes.profile


def test_no_film_negative_edit_ever_raises_the_version():
    old = profile()
    old["Version"]["Version"] = "1050"
    changes = WorkingChanges(old)
    changes.edit(adj(flare=[0.01, 0, 0]), [])
    assert changes.profile["Version"]["Version"] == "1050"


@pytest.mark.parametrize("version", ["1010", "1038"])
def test_typed_reference_edits_are_refused_below_1039_like_a_legacy_profile(version):
    old = profile()
    old["Version"]["Version"] = version
    with pytest.raises(AdjustmentError, match="legacy"):
        WorkingChanges(old).edit(adj(ref_input=[100, 100, 100]), [])
    assert "film_negative" not in read_format(old).adjustments


@pytest.mark.parametrize("preset", ["status_m_reference", "custom"])
def test_film_base_pick_refuses_a_non_identity_preset_with_an_empty_basis(preset):
    changes = WorkingChanges(profile(extra="Method=density\n"))
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="matching matrix_basis"):
        changes.edit(adj(matrix_preset=preset, matrix_basis="", film_base_sample=[6553.5] * 3), [])
    assert keyfile.dumps(changes.profile) == before


def test_film_base_pick_refuses_a_basis_for_another_input_gamma():
    changes = WorkingChanges(profile(extra="Method=density\nInputGamma=2.2\n"))
    with pytest.raises(AdjustmentError, match="matching matrix_basis"):
        changes.edit(adj(
            matrix_preset="status_m_reference", matrix_basis=OLD_BASIS, film_base_sample=[6553.5] * 3,
        ), [])


@pytest.mark.parametrize("raw_source", [None, True, False])
def test_film_base_pick_refuses_an_input_gamma_ART_would_refuse(raw_source):
    # A profiled source (the default camera profile): ART refuses any non-unity gamma.
    changes = WorkingChanges(profile(extra="Method=density\n"))
    with pytest.raises(AdjustmentError, match="profiled or raw"):
        changes.edit(adj(input_gamma=2.2, film_base_sample=[6553.5] * 3), [], raw_source=raw_source)


def test_film_base_pick_refuses_an_input_gamma_on_an_unprofiled_raw_source():
    changes = WorkingChanges(profile(extra="Method=density\n"))
    changes.profile["Color Management"] = {"InputProfile": "(none)"}
    with pytest.raises(AdjustmentError, match="raw source"):
        changes.edit(adj(input_gamma=2.2, film_base_sample=[6553.5] * 3), [], raw_source=True)


def test_film_base_pick_accepts_an_input_gamma_on_an_unprofiled_scan():
    changes = WorkingChanges(profile(extra="Method=density\n"))
    changes.profile["Color Management"] = {"InputProfile": "(none)"}
    changes.edit(adj(input_gamma=2.2, film_base_sample=[30000] * 3), [], raw_source=False)
    assert "RGBGains" in changes.profile["Film Negative"]


@pytest.mark.parametrize("preset", ["status_m_reference", "custom"])
def test_density_method_refuses_a_non_identity_preset_without_a_basis(preset):
    changes = WorkingChanges(profile(extra="Method=density\n"))
    before = keyfile.dumps(changes.profile)
    with pytest.raises(AdjustmentError, match="matching matrix_basis"):
        changes.edit(adj(matrix_preset=preset), [])
    assert keyfile.dumps(changes.profile) == before


def test_density_method_accepts_a_non_identity_preset_with_its_basis():
    changes = WorkingChanges(profile(extra="Method=density\n"))
    changes.edit(adj(matrix_preset="status_m_reference", matrix_basis=OLD_BASIS), [])
    assert changes.profile["Film Negative"]["MatrixPreset"] == "status_m_reference"


def test_reference_white_and_fit_base_anchor_follow_the_sidecar_version():
    for version, white, anchor in (("1057", 1.0, "legacy"), ("1058", 0.9, "code95")):
        old = profile(extra="Method=namicolor\n")
        old["Version"]["Version"] = version
        film = read_format(old).adjustments["film_negative"]
        assert film["cineon_reference_white"] == white
        assert film["fit_base_anchor"] == anchor
    explicit = profile(extra="Method=namicolor\nCineonReferenceWhite=0.8\nNamiColorFitBaseAnchor=code95\n")
    explicit["Version"]["Version"] = "1057"
    film = read_format(explicit).adjustments["film_negative"]
    assert (film["cineon_reference_white"], film["fit_base_anchor"]) == (0.8, "code95")


def test_defaults_declare_white_09_and_code95_anchor():
    fields = describe_adjustments().tools["film_negative"].fields
    assert fields["cineon_reference_white"].default == 0.9
    assert fields["fit_base_anchor"].default == "code95"


def test_fit_base_enable_is_refused_on_a_sidecar_older_than_1058():
    old = profile(extra="Method=namicolor\n")
    old["Version"]["Version"] = "1057"
    changes = WorkingChanges(old)
    with pytest.raises(AdjustmentError, match="1058"):
        changes.edit(adj(namicolor_fit_base=True), [])
    changes.edit(adj(namicolor_fit_base=True, fit_base_anchor="legacy"), [])
    assert changes.profile["Film Negative"]["NamiColorFitBaseAnchor"] == "legacy"
    assert changes.profile["Version"]["Version"] == "1057"
    current = profile(extra="Method=namicolor\n")
    current["Version"]["Version"] = "1058"
    WorkingChanges(current).edit(adj(namicolor_fit_base=True), [])


def test_partial_of_an_old_conversion_carries_white_1_and_legacy_anchor():
    old = profile()
    old["Version"]["Version"] = "1057"
    changes = WorkingChanges(old)
    changes.edit(adj(method="namicolor"), [])
    saved = keyfile.loads(keyfile.dumps(changes.partial_profile()))
    assert saved["Film Negative"]["CineonReferenceWhite"] == "1"
    assert saved["Film Negative"]["NamiColorFitBaseAnchor"] == "legacy"


def test_flare_defaults_to_zero_whatever_the_version():
    for version in ("1050", "1059"):
        old = profile(extra="Method=density\n")
        old["Version"]["Version"] = version
        assert read_format(old).adjustments["film_negative"]["flare"] == [0.0, 0.0, 0.0]


def test_flare_edit_round_trips():
    changes = WorkingChanges(profile(extra="Method=density\n"))
    changes.edit(adj(flare=[0.01, 0.02, 0.03]), [])
    assert triple(changes.profile["Film Negative"]["Flare"]) == [0.01, 0.02, 0.03]
    assert read_format(changes.profile).adjustments["film_negative"]["flare"] == [0.01, 0.02, 0.03]


@pytest.mark.parametrize("flare", [[-0.01, 0, 0], [0, 0.51, 0], [0, 0, 1]])
def test_flare_out_of_range_is_refused(flare):
    with pytest.raises(Exception, match="flare|greater|less"):
        adj(flare=flare)


def test_new_fields_are_declared_with_their_defaults():
    fields = describe_adjustments().tools["film_negative"].fields
    assert fields["flare"].default == [0.0, 0.0, 0.0]
