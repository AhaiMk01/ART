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
