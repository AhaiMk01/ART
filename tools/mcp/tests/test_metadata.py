import json
import sys
from pathlib import Path

import pytest

from art_mcp.metadata import Exiftool, ExiftoolError, ExiftoolTimeout, InvalidTag

FAKE = Path(__file__).with_name("fake_exiftool.py")

SONY = {
    "Make": "SONY", "Model": "ILCE-7M3", "LensModel": "FE 24-70mm F2.8 GM", "ISO": 100,
    "ExposureTime": 0.125, "FNumber": 2.8, "FocalLength": 35,
    "DateTimeOriginal": "2025:12:28 12:04:04", "ImageWidth": 6048, "ImageHeight": 4024,
    "Orientation": 1,
}  # fmt: skip


def photo(tmp_path, known, name="a.ARW"):
    image = tmp_path / name
    image.write_bytes(b"x")
    image.with_name(name + ".exif.json").write_text(json.dumps(known))
    return image


@pytest.fixture
def exiftool():
    return Exiftool((sys.executable, str(FAKE)))


def test_fixed_fields_are_read_and_typed(exiftool, tmp_path):
    m = exiftool.read(photo(tmp_path, SONY))

    assert (m.make, m.model, m.lens) == ("SONY", "ILCE-7M3", "FE 24-70mm F2.8 GM")
    assert (m.iso, m.shutter_seconds, m.aperture, m.focal_length_mm) == (100, 0.125, 2.8, 35.0)
    assert m.capture_date == "2025-12-28T12:04:04"
    assert (m.width, m.height, m.orientation) == (6048, 4024, 1)
    assert m.tags == {}


def test_missing_and_placeholder_values_are_none(exiftool, tmp_path):
    # What a Sony body records with a manual lens: "----" and zeros.
    manual = {"Make": "SONY", "LensModel": "----", "FNumber": 0, "FocalLength": 0, "ISO": 100}
    m = exiftool.read(photo(tmp_path, manual))

    assert m.make == "SONY" and m.iso == 100
    assert (m.model, m.lens, m.aperture, m.focal_length_mm, m.capture_date, m.width) == (None,) * 6


def test_requested_tags_are_returned_and_missing_ones_left_out(exiftool, tmp_path):
    image = photo(tmp_path, {**SONY, "Software": "ILCE-7M3 v3.00", "Artist": "me"})
    m = exiftool.read(image, ["Software", "NoSuchTag"])

    assert m.tags == {"Software": "ILCE-7M3 v3.00"}
    assert m.make == "SONY"


@pytest.mark.parametrize("tag", ["-overwrite_original", "@args.txt", "Make=x", "a b", "", "Exif*;"])
def test_tag_names_that_could_act_as_options_are_refused(exiftool, tmp_path, tag):
    with pytest.raises(InvalidTag):
        exiftool.read(photo(tmp_path, SONY), [tag])


def test_unreadable_file_is_an_error_with_exiftools_message(exiftool, tmp_path):
    with pytest.raises(ExiftoolError, match="File not found"):
        exiftool.read(tmp_path / "gone.ARW")


def test_exiftool_that_cannot_start_is_an_error(tmp_path):
    with pytest.raises(ExiftoolError, match="cannot start"):
        Exiftool((str(tmp_path / "nope.exe"),)).read(photo(tmp_path, SONY))


def test_exiftool_output_that_is_not_json_is_an_error(tmp_path):
    junk = tmp_path / "junk.py"
    junk.write_text("print(1)")
    with pytest.raises(ExiftoolError, match="unexpected"):
        Exiftool((sys.executable, str(junk))).read(photo(tmp_path, SONY))


def test_slow_exiftool_is_killed_after_the_timeout(tmp_path):
    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(10)")
    with pytest.raises(ExiftoolTimeout):
        Exiftool((sys.executable, str(slow)), timeout=0.5).read(photo(tmp_path, SONY))


def test_values_of_the_wrong_type_are_none_rather_than_an_error(exiftool, tmp_path):
    # exiftool prints a malformed rational as a string even with -n.
    odd = {"Make": "SONY", "ExposureTime": "1 250", "ISO": "100 200", "ImageWidth": 6000.5}
    m = exiftool.read(photo(tmp_path, odd))

    assert m.make == "SONY"
    assert (m.shutter_seconds, m.iso, m.width) == (None, None, None)
