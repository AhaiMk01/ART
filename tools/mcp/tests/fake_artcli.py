"""Stand-in for ART-cli in tests: mimics its file effects, not its pixels.

- ``-v`` prints a version line.
- Writes a small JPEG-ish file (TIFF/PNG magic with ``-t``/``-n``) to the
  ``-o``/``-O`` output. Its bytes embed
  the text of every ``-p`` layer, standing in for "the pixels reflect the
  profile" so tests can see what was rendered.
- With ``-O``, writes ``<output>.arp``: the last ``-p`` file's text, or a
  small default profile with ``-d``.
- Every output also embeds the command line (``args: ...``), so tests can see
  which flags were used.
- A ``.png`` output is a bare PNG header whose size is the fake image
  (6000x4000, ``FAKE_SIZE``) clamped to the last ``[Crop]`` layer's W/H, as
  ART clamps a crop to the frame; this is what a frame probe reads.
- A missing ``-c`` input exits 2 like the real one.
"""

import sys
from pathlib import Path

DEFAULT_PROFILE = """[Version]
AppVersion=9.9.9
Version=1045

[Exposure]
Enabled=true
Compensation=0
Black=0

[White Balance]
Enabled=true
Setting=Camera

[Crop]
Enabled=false
X=-1
Y=-1
W=-1
H=-1

[LensProfile]
LcMode=none
UseDistortion=true
UseVignette=true
UseCA=false
"""

args = sys.argv[1:]
if args == ["-v"]:
    print("ART, version 9.9.9, command line.")
    sys.exit(0)


def value(flag):
    return args[args.index(flag) + 1] if flag in args else None


image = Path(args[args.index("-c") + 1])
if not image.exists():
    print(f'"{image}" doesn\'t exist!', file=sys.stderr)
    sys.exit(2)

layers = [Path(args[i + 1]).read_text() for i, a in enumerate(args) if a == "-p"]
output = Path(value("-o") or value("-O"))
FAKE_SIZE = (6000, 4000)


def png_header():
    crop = {}
    for layer in layers:
        in_crop = False
        for line in layer.splitlines():
            if line.startswith("["):
                in_crop = line == "[Crop]"
            elif in_crop and "=" in line:
                k, _, v = line.partition("=")
                crop[k] = int(v) if v.lstrip("-").isdigit() else v
    if crop.get("Enabled") != "true" or crop.get("W", 0) <= 0 or crop.get("H", 0) <= 0:
        crop = {}  # like ART: a disabled or empty crop is no crop
    w = min(FAKE_SIZE[0], crop.get("W", FAKE_SIZE[0]))
    h = min(FAKE_SIZE[1], crop.get("H", FAKE_SIZE[1]))
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big")
    )


if output.suffix == ".png":
    output.write_bytes(png_header())
else:
    magic = b"II*\x00" if "-t" in args else b"\x89PNG\r\n\x1a\n" if "-n" in args else b"\xff\xd8"
    output.write_bytes(
        magic + "\n".join(layers).encode() + b"\nargs: " + " ".join(args).encode() + b"\xff\xd9"
    )
if "-O" in args:
    Path(str(output) + ".arp").write_text(layers[-1] if layers else DEFAULT_PROFILE)
