"""Stand-in for ART-cli in tests: mimics its file effects, not its pixels.

- ``-v`` prints a version line.
- Writes a small JPEG-ish file to the ``-o``/``-O`` output.
- With ``-O``, writes ``<output>.arp``: the last ``-p`` file's text, or a
  default-profile marker with ``-d``.
- A missing ``-c`` input exits 2 like the real one.
"""

import sys
from pathlib import Path

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

output = Path(value("-o") or value("-O"))
output.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
if "-O" in args:
    profiles = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
    text = Path(profiles[-1]).read_text() if profiles else "[Version]\nSource=default\n"
    Path(str(output) + ".arp").write_text(text)
