"""Free text in a typed field is a plain string: GLib-escaped in the file, unescaped
when read back. A Windows path is the case that mattered: ART refuses the whole
profile for a backslash that does not start a valid escape (``C:\\Users`` fails on
``\\U``), and read back the stored form showed doubled backslashes."""

import json

import pytest

from art_mcp import keyfile
from art_mcp.profile import WorkingChanges, read_format
from art_mcp.schema import AdjustmentError, parse_adjustments

BASE = "[Version]\nVersion=1053\n\n[Film Negative]\nEnabled=true\nMethod=density\n"
WINDOWS_PATH = "C:\\Users\\x\\new.cube"


@pytest.mark.parametrize(
    "text, stored",
    [
        ("plain", "plain"),
        (WINDOWS_PATH, "C:\\\\Users\\\\x\\\\new.cube"),
        ("two\nlines", "two\\nlines"),
        ("a\tb\rc", "a\\tb\\rc"),
        ("  lead", "\\s\\slead"),
        ("trail", "trail"),
        ("", ""),
        ("café ✓", "café ✓"),
    ],
)
def test_escape_and_unescape_are_inverse(text, stored):
    assert keyfile.escape(text) == stored
    assert keyfile.unescape(stored) == text


def test_unescape_leaves_an_unknown_sequence_as_written():
    assert keyfile.unescape("a\\gb") == "a\\gb"
    assert keyfile.unescape("end\\") == "end\\"


def edit(**fields):
    changes = WorkingChanges(keyfile.loads(BASE))
    result = changes.edit(parse_adjustments({"film_negative": fields}), [])
    return changes, result


def typed(profile):
    return read_format(profile).adjustments["film_negative"]


def test_a_windows_path_is_stored_escaped_and_read_back_as_typed():
    changes, _ = edit(calibration_note=WINDOWS_PATH)

    assert changes.profile["Film Negative"]["CalibrationNote"] == "C:\\\\Users\\\\x\\\\new.cube"
    assert typed(changes.profile)["calibration_note"] == WINDOWS_PATH
    assert typed(keyfile.loads(keyfile.dumps(changes.profile)))["calibration_note"] == WINDOWS_PATH


def test_a_note_with_a_line_break_stays_on_one_line_and_comes_back():
    changes, _ = edit(calibration_note="Portra 400\nTungsten")

    assert changes.profile["Film Negative"]["CalibrationNote"] == "Portra 400\\nTungsten"
    assert typed(keyfile.loads(keyfile.dumps(changes.profile)))["calibration_note"] == (
        "Portra 400\nTungsten"
    )


def test_a_value_ART_wrote_is_read_unescaped():
    profile = keyfile.loads(
        BASE + "CalibrationNote=C:\\\\a\\\\b.cube\\sx\\ny\n"
    )

    assert typed(profile)["calibration_note"] == "C:\\a\\b.cube x\ny"


def test_setting_the_text_a_profile_already_holds_is_not_a_change():
    changes, first = edit(calibration_note=WINDOWS_PATH)
    again = changes.edit(
        parse_adjustments({"film_negative": {"calibration_note": WINDOWS_PATH}}), []
    )

    assert first.changed
    assert not again.changed


@pytest.mark.parametrize("char", ["\v", "\f", "\x1c", "\x85", "\u2028"])
def test_a_line_break_that_would_split_the_line_is_refused(char):
    with pytest.raises(AdjustmentError) as e:
        edit(calibration_note="a" + char + "b")

    assert e.value.code == "out_of_range"


def test_a_matrix_basis_bound_to_an_input_profile_path_matches_that_profile():
    # InputProfile is a file path; ART stores it escaped, and the basis is JSON
    # whose own backslashes are JSON-escaped on top of that.
    profile = keyfile.loads(
        "[Version]\nVersion=1053\n\n"
        "[Color Management]\nInputProfile=C:\\\\profiles\\\\cam.icc\n\n"
        "[Film Negative]\nEnabled=true\nMethod=density\nColorSpace=0\n"
    )
    basis = json.dumps(
        {
            "v": 1,
            "color_space": "input",
            "profile": "C:\\profiles\\cam.icc",
            "input_gamma": "1",
            "source": "Unknown",
        }
    )
    changes = WorkingChanges(profile)

    result = changes.edit(
        parse_adjustments(
            {
                "film_negative": {
                    "matrix_preset": "status_m_reference",
                    "matrix_basis": basis,
                    "film_base_sample": [20000, 12000, 6000],
                }
            }
        ),
        [],
    )

    assert {e.key for e in result.changed} >= {"RGBGains", "MatrixBasis"}
