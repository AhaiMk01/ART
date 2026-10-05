"""Stand-in for ART-cli in tests: mimics its file effects, not its pixels.

- ``-v`` prints a version line.
- Writes a small JPEG-ish file (TIFF/PNG magic with ``-t``/``-n``) to the
  ``-o``/``-O`` output. Its bytes embed
  the text of every ``-p`` layer, standing in for "the pixels reflect the
  profile" so tests can see what was rendered.
- With ``-O``, writes ``<output>.arp``: the last ``-p`` file's text, or a
  small default profile with ``-d``, or with both that profile with every
  ``-p`` file laid over it key by key; several ``-p`` files without ``-d``
  are laid over one another in order, the first one over nothing.
- Every output also embeds the command line (``args: ...``), so tests can see
  which flags were used.
- A ``.png`` output is a bare PNG header whose size is the fake image
  (6000x4000, ``FAKE_SIZE``) clamped to the last ``[Crop]`` layer's W/H, as
  ART clamps a crop to the frame; this is what a frame probe reads.
- A missing ``-c`` input exits 2 like the real one.
- ``-x size,space,x1,y1,...`` (spot sampling, no output file) prints one
  ``ART-SPOTS`` line: spot i has avg ``[x, y, size]`` and max
  ``[x + 1, y + 1, size + 1]``, on the fake 6000x4000 frame. With
  ``FAKE_SPOTS=release`` it acts like a release art-cli (help, exit -1);
  with ``FAKE_SPOTS=silent`` it exits 0 printing nothing.
- With ``FAKE_PNG_SOURCE`` set, an 8-bit PNG output (``-n -b8``) is a copy of
  that file, so a test chooses the pixels ``image_stats`` sees. With
  ``FAKE_PNG_DIR`` set to a folder, the copy is of ``<image stem>.png`` in it
  when that exists (so each image has its own pixels, whatever the
  ``FAKE_PNG_SOURCE``); an image with neither gets a bare PNG header, which
  does not decode.
- With ``FAKE_ARGS_LOG`` set, the command line is appended there as a JSON line.
- With ``FAKE_DEFAULT_PROFILE`` set, ``-d`` stands for that file's text instead
  of the small default profile.
- With ``FAKE_REAL_JPEG`` set, a JPEG output is a decodable image: the fake
  6000x4000 frame, clamped to the last ``[Crop]`` layer's W/H like a PNG's size,
  fitted into the last ``[Resize]`` layer's Width x Height (60x40 without one),
  in a flat colour taken from a hash of the layers, so a different profile
  gives different pixels.
"""

import hashlib
import json
import os
import shutil
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


if os.environ.get("FAKE_ARGS_LOG"):
    with open(os.environ["FAKE_ARGS_LOG"], "a") as log:
        log.write(json.dumps(args) + "\n")


def value(flag):
    return args[args.index(flag) + 1] if flag in args else None


image = Path(args[args.index("-c") + 1])
if not image.exists():
    print(f'"{image}" doesn\'t exist!', file=sys.stderr)
    sys.exit(2)

if "-x" in args:
    mode = os.environ.get("FAKE_SPOTS")
    if mode == "release":
        print("ART, version 9.9.9, command line.\nSymbols:\nUsage:\n  ART-cli -c <dir>|<files>", file=sys.stderr)
        sys.exit(-1)
    if mode != "silent":
        size, _space, *coords = args[args.index("-x") + 1].split(",")
        spots = [
            {
                "x": int(x), "y": int(y),
                "avg": [int(x), int(y), int(size)],
                "max": [int(x) + 1, int(y) + 1, int(size) + 1],
            }
            for x, y in zip(coords[::2], coords[1::2], strict=True)
        ]
        print("some banner line")
        print("ART-SPOTS " + json.dumps({"width": 6000, "height": 4000, "spots": spots}))
    sys.exit(0)

layers = [Path(args[i + 1]).read_text() for i, a in enumerate(args) if a == "-p"]
output = Path(value("-o") or value("-O"))
FAKE_SIZE = (6000, 4000)


def shown_size():
    """The fake frame's size clamped to the crop the layers leave."""
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
    return min(FAKE_SIZE[0], crop.get("W", FAKE_SIZE[0])), min(FAKE_SIZE[1], crop.get("H", FAKE_SIZE[1]))


def png_header():
    w, h = shown_size()
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big")
    )


def real_jpeg():
    from PIL import Image

    resize = {}
    for layer in layers:
        in_resize = False
        for line in layer.splitlines():
            if line.startswith("["):
                in_resize = line == "[Resize]"
            elif in_resize and "=" in line:
                k, _, v = line.partition("=")
                resize[k] = v
    if resize.get("Enabled") == "true":
        shown = shown_size()
        scale = min(int(resize["Width"]) / shown[0], int(resize["Height"]) / shown[1])
        size = (max(1, round(shown[0] * scale)), max(1, round(shown[1] * scale)))
    else:
        size = (60, 40)
    colour = tuple(hashlib.md5("\n".join(layers).encode()).digest()[:3])
    Image.new("RGB", size, colour).save(output, "JPEG", quality=95)


def png_source():
    """The file an 8-bit PNG output copies (FAKE_PNG_DIR's file of this image, else FAKE_PNG_SOURCE)."""
    own = Path(os.environ.get("FAKE_PNG_DIR", "")) / (image.stem + ".png")
    return str(own) if os.environ.get("FAKE_PNG_DIR") and own.is_file() else os.environ.get("FAKE_PNG_SOURCE")


if output.suffix == ".png" and "-b8" in args and png_source():
    shutil.copyfile(png_source(), output)
elif os.environ.get("FAKE_REAL_JPEG") and output.suffix == ".jpg" and "-t" not in args and "-n" not in args:
    real_jpeg()
elif output.suffix == ".png":
    output.write_bytes(png_header())
else:
    magic = b"II*\x00" if "-t" in args else b"\x89PNG\r\n\x1a\n" if "-n" in args else b"\xff\xd8"
    output.write_bytes(
        magic + "\n".join(layers).encode() + b"\nargs: " + " ".join(args).encode() + b"\xff\xd9"
    )


def layered(base, over):
    """``over``'s keys set in ``base`` (both KeyFile text)."""
    groups = {}
    for text in (base, over):
        group = None
        for line in text.splitlines():
            if line.startswith("["):
                group = groups.setdefault(line[1:-1], {})
            elif "=" in line and group is not None:
                key, _, val = line.partition("=")
                group[key] = val
    lines = []
    for name, keys in groups.items():
        lines += [f"[{name}]", *(f"{key}={val}" for key, val in keys.items()), ""]
    return "\n".join(lines)


if "-O" in args:
    default_file = os.environ.get("FAKE_DEFAULT_PROFILE")
    default = Path(default_file).read_text() if default_file else DEFAULT_PROFILE
    arp = layers[-1] if layers else default
    if layers and ("-d" in args or len(layers) > 1):
        arp = default if "-d" in args else ""
        for layer in layers:
            arp = layered(arp, layer)
    Path(str(output) + ".arp").write_text(arp)
