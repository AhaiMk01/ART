"""The curated adjustments: typed, range-checked values of one tool each.

Hand-written to mirror ART's GUI ranges (spec Appendix A). Every field maps to
exactly one ``[Group] Key`` of the processing profile, recorded in the field's
``key`` extra. Fields default to ``None`` = "not set in this request".
"""

from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, WithJsonSchema

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
    group: str | None = None,
    stored_as: dict[str, str] | None = None,
) -> Any:
    """A curated field: the ``[Group] Key`` it sets (``group`` only when it
    isn't the tool's own group) and, for values ART stores differently from
    how they are named here, the stored form of each (``stored_as``)."""
    extra: dict[str, Any] = {"key": key, "art_default": default}
    if unit:
        extra["unit"] = unit
    if group:
        extra["group"] = group
    if stored_as:
        extra["stored_as"] = stored_as
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


CropRatio = Literal[
    "As Image", "3:2", "4:3", "16:9", "16:10", "1:1", "2:1", "3:1", "4:1", "5:1",
    "6:1", "7:1", "4:5", "5:7", "6:7", "6:17", "24:65 - XPAN",
    "1.414 - ISO 216 (A4 paper)", "3.5:5", "8.5:11 - US Letter", "9.5:12", "10:12",
    "11:14", "11:17 - Tabloid", "13:19", "17:22", "45:35 - ePassport", "64:27",
]  # fmt: skip
"""ART's crop ratios (``crop_ratios`` in src/gui/crop.cc)."""


class Crop(BaseModel):
    """Crop rectangle in the pixels of the image frame (the raw image after
    coarse rotation and the raw border); checked against the image's size."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    x: int | None = F("X", "Left edge", ge=0, unit="px", default=-1)
    y: int | None = F("Y", "Top edge", ge=0, unit="px", default=-1)
    w: int | None = F("W", "Width", ge=1, unit="px", default=-1)
    h: int | None = F("H", "Height", ge=1, unit="px", default=-1)
    fixed_ratio: bool | None = F("FixedRatio", "Keep `ratio` when resizing", default=True)
    ratio: CropRatio | None = F("Ratio", "Aspect ratio", default="As Image")
    orientation: Literal["Landscape", "Portrait", "As Image"] | None = F(
        "Orientation", "Orientation of the ratio", default="As Image"
    )


class Rotation(BaseModel):
    """Fine rotation."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    degree: float | None = F("Degree", "Rotation angle", ge=-45, le=45, unit="deg", default=0)
    auto_fill: bool | None = F(
        "AutoFill", "Crop away the empty borders the rotation leaves",
        group="Common Properties for Transformations", default=True,
    )  # fmt: skip


class LocalContrast(BaseModel):
    """Local contrast (first region only; more regions, curves and masks are
    raw edits)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    contrast: float | None = F("Contrast", "Local contrast amount", ge=-100, le=100, default=0)


class Sharpening(BaseModel):
    """Capture sharpening: unsharp mask (`usm`) or deconvolution (`rld`)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    method: Literal["usm", "rld"] | None = F("Method", "Sharpening method", default="rld")
    contrast: float | None = F(
        "Contrast", "Contrast threshold: leave flat areas alone", ge=0, le=200, default=20
    )
    amount: int | None = F("Amount", "Amount (usm)", ge=1, le=1000, default=200)
    radius: float | None = F("Radius", "Radius (usm)", ge=0.3, le=3, unit="px", default=0.5)
    deconv_amount: int | None = F("DeconvAmount", "Amount (rld)", ge=0, le=100, default=100)
    deconv_radius: float | None = F(
        "DeconvRadius", "Radius (rld)", ge=0.4, le=2.5, unit="px", default=0.75
    )
    deconv_auto_radius: bool | None = F(
        "DeconvAutoRadius", "Pick the rld radius automatically", default=True
    )


class Denoise(BaseModel):
    """Noise reduction: main luminance and chrominance amounts."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    luminance: float | None = F("Luminance", "Luminance noise reduction", ge=0, le=100, default=0)
    chrominance_method: Literal["manual", "automatic"] | None = F(
        "ChrominanceMethod", "How the chrominance amount is chosen",
        stored_as={"manual": "0", "automatic": "1"}, default="automatic",
    )  # fmt: skip
    chrominance_auto_factor: float | None = F(
        "ChrominanceAutoFactor", "Scales the automatic chrominance amount",
        ge=0, le=1, default=1,
    )  # fmt: skip
    chrominance: float | None = F(
        "Chrominance", "Chrominance noise reduction (manual)", ge=0, le=100, default=15
    )


class Vignetting(BaseModel):
    """Vignetting correction."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    amount: int | None = F("Amount", "Amount", ge=-100, le=100, default=0)
    radius: int | None = F("Radius", "Radius", ge=0, le=100, default=50)
    strength: int | None = F("Strength", "Strength", ge=1, le=100, default=1)
    center_x: int | None = F(
        "CenterX", "Horizontal centre offset", ge=-100, le=100,
        unit="% of image width from centre", default=0,
    )  # fmt: skip
    center_y: int | None = F(
        "CenterY", "Vertical centre offset", ge=-100, le=100,
        unit="% of image height from centre", default=0,
    )  # fmt: skip


class LensProfile(BaseModel):
    """Lens correction profile; `lc_mode` none turns it off."""

    model_config = ConfigDict(extra="forbid")

    lc_mode: Literal["none", "lfauto", "lfmanual", "lcp", "exif"] | None = F(
        "LcMode", "Where the lens profile comes from (none = off)", default="none"
    )
    use_distortion: bool | None = F("UseDistortion", "Correct distortion", default=True)
    use_vignette: bool | None = F("UseVignette", "Correct vignetting", default=True)
    use_ca: bool | None = F("UseCA", "Correct chromatic aberration", default=False)


class Adjustments(BaseModel):
    """Typed changes to curated tools. Set only what should change."""

    model_config = ConfigDict(extra="forbid")

    exposure: Exposure | None = None
    white_balance: WhiteBalance | None = None
    crop: Crop | None = None
    rotation: Rotation | None = None
    local_contrast: LocalContrast | None = None
    sharpening: Sharpening | None = None
    denoise: Denoise | None = None
    vignetting: Vignetting | None = None
    lens_profile: LensProfile | None = None


TOOLS: dict[str, tuple[str, type[BaseModel]]] = {
    "exposure": ("Exposure", Exposure),
    "white_balance": ("White Balance", WhiteBalance),
    "crop": ("Crop", Crop),
    "rotation": ("Rotation", Rotation),
    "local_contrast": ("Local Contrast", LocalContrast),
    "sharpening": ("Sharpening", Sharpening),
    "denoise": ("Denoise", Denoise),
    "vignetting": ("Vignetting Correction", Vignetting),
    "lens_profile": ("LensProfile", LensProfile),
}
"""Tool name -> ([Group] in the .arp, its model)."""


def _extra(model: type[BaseModel], name: str) -> dict[str, Any]:
    extra = model.model_fields[name].json_schema_extra
    assert isinstance(extra, dict)
    return extra


def field_key(model: type[BaseModel], name: str) -> str:
    return str(_extra(model, name)["key"])


def field_group(model: type[BaseModel], name: str, tool_group: str) -> str:
    """The [Group] a field sets: the tool's own, unless the field names
    another (Rotation's AutoFill)."""
    return str(_extra(model, name).get("group", tool_group))


def stored_value(model: type[BaseModel], name: str, value: str) -> str:
    """How ART stores a field's value (Denoise's method is a number)."""
    return str(_extra(model, name).get("stored_as", {}).get(value, value))


def named_value(model: type[BaseModel], name: str, stored: str) -> str:
    """The inverse of ``stored_value``."""
    for named, as_stored in _extra(model, name).get("stored_as", {}).items():
        if as_stored == stored:
            return str(named)
    return stored


def crop_bounds_problem(x: int, y: int, w: int, h: int, *, frame_w: int, frame_h: int) -> str | None:
    """Why a crop rectangle doesn't fit a ``frame_w`` x ``frame_h`` frame, or
    None if it does."""
    if x < 0 or y < 0 or w < 1 or h < 1:
        return f"crop x={x}, y={y}, w={w}, h={h} needs x, y >= 0 and w, h >= 1"
    if x + w > frame_w or y + h > frame_h:
        return (
            f"crop x={x}, y={y}, w={w}, h={h} reaches past the image "
            f"({frame_w}x{frame_h} px): needs x + w <= {frame_w} and y + h <= {frame_h}"
        )
    return None


class FieldDescription(BaseModel):
    group: str
    key: str
    """The [Group] Key it sets."""
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
                group=field_group(model, field, group),
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


AdjustmentsArg = Annotated[
    dict[str, Any] | None,
    WithJsonSchema({"anyOf": [adjustments_json_schema(), {"type": "null"}]}),
]
"""``edit_profile``'s `adjustments` argument (both servers). Validated by
hand (``parse_adjustments``) so a bad value is reported as out_of_range rather
than as a generic schema error; the published input schema is still the typed
one."""


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
    if lo is not None and hi is not None:
        return f"{lo:g}..{hi:g}{unit}"
    return f">= {lo:g}{unit}" if lo is not None else f"<= {hi:g}{unit}"


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
