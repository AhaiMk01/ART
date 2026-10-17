"""The skill's pooled roll fit script (skills/film-negative/scripts/pooled_fit.py)
on a synthetic roll with known slopes and offsets.

Neutral squares are generated from D_c = k_c * D_G + o_c (scan exposure s
folded in), sampled back to linear values, and fitted; the fold is checked
against the NamiColor equation of reference.md: a neutral decodes to the
same q in every channel.
"""

import importlib.util
import json
import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

SCRIPT = Path(__file__).parents[1] / "skills/film-negative/scripts/pooled_fit.py"
spec = importlib.util.spec_from_file_location("pooled_fit", SCRIPT)
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)

K = {0: 0.8, 2: 1.05}
DEN_G, S_G, GAIN = 1.0, -0.4, 0.5


def lin(D):
    return 65535 * 10 ** (-D)


def roll(tmp_path, offsets, light=None, extra=None, s=None, noise=0.0):
    rng = np.random.default_rng(0)
    frames = {}
    for f, (oR, oB) in offsets.items():
        sq = []
        for j, dg in enumerate((0.9, 1.3, 1.7)):
            D = np.array([K[0] * dg + oR, dg, K[2] * dg + oB]) + rng.normal(0, noise, 3)
            D -= math.log10((s or {}).get(f, 1.0))  # what the scan records
            sq.append(dict(material="white paint", object_id=f"obj{j}", basis="material",
                           avg=list(lin(D)), sd=[50.0, 50.0, 50.0], size=32))
        frames[f] = dict(light=(light or {}).get(f, "daylight"), s=(s or {}).get(f, 1.0), squares=sq)
    for f, fr in (extra or {}).items():
        frames[f] = fr
    p = tmp_path / "picks.json"
    p.write_text(json.dumps(dict(frames=frames)))
    return p


def run(tmp_path, picks, *args):
    out = tmp_path / "out.json"
    pf.main([str(picks), "--json", str(out), *args])
    return json.loads(out.read_text())


def test_recovers_slopes_and_offsets(tmp_path):
    offs = {f"{i:02d}": (-0.10 - 0.01 * i, 0.20 + 0.01 * i) for i in range(5)}
    r = run(tmp_path, roll(tmp_path, offs))
    assert r["slopes"]["R"]["k"] == pytest.approx(K[0], abs=1e-6)
    assert r["slopes"]["B"]["k"] == pytest.approx(K[2], abs=1e-6)
    assert r["checks"] == []
    assert r["frames"]["03"]["R"]["fit"] == pytest.approx(-0.13, abs=1e-6)


def test_capture_exposure_is_normalized(tmp_path):
    offs = {f"{i:02d}": (-0.1, 0.2) for i in range(4)}
    r = run(tmp_path, roll(tmp_path, offs, s={"00": 2.0, "01": 2.0}))
    for f in offs:
        assert r["frames"][f]["R"]["fit"] == pytest.approx(-0.1, abs=1e-6)


def test_frame_without_neutrals_takes_its_light_group_mean(tmp_path):
    offs = {"01": (-0.1, 0.2), "02": (-0.12, 0.22), "03": (-0.11, 0.21), "09": (-0.3, 0.5)}
    extra = {"04": dict(light="daylight", squares=[]), "10": dict(light="lamp", squares=[])}
    r = run(tmp_path, roll(tmp_path, offs, light={"09": "lamp"}, extra=extra))
    day = [r["frames"][f]["B"]["final"] for f in ("01", "02", "03")]
    assert min(day) - 1e-9 <= r["frames"]["04"]["B"]["final"] <= max(day) + 1e-9
    assert r["frames"]["04"]["B"]["lam"] == 0.0
    # a light no other frame shares keeps its own fitted offset
    assert r["frames"]["09"]["B"]["final"] == pytest.approx(0.5, abs=1e-6)
    assert r["frames"]["10"]["B"]["final"] == pytest.approx(0.5, abs=1e-6)


def test_deviation_from_the_rest_of_the_light(tmp_path):
    offs = {f"{i:02d}": (-0.1, 0.2) for i in range(5)}
    offs["05"] = (-0.1, 0.12)  # an off-white "white"
    r = run(tmp_path, roll(tmp_path, offs))
    assert r["frames"]["05"]["dev"][1] == pytest.approx(-0.08, abs=1e-6)
    assert r["frames"]["00"]["dev"][1] == pytest.approx(0.0, abs=1e-6)


def test_preset_slopes_fit_offsets_only(tmp_path):
    offs = {"01": (-0.1, 0.2), "02": (-0.12, 0.22)}
    r = run(tmp_path, roll(tmp_path, offs), "--slopes", "0.8,1.05")
    assert r["slopes"]["B"]["k"] == 1.05
    assert r["frames"]["02"]["B"]["fit"] == pytest.approx(0.22, abs=1e-6)


def test_prior_settles_an_unset_slope(tmp_path):
    # two frames only: the slope is not set; the prior pulls it, the data move it
    offs = {"01": (-0.1, 0.2), "02": (-0.12, 0.22)}
    out = tmp_path / "out.json"
    pf.main([str(roll(tmp_path, offs, noise=0.01)), "--prior", "0.9,1.2,0.05", "--json", str(out)])
    r = json.loads(out.read_text())
    assert r["checks"]
    for ch, k0 in (("R", 0.9), ("B", 1.2)):
        s = r["slopes"][ch]
        lo, hi = sorted((s["k"], k0))
        assert lo <= s["posterior"] <= hi


def test_single_frame_of_uncertain_rows_takes_the_prior(tmp_path):
    # one frame, one granite boulder tagged uncertain: no slope evidence; the
    # prior sets it and the offset comes from the boulder, flagged weak
    D = np.array([K[0] * 1.2 - 0.1, 1.2, K[2] * 1.2 + 0.2])
    sq = [dict(material="granite", object_id="rock", basis="uncertain",
               avg=list(lin(D)), sd=[50.0] * 3, size=32)]
    p = tmp_path / "picks.json"
    p.write_text(json.dumps(dict(frames={"01": dict(light="daylight", squares=sq)})))
    with pytest.raises(SystemExit):
        pf.main([str(p)])
    r = run(tmp_path, p, "--prior", "1,1,0.15")
    assert r["slopes"]["R"]["k"] == 1.0 and r["slopes"]["R"]["fixed"] == "prior"
    assert len(r["weak"]) == 2
    f = r["frames"]["01"]
    assert f["R"]["final"] == pytest.approx(D[0] - D[1], abs=1e-9)
    assert "weak: uncertain rows only" in f["notes"]


def test_fold_decodes_neutrals_to_equal_codes(tmp_path):
    offs = {f"{i:02d}": (-0.1 - 0.01 * i, 0.2 + 0.01 * i) for i in range(4)}
    s = {"00": 2.0}
    r = run(tmp_path, roll(tmp_path, offs, s=s), "--green", f"{DEN_G},{S_G}", "--input-gain", str(GAIN))
    for f in offs:
        nc = r["frames"][f]["namicolor"]
        final = (r["frames"][f]["R"]["final"], r["frames"][f]["B"]["final"])
        for dg in (0.8, 1.5):  # a neutral at this scene density, as the scan records it
            D = np.array([K[0] * dg + final[0], dg, K[2] * dg + final[1]]) - math.log10(s.get(f, 1.0))
            q = [(1 - GAIN * math.log10(16 * 10 ** (-D[c])) + nc["shift"][c]) / (1 - nc["gain"][c])
                 for c in range(3)]
            assert q[0] == pytest.approx(q[1], abs=1e-9)
            assert q[2] == pytest.approx(q[1], abs=1e-9)
