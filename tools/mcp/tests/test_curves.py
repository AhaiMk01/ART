"""Curve text <-> points, validation, contrast; the tone_curve adjustment on the
profile module."""

import pytest

from art_mcp.curves import LinearCurve, PointCurve, decode, drawn_curve, drawn_points, encode
from art_mcp.profile import Conflict, RawEdit, WorkingChanges, edit_warnings, read_format
from art_mcp.schema import AdjustmentError, describe_adjustments, parse_adjustments

ART_SPLINE = (
    "1;0;0;0.11;0.089999999999999997;0.32000000000000001;0.46999999999999997;"
    "0.66000000000000003;0.87;1;1;"
)
ART_CATMULL = "4;0;0;0.11;0.09;0.66;0.87;1;1;"


@pytest.mark.parametrize("text", [ART_SPLINE, ART_CATMULL, "3;0;0;1;1;"])
def test_art_curve_text_round_trips_through_decode_and_encode(text):
    decoded = decode(text)

    assert decoded is not None
    again = encode(PointCurve.model_validate(decoded))
    assert decode(again) == decoded


def test_decode_reads_art_curves_as_type_and_points():
    spline = decode(ART_SPLINE)
    assert spline is not None
    assert spline["type"] == "spline" and spline["points"][1] == [0.11, 0.09]
    assert len(spline["points"]) == 5
    catmull = decode(ART_CATMULL)
    assert catmull is not None and catmull["type"] == "catmull_rom"
    nurbs = decode("3;0;0;1;1;")
    assert nurbs is not None and nurbs["type"] == "nurbs"


def test_linear_reads_without_points_and_writes_zero():
    assert decode("0;") == {"type": "linear"}
    assert encode(LinearCurve(type="linear")) == "0;"


def test_encode_writes_art_text_compactly():
    curve = PointCurve(type="spline", points=[(0, 0), (0.25, 0.1), (1, 1)])
    assert encode(curve) == "1;0;0;0.25;0.1;1;1;"


@pytest.mark.parametrize(
    "text",
    [
        "", "2;0;0;1;1;", "2;0.5;0.5;0.5;0.5;0.5;0.5;", "1;0;0;1;", "x;0;0;1;1;",
        "1;0;0;1.5;1;", "1;0.5;0;0.2;1;", "1;0;0;", "0;1;",
    ],
)  # fmt: skip
def test_parametric_empty_or_unparseable_curves_do_not_decode(text):
    assert decode(text) is None


def adj(**tools):
    return parse_adjustments(tools)


@pytest.mark.parametrize(
    "curve",
    [
        {"type": "spline", "points": [[0, 0]]},
        {"type": "spline", "points": [[i / 40, i / 40] for i in range(33)]},
        {"type": "spline", "points": [[0, 0], [1.2, 1]]},
        {"type": "spline", "points": [[0, -0.1], [1, 1]]},
        {"type": "spline", "points": [[0, 0], [0.5, 0.5], [0.5, 0.6]]},
        {"type": "spline", "points": [[0.6, 0], [0.5, 1]]},
        {"type": "parametric", "points": [[0, 0], [1, 1]]},
        {"type": "spline"},
    ],
)
def test_bad_curves_are_out_of_range(curve):
    with pytest.raises(AdjustmentError) as e:
        adj(tone_curve={"curve1": curve})
    assert e.value.code == "out_of_range"
    assert "tone_curve.curve1" in str(e.value)


@pytest.mark.parametrize(
    "curve", [{"type": "linear", "points": [[0, 0], [1, 1]]}]
)
def test_unknown_keys_inside_a_curve_are_unknown_key(curve):
    with pytest.raises(AdjustmentError) as e:
        adj(tone_curve={"curve1": curve})
    assert e.value.code == "unknown_key" and "tone_curve.curve1" in str(e.value)


def test_error_messages_say_what_is_wrong():
    with pytest.raises(AdjustmentError, match="strictly increasing"):
        adj(tone_curve={"curve1": {"type": "spline", "points": [[0, 0], [0.5, 0.5], [0.5, 0.6]]}})
    with pytest.raises(AdjustmentError, match="2 to 32 points, got 1"):
        adj(tone_curve={"curve2": {"type": "nurbs", "points": [[0, 0]]}})


def test_bad_mode_and_unknown_field_are_reported():
    with pytest.raises(AdjustmentError, match="Standard") as e:
        adj(tone_curve={"mode": "Bright"})
    assert e.value.code == "out_of_range"
    with pytest.raises(AdjustmentError) as e2:
        adj(tone_curve={"curve3": {"type": "linear"}})
    assert e2.value.code == "unknown_key"


def profile(**tone_curve):
    return {
        "Version": {"Version": "1045"},
        "ToneCurve": {
            "Enabled": "true", "CurveMode": "Neutral", "HistogramMatching": "false",
            "Curve": "0;", "Curve2": "0;", **tone_curve,
        },
    }  # fmt: skip


def test_curves_compile_to_art_text_and_enable_the_tool():
    changes = WorkingChanges(profile(Enabled="false"))
    curve = {"type": "spline", "points": [[0, 0], [0.5, 0.4], [1, 1]]}

    result = changes.edit(adj(tone_curve={"mode": "Luminance", "curve1": curve}), [])

    assert changes.partial_profile() == {
        "ToneCurve": {"CurveMode": "Luminance", "Curve": "1;0;0;0.5;0.4;1;1;", "Enabled": "true"}
    }
    assert result.implied == [RawEdit(group="ToneCurve", key="Enabled", value="true")]


def test_contrast_is_a_typed_int_that_enables_the_tool_and_keeps_histogram_matching():
    changes = WorkingChanges(profile(Enabled="false", HistogramMatching="true"))

    result = changes.edit(adj(tone_curve={"contrast": 25}), [])

    assert changes.partial_profile() == {"ToneCurve": {"Contrast": "25", "Enabled": "true"}}
    assert result.implied == [RawEdit(group="ToneCurve", key="Enabled", value="true")]
    assert changes.profile["ToneCurve"]["HistogramMatching"] == "true"
    typed = read_format(changes.profile).adjustments["tone_curve"]
    assert typed["contrast"] == 25 and isinstance(typed["contrast"], int)


@pytest.mark.parametrize("value", [101, -101])
def test_contrast_outside_100_is_out_of_range(value):
    with pytest.raises(AdjustmentError) as e:
        adj(tone_curve={"contrast": value})
    assert e.value.code == "out_of_range"


def test_setting_a_curve_turns_histogram_matching_off_unless_asked_otherwise():
    changes = WorkingChanges(profile(HistogramMatching="true"))
    result = changes.edit(adj(tone_curve={"curve2": {"type": "linear"}}), [])
    assert result.implied == [RawEdit(group="ToneCurve", key="HistogramMatching", value="false")]

    kept = WorkingChanges(profile(HistogramMatching="true"))
    kept.edit(adj(tone_curve={"curve1": {"type": "linear"}, "histogram_matching": True}), [])
    assert kept.profile["ToneCurve"]["HistogramMatching"] == "true"

    untouched = WorkingChanges(profile(HistogramMatching="true"))
    untouched.edit(adj(tone_curve={"mode": "Standard"}), [])
    assert untouched.profile["ToneCurve"]["HistogramMatching"] == "true"


def test_a_raw_edit_of_an_implied_histogram_matching_wins():
    changes = WorkingChanges(profile(HistogramMatching="true"))
    changes.edit(
        adj(tone_curve={"curve1": {"type": "linear"}}),
        [RawEdit(group="ToneCurve", key="HistogramMatching", value="true")],
    )
    assert changes.profile["ToneCurve"]["HistogramMatching"] == "true"


def test_a_raw_edit_of_a_curve_conflicts_with_the_adjustment():
    with pytest.raises(Conflict, match=r"\[ToneCurve\] Curve"):
        WorkingChanges(profile()).edit(
            adj(tone_curve={"curve1": {"type": "linear"}}),
            [RawEdit(group="ToneCurve", key="Curve", value="0;")],
        )


def test_read_format_types_curves_and_mode2_follows_mode_when_absent():
    view = read_format(profile(Curve=ART_SPLINE, CurveMode="FilmLike"))
    typed = view.adjustments["tone_curve"]

    assert typed["mode"] == "FilmLike" and typed["mode2"] == "FilmLike"
    assert typed["curve1"]["type"] == "spline" and typed["curve1"]["points"][1] == [0.11, 0.09]
    assert typed["curve2"] == {"type": "linear"}
    assert typed["histogram_matching"] is False and typed["enabled"] is True
    assert "ToneCurve" not in view.raw


def test_read_format_reports_a_stored_mode2():
    view = read_format(profile(CurveMode2="Standard", Curve2=ART_CATMULL))

    assert view.adjustments["tone_curve"]["mode2"] == "Standard"
    assert view.adjustments["tone_curve"]["curve2"]["type"] == "catmull_rom"
    assert "ToneCurve" not in view.raw


def test_legacy_open_display_transform_mode_reads_as_neutral():
    view = read_format(profile(CurveMode="OpenDisplayTransform"))

    assert view.adjustments["tone_curve"]["mode"] == "Neutral"
    assert "ToneCurve" not in view.raw


def test_a_double_overshoot_past_one_still_decodes():
    assert decode("1;0;0;0.5;0.6;1.0000000000000002;1;") == {
        "type": "spline", "points": [[0.0, 0.0], [0.5, 0.6], [1.0, 1.0]]
    }
    assert decode("1;0;0;1.001;1;") is None


def test_parametric_or_unparseable_curves_stay_raw():
    view = read_format(profile(Curve="2;0;0;1;0.5;", Curve2=""))

    typed = view.adjustments["tone_curve"]
    assert "curve1" not in typed and "curve2" not in typed
    assert view.raw["ToneCurve"] == {"Curve": "2;0;0;1;0.5;", "Curve2": ""}


def test_setting_mode_re_aligns_a_stored_mode2():
    changes = WorkingChanges(profile(CurveMode2="Standard"))

    result = changes.edit(adj(tone_curve={"mode": "Luminance"}), [])

    assert changes.profile["ToneCurve"]["CurveMode2"] == "Luminance"
    assert RawEdit(group="ToneCurve", key="CurveMode2", value="Luminance") in result.implied
    assert read_format(changes.profile).adjustments["tone_curve"]["mode2"] == "Luminance"

    both = WorkingChanges(profile(CurveMode2="Standard"))
    both.edit(adj(tone_curve={"mode": "Luminance", "mode2": "Perceptual"}), [])
    assert both.profile["ToneCurve"]["CurveMode2"] == "Perceptual"


def test_describe_includes_tone_curve_with_the_domain_note():
    tool = describe_adjustments().tools["tone_curve"]

    assert tool.group == "ToneCurve"
    assert "sRGB" in tool.description and "image_stats" in tool.description
    assert tool.fields["curve1"].key == "Curve" and tool.fields["curve1"].type == "curve"
    assert tool.fields["mode"].enum and "Neutral" in tool.fields["mode"].enum
    assert tool.fields["mode2"].key == "CurveMode2"
    assert tool.fields["contrast"].key == "Contrast" and "S-curve" in tool.fields["contrast"].description


ART_REFERENCE = [  # (ART text, getVal at x = 0, 1/8, ..., 1) from DiagonalCurve in ART's C++
    ("1;0;0;0.25;0.1;0.75;0.9;1;1;", [0.0, 0.021875, 0.1, 0.271875, 0.5, 0.728125, 0.9, 0.978125, 1.0]),
    ("1;0;0;0.11;0.09;0.66;0.87;1;1;", [0.0, 0.105442780572, 0.268098690282, 0.466878726414, 0.667071229236, 0.833964539017, 0.936784072464, 0.982680660772, 1.0]),
    ("1;0.08;0;1;1;", [0.0, 0.048913043478, 0.184782608696, 0.320652173913, 0.45652173913, 0.592391304348, 0.728260869565, 0.864130434783, 1.0]),
    ("4;0;0;0.11;0.09;0.66;0.87;1;1;", [0.0, 0.108261411297, 0.294830900461, 0.493720332602, 0.681232373869, 0.837131155618, 0.926726216175, 0.972494685888, 1.0]),
    ("4;0;0;0.3;0.5;1;1;", [0.0, 0.245561316214, 0.440715392628, 0.570597067556, 0.670063095052, 0.759874486347, 0.844227125018, 0.924541334953, 1.0]),
    ("1;0;0;0.25;0.27;0.5;0.47;0.75;0.78;1;1;", [0.0, 0.145580357143, 0.27, 0.364508928571, 0.47, 0.621383928571, 0.78, 0.902455357143, 1.0]),
    ("4;0;0;0.25;0.27;0.5;0.47;0.75;0.78;1;1;", [0.0, 0.140383130418, 0.27, 0.36801026817, 0.47, 0.623434118089, 0.78, 0.896968116457, 1.0]),
    ("1;0;0.1;0.25;0;0.5;0.9;0.75;0.3;1;1;", [0.1, 0.0, 0.0, 0.522991071429, 0.9, 0.644866071429, 0.3, 0.472544642857, 1.0]),
    ("4;0;0.1;0.25;0;0.5;0.9;0.75;0.3;1;1;", [0.1, 0.016398150609, 0.0, 0.42343642741, 0.9, 0.599604753165, 0.3, 0.55571971567, 1.0]),
    ("1;0;0;0.7;0.95;0.85;1;1;1;", [0.0, 0.217563200092, 0.425655976676, 0.614807906245, 0.775548565291, 0.898407530305, 0.974141703465, 1.002372623026, 1.0]),
    ("4;0;0;0.7;0.95;0.85;1;1;1;", [0.0, 0.18175269673, 0.362677182506, 0.539885820091, 0.711056156239, 0.870272318617, 0.983756433035, 1.0, 1.0]),
    ("1;0;0;0.5;1;0.6;1;1;0.2;", [0.0, 0.338629201681, 0.641806722689, 0.874080882353, 1.0, 0.983580619748, 0.812657563025, 0.533409926471, 0.2]),
]


@pytest.mark.parametrize("text,expected", ART_REFERENCE)
def test_drawn_curve_matches_arts_diagonal_curve(text, expected):
    curve = decode(text)
    assert curve is not None
    drawn = drawn_curve(curve)
    assert drawn is not None
    tolerance = 1e-4 if curve["type"] == "catmull_rom" else 1e-6
    for i, want in enumerate(expected):
        assert drawn.value(i / 8) == pytest.approx(want, abs=tolerance), (text, i / 8)


def test_art_clamps_below_zero_but_not_above_one():
    over = decode("1;0;0;0.7;0.95;0.85;1;1;1;")
    assert over is not None
    assert max(drawn_curve(over).raw(i / 1000) for i in range(1001)) > 1.003  # type: ignore[union-attr]
    wiggle = decode("1;0;0.1;0.25;0;0.5;0.9;0.75;0.3;1;1;")
    assert wiggle is not None
    d = drawn_curve(wiggle)
    assert d is not None
    assert min(d.raw(i / 1000) for i in range(1001)) < 0 and min(d.value(i / 1000) for i in range(1001)) == 0


def test_drawn_points_are_nine_rounded_pairs_and_none_for_nurbs_with_three_points():
    curve = decode(ART_SPLINE)
    assert curve is not None
    pts = drawn_points(curve)
    assert pts is not None and [p[0] for p in pts] == [i / 8 for i in range(9)]
    assert pts[1] == [0.125, 0.1094] and pts[0] == [0, 0.0] and pts[8] == [1, 1.0]
    assert drawn_points({"type": "nurbs", "points": [[0, 0], [0.5, 0.7], [1, 1]]}) is None
    assert drawn_points({"type": "nurbs", "points": [[0, 0], [1, 1]]}) == [[i / 8, i / 8] for i in range(9)]
    assert drawn_points({"type": "nurbs", "points": [[0, 0], [0.5, 0.5], [1, 1]]}) is None
    assert drawn_points({"type": "nurbs", "points": [[0, 0], [1, 0.5]]})[8] == [1, 0.5]  # type: ignore[index]


def test_a_two_point_spline_is_linear_and_an_identity_spline_is_the_identity():
    assert drawn_points({"type": "spline", "points": [[0, 0], [1, 1]]}) == [[i / 8, i / 8] for i in range(9)]
    flat = drawn_points({"type": "catmull_rom", "points": [[0, 0.5], [1, 0.5]]})
    assert flat is not None and all(y == 0.5 for _, y in flat)
    ident = drawn_points({"type": "spline", "points": [[0, 0], [0.5, 0.5], [1, 1]]})
    assert ident == [[i / 8, i / 8] for i in range(9)]


def test_read_format_adds_drawn_to_typed_curves_but_not_to_linear():
    typed = read_format(profile(Curve=ART_SPLINE, Curve2=ART_CATMULL)).adjustments["tone_curve"]
    assert len(typed["curve1"]["drawn"]) == 9 and typed["curve1"]["drawn"][1] == [0.125, 0.1094]
    assert len(typed["curve2"]["drawn"]) == 9
    assert "drawn" not in read_format(profile()).adjustments["tone_curve"]["curve1"]
    nurbs = read_format(profile(Curve="3;0;0;0.5;0.7;1;1;")).adjustments["tone_curve"]["curve1"]
    assert nurbs["drawn"] is None


def test_read_format_output_can_be_sent_back_and_drawn_is_ignored():
    typed = read_format(profile(Curve=ART_SPLINE)).adjustments["tone_curve"]
    assert "drawn" in typed["curve1"]

    parsed = adj(tone_curve=typed)
    changes = WorkingChanges(profile())
    changes.edit(parsed, [])

    assert changes.profile["ToneCurve"]["Curve"] == "1;0;0;0.11;0.09;0.32;0.47;0.66;0.87;1;1;"


def edit_warnings_for(**curves):
    parsed = adj(tone_curve=curves)
    changes = WorkingChanges(profile())
    changes.edit(parsed, [])
    return edit_warnings(parsed, changes.profile)


def test_clipping_curve_is_warned_with_the_x_range():
    warnings = edit_warnings_for(
        curve2={"type": "spline", "points": [[0, 0.1], [0.25, 0], [0.5, 0.9], [0.75, 0.3], [1, 1]]}
    )
    assert any(w.startswith("curve2 clips to 0 for x 0.0") for w in warnings), warnings
    assert any(w.startswith("curve2 reverses for x ") for w in warnings), warnings


def test_curve_above_one_is_warned():
    warnings = edit_warnings_for(curve1={"type": "spline", "points": [[0, 0], [0.7, 0.95], [0.85, 1], [1, 1]]})
    assert any("curve1 goes above 1 for x " in w for w in warnings), warnings


def test_well_behaved_linear_and_two_point_curves_do_not_warn():
    assert edit_warnings_for(curve1={"type": "linear"}) == []
    assert edit_warnings_for(curve1={"type": "spline", "points": [[0, 0], [0.25, 0.3], [0.5, 0.5], [1, 1]]}) == []
    assert edit_warnings_for(curve2={"type": "catmull_rom", "points": [[0, 0.1], [0.5, 0.5], [1, 1]]}) == []


def test_nurbs_gets_one_cannot_check_warning():
    warnings = edit_warnings_for(curve1={"type": "nurbs", "points": [[0, 0], [0.5, 0.7], [1, 1]]})
    assert len(warnings) == 1 and "NURBS" in warnings[0] and "curve1" in warnings[0]


def test_only_curves_set_by_the_agent_are_checked():
    parsed = adj(tone_curve={"mode": "Standard"})
    changes = WorkingChanges(profile(Curve="1;0;0;0.7;0.95;0.85;1;1;1;"))
    changes.edit(parsed, [])
    assert edit_warnings(parsed, changes.profile) == []
