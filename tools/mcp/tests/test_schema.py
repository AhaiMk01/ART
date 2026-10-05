import pytest

from art_mcp.schema import PPVERSION, AdjustmentError, parse_adjustments


def test_in_range_values_parse_and_only_set_fields_are_set():
    adj = parse_adjustments({"exposure": {"compensation": 0.7}})

    assert adj.exposure is not None and adj.exposure.compensation == 0.7
    assert adj.exposure.model_fields_set == {"compensation"}
    assert adj.white_balance is None
    assert PPVERSION == 1045


@pytest.mark.parametrize(
    "data, range_text",
    [
        ({"exposure": {"compensation": 12.5}}, "-12..12"),
        ({"exposure": {"hl_recovery_blur": 4}}, "0..3"),
        ({"white_balance": {"temperature": 1000}}, "1500..60000"),
        ({"white_balance": {"equal": 2}}, "0.8..1.5"),
    ],
)
def test_out_of_range_is_rejected_naming_the_range(data, range_text):
    with pytest.raises(AdjustmentError) as e:
        parse_adjustments(data)

    assert e.value.code == "out_of_range"
    assert range_text in str(e.value)


def test_enum_value_outside_the_allowed_ones_is_out_of_range():
    with pytest.raises(AdjustmentError) as e:
        parse_adjustments({"exposure": {"hl_recovery": "Extreme"}})

    assert e.value.code == "out_of_range"
    assert "Balanced" in str(e.value)


def test_unknown_tool_or_field_is_unknown_key():
    for data in ({"curves": {}}, {"exposure": {"compensaton": 1}}):
        with pytest.raises(AdjustmentError) as e:
            parse_adjustments(data)
        assert e.value.code == "unknown_key"


CURVE = {"type": "spline", "points": [[0, 0], [0.5, 0.6], [1, 1]]}
SHAPE = {"type": "rectangle", "width": 110, "roundness": 100}


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"exposure": None},  # a tool or a field may be null: not set
        {"exposure": {}},
        {"exposure": {"compensation": None, "black": 0.1}},
        {"tone_curve": {"curve1": CURVE, "curve2": None}},
        {"tone_curve": {"curve1": {"type": "linear"}, "curve2": {"type": "nurbs", "points": [[0, 0], [1, 1]]}}},
        {"tone_curve": {"curve1": {**CURVE, "drawn": [[0, 0]]}}},  # a read-back curve may be sent as it is
        {"tone_curve": {"mode": "Neutral", "mode2": "Luminance", "contrast": 10}},
        {"color_correction": {"regions": [None, {"b": {"slope": 0.85}}]}},
        {"color_correction": {"regions": [{"r": None, "mask": None}]}},
        {"color_correction": {"regions": [{"mask": {"shapes": [None, SHAPE, {"type": "gradient", "x": 10}]}}]}},
        {"film_negative": {"ref_input": [1, 2, 3], "ref_output": [0, 0, 0]}},
    ],
)
def test_valid_requests_are_accepted(data):
    assert parse_adjustments(data) is not None


@pytest.mark.parametrize(
    "data, code, text",
    [
        ({"exposure": {"gain": 1}}, "unknown_key", "known here: black, compensation, enabled"),
        ({"curves": {}}, "unknown_key", "curves is not an adjustment"),
        ({"color_correction": {"regions": [{"r": {"gain": 1}}]}}, "unknown_key", "regions.0.r.gain"),
        ({"color_correction": {"regions": [{"mask": {"shapes": [{"type": "rectangle", "strength_end": 1}]}}]}},
         "unknown_key", "strength_end"),
        ({"exposure": {"compensation": 12.5}}, "out_of_range", "-12..12 EV"),
        ({"white_balance": {"temperature": "hot"}}, "out_of_range", "valid integer"),
        ({"tone_curve": {"mode": "Bogus"}}, "out_of_range", "not one of: Standard"),
        ({"tone_curve": {"curve1": {"type": "spline", "points": [[0, 0]]}}}, "out_of_range", "needs 2 to 32 points"),
        ({"tone_curve": {"curve1": {"type": "spline", "points": [[0, 0], [2, 1]]}}}, "out_of_range", "outside 0..1"),
        ({"tone_curve": {"curve1": {"type": "spline", "points": [[0, 0], [0.5, 1], [0.5, 1]]}}},
         "out_of_range", "strictly increasing"),
        ({"tone_curve": {"curve1": {"type": "wavy", "points": [[0, 0], [1, 1]]}}}, "out_of_range", "'spline'"),
        ({"color_correction": {"regions": [{"r": {"slope": 11}}]}}, "out_of_range", "regions.0.r.slope=11"),
        ({"color_correction": {"regions": [{"mask": {"shapes": [{"type": "polygon"}]}}]}}, "out_of_range", "polygon"),
        ({"color_correction": {"regions": [{"mask": {"shapes": [{"type": "rectangle", "mode": "xor"}]}}]}},
         "out_of_range", "mode"),
        ({"film_negative": {"ref_input": [1, 2]}}, "out_of_range", "at least 3 items"),
        ({"film_negative": {"ref_input": [1, 2, -3]}}, "out_of_range", "ref_input.2=-3"),
        ({"crop": {"ratio": "7:3"}}, "out_of_range", "not one of: As Image, 3:2"),
        ({"vignetting": {"center_x": 101}}, "out_of_range", "-100..100 % of image width"),
    ],
)
def test_invalid_requests_are_rejected_with_the_same_code_and_text(data, code, text):
    with pytest.raises(AdjustmentError) as e:
        parse_adjustments(data)

    assert e.value.code == code
    assert text in str(e.value)


def test_a_null_field_is_not_set():
    adj = parse_adjustments({"exposure": {"compensation": None, "black": 0.1}, "tone_curve": {"curve2": None}})

    assert adj.exposure is not None and adj.exposure.model_fields_set == {"compensation", "black"}
    assert adj.exposure.compensation is None and adj.exposure.black == 0.1
    assert adj.tone_curve is not None and adj.tone_curve.curve2 is None
