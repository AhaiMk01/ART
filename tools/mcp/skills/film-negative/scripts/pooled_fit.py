# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.24"]
# ///
"""Pooled roll fit (NamiColor) of reference.md, "Pooled roll fit", steps 2-7.

    uv run pooled_fit.py picks.json [--flare R,G,B] [--slopes kR,kB]
                         [--prior kR,kB[,SD]] [--green DEN_G,S_G]
                         [--input-gain G] [--json out.json]

picks.json:
    {"frames": {"<frame>": {
        "light": "daylight",          # light group (scene light, never a capture setting)
        "s": 1.0,                     # capture multiplier vs the reference scan exposure
        "squares": [{"material": "white paint", "object_id": "van",
                     "basis": "material" | "uncertain" | "C",
                     "avg": [r, g, b], "sd": [r, g, b], "size": 32}, ...]}}}

avg/sd: sample_spots at stage "source", in the processing basis.
--flare: veiling offset in source units, subtracted before the log (NamiColor
Flare = value / 65535). --slopes: a preset for the same film and basis; only
offsets are fitted. --prior: when the slope is not set, weight the roll's own
slope (its frame-bootstrap spread) against this prior and refit the offsets
with the result. --green: green's den_G and shift s_G, to fold the result
into NamiColor gains and shifts (master and black terms 0, FitBase off).

Fits `material` rows only; `uncertain` rows are compared against the fit,
`C` rows only describe the light. Works on any number of frames, one
included: when no frame carries a slope, --prior (or --slopes) sets it and
only offsets are fitted; with no `material` row at all, the offsets come
from the `uncertain` rows. Both are reported as WEAK. The report says whether the slope is set,
how far each frame's offset lies from the rest of its light group (in mD;
what a large one means is a judgement, see "Neutral by material"), and the
D_G range the slope was checked over (outside it the line is extrapolated).
"""

import argparse
import json
import math
import sys

import numpy as np

SIG_MODEL = 0.008  # model floor, D
N_CAP = 64  # cap on independent pixels per square (texture is correlated)
C_HUBER = 1.345
SPAN = 0.3  # "two levels well apart" in D_G
SPAN_CURV = 0.5  # material span needed for the straight-axis check
TOL, TOL_SAME = 25.0, 15.0  # mD: different materials / one material, similar D_G
NAME = {0: "R", 1: "G", 2: "B"}


def load(path, flare):
    """One observation per object per frame and basis (step 2)."""
    frames = json.load(open(path, encoding="utf-8"))["frames"]
    groups, meta = {}, {}
    for f, fr in frames.items():
        s = float(fr.get("s", 1.0))
        meta[f] = dict(light=fr.get("light", "?"), s=s)
        for q in fr.get("squares", []):
            avg = [v - fl for v, fl in zip(q["avg"], flare, strict=True)]
            if min(avg) <= 0:
                continue
            n = min(int(q.get("size", 32)) ** 2, N_CAP)
            D = [-math.log10(v / 65535) + math.log10(s) for v in avg]
            sd = [q["sd"][c] / (avg[c] * math.log(10)) / math.sqrt(n) for c in range(3)]
            key = (q["basis"], f, q.get("object_id") or q.get("material", "?"))
            groups.setdefault(key, []).append((D, sd, q.get("material", "?")))
    rows = {"material": [], "uncertain": [], "C": []}
    for (basis, f, obj), qs in groups.items():
        rows.setdefault(basis, []).append(dict(
            frame=f, obj=obj, material=qs[0][2], n=len(qs),
            D=np.mean([q[0] for q in qs], axis=0),
            sd=np.min([q[1] for q in qs], axis=0)))
    return rows, meta


def var(r, c, k):
    return r["sd"][c] ** 2 + (k * r["sd"][1]) ** 2 + SIG_MODEL ** 2


def fit_channel(rows, c, k_fixed=None):
    """D_c = k * D_G + o_f, Huber-weighted (step 3)."""
    frames = sorted({r["frame"] for r in rows})
    by = {f: [i for i, r in enumerate(rows) if r["frame"] == f] for f in frames}
    multi = [f for f in frames if len(by[f]) >= 2]
    x = np.array([r["D"][1] for r in rows])
    y = np.array([r["D"][c] for r in rows])
    if k_fixed is not None:
        k = float(k_fixed)
    else:
        if not multi:
            raise ValueError("no frame has two material objects; give --slopes")
        pairs = [(y[j] - y[i]) / (x[j] - x[i]) for f in multi for a, i in enumerate(by[f])
                 for j in by[f][a + 1:] if abs(x[j] - x[i]) > 0.05]
        k = float(np.median(pairs)) if pairs else 1.0
    rw = np.ones(len(rows))
    scale = 1.0
    for _ in range(50):
        v = np.array([var(r, c, k) for r in rows])
        w = rw / v
        stats = {}
        num = den = 0.0
        for f in multi:
            idx = by[f]
            xm, ym = np.average(x[idx], weights=w[idx]), np.average(y[idx], weights=w[idx])
            stats[f] = (xm, ym, w[idx].sum())
            num += float(np.sum(w[idx] * (x[idx] - xm) * (y[idx] - ym)))
            den += float(np.sum(w[idx] * (x[idx] - xm) ** 2))
        k_new = k if k_fixed is not None else num / den
        z = {}
        for f in multi:
            xm, ym, ws = stats[f]
            for i in by[f]:
                wi = 1.0 / v[i]
                h = wi / ws + (0 if k_fixed is not None else wi * (x[i] - xm) ** 2 / den)
                r = (y[i] - ym) - k_new * (x[i] - xm)
                z[i] = r / math.sqrt(v[i] * (1 - min(h, 0.95)))
        if z:
            scale = 1.4826 * float(np.median(np.abs(list(z.values())))) or 1.0
            for i, zi in z.items():
                u = abs(zi) / (C_HUBER * scale)
                rw[i] = 1.0 if u <= 1 else 1.0 / u
        done = abs(k_new - k) < 1e-8
        k = k_new
        if done and k_fixed is None:
            break
    v = np.array([var(r, c, k) for r in rows])
    w = np.maximum(rw, 1e-6) / v
    offs, se = {}, {}
    for f in frames:
        idx = by[f]
        offs[f] = float(np.average(y[idx] - k * x[idx], weights=w[idx]))
        se[f] = scale * math.sqrt(1.0 / w[idx].sum())
    return dict(k=k, offs=offs, se=se, rw=rw, scale=scale)


def bootstrap(rows, c, n=300):
    frames = sorted({r["frame"] for r in rows})
    rng = np.random.default_rng(1)
    ks = []
    for _ in range(n):
        pts = [dict(r, frame=f"{f}#{j}") for j, f in enumerate(rng.choice(frames, len(frames)))
               for r in rows if r["frame"] == f]
        try:
            ks.append(fit_channel(pts, c)["k"])
        except (ValueError, ZeroDivisionError):
            pass
    return tuple(np.percentile(ks, [5, 95])) if ks else (float("nan"),) * 2


def curvature(rows, c, off):
    """Step 4: q of D_c = k D_G + q (D_G - 1.2)^2 + o_f, after subtracting `off`."""
    frames = sorted({r["frame"] for r in rows})
    multi = [f for f in frames if sum(r["frame"] == f for r in rows) >= 2]
    X, Y = [], []
    for r in rows:
        if r["frame"] not in multi:
            continue
        lin = 65535.0 * 10 ** (-r["D"]) - np.array(off)
        if lin.min() <= 1:
            return None
        D = -np.log10(lin / 65535.0)
        X.append([D[1], (D[1] - 1.2) ** 2] + [float(r["frame"] == g) for g in multi])
        Y.append(D[c])
    X, Y = np.array(X), np.array(Y)
    if len(Y) <= X.shape[1] + 1:
        return None
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    res = Y - X @ beta
    s2 = res @ res / (len(Y) - X.shape[1])
    return float(beta[0]), float(beta[1]), float(np.sqrt(s2 * np.linalg.pinv(X.T @ X)[1, 1]))


def straighten(rows, c):
    """Offset in channel c that brings q to zero, or None if no positive one does."""
    lo, hi = 0.0, 0.95 * min(65535.0 * 10 ** (-r["D"][c]) for r in rows)
    at = lambda v: curvature(rows, c, [v if i == c else 0 for i in range(3)])  # noqa: E731
    rl, rh = at(lo), at(hi)
    if not rl or not rh or np.sign(rl[1]) == np.sign(rh[1]):
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        rm = at(mid)
        if rm is None or np.sign(rm[1]) == np.sign(rl[1]):
            lo, rl = mid, rm or rl
        else:
            hi = mid
    return lo, at(lo)[0]


def shrink(fits, meta, frames_fit):
    """Step 6: offsets toward the light-group mean, tau pooled over R and B."""
    out = {}
    groups = {}
    for f, m in meta.items():
        groups.setdefault(m["light"], []).append(f)
    for light, fs in groups.items():
        fitted = [f for f in fs if f in frames_fit]
        if not fitted:
            for f in fs:
                out[f] = dict(light=light, note="no neutrals in this light group: offset unknown")
            continue
        tau2 = 1e-6
        if len(fitted) >= 2:
            t = [float(np.var([fits[c]["offs"][f] for f in fitted], ddof=1))
                 - float(np.mean([fits[c]["se"][f] ** 2 for f in fitted])) for c in (0, 2)]
            tau2 = max(float(np.mean(t)), 1e-6)
        mean = {}
        for c in (0, 2):
            wts = [1 / (tau2 + fits[c]["se"][f] ** 2) for f in fitted]
            mean[c] = float(np.average([fits[c]["offs"][f] for f in fitted], weights=wts))
        for f in fs:
            o = dict(light=light, tau=math.sqrt(tau2))
            if f not in fitted:
                o.update(note="no neutrals: light-group mean over the roll",
                         **{NAME[c]: dict(final=mean[c], lam=0.0) for c in (0, 2)})
            elif len(fitted) == 1:
                o.update(note="only frame under this light: keeps its fitted offset",
                         **{NAME[c]: dict(fit=fits[c]["offs"][f], final=fits[c]["offs"][f], lam=1.0,
                                          se=fits[c]["se"][f]) for c in (0, 2)})
            else:
                for c in (0, 2):
                    se2 = fits[c]["se"][f] ** 2
                    lam = tau2 / (tau2 + se2)
                    fit = fits[c]["offs"][f]
                    o[NAME[c]] = dict(fit=fit, final=mean[c] + lam * (fit - mean[c]), lam=lam,
                                      se=math.sqrt(se2))
            if f in fitted and len(fitted) >= 2:  # how far from the rest of its light, in D
                o["dev"] = [fits[c]["offs"][f] - float(np.median(
                    [fits[c]["offs"][g] for g in fitted if g != f])) for c in (0, 2)]
            out[f] = o
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("picks")
    ap.add_argument("--flare", default="0,0,0")
    ap.add_argument("--slopes", help="kR,kB preset: fit offsets only")
    ap.add_argument("--prior", help="kR,kB[,sd]: when the slope is not set, combine the roll's "
                    "slope with this prior (sd default 0.05) and refit the offsets")
    ap.add_argument("--green", help="den_G,s_G: fold into NamiColor gains and shifts")
    ap.add_argument("--input-gain", type=float, default=1.0)
    ap.add_argument("--json", help="write the full result here")
    a = ap.parse_args(argv)
    flare = [float(v) for v in a.flare.split(",")]
    rows, meta = load(a.picks, flare)
    mat, unc, cee = rows["material"], rows["uncertain"], rows["C"]
    preset = [float(v) for v in a.slopes.split(",")] if a.slopes else None
    prior = None
    if a.prior:
        pv = [float(v) for v in a.prior.split(",")]
        prior = ({0: pv[0], 2: pv[1]}, pv[2] if len(pv) > 2 else 0.05)
    result = dict(slopes={}, checks=[], frames={}, uncertain=[], C=[], weak=[])
    P = print
    n_mat, n_unc = len(mat), len(unc)
    if not mat:
        # one frame or a roll without material neutrals: offsets from the
        # uncertain rows at a slope that is not the roll's own, all weak
        if not (preset or prior) or not unc:
            sys.exit("no material rows: give --slopes or --prior to fit offsets from the uncertain rows")
        mat, unc = unc, []
        result["weak"].append("offsets from uncertain rows only")
    fixed = "preset" if preset else None
    try:
        fits = {c: fit_channel(mat, c, preset[0 if c == 0 else 1] if preset else None) for c in (0, 2)}
    except (ValueError, ZeroDivisionError):
        if not prior:
            sys.exit("no frame has two material objects to carry a slope: give --slopes or --prior")
        preset, fixed = [prior[0][0], prior[0][2]], "prior"
        fits = {c: fit_channel(mat, c, preset[0 if c == 0 else 1]) for c in (0, 2)}
        result["weak"].append("slope is the prior's: no evidence in the picks")

    P(f"material objects {n_mat} in {len({r['frame'] for r in rows['material']})} frames; "
      f"uncertain {n_unc}; C {len(cee)}")
    for w in result["weak"]:
        P(f"WEAK: {w}")
    half = {}
    for c in (0, 2):
        f = fits[c]
        lo, hi = (f["k"], f["k"]) if preset else bootstrap(mat, c)
        half[c] = (hi - lo) / 2
        result["slopes"][NAME[c]] = dict(k=f["k"], boot90=[lo, hi], scale=f["scale"], fixed=fixed)
        P(f"k_{NAME[c]} {f['k']:.3f}" + (f"  ({fixed})" if preset else
          f"  frame-bootstrap 90% {lo:.3f}-{hi:.3f}") + f"; robust scale {f['scale']:.2f}")

    # step 5: is the slope set?
    reasons = []
    carry = []
    for fr in sorted({r["frame"] for r in mat}):
        dg = [r["D"][1] for r in mat if r["frame"] == fr]
        if max(dg) - min(dg) >= SPAN:
            carry.append(fr)
    dg_all = [r["D"][1] for r in mat if r["frame"] in carry]
    checked = (min(dg_all), max(dg_all)) if dg_all else None
    result["checked_D_G"] = checked
    if not preset:
        if len(carry) < 3:
            reasons.append(f"only {len(carry)} frame(s) with material at two levels {SPAN} D_G apart")
        for c in (0, 2):
            k = fits[c]["k"]
            tol = max(half[c], 0.02)
            movers = []
            for fr in sorted({r["frame"] for r in mat}):
                try:
                    kf = fit_channel([r for r in mat if r["frame"] != fr], c)["k"]
                except (ValueError, ZeroDivisionError):
                    continue
                if abs(kf - k) > tol:
                    movers.append(f"{fr} ({kf:.3f})")
            if movers:
                reasons.append(f"k_{NAME[c]} {k:.3f} moves without " + ", ".join(movers))
            side = {"low": set(), "high": set()}
            for u in unc:
                far = [m for m in mat if m["frame"] == u["frame"] and abs(m["D"][1] - u["D"][1]) >= SPAN]
                if not far:
                    continue
                m = max(far, key=lambda m: abs(m["D"][1] - u["D"][1]))
                gap = u["D"][1] - m["D"][1]
                miss = 1000 * ((u["D"][c] - m["D"][c]) - k * gap)
                if abs(miss) > TOL:
                    side["low" if miss / gap < 0 else "high"].add(u["frame"])
            for s, o in (("low", "high"), ("high", "low")):
                if len(side[s]) >= 3 and not side[o]:
                    reasons.append(f"uncertain rows in {len(side[s])} frames imply k_{NAME[c]} "
                                   f"{s}er ({', '.join(sorted(side[s]))})")
        P("slope " + ("NOT SET: " + "; ".join(reasons) + ". Take it from a preset (--slopes) "
                      "and fit offsets only, or give --prior." if reasons else "SET"))
    result["checks"] = reasons
    if prior and not preset:
        k0, sd0 = prior
        for c in (0, 2):
            lo, hi = result["slopes"][NAME[c]]["boot90"]
            se = max((hi - lo) / 2 / 1.645, 1e-4) if math.isfinite(hi - lo) else float("inf")
            kd = fits[c]["k"]
            kp = (kd / se ** 2 + k0[c] / sd0 ** 2) / (1 / se ** 2 + 1 / sd0 ** 2)
            result["slopes"][NAME[c]].update(prior=k0[c], prior_sd=sd0, data_se=se, posterior=kp)
            if reasons:
                fits[c] = fit_channel(mat, c, kp)
                P(f"k_{NAME[c]} {kp:.3f} from the prior {k0[c]:.3f} (sd {sd0:.3f}) and the roll's "
                  f"{kd:.3f} (sd {se:.3f}); offsets refitted with it")
            else:
                P(f"k_{NAME[c]} kept from the roll; the prior {k0[c]:.3f} is "
                  f"{abs(kd - k0[c]) / math.hypot(se, sd0):.1f} sd away")
    if checked:
        P(f"slope checked over D_G {checked[0]:.2f}-{checked[1]:.2f} "
          f"(frames {', '.join(carry)}); outside it the line is extrapolated")

    # step 4: straight axis
    span = max(r["D"][1] for r in mat) - min(r["D"][1] for r in mat)
    result["curvature"] = {}
    for c in (0, 2):
        r0 = curvature(mat, c, [0, 0, 0]) if span >= SPAN_CURV else None
        if r0 is None:
            P(f"axis {NAME[c]}: not tested (span {span:.2f} D_G, needs {SPAN_CURV} and two rows in a frame)")
            continue
        _, q, se = r0
        entry = dict(q=q, se=se, bent=abs(q) > 2.5 * se)
        line = f"axis {NAME[c]}: q {q:+.3f} +- {se:.3f}" + ("  BENT" if entry["bent"] else "  straight")
        if entry["bent"]:
            s = straighten(mat, c)
            if s:
                entry["offset"] = s[0]
                line += (f"; offset {s[0]:.0f} (Flare {s[0] / 65535:.4f}) straightens it, "
                         f"k then {s[1]:.3f}: refit with --flare")
            else:
                line += "; no positive offset straightens it (not a scan offset): report it"
        result["curvature"][NAME[c]] = entry
        P(line)

    # step 6: shrinkage
    sh = shrink(fits, meta, set(fits[0]["offs"]))
    P("\nframe | light | offset R, B fit -> final (mD) | vs median of the rest of its light R, B (mD)"
      " | lam R, B | note")
    for fr in sorted(meta):
        o = sh[fr]
        notes = [o.get("note", "")]
        if fr in fits[0]["offs"]:
            objs = [r for r in mat if r["frame"] == fr]
            if len(objs) == 1:
                notes.append("weak: one object sets its offset")
            if not n_mat:
                notes.append("weak: uncertain rows only")
            elif checked and min(r["D"][1] for r in objs) > checked[1]:
                notes.append("weak: neutrals only above the checked D_G range")
        dev = " ".join(f"{1000 * v:+4.0f}" for v in o["dev"]) if "dev" in o else "   -    -"
        if "R" in o:
            fit_s = " ".join(f"{1000 * o[ch]['fit']:+.0f}" if "fit" in o[ch] else "   -" for ch in "RB")
            P(f"{fr} | {o['light']} | {fit_s} -> {1000 * o['R']['final']:+.0f} {1000 * o['B']['final']:+.0f}"
              f" | {dev} | {o['R']['lam']:.2f} {o['B']['lam']:.2f} | " + "; ".join(n for n in notes if n))
        else:
            P(f"{fr} | {o['light']} | - | - | - | " + "; ".join(n for n in notes if n))
        result["frames"][fr] = dict(o, s=meta[fr]["s"], notes=[n for n in notes if n])

    def resid(r, c):
        return 1000 * (r["D"][c] - fits[c]["k"] * r["D"][1] - fits[c]["offs"][r["frame"]])

    P("\nmaterial rows: frame | object | D_G | resid R, B (mD) | robust weight R, B")
    for i, r in sorted(enumerate(mat), key=lambda t: (t[1]["frame"], t[1]["D"][1])):
        w = [fits[c]["rw"][i] for c in (0, 2)]
        P(f"  {r['frame']} | {r['obj'][:36]:<36} | {r['D'][1]:.2f} | {resid(r, 0):+5.0f} {resid(r, 2):+5.0f}"
          f" | {w[0]:.2f} {w[1]:.2f}" + ("  <- low weight" if min(w) < 0.3 else ""))

    P("\nuncertain rows vs the closest material row of the frame (fit-free):")
    for u in sorted(unc, key=lambda r: (r["frame"], r["D"][1])):
        same = [m for m in mat if m["frame"] == u["frame"]]
        if not same:
            P(f"  {u['frame']} | {u['obj'][:36]} | {u['D'][1]:.2f} | no material row in the frame")
            result["uncertain"].append(dict(frame=u["frame"], obj=u["obj"], verdict="no material row"))
            continue
        m = min(same, key=lambda m: abs(m["D"][1] - u["D"][1]))
        gap = abs(m["D"][1] - u["D"][1])
        diff = [1000 * ((u["D"][c] - fits[c]["k"] * u["D"][1]) - (m["D"][c] - fits[c]["k"] * m["D"][1]))
                for c in (0, 2)]
        err = [1000 * half[c] * gap for c in (0, 2)]
        tol = TOL_SAME if u["material"] == m["material"] else TOL
        if max(err) > tol / 3:
            verdict = "not comparable (gap too large for this slope)"
        elif max(abs(d) for d in diff) <= tol:
            verdict = f"agrees within {tol:.0f} (supports; does not clear the doubt alone)"
        else:
            verdict = "disagrees"
        P(f"  {u['frame']} | {u['obj'][:36]} | {u['D'][1]:.2f} vs {m['obj'][:24]} | gap {gap:.2f} | "
          f"{diff[0]:+4.0f} {diff[1]:+4.0f} mD | {verdict}")
        result["uncertain"].append(dict(frame=u["frame"], obj=u["obj"], vs=m["obj"], gap=gap,
                                        diff=diff, verdict=verdict))

    if cee:
        P("\nC rows (light only, never fitted): residual from the frame's line, mD "
          "(+B = more blue-record density = bluer light)")
        for r in sorted(cee, key=lambda r: (r["frame"], r["D"][1])):
            if r["frame"] in fits[0]["offs"]:
                P(f"  {r['frame']} | {r['obj'][:36]} | {r['D'][1]:.2f} | {resid(r, 0):+5.0f} {resid(r, 2):+5.0f}")
                result["C"].append(dict(frame=r["frame"], obj=r["obj"], resid=[resid(r, 0), resid(r, 2)]))

    # step 7: fold into NamiColor
    if a.green:
        den_g, s_g = (float(v) for v in a.green.split(","))
        g = a.input_gain
        base = 1 - g * math.log10(16)
        P(f"\nNamiColor (input gain {g}, master/black 0, FitBase off; Flare "
          + ";".join(f"{v / 65535:.4f}" for v in flare) + "):")
        for fr in sorted(meta):
            o = sh[fr]
            if "R" not in o:
                continue
            comp = g * math.log10(meta[fr]["s"])  # capture compensation, once, on the processing input
            k = {0: fits[0]["k"], 1: 1.0, 2: fits[2]["k"]}
            off = {0: o["R"]["final"], 1: 0.0, 2: o["B"]["final"]}
            gain = [1 - k[c] * den_g for c in range(3)]
            shift = [k[c] * (base + s_g) - base - g * off[c] + comp for c in range(3)]
            result["frames"][fr]["namicolor"] = dict(gain=gain, shift=shift)
            P(f"  {fr}: NamiColorGain=" + ";".join(f"{v:.5f}" for v in gain)
              + "  NamiColorShift=" + ";".join(f"{v:.5f}" for v in shift))

    if a.json:
        json.dump(result, open(a.json, "w", encoding="utf-8"), indent=1, default=float)


if __name__ == "__main__":
    main()
