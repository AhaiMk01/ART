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
    args = artcli.preview_args(
        IMG, OUT, profile=Path("C:/tmp/w.arp"), resize=Path("C:/tmp/r.arp"), fast=True
    )

    assert args == [
        "-o", str(OUT), "-f", "-Y", "-a",
        "-p", str(Path("C:/tmp/w.arp")), "-p", str(Path("C:/tmp/r.arp")),
        "-j85", "-c", str(IMG),
    ]


PROFILE = Path("C:/tmp/w.arp")


def export(fmt, quality=None, bit_depth=None, write_profile=False):
    return artcli.export_args(IMG, OUT, [PROFILE], fmt, quality, bit_depth, write_profile)


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


def test_preview_run_without_fast_export_has_no_f_flag():
    args = artcli.preview_args(
        IMG, OUT, profile=Path("C:/tmp/w.arp"), resize=Path("C:/tmp/r.arp"), fast=False
    )

    assert "-f" not in args
    assert args[:4] == ["-o", str(OUT), "-Y", "-a"]


def test_region_preview_layers_crop_between_profile_and_resize():
    args = artcli.preview_args(
        IMG, OUT, profile=Path("C:/tmp/w.arp"), resize=Path("C:/tmp/r.arp"),
        fast=False, crop=Path("C:/tmp/c.arp"),
    )  # fmt: skip

    layers = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
    assert layers == [str(Path(p)) for p in ("C:/tmp/w.arp", "C:/tmp/c.arp", "C:/tmp/r.arp")]


def test_crop_layer_is_pixel_geometry_without_a_fixed_ratio():
    from art_mcp import keyfile

    layer = keyfile.loads(artcli.crop_profile(artcli.Rect(10, 20, 300, 200)))

    assert layer == {
        "Crop": {"Enabled": "true", "X": "10", "Y": "20", "W": "300", "H": "200", "FixedRatio": "false"}
    }


def test_region_fractions_map_onto_the_frame_in_pixels():
    frame = artcli.Rect(100, 50, 6000, 4000)

    rect = artcli.region_rect(frame, x=0.25, y=0.5, w=0.5, h=0.25)

    assert rect == artcli.Rect(100 + 1500, 50 + 2000, 3000, 1000)


def test_region_rect_never_leaves_the_frame_or_collapses():
    frame = artcli.Rect(0, 0, 1000, 1000)

    assert artcli.region_rect(frame, x=0.9999, y=0.0, w=0.0001, h=1.0) == artcli.Rect(999, 0, 1, 1000)
    assert artcli.region_rect(frame, x=0.5, y=0.5, w=0.5, h=0.5) == artcli.Rect(500, 500, 500, 500)


def test_png_size_reads_the_header(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (6016).to_bytes(4, "big") + (1).to_bytes(4, "big"))

    assert artcli.png_size(png) == (6016, 1)


def test_frame_probe_strips_the_frame_with_only_frame_defining_groups():
    from art_mcp import keyfile

    profile = {
        "Exposure": {"Compensation": "1"},
        "Coarse Transformation": {"Rotate": "90"},
        "RAW Bayer": {"Border": "4"},
        "Crop": {"Enabled": "true", "X": "5"},
    }

    row = keyfile.loads(artcli.frame_probe_layer(profile, strip="row"))
    column = keyfile.loads(artcli.frame_probe_layer(profile, strip="column"))

    assert set(row) == {"Coarse Transformation", "RAW Bayer", "Crop", "Resize"}
    assert row["Coarse Transformation"] == {"Rotate": "90"}
    assert (row["Crop"]["X"], row["Crop"]["H"]) == ("0", "1") and int(row["Crop"]["W"]) > 100000
    assert (column["Crop"]["W"], int(column["Crop"]["H"]) > 100000) == ("1", True)
    assert row["Resize"] == {"Enabled": "false"}


def test_probe_run_applies_only_the_probe_layer():
    args = artcli.probe_args(IMG, OUT, layer=Path("C:/tmp/p.arp"))

    assert args == ["-o", str(OUT), "-n", "-Y", "-a", "-p", str(Path("C:/tmp/p.arp")), "-c", str(IMG)]
