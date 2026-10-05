"""Against the real exiftool shipped with ART. Skipped when it isn't found.
The raw test also needs ART_MCP_TEST_RAW; the file is only read."""

import os
from pathlib import Path

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from art_mcp import artdir
from art_mcp.metadata import Exiftool

PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ART"
ART_DIR = artdir.find_art_dir(None, os.environ, PROGRAM_FILES)
EXIFTOOL = artdir.find_exiftool(ART_DIR) if ART_DIR else None
RAW = os.environ.get("ART_MCP_TEST_RAW")

needs_exiftool = pytest.mark.skipif(EXIFTOOL is None, reason="exiftool not found beside ART-cli")


@pytest.fixture
def exiftool():
    return Exiftool((str(EXIFTOOL),), timeout=60)


@needs_exiftool
def test_jpeg_fixed_fields_and_extra_tags(exiftool, tmp_path):
    exif = Image.Exif()
    exif[0x010F] = "ACME"  # Make
    exif[0x0110] = "Model One"
    exif[0x0131] = "art-mcp tests"  # Software
    exif[0x0112] = 6  # Orientation
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = "2024:05:06 07:08:09"  # DateTimeOriginal
    sub[0x8827] = 200  # ISO
    sub[0x829A] = IFDRational(1, 250)  # ExposureTime
    sub[0x829D] = IFDRational(28, 10)  # FNumber
    sub[0x920A] = IFDRational(50, 1)  # FocalLength
    jpeg = tmp_path / "caf\u00e9.jpg"  # non-ASCII name
    Image.new("RGB", (64, 48)).save(jpeg, exif=exif)

    m = exiftool.read(jpeg, ["Software", "NoSuchTag"])

    assert (m.make, m.model, m.lens) == ("ACME", "Model One", None)
    assert (m.iso, m.shutter_seconds, m.aperture, m.focal_length_mm) == (200, 0.004, 2.8, 50.0)
    assert m.capture_date == "2024-05-06T07:08:09"
    assert (m.width, m.height, m.orientation) == (64, 48, 6)
    assert m.tags == {"Software": "art-mcp tests"}


@needs_exiftool
@pytest.mark.skipif(not RAW or not Path(RAW).is_file(), reason="ART_MCP_TEST_RAW not set")
def test_raw_fixed_fields(exiftool):
    m = exiftool.read(Path(RAW))

    assert m.make and m.model
    assert m.iso and m.shutter_seconds and m.capture_date
    assert m.width and m.height and m.orientation


@needs_exiftool
def test_missing_file_is_an_error(exiftool, tmp_path):
    from art_mcp.metadata import ExiftoolError

    with pytest.raises(ExiftoolError, match="not found"):
        exiftool.read(tmp_path / "gone.jpg")


@needs_exiftool
def test_read_many_reads_real_files_in_one_run_and_names_the_ones_it_cannot(exiftool, tmp_path):
    from art_mcp.metadata import ExiftoolError

    def jpeg(name, iso):
        exif = Image.Exif()
        exif.get_ifd(0x8769)[0x8827] = iso  # ISO
        path = tmp_path / name
        Image.new("RGB", (8, 8)).save(path, exif=exif)
        return path

    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    first, second = jpeg("a.jpg", 100), jpeg("café à.jpg", 400)  # non-ASCII name
    results = exiftool.read_many([first, tmp_path / "gone.jpg", empty, second, first])

    assert [r.iso if not isinstance(r, ExiftoolError) else None for r in results] == [100, None, None, 400, 100]
    assert "not found" in str(results[1]) and "gone.jpg" in str(results[1])
    assert "empty" in str(results[2])
