"""The seven curated tools added after Exposure and White Balance (Appendix A):
their ranges, groups, value mappings and crop bounds."""

import pytest

from art_mcp.profile import WorkingChanges, read_format
from art_mcp.schema import AdjustmentError, crop_bounds_problem, parse_adjustments


def profile():
    return {
        "Version": {"Version": "1045"},
        "Rotation": {"Enabled": "false", "Degree": "0"},
        "Common Properties for Transformations": {"AutoFill": "true", "Method": "log"},
        "Denoise": {"Enabled": "false", "Luminance": "0", "ChrominanceMethod": "1",
                    "ChrominanceAutoFactor": "1", "Chrominance": "15"},
        "Crop": {"Enabled": "false", "X": "-1", "Y": "-1", "W": "-1", "H": "-1",
                 "FixedRatio": "true", "Ratio": "As Image", "Orientation": "As Image",
                 "Guide": "Frame"},
        "LensProfile": {"LcMode": "none", "UseDistortion": "true", "UseVignette": "true",
                        "UseCA": "false"},
    }  # fmt: skip


def test_rotation_auto_fill_lives_in_common_properties():
    changes = WorkingChanges(profile())

    changes.edit(parse_adjustments({"rotation": {"degree": 2.5, "auto_fill": False}}), [])

    assert changes.partial_profile() == {
        "Rotation": {"Degree": "2.5", "Enabled": "true"},
        "Common Properties for Transformations": {"AutoFill": "false"},
    }
    typed = read_format(changes.profile)
    assert typed.adjustments["rotation"] == {"enabled": True, "degree": 2.5, "auto_fill": False}
    assert "AutoFill" not in typed.raw["Common Properties for Transformations"]


def test_denoise_chrominance_method_is_named_but_stored_as_a_number():
    changes = WorkingChanges(profile())
    assert read_format(changes.profile).adjustments["denoise"]["chrominance_method"] == "automatic"

    changes.edit(parse_adjustments({"denoise": {"chrominance_method": "manual", "chrominance": 30}}), [])

    assert changes.profile["Denoise"]["ChrominanceMethod"] == "0"
    assert read_format(changes.profile).adjustments["denoise"]["chrominance_method"] == "manual"


def test_lens_profile_has_no_enabled_switch():
    changes = WorkingChanges(profile())

    result = changes.edit(parse_adjustments({"lens_profile": {"lc_mode": "lfauto"}}), [])

    assert result.implied == []
    assert changes.partial_profile() == {"LensProfile": {"LcMode": "lfauto"}}


@pytest.mark.parametrize(
    "tool, field, value",
    [
        ("rotation", "degree", 45.01),
        ("local_contrast", "contrast", -100.5),
        ("sharpening", "amount", 1001),
        ("sharpening", "radius", 0.29),
        ("sharpening", "deconv_radius", 2.6),
        ("denoise", "luminance", 100.01),
        ("denoise", "chrominance_auto_factor", 1.5),
        ("vignetting", "strength", 0),
        ("vignetting", "center_x", 101),
        ("vignetting", "center_y", -101),
        ("vignetting", "amount", 101),
        ("vignetting", "radius", -1),
        ("sharpening", "contrast", 200.5),
        ("sharpening", "deconv_amount", 101),
        ("denoise", "chrominance", -0.1),
        ("crop", "w", 0),
        ("crop", "h", 0),
        ("crop", "x", -1),
        ("crop", "y", -1),
    ],
)
def test_values_outside_art_ranges_are_out_of_range(tool, field, value):
    with pytest.raises(AdjustmentError) as e:
        parse_adjustments({tool: {field: value}})
    assert e.value.code == "out_of_range"


@pytest.mark.parametrize(
    "tool, field, value",
    [
        ("sharpening", "method", "psf"),
        ("lens_profile", "lc_mode", "magic"),
        ("crop", "ratio", "7:5"),
        ("crop", "orientation", "Diagonal"),
        ("denoise", "chrominance_method", "auto"),
    ],
)
def test_values_outside_art_enums_are_out_of_range(tool, field, value):
    with pytest.raises(AdjustmentError) as e:
        parse_adjustments({tool: {field: value}})
    assert e.value.code == "out_of_range"


@pytest.mark.parametrize(
    "x, y, w, h, problem",
    [
        (0, 0, 6000, 4000, False),
        (100, 200, 5900, 3800, False),
        (100, 0, 5901, 4000, True),
        (0, 4000, 10, 10, True),
        (-1, 0, 10, 10, True),
    ],
)
def test_crop_must_lie_inside_the_frame(x, y, w, h, problem):
    assert (crop_bounds_problem(x, y, w, h, frame_w=6000, frame_h=4000) is not None) == problem


def test_a_field_in_another_group_does_not_enable_the_tool():
    changes = WorkingChanges(profile())

    result = changes.edit(parse_adjustments({"rotation": {"auto_fill": False}}), [])

    assert result.implied == []
    assert changes.profile["Rotation"]["Enabled"] == "false"


def test_describe_names_the_group_each_field_sets():
    from art_mcp.schema import describe_adjustments

    rotation = describe_adjustments().tools["rotation"]

    assert rotation.fields["degree"].group == "Rotation"
    assert rotation.fields["auto_fill"].group == "Common Properties for Transformations"
