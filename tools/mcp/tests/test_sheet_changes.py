"""The pure part of a contact-sheet pass's `changes`: numbers shown with at most seven significant digits, values
that are the same 32-bit float never a change, and the changes of many frames grouped by identical change."""

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
        ("1.3700000047683716", "1.37"),  # 1.37 as ART's 32-bit float writes it back
        ("6450.7001953125", "6450.7"),
        ("2347.89990234375", "2347.9"),
        ("0.59999999999999998", "0.6"),
        ("-0.021600000000000001", "-0.0216"),
        ("0.098000000000000004", "0.098"),
        ("2.2000000000000002", "2.2"),
        ("1.50", "1.5"),
        ("3.14159265358979", "3.141593"),
        ("0.123456789", "0.1234568"),
        ("-1234.56789", "-1234.568"),
        ("1234567.4", "1234567"),
        ("1e-05", "1e-05"),
        ("0.00001", "1e-05"),
        ("9.999999717180685e-10", "1e-09"),
        (".5", "0.5"),
        ("1.", "1"),
        ("3750.0", "3750"),
    ],
)
def test_a_decimal_is_shown_with_at_most_seven_significant_digits(written, shown):
    assert normalise_value(written) == shown
    assert float(shown) == pytest.approx(float(written), rel=1e-6)  # nothing that matters was lost


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


def test_a_list_of_32_bit_floats_is_shown_short_with_its_final_separator_as_written():
    assert normalise_value("6450.7001953125;3750;2347.89990234375;") == "6450.7;3750;2347.9;"
    assert normalise_value("6450.7;3750;2347.9") == "6450.7;3750;2347.9"


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
    assert not same_value("1;2;", "1;2;3;")  # a token more
    assert not same_value("1;2;", "1;2;;")  # an empty token more


def test_a_number_and_the_32_bit_float_art_writes_back_are_the_same_value():
    # the left is what an agent types, the right what art-cli writes back for it
    assert same_value("6450.7", "6450.7001953125")
    assert same_value("2347.9", "2347.89990234375")
    assert same_value("1.37", "1.3700000047683716")
    assert same_value("-0.0216", "-0.02160000056028366")
    assert same_value("0.6", "0.6000000238418579")
    assert same_value("1e-9", "9.999999717180685e-10")
    assert same_value("1e-30", "1.0000000031710769e-30")
    assert same_value("3750", "3750.0")


def test_the_threshold_is_a_relative_difference_of_one_in_a_million():
    assert same_value("1", "1.0000009")
    assert not same_value("1", "1.000002")
    assert same_value("123456.7", "123456.8")  # 8e-7 of the value
    assert not same_value("123456.7", "123457.9")  # 1e-5 of it


def test_a_real_difference_is_a_different_value_however_small_the_numbers():
    assert not same_value("6450.7", "6450.8")
    assert not same_value("1.37", "1.371")
    assert not same_value("6450.7", "-6450.7")
    assert not same_value("1e-30", "2e-30")
    assert not same_value("0.0001", "0.00011")


def test_zero_is_the_same_only_as_zero():
    assert same_value("0", "0.0")
    assert same_value("0", "-0.0")
    assert not same_value("0", "1e-9")
    assert not same_value("1e-9", "0")
    assert not same_value("0.0", "-1e-30")


def test_list_tokens_are_compared_one_by_one_as_numbers():
    assert same_value("6450.7001953125;3750;2347.89990234375;", "6450.7;3750;2347.9;")
    assert not same_value("6450.7001953125;3750;2347.89990234375;", "6450.7;3750;2348.9;")
    assert not same_value("6450.7001953125;3750;2347.89990234375;", "6450.7;3750;2347.9;4")
    assert same_value("Name;1.5000000000000001;;x", "Name;1.5;;x")
    assert not same_value("Name;1.5;;x", "Other;1.5;;x")


def test_a_list_is_the_same_with_or_without_its_final_separator():
    # typed by an agent on the left, as art-cli writes it on the right (a GLib key file reads both alike)
    assert same_value("6450.7;3750;2347.9", "6450.7001953125;3750;2347.89990234375;")
    assert same_value("6000;6000;6000", "6000;6000;6000;")
    assert same_value("a;b;", "a;b")
    assert not same_value("6000;6000;6000", "6000;6000;6001;")


def test_integers_are_never_compared_with_a_tolerance():
    assert not same_value("100000000", "100000001")
    assert not same_value("16777217", "16777216")
    assert not same_value("100000000;4", "100000001;4")


def test_a_number_too_big_for_a_double_is_not_the_same_as_a_small_one_and_raises_nothing():
    assert not same_value("1" + "0" * 400, "1.5")
    assert not same_value("1.5", "1" + "0" * 400)
    assert same_value("1" + "0" * 400, "1" + "0" * 400)


def test_different_text_is_a_different_value():
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


def test_a_re_formatted_32_bit_float_is_not_a_change_but_the_real_changes_next_to_it_are():
    # the roll test's pass 5 for one frame: RefInput and RefOutput as typed, then as art-cli wrote them back
    before = {
        "Exposure": {"Compensation": "0.3"},
        "Film Negative": {"RefInput": "6450.7;3750;2347.9", "RefOutput": "6000;6000;6000"},
    }
    after = {
        "Exposure": {"Compensation": "0.4000000059604645"},
        "Film Negative": {"RefInput": "6450.7001953125;3750;2347.89990234375;", "RefOutput": "6000;6000;6000;"},
    }

    assert changes_between(before, after) == [
        KeyChange(group="Exposure", key="Compensation", before="0.3", after="0.4")
    ]


def test_a_list_with_one_real_change_is_shown_with_every_token_short():
    before = {"Film Negative": {"RefInput": "6450.7;3750;2347.9"}}
    after = {"Film Negative": {"RefInput": "6450.7001953125;3800;2347.89990234375;"}}

    assert changes_between(before, after) == [
        KeyChange(
            group="Film Negative", key="RefInput", before="6450.7;3750;2347.9", after="6450.7;3800;2347.9;"
        )
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


def test_the_same_change_written_with_and_without_32_bit_noise_is_one_entry():
    typed = changes_between({"Exposure": {"Compensation": "0"}}, {"Exposure": {"Compensation": "1.37"}})
    written_back = changes_between(
        {"Exposure": {"Compensation": "0"}}, {"Exposure": {"Compensation": "1.3700000047683716"}}
    )

    groups = summarise([("A.ARW", typed), ("B.ARW", written_back)]).groups

    assert [(g.before, g.after, g.images) for g in groups] == [("0", "1.37", ["A.ARW", "B.ARW"])]


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


# -- a change on every frame names none ---------------------------------------------


def frames(count, with_change):
    """`count` frames named F1.ARW..; the first `with_change` of them have `change("Black")`."""
    return [(f"F{i}.ARW", [change("Black")] if i <= with_change else []) for i in range(1, count + 1)]


def test_a_change_on_every_frame_of_a_pass_of_many_lists_no_names():
    [group] = summarise(frames(6, with_change=6)).groups

    assert (group.group, group.key) == ("Exposure", "Black") and group.images is None


def test_a_change_on_some_frames_still_names_them():
    [group] = summarise(frames(6, with_change=2)).groups

    assert group.images == ["F1.ARW", "F2.ARW"]


def test_a_small_pass_always_names_its_frames():
    assert summarise(frames(4, with_change=4)).groups[0].images == ["F1.ARW", "F2.ARW", "F3.ARW", "F4.ARW"]
    assert summarise(frames(5, with_change=5)).groups[0].images is None  # more than four: the names are noise


def test_a_frame_with_nothing_to_compare_is_a_frame_the_change_was_not_made_on():
    per_image = [("F0.ARW", None)] + frames(5, with_change=5)

    [group] = summarise(per_image).groups

    assert group.images == ["F1.ARW", "F2.ARW", "F3.ARW", "F4.ARW", "F5.ARW"]


def test_entries_are_ordered_by_sharing_before_the_names_are_dropped():
    per_image = [
        (f"F{i}.ARW", [change("Everywhere")] + ([change("Some")] if i <= 3 else [])) for i in range(1, 7)
    ]

    groups = summarise(per_image).groups

    assert [(g.key, g.images) for g in groups] == [("Everywhere", None), ("Some", ["F1.ARW", "F2.ARW", "F3.ARW"])]
