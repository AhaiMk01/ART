"""Independent fixtures for the film-negative method-load rule and a few
NamiColor reference literals.

These are reference-formula checks on literals: they do not call the engine.
Engine coverage lives in test_integration_film_negative.py (needs ART_DIR).

Profile method selection is implemented only in C++:
ProcParams::load and KeyFilePartialProfile::applyTo in
src/engine/procparams.cc. tools/mcp keyfile loading does not mirror that
rule, so the sidecar cases below only lock the fixture files a human or
art-cli can load. They do not pretend a Python merge selected the method.
"""

import math
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

# DiVERE Status M rows. R-basis displacement is the first column.
STATUS_M_ROWS = (
    (1.0197, 0.0317, 0.0091),
    (-0.0052, 0.8933, 0.0521),
    (0.0131, -0.0011, 0.9712),
)
R_DISPLACEMENT = (1.0197, -0.0052, 0.0131)

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


def test_reference_matrix_r_displacement_is_the_published_column():
    got = tuple(STATUS_M_ROWS[i][0] for i in range(3))
    assert got == R_DISPLACEMENT
    # Unequal row sums: not a neutral-axis fixture.
    sums = [sum(row) for row in STATUS_M_ROWS]
    assert sums != [1.0, 1.0, 1.0]


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
