"""Stand-in for ART-cli in tests: mimics its file effects, not its pixels.

- ``-v`` prints a version line.
- Writes a small JPEG-ish file to the ``-o``/``-O`` output. Its bytes embed
  the text of every ``-p`` layer, standing in for "the pixels reflect the
  profile" so tests can see what was rendered.
- With ``-O``, writes ``<output>.arp``: the last ``-p`` file's text, or a
  small default profile with ``-d``.
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
output.write_bytes(b"\xff\xd8" + "\n".join(layers).encode() + b"\xff\xd9")
if "-O" in args:
    Path(str(output) + ".arp").write_text(layers[-1] if layers else DEFAULT_PROFILE)
