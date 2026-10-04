from pathlib import Path

import pytest

from art_mcp.render import artcli

IMG = Path("D:/photos/IMG_1.ARW")
OUT = Path("C:/tmp/out.jpg")


def test_resolve_run_uses_sidecar_when_present():
    args = artcli.resolve_profile_args(IMG, OUT, sidecar=Path("D:/photos/IMG_1.ARW.arp"))

    assert args == ["-O", str(OUT), "-f", "-Y", "-a", "-p", str(Path("D:/photos/IMG_1.ARW.arp")), "-c", str(IMG)]


def test_resolve_run_uses_default_profile_without_sidecar():
    args = artcli.resolve_profile_args(IMG, OUT, sidecar=None)

    assert args == ["-O", str(OUT), "-f", "-Y", "-a", "-d", "-c", str(IMG)]


def test_preview_run_layers_working_profile_then_resize():
    args = artcli.preview_args(IMG, OUT, profile=Path("C:/tmp/w.arp"), resize=Path("C:/tmp/r.arp"))

    assert args == [
        "-o", str(OUT), "-f", "-Y", "-a",
        "-p", str(Path("C:/tmp/w.arp")), "-p", str(Path("C:/tmp/r.arp")),
        "-j85", "-c", str(IMG),
    ]


PROFILE = Path("C:/tmp/w.arp")


def export(fmt, quality=None, bit_depth=None, write_profile=False):
    return artcli.export_args(IMG, OUT, PROFILE, fmt, quality, bit_depth, write_profile)


def test_jpeg_export_is_full_size_with_quality_and_no_resize_flag():
    assert export("jpeg", quality=90) == [
        "-o", str(OUT), "-Y", "-a", "-p", str(PROFILE), "-j90", "-c", str(IMG),
    ]  # fmt: skip


def flags(args):
    """The format flags between the profile and ``-c``."""
    return args[args.index(str(PROFILE)) + 1 : args.index("-c")]


def test_jpeg_without_quality_takes_arts_default():
    assert flags(export("jpeg")) == ["-j"]


def test_tiff_and_png_flags_with_bit_depth():
    assert flags(export("tiff", bit_depth="16f")) == ["-t", "-b16f"]
    assert flags(export("png", bit_depth="16")) == ["-n", "-b16"]
    assert flags(export("tiff")) == ["-t"]


def test_write_profile_switches_to_dash_big_o():
    assert export("png", write_profile=True)[0] == "-O"


@pytest.mark.parametrize(
    "fmt, quality, bit_depth",
    [
        ("jpeg", 0, None),
        ("jpeg", 101, None),
        ("jpeg", None, "16"),
        ("png", 90, None),
        ("tiff", 90, None),
        ("png", None, "32"),
        ("png", None, "16f"),
        ("tiff", None, "12"),
        ("bmp", None, None),
    ],
)
def test_invalid_combinations_are_rejected(fmt, quality, bit_depth):
    with pytest.raises(ValueError):
        export(fmt, quality, bit_depth)


def test_jpeg_accepts_8_bit():
    assert flags(export("jpeg", 80, "8")) == ["-j80", "-b8"]
