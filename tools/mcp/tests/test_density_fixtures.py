"""Independent numerical fixtures for the density film-negative contract.

These are reference-formula checks on literals: they do not call the engine.
Engine coverage lives in test_integration_film_negative.py (needs ART_DIR).

Expected values are handwritten literals from issue #46 (and the Colour
Cineon convention). They are not read back from filmnegativeproc.cc,
papercurve.cc, or cineonlut.cc, and this file does not call art-cli.

Profile method selection is implemented only in C++:
ProcParams::load and KeyFilePartialProfile::applyTo in
src/engine/procparams.cc. tools/mcp keyfile loading does not mirror that
rule, so the sidecar cases below only lock the fixture files a human or
art-cli can load. They do not pretend a Python merge selected the method.

Not run: GUI mode changes, preview/detail/thumbnail agreement, full-resolution
export timing, CPU/memory, Render/Live servers, and an art-cli pixel render
(no art-cli was built in this worktree).
"""

import math
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# 10**(-2.5) / T, rounded as published in issue #46.
NEGATIVE_LINEAR = {
    0.01: 0.316227766,
    0.1: 0.031622777,
    1.0: 0.003162278,
}

# DiVERE Status M rows. R-basis displacement is the first column.
STATUS_M_ROWS = (
    (1.0197, 0.0317, 0.0091),
    (-0.0052, 0.8933, 0.0521),
    (0.0131, -0.0011, 0.9712),
)
R_DISPLACEMENT = (1.0197, -0.0052, 0.0131)

# 10**0.1, and 0.031622777 * 10**0.1.
GAIN_0_1 = 1.25892541179
GAINED_LINEAR = 0.03981071756

# Colour: (685 + 300*log10(0.18*(1-b)+b)) with b = 10**((95-685)/300).
CINEON_018_CODE = 467.837964

OLD_KEYS = {
    "RedRatio",
    "GreenExponent",
    "BlueRatio",
    "RedBase",
    "GreenBase",
    "BlueBase",
    "RefInput",
    "RefOutput",
    "ColorSpace",
    "BackCompat",
}


def test_identity_negative_literals():
    # Closed form from the spec, checked against the published approximations.
    # Not a pipeline reimplementation compared with itself.
    scale = 10 ** (-2.5)
    for transmittance, published in NEGATIVE_LINEAR.items():
        assert abs(scale / transmittance - published) < 5e-10
    # Increasing transmittance darkens the negative inversion.
    assert NEGATIVE_LINEAR[0.01] > NEGATIVE_LINEAR[0.1] > NEGATIVE_LINEAR[1.0]
    # Above reference white is retained: T=2 is half of T=1.
    assert abs(scale / 2.0 - 0.00158113883) < 5e-11


def test_identity_reversal_reproduces_input_above_the_floor():
    floor = 1e-10
    for sample in (0.18, 1.0, 2.5, 1e-6):
        assert max(sample, floor) == sample
    assert max(0.0, floor) == floor
    assert max(-0.2, floor) == floor


def test_reference_matrix_r_displacement_is_the_published_column():
    got = tuple(STATUS_M_ROWS[i][0] for i in range(3))
    assert got == R_DISPLACEMENT
    # Unequal row sums: not a neutral-axis fixture.
    sums = [sum(row) for row in STATUS_M_ROWS]
    assert sums != [1.0, 1.0, 1.0]


def test_gain_of_0_1_multiplies_pre_curve_linear_by_10_to_the_0_1():
    assert abs(10 ** 0.1 - GAIN_0_1) < 1e-11
    before = NEGATIVE_LINEAR[0.1]
    assert abs(before * GAIN_0_1 - GAINED_LINEAR) < 1e-11


def test_output_black_offset_subtracts_and_floors_at_zero():
    linear = NEGATIVE_LINEAR[0.1]
    assert abs(max(0.0, linear - 0.01) - 0.021622777) < 5e-10
    assert max(0.0, NEGATIVE_LINEAR[1.0] - 0.05) == 0.0
    # Not a flare recovery: the offset does not change the input.
    assert linear - 0.0 == linear


def test_cineon_black_white_and_linear_018():
    b = 10 ** ((95 - 685) / 300.0)
    code = (685 + 300 * math.log10(0.18 * (1.0 - b) + b)) / 1023.0
    assert abs(code * 1023.0 - CINEON_018_CODE) < 1e-6
    # Black and reference white are the documented codes, not a fit.
    black = (685 + 300 * math.log10(b)) / 1023.0
    white = (685 + 300 * math.log10((1.0 - b) + b)) / 1023.0
    assert abs(black - 95 / 1023.0) < 1e-12
    assert abs(white - 685 / 1023.0) < 1e-12


def _entries(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    group = None
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            out.setdefault(group, {})
            continue
        key, value = line.split("=", 1)
        out[group][key] = value
    return out


def _spec_selects_power_law(entries):
    """Issue #46 rule, written here so the fixtures stay honest.

    This is not ProcParams::load. That function is the implementation.
    """
    film = entries.get("Film Negative", {})
    if "Method" in film:
        return False
    if not OLD_KEYS.intersection(film):
        return False
    version = entries.get("Version", {}).get("Version")
    if version is None:
        return True
    return int(version) < 1046


def test_old_sidecar_without_method_is_the_power_law_fixture():
    entries = _entries("old_sidecar_no_method.arp")
    assert "Method" not in entries["Film Negative"]
    assert int(entries["Version"]["Version"]) < 1046
    assert _spec_selects_power_law(entries)


def test_partial_method_fixtures_match_the_spec_rule():
    # C++: ProcParams::load, KeyFilePartialProfile::applyTo.
    assert not _spec_selects_power_law(_entries("current_partial_no_method.arp"))
    assert _spec_selects_power_law(_entries("prefeature_partial_old_keys.arp"))
    assert not _spec_selects_power_law(
        _entries("prefeature_partial_enabled_only.arp")
    )
    assert _spec_selects_power_law(_entries("versionless_old_keys.arp"))
    assert not _spec_selects_power_law(_entries("versionless_new_fields_only.arp"))
    for name in (
        "current_partial_no_method.arp",
        "prefeature_partial_old_keys.arp",
        "prefeature_partial_enabled_only.arp",
        "versionless_old_keys.arp",
        "versionless_new_fields_only.arp",
        "old_sidecar_no_method.arp",
    ):
        assert "Method" not in _entries(name)["Film Negative"]
