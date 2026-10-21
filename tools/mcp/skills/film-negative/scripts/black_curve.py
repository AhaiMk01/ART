# /// script
# requires-python = ">=3.10"
# ///
"""Hue-preserving black for NamiColor (reference.md, "Shadow black").

    uv run black_curve.py --ev EV [--w W]

NamiColor's Cineon decode subtracts c0 = W*b/(1-b) (b = 10^(-590/300)) from
every channel, so a small density error in a shadow becomes a large colour
ratio near black. This prints the two settings that move that black to
luminance only:

  exposure.black   negative: adds c0 back to every channel after the exposure
                   scale (ART: v * 2^EV - black * 2000), which is the pure
                   power law of the densities;
  tone_curve       curve1 in Luminance mode, which takes c0 off luminance and
                   scales R, G and B together, so black depth is unchanged and
                   the shadow keeps its hue.

Both depend on the exposure compensation EV and on W
(`cineon_reference_white`); rerun after changing either. Curve 1 must stay the
first curve: contrast 0, the look on curve2 (mode2). It assumes `[ToneCurve]
WhitePoint` 1: curve 1 clips channels above 1.0, so set exposure so that
highlights with detail stay below it."""
import argparse
import json


def enc(x):
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055


def dec(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ev", type=float, required=True, help="exposure.compensation of the frame")
    ap.add_argument("--w", type=float, default=0.9, help="cineon_reference_white (default 0.9)")
    a = ap.parse_args()

    b = 10 ** ((95 - 685) / 300)
    c = a.w * b / (1 - b) * 2 ** a.ev  # black after exposure, in curve units
    if not 0 < c < 0.5:
        raise SystemExit(f"black {c:.4f} of the curve range: check --ev and --w")
    # Curve points in sRGB-gamma-encoded values (as ART's tone curve takes them):
    # zero up to the black, dense just above it where the curve bends, sparse above.
    x0 = enc(c)
    xs = [0.0, x0]
    xs += [x0 + (min(3 * x0, 0.5) - x0) * (i + 1) / 14 for i in range(14)]
    xs += [xs[-1] + (1 - xs[-1]) * (i + 1) / 14 for i in range(14)]
    pts = [[round(x, 4), round(enc(max(dec(x) - c, 0.0)), 4)] for x in xs]

    black = -a.w * b / (1 - b) * 2 ** a.ev * 65535 / 2000
    print(json.dumps({
        "exposure": {"black": round(black, 4)},
        "tone_curve": {"contrast": 0, "mode": "Luminance",
                       "curve1": {"type": "catmull_rom", "points": pts}},
    }, indent=1))


if __name__ == "__main__":
    main()
