"""Adjustment rules on the profile module: compile to the partial profile,
conflict, auto-enable, explicit disable, typed read format."""

import pytest

from art_mcp.profile import Conflict, RawEdit, WorkingChanges, read_format
from art_mcp.schema import parse_adjustments


def full_profile():
    return {
        "Version": {"Version": "1045"},
        "Exposure": {
            "Enabled": "true", "Compensation": "0", "Black": "0",
            "HLRecovery": "Off", "HLRecoveryBlur": "0",
        },
        "White Balance": {
            "Enabled": "true", "Setting": "Camera", "Temperature": "6504",
            "Green": "1", "Multipliers": "1;1;1",
        },
        "Sharpening": {"Enabled": "false"},
    }


def edit(group, key, value):
    return RawEdit(group=group, key=key, value=value)


def adj(**tools):
    return parse_adjustments(tools)


def test_adjustment_joins_the_partial_profile_like_a_raw_edit():
    changes = WorkingChanges(full_profile())

    result = changes.edit(adj(exposure={"compensation": 0.7}), [edit("Sharpening", "Enabled", "true")])

    assert changes.partial_profile() == {
        "Exposure": {"Compensation": "0.7"},
        "Sharpening": {"Enabled": "true"},
    }
    assert result.changed == [
        edit("Exposure", "Compensation", "0.7"), edit("Sharpening", "Enabled", "true")
    ]
    assert result.implied == []


def test_adjustment_and_raw_edit_on_the_same_key_conflict_and_change_nothing():
    changes = WorkingChanges(full_profile())

    with pytest.raises(Conflict, match=r"\[Exposure\] Compensation"):
        changes.edit(adj(exposure={"compensation": 1}), [edit("Exposure", "Compensation", "2")])

    assert changes.partial_profile() == {}


def test_adjusting_a_disabled_tool_enables_it_as_an_implied_change():
    profile = full_profile()
    profile["Exposure"]["Enabled"] = "false"
    changes = WorkingChanges(profile)

    result = changes.edit(adj(exposure={"black": 0.5}), [])

    assert profile["Exposure"]["Enabled"] == "true"
    assert result.implied == [edit("Exposure", "Enabled", "true")]
    assert edit("Exposure", "Enabled", "true") in result.changed


def test_explicit_enabled_false_wins_over_the_implied_enable():
    profile = full_profile()
    profile["Exposure"]["Enabled"] = "false"
    changes = WorkingChanges(profile)

    result = changes.edit(adj(exposure={"black": 0.5, "enabled": False}), [])

    assert profile["Exposure"]["Enabled"] == "false"
    assert result.implied == []
    assert profile["Exposure"]["Black"] == "0.5"


def test_white_balance_temperature_switches_setting_to_custom_temp():
    changes = WorkingChanges(full_profile())

    result = changes.edit(adj(white_balance={"temperature": 5200}), [])

    assert changes.partial_profile() == {
        "White Balance": {"Temperature": "5200", "Setting": "CustomTemp"}
    }
    assert result.implied == [edit("White Balance", "Setting", "CustomTemp")]


def test_white_balance_explicit_setting_is_not_overridden():
    changes = WorkingChanges(full_profile())

    result = changes.edit(adj(white_balance={"setting": "Auto", "temperature": 5200}), [])

    assert changes.profile["White Balance"]["Setting"] == "Auto"
    assert result.implied == []


def test_a_raw_edit_of_an_implied_key_wins_over_the_implication():
    profile = full_profile()
    profile["Exposure"]["Enabled"] = "false"
    changes = WorkingChanges(profile)

    changes.edit(adj(exposure={"black": 0.5}), [edit("Exposure", "Enabled", "false")])

    assert profile["Exposure"]["Enabled"] == "false"


def test_adjusting_a_key_art_omits_from_the_profile_adds_it():
    profile = full_profile()
    changes = WorkingChanges(profile)

    changes.edit(adj(white_balance={"equal": 1.2}), [])

    assert profile["White Balance"]["Equal"] == "1.2"
    assert changes.partial_profile()["White Balance"]["Equal"] == "1.2"


def test_read_format_types_curated_tools_and_leaves_other_keys_raw_once():
    view = read_format(full_profile())

    assert view.adjustments["exposure"] == {
        "enabled": True, "compensation": 0.0, "black": 0.0,
        "hl_recovery": "Off", "hl_recovery_blur": 0,
    }
    assert view.adjustments["white_balance"] == {
        "enabled": True, "setting": "Camera", "temperature": 6504, "green": 1.0, "equal": 1.0,
    }
    assert "Exposure" not in view.raw
    assert view.raw["White Balance"] == {"Multipliers": "1;1;1"}
    assert view.raw["Sharpening"] == {"Enabled": "false"}


def test_a_value_that_does_not_fit_the_schema_stays_raw():
    profile = full_profile()
    profile["White Balance"]["Setting"] = "CustomMultLegacy"

    view = read_format(profile)

    assert "setting" not in view.adjustments["white_balance"]
    assert view.raw["White Balance"]["Setting"] == "CustomMultLegacy"


def test_newer_profile_version_warns_that_the_schema_is_older():
    profile = full_profile()
    profile["Version"]["Version"] = "1050"

    assert read_format(profile).warnings
    assert not read_format(full_profile()).warnings
