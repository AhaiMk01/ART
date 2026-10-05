"""What changed between two passes of a contact sheet: the differing profile
values, with numbers shown in their shortest form, and the changes of many
frames grouped by identical change.

Pure: no ART, no files. ``sheet_ops`` records the per-frame changes in a pass's
JSON and returns the grouped summary.

ART writes a double with 17 significant digits (``1.3700000000000001``), which
costs an agent context and says nothing more than ``1.37``. A value that is a
number, or a ``;``-separated list of tokens (a curve, ``r;g;b;``) some of
which are, is shown with each numeric token as ``repr(float(token))``; an
integer and any other text stay as written. Two values that are numerically
equal are the same value however they were written, so they are never a change.
"""

import math
import re
from collections.abc import Iterable

from pydantic import BaseModel

from art_mcp.keyfile import KeyFile

MAX_SHARED_CHANGES = 25
"""How many groups of identical changes a summary lists."""

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


def _shortest(token: str) -> str:
    value = number(token)
    return repr(value) if isinstance(value, float) else token


def normalise_value(value: str | None) -> str | None:
    """``value`` with each numeric ``;``-separated token in its shortest
    round-trip form; integers and other text are left as they are."""
    if value is None:
        return None
    return ";".join(_shortest(token) for token in value.split(";"))


def same_value(a: str | None, b: str | None) -> bool:
    """Whether two values are equal: the same text, or the same number of
    ``;``-separated tokens each the same text or the same number."""
    if a is None or b is None:
        return a is b
    if a == b:
        return True
    tokens_a, tokens_b = a.split(";"), b.split(";")
    return len(tokens_a) == len(tokens_b) and all(
        x == y or ((n := number(x)) is not None and n == number(y)) for x, y in zip(tokens_a, tokens_b, strict=True)
    )


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
