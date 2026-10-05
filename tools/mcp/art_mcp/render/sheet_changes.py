"""What changed between two passes of a contact sheet: the differing profile
values, with numbers shown with at most seven significant digits, and the
changes of many frames grouped by identical change.

Pure: no ART, no files. ``sheet_ops`` records the per-frame changes in a pass's
JSON and returns the grouped summary.

ART keeps many numbers as 32-bit floats and writes them back as doubles with 17
significant digits: the ``6450.7`` an agent typed comes back as
``6450.7001953125``, ``1.37`` as ``1.3700000047683716``. That says nothing more
than ``6450.7`` or ``1.37`` and costs context, and it is not a change. So a value
that is a number, or a ``;``-separated list of tokens (a curve, ``r;g;b;``) some
of which are, is shown with each decimal token as ``%.7g`` (a float32 has about
seven digits); an integer and any other text stay as written. Two numbers whose
difference is below one millionth of the larger are the same value, as are two
lists of the same tokens with or without the final ``;``, and a same value is
never a change.
"""

import math
import re
from collections.abc import Iterable

from pydantic import BaseModel

from art_mcp.keyfile import KeyFile

MAX_SHARED_CHANGES = 25
"""How many groups of identical changes a summary lists."""

SIGNIFICANT_DIGITS = 7
"""How many digits of a decimal are shown: what a 32-bit float holds."""

SAME_NUMBER = 1e-6
"""Two numbers are the same value when they differ by less than this fraction of
the larger one. A float32 is within 6e-8 of the decimal typed for it, so this
passes that rounding and still sees an edit in the sixth digit."""

_INTEGER = re.compile(r"[+-]?\d+")
_DECIMAL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


class KeyChange(BaseModel):
    group: str
    key: str
    before: str | None
    """The value in the earlier pass; null when the profile had no such key."""
    after: str | None


class SharedChange(BaseModel):
    """One change (the same group, key, before and after) and the frames it was made on."""

    group: str
    key: str
    before: str | None
    after: str | None
    images: list[str]
    """File names of the frames, in sheet order."""


class ChangeSummary(BaseModel):
    groups: list[SharedChange]
    """The changes shared by the most frames first, then by name."""
    more: int
    """How many further groups of changes are not listed."""


def number(token: str) -> int | float | None:
    """The number ``token`` is, or None: only a plain integer or decimal
    counts, not ``nan``, ``inf``, ``1_000``, one with spaces, or one too big for
    a double."""
    try:
        if _INTEGER.fullmatch(token):
            return int(token)
        if _DECIMAL.fullmatch(token):
            value = float(token)
            return value if math.isfinite(value) else None
    except ValueError:  # an integer with thousands of digits
        return None
    return None


def _short(token: str) -> str:
    value = number(token)
    return f"{value:.{SIGNIFICANT_DIGITS}g}" if isinstance(value, float) else token


def normalise_value(value: str | None) -> str | None:
    """``value`` with each decimal ``;``-separated token shown with at most
    seven significant digits (``6450.7001953125`` as ``6450.7``); integers and
    other text, and the separators, are left as they are."""
    if value is None:
        return None
    return ";".join(_short(token) for token in value.split(";"))


def _tokens(value: str) -> list[str]:
    """The tokens of a ``;``-separated list. A final ``;`` ends the list and is
    no token: a key file reads ``a;b`` and ``a;b;`` alike (an agent types the
    one, art-cli writes the other)."""
    tokens = value.split(";")
    if len(tokens) > 1 and tokens[-1] == "":
        tokens.pop()
    return tokens


def _same_number(x: int | float, y: int | float) -> bool:
    """Equal, or (unless both are integers, which are exact) closer than
    ``SAME_NUMBER`` of the larger. A zero is the same only as a zero."""
    if x == y:
        return True
    if isinstance(x, int) and isinstance(y, int):
        return False
    try:
        a, b = float(x), float(y)
    except OverflowError:  # an integer of hundreds of digits
        return False
    return abs(a - b) < SAME_NUMBER * max(abs(a), abs(b))


def _same_token(x: str, y: str) -> bool:
    if x == y:
        return True
    m, n = number(x), number(y)
    return m is not None and n is not None and _same_number(m, n)


def same_value(a: str | None, b: str | None) -> bool:
    """Whether two values are equal: the same text, or lists (a final ``;``
    does not count) of the same number of tokens each the same text or the same
    number, numbers being the same when they are the same 32-bit float, within
    a millionth of each other (``6450.7`` and ``6450.7001953125``)."""
    if a is None or b is None:
        return a is b
    if a == b:
        return True
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    return len(tokens_a) == len(tokens_b) and all(_same_token(x, y) for x, y in zip(tokens_a, tokens_b, strict=True))


def changes_between(before: KeyFile, after: KeyFile) -> list[KeyChange]:
    """Every value that differs between two profiles (changed, added or
    removed), in file order, shown normalised. A value that only differs in how
    a number was written is not a change."""
    changes: list[KeyChange] = []
    for group in [*before, *(g for g in after if g not in before)]:
        old, new = before.get(group, {}), after.get(group, {})
        for key in [*old, *(k for k in new if k not in old)]:
            if not same_value(old.get(key), new.get(key)):
                changes.append(
                    KeyChange(
                        group=group, key=key, before=normalise_value(old.get(key)), after=normalise_value(new.get(key))
                    )
                )
    return changes


def summarise(
    per_image: Iterable[tuple[str, list[KeyChange] | None]], limit: int = MAX_SHARED_CHANGES
) -> ChangeSummary | None:
    """The changes of ``(file name, its changes)`` pairs grouped by identical
    change, the ``limit`` most shared (then by group, key, before, after)
    listed and the rest counted in ``more``. A frame whose changes are None had
    nothing to compare with and counts for nothing; None when no frame had."""
    groups: dict[tuple[str, str, str | None, str | None], SharedChange] = {}
    compared = False
    for name, changes in per_image:
        if changes is None:
            continue
        compared = True
        for c in changes:
            shared = groups.setdefault(
                (c.group, c.key, c.before, c.after),
                SharedChange(group=c.group, key=c.key, before=c.before, after=c.after, images=[]),
            )
            shared.images.append(name)
    if not compared:
        return None
    ordered = sorted(
        groups.values(),
        key=lambda g: (-len(g.images), g.group.casefold(), g.key.casefold(), g.before or "", g.after or ""),
    )
    return ChangeSummary(groups=ordered[:limit], more=max(0, len(ordered) - limit))
