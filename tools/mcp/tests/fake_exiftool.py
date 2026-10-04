"""Stand-in for exiftool in tests: mimics ``exiftool -@ -`` fed
``-j -n -Tag... -- <file>`` as an argument file on stdin (one argument per line).

The tags it knows about for ``<file>`` are the JSON object in
``<file>.exif.json``; it prints only the requested ones that exist (like the
real one, a missing tag is simply absent). A missing file prints exiftool's
error and exits 1.
"""

import json
import sys
from pathlib import Path

assert sys.argv[1:] == ["-@", "-"], sys.argv
args = sys.stdin.buffer.read().decode("utf-8").split("\n")
image = Path(args[-1])
if not image.exists():
    print(f"Error: File not found - {image}")
    sys.exit(1)

known = json.loads(image.with_name(image.name + ".exif.json").read_text())
wanted = [a[1:].lower() for a in args[:-2] if a.startswith("-") and len(a) > 2 and a != "-charset"]
found = {k: v for k, v in known.items() if k.lower() in wanted}
print(json.dumps([{"SourceFile": str(image).replace("\\", "/"), **found}]))
