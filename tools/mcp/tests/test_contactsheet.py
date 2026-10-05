import pytest
from PIL import Image

from art_mcp.contactsheet import BACKGROUND, HEADER_HEIGHT, LABEL_HEIGHT, PAD, Box, Cell, compose, side_by_side


@pytest.fixture
def landscape(tmp_path):
    path = tmp_path / "landscape.png"
    Image.new("RGB", (400, 200), (200, 50, 50)).save(path)
    return path


@pytest.fixture
def portrait(tmp_path):
    path = tmp_path / "portrait.png"
    Image.new("RGB", (100, 200), (50, 50, 200)).save(path)
    return path


def differs_from_background(sheet, rect):
    x0, y0, x1, y1 = rect
    return any(sheet.getpixel((x, y)) != BACKGROUND for x in range(x0, x1) for y in range(y0, y1))


def test_each_frame_is_centred_in_its_cell_whatever_its_shape(landscape, portrait):
    # at 100 px the landscape frame is 100x50 and the portrait one 50x100: the cells are 100 high
    sheet, boxes = compose([Cell("a", landscape), Cell("b", portrait)], columns=2, thumb_size=100)

    assert boxes == [Box(PAD, PAD + 25, 100, 50), Box(2 * PAD + 100 + 25, PAD, 50, 100)]
    assert sheet.size == (PAD + 2 * (100 + PAD), PAD + 100 + LABEL_HEIGHT + PAD)
    assert sheet.getpixel((PAD + 50, PAD + 50)) == (200, 50, 50)


def test_cells_are_only_as_high_as_the_tallest_frame(landscape):
    sheet, boxes = compose([Cell("a", landscape)], columns=1, thumb_size=100)

    assert boxes == [Box(PAD, PAD, 100, 50)]
    assert sheet.height == PAD + 50 + LABEL_HEIGHT + PAD


def test_frames_fill_rows_in_order_and_fewer_cells_than_columns_make_a_narrower_sheet(landscape):
    cells = [Cell(str(i), landscape) for i in range(5)]
    sheet, boxes = compose(cells, columns=3, thumb_size=100)
    narrow, _ = compose(cells[:2], columns=3, thumb_size=100)

    row = 50 + LABEL_HEIGHT + PAD
    assert [(b.x, b.y) for b in boxes[:4]] == [
        (PAD, PAD),
        (PAD + 108, PAD),
        (PAD + 216, PAD),
        (PAD, PAD + row),
    ]
    assert sheet.size == (PAD + 3 * (100 + PAD), PAD + 2 * row)
    assert narrow.width == PAD + 2 * (100 + PAD)


def test_the_file_name_is_written_under_the_frame_and_kept_inside_its_cell(landscape):
    name = "a_very_long_file_name_that_cannot_fit_in_a_small_cell.ARW"
    sheet, _ = compose([Cell(name, landscape), Cell("b", landscape)], columns=2, thumb_size=100)

    label_rows = (PAD + 50, PAD + 50 + LABEL_HEIGHT)
    assert differs_from_background(sheet, (PAD, label_rows[0], PAD + 100, label_rows[1]))
    gap = (PAD + 100, label_rows[0], 2 * PAD + 100, label_rows[1])  # between the two cells
    assert not differs_from_background(sheet, gap)


def test_a_cell_without_a_frame_is_a_placeholder_with_its_note(landscape):
    sheet, boxes = compose([Cell("gone", None, "not_open"), Cell("b", landscape)], columns=2, thumb_size=100)

    assert boxes[0] is None and boxes[1] is not None
    assert sheet.getpixel((PAD + 5, PAD + 5)) != BACKGROUND  # the placeholder square
    assert differs_from_background(sheet, (PAD, PAD + 50, PAD + 100, PAD + 50 + LABEL_HEIGHT))  # still labelled


def test_a_pair_of_frames_fills_a_double_wide_cell(landscape, portrait):
    pair = side_by_side(Image.open(landscape), Image.open(portrait), 100)
    assert pair.size == (2 * 100 + PAD, 100)  # as high as the taller frame
    assert pair.getpixel((50, 50)) == (200, 50, 50)  # left, centred
    assert pair.getpixel((100 + PAD + 50, 50)) == (50, 50, 200)  # right
    assert pair.getpixel((100 + PAD // 2, 50)) == BACKGROUND  # the gap

    sheet, boxes = compose([Cell("pair", pair)], columns=1, thumb_size=100, cell_width=2 * 100 + PAD)
    assert boxes == [Box(PAD, PAD, 2 * 100 + PAD, 100)]
    assert sheet.width == 2 * PAD + 2 * 100 + PAD


def test_a_title_takes_a_line_above_the_grid(landscape):
    plain, plain_boxes = compose([Cell("a", landscape)], columns=1, thumb_size=100)
    titled, boxes = compose([Cell("a", landscape)], columns=1, thumb_size=100, title="pass 03 - black point")

    assert titled.height == plain.height + HEADER_HEIGHT
    assert boxes[0].y == plain_boxes[0].y + HEADER_HEIGHT
    assert differs_from_background(titled, (PAD, PAD, titled.width - PAD, HEADER_HEIGHT))
