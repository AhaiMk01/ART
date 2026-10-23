"""A Film Negative profile written by art_mcp, read by a real ART-cli.

The unit tests hand art_mcp's own output to art_mcp; none of them proved ART can
load it. ART once read 3-value lists as curves and refused every profile it was
handed, which no test noticed. Skipped unless `ART_DIR` names a current ART
build (the installed ART may predate it) and, on Windows, its runtime DLLs are
on PATH.
"""

import copy
import hashlib
import json
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
from PIL import Image

from art_mcp import artdir, keyfile
from art_mcp.metadata import Exiftool
from art_mcp.profile import WorkingChanges
from art_mcp.schema import AdjustmentError, parse_adjustments

CLI = None
if os.environ.get("ART_DIR"):
    found = artdir.find_art_dir(None, os.environ, None)
    CLI = artdir.find_cli(found) if found else None

pytestmark = pytest.mark.skipif(CLI is None, reason="ART_DIR does not name an ART build")

BASIS = '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}'


def run_cli(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(CLI), *args], capture_output=True, text=True, timeout=120, cwd=tmp_path, check=False)


@pytest.fixture
def scan(tmp_path):
    path = tmp_path / "scan.tif"
    Image.new("RGB", (32, 32), (128, 128, 128)).save(path)
    return path


def render(tmp_path: Path, scan: Path, profile: dict, tag: str):
    """Render ``scan`` with ``profile``; the process result and the sidecar ART
    wrote after loading it (None if it wrote none)."""
    profile_path = tmp_path / f"{tag}.arp"
    profile_path.write_text(keyfile.dumps(profile))
    out = tmp_path / f"{tag}.jpg"
    result = run_cli(["-O", str(out), "-Y", "-a", "-p", str(profile_path), "-c", str(scan)], tmp_path)
    written = Path(f"{out}.arp")
    return result, keyfile.loads(written.read_text()) if written.exists() else None


@pytest.fixture
def base(tmp_path, scan):
    """ART's own default profile for the scan, as the Render server starts from."""
    result, loaded = render(tmp_path, scan, {}, "base")
    assert result.returncode == 0 and loaded is not None, result.stderr
    if "Method" not in loaded.get("Film Negative", {}):
        pytest.skip("this ART has no film negative method")
    return loaded


def film(base: dict, **fields):
    # WorkingChanges edits the dict it is given: copy, so one test's profile
    # never leaks into the next built from the same base.
    changes = WorkingChanges(copy.deepcopy(base))
    changes.edit(parse_adjustments({"film_negative": {"enabled": True, "method": "namicolor", **fields}}), [])
    return changes.profile


def pixels(path: Path) -> str:
    """Digest every decoded RGB pixel without dumping a whole RAW on failure."""
    with Image.open(path) as jpeg:
        return hashlib.sha256(jpeg.convert("RGB").tobytes()).hexdigest()


def numbers(text: str) -> list[float]:
    return [float(part) for part in text.split(";") if part]


def tiff_rgb_samples(path):
    """Read the engine's uncompressed RGB TIFF at its actual sample depth."""
    data = path.read_bytes()
    order = "<" if data[:2] == b"II" else ">"
    offset = struct.unpack_from(order + "I", data, 4)[0]
    count = struct.unpack_from(order + "H", data, offset)[0]
    tags = {}
    for index in range(count):
        entry = offset + 2 + 12 * index
        tag, kind, length, value = struct.unpack_from(order + "HHII", data, entry)
        if kind not in (3, 4):
            continue
        size, code = (2, "H") if kind == 3 else (4, "I")
        start = entry + 8 if size * length <= 4 else value
        tags[tag] = struct.unpack_from(order + code * length, data, start)
    assert tags[259] == (1,)
    assert tags[277] == (3,)
    assert len(tags[273]) == 1
    bits = tags[258][0]
    floating = tags.get(339, (1,))[0] == 3
    assert (bits, floating) in ((16, False), (32, True))
    code = "f" if floating else "H"
    total = tags[256][0] * tags[257][0] * 3
    values = struct.unpack_from(order + code * total, data, tags[273][0])
    return [values[index:index + 3] for index in range(0, total, 3)]


def test_a_default_namicolor_profile_loads(tmp_path, scan, base):
    result, loaded = render(tmp_path, scan, film(base), "plain")

    assert result.returncode == 0, result.stderr
    assert loaded is not None
    assert loaded["Film Negative"]["Method"] == "namicolor"


@pytest.mark.parametrize("stored", ["density", "1"])
def test_a_removed_density_method_loads_as_power_law_and_ignores_its_keys(tmp_path, scan, base, stored):
    profile = film(base, method="power_law")
    profile["Film Negative"].update({"Method": stored, "DensityGamma": "1.4", "RGBGains": "0.5;0;0"})

    result, loaded = render(tmp_path, scan, profile, "density-removed")

    assert result.returncode == 0, result.stderr
    assert loaded is not None
    film_group = loaded["Film Negative"]
    assert film_group["Method"] == "power_law"
    assert "DensityGamma" not in film_group and "RGBGains" not in film_group


@pytest.mark.parametrize(
    "matrix",
    [
        [2.0, 0.2, 0, 0, 0.9, 0, 0, 0, 1],  # a first coefficient of 2 once read as a curve marker
        [-10, 10, 0.125, 0.0001, 1.0197, -0.0052, 3, 2, 1.1],
    ],
)
def test_a_custom_matrix_comes_back_as_written(tmp_path, scan, base, matrix):
    profile = film(base, matrix_preset="custom", matrix=matrix, matrix_basis=BASIS)

    result, loaded = render(tmp_path, scan, profile, "matrix")

    assert result.returncode == 0, result.stderr
    assert loaded is not None
    assert numbers(loaded["Film Negative"]["Matrix"]) == pytest.approx(matrix, abs=1e-12)


def test_namicolor_rejects_an_invalid_denominator_in_a_sidecar(tmp_path, scan, base):
    """Raw sidecars must not bypass the coupled-control validation."""
    profile = film(base, method="namicolor")
    profile["Film Negative"]["NamiColorGain"] = "1;0;0;"
    result, _ = render(tmp_path, scan, profile, "invalid-namicolor")
    assert result.returncode != 0
    assert not (tmp_path / "invalid-namicolor.jpg").exists()


def test_transmission_floor_keeps_black_raw_values_finite_on_new_profiles(tmp_path, base):
    # Raw values at black (dense lamps) under a steep fit: the 1e-10 floor of
    # sidecars before 1060 decodes them past float range; one 16-bit code does not.
    black = tmp_path / "black.tif"
    Image.new("RGB", (32, 32), (0, 0, 0)).save(black)
    profile = film(base, method="namicolor", namicolor_input_gain=1, namicolor_gain=[0.218, 0.218, 0.218])
    result, written = render(tmp_path, black, profile, "floor-new")
    assert result.returncode == 0, result.stdout + result.stderr
    assert float(written["Film Negative"]["TransmissionFloor"]) == pytest.approx(1 / 65535)

    old = copy.deepcopy(profile)
    old["Version"]["Version"] = "1059"
    old["Film Negative"].pop("TransmissionFloor", None)
    result, _ = render(tmp_path, black, old, "floor-old")
    assert result.returncode != 0
    assert "non-finite" in result.stdout + result.stderr


@pytest.mark.parametrize("film_type", ["negative", "reversal"])
def test_namicolor_identity_is_exact_and_old_dormant_masks_migrate(tmp_path, scan, base, film_type):
    identity = film(
        base, method="namicolor", film_type=film_type,
        namicolor_input_gain=0.2, namicolor_master_shift=-0.35,
    )
    result, _ = render(tmp_path, scan, identity, "mask-identity")
    assert result.returncode == 0, result.stdout + result.stderr
    expected = pixels(tmp_path / "mask-identity.jpg")

    # Identity ignores even stale invalid retained coefficients and bindings.
    stale = keyfile.loads(keyfile.dumps(identity))
    stale["Film Negative"].update({"Matrix": "nan;0;0;0;2;0;0;0;3;", "MatrixBasis": "old basis"})
    result, _ = render(tmp_path, scan, stale, "mask-stale-identity")
    assert result.returncode == 0, result.stdout + result.stderr
    assert pixels(tmp_path / "mask-stale-identity.jpg") == expected

    custom_identity = film(
        identity, method="namicolor", matrix_preset="custom",
        matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1], matrix_basis=BASIS,
    )
    result, _ = render(tmp_path, scan, custom_identity, "mask-custom-identity")
    assert result.returncode == 0, result.stdout + result.stderr
    assert pixels(tmp_path / "mask-custom-identity.jpg") == expected

    for preset in ("custom", "status_m_reference"):
        old = keyfile.loads(keyfile.dumps(identity))
        old["Version"]["Version"] = "1054"
        retained = "1;0.4;0;0;1;0;0;0;1;"
        old["Film Negative"].update({
            "MatrixPreset": preset, "Matrix": retained,
            "MatrixBasis": "old incompatible basis", "CalibrationNote": "retained calibration provenance",
        })
        result, loaded = render(tmp_path, scan, old, f"old-mask-{preset}")
        assert result.returncode == 0, result.stdout + result.stderr
        assert pixels(tmp_path / f"old-mask-{preset}.jpg") == expected
        assert loaded["Film Negative"]["MatrixPreset"] == "identity"
        assert numbers(loaded["Film Negative"]["Matrix"]) == numbers(retained)
        assert loaded["Film Negative"]["MatrixBasis"] == "old incompatible basis"
        assert loaded["Film Negative"]["CalibrationNote"] == "retained calibration provenance"


@pytest.mark.parametrize("basis", [
    "",
    BASIS.replace('"working"', '"input"'),
    BASIS.replace('"Rec2020"', '"ProPhoto"'),
    BASIS.replace('"input_gamma":"1"', '"input_gamma":"1.2"'),
    BASIS.replace('"Unknown"', '"Different camera"'),
])
@pytest.mark.parametrize("preset", ["custom", "status_m_reference"])
def test_namicolor_active_mask_rejects_missing_or_mismatched_basis(tmp_path, scan, base, basis, preset):
    profile = film(base, method="namicolor", namicolor_input_gain=0.2)
    # Write raw sidecar fields as well as typed success cases above: engine validation
    # must protect GUI, CLI and profiles that bypass the MCP editing policy.
    profile["Film Negative"].update({
        "MatrixPreset": preset, "Matrix": "1;0.2;0;0;1;0;0;0;1;", "MatrixBasis": basis,
    })
    result, _ = render(tmp_path, scan, profile, "invalid-mask-basis")
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (tmp_path / "invalid-mask-basis.jpg").exists()


def test_namicolor_active_custom_mask_rejects_nonfinite_sidecar_coefficients(tmp_path, scan, base):
    profile = film(base, method="namicolor")
    profile["Film Negative"].update({
        "MatrixPreset": "custom", "Matrix": "nan;0;0;0;1;0;0;0;1;", "MatrixBasis": BASIS,
    })
    result, _ = render(tmp_path, scan, profile, "invalid-mask-finite")
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (tmp_path / "invalid-mask-finite.jpg").exists()


def test_real_raw_namicolor_typed_mask_changes_pixels_and_identity_preserves_them(tmp_path, monkeypatch):
    # Compare mask behaviour, not scheduling-dependent RAW processing noise.
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("ART_GPU", "off")
    raw_source = os.environ.get("ART_MCP_TEST_RAW")
    if not raw_source or not Path(raw_source).is_file():
        pytest.skip("ART_MCP_TEST_RAW does not name a real RAW")
    found = artdir.find_art_dir(None, os.environ, None)
    exiftool = os.environ.get("ART_MCP_EXIFTOOL") or (artdir.find_exiftool(found) if found else None)
    if not exiftool:
        pytest.skip("exiftool not found beside ART-cli or via ART_MCP_EXIFTOOL")
    raw = tmp_path / Path(raw_source).name
    shutil.copyfile(raw_source, raw)
    result, loaded = render(tmp_path, raw, {}, "raw-default")
    assert result.returncode == 0 and loaded is not None, result.stdout + result.stderr
    # Read ART's exported, normalized make/model, not an invented source identity.
    metadata = Exiftool((str(exiftool),), timeout=60).read(tmp_path / "raw-default.jpg")
    source = f"{metadata.make or ''} {metadata.model or ''}"
    if source == " ":
        source = "Unknown"
    identity = film(
        loaded, method="namicolor", color_space="working",
        namicolor_input_gain=0.2, namicolor_master_shift=-0.35,
    )
    identity["Color Management"]["WorkingProfile"] = "Rec2020"
    result, _ = render(tmp_path, raw, identity, "raw-identity")
    assert result.returncode == 0, result.stdout + result.stderr
    expected = pixels(tmp_path / "raw-identity.jpg")
    basis = json.dumps({
        "v": 1, "color_space": "working", "profile": "Rec2020",
        "input_gamma": "1", "source": source,
    })
    custom_identity = film(
        identity, method="namicolor", matrix_preset="custom",
        matrix=[1, 0, 0, 0, 1, 0, 0, 0, 1], matrix_basis=basis,
    )
    result, _ = render(tmp_path, raw, custom_identity, "raw-custom-identity")
    assert result.returncode == 0, result.stdout + result.stderr
    assert pixels(tmp_path / "raw-custom-identity.jpg") == expected
    custom_identity["Version"]["Version"] = "1054"
    request = parse_adjustments({"film_negative": {
        "matrix": [1, 0.4, 0, 0, 1, 0, 0, -0.3, 1],
    }})
    with pytest.raises(AdjustmentError, match="below Version 1055"):
        WorkingChanges(custom_identity).edit(request, [])
    custom_identity["Version"]["Version"] = "1055"
    changes = WorkingChanges(custom_identity)
    changes.edit(request, [])
    assert changes.profile["Version"]["Version"] == "1055"
    result, _ = render(tmp_path, raw, changes.profile, "raw-mixed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert pixels(tmp_path / "raw-mixed.jpg") != expected


def _unit_white_profile(base, version=None, **fields):
    """NamiColor with input gain 0 and a shift that puts every channel on Cineon code 685,
    exported as unprinted linear float: the pixel value is the decode's reference white."""
    profile = film(
        base, method="namicolor", color_space="working", namicolor_input_gain=0,
        namicolor_shift=[685 / 1023 - 1] * 3, **fields,
    )
    profile["Exposure"]["Enabled"] = "false"
    profile["Color Management"].update({"WorkingProfile": "sRGB", "OutputProfile": "(none)"})
    if version is not None:  # an older sidecar: ART reads the missing keys by its version
        profile["Version"]["Version"] = str(version)
        for key in ("CineonReferenceWhite", "NamiColorFitBaseAnchor"):
            profile["Film Negative"].pop(key, None)
    return profile


@pytest.mark.parametrize(
    ("version", "white"),
    [(None, 0.9), (1058, 0.9), (1057, 1.0)],
)
def test_namicolor_code_685_decodes_to_the_default_reference_white(tmp_path, scan, base, version, white):
    """New profiles: code 685 is 90% diffuse white (W 0.9). A sidecar below Version 1058
    without the key keeps W 1 and renders as before."""
    profile = _unit_white_profile(base, version)
    arp = tmp_path / "white.arp"
    arp.write_text(keyfile.dumps(profile))
    output = tmp_path / "white.tif"
    result = run_cli(["-a", "-o", str(output), "-t", "-b32", "-p", str(arp), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    for pixel in tiff_rgb_samples(output):
        assert pixel == pytest.approx([white] * 3, rel=2e-5)


def test_an_explicit_reference_white_wins_on_an_old_sidecar(tmp_path, scan, base):
    profile = _unit_white_profile(base, 1057)
    profile["Film Negative"]["CineonReferenceWhite"] = "0.5"
    arp = tmp_path / "explicit-white.arp"
    arp.write_text(keyfile.dumps(profile))
    output = tmp_path / "explicit-white.tif"
    result = run_cli(["-a", "-o", str(output), "-t", "-b32", "-p", str(arp), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    for pixel in tiff_rgb_samples(output):
        assert pixel == pytest.approx([0.5] * 3, rel=2e-5)


def _render_png(tmp_path, scan, arp, name):
    out = tmp_path / name
    result = run_cli(["-O", str(out), "-a", "-n", "-b16", "-p", str(arp), "-c", str(scan)], tmp_path)
    return result, out


def _png_pixels(path):
    # Decoded pixel rows only: ART writes metadata (zTXt) that differs per run.
    data = path.read_bytes()
    pos, idat = 8, []
    while pos < len(data):
        (length,) = struct.unpack_from(">I", data, pos)
        if data[pos + 4:pos + 8] == b"IDAT":
            idat.append(data[pos + 8:pos + 8 + length])
        pos += 12 + length
    return zlib.decompress(b"".join(idat))


def _refused(tmp_path, scan, arp, name):
    result, out = _render_png(tmp_path, scan, arp, name)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not out.exists()


def _srgb_decode(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _srgb_encode(v):
    return v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _gradient_scan(path, flare=0.0, noise=False):
    # An untagged 8-bit TIFF is read as sRGB: veiling light adds in LINEAR light,
    # so `flare` is added after decoding and the sum re-encoded.
    import random

    rng = random.Random(1)
    image = Image.new("RGB", (48, 48))
    for y in range(48):
        for x in range(48):
            level = 40 + x * 2
            jitter = rng.randint(-12, 12) if noise else 0
            values = []
            for c in (0, 3, 6):
                code = min(255, max(0, level + jitter + c))
                if flare:
                    code = round(255 * _srgb_encode(min(1.0, _srgb_decode(code / 255) + flare)))
                values.append(code)
            image.putpixel((x, y), tuple(values))
    image.save(path)
    return path


def _render_jpg_pixels(tmp_path, scan, profile, tag):
    result, loaded = render(tmp_path, scan, profile, tag)
    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(tmp_path / f"{tag}.jpg") as jpeg:
        return jpeg.convert("RGB")


def test_zero_flare_renders_like_no_flare_key(tmp_path, base):
    scan = _gradient_scan(tmp_path / "g.tif")
    plain = film(base)
    plain["Film Negative"].pop("Flare", None)
    zero = film(base, flare=[0, 0, 0])
    assert _png_pixels_of(tmp_path, scan, plain, "plain") == _png_pixels_of(tmp_path, scan, zero, "zero")


def _png_pixels_of(tmp_path, scan, profile, tag):
    arp = tmp_path / f"{tag}.arp"
    arp.write_text(keyfile.dumps(profile))
    result, out = _render_png(tmp_path, scan, arp, f"{tag}.png")
    assert result.returncode == 0, result.stdout + result.stderr
    return _png_pixels(out)


def test_flare_equal_to_an_additive_offset_renders_like_the_clean_negative(tmp_path, base):
    f = 0.01  # linear transmission fraction
    clean = _gradient_scan(tmp_path / "clean.tif")
    veiled = _gradient_scan(tmp_path / "veiled.tif", flare=f)
    want = _render_jpg_pixels(tmp_path, clean, film(base), "clean")
    got = _render_jpg_pixels(tmp_path, veiled, film(base, flare=[f, f, f]), "veiled")
    uncorrected = _render_jpg_pixels(tmp_path, veiled, film(base), "uncorrected")

    def worst(a, b):
        pairs = zip(a.getdata(), b.getdata(), strict=True)
        return max(abs(p - q) for pa, pb in pairs for p, q in zip(pa, pb, strict=True))

    assert worst(want, uncorrected) > worst(want, got)
