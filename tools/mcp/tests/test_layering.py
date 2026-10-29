"""layering.overlay: a partial profile laid over a complete one key by key, as
the fork's KeyFilePartialProfile::applyTo does in the editor."""

from art_mcp.layering import overlay

BASE = {
    "Version": {"AppVersion": "1.26", "Version": "1064"},
    "Exposure": {"Enabled": "true", "Compensation": "0", "HLRecovery": "Balanced"},
    "Crop": {"Enabled": "true", "X": "100"},
    "ColorCorrection": {"Enabled": "true", "LabRegionA_1": "0.1", "LabRegionA_2": "0.2"},
    "Film Negative": {"Enabled": "false", "Method": "namicolor", "RedRatio": "1.0"},
}


def test_a_preset_changes_only_the_keys_it_lists():
    merged = overlay(BASE, {"Exposure": {"Compensation": "0.1"}})

    assert merged["Exposure"] == {"Enabled": "true", "Compensation": "0.1", "HLRecovery": "Balanced"}
    assert merged["Crop"] == BASE["Crop"]


def test_a_group_the_base_lacks_is_added_and_the_base_is_not_changed():
    merged = overlay(BASE, {"Sharpening": {"Enabled": "true"}})

    assert merged["Sharpening"] == {"Enabled": "true"}
    assert "Sharpening" not in BASE


def test_later_layers_win():
    merged = overlay(BASE, {"Exposure": {"Compensation": "1"}}, {"Exposure": {"Compensation": "2"}})

    assert merged["Exposure"]["Compensation"] == "2"


def test_color_correction_regions_are_replaced_whole():
    merged = overlay(BASE, {"ColorCorrection": {"Enabled": "true", "LabRegionA_1": "0.5"}})

    assert merged["ColorCorrection"] == {"Enabled": "true", "LabRegionA_1": "0.5"}  # region 2 is gone


def test_old_film_keys_without_a_method_select_power_law():
    for version in ({}, {"Version": {"Version": "1045"}}):
        merged = overlay(BASE, {**version, "Film Negative": {"RedRatio": "1.3"}})

        assert merged["Film Negative"]["Method"] == "power_law"


def test_a_method_or_a_newer_version_keeps_the_film_method():
    with_method = overlay(BASE, {"Film Negative": {"RedRatio": "1.3", "Method": "namicolor"}})
    newer = overlay(BASE, {"Version": {"Version": "1046"}, "Film Negative": {"RedRatio": "1.3"}})
    no_old_keys = overlay(BASE, {"Film Negative": {"Enabled": "true"}})

    assert [m["Film Negative"]["Method"] for m in (with_method, newer, no_old_keys)] == ["namicolor"] * 3
