import json

import pytest

from art_mcp.profile import (
    EditItem,
    ImageEdit,
    RawEdit,
    UnknownKey,
    WorkingChanges,
    check_batch_paths,
    check_edit_targets,
    check_exclusions,
    drop_excluded,
    edit_item,
    edit_requests,
    edit_result,
    failed_edit,
    read_format,
)
from art_mcp.schema import parse_adjustments


def profile():
    return {
        "Version": {"Version": "1045"},
        "Exposure": {"Enabled": "true", "Compensation": "0"},
        "Sharpening": {"Enabled": "false"},
    }


def edit(group, key, value):
    return RawEdit(group=group, key=key, value=value)


def test_partial_profile_holds_only_the_keys_the_agent_changed():
    changes = WorkingChanges(profile())

    changes.apply([edit("Exposure", "Compensation", "1"), edit("Sharpening", "Enabled", "true")])

    assert changes.partial_profile() == {
        "Exposure": {"Compensation": "1"},
        "Sharpening": {"Enabled": "true"},
    }


def test_changed_reports_final_values_once_and_skips_no_ops():
    changes = WorkingChanges(profile())

    changed = changes.apply([
        edit("Exposure", "Compensation", "2"),
        edit("Exposure", "Compensation", "3"),
        edit("Exposure", "Enabled", "true"),
        edit("Sharpening", "Enabled", "true"),
        edit("Sharpening", "Enabled", "false"),
    ])

    assert changed == [edit("Exposure", "Compensation", "3")]


def test_read_format_shows_the_version_once():
    view = read_format(profile())

    assert view.ppversion == 1045
    assert "Version" not in view.raw


def rich_profile():
    return {
        "Version": {"Version": "1045"},
        "Exposure": {"Enabled": "true", "Compensation": "0", "Black": "0", "Untyped": "x"},
        "Rotation": {"Enabled": "false", "Degree": "0"},
        "Common Properties for Transformations": {"AutoFill": "true", "Method": "log"},
        "ToneCurve": {"Enabled": "true", "Curve": "0;", "Curve2": "0;", "WhitePoint": "1"},
        "Film Negative": {"Enabled": "false", "RedRatio": "1.36", "BlueRatio": "0.86"},
        "RAW": {"CAEnabled": "true", "CA": "true"},
        "RAW Bayer": {"Method": "rcd", "Border": "4"},
    }


def test_read_format_of_chosen_groups_holds_only_those_groups():
    view = read_format(rich_profile(), groups=["Exposure", "RAW Bayer"])

    assert set(view.adjustments) == {"exposure"}
    assert view.raw == {"Exposure": {"Untyped": "x"}, "RAW Bayer": {"Method": "rcd", "Border": "4"}}
    assert view.ppversion == 1045


def test_a_tool_is_chosen_by_each_group_its_fields_live_in():
    view = read_format(rich_profile(), groups=["Common Properties for Transformations"])

    assert set(view.adjustments) == {"rotation"}
    assert view.adjustments["rotation"]["auto_fill"] is True
    assert view.raw == {"Common Properties for Transformations": {"Method": "log"}}


def test_an_unknown_group_lists_the_valid_ones():
    with pytest.raises(UnknownKey) as e:
        read_format(rich_profile(), groups=["Exposure", "Film negative"])

    message = str(e.value)
    assert "Film negative" in message
    assert "Film Negative" in message and "RAW Bayer" in message
    assert "Version" not in message


def test_changed_only_holds_the_fields_and_keys_that_differ_from_the_default():
    changes = WorkingChanges(rich_profile())
    changes.edit(
        parse_adjustments({"exposure": {"compensation": 0.5}, "film_negative": {"red_ratio": 1.4}}),
        [edit("RAW Bayer", "Method", "amaze")],
    )

    view = read_format(changes.profile, default=rich_profile())

    assert view.adjustments == {
        "exposure": {"compensation": 0.5},
        "film_negative": {"enabled": True, "red_ratio": 1.4},  # adjusting a tool turned it on
    }
    assert view.raw == {"RAW Bayer": {"Method": "amaze"}}


def test_changed_only_of_an_untouched_profile_is_empty():
    view = read_format(rich_profile(), default=rich_profile())

    assert view.adjustments == {} and view.raw == {}
    assert view.ppversion == 1045


def test_changed_only_shows_a_key_the_default_does_not_have():
    default = rich_profile()
    del default["RAW Bayer"]["Border"]
    del default["ToneCurve"]["WhitePoint"]

    view = read_format(rich_profile(), default=default)

    assert view.raw["RAW Bayer"] == {"Border": "4"}
    assert view.raw["ToneCurve"] == {"WhitePoint": "1"}


def test_changed_only_and_groups_combine():
    changes = WorkingChanges(rich_profile())
    changes.edit(parse_adjustments({"exposure": {"compensation": 0.5}}), [edit("RAW Bayer", "Method", "amaze")])

    view = read_format(changes.profile, groups=["RAW Bayer"], default=rich_profile())

    assert view.adjustments == {}
    assert view.raw == {"RAW Bayer": {"Method": "amaze"}}


def edited(adjustments=None, raw_edits=(), full=False):
    """The edit result of a request on ``rich_profile``."""
    changes = WorkingChanges(rich_profile())
    parsed = parse_adjustments(adjustments) if adjustments else None
    outcome = changes.edit(parsed, list(raw_edits))
    return edit_result(outcome, changes.profile, parsed, list(raw_edits), [], full=full)


def test_edit_result_groups_the_changed_values_and_keeps_the_implied_ones_apart():
    result = edited({"film_negative": {"red_ratio": 1.4}}, [edit("RAW Bayer", "Method", "amaze")])

    assert result.changed == {"Film Negative": {"RedRatio": "1.4"}, "RAW Bayer": {"Method": "amaze"}}
    assert result.implied == {"Film Negative": {"Enabled": "true"}}
    assert result.warnings == [] and result.profile is None


def test_a_raw_edit_of_a_key_an_adjustment_only_implies_is_asked_for():
    result = edited({"film_negative": {"red_ratio": 1.4}}, [edit("Film Negative", "Enabled", "false")])

    assert result.changed == {"Film Negative": {"RedRatio": "1.4"}}
    assert result.implied == {}


def test_edit_result_reads_back_the_drawn_line_of_a_curve_it_set():
    spline = {"type": "spline", "points": [[0, 0], [0.5, 0.6], [1, 1]]}

    result = edited({"tone_curve": {"curve1": spline, "curve2": {"type": "linear"}}})

    assert list(result.drawn) == ["curve1"]  # a linear curve draws nothing
    assert len(result.drawn["curve1"]) == 9 and result.drawn["curve1"][4] == [0.5, 0.6]
    assert result.changed["ToneCurve"]["Curve"] == "1;0;0;0.5;0.6;1;1;"


def test_edit_result_without_a_curve_has_no_drawn_line():
    assert edited({"exposure": {"compensation": 1}}).drawn == {}


def test_full_edit_result_echoes_the_groups_the_request_touched():
    result = edited(
        {"film_negative": {"red_ratio": 1.4}}, [edit("RAW Bayer", "Method", "amaze")], full=True
    )

    assert result.profile is not None
    assert set(result.profile.adjustments) == {"film_negative"}
    assert result.profile.adjustments["film_negative"]["red_ratio"] == 1.4
    assert result.profile.raw == {"RAW Bayer": {"Method": "amaze", "Border": "4"}}


def test_full_edit_result_echoes_the_requested_groups_even_when_nothing_changed():
    result = edited({"exposure": {"compensation": 0}}, full=True)

    assert result.changed == {}
    assert result.profile is not None and set(result.profile.adjustments) == {"exposure"}


def test_an_edit_result_without_the_full_echo_leaves_the_profile_field_out_when_serialised():
    result = edited({"exposure": {"compensation": 1}})

    assert result.profile is None  # the attribute stays; the wire has no `"profile": null`
    assert "profile" not in result.model_dump()
    assert "profile" not in json.loads(result.model_dump_json())
    assert "profile" in edited({"exposure": {"compensation": 1}}, full=True).model_dump()


def test_a_batch_item_counts_the_asked_for_changes_and_keeps_the_implied_ones_and_the_warnings():
    result = edited({"film_negative": {"red_ratio": 1.4}}, [edit("RAW Bayer", "Method", "amaze")])
    result.warnings.append("a note")

    item = edit_item("a.ARW", result)

    assert item == ImageEdit(
        path="a.ARW", changed=2, implied={"Film Negative": {"Enabled": "true"}}, warnings=["a note"], error=None
    )


def test_a_batch_item_of_an_edit_that_changed_nothing_counts_zero():
    assert edit_item("a.ARW", edited({"exposure": {"compensation": 0}})).changed == 0


def test_a_failed_batch_item_has_only_its_error():
    item = failed_edit("a.ARW", "not_open: a.ARW is not open")

    assert item == ImageEdit(path="a.ARW", changed=None, implied={}, warnings=[], error="not_open: a.ARW is not open")


def oops(code, message):
    return ValueError(f"{code}: {message}")


def test_edit_targets_are_one_path_or_a_list_of_up_to_fifty():
    assert check_edit_targets("a.ARW", None, False, oops) is None
    assert check_edit_targets(None, ["a.ARW", "b.ARW"], False, oops) == ["a.ARW", "b.ARW"]
    assert check_edit_targets(None, [f"{i}.ARW" for i in range(50)], False, oops) is not None


@pytest.mark.parametrize(
    ("path", "paths", "full", "text"),
    [
        ("a.ARW", ["b.ARW"], False, "not both"),
        (None, None, False, "path or paths"),
        (None, [], False, "paths is empty"),
        (None, [f"{i}.ARW" for i in range(51)], False, "51 entries; the most one call takes is 50"),
        (None, ["a.ARW"], True, "full"),
    ],
)
def test_bad_edit_targets_are_out_of_range(path, paths, full, text):
    with pytest.raises(ValueError, match=f"out_of_range: .*{text}"):
        check_edit_targets(path, paths, full, oops)


def test_batch_paths_are_one_path_or_a_list_of_up_to_fifty():
    assert check_batch_paths("a.ARW", None, oops) is None
    assert check_batch_paths(None, ["a.ARW", "b.ARW"], oops) == ["a.ARW", "b.ARW"]
    assert check_batch_paths(None, [f"{i}.ARW" for i in range(50)], oops) is not None


@pytest.mark.parametrize(
    ("path", "paths", "text"),
    [
        ("a.ARW", ["b.ARW"], "not both"),
        (None, None, "path or paths"),
        (None, [], "paths is empty"),
        (None, [f"{i}.ARW" for i in range(51)], "51 entries; the most one call takes is 50"),
    ],
)
def test_bad_batch_paths_are_out_of_range(path, paths, text):
    with pytest.raises(ValueError, match=f"out_of_range: .*{text}"):
        check_batch_paths(path, paths, oops)


SHARED = {"exposure": {"compensation": 1}}
SHARED_RAW = [edit("Exposure", "Black", "5")]


def test_edit_requests_are_the_one_path_none_or_one_edit_per_image():
    assert edit_requests("a.ARW", None, None, SHARED, None, False, oops) is None
    # paths: every image gets the call's own edit; items: each its own
    assert edit_requests(None, ["a.ARW", "b.ARW"], None, SHARED, SHARED_RAW, False, oops) == [
        EditItem(path="a.ARW", adjustments=SHARED, raw_edits=SHARED_RAW),
        EditItem(path="b.ARW", adjustments=SHARED, raw_edits=SHARED_RAW),
    ]
    items = [EditItem(path="a.ARW", adjustments=SHARED), EditItem(path="b.ARW", raw_edits=SHARED_RAW)]
    assert edit_requests(None, None, items, None, None, False, oops) == items
    assert edit_requests(None, None, items * 25, None, None, False, oops) is not None  # fifty


@pytest.mark.parametrize(
    ("given", "text"),
    [
        ({}, "path or paths, or items"),
        ({"path": "a.ARW", "paths": ["a.ARW"]}, "not both"),  # the call before items
        ({"path": "a.ARW", "items": [EditItem(path="a.ARW")]}, "not path and items"),
        ({"paths": ["a.ARW"], "items": [EditItem(path="a.ARW")]}, "not paths and items"),
        ({"path": "a.ARW", "paths": ["a.ARW"], "items": [EditItem(path="a.ARW")]}, "not path and paths and items"),
        ({"items": []}, "items is empty"),
        ({"items": [EditItem(path="a.ARW")] * 51}, "items has 51 entries; the most one call takes is 50"),
        ({"items": [EditItem(path="a.ARW")], "full": True}, "full is for one image"),
        ({"items": [EditItem(path="a.ARW")], "adjustments": SHARED}, "in each item"),
        ({"items": [EditItem(path="a.ARW")], "raw_edits": SHARED_RAW}, "in each item"),
    ],
)
def test_bad_edit_requests_are_out_of_range(given, text):
    args = {"path": None, "paths": None, "items": None, "adjustments": None, "raw_edits": None, "full": False}
    with pytest.raises(ValueError, match=f"out_of_range: .*{text}"):
        edit_requests(**(args | given), error=oops)


def test_an_edit_item_is_a_path_with_its_own_adjustments_and_raw_edits_and_nothing_else():
    raw = {"group": "Exposure", "key": "Black", "value": "5"}
    item = EditItem.model_validate({"path": "a.ARW", "adjustments": SHARED, "raw_edits": [raw]})

    assert item.adjustments == SHARED and item.raw_edits == SHARED_RAW
    assert EditItem(path="a.ARW").adjustments is None
    with pytest.raises(ValueError):
        EditItem.model_validate({"path": "a.ARW", "adjusments": SHARED})
    with pytest.raises(ValueError):
        EditItem.model_validate({"adjustments": SHARED})


def test_exclusions_name_a_group_or_a_group_and_key_of_the_profile():
    check_exclusions(profile(), ["Exposure", "Exposure/Compensation", "Sharpening"])

    for bad in ("Nonsense", "Exposure/Nonsense"):
        with pytest.raises(UnknownKey, match=f"exclude '{bad}': not in this image's processing profile"):
            check_exclusions(profile(), [bad])


def test_dropping_exclusions_removes_the_group_or_the_key_and_counts_what_went():
    keys = {"Exposure": {"Compensation": "2", "Black": "5"}, "Film Negative": {"RedRatio": "1.3"}}

    dropped = drop_excluded(keys, ["Exposure/Black", "Film Negative", "Crop", "Exposure/Nope"])

    assert keys == {"Exposure": {"Compensation": "2"}}
    assert dropped == {"Exposure/Black": 1, "Film Negative": 1, "Crop": 0, "Exposure/Nope": 0}


def test_a_group_left_without_keys_by_the_exclusions_goes_too():
    keys = {"Exposure": {"Black": "5"}, "Crop": {"X": "1"}}

    drop_excluded(keys, ["Exposure/Black"])

    assert keys == {"Crop": {"X": "1"}}
