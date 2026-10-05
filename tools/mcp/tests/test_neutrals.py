"""suggest_neutrals: the pure scoring and selection (art_mcp/neutrals.py)."""

import random

import pytest
from PIL import Image, ImageDraw

from art_mcp.neutrals import (
    BAND_SLOTS,
    Cell,
    choose_cells,
    cost,
    describe,
    measure_cells,
    saturation_of,
    suggest_candidates,
)

# -- one cell ------------------------------------------------------------------


def test_saturation_is_zero_for_grey_and_chroma_over_max_otherwise():
    assert saturation_of(128, 128, 128) == 0
    assert saturation_of(200, 100, 100) == 0.5
    assert saturation_of(0, 0, 0) == 0


def test_cost_adds_saturation_and_flatness():
    assert cost(Cell(0, 0, 100, 90, 110, 0.18, 0.02)) == pytest.approx(0.20)


@pytest.mark.parametrize(
    ("cell", "words"),
    [
        (Cell(0, 0, 50, 49, 51, 0.01, 0.01), "flat, neutral, dark"),
        (Cell(0, 0, 120, 110, 130, 0.08, 0.03), "flat, near-neutral, mid"),
        (Cell(0, 0, 200, 150, 210, 0.2, 0.06), "some texture, tinted, light"),
    ],
)
def test_describe_names_flatness_tint_and_tone(cell, words):
    assert describe(cell) == words


# -- measuring a rendered image --------------------------------------------------


def noise(draw, box, rng, mean=128, spread=45):
    left, top, right, bottom = box
    for x in range(left, right):
        for y in range(top, bottom):
            v = mean + rng.randint(-spread, spread)
            draw.point((x, y), (v, v, v))


def test_measure_cells_reads_level_saturation_and_flatness():
    image = Image.new("RGB", (80, 40), (100, 100, 100))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 0, 79, 39), fill=(200, 100, 50))  # flat orange on the right
    noise(draw, (0, 0, 20, 40), random.Random(1))  # noise on the left quarter

    # 8000 x 4000 frame px at 0.01 preview px each: cells of 400 frame px are 4 px
    cols, rows, cells = measure_cells(image, 8000, 4000, 400)

    assert (cols, rows) == (20, 10)
    by_position = {(c.col, c.row): c for c in cells}
    grey = by_position[(7, 5)]
    assert grey.level == pytest.approx(100, abs=0.5) and grey.saturation == 0 and grey.flatness < 0.01
    orange = by_position[(15, 5)]
    assert orange.saturation == pytest.approx(0.75, abs=0.01) and orange.flatness < 0.01
    assert (orange.low, orange.high) == (50, 200)
    assert by_position[(2, 5)].flatness > 0.1


def test_measure_cells_aligns_cells_to_the_area_not_the_image_size():
    # 83 x 41 preview px stand for 8300 x 4100 frame px (0.01 px each): the 1000 px cells are 10 px, and the
    # spare 3 px at the right and bottom are not analysed
    image = Image.new("RGB", (83, 41), (60, 60, 60))
    ImageDraw.Draw(image).rectangle((40, 20, 49, 29), fill=(180, 180, 180))  # frame x 4000..4999, y 2000..2999
    cols, rows, cells = measure_cells(image, 8300, 4100, 1000)
    assert (cols, rows) == (8, 4)
    levels = {(c.col, c.row): round(c.level) for c in cells}
    assert levels[(4, 2)] == 180
    assert levels[(3, 2)] == 60 and levels[(4, 1)] == 60 and levels[(5, 2)] == 60


# -- choosing cells --------------------------------------------------------------


def ramp(cols=30, rows=20, flatness=0.01, saturation=0.02):
    """A grid whose level rises with the column: 20 .. 230."""
    return [
        Cell(c, r, 20 + 210 * c / (cols - 1), 20 + 210 * c / (cols - 1), 20 + 210 * c / (cols - 1),
             saturation, flatness)
        for c in range(cols)
        for r in range(rows)
    ]  # fmt: skip


def test_choice_spreads_over_the_levels_and_the_frame():
    chosen = choose_cells(ramp(), 30, 20, 8, margin=0.0)

    assert len(chosen) == 8
    levels = sorted(c.level for c in chosen)
    assert levels[0] < 60 and levels[-1] > 190  # dark to light, not eight mid-tones
    for a in chosen:
        for b in chosen:
            if a is not b:
                assert (a.col - b.col) ** 2 + (a.row - b.row) ** 2 >= 3 * 3  # never touching


def test_choice_takes_the_best_cell_of_each_level_band_first():
    good = Cell(5, 5, 100, 100, 100, 0.0, 0.0)
    worse = Cell(20, 15, 105, 105, 105, 0.02, 0.02)
    other_band = Cell(10, 10, 220, 220, 220, 0.05, 0.04)  # worse than `worse`, but alone in its band
    chosen = choose_cells([worse, good, other_band], 30, 20, 4, margin=0.0)
    assert chosen[:2] == [good, other_band]
    assert chosen[2:] == [worse]


@pytest.mark.parametrize(
    "cell",
    [
        Cell(15, 10, 8, 8, 8, 0.0, 0.0),  # near black
        Cell(15, 10, 250, 250, 250, 0.0, 0.0),  # near clipped
        Cell(15, 10, 120, 40, 250, 0.0, 0.0),  # one channel clipped, level fine
        Cell(15, 10, 120, 100, 140, 0.5, 0.01),  # strongly coloured
        Cell(15, 10, 120, 100, 140, 0.12, 0.01),  # clearly tinted (limit 0.10)
        Cell(15, 10, 120, 100, 140, 0.0, 0.4),  # textured
        Cell(15, 10, 120, 100, 140, 0.0, 0.07),  # somewhat textured (limit 0.06)
    ],
)
def test_unusable_cells_are_never_suggested(cell):
    assert choose_cells([cell], 30, 20, 4, margin=0.0) == []


def test_cells_near_the_border_are_left_out():
    inside = Cell(15, 10, 100, 100, 100, 0.0, 0.0)
    edge = Cell(1, 10, 100, 100, 100, 0.0, 0.0)
    corner = Cell(29, 19, 100, 100, 100, 0.0, 0.0)
    assert choose_cells([edge, corner, inside], 30, 20, 3, margin=0.1) == [inside]


def test_fewer_cells_than_asked_for_give_fewer_candidates():
    chosen = choose_cells(ramp(cols=3, rows=2), 3, 2, 16, margin=0.0)
    assert 1 <= len(chosen) < 16


def test_choice_is_deterministic_and_independent_of_input_order():
    cells = ramp()
    shuffled = list(cells)
    random.Random(3).shuffle(shuffled)
    assert choose_cells(cells, 30, 20, 8, margin=0.0) == choose_cells(shuffled, 30, 20, 8, margin=0.0)


def test_band_slots_is_two():
    assert BAND_SLOTS == 2


# -- the whole thing on a picture --------------------------------------------------


def scene():
    """600 x 400 preview of a 6000 x 4000 area: noise, flat greys of several
    levels, flat colours, a flat near-black block, and a flat grey in the
    outer 10%."""
    rng = random.Random(7)
    image = Image.new("RGB", (600, 400))
    draw = ImageDraw.Draw(image)
    noise(draw, (0, 0, 600, 400), rng, spread=70)
    greys = {(70, 70, 150, 150): 50, (260, 70, 340, 150): 110, (450, 70, 530, 150): 190,
             (70, 250, 150, 330): 80, (260, 250, 340, 330): 150, (450, 250, 530, 330): 225}  # fmt: skip
    for box, level in greys.items():
        draw.rectangle(box, fill=(level, level, level))
    draw.rectangle((160, 160, 240, 240), fill=(210, 120, 40))  # orange
    draw.rectangle((350, 160, 430, 240), fill=(60, 80, 200))  # blue
    draw.rectangle((540, 330, 590, 390), fill=(8, 8, 8))  # near black
    draw.rectangle((2, 150, 28, 250), fill=(128, 128, 128))  # grey inside the border
    return image, list(greys)


def patch_of(candidate, boxes, origin=(0, 0), scale=10):
    """The index of the box (preview px) the candidate's frame position is in, else None."""
    x, y = candidate.x - origin[0], candidate.y - origin[1]
    for i, (left, top, right, bottom) in enumerate(boxes):
        if left * scale <= x < right * scale and top * scale <= y < bottom * scale:
            return i
    return None


def test_candidates_land_on_the_flat_neutral_patches_across_the_levels():
    image, greys = scene()

    result = suggest_candidates(image, (0, 0, 6000, 4000), size=32, count=8, margin=0.1)

    assert len(result.candidates) == 8
    patches = [patch_of(c, greys) for c in result.candidates]
    assert None not in patches, [(c.x, c.y) for c in result.candidates]
    levels = [c.level for c in result.candidates]
    assert levels == sorted(levels)  # dark to light
    assert min(levels) < 70 and max(levels) > 180
    assert len(set(patches)) >= 4  # several places, not eight cells of one patch


def test_candidates_carry_their_scores_and_a_reason():
    image, _ = scene()
    [first, *_] = suggest_candidates(image, (0, 0, 6000, 4000), size=32, count=4, margin=0.1).candidates
    assert 0 <= first.level <= 255
    assert first.saturation <= 0.01 and first.flatness <= 0.01
    assert first.why == "flat, neutral, dark"


def test_candidates_are_in_frame_pixels_of_the_area_given():
    image, greys = scene()
    result = suggest_candidates(image, (1000, 500, 6000, 4000), size=32, count=4, margin=0.1)
    for c in result.candidates:
        assert 1000 <= c.x < 7000 and 500 <= c.y < 4500
        assert patch_of(c, greys, origin=(1000, 500)) is not None, (c.x, c.y)


def test_a_small_size_is_enlarged_so_a_cell_is_a_few_preview_pixels():
    image, _ = scene()
    result = suggest_candidates(image, (0, 0, 6000, 4000), size=2, count=4, margin=0.1)
    assert result.cell == 40  # 4 preview px at 0.1 px per frame px
    assert suggest_candidates(image, (0, 0, 6000, 4000), size=64, count=4, margin=0.1).cell == 64


def test_a_cell_larger_than_the_area_is_refused():
    image, _ = scene()
    with pytest.raises(ValueError):
        suggest_candidates(image, (0, 0, 6000, 4000), size=5000, count=4, margin=0.1)
