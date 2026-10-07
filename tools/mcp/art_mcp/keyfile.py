"""Reading and writing GLib KeyFile text, the format of .arp sidecars.

Values are kept as the raw strings stored in the file: escapes (``\\s``,
``\\n``, ...) and ``;``-separated lists are left untouched, so every group,
key and value round-trips unchanged (comments and blank lines are dropped).
Interpreting a value is the caller's job; ``escape`` and ``unescape`` convert a
single string value to and from the form GLib stores it in.
"""

KeyFile = dict[str, dict[str, str]]
"""Group name -> key -> raw value, in file order."""

_UNESCAPES = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}


def escape(text: str) -> str:
    """The stored form of a string value, as GLib writes it: a backslash, newline,
    tab or carriage return is escaped, and so is a leading space, which GLib would
    otherwise strip. ART refuses a whole profile for a backslash that starts no
    valid escape (``C:\\Users`` is read as ``\\U``)."""
    body = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    bare = body.lstrip(" ")
    return "\\s" * (len(body) - len(bare)) + bare


def unescape(stored: str) -> str:
    """The value a stored string stands for, ``escape`` undone. A backslash
    sequence GLib does not define is left as written."""
    out: list[str] = []
    i = 0
    while i < len(stored):
        char = stored[i]
        if char == "\\" and i + 1 < len(stored) and stored[i + 1] in _UNESCAPES:
            out.append(_UNESCAPES[stored[i + 1]])
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def loads(text: str) -> KeyFile:
    kf: KeyFile = {}
    group: dict[str, str] | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            group = kf.setdefault(stripped[1:-1], {})
            continue
        key, sep, value = line.partition("=")
        if not sep or group is None:
            raise ValueError(f"line {lineno}: not a group or key=value: {line!r}")
        group[key.strip()] = value.lstrip()
    return kf


def dumps(kf: KeyFile) -> str:
    out: list[str] = []
    for name, entries in kf.items():
        out.append(f"[{name}]")
        out.extend(f"{key}={value}" for key, value in entries.items())
        out.append("")
    return "\n".join(out)
