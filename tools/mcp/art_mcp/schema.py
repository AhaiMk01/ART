"""The curated adjustments: typed, range-checked values of one tool each.

Hand-written to mirror ART's GUI ranges (spec Appendix A). Every field maps to
exactly one ``[Group] Key`` of the processing profile, recorded in the field's
``key`` extra. Fields default to ``None`` = "not set in this request".
"""

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PPVERSION = 1045
"""The processing-profile version (``src/utils/ppversion.h``) this schema was
written for."""


def F(
    key: str,
    description: str,
    *,
    ge: float | None = None,
    le: float | None = None,
    unit: str | None = None,
    default: Any = None,
) -> Any:
    extra: dict[str, Any] = {"key": key, "art_default": default}
    if unit:
        extra["unit"] = unit
    return Field(None, ge=ge, le=le, description=description, json_schema_extra=extra)


class Exposure(BaseModel):
    """Exposure compensation, black point and highlight recovery."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=True)
    compensation: float | None = F(
        "Compensation", "Exposure compensation", ge=-12, le=12, unit="EV", default=0
    )
    black: float | None = F("Black", "Black point", ge=-2, le=2, default=0)
    hl_recovery: Literal["Off", "Blend", "Color", "Balanced"] | None = F(
        "HLRecovery", "Highlight recovery method for clipped raw highlights", default="Off"
    )
    hl_recovery_blur: int | None = F(
        "HLRecoveryBlur", "Highlight recovery blur", ge=0, le=3, default=0
    )


class WhiteBalance(BaseModel):
    """White balance. Setting temperature, green or equal without `setting`
    switches `setting` to CustomTemp."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=True)
    setting: Literal["Camera", "Auto", "CustomTemp", "CustomMult"] | None = F(
        "Setting", "Where the white balance comes from", default="Camera"
    )
    temperature: int | None = F(
        "Temperature", "Colour temperature (CustomTemp)", ge=1500, le=60000, unit="K", default=6504
    )
    green: float | None = F(
        "Green", "Green/magenta tint multiplier (CustomTemp)", ge=0.02, le=10,
        unit="tint multiplier", default=1.0,
    )
    equal: float | None = F(
        "Equal", "Blue/red balance (CustomTemp)", ge=0.8, le=1.5, unit="blue/red balance",
        default=1.0,
    )


class Adjustments(BaseModel):
    """Typed changes to curated tools. Set only what should change."""

    model_config = ConfigDict(extra="forbid")

    exposure: Exposure | None = None
    white_balance: WhiteBalance | None = None


TOOLS: dict[str, tuple[str, type[BaseModel]]] = {
    "exposure": ("Exposure", Exposure),
    "white_balance": ("White Balance", WhiteBalance),
}
"""Tool name -> ([Group] in the .arp, its model)."""


def field_key(model: type[BaseModel], name: str) -> str:
    extra = model.model_fields[name].json_schema_extra
    assert isinstance(extra, dict)
    return str(extra["key"])


class FieldDescription(BaseModel):
    key: str
    """The [Group] Key it maps to (group: see the tool)."""
    type: str
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    enum: list[str] | None = None
    default: Any = None
    """ART's built-in default; an image's actual value comes from its profile."""
    description: str


class ToolDescription(BaseModel):
    group: str
    description: str
    fields: dict[str, FieldDescription]


class AdjustmentsDescription(BaseModel):
    schema_ppversion: int
    """The PPVERSION this schema was written for."""
    tools: dict[str, ToolDescription]
    warnings: list[str] = []


def describe_adjustments() -> AdjustmentsDescription:
    tools: dict[str, ToolDescription] = {}
    for name, (group, model) in TOOLS.items():
        properties = model.model_json_schema()["properties"]
        fields: dict[str, FieldDescription] = {}
        for field, prop in properties.items():
            # Optional fields come as anyOf [<real schema>, null]: flatten.
            real = next((p for p in prop.get("anyOf", [prop]) if p.get("type") != "null"), prop)
            fields[field] = FieldDescription(
                key=prop["key"],
                type=real["type"],
                minimum=real.get("minimum"),
                maximum=real.get("maximum"),
                unit=prop.get("unit"),
                enum=real.get("enum"),
                default=prop["art_default"],
                description=prop["description"],
            )
        tools[name] = ToolDescription(
            group=group, description=(model.__doc__ or "").strip(), fields=fields
        )
    return AdjustmentsDescription(schema_ppversion=PPVERSION, tools=tools)


def adjustments_json_schema() -> dict[str, Any]:
    """The JSON schema of ``Adjustments`` with its definitions inlined, for
    ``edit_profile``'s input schema."""
    schema = Adjustments.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: inline(v) for k, v in node.items()}
        if isinstance(node, list):
            return [inline(v) for v in node]
        return node

    result: dict[str, Any] = inline(schema)
    return result


class AdjustmentError(Exception):
    def __init__(self, code: Literal["out_of_range", "unknown_key"], message: str) -> None:
        super().__init__(message)
        self.code = code


def _range_text(model: type[BaseModel], name: str) -> str:
    info = model.model_fields[name]
    lo = hi = None
    for m in info.metadata:
        lo = getattr(m, "ge", lo)
        hi = getattr(m, "le", hi)
    extra = info.json_schema_extra
    unit = f" {extra['unit']}" if isinstance(extra, dict) and "unit" in extra else ""
    return f"{lo:g}..{hi:g}{unit}"


def _describe(error: Any) -> tuple[str, str]:
    """(code, message) for one pydantic error."""
    loc = [str(p) for p in error["loc"]]
    where = ".".join(loc)
    kind = error["type"]
    if kind == "extra_forbidden":
        known = ", ".join(sorted(_known_names(loc[:-1])))
        return "unknown_key", f"{where} is not an adjustment (known here: {known})"
    if kind in ("greater_than_equal", "less_than_equal") and len(loc) == 2:
        model = TOOLS[loc[0]][1]
        return "out_of_range", f"{where}={error['input']!r} is outside {_range_text(model, loc[1])}"
    if kind == "literal_error" and len(loc) == 2:
        model = TOOLS[loc[0]][1]
        allowed = ", ".join(get_args(_literal_of(model, loc[1])))
        return "out_of_range", f"{where}={error['input']!r} is not one of: {allowed}"
    return "out_of_range", f"{where}: {error['msg']}"


def _literal_of(model: type[BaseModel], name: str) -> Any:
    annotation = model.model_fields[name].annotation
    for arg in get_args(annotation):
        if get_args(arg):
            return arg
    return annotation


def _known_names(loc: list[str]) -> list[str]:
    if not loc:
        return list(TOOLS)
    return list(TOOLS[loc[0]][1].model_fields)


def parse_adjustments(data: dict[str, Any]) -> Adjustments:
    """Validate an ``adjustments`` request. Raises AdjustmentError with code
    ``out_of_range`` (value outside its range or enum) or ``unknown_key``
    (no such tool or field); nothing is clamped."""
    try:
        return Adjustments.model_validate(data)
    except ValidationError as e:
        problems = [_describe(err) for err in e.errors()]
        code: Literal["out_of_range", "unknown_key"] = (
            "unknown_key" if all(c == "unknown_key" for c, _ in problems) else "out_of_range"
        )
        raise AdjustmentError(code, "; ".join(m for _, m in problems)) from None
