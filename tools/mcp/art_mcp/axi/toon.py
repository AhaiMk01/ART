"""A TOON encoder (Token-Oriented Object Notation, spec v4) for ``art-axi``'s
output: comma delimiter, two-space indent, encode only.

It covers what the CLI prints: objects, primitive arrays, tabular arrays of
flat objects and list items for everything else. It never writes the spec's
nested field groups or keyed tabular objects; the list and nested forms it
falls back to are valid TOON that every decoder reads.
"""

import math
import re
from typing import Any

_NUMERIC = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?$", re.IGNORECASE)
_BARE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_NEEDS_QUOTES = set(':"\\[]{},')


def encode(value: Any) -> str:
    """``value`` (JSON-shaped: dict, list, str, number, bool, None) as a TOON
    document, without a trailing newline."""
    lines: list[str] = []
    if isinstance(value, dict):
        _object(value, 0, lines)
    elif isinstance(value, list):
        _array(None, value, 0, lines)
    else:
        lines.append(_primitive(value))
    return "\n".join(lines)


def is_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _number(n: int | float) -> str:
    if isinstance(n, int):
        return str(n)
    if math.isnan(n) or math.isinf(n):
        return "null"
    if n == 0:
        return "0"
    if n.is_integer() and abs(n) < 1e21:
        return str(int(n))
    text = repr(n)
    if "e" not in text:
        return text
    if 1e-6 <= abs(n) < 1e21:
        # repr switches to exponents earlier than TOON's canonical range.
        mantissa, exponent = text.split("e")
        digits = mantissa.replace("-", "").replace(".", "")
        point = (mantissa.lstrip("-").find(".") if "." in mantissa else len(mantissa.lstrip("-"))) + int(exponent)
        sign = "-" if n < 0 else ""
        if point <= 0:
            return f"{sign}0.{'0' * -point}{digits}"
        return f"{sign}{digits[:point]}.{digits[point:]}".rstrip(".")
    mantissa, exponent = text.split("e")
    return f"{mantissa}e{int(exponent):+d}"


def _escape(text: str) -> str:
    out = []
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _string(text: str) -> str:
    if (
        text == ""
        or text != text.strip(" \t")
        or text in ("true", "false", "null")
        or _NUMERIC.match(text)
        or any(ch in _NEEDS_QUOTES or ord(ch) < 0x20 for ch in text)
        or text[0] in "-#"
    ):
        return _escape(text)
    return text


def _primitive(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _number(value)
    return _string(str(value))


def _key(key: str) -> str:
    return key if _BARE_KEY.match(key) else _escape(key)


def _tabular_fields(items: list[Any]) -> list[str] | None:
    """The header fields when ``items`` can be rows of one table: non-empty
    objects with the same keys, every value primitive."""
    if not items or not all(isinstance(item, dict) and item for item in items):
        return None
    fields = list(items[0])
    keys = set(fields)
    for item in items:
        if set(item) != keys or not all(is_primitive(v) for v in item.values()):
            return None
    return fields


def _object(obj: dict[str, Any], depth: int, lines: list[str]) -> None:
    for key, value in obj.items():
        _field(_key(str(key)), value, depth, lines)


def _field(key: str, value: Any, depth: int, lines: list[str]) -> None:
    pad = "  " * depth
    if isinstance(value, dict):
        lines.append(f"{pad}{key}:")
        _object(value, depth + 1, lines)
    elif isinstance(value, list):
        _array(key, value, depth, lines)
    else:
        lines.append(f"{pad}{key}: {_primitive(value)}")


def _array(key: str | None, items: list[Any], depth: int, lines: list[str], prefix: str = "") -> None:
    """``key[N]...`` for ``items`` at ``depth``; ``prefix`` is ``"- "`` when the
    header sits on a list item's hyphen line."""
    pad = "  " * depth
    name = key or ""
    if not items:
        lines.append(f"{pad}{prefix}{name}: []" if key else f"{pad}{prefix}[0]:" if prefix else f"{pad}[]")
        return
    head = f"{pad}{prefix}{name}[{len(items)}]"
    # A list item's first field opens its body two levels below the hyphen;
    # a bare array item (`- [N]:`) one level.
    body = depth + (2 if prefix and key is not None else 1)
    if all(is_primitive(item) for item in items):
        lines.append(f"{head}: {','.join(_primitive(item) for item in items)}")
        return
    fields = _tabular_fields(items)
    # A header without a key is a table only at the root.
    if fields is not None and (key is not None or not prefix):
        lines.append(f"{head}{{{','.join(_key(f) for f in fields)}}}:")
        for item in items:
            lines.append("  " * body + ",".join(_primitive(item[f]) for f in fields))
        return
    lines.append(f"{head}:")
    for item in items:
        _list_item(item, body, lines)


def _list_item(item: Any, depth: int, lines: list[str]) -> None:
    pad = "  " * depth
    if is_primitive(item):
        lines.append(f"{pad}- {_primitive(item)}")
    elif isinstance(item, list):
        _array(None, item, depth, lines, prefix="- ")
    elif not item:
        lines.append(f"{pad}-")
    else:
        entries = list(item.items())
        first_key, first_value = entries[0]
        key = _key(str(first_key))
        if isinstance(first_value, dict):
            lines.append(f"{pad}- {key}:")
            _object(first_value, depth + 2, lines)
        elif isinstance(first_value, list):
            _array(key, first_value, depth, lines, prefix="- ")
        else:
            lines.append(f"{pad}- {key}: {_primitive(first_value)}")
        for k, v in entries[1:]:
            _field(_key(str(k)), v, depth + 1, lines)
