"""Paper-target contract, independent of the C++ pixel loop.

R = log10(65536)
u = 1 - clamp(C / R, 0, 1)
v = piecewise-linear interp, clamped to endpoint y
C = R * (1 - v)

Shared curve, then the matching channel curve. Unknown ids are an error,
not a substitute curve. Source points are sorted by increasing x.
"""

import json
import math
import re
from pathlib import Path

import pytest

from art_mcp.schema import AdjustmentError, parse_adjustments

CURVES = Path(__file__).resolve().parents[3] / "data" / "filmcurves"
R = math.log10(65536)


def load(ident):
    obj = json.loads((CURVES / f"{ident}.json").read_text(encoding="utf-8"))
    out = {}
    for key in ("RGB", "R", "G", "B"):
        pts = sorted((float(x), float(y)) for x, y in obj["curves"][key])
        deduped = []
        for x, y in pts:
            if deduped and x == deduped[-1][0]:
                assert y == deduped[-1][1]
                continue
            deduped.append((x, y))
        xs = [p[0] for p in deduped]
        assert xs == sorted(xs)
        out[key] = deduped
    return out


def interp(points, u):
    if u <= points[0][0]:
        return points[0][1]
    if u >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x0 <= u <= x1:
            t = (u - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    raise AssertionError(u)


def apply_one(density, points):
    ratio = density / R
    ratio = 0.0 if ratio < 0.0 else 1.0 if ratio > 1.0 else ratio
    v = interp(points, 1.0 - ratio)
    return R * (1.0 - v)


def apply_paper(c0, c1, c2, ident):
    if not (CURVES / f"{ident}.json").is_file():
        return None
    curve = load(ident)
    shared = [apply_one(c, curve["RGB"]) for c in (c0, c1, c2)]
    return (
        apply_one(shared[0], curve["R"]),
        apply_one(shared[1], curve["G"]),
        apply_one(shared[2], curve["B"]),
    )


def test_shipped_identifiers_match_the_ticket():
    expected = {
        "kodak_2383",
        "kodak_2393",
        "kodak_ektacolor_edge",
        "kodak_endura_premier",
        "kodak_portra_endura",
        "kodak_supra_endura",
        "kodak_ultra_endura",
        "ilford_mgfb_00",
        "ilford_mgfb_0",
        "ilford_mgfb_1",
        "ilford_mgfb_2",
        "ilford_mgfb_3",
        "ilford_mgfb_4",
        "ilford_mgfb_5",
    }
    found = {p.stem for p in CURVES.glob("*.json")}
    assert found == expected


def test_descending_ilford_points_clamp_to_the_low_x_endpoint():
    # DiVERE stores Ilford MGFB 00 RGB descending. After sort the first
    # point is x=0.324359818125, y=0.5683874341666666. u below that x
    # clamps to that y. Hand: C_out = R * (1 - y).
    y = 0.5683874341666666
    expected = R * (1.0 - y)
    got = apply_one(R, load("ilford_mgfb_00")["RGB"])
    assert got == pytest.approx(expected, rel=1e-12)
    assert got == pytest.approx(2.0788532611412505, rel=1e-12)

def test_interior_blend_is_piecewise_linear():
    # First two sorted Ilford 00 RGB points, midpoint, by hand.
    # x0=0.324359818125 y0=0.5683874341666666
    # x1=0.42860636386639916 y1=0.604787913219865
    # umid=0.37648309099569954 vmid=0.5865876736932658
    # C = R*(1-umid) = 3.0031566786237365
    # C' = R*(1-vmid) = 1.991192172728841
    c = R * (1.0 - 0.37648309099569954)
    got = apply_one(c, load("ilford_mgfb_00")["RGB"])
    assert got == pytest.approx(1.991192172728841, rel=1e-9)


def test_shared_then_channel_is_not_channel_then_shared():
    # Constant responses, so order is visible. Not a Kodak curve.
    shared = [(0.0, 0.2), (1.0, 0.2)]
    channel = [(0.0, 0.5), (1.0, 0.5)]
    shared_first = apply_one(apply_one(1.0, shared), channel)
    channel_first = apply_one(apply_one(1.0, channel), shared)
    assert shared_first == pytest.approx(R * 0.5, rel=1e-12)
    assert channel_first == pytest.approx(R * 0.8, rel=1e-12)


def test_unknown_curve_is_an_error_not_identity():
    assert apply_paper(1.0, 1.0, 1.0, "not_a_kodak") is None
    with pytest.raises(AdjustmentError) as e:
        parse_adjustments({"film_negative": {"paper_curve": "not_a_kodak"}})
    assert e.value.code == "out_of_range"


def test_ilford_channel_curves_are_identity_and_do_not_desaturate():
    curve = load("ilford_mgfb_2")
    assert curve["R"] == [(0.0, 0.0), (1.0, 1.0)]
    assert curve["G"] == curve["R"] and curve["B"] == curve["R"]
    # Unequal densities stay unequal: a shared curve is not a desaturate.
    out = apply_paper(0.4, 1.2, 2.5, "ilford_mgfb_2")
    assert out[0] != pytest.approx(out[1])
    assert out[1] != pytest.approx(out[2])


def parse_vendored_table():
    """{ident: {channel: [(x, y), ...]}} from the generated C++ table."""
    inc = (Path(__file__).resolve().parents[3] / "src" / "engine" / "papercurves.inc").read_text(encoding="utf-8")
    arrays = {}
    pattern = r"static const double k_(\w+)_(rgb|r|g|b)_(x|y)\[\] = \{([^}]*)\};"
    for ident, channel, axis, body in re.findall(pattern, inc):
        arrays[(ident, channel, axis)] = [float(v) for v in body.split(",") if v.strip()]
    table = {}
    for (ident, channel, axis), values in arrays.items():
        if axis == "x":
            ys = arrays[(ident, channel, "y")]
            assert len(ys) == len(values), (ident, channel)
            table.setdefault(ident, {})[channel.upper()] = list(zip(values, ys, strict=True))
    return table


def test_the_whole_generated_table_matches_data_filmcurves():
    table = parse_vendored_table()
    shipped = {p.stem for p in CURVES.glob("*.json")}
    assert set(table) == shipped
    for ident in sorted(shipped):
        expected = load(ident)
        assert set(table[ident]) == {"RGB", "R", "G", "B"}, ident
        for channel, points in expected.items():
            got = table[ident][channel]
            assert len(got) == len(points), (ident, channel)
            for (gx, gy), (ex, ey) in zip(got, points, strict=True):
                assert gx == pytest.approx(ex, abs=1e-12), (ident, channel)
                assert gy == pytest.approx(ey, abs=1e-12), (ident, channel)
