"""Marks on a preview: the shared drawing (art_mcp/marks.py), pure Pillow."""

import io
import math
from fractions import Fraction

import pytest
from PIL import Image

from art_mcp.marks import (
    DARK,
    LIGHT,
    MAX_LABEL,
    MAX_MARKS,
    Mark,
    check_marks,
    draw_marks,
    labels_of,
    mark_file,
    save_jpeg,
)
from art_mcp.render.artcli import Rect
from art_mcp.render.errors import RenderError, render_error

GREY = (128, 128, 128)
FRAME = Rect(0, 0, 6000, 4000)
"""A 6000 x 4000 frame shown in a 600 x 400 picture: one preview pixel is ten frame pixels."""


@pytest.fixture
def picture():
    return Image.new("RGB", (600, 400), GREY)


def changed(image, background=GREY):
    """The bounding box (left, top, right, bottom, inclusive) of the pixels that are not ``background``."""
    xs, ys = [], []
    for y in range(image.height):
        for x in range(image.width):
            if image.getpixel((x, y)) != background:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def square(mark, area, size):
    """Where the mark's square is in a picture of ``size`` showing ``area``: [left, right) x [top, bottom), by
    exact arithmetic (a half pixel rounds up)."""

    def edge(value, origin, extent, pixels):
        return math.floor((Fraction(value) - origin) * pixels / extent + Fraction(1, 2))

    half = Fraction(mark.size, 2)
    return (
        edge(mark.x - half, area.x, area.w, size[0]),
        edge(mark.x + half, area.x, area.w, size[0]),
        edge(mark.y - half, area.y, area.h, size[1]),
        edge(mark.y + half, area.y, area.h, size[1]),
    )


# -- the box -----------------------------------------------------------------


def test_a_mark_is_a_white_box_with_a_dark_outline_around_the_square_it_marks(picture):
    mark = Mark(x=3000, y=2000, size=200)  # the square 2900..3100 x 1900..2100: preview 290..310 x 190..210

    assert draw_marks(picture, [mark], FRAME) == []

    assert square(mark, FRAME, picture.size) == (290, 310, 190, 210)
    for x, y in ((289, 200), (310, 200), (300, 189), (300, 210), (289, 189), (310, 210)):
        assert picture.getpixel((x, y)) == LIGHT, (x, y)
    for x, y in ((288, 200), (311, 200), (300, 188), (300, 211), (288, 188), (311, 211)):
        assert picture.getpixel((x, y)) == DARK, (x, y)
    # what is inside the square is the picture's own, so the box does not hide what it marks
    assert all(picture.getpixel((x, y)) == GREY for x in range(290, 310) for y in range(190, 210))
    assert picture.getpixel((50, 50)) == GREY and picture.getpixel((600 - 1, 400 - 1)) == GREY


def test_the_outline_is_readable_on_dark_and_on_light_content():
    for ground in ((10, 10, 10), (245, 245, 245)):
        image = Image.new("RGB", (600, 400), ground)
        draw_marks(image, [Mark(x=3000, y=2000, size=200)], FRAME)

        rings = [image.getpixel((289, 200)), image.getpixel((288, 200))]
        assert max(abs(sum(p) - sum(ground)) for p in rings) > 3 * 200, ground  # one of them stands out of it
        assert abs(sum(rings[0]) - sum(rings[1])) > 3 * 200, ground  # and the two differ from each other


def test_a_picture_of_another_size_keeps_the_marks_on_the_same_part_of_the_frame():
    big = Image.new("RGB", (1200, 800), GREY)  # 0.2 px per frame px
    mark = Mark(x=1500, y=1000, size=400)  # the square 1300..1700 x 800..1200: preview 260..340 x 160..240

    draw_marks(big, [mark], FRAME)

    assert square(mark, FRAME, big.size) == (260, 340, 160, 240)
    assert big.getpixel((259, 200)) == LIGHT and big.getpixel((340, 200)) == LIGHT
    assert big.getpixel((258, 200)) == DARK and big.getpixel((341, 200)) == DARK
    assert big.getpixel((300, 159)) == LIGHT and big.getpixel((300, 240)) == LIGHT


def test_a_tiny_square_is_still_one_pixel_with_its_rings_around_it(picture):
    mark = Mark(x=3000, y=2000, size=2)  # 0.2 preview px: one pixel, at 300, 200

    draw_marks(picture, [mark], FRAME)

    assert picture.getpixel((300, 200)) == GREY
    assert [picture.getpixel((x, 200)) for x in (298, 299, 301, 302)] == [DARK, LIGHT, LIGHT, DARK]
    assert [picture.getpixel((300, y)) for y in (198, 199, 201, 202)] == [DARK, LIGHT, LIGHT, DARK]


def test_the_default_size_is_the_square_sample_spots_reads():
    assert Mark(x=1, y=2).size == 32


def test_an_area_that_is_not_the_frame_shifts_and_scales_the_marks(picture):
    crop = Rect(1000, 500, 4000, 2000)  # shown in 600 x 300: 0.15 px per frame px
    image = Image.new("RGB", (600, 300), GREY)
    mark = Mark(x=3000, y=1500, size=200)  # the square 2900..3100 x 1400..1600: preview 285..315 x 135..165

    draw_marks(image, [mark], crop)

    assert square(mark, crop, image.size) == (285, 315, 135, 165)
    assert image.getpixel((284, 150)) == LIGHT and image.getpixel((315, 150)) == LIGHT
    assert image.getpixel((300, 134)) == LIGHT and image.getpixel((300, 165)) == LIGHT
    assert image.getpixel((283, 150)) == DARK and image.getpixel((316, 150)) == DARK


def test_the_rings_are_thicker_on_a_big_picture():
    big = Image.new("RGB", (2400, 1600), GREY)
    draw_marks(big, [Mark(x=3000, y=2000, size=400)], FRAME)  # 0.4 px per frame px: the square 1120..1280 x 720..880

    row = [big.getpixel((x, 800)) for x in (1115, 1116, 1117, 1118, 1119, 1120)]
    assert row == [GREY, DARK, DARK, LIGHT, LIGHT, GREY]


# -- the number ----------------------------------------------------------------


def test_the_number_is_in_a_filled_tab_on_the_top_left_of_the_box(picture):
    draw_marks(picture, [Mark(x=3000, y=2000, size=200)], FRAME)

    left, top, right, bottom = changed(picture)
    assert (left, right, bottom) == (288, 311, 211)  # the tab is no wider than the box
    assert top <= 188 - 10  # and sits above it, as high as its text
    assert picture.getpixel((288, top)) == LIGHT  # the tab has a light edge, and a dark fill inside it
    assert picture.getpixel((289, top + 1)) == DARK


def test_a_tab_that_does_not_fit_above_the_box_goes_below_it(picture):
    draw_marks(picture, [Mark(x=3000, y=100, size=200)], FRAME)  # the box top is at preview row 0

    left, top, right, bottom = changed(picture)
    assert top == 0 and bottom > 12  # drawn down from the top: the rings, then the tab below the box
    assert (left, right) == (288, 311)


def test_a_tab_is_kept_inside_the_picture_at_the_right_edge(picture):
    draw_marks(picture, [Mark(x=5995, y=2000, size=200, label="MMMM")], FRAME)  # the box is at 590, a wide tab 40 px

    left, top, right, _ = changed(picture)
    assert right == 599
    row = [x for x in range(600) if picture.getpixel((x, top)) != GREY]
    assert row[0] < 588 and row[-1] == 599  # the tab was moved left to fit, not cut off


def test_marks_are_numbered_in_request_order_and_a_label_replaces_the_number():
    marks = [Mark(x=1, y=1), Mark(x=2, y=2, label="WB"), Mark(x=3, y=3), Mark(x=4, y=4, label="")]

    assert labels_of(marks) == ["1", "WB", "3", "4"]


def test_a_longer_label_makes_a_wider_tab():
    narrow, wide = (Image.new("RGB", (600, 400), GREY) for _ in range(2))
    draw_marks(narrow, [Mark(x=3000, y=2000, size=20, label="1")], FRAME)
    draw_marks(wide, [Mark(x=3000, y=2000, size=20, label="MMMM")], FRAME)

    assert changed(wide)[2] > changed(narrow)[2] + 10


# -- outside the picture -------------------------------------------------------


def test_a_mark_wholly_outside_the_area_is_not_drawn_and_a_warning_names_it(picture):
    crop = Rect(1000, 500, 4000, 2000)
    image = Image.new("RGB", (600, 300), GREY)
    marks = [Mark(x=3000, y=1500, size=200), Mark(x=100, y=100), Mark(x=5900, y=3900)]

    warnings = draw_marks(image, marks, crop)

    assert len(warnings) == 1
    assert "2 of 3 marks" in warnings[0] and "2, 3" in warnings[0] and "not drawn" in warnings[0]
    assert "1000" in warnings[0] and "4000" in warnings[0]  # where the picture is: x, y, w, h
    assert changed(image)[0] > 270  # only the first mark is there


def test_a_square_that_overlaps_the_area_is_drawn_where_it_overlaps(picture):
    crop = Rect(1000, 500, 4000, 2000)
    image = Image.new("RGB", (600, 300), GREY)

    warnings = draw_marks(image, [Mark(x=1000, y=1500, size=200)], crop)  # half of the square is left of the crop

    assert warnings == []
    assert image.getpixel((15, 150)) == LIGHT  # its right ring: the square is 900..1100, the crop starts at 1000


def test_a_picture_of_another_shape_than_the_area_is_warned_about():
    image = Image.new("RGB", (600, 300), GREY)  # the frame is 3:2

    warnings = draw_marks(image, [Mark(x=3000, y=2000)], FRAME)

    assert len(warnings) == 1 and "shape" in warnings[0] and "misplaced" in warnings[0]


def test_rounding_to_whole_pixels_is_not_a_different_shape():
    image = Image.new("RGB", (1024, 684), GREY)  # 6016 x 4016 shrunk: 1024 x 683.6

    assert draw_marks(image, [Mark(x=3000, y=2000)], Rect(0, 0, 6016, 4016)) == []


# -- the request -----------------------------------------------------------------


def error(code, message):
    return render_error(code, message)


def problem(marks, frame=None):
    with pytest.raises(RenderError) as caught:
        check_marks(marks, frame, error)
    assert caught.value.code == "out_of_range"
    return caught.value.message


def test_at_most_64_marks_with_a_size_of_2_to_256_and_a_label_of_4_characters():
    check_marks([Mark(x=0, y=0)] * MAX_MARKS, None, error)
    check_marks([Mark(x=0, y=0, size=2), Mark(x=0, y=0, size=256, label="abcd")], None, error)

    assert MAX_MARKS == 64 and MAX_LABEL == 4
    assert "64" in problem([Mark(x=0, y=0)] * 65)
    too_small = problem([Mark(x=0, y=0, size=1)])
    assert "size" in too_small and "mark 1" in too_small
    too_big = problem([Mark(x=0, y=0), Mark(x=0, y=0, size=257)])
    assert "size" in too_big and "mark 2" in too_big
    too_long = problem([Mark(x=0, y=0, label="abcde")])
    assert "label" in too_long and "4" in too_long


def test_a_mark_whose_centre_is_outside_the_frame_is_out_of_range_and_says_which():
    marks = [Mark(x=10, y=10), Mark(x=6000, y=10)]

    check_marks(marks[:1], (6000, 4000), error)
    message = problem(marks, (6000, 4000))

    assert "mark 2" in message and "(6000, 10)" in message and "6000 x 4000" in message
    assert "outside" in problem([Mark(x=-1, y=0)], (6000, 4000))
    assert "outside" in problem([Mark(x=0, y=4000)], (6000, 4000))


def test_the_frame_is_not_checked_when_it_is_not_known():
    check_marks([Mark(x=10**6, y=10**6)], None, error)


def test_a_number_is_a_fine_label():
    assert Mark.model_validate({"x": 1, "y": 2, "label": 7}).label == "7"


def test_extra_fields_of_a_suggest_neutrals_candidate_are_ignored():
    candidate = {"x": 10, "y": 20, "level": 120, "saturation": 0.01, "flatness": 0.02, "why": "flat, neutral, mid"}

    assert Mark.model_validate(candidate) == Mark(x=10, y=20)


# -- files ----------------------------------------------------------------------


def test_mark_file_marks_a_jpeg_in_place_and_keeps_its_size_and_colour_profile(tmp_path):
    profile = b"\x00\x00\x00\x0cfake icc profile bytes"
    path = tmp_path / "preview.jpg"
    Image.new("RGB", (600, 400), GREY).save(path, "JPEG", quality=85, icc_profile=profile)

    warnings = mark_file(path, [Mark(x=3000, y=2000, size=200)], FRAME)

    assert warnings == []
    with Image.open(path) as marked:
        assert marked.format == "JPEG" and marked.size == (600, 400)
        assert marked.info.get("icc_profile") == profile
        marked = marked.convert("RGB")
    assert sum(marked.getpixel((289, 200))) > 3 * 230 and sum(marked.getpixel((288, 200))) < 3 * 25
    assert all(abs(c - g) <= 3 for c, g in zip(marked.getpixel((300, 200)), GREY, strict=True))
    assert all(abs(c - g) <= 3 for c, g in zip(marked.getpixel((50, 50)), GREY, strict=True))


def test_mark_file_of_something_that_is_not_an_image_is_a_value_error(tmp_path):
    path = tmp_path / "preview.jpg"
    path.write_bytes(b"\xff\xd8not a jpeg\xff\xd9")

    with pytest.raises(ValueError, match="image"):
        mark_file(path, [Mark(x=1, y=1)], FRAME)
    assert path.read_bytes() == b"\xff\xd8not a jpeg\xff\xd9"


def test_the_thin_outline_survives_jpeg_compression_on_a_coloured_ground(tmp_path):
    path = tmp_path / "preview.jpg"
    Image.new("RGB", (600, 400), (200, 60, 30)).save(path, "JPEG", quality=85)

    mark_file(path, [Mark(x=3000, y=2000, size=200)], FRAME)

    with Image.open(path) as marked:
        marked = marked.convert("RGB")
        assert min(marked.getpixel((289, 200))) > 215  # white, not tinted by the red ground
        assert max(marked.getpixel((288, 200))) < 40


def test_save_jpeg_writes_a_decodable_jpeg(picture):
    buffer = io.BytesIO()

    save_jpeg(picture, buffer)

    assert Image.open(io.BytesIO(buffer.getvalue())).format == "JPEG"
