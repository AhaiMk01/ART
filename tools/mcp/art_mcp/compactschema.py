"""A compact JSON schema for the models in a tool's input schema.

Pydantic writes a `title` on every model and field, `default: null` and an
`anyOf: [<type>, {"type": "null"}]` wrapper on every optional field and
`additionalProperties: false` on every model; ``schema.F`` adds ART
bookkeeping (the stored key, ART's default, ...) to every curated field. A
client loads all of it with every session, for ``edit_profile`` about 30,000
characters, and an agent needs none of it to form a request.

``CompactModel`` is the base of the models that go into an input schema: its
``json_schema_extra`` drops that noise, folds a field's unit into its
description, and keeps only the first paragraph of the model's docstring (the
rest is reference text for ``describe_adjustments``). Validation is not
touched: the models accept and reject what they always did, and an optional
field is just its type in the schema (leaving it out, or null, means "not
set"). ``full_schema`` switches the compaction off for code that wants the
complete schema (``schema.describe_adjustments``).
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel, ConfigDict

_compact: ContextVar[bool] = ContextVar("compact_schema", default=True)

BOOKKEEPING = (
    "key", "art_default", "group", "stored_as", "default_from", "curve", "read_as", "rgb",
)  # fmt: skip
"""The extras ``schema.F`` and ``schema.rgb_field`` put on a field: for
``describe_adjustments`` and the reading code, not for a caller."""

NO_NEWS = {"enabled": "Turn the tool on or off"}
"""Field name -> a description that says no more than the name."""


@contextmanager
def full_schema() -> Iterator[None]:
    """Within the block the models emit their complete JSON schema."""
    token = _compact.set(False)
    try:
        yield
    finally:
        _compact.reset(token)


def _restates(name: str, description: str) -> bool:
    """Whether ``description`` only repeats the field's name ("Amount" for
    `amount`)."""
    words = re.sub(r"\W+", " ", description).strip().lower()
    return words == name.replace("_", " ").lower() or NO_NEWS.get(name) == description


def _with_unit(description: str, unit: str) -> str:
    """``description`` followed by its ``unit``: inside the closing
    parenthesis it already ends with ("Radius (usm)" -> "Radius (usm, px)"),
    else in new ones; not at all when it says so already."""
    if re.search(rf"\b{re.escape(unit)}\b", description, re.IGNORECASE):
        return description
    if "(" in unit:
        return f"{description}: {unit}"
    if description.endswith(")"):
        return f"{description[:-1]}, {unit})"
    return f"{description} ({unit})"


def _compact_property(name: str, prop: dict[str, Any]) -> None:
    for noise in ("title", *BOOKKEEPING):
        prop.pop(noise, None)
    if "default" in prop and prop["default"] is None:
        del prop["default"]  # "not set" is the same as leaving the field out
    unit = prop.pop("unit", None)
    options = prop.get("anyOf")
    if isinstance(options, list) and len(options) == 2 and {"type": "null"} in options:
        # An optional field is just its type: leaving it out (or null) means "not set".
        inner = next(o for o in options if o != {"type": "null"})
        del prop["anyOf"]
        prop.update(inner)
    description = prop.get("description")
    if isinstance(description, str):
        if unit:
            description = _with_unit(description, unit)
        if _restates(name, description):
            del prop["description"]
        else:
            prop["description"] = description


def compact_model_schema(schema: dict[str, Any], model: type) -> None:
    """``json_schema_extra`` of a model: no titles, defaults, bookkeeping,
    ``additionalProperties`` or optional wrappers (a list item that may be
    null stays so: its position matters). Of the model's docstring the schema
    keeps the first paragraph, on one line: what a caller needs. The rest is
    reference text for ``describe_adjustments``."""
    if not _compact.get():
        return
    for noise in ("title", "additionalProperties"):
        schema.pop(noise, None)
    description = schema.get("description")
    if isinstance(description, str):
        schema["description"] = " ".join(description.split("\n\n")[0].split())
    for name, prop in schema.get("properties", {}).items():
        _compact_property(name, prop)


SCHEMA_MAPS = ("properties", "$defs", "definitions")
"""Keys whose value maps names to schemas: the names (a parameter called `title`) are not annotations."""


def compact_tool_schema(node: Any) -> Any:
    """``node`` (a tool's input or output schema, or a part of one) without the
    annotations a model reads nothing from: every ``title`` and every
    ``default: null``. A copy; ``node`` is not changed. Nothing that says what
    is valid goes: a parameter that may be null still has its ``null``."""
    if isinstance(node, list):
        return [compact_tool_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    compact: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue
        if key == "default" and value is None:
            continue
        if key in SCHEMA_MAPS and isinstance(value, dict):
            compact[key] = {name: compact_tool_schema(schema) for name, schema in value.items()}
        else:
            compact[key] = compact_tool_schema(value)
    return compact


class CompactToolSchemas:
    """Server middleware (``async (ctx, call_next)``) that thins the schemas in
    a ``tools/list`` result with ``compact_tool_schema``: pydantic writes a
    ``title`` on every parameter, field and model and a ``default: null`` on
    every optional one, and a client loads all of it, input and output
    schemas, with every session. Only what a client is told changes: calls are
    validated against the tool's own parameters, as before."""

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        result = await call_next(ctx)
        if ctx.method == "tools/list":
            # What middleware sees of a result is the wire form: a dict, camelCase keys.
            for tool in result.get("tools", []):
                for key in ("inputSchema", "outputSchema"):
                    if tool.get(key):
                        tool[key] = compact_tool_schema(tool[key])
        return result


class CompactModel(BaseModel):
    """A model that rejects unknown fields and has a compact JSON schema."""

    model_config = ConfigDict(extra="forbid", json_schema_extra=compact_model_schema)
