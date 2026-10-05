"""The pure part of a contact-sheet pass's `changes`: numbers shown in their shortest form, numerically equal
values never a change, and the changes of many frames grouped by identical change."""

import pytest

from art_mcp.render.sheet_changes import (
    ChangeSummary,
    KeyChange,
    SharedChange,
    changes_between,
    normalise_value,
    same_value,
    summarise,
)

# -- normalise_value ----------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "shown"),
    [
        ("1.3700000000000001", "1.37"),
        ("0.59999999999999998", "0.6"),
        ("-0.021600000000000001", "-0.0216"),
        ("0.098000000000000004", "0.098"),
        ("2.2000000000000002", "2.2"),
        ("1.50", "1.5"),
        ("1e-05", "1e-05"),
        ("0.00001", "1e-05"),
        (".5", "0.5"),
        ("1.", "1.0"),
    ],
)
def test_a_decimal_is_shown_in_its_shortest_round_trip_form(written, shown):
    assert normalise_value(written) == shown
    assert float(shown) == float(written)  # the same double: nothing was lost


@pytest.mark.parametrize("value", ["0", "1045", "4326", "13000", "-7", "+5", "0012", "123456789012345678901"])
def test_an_integer_stays_as_it_was_written(value):
    assert normalise_value(value) == value


@pytest.mark.parametrize(
    "value",
    ["Balanced", "true", "dc9571efc", "", "nan", "inf", "1e999999", "1_000", " 1.5", "1.5 ", "0x10", "1,5", "None"],
)
def test_anything_that_is_not_a_plain_number_is_left_alone(value):
    assert normalise_value(value) == value


def test_a_missing_value_stays_missing():
    assert normalise_value(None) is None


def test_a_curve_is_normalised_token_by_token():
    curve = "1;0.098000000000000004;0;0.59999999999999998;0.59999999999999998;1;1;"

    assert normalise_value(curve) == "1;0.098;0;0.6;0.6;1;1;"


def test_a_list_keeps_its_separators_and_its_text_tokens():
    assert normalise_value("0;0;0;") == "0;0;0;"
    assert normalise_value("4326;2069;1134") == "4326;2069;1134"
    assert normalise_value("Name;1.5000000000000001;;x") == "Name;1.5;;x"


# -- same_value ---------------------------------------------------------------


def test_the_same_number_written_differently_is_the_same_value():
    assert same_value("-0.0216", "-0.021600000000000001")
    assert same_value("1.5", "1.50")
    assert same_value("1", "1.0")
    assert same_value("0", "-0.0")
    assert same_value("+5", "5")


def test_lists_are_the_same_when_every_token_is():
    assert same_value("1;0.6;0;", "1;0.59999999999999998;0;")
    assert not same_value("1;0.6;0;", "1;0.61;0;")
    assert not same_value("1;2;", "1;2")  # a token more
    assert not same_value("1;2;", "1;2;3;")


def test_different_numbers_and_different_text_are_different_values():
    assert not same_value("1.37", "1.3700000001")
    assert not same_value("Off", "off")
    assert not same_value("1.5", "abc")
    assert not same_value("abc", "1.5")
    assert same_value("abc", "abc")


def test_a_missing_value_differs_from_any_value_and_equals_a_missing_one():
    assert not same_value(None, "0")
    assert not same_value("", None)
    assert same_value(None, None)


def test_beyond_double_precision_integers_are_compared_exactly():
    assert not same_value("9007199254740993", "9007199254740992")
    assert same_value("9007199254740992", "9007199254740992.0")


# -- changes_between ----------------------------------------------------------


def test_changes_are_normalised_in_the_before_and_the_after():
    before = {"Film Negative": {"RedRatio": "1.355", "RefInput": "0;0;0;"}}
    after = {"Film Negative": {"RedRatio": "1.3700000000000001", "RefInput": "4326;2069;1134"}}

    assert changes_between(before, after) == [
        KeyChange(group="Film Negative", key="RedRatio", before="1.355", after="1.37"),
        KeyChange(group="Film Negative", key="RefInput", before="0;0;0;", after="4326;2069;1134"),
    ]


def test_a_value_written_differently_but_numerically_equal_is_not_a_change():
    before = {"Exposure": {"Compensation": "-0.0216", "Curve": "1;0.6;1;"}, "Crop": {"X": "10"}}
    after = {
        "Exposure": {"Compensation": "-0.021600000000000001", "Curve": "1;0.59999999999999998;1;"},
        "Crop": {"X": "10.0"},
    }

    assert changes_between(before, after) == []


def test_a_curve_that_changes_in_one_token_is_one_change_shown_short():
    before = {"ToneCurve": {"Curve": "1;0.098000000000000004;0;0.6;0.6;1;1;"}}
    after = {"ToneCurve": {"Curve": "1;0.12;0;0.59999999999999998;0.59999999999999998;1;1;"}}

    assert changes_between(before, after) == [
        KeyChange(group="ToneCurve", key="Curve", before="1;0.098;0;0.6;0.6;1;1;", after="1;0.12;0;0.6;0.6;1;1;")
    ]


def test_added_and_removed_keys_and_groups_are_changes_with_a_null_side():
    before = {"A": {"x": "1", "gone": "0.10000000000000001"}, "Old": {"k": "v"}}
    after = {"A": {"x": "1", "new": "2.2000000000000002"}, "New": {"k": "w"}}

    assert changes_between(before, after) == [
        KeyChange(group="A", key="gone", before="0.1", after=None),
        KeyChange(group="A", key="new", before=None, after="2.2"),
        KeyChange(group="Old", key="k", before="v", after=None),
        KeyChange(group="New", key="k", before=None, after="w"),
    ]


# -- summarise ----------------------------------------------------------------


def change(key, before="0", after="1", group="Exposure"):
    return KeyChange(group=group, key=key, before=before, after=after)


def test_one_change_on_three_frames_is_one_entry_listing_the_three_file_names():
    ratio = change("RedRatio", "1.355", "1.37", "Film Negative")
    per_image = [("A.ARW", [ratio]), ("B.ARW", [ratio]), ("C.ARW", [ratio, change("Black")])]

    summary = summarise(per_image)

    assert summary == ChangeSummary(
        groups=[
            SharedChange(
                group="Film Negative", key="RedRatio", before="1.355", after="1.37", images=["A.ARW", "B.ARW", "C.ARW"]
            ),
            SharedChange(group="Exposure", key="Black", before="0", after="1", images=["C.ARW"]),
        ],
        more=0,
    )


def test_a_change_to_another_value_is_another_entry_even_on_the_same_key():
    per_image = [("A.ARW", [change("Black", "0", "1")]), ("B.ARW", [change("Black", "0", "2")])]

    groups = summarise(per_image).groups

    assert [(g.after, g.images) for g in groups] == [("1", ["A.ARW"]), ("2", ["B.ARW"])]


def test_entries_are_sorted_by_how_many_frames_share_them_then_by_name():
    per_image = [
        ("A.ARW", [change("Zeta"), change("Beta", group="Exposure"), change("Alpha", group="Crop")]),
        ("B.ARW", [change("Zeta"), change("Beta", group="Exposure")]),
        ("C.ARW", [change("Zeta")]),
    ]

    names = [(g.group, g.key, len(g.images)) for g in summarise(per_image).groups]

    assert names == [("Exposure", "Zeta", 3), ("Exposure", "Beta", 2), ("Crop", "Alpha", 1)]


def test_equally_shared_changes_are_ordered_by_group_then_key():
    per_image = [("A.ARW", [change("b", group="Z"), change("b", group="A"), change("a", group="Z")])]

    names = [(g.group, g.key) for g in summarise(per_image).groups]

    assert names == [("A", "b"), ("Z", "a"), ("Z", "b")]


def test_only_the_most_shared_entries_are_listed_and_more_counts_the_rest():
    per_image = [
        ("A.ARW", [change(f"k{i:02d}") for i in range(30)]),
        ("B.ARW", [change("k29"), change("k28")]),
    ]

    summary = summarise(per_image, limit=25)

    assert len(summary.groups) == 25 and summary.more == 5
    assert [g.key for g in summary.groups[:2]] == ["k28", "k29"]  # the shared ones come first
    assert summary.groups[2].key == "k00"


def test_exactly_as_many_entries_as_the_limit_leaves_nothing_more():
    summary = summarise([("A.ARW", [change("a"), change("b")])], limit=2)

    assert len(summary.groups) == 2 and summary.more == 0


def test_the_limit_defaults_to_25():
    summary = summarise([("A.ARW", [change(f"k{i:02d}") for i in range(40)])])

    assert len(summary.groups) == 25 and summary.more == 15


def test_frames_with_nothing_to_compare_count_for_nothing_and_changes_none_means_no_comparison_at_all():
    assert summarise([("A.ARW", None), ("B.ARW", None)]) is None
    assert summarise([]) is None
    assert summarise([("A.ARW", None), ("B.ARW", [change("Black")])]).groups[0].images == ["B.ARW"]


def test_compared_frames_with_no_change_give_an_empty_summary_not_none():
    assert summarise([("A.ARW", []), ("B.ARW", [])]) == ChangeSummary(groups=[], more=0)
