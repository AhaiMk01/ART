import pytest

from art_mcp.profile import RawEdit, UnknownKey, WorkingChanges, edit_result, read_format
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
