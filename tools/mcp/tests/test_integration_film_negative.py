"""A Film Negative profile written by art_mcp, read by a real ART-cli.

The unit tests hand art_mcp's own output to art_mcp; none of them proved ART can
load it. ART once read the 3-value `RGBGains` and `ChannelGamma` lists as curves
and refused every profile it was handed, which no test noticed. Skipped unless
`ART_DIR` names an ART build with the density method (the installed ART may
predate it) and, on Windows, its runtime DLLs are on PATH.
"""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from art_mcp import artdir, keyfile
from art_mcp.profile import WorkingChanges
from art_mcp.schema import parse_adjustments

CLI = None
if os.environ.get("ART_DIR"):
    found = artdir.find_art_dir(None, os.environ, None)
    CLI = artdir.find_cli(found) if found else None

pytestmark = pytest.mark.skipif(CLI is None, reason="ART_DIR does not name an ART build")

BASIS = '{"v":1,"color_space":"working","profile":"Rec2020","input_gamma":"1","source":"Unknown"}'


def run_cli(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(CLI), *args], capture_output=True, text=True, timeout=120, cwd=tmp_path, check=False
    )


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
    changes = WorkingChanges(base)
    changes.edit(parse_adjustments({"film_negative": {"enabled": True, "method": "density", **fields}}), [])
    return changes.profile


def pixels(path: Path) -> bytes:
    """The decoded image: the files differ in metadata such as the time."""
    with Image.open(path) as jpeg:
        return jpeg.convert("RGB").tobytes()


def numbers(text: str) -> list[float]:
    return [float(part) for part in text.split(";") if part]


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
