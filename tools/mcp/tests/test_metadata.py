import json
import sys
from pathlib import Path

import pytest

from art_mcp.metadata import Exiftool, ExiftoolError, ExiftoolTimeout, InvalidTag, Metadata

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


def run_log(tmp_path, monkeypatch):
    """A function giving the files each exiftool run was asked for."""
    log = tmp_path / "exiftool-runs.log"
    monkeypatch.setenv("FAKE_EXIFTOOL_LOG", str(log))
    return lambda: [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_read_many_runs_exiftool_once_and_keeps_the_order(exiftool, tmp_path, monkeypatch):
    runs = run_log(tmp_path, monkeypatch)
    images = [photo(tmp_path, {**SONY, "ISO": iso}, name=f"{iso}.ARW") for iso in (400, 100, 200)]

    results = exiftool.read_many(images)

    assert [m.iso for m in results] == [400, 100, 200]
    assert all(m.make == "SONY" and m.shutter_seconds == 0.125 for m in results)
    assert runs() == [[str(i) for i in images]]


def test_read_many_returns_a_files_own_error_and_the_others_still_read(exiftool, tmp_path):
    good = photo(tmp_path, SONY, name="good.ARW")
    bare = tmp_path / "bare.ARW"  # no .exif.json: the fake can't read it
    bare.write_bytes(b"x")
    results = exiftool.read_many([good, tmp_path / "gone.ARW", bare, good])

    assert [type(r).__name__ for r in results] == ["Metadata", "ExiftoolError", "ExiftoolError", "Metadata"]
    assert "File not found" in str(results[1]) and "gone.ARW" in str(results[1])
    assert "File format error" in str(results[2])
    assert results[0] == results[3] and results[0] is not results[3]


def test_read_many_takes_the_error_exiftool_names_for_a_file_that_has_a_record(exiftool, tmp_path):
    empty = photo(tmp_path, {"__error__": "File is empty"}, name="empty.ARW")
    results = exiftool.read_many([empty, photo(tmp_path, SONY)])

    assert isinstance(results[0], ExiftoolError) and "File is empty" in str(results[0])
    assert results[1].make == "SONY"


def test_read_many_does_not_start_exiftool_when_no_file_exists(exiftool, tmp_path, monkeypatch):
    runs = run_log(tmp_path, monkeypatch)
    results = exiftool.read_many([tmp_path / "a.ARW", tmp_path / "b.ARW"])

    assert all(isinstance(r, ExiftoolError) and "File not found" in str(r) for r in results)
    assert runs() == []


def test_read_many_of_nothing_is_nothing(exiftool):
    assert exiftool.read_many([]) == []


def test_read_many_returns_the_requested_tags_of_each_file(exiftool, tmp_path):
    a = photo(tmp_path, {**SONY, "Software": "v1"}, name="a.ARW")
    b = photo(tmp_path, SONY, name="b.ARW")
    first, second = exiftool.read_many([a, b], ["Software"])

    assert first.tags == {"Software": "v1"} and second.tags == {}


def test_read_many_refuses_a_bad_tag_name_for_the_whole_call(exiftool, tmp_path):
    with pytest.raises(InvalidTag):
        exiftool.read_many([photo(tmp_path, SONY)], ["-overwrite_original"])


def test_read_many_of_a_run_that_produces_junk_raises(tmp_path):
    junk = tmp_path / "junk.py"
    junk.write_text("print(1)")
    with pytest.raises(ExiftoolError, match="unexpected"):
        Exiftool((sys.executable, str(junk))).read_many([photo(tmp_path, SONY)])


def test_read_many_of_a_slow_run_raises_a_timeout(tmp_path):
    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(10)")
    with pytest.raises(ExiftoolTimeout):
        Exiftool((sys.executable, str(slow)), timeout=0.5).read_many([photo(tmp_path, SONY)])


def test_the_fields_that_depend_on_which_camera_took_the_file_say_so():
    # A negative photographed on a light table: these describe the digitising camera.
    fields = Metadata.model_json_schema()["properties"]
    for name in ("shutter_seconds", "iso", "aperture", "focal_length_mm"):
        assert "THIS file" in fields[name]["description"], name
        assert "digitising camera" in fields[name]["description"], name
    assert "manual lens" in fields["aperture"]["description"]
