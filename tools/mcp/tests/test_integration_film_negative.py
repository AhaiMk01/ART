"""A Film Negative profile written by art_mcp, read by a real ART-cli.

The unit tests hand art_mcp's own output to art_mcp; none of them proved ART can
load it. ART once read the 3-value `RGBGains` and `ChannelGamma` lists as curves
and refused every profile it was handed, which no test noticed. Skipped unless
`ART_DIR` names an ART build with the density method (the installed ART may
predate it) and, on Windows, its runtime DLLs are on PATH.
"""

import copy
import hashlib
import json
import math
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
        pytest.skip("this ART has no density method")
    return loaded


def density(base: dict, **fields):
    # WorkingChanges edits the dict it is given: copy, so one test's profile
    # never leaks into the next built from the same base.
    changes = WorkingChanges(copy.deepcopy(base))
    changes.edit(parse_adjustments({"film_negative": {"enabled": True, "method": "density", **fields}}), [])
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


def test_a_default_density_profile_loads(tmp_path, scan, base):
    result, loaded = render(tmp_path, scan, density(base), "plain")

    assert result.returncode == 0, result.stderr
    assert loaded is not None
    assert loaded["Film Negative"]["Method"] == "density"
    assert numbers(loaded["Film Negative"]["RGBGains"]) == [0, 0, 0]


def test_gains_and_channel_gamma_come_back_as_written(tmp_path, scan, base):
    gains = [-2.270584822, -2.521374106, -2.84470892]
    gammas = [0.8, 1.2, 1.5]

    result, loaded = render(tmp_path, scan, density(base, rgb_gains=gains, channel_gamma=gammas), "gains")

    assert result.returncode == 0, result.stderr
    assert loaded is not None
    film = loaded["Film Negative"]
    assert numbers(film["RGBGains"]) == pytest.approx(gains, abs=1e-12)
    assert numbers(film["ChannelGamma"]) == pytest.approx(gammas, abs=1e-12)


@pytest.mark.parametrize(
    "matrix",
    [
        [2.0, 0.2, 0, 0, 0.9, 0, 0, 0, 1],  # a first coefficient of 2 once read as a curve marker
        [-10, 10, 0.125, 0.0001, 1.0197, -0.0052, 3, 2, 1.1],
    ],
)
def test_a_custom_matrix_comes_back_as_written(tmp_path, scan, base, matrix):
    profile = density(base, matrix_preset="custom", matrix=matrix, matrix_basis=BASIS)

    result, loaded = render(tmp_path, scan, profile, "matrix")

    assert result.returncode == 0, result.stderr
    assert loaded is not None
    assert numbers(loaded["Film Negative"]["Matrix"]) == pytest.approx(matrix, abs=1e-12)


INVERTING_CUBE = "LUT_3D_SIZE 2\n" + "".join(
    f"{1 - r} {1 - g} {1 - b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)
)


def test_a_print_lut_left_in_a_power_law_profile_is_inactive(tmp_path, scan, base):
    """Switching methods keeps the inactive values: the LUT belongs to Density, so
    a Power-law render does not apply it."""
    cube = tmp_path / "invert.cube"
    cube.write_text(INVERTING_CUBE)
    digest = hashlib.sha256(cube.read_bytes()).hexdigest()
    plain = render(tmp_path, scan, density(base, method="power_law"), "pl_plain")[0]
    # a Windows path: its backslashes must be escaped in the sidecar, or ART
    # refuses the whole profile at `\U`
    profile = density(base, method="power_law", cineon_lut=str(cube), cineon_lut_sha256=digest)

    result, _ = render(tmp_path, scan, profile, "pl_lut")

    assert plain.returncode == 0, plain.stderr
    assert result.returncode == 0, result.stderr
    assert pixels(tmp_path / "pl_lut.jpg") == pixels(tmp_path / "pl_plain.jpg")


def test_the_same_print_lut_does_change_a_density_render(tmp_path, scan, base):
    """The control for the test above: with Density the LUT is applied."""
    cube = tmp_path / "invert.cube"
    cube.write_text(INVERTING_CUBE)
    digest = hashlib.sha256(cube.read_bytes()).hexdigest()
    plain = render(tmp_path, scan, density(base), "d_plain")[0]
    profile = density(base, cineon_lut=str(cube), cineon_lut_sha256=digest)

    result, _ = render(tmp_path, scan, profile, "d_lut")

    assert plain.returncode == 0, plain.stderr
    assert result.returncode == 0, result.stderr
    assert pixels(tmp_path / "d_lut.jpg") != pixels(tmp_path / "d_plain.jpg")


@pytest.mark.parametrize("film_type", ["negative", "reversal"])
@pytest.mark.parametrize("fit_base", [False, True])
@pytest.mark.parametrize("mask", ["identity", "mixed"])
def test_namicolor_cineon_export_matches_log_channel_alignment(tmp_path, base, film_type, fit_base, mask):
    """Exercise the engine, not a Python reimplementation handed back to itself."""
    scan = tmp_path / "colour-patches.png"
    image = Image.new("RGB", (128, 32))
    for index, colour in enumerate([(32, 24, 16), (96, 48, 32), (128, 96, 48), (200, 160, 128)]):
        image.paste(colour, (index * 32, 0, (index + 1) * 32, 32))
    image.save(scan)
    master_shift = -0.25 if film_type == "reversal" else -0.35
    profile = density(
        base,
        method="namicolor",
        film_type=film_type,
        color_space="working",
        target_mode="cineon",
        namicolor_input_gain=0.2,
        namicolor_master_gain=0.03,
        namicolor_master_shift=master_shift,
        namicolor_black=[0.01, -0.02, 0.03],
        namicolor_gain=[0.05, -0.04, 0.02],
        namicolor_shift=[0.02, -0.03, 0.04],
        namicolor_fit_base=fit_base,
        fit_base_anchor="code95",
    )
    profile["Color Management"]["OutputProfile"] = "(none)"
    matrix = [1, 0.25, -0.1, -0.15, 1, 0.2, 0.1, -0.2, 1]
    if mask == "mixed":
        changes = WorkingChanges(profile)
        changes.edit(parse_adjustments({"film_negative": {
            "matrix_preset": "custom", "matrix": matrix, "matrix_basis": BASIS,
        }}), [])
        assert int(changes.profile["Version"]["Version"]) >= 1055
        profile = changes.profile
    path = tmp_path / "namicolor.arp"
    path.write_text(keyfile.dumps(profile))
    centres = [(16 + index * 32, 16) for index in range(4)]
    coordinates = ",".join(str(value) for point in centres for value in point)
    sampled = run_cli(["-a", "-p", str(path), "-x", f"8,working,{coordinates}", "-c", str(scan)], tmp_path)
    assert sampled.returncode == 0, sampled.stdout + sampled.stderr
    line = next(line for line in sampled.stdout.splitlines() if line.startswith("ART-SPOTS "))
    spots = json.loads(line.removeprefix("ART-SPOTS "))["spots"]
    out = tmp_path / "cineon.tif"
    rendered = run_cli(["-O", str(out), "-a", "-t", "-b16", "-p", str(path), "-c", str(scan)], tmp_path)
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    with Image.open(out) as result:
        assert result.tag_v2[258] == (16, 16, 16)
        for point, spot in zip(centres, spots, strict=True):
            expected = []
            densities = [-math.log10(max(value / 65535, 1e-10)) for value in spot["avg"]]
            if mask == "mixed":
                densities = [
                    0.7 + sum(matrix[row * 3 + col] * (densities[col] - 0.7) for col in range(3))
                    for row in range(3)
                ]
            for channel, transmission in enumerate(spot["avg"]):
                if mask == "mixed":
                    initial = (
                        1 + 0.2 * (densities[channel] - math.log10(16))
                        if film_type == "negative"
                        else 0.8 - 0.2 * densities[channel]
                    )
                else:
                    transmission = max(transmission / 65535, 1e-10)
                    initial = (
                        1 - 0.2 * math.log10(16 * transmission)
                        if film_type == "negative"
                        else 0.8 + 0.2 * math.log10(transmission)
                    )
                black = [0.01, -0.02, 0.03][channel]
                gain = [0.05, -0.04, 0.02][channel]
                shift = [0.02, -0.03, 0.04][channel]
                code = (initial + shift + master_shift + black) / (1 - gain - 0.03 + black)
                if fit_base:
                    code = (95 + 928 * code) / 1023  # normalized 0 -> code 95, 1 -> code 1023
                assert 0 <= code <= 1
                # Pillow exposes 16-bit RGB as the high eight bits.
                expected.append(round(code * 65535) >> 8)
            assert result.getpixel(point) == pytest.approx(expected, abs=1)
    saved = keyfile.loads(Path(f"{out}.arp").read_text())
    assert saved["Film Negative"]["Method"] == "namicolor"
    assert saved["Film Negative"]["NamiColorFitBase"] == str(fit_base).lower()
    assert saved["Film Negative"]["NamiColorFitBaseAnchor"] == "code95"


def test_namicolor_rejects_an_invalid_denominator_in_a_sidecar(tmp_path, scan, base):
    """Raw sidecars must not bypass the coupled-control validation."""
    profile = density(base, method="namicolor")
    profile["Film Negative"]["NamiColorGain"] = "1;0;0;"
    result, _ = render(tmp_path, scan, profile, "invalid-namicolor")
    assert result.returncode != 0
    assert not (tmp_path / "invalid-namicolor.jpg").exists()


def test_namicolor_lut_accepts_builtin_working_primaries_and_maps_its_output(tmp_path, scan, base):
    """Built-in working spaces are not files in the output-ICC registry."""
    cube = tmp_path / "constant.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "0.18 0.09 0.03\n" * 8)
    profile = density(
        base,
        method="namicolor",
        color_space="input",
        namicolor_input_gain=0.2,
        namicolor_master_shift=-0.4,
        cineon_lut=str(cube),
        cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_input_primaries="sRGB",
        cineon_lut_output_primaries="sRGB",
        cineon_lut_output_transfer="linear",
    )
    profile["Color Management"]["WorkingProfile"] = "Rec2020"
    profile["Color Management"]["OutputProfile"] = "RTv2_sRGB"
    path = tmp_path / "managed-lut.arp"
    path.write_text(keyfile.dumps(profile))
    out = tmp_path / "managed-lut.png"
    result = run_cli(["-O", str(out), "-a", "-n", "-b16", "-p", str(path), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(out) as image:
        assert image.getpixel((16, 16)) == pytest.approx([118, 85, 48], abs=2)


def test_cineon_lut_clamps_gamut_excursions_without_losing_in_domain_channels(tmp_path, scan, base):
    """A finite out-of-gamut value must reach the LUT boundary, not abort the frame."""
    cube = tmp_path / "identity.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "".join(f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)))
    profile = density(
        base,
        method="namicolor",
        color_space="working",
        namicolor_input_gain=0,
        cineon_reference_white=1,
        namicolor_shift=[-0.98, -0.35, -0.6],
        cineon_lut=str(cube),
        cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_input_primaries="sRGB",
        cineon_lut_output_primaries="sRGB",
        cineon_lut_output_transfer="linear",
    )
    profile["Color Management"]["WorkingProfile"] = "Rec2020"
    profile["Color Management"]["OutputProfile"] = "RTv2_sRGB"
    path = tmp_path / "gamut-lut.arp"
    path.write_text(keyfile.dumps(profile))
    out = tmp_path / "gamut-lut.png"
    result = run_cli(["-O", str(out), "-a", "-n", "-b16", "-p", str(path), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    # Cineon codes .02/.65/.4 decode to Rec2020 linear
    # (-.0047556, .8558099, .1108099). Rec2020 -> sRGB yields
    # (-.5188781, .9692142, .0379762); the red coordinate is below the
    # LUT's code-zero boundary, while green/blue encode to .6656604/.2838282.
    with Image.open(out) as image:
        assert image.getpixel((16, 16)) == pytest.approx([0, 213, 145], abs=2)


@pytest.mark.parametrize(
    ("transfer", "reference"),
    [
        ("cineon", [0.0928641251, 0.4573196131, 0.6695992180]),
        ("linear", [0, 0.18, 1]),
        ("srgb", [0, 0.4613561295, 1]),
        ("gamma_2_4", [0, 0.4894370896, 1]),
        ("logc3", [0.092809, 0.3910068320, 0.5706315581]),
        ("slog3", [0.0928641251, 0.4105571848, 0.5960273437]),
        ("acescct", [0.0729055342, 0.4135884025, 0.5547945205]),
    ],
)
def test_lut_input_transfer_encodes_linear_black_grey_and_white(tmp_path, scan, base, transfer, reference):
    cube = tmp_path / "identity.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "".join(f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)))
    profile = density(
        base,
        method="namicolor",
        color_space="working",
        namicolor_input_gain=0,
        cineon_reference_white=1,
        # Decoding these three Cineon coordinates gives linear 0/.18/1.
        namicolor_shift=[0.0928641251 - 1, 0.4573196131 - 1, 0.6695992180 - 1],
        cineon_lut=str(cube),
        cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_input_transfer=transfer,
        cineon_lut_output_transfer="linear",
    )
    profile["Color Management"]["OutputProfile"] = "(none)"
    path = tmp_path / "transfer.arp"
    path.write_text(keyfile.dumps(profile))
    out = tmp_path / "transfer.png"
    result = run_cli(["-O", str(out), "-a", "-n", "-b16", "-p", str(path), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(out) as image:
        expected = [round(value * 65535) >> 8 for value in reference]
        assert image.getpixel((16, 16)) == pytest.approx(expected, abs=1)


@pytest.mark.parametrize("film_type", ["negative", "reversal"])
def test_namicolor_identity_is_exact_and_old_dormant_masks_migrate(tmp_path, scan, base, film_type):
    identity = density(
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

    custom_identity = density(
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
    profile = density(base, method="namicolor", namicolor_input_gain=0.2)
    # Write raw sidecar fields as well as typed success cases above: engine validation
    # must protect GUI, CLI and profiles that bypass the MCP editing policy.
    profile["Film Negative"].update({
        "MatrixPreset": preset, "Matrix": "1;0.2;0;0;1;0;0;0;1;", "MatrixBasis": basis,
    })
    result, _ = render(tmp_path, scan, profile, "invalid-mask-basis")
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (tmp_path / "invalid-mask-basis.jpg").exists()


def test_namicolor_active_custom_mask_rejects_nonfinite_sidecar_coefficients(tmp_path, scan, base):
    profile = density(base, method="namicolor")
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
    identity = density(
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
    custom_identity = density(
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


@pytest.mark.parametrize("method", ["density", "namicolor"])
@pytest.mark.parametrize(
    "stage, expected",
    [("before_grade", (46, 92, 138)), ("after_grade", (23, 46, 69))],
)
def test_print_lut_order_does_not_commute_with_scene_exposure(tmp_path, scan, base, method, stage, expected):
    # A constant linear LUT returns (.09, .18, .27). Exposure +1 doubles those
    # only when the LUT precedes grading: (.18, .36, .54). No output transfer.
    cube = tmp_path / "constant.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "0.09 0.18 0.27\n" * 8)
    profile = density(
        base, method=method, cineon_lut=str(cube),
        cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_stage=stage, cineon_lut_input_transfer="linear",
        cineon_lut_output_transfer="linear",
    )
    profile["Color Management"].update({"WorkingProfile": "sRGB", "OutputProfile": "(none)"})
    profile["Exposure"].update({"Enabled": "true", "Compensation": "1", "Black": "0"})
    path = tmp_path / "order.arp"
    path.write_text(keyfile.dumps(profile))
    out = tmp_path / "order.png"
    result = run_cli(["-O", str(out), "-a", "-n", "-b16", "-p", str(path), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    with Image.open(out) as image:
        assert image.getpixel((16, 16)) == pytest.approx(expected, abs=1)
    loaded = keyfile.loads(Path(f"{out}.arp").read_text())
    assert loaded["Film Negative"]["CineonLUTStage"] == stage


@pytest.mark.parametrize("method", ["density", "namicolor"])
def test_stage_has_no_effect_without_a_print_lut(tmp_path, scan, base, method):
    profile = density(base, method=method, cineon_lut="", cineon_lut_stage="before_grade")
    profile["Exposure"]["Compensation"] = "0.5"
    result, _ = render(tmp_path, scan, profile, "no-lut-before")
    assert result.returncode == 0, result.stdout + result.stderr
    changes = WorkingChanges(profile)
    changes.edit(parse_adjustments({"film_negative": {"cineon_lut_stage": "after_grade"}}), [])
    result, _ = render(tmp_path, scan, changes.profile, "no-lut-after")
    assert result.returncode == 0, result.stdout + result.stderr
    assert pixels(tmp_path / "no-lut-after.jpg") == pixels(tmp_path / "no-lut-before.jpg")


@pytest.mark.parametrize(
    "version, lut_present, explicit_stage, expected",
    [
        ("1053", True, None, "before_grade"),
        ("1055", True, None, "before_grade"),
        ("1055", False, None, "after_grade"),
        ("1056", True, None, "after_grade"),
        ("1055", True, "after_grade", "after_grade"),
        ("1056", True, "before_grade", "before_grade"),
    ],
)
def test_native_profile_stage_defaults_and_explicit_values(
    tmp_path, scan, base, version, lut_present, explicit_stage, expected
):
    profile = density(base)
    profile["Version"]["Version"] = version
    film = profile["Film Negative"]
    film.pop("CineonLUTStage", None)
    if not lut_present:
        film.pop("CineonLUT", None)
    else:
        film["CineonLUT"] = ""  # Migration depends on key presence, not activity.
    if explicit_stage is not None:
        film["CineonLUTStage"] = explicit_stage
    result, loaded = render(tmp_path, scan, profile, "native-stage")
    assert result.returncode == 0, result.stdout + result.stderr
    assert loaded["Film Negative"]["CineonLUTStage"] == expected


def test_an_old_active_print_lut_renders_like_explicit_before_grade(tmp_path, scan, base):
    cube = tmp_path / "constant.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "0.09 0.18 0.27\n" * 8)
    profile = density(
        base, cineon_lut=str(cube), cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_stage="before_grade", cineon_lut_input_transfer="linear",
    )
    profile["Exposure"]["Compensation"] = "1"
    result, _ = render(tmp_path, scan, profile, "explicit-before")
    assert result.returncode == 0, result.stdout + result.stderr
    profile["Version"]["Version"] = "1055"
    profile["Film Negative"].pop("CineonLUTStage")
    result, loaded = render(tmp_path, scan, profile, "old-order")
    assert result.returncode == 0, result.stdout + result.stderr
    assert loaded["Film Negative"]["CineonLUTStage"] == "before_grade"
    assert pixels(tmp_path / "old-order.jpg") == pixels(tmp_path / "explicit-before.jpg")


@pytest.mark.parametrize("version", ["1053", "1055"])
def test_an_old_raw_partial_omitting_lut_and_stage_preserves_after_grade(tmp_path, scan, base, version):
    cube = tmp_path / "constant.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "0.09 0.18 0.27\n" * 8)
    profile = density(
        base, cineon_lut=str(cube), cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_stage="after_grade", cineon_lut_input_transfer="linear",
    )
    profile["Exposure"]["Compensation"] = "1"
    result, _ = render(tmp_path, scan, profile, "partial-reference")
    assert result.returncode == 0, result.stdout + result.stderr
    source = tmp_path / "current.arp"
    source.write_text(keyfile.dumps(profile))
    partial = tmp_path / "old-partial.arp"
    partial.write_text(f"[Version]\nVersion={version}\n\n[Film Negative]\nCalibrationNote=layered note\n")
    out = tmp_path / "layered.jpg"
    result = run_cli([
        "-O", str(out), "-Y", "-a", "-p", str(source), "-p", str(partial), "-c", str(scan),
    ], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    loaded = keyfile.loads(Path(f"{out}.arp").read_text())
    assert loaded["Film Negative"]["CineonLUTStage"] == "after_grade"
    assert loaded["Film Negative"]["CalibrationNote"] == "layered note"
    assert pixels(out) == pixels(tmp_path / "partial-reference.jpg")


@pytest.mark.parametrize("stage", ["post_grade", "unknown"])
def test_unknown_native_print_lut_stage_rejects_the_profile(tmp_path, scan, base, stage):
    profile = density(base)
    profile["Film Negative"]["CineonLUTStage"] = stage
    result, _ = render(tmp_path, scan, profile, "invalid-stage")
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (tmp_path / "invalid-stage.jpg").exists()


def test_after_grade_identity_lut_preserves_colours_after_noop_local_contrast(tmp_path, scan, base):
    cube = tmp_path / "identity.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "".join(
        f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)
    ))
    profile = density(
        base, method="namicolor", namicolor_input_gain=0,
        cineon_reference_white=1,
        # Constant linear RGB (0, .18, 1), independently published Cineon codes.
        namicolor_shift=[0.0928641251 - 1, 0.4573196131 - 1, 0.6695992180 - 1],
        cineon_lut=str(cube), cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_stage="after_grade", cineon_lut_input_transfer="linear",
        cineon_lut_output_transfer="linear",
    )
    profile["Color Management"].update({"WorkingProfile": "sRGB", "OutputProfile": "(none)"})
    results = []
    for enabled in (False, True):
        # A disabled mask leaves pixels unchanged, but enabling the late tool
        # still runs its normal RGB -> LAB mode transition.
        profile["Local Contrast"].update({
            "Enabled": str(enabled).lower(), "Contrast": "0", "MaskEnabled": "false", "ShowMask": "-1",
        })
        path = tmp_path / f"local-contrast-{enabled}.arp"
        path.write_text(keyfile.dumps(profile))
        out = tmp_path / f"local-contrast-{enabled}.png"
        result = run_cli(["-O", str(out), "-n", "-b16", "-p", str(path), "-c", str(scan)], tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        with Image.open(out) as image:
            results.append(image.getpixel((16, 16)))
    assert results[0] == pytest.approx((0, 46, 255), abs=1)
    assert results[1] == pytest.approx(results[0], abs=1)


def test_typed_stage_opt_in_preserves_the_old_dormant_namicolor_mask_render(tmp_path, scan, base):
    cube = tmp_path / "identity.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "".join(
        f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)
    ))
    old = density(
        base, method="namicolor", namicolor_input_gain=0.2, namicolor_master_shift=-0.35,
        cineon_lut=str(cube), cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_input_transfer="linear",
    )
    old["Version"]["Version"] = "1054"
    old["Film Negative"].pop("CineonLUTStage", None)
    old["Film Negative"].update({
        "MatrixPreset": "custom", "Matrix": "1;0.4;0;0;1;0;0;0;1;",
        "MatrixBasis": "old inactive binding",
    })
    result, _ = render(tmp_path, scan, old, "dormant-before")
    assert result.returncode == 0, result.stdout + result.stderr
    changes = WorkingChanges(old)
    changes.edit(parse_adjustments({"film_negative": {"cineon_lut_stage": "after_grade"}}), [])
    result, loaded = render(tmp_path, scan, changes.profile, "dormant-after")
    assert result.returncode == 0, result.stdout + result.stderr
    assert loaded["Film Negative"]["CineonLUTStage"] == "after_grade"
    assert loaded["Film Negative"]["MatrixPreset"] == "identity"
    assert loaded["Film Negative"]["MatrixBasis"] == "old inactive binding"
    assert pixels(tmp_path / "dormant-after.jpg") == pixels(tmp_path / "dormant-before.jpg")


def test_typed_stage_opt_in_keeps_pre1054_input_lut_render_and_after_grade_ignores_legacy_route(tmp_path, scan, base):
    cube = tmp_path / "constant.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "0.18 0.09 0.03\n" * 8)
    old = density(
        base, color_space="input", cineon_lut=str(cube),
        cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
    )
    old["Version"]["Version"] = "1053"
    old["Film Negative"].pop("CineonLUTStage", None)
    old["Film Negative"].pop("LegacyInputLUT", None)
    result, _ = render(tmp_path, scan, old, "old-input-lut")
    assert result.returncode == 0, result.stdout + result.stderr
    changes = WorkingChanges(old)
    changes.edit(parse_adjustments({"film_negative": {"cineon_lut_stage": "before_grade"}}), [])
    result, loaded = render(tmp_path, scan, changes.profile, "explicit-input-lut")
    assert result.returncode == 0, result.stdout + result.stderr
    assert loaded["Film Negative"]["LegacyInputLUT"] == "true"
    assert pixels(tmp_path / "explicit-input-lut.jpg") == pixels(tmp_path / "old-input-lut.jpg")
    changes.edit(parse_adjustments({"film_negative": {"cineon_lut_stage": "after_grade"}}), [])
    result, _ = render(tmp_path, scan, changes.profile, "after-legacy-retained")
    assert result.returncode == 0, result.stdout + result.stderr
    changes.profile["Film Negative"]["LegacyInputLUT"] = "false"
    result, _ = render(tmp_path, scan, changes.profile, "after-legacy-cleared")
    assert result.returncode == 0, result.stdout + result.stderr
    assert pixels(tmp_path / "after-legacy-retained.jpg") == pixels(tmp_path / "after-legacy-cleared.jpg")


@pytest.mark.parametrize(
    ("version", "flag", "signed"),
    [(1056, None, False), (1057, None, True), (1056, "true", True), (1057, "false", False)],
)
def test_namicolor_float_handoff_keeps_signed_exposure_and_overwhite(
    tmp_path, base, version, flag, signed,
):
    scan = tmp_path / "odd-width.png"
    Image.new("RGB", (35, 7), (128, 128, 128)).save(scan)
    profile = density(
        base, method="namicolor", color_space="working", namicolor_input_gain=0,
        namicolor_shift=[-.98, -.5, -.05], cineon_reference_white=.9,
    )
    profile["Version"]["Version"] = str(version)
    profile["Film Negative"].pop("PreserveRange", None)
    if flag is not None:
        profile["Film Negative"]["PreserveRange"] = flag
    profile["Exposure"].update({"Enabled": "true", "Compensation": "1", "Black": "0"})
    profile["Color Management"].update({"WorkingProfile": "sRGB", "OutputProfile": "(none)"})
    arp = tmp_path / "signed.arp"
    arp.write_text(keyfile.dumps(profile))
    output = tmp_path / "signed.tif"
    result = run_cli(["-a", "-o", str(output), "-t", "-b32", "-p", str(arp), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = (-.00856008636639 if signed else 0, .46080839580096, 16.4299039838313)
    for pixel in tiff_rgb_samples(output):
        assert pixel == pytest.approx(expected, rel=2e-6, abs=1e-7)


@pytest.mark.parametrize("preserve", [False, True])
def test_namicolor_float_lut_output_keeps_out_of_gamut_working_rgb(tmp_path, scan, base, preserve):
    cube = tmp_path / "green-rec2020.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "0 1 0\n" * 8)
    profile = density(
        base, method="namicolor", namicolor_input_gain=0,
        cineon_reference_white=1,
        preserve_range=preserve, cineon_lut=str(cube),
        cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_input_transfer="linear", cineon_lut_output_transfer="linear",
        cineon_lut_input_primaries="sRGB", cineon_lut_output_primaries="Rec2020",
    )
    profile["Exposure"]["Enabled"] = "false"
    profile["Color Management"].update({"WorkingProfile": "sRGB", "OutputProfile": "(none)"})
    arp = tmp_path / "lut-range.arp"
    arp.write_text(keyfile.dumps(profile))
    output = tmp_path / "lut-range.tif"
    result = run_cli(["-a", "-o", str(output), "-t", "-b32", "-p", str(arp), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    # Published linear Rec.2020 -> Rec.709 green-primary coordinates.
    expected = (-.58764114, 1.1328999, -.1005789) if preserve else (0, 1.1328999, 0)
    for pixel in tiff_rgb_samples(output):
        assert pixel == pytest.approx(expected, abs=2e-4)


@pytest.mark.parametrize("codes", [[-.01, .5, .9], [.02, .5, 1.02]])
def test_namicolor_cineon_handoff_refuses_unrepresentable_codes(tmp_path, scan, base, codes):
    profile = density(
        base, method="namicolor", target_mode="cineon", namicolor_input_gain=0,
        namicolor_master_shift=-.01,
        namicolor_shift=[code - .99 for code in codes], preserve_range=True,
    )
    profile["Color Management"]["OutputProfile"] = "(none)"
    arp = tmp_path / "out-of-range.arp"
    arp.write_text(keyfile.dumps(profile))
    output = tmp_path / "out-of-range.tif"
    result = run_cli(["-a", "-o", str(output), "-t", "-b16", "-p", str(arp), "-c", str(scan)], tmp_path)
    assert result.returncode != 0
    assert not output.exists()
    profile["Film Negative"]["PreserveRange"] = "false"
    arp.write_text(keyfile.dumps(profile))
    result = run_cli(["-a", "-o", str(output), "-t", "-b16", "-p", str(arp), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = [max(0, min(65535, round(code * 65535))) for code in codes]
    for pixel in tiff_rgb_samples(output):
        assert pixel == pytest.approx(expected, abs=1)


def test_namicolor_cineon_handoff_keeps_quantized_range_endpoints(tmp_path, scan, base):
    profile = density(
        base, method="namicolor", target_mode="cineon", namicolor_input_gain=0,
        namicolor_shift=[-1, -.5, 0], preserve_range=True,
    )
    profile["Color Management"]["OutputProfile"] = "(none)"
    arp = tmp_path / "endpoints.arp"
    arp.write_text(keyfile.dumps(profile))
    output = tmp_path / "endpoints.tif"
    result = run_cli(["-a", "-o", str(output), "-t", "-b16", "-p", str(arp), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    for pixel in tiff_rgb_samples(output):
        assert pixel == pytest.approx([0, 32768, 65535], abs=1)


def _unit_white_profile(base, version=None, **fields):
    """NamiColor with input gain 0 and a shift that puts every channel on Cineon code 685,
    exported as unprinted linear float: the pixel value is the decode's reference white."""
    profile = density(
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


@pytest.mark.parametrize(
    ("version", "anchor", "code"),
    [(None, None, 95), (1058, "code95", 95), (1057, None, 93 / 1023 / (1 + 93 / 1023) * 1023), (1057, "code95", 95)],
)
def test_fit_base_sends_normalized_zero_to_code_95_and_old_sidecars_keep_the_legacy_lift(
    tmp_path, scan, base, version, anchor, code,
):
    """Normalized q = 0 (the film base) lands on Cineon code 95 exactly; the legacy map put it at
    about 85.25. The legacy map is kept for a sidecar below Version 1058 that says nothing."""
    profile = density(
        base, method="namicolor", color_space="working", target_mode="cineon",
        namicolor_input_gain=0, namicolor_shift=[-1, -1, -1], namicolor_fit_base=True,
    )
    profile["Color Management"]["OutputProfile"] = "(none)"
    if version is not None:
        profile["Version"]["Version"] = str(version)
        profile["Film Negative"].pop("NamiColorFitBaseAnchor", None)
    if anchor is not None:
        profile["Film Negative"]["NamiColorFitBaseAnchor"] = anchor
    arp = tmp_path / "anchor.arp"
    arp.write_text(keyfile.dumps(profile))
    output = tmp_path / "anchor.tif"
    result = run_cli(["-a", "-o", str(output), "-t", "-b16", "-p", str(arp), "-c", str(scan)], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    for pixel in tiff_rgb_samples(output):
        assert pixel == pytest.approx([round(code / 1023 * 65535)] * 3, abs=1)


def _cube_profile(tmp_path, base, header):
    cube = tmp_path / "header.cube"
    cube.write_text(header + "LUT_3D_SIZE 2\n" + "".join(
        f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)))
    profile = density(
        base, method="namicolor", cineon_lut=str(cube),
        cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_output_transfer="linear",
    )
    arp = tmp_path / "header.arp"
    arp.write_text(keyfile.dumps(profile))
    return arp


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


def test_cube_with_default_input_range_header_is_accepted(tmp_path, scan, base):
    plain, plain_out = _render_png(tmp_path, scan, _cube_profile(tmp_path, base, ""), "plain.png")
    assert plain.returncode == 0, plain.stdout + plain.stderr
    ranged, ranged_out = _render_png(
        tmp_path, scan, _cube_profile(tmp_path, base, "LUT_3D_INPUT_RANGE 0.0 1.0\n"), "ranged.png")
    assert ranged.returncode == 0, ranged.stdout + ranged.stderr
    assert _png_pixels(plain_out) == _png_pixels(ranged_out)


@pytest.mark.parametrize("header", [
    "LUT_3D_INPUT_RANGE 0.0 2.0\n",
    "LUT_3D_INPUT_RANGE -0.1 1.0\n",
])
def test_cube_with_another_input_range_is_honoured_not_ignored(tmp_path, scan, base, header):
    # ART applies the range the cube declares (Adobe/Resolve meaning), so the
    # render must differ from the one that ignores the header.
    plain, plain_out = _render_png(tmp_path, scan, _cube_profile(tmp_path, base, ""), "plain.png")
    assert plain.returncode == 0, plain.stdout + plain.stderr
    ranged, ranged_out = _render_png(tmp_path, scan, _cube_profile(tmp_path, base, header), "ranged.png")
    assert ranged.returncode == 0, ranged.stdout + ranged.stderr
    assert _png_pixels(plain_out) != _png_pixels(ranged_out)


def _refused(tmp_path, scan, arp, name):
    result, out = _render_png(tmp_path, scan, arp, name)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not out.exists()


@pytest.mark.parametrize("header", [
    "LUT_IN_VIDEO_RANGE\n",
    "LUT_OUT_VIDEO_RANGE\n",
    "DOMAIN_MAX 1.0 1.0\n",
    "# OUTPUT_TRANSFER: ARRI LogC3\n",
])
def test_cube_with_unsupported_header_is_refused(tmp_path, scan, base, header):
    _refused(tmp_path, scan, _cube_profile(tmp_path, base, header), "refused.png")


def _legacy_lut_arp(tmp_path, base, **stored):
    cube = tmp_path / "legacy.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "".join(
        f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)))
    profile = density(
        base, color_space="input", cineon_lut=str(cube),
        cineon_lut_sha256=hashlib.sha256(cube.read_bytes()).hexdigest(),
        cineon_lut_stage="before_grade",
    )
    profile["Film Negative"]["LegacyInputLUT"] = "true"
    profile["Film Negative"].update(stored)
    arp = tmp_path / "legacy.arp"
    arp.write_text(keyfile.dumps(profile))
    return arp


@pytest.mark.parametrize("key", ["CineonLUTInputPrimaries", "CineonLUTOutputPrimaries"])
def test_legacy_input_space_lut_with_primaries_is_refused(tmp_path, scan, base, key):
    plain, _ = _render_png(tmp_path, scan, _legacy_lut_arp(tmp_path, base), "plain.png")
    assert plain.returncode == 0, plain.stdout + plain.stderr
    refused, out = _render_png(tmp_path, scan, _legacy_lut_arp(tmp_path, base, **{key: "Rec2020"}), "refused.png")
    assert refused.returncode != 0 and not out.exists()
    assert "cannot use LUT primaries" in refused.stdout + refused.stderr


def test_legacy_input_space_primaries_without_a_lut_still_render(tmp_path, scan, base):
    arp = _legacy_lut_arp(tmp_path, base, CineonLUTInputPrimaries="Rec2020", CineonLUT="", CineonLUTSha256="")
    result, _ = _render_png(tmp_path, scan, arp, "nolut.png")
    assert result.returncode == 0, result.stdout + result.stderr


# -- Flare and DenoiseBeforeInversion (PPVERSION 1059) ---------------------------


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
    plain = density(base)
    plain["Film Negative"].pop("Flare", None)
    zero = density(base, flare=[0, 0, 0])
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
    want = _render_jpg_pixels(tmp_path, clean, density(base), "clean")
    got = _render_jpg_pixels(tmp_path, veiled, density(base, flare=[f, f, f]), "veiled")
    uncorrected = _render_jpg_pixels(tmp_path, veiled, density(base), "uncorrected")

    def worst(a, b):
        pairs = zip(a.getdata(), b.getdata(), strict=True)
        return max(abs(p - q) for pa, pb in pairs for p, q in zip(pa, pb, strict=True))

    assert worst(want, got) <= 4
    assert worst(want, uncorrected) > worst(want, got)


def test_denoise_before_inversion_matters_only_when_denoise_is_on(tmp_path, base):
    scan = _gradient_scan(tmp_path / "noisy.tif", noise=True)

    def render_case(denoise_on, before, tag):
        profile = density(base, denoise_before_inversion=before)
        profile.setdefault("Denoise", {})
        profile["Denoise"]["Enabled"] = "true" if denoise_on else "false"
        profile["Denoise"]["Luminance"] = "60"
        return _png_pixels_of(tmp_path, scan, profile, tag)

    assert render_case(True, True, "on_before") != render_case(True, False, "on_after")
    assert render_case(False, True, "off_before") == render_case(False, False, "off_after")
