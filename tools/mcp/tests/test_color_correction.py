"""The typed color_correction adjustment at the profile seam: regions in RGB
mode, area masks, complete key sets for new regions and shapes."""

from pathlib import Path

import pytest

from art_mcp import keyfile
from art_mcp.colorcorrection import REGION_DEFAULTS, SHAPE_DEFAULTS, is_region_key
from art_mcp.profile import (
    Conflict,
    RawEdit,
    UnknownKey,
    WorkingChanges,
    edit_result,
    partial_vs_default,
    read_format,
)
from art_mcp.schema import AdjustmentError, describe_adjustments, parse_adjustments

REAL_DEFAULT = (Path(__file__).parent / "data" / "art_default_colorcorrection.arp").read_text()
"""The [ColorCorrection] group of ART's default profile, as the fork's art-cli
(PPVERSION 1045) writes it."""

ELLIPSE = {
    "inverted": True, "feather": 5,
    "shapes": [{"type": "rectangle", "x": 0, "y": 0, "width": 110, "height": 110,
                "angle": 0, "roundness": 100, "feather": 60, "blur": 0, "mode": "add"}],
}  # fmt: skip


def adj(**tools):
    return parse_adjustments(tools)


def profile():
    return {"Version": {"Version": "1045"}, **keyfile.loads(REAL_DEFAULT)}


def keys(group, n):
    return {k.rsplit("_", 1)[0] for k in group if k.endswith(f"_{n}")}


def test_a_new_region_gets_the_key_set_ART_saves():
    changes = WorkingChanges(profile())

    changes.edit(adj(color_correction={"regions": [None, {"b": {"slope": 0.85}}]}), [])

    group = changes.profile["ColorCorrection"]
    assert keys(group, 2) == keys(group, 1) == {k for k, _ in REGION_DEFAULTS}
    assert group["Mode_2"] == "RGB" and group["SlopeB_2"] == "0.85"
    assert group["SlopeG_2"] == "1" and group["HSLGamma_2"] == "2.3999999999999999"


def edited(request):
    """The edit result (as edit_profile reports it) of a color_correction request on ART's default profile."""
    changes = WorkingChanges(profile())
    parsed = adj(color_correction=request)
    outcome = changes.edit(parsed, [])
    return changes, edit_result(outcome, changes.profile, parsed, [], [])


def test_a_new_region_reports_what_the_request_set_and_counts_the_keys_left_at_their_defaults():
    changes, result = edited({"regions": [None, {"b": {"slope": 0.85}}]})

    assert result.changed == {"ColorCorrection": {"Mode_2": "RGB", "SlopeB_2": "0.85"}}
    assert result.implied == {"ColorCorrection": {"Enabled": "true"}}
    # The template's keys minus the two the request set (Mode, SlopeB): the rest is ART's defaults.
    assert result.created == {"ColorCorrection": [f"region 2 ({len(REGION_DEFAULTS) - 2} keys at their defaults)"]}
    group = changes.profile["ColorCorrection"]
    assert keys(group, 2) == {k for k, _ in REGION_DEFAULTS}  # the profile still gets every key
    assert group["HSLGamma_2"] == "2.3999999999999999" and "HSLGamma_2" not in result.changed["ColorCorrection"]


def test_what_a_new_region_is_made_of_adds_up():
    changes, result = edited({"regions": [None, {"b": {"slope": 0.85, "power": 0.62}, "g": {"slope": 1}}]})

    group = changes.profile["ColorCorrection"]
    region_keys = {k for k in result.changed["ColorCorrection"] | result.implied["ColorCorrection"] if k.endswith("_2")}
    defaulted = int(result.created["ColorCorrection"][0].split("(")[1].split()[0])
    assert region_keys == {"Mode_2", "SlopeB_2", "PowerB_2", "SlopeG_2"}  # a slope of 1 is still asked for
    assert defaulted + len(region_keys) == len(keys(group, 2))


def test_a_new_region_with_a_mask_counts_its_region_and_its_shape_apart():
    shape = {"type": "rectangle", "width": 110, "height": 110, "roundness": 100, "feather": 60}

    _, result = edited({"regions": [None, {"b": {"slope": 0.85}, "mask": {"inverted": True, "shapes": [shape]}}]})

    # Set: Mode, SlopeB, MaskInverted, AreaMaskEnabled (implied); the shape's Type, Width, Height, Roundness,
    # ShapeFeather.
    assert result.created == {"ColorCorrection": [
        f"region 2 ({len(REGION_DEFAULTS) - 4} keys at their defaults)",
        f"region 2 mask shape 0 ({len(SHAPE_DEFAULTS['rectangle']) - 5} keys at their defaults)",
    ]}  # fmt: skip
    changed = result.changed["ColorCorrection"]
    assert changed["AreaMaskRoundness_2"] == "100" and changed["MaskInverted_2"] == "true"
    assert "AreaMaskX_2" not in changed and "AreaMaskAngle_2" not in changed  # defaults, counted not listed
    assert result.implied["ColorCorrection"] == {"Enabled": "true", "AreaMaskEnabled_2": "true"}


def test_editing_a_region_that_exists_creates_nothing():
    base = profile()
    base["ColorCorrection"].update({"Mode_1": "RGB", "Enabled": "true"})
    changes = WorkingChanges(base)
    parsed = adj(color_correction={"regions": [{"g": {"offset": 0.02}}]})

    result = edit_result(changes.edit(parsed, []), changes.profile, parsed, [], [])

    assert result.created == {} and result.changed == {"ColorCorrection": {"OffsetG_1": "0.02"}}


def test_a_shape_appended_to_a_mask_or_replaced_by_one_of_another_type_is_created_too():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {"mask": ELLIPSE}]}), [])

    def edit_shapes(*shapes):
        parsed = adj(color_correction={"regions": [None, {"mask": {"shapes": list(shapes)}}]})
        return edit_result(changes.edit(parsed, []), changes.profile, parsed, [], [])

    appended = edit_shapes(None, {"type": "gradient", "x": 10})
    replaced = edit_shapes({"type": "gradient", "angle": 45})
    edited_in_place = edit_shapes({"type": "gradient", "angle": 90})

    # The gradient's template minus its Type and X; then minus its Type and Angle.
    assert appended.created == {"ColorCorrection": [
        f"region 2 mask shape 1 ({len(SHAPE_DEFAULTS['gradient']) - 2} keys at their defaults)"]}  # fmt: skip
    assert replaced.created == {"ColorCorrection": [
        f"region 2 mask shape 0 ({len(SHAPE_DEFAULTS['gradient']) - 2} keys at their defaults)"]}  # fmt: skip
    assert edited_in_place.created == {}
    assert edited_in_place.changed == {"ColorCorrection": {"AreaMaskAngle_2": "90"}}


def test_a_region_created_without_a_color_correction_group_counts_the_group_too():
    changes = WorkingChanges({"Version": {"Version": "1045"}})
    parsed = adj(color_correction={"regions": [{"r": {"slope": 1.2}}]})

    result = edit_result(changes.edit(parsed, []), changes.profile, parsed, [], [])

    assert result.created == {"ColorCorrection": [f"region 1 ({len(REGION_DEFAULTS) - 2} keys at their defaults)"]}
    assert result.changed == {"ColorCorrection": {"Mode_1": "RGB", "SlopeR_1": "1.2"}}


def test_the_defaults_of_a_created_region_still_reach_the_partial_profile():
    """Listing them apart changes the report, not what is sent to ART."""
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {"b": {"slope": 0.85}}]}), [])

    partial = changes.partial_profile()["ColorCorrection"]

    assert keys(partial, 2) == {k for k, _ in REGION_DEFAULTS} and partial["SlopeB_2"] == "0.85"


def test_a_raw_edit_of_a_key_a_replaced_shape_is_given_by_default_is_still_a_conflict():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {"mask": ELLIPSE}]}), [])

    with pytest.raises(Conflict, match="AreaMaskX_2"):
        changes.edit(
            adj(color_correction={"regions": [None, {"mask": {"shapes": [{"type": "gradient"}]}}]}),
            [RawEdit(group="ColorCorrection", key="AreaMaskX_2", value="50")],
        )


def test_the_template_is_the_real_default_region():
    real = keyfile.loads(REAL_DEFAULT)["ColorCorrection"]

    assert {k[:-2]: v for k, v in real.items() if k.endswith("_1")} == dict(REGION_DEFAULTS)


def test_region_one_edit_writes_the_keys_and_lists_the_implied_changes():
    changes = WorkingChanges(profile())

    result = changes.edit(
        adj(color_correction={"regions": [{"r": {"slope": 1.1844, "power": 1.0204}, "b": {"slope": 0.9239}}]}),
        [],
    )

    assert {(e.key, e.value) for e in result.changed} == {
        ("SlopeR_1", "1.1844"), ("PowerR_1", "1.0204"), ("SlopeB_1", "0.9239"),
        ("Mode_1", "RGB"), ("Enabled", "true"),
    }  # fmt: skip
    assert {(e.key, e.value) for e in result.implied} == {("Mode_1", "RGB"), ("Enabled", "true")}


def test_an_rgb_region_in_an_enabled_tool_implies_nothing():
    base = profile()
    base["ColorCorrection"].update({"Mode_1": "RGB", "Enabled": "true"})
    changes = WorkingChanges(base)

    result = changes.edit(adj(color_correction={"regions": [{"g": {"offset": 0.02}}]}), [])

    assert result.changed == [RawEdit(group="ColorCorrection", key="OffsetG_1", value="0.02")]
    assert result.implied == []


def test_editing_only_the_mask_of_a_region_keeps_its_mode():
    base = profile()
    base["ColorCorrection"]["Mode_1"] = "HSL"
    changes = WorkingChanges(base)

    changes.edit(adj(color_correction={"enabled": False, "regions": [{"mask": {"inverted": True}}]}), [])

    assert changes.profile["ColorCorrection"]["Mode_1"] == "HSL"
    assert changes.profile["ColorCorrection"]["MaskInverted_1"] == "true"


def test_adding_a_region_with_an_inverted_ellipse_writes_complete_mask_keys():
    changes = WorkingChanges(profile())

    result = changes.edit(
        adj(color_correction={"regions": [None, {"b": {"slope": 0.85}, "mask": ELLIPSE}]}), []
    )

    group = changes.profile["ColorCorrection"]
    assert {k: group[k] for k in group if k.startswith("AreaMask") and k.endswith("_2")} == {
        "AreaMaskEnabled_2": "true", "AreaMaskFeather_2": "5", "AreaMaskBlur_2": "0",
        "AreaMaskContrast_2": "0;",
        "AreaMaskType_2": "rectangle", "AreaMaskX_2": "0", "AreaMaskY_2": "0",
        "AreaMaskWidth_2": "110", "AreaMaskHeight_2": "110", "AreaMaskAngle_2": "0",
        "AreaMaskRoundness_2": "100", "AreaMaskMode_2": "add",
        "AreaMaskShapeFeather_2": "60", "AreaMaskShapeBlur_2": "0",
    }  # fmt: skip
    assert group["MaskInverted_2"] == "true"
    assert RawEdit(group="ColorCorrection", key="AreaMaskEnabled_2", value="true") in result.implied
    assert RawEdit(group="ColorCorrection", key="Enabled", value="true") in result.implied


def test_a_second_shape_uses_ARTs_indexed_key_names():
    changes = WorkingChanges(profile())
    second = {"type": "gradient", "x": 10, "angle": -45, "strength_start": 80}

    changes.edit(adj(color_correction={"regions": [None, {"mask": {"shapes": [ELLIPSE["shapes"][0], second]}}]}), [])

    group = changes.profile["ColorCorrection"]
    gradient = {k[len("AreaMask_1_"):-2]: v for k, v in group.items() if k.startswith("AreaMask_1_")}
    assert gradient == {
        "Type": "gradient", "X": "10", "Y": "0", "StrengthStart": "80", "StrengthEnd": "0",
        "Angle": "-45", "Mode": "add", "ShapeFeather": "25", "ShapeBlur": "0",
    }  # fmt: skip
    assert set(gradient) == {k for k, _ in SHAPE_DEFAULTS["gradient"]}


def test_regions_and_masks_read_back_typed_and_the_rest_stays_raw():
    changes = WorkingChanges(profile())
    request = {"regions": [
        {"r": {"slope": 1.1844, "power": 1.0204}, "b": {"slope": 0.9239, "power": 0.6241}},
        {"b": {"slope": 0.85}, "mask": ELLIPSE},
    ]}  # fmt: skip
    changes.edit(adj(color_correction=request), [])

    view = read_format(changes.profile)

    typed = view.adjustments["color_correction"]
    assert typed["enabled"] is True and len(typed["regions"]) == 2
    first, second = typed["regions"]
    assert first["r"] == {"slope": 1.1844, "offset": 0.0, "power": 1.0204}
    assert first["g"] == {"slope": 1.0, "offset": 0.0, "power": 1.0}
    assert first["mask"] == {"enabled": False, "inverted": False, "feather": 0.0, "blur": 0.0, "shapes": []}
    assert second["b"]["slope"] == 0.85
    assert second["mask"]["inverted"] is True and second["mask"]["feather"] == 5
    assert second["mask"]["shapes"][0]["roundness"] == 100 and second["mask"]["shapes"][0]["type"] == "rectangle"
    raw = view.raw["ColorCorrection"]
    assert "SlopeR_1" not in raw and "AreaMaskType_2" not in raw and "Mode_2" not in raw
    assert raw["PivotR_1"] == "1" and raw["MaskEnabled_2"] == "true"
    # What typed reading says, writing it again changes nothing.
    again = WorkingChanges(changes.profile)
    assert again.edit(adj(color_correction=typed), []).changed == []


def test_a_region_in_another_mode_reads_as_null_and_stays_raw():
    view = read_format(profile())

    assert view.adjustments["color_correction"] == {"enabled": False, "regions": [None]}
    assert view.raw["ColorCorrection"]["Mode_1"] == "Jzazbz"
    assert view.raw["ColorCorrection"]["SlopeR_1"] == "1"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ParametricMaskEnabled_2", "true"), ("DrawnMaskEnabled_2", "true"),
        ("LinkedMaskEnabled_2", "true"), ("ExternalMaskEnabled_2", "true"),
        ("DeltaEMaskEnabled_2", "true"), ("AreaMaskType_2", "polygon"),
        ("MaskEnabled_2", "false"), ("MaskOpacity_2", "50"),
    ],
)  # fmt: skip
def test_unsupported_masks_leave_that_region_raw(key, value):
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {"mask": ELLIPSE}]}), [])
    changes.edit(None, [RawEdit(group="ColorCorrection", key="AreaMaskType_2", value="rectangle")])
    changes.edit(None, [RawEdit(group="ColorCorrection", key=key, value=value)])

    view = read_format(changes.profile)

    assert view.adjustments["color_correction"]["regions"][1] is None
    assert view.raw["ColorCorrection"]["SlopeB_2"] == "1" and "Mode_2" in view.raw["ColorCorrection"]
    with pytest.raises(AdjustmentError, match=r"regions\.1\.mask.*raw edits"):
        changes.edit(adj(color_correction={"regions": [None, {"mask": {"inverted": False}}]}), [])


def test_values_of_a_region_with_an_unsupported_mask_can_still_be_edited():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {}]}), [])
    changes.edit(None, [RawEdit(group="ColorCorrection", key="DrawnMaskEnabled_2", value="true")])

    result = changes.edit(adj(color_correction={"regions": [None, {"r": {"slope": 2}}]}), [])

    assert result.changed == [RawEdit(group="ColorCorrection", key="SlopeR_2", value="2")]


def test_editing_a_region_changes_only_those_keys():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {"b": {"slope": 0.85}, "mask": ELLIPSE}]}), [])
    settled = WorkingChanges(changes.profile)

    result = settled.edit(
        adj(color_correction={"regions": [None, {"b": {"slope": 0.8}, "mask": {"feather": 7,
            "shapes": [{"type": "rectangle", "feather": 40}]}}]}),
        [],
    )  # fmt: skip

    assert {(e.key, e.value) for e in result.changed} == {
        ("SlopeB_2", "0.8"), ("AreaMaskFeather_2", "7"), ("AreaMaskShapeFeather_2", "40"),
    }  # fmt: skip
    assert result.implied == []
    assert settled.profile["ColorCorrection"]["AreaMaskWidth_2"] == "110"


def test_a_shape_of_another_type_replaces_the_shape_with_a_complete_key_set():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {"mask": ELLIPSE}]}), [])

    changes.edit(adj(color_correction={"regions": [None, {"mask": {"shapes": [{"type": "gradient"}]}}]}), [])

    group = changes.profile["ColorCorrection"]
    assert group["AreaMaskType_2"] == "gradient" and group["AreaMaskStrengthStart_2"] == "100"
    assert group["AreaMaskShapeFeather_2"] == "25"


def test_a_shape_past_the_end_is_refused_rather_than_silently_dropped_by_ART():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {"mask": ELLIPSE}]}), [])
    before = {g: dict(v) for g, v in changes.profile.items()}

    with pytest.raises(AdjustmentError) as e:
        changes.edit(adj(color_correction={"regions": [None, {"mask": {"shapes": [
            None, None, {"type": "gradient"}]}}]}), [])  # fmt: skip

    assert e.value.code == "out_of_range"
    assert "1 shape(s)" in str(e.value) and "index 1" in str(e.value)
    assert changes.profile == before


def test_a_shape_at_the_count_is_appended_with_the_complete_key_set():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"regions": [None, {"mask": ELLIPSE}]}), [])

    changes.edit(adj(color_correction={"regions": [None, {"mask": {"shapes": [
        {"type": "rectangle"}, {"type": "gradient", "x": 5}]}}]}), [])  # fmt: skip

    group = changes.profile["ColorCorrection"]
    appended = {k for k in group if k.startswith("AreaMask_1_")}
    assert appended == {f"AreaMask_1_{base}_2" for base, _ in SHAPE_DEFAULTS["gradient"]}
    assert group["AreaMask_1_X_2"] == "5"


def test_a_region_past_the_end_must_be_the_next_one():
    changes = WorkingChanges(profile())

    with pytest.raises(AdjustmentError, match=r"regions\.2.*1 region.*index 1"):
        changes.edit(adj(color_correction={"regions": [None, None, {}]}), [])
    assert "Mode_2" not in changes.profile["ColorCorrection"]


def test_without_a_color_correction_group_region_one_is_created_and_the_tool_enabled():
    changes = WorkingChanges({"Version": {"Version": "1045"}})

    result = changes.edit(adj(color_correction={"regions": [{"r": {"slope": 1.2}}]}), [])

    group = changes.profile["ColorCorrection"]
    assert keys(group, 1) == {k for k, _ in REGION_DEFAULTS} and group["Mode_1"] == "RGB"
    assert group["Enabled"] == "true" and group["SlopeR_1"] == "1.2"
    assert RawEdit(group="ColorCorrection", key="Enabled", value="true") in result.implied


def test_raw_edits_still_need_an_existing_key_but_typed_edits_may_create_keys():
    changes = WorkingChanges(profile())

    with pytest.raises(UnknownKey):
        changes.edit(None, [RawEdit(group="ColorCorrection", key="SlopeB_2", value="0.9")])
    changes.edit(adj(color_correction={"regions": [None, {}]}), [])
    changes.edit(None, [RawEdit(group="ColorCorrection", key="PivotB_2", value="0.18")])

    assert changes.profile["ColorCorrection"]["PivotB_2"] == "0.18"


def test_a_partial_profile_carries_every_region_whole():
    """ART replaces all regions with what a profile lists, defaults for missing
    keys: one changed region key must bring every region key along."""
    base = profile()
    base["ColorCorrection"].update({"Mode_1": "RGB", "SlopeR_1": "1.3"})
    changes = WorkingChanges(base)
    changes.edit(adj(color_correction={"regions": [{"b": {"power": 0.62}}]}), [])

    partial = changes.partial_profile()["ColorCorrection"]

    assert partial["PowerB_1"] == "0.62"
    assert partial["Mode_1"] == "RGB" and partial["SlopeR_1"] == "1.3"
    assert keys(partial, 1) == {k for k, _ in REGION_DEFAULTS}
    assert "ShowMask" not in partial and "Enabled" in partial


def test_a_partial_profile_without_region_changes_stays_small():
    changes = WorkingChanges(profile())
    changes.edit(adj(color_correction={"enabled": True}), [])

    assert changes.partial_profile() == {"ColorCorrection": {"Enabled": "true"}}


def test_a_changed_back_region_is_not_in_the_partial_profile():
    changes = WorkingChanges(profile())
    changes.edit(None, [RawEdit(group="ColorCorrection", key="SlopeR_1", value="2")])
    changes.edit(None, [RawEdit(group="ColorCorrection", key="SlopeR_1", value="1")])

    assert changes.partial_profile() == {}


def test_a_partial_profile_vs_default_carries_every_region_whole_too():
    default = profile()
    default["ColorCorrection"].update({f"{k}_1": v for k, v in REGION_DEFAULTS})
    graded = {group: dict(entries) for group, entries in default.items()}
    graded["ColorCorrection"]["SlopeR_1"] = "1.3"

    partial = partial_vs_default(graded, default)["ColorCorrection"]

    assert partial["SlopeR_1"] == "1.3"
    assert keys(partial, 1) == {k for k, _ in REGION_DEFAULTS}
    assert "Enabled" not in partial


def test_a_partial_profile_vs_default_without_region_changes_has_no_regions():
    default = profile()
    default["ColorCorrection"].update({f"{k}_1": v for k, v in REGION_DEFAULTS})
    same_regions = {group: dict(entries) for group, entries in default.items()}
    same_regions["ColorCorrection"]["Enabled"] = "true"

    assert partial_vs_default(same_regions, default) == {"ColorCorrection": {"Enabled": "true"}}


@pytest.mark.parametrize(
    "request_",
    [
        {"regions": [{"r": {"slope": 11}}]},
        {"regions": [{"b": {"offset": 0.2}}]},
        {"regions": [{"b": {"power": 0}}]},
        {"regions": [{"mask": {"feather": 101}}]},
        {"regions": [{"mask": {"shapes": [{"type": "rectangle", "x": 101}]}}]},
        {"regions": [{"mask": {"shapes": [{"type": "rectangle", "roundness": 101}]}}]},
        {"regions": [{"mask": {"shapes": [{"type": "rectangle", "mode": "xor"}]}}]},
        {"regions": [{"mask": {"shapes": [{"type": "polygon"}]}}]},
        {"regions": [{"mask": {"shapes": [{"type": "gradient", "strength_end": 101}]}}]},
        {"regions": [{"mask": {"shapes": [{"type": "rectangle", "strength_end": 1}]}}]},
    ],
)
def test_bad_values_are_rejected_without_clamping(request_):
    with pytest.raises(AdjustmentError):
        adj(color_correction=request_)


def test_unknown_names_are_unknown_key():
    with pytest.raises(AdjustmentError) as e:
        adj(color_correction={"regions": [{"r": {"gain": 1}}]})

    assert e.value.code == "unknown_key"


def test_the_description_states_ARTs_semantics_and_the_mask_coordinates():
    tool = describe_adjustments().tools["color_correction"]

    assert tool.group == "ColorCorrection"
    for phrase in ("v*slope + offset/2", "inverse", "0.5 squares", "image centre", "outside its shapes"):
        assert phrase in tool.description
    # x, y are % of HALF the width / height (ART: centre = w/2 + x/100 * w/2), unlike width, height
    assert "% of HALF the image's width and height" in tool.description
    assert "100 puts the shape's centre on the right or bottom edge" in tool.description
    assert set(tool.fields) == {"enabled", "regions"}


def test_key_names_are_regions_and_not_mistaken_for_group_keys():
    assert is_region_key("SlopeR_1") and is_region_key("AreaMask_1_Type_12")
    assert not is_region_key("Enabled") and not is_region_key("ShowMask")
