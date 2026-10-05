"""Stand-in for exiftool in tests: mimics ``exiftool -@ -`` fed
``-j -n -Tag... -- <file>...`` as an argument file on stdin (one argument per line).

The tags it knows about for ``<file>`` are the JSON object in
``<file>.exif.json``; it prints only the requested ones that exist (like the
real one, a missing tag is simply absent), one record per file in an array.
Like the real one, a file it cannot read gets ``Error: ... - <file>`` on
stderr, and the exit status is 1 once any file failed, the other files'
records still printed: a missing file or a file without ``.exif.json`` has no
record; a ``.exif.json`` holding ``"__error__": "<text>"`` has a record with
only ``SourceFile`` and ``Error: <text> - <file>`` (an empty file).

With ``FAKE_EXIFTOOL_LOG`` set, every run appends one line to that file: the
files it was asked for, as JSON.
"""

import json
import os
import sys
from pathlib import Path

assert sys.argv[1:] == ["-@", "-"], sys.argv
args = sys.stdin.buffer.read().decode("utf-8").split("\n")
split = args.index("--")
files = [Path(a) for a in args[split + 1 :]]
if os.environ.get("FAKE_EXIFTOOL_LOG"):
    with open(os.environ["FAKE_EXIFTOOL_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps([str(f) for f in files]) + "\n")
wanted = [a[1:].lower() for a in args[:split] if a.startswith("-") and len(a) > 2 and a != "-charset"]

records = []
failed = False
for image in files:
    shown = str(image).replace("\\", "/")
    exif = image.with_name(image.name + ".exif.json")
    if not image.exists():
        print(f"Error: File not found - {shown}", file=sys.stderr)
        failed = True
    elif not exif.exists():
        print(f"Error: File format error - {shown}", file=sys.stderr)
        failed = True
    else:
        known = json.loads(exif.read_text())
        if "__error__" in known:
            print(f"Error: {known['__error__']} - {shown}", file=sys.stderr)
            failed = True
            records.append({"SourceFile": shown})
        else:
            records.append({"SourceFile": shown, **{k: v for k, v in known.items() if k.lower() in wanted}})
if records:
    print(json.dumps(records))
sys.exit(1 if failed else 0)
