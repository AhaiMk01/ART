"""Reading and writing GLib KeyFile text, the format of .arp sidecars.

Values are kept as the raw strings stored in the file: escapes (``\\s``,
``\\n``, ...) and ``;``-separated lists are left untouched, so every group,
key and value round-trips unchanged (comments and blank lines are dropped).
Interpreting a value is the caller's job.
"""

KeyFile = dict[str, dict[str, str]]
"""Group name -> key -> raw value, in file order."""


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
