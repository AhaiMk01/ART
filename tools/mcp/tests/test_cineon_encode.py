"""Colour/OCIO Cineon encode, checked against the published code values.

Linear scene values are 0..1. Reference white 1 maps to 685/1023, black to
95/1023, and linear 0.18 maps to about 467.838/1023 before 16-bit
quantization (round(y * 65535)).
"""

import math

BLACK = 95.0
WHITE = 685.0
SOFT_CLIP = 10 ** ((BLACK - WHITE) / 300.0)


def cineon_code(linear, reference_white=1.0):
    x = max(0.0, linear) / reference_white
    return (WHITE + 300.0 * math.log10(x * (1.0 - SOFT_CLIP) + SOFT_CLIP)) / 1023.0


def quantize_uint16(code):
    return int(round(min(1.0, max(0.0, code)) * 65535.0))


def test_reference_white_and_black_hit_the_cineon_codes():
    assert cineon_code(1.0) == WHITE / 1023.0
    assert cineon_code(0.0) == BLACK / 1023.0


def test_linear_018_maps_to_about_467_838():
    code = cineon_code(0.18)
    assert abs(code - 467.838 / 1023.0) < 1e-6
    assert quantize_uint16(code) == 29970


def test_a_higher_reference_white_lowers_the_code():
    assert cineon_code(0.18, 2.0) < cineon_code(0.18, 1.0)
