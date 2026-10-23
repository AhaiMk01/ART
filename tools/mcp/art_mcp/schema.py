"""The curated adjustments: typed, range-checked values of one tool each.

Hand-written to mirror ART's GUI ranges (spec Appendix A). Every field maps to
exactly one ``[Group] Key`` of the processing profile, recorded in the field's
``key`` extra. Fields default to ``None`` = "not set in this request".
"""

from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from art_mcp.compactschema import CompactModel, compact_model_schema, full_schema
from art_mcp.curves import CurveSpec

PPVERSION = 1064
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
    default_from: str | None = None,
    curve: bool = False,
    read_as: dict[str, str] | None = None,
) -> Any:
    """A curated field: the ``[Group] Key`` it sets (``group`` only when it
    isn't the tool's own group) and, for values ART stores differently from
    how they are named here, the stored form of each (``stored_as``). A field
    with no value of its own reads as the field it follows (``default_from``).
    ``read_as`` maps legacy stored names ART still loads to their current name."""
    extra: dict[str, Any] = {"key": key, "art_default": default}
    if unit:
        extra["unit"] = unit
    if group:
        extra["group"] = group
    if stored_as:
        extra["stored_as"] = stored_as
    if default_from:
        extra["default_from"] = default_from
    if curve:
        extra["curve"] = True
    if read_as:
        extra["read_as"] = read_as
    return Field(None, ge=ge, le=le, description=description, json_schema_extra=extra)


class Exposure(CompactModel):
    """Exposure compensation, black point and highlight recovery."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=True)
    compensation: float | None = F("Compensation", "Exposure compensation", ge=-12, le=12, unit="EV", default=0)
    black: float | None = F("Black", "Black point", ge=-2, le=2, default=0)
    hl_recovery: Literal["Off", "Blend", "Color", "Balanced"] | None = F(
        "HLRecovery", "Highlight recovery method for clipped raw highlights", default="Off"
    )
    hl_recovery_blur: int | None = F("HLRecoveryBlur", "Highlight recovery blur", ge=0, le=3, default=0)


class WhiteBalance(CompactModel):
    """White balance. Setting temperature, green or equal without `setting`
    switches `setting` to CustomTemp."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=True)
    setting: Literal["Camera", "Auto", "CustomTemp", "CustomMult"] | None = F(
        "Setting", "Where the white balance comes from", default="Camera"
    )
    temperature: int | None = F(
        "Temperature", "Colour temperature (CustomTemp)", ge=1500, le=60000, unit="K", default=6504
    )
    green: float | None = F(
        "Green",
        "Green/magenta tint multiplier (CustomTemp)",
        ge=0.02,
        le=10,
        unit="tint multiplier",
        default=1.0,
    )
    equal: float | None = F(
        "Equal",
        "Blue/red balance (CustomTemp)",
        ge=0.8,
        le=1.5,
        unit="blue/red balance",
        default=1.0,
    )


CropRatio = Literal[
    "As Image", "3:2", "4:3", "16:9", "16:10", "1:1", "2:1", "3:1", "4:1", "5:1",
    "6:1", "7:1", "4:5", "5:7", "6:7", "6:17", "24:65 - XPAN",
    "1.414 - ISO 216 (A4 paper)", "3.5:5", "8.5:11 - US Letter", "9.5:12", "10:12",
    "11:14", "11:17 - Tabloid", "13:19", "17:22", "45:35 - ePassport", "64:27",
]  # fmt: skip
"""ART's crop ratios (``crop_ratios`` in src/gui/crop.cc)."""


class RawEdit(BaseModel):
    model_config = ConfigDict(json_schema_extra=compact_model_schema)

    group: str
    key: str
    value: str

    @property
    def name(self) -> str:
        return f"[{self.group}] {self.key}"


class Crop(CompactModel):
    """Crop rectangle in pixels of the image frame (after coarse rotation and border). art-cli
    ignores `ratio`; the editor re-fits to it unless `fixed_ratio` is false."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    x: int | None = F("X", "Left edge", ge=0, unit="px", default=-1)
    y: int | None = F("Y", "Top edge", ge=0, unit="px", default=-1)
    w: int | None = F("W", "Width", ge=1, unit="px", default=-1)
    h: int | None = F("H", "Height", ge=1, unit="px", default=-1)
    fixed_ratio: bool | None = F(
        "FixedRatio", "Keep `ratio` when edited in ART", default=True
    )
    ratio: CropRatio | None = F("Ratio", "Aspect ratio", default="As Image")
    orientation: Literal["Landscape", "Portrait", "As Image"] | None = F(
        "Orientation", "Orientation of the ratio", default="As Image"
    )


class Rotation(CompactModel):
    """Fine rotation."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    degree: float | None = F("Degree", "Rotation angle", ge=-45, le=45, unit="deg", default=0)
    auto_fill: bool | None = F(
        "AutoFill", "Crop away the empty borders the rotation leaves",
        group="Common Properties for Transformations", default=True,
    )  # fmt: skip


class LocalContrast(CompactModel):
    """Local contrast (first region only; more regions, curves and masks are
    raw edits)."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    contrast: float | None = F("Contrast", "Local contrast amount", ge=-100, le=100, default=0)


class Sharpening(CompactModel):
    """Capture sharpening: unsharp mask (`usm`) or deconvolution (`rld`)."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    method: Literal["usm", "rld"] | None = F("Method", "Sharpening method", default="rld")
    contrast: float | None = F("Contrast", "Contrast threshold: leave flat areas alone", ge=0, le=200, default=20)
    amount: int | None = F("Amount", "Amount (usm)", ge=1, le=1000, default=200)
    radius: float | None = F("Radius", "Radius (usm)", ge=0.3, le=3, unit="px", default=0.5)
    deconv_amount: int | None = F("DeconvAmount", "Amount (rld)", ge=0, le=100, default=100)
    deconv_radius: float | None = F("DeconvRadius", "Radius (rld)", ge=0.4, le=2.5, unit="px", default=0.75)
    deconv_auto_radius: bool | None = F("DeconvAutoRadius", "Pick the rld radius automatically", default=True)


class Denoise(CompactModel):
    """Noise reduction: main luminance and chrominance amounts."""

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
    chrominance: float | None = F("Chrominance", "Chrominance noise reduction (manual)", ge=0, le=100, default=15)


class Vignetting(CompactModel):
    """Vignetting correction."""

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


class LensProfile(CompactModel):
    """Lens correction profile; `lc_mode` none turns it off."""

    lc_mode: Literal["none", "lfauto", "lfmanual", "lcp", "exif"] | None = F(
        "LcMode", "Where the lens profile comes from (none = off)", default="none"
    )
    use_distortion: bool | None = F("UseDistortion", "Correct distortion", default=True)
    use_vignette: bool | None = F("UseVignette", "Correct vignetting", default=True)
    use_ca: bool | None = F("UseCA", "Correct chromatic aberration", default=False)


CurveModeName = Literal[
    "Standard", "WeightedStd", "FilmLike", "SatAndValueBlending", "Luminance", "Perceptual", "Neutral"
]
"""ART's tone curve modes, named as ART writes them."""

_LEGACY_MODES = {"OpenDisplayTransform": "Neutral"}
"""Older mode names ART's loader still accepts."""


class ToneCurve(CompactModel):
    """Tone curves 1 and 2 and the contrast slider. A curve is `{"type":
    "spline"|"catmull_rom"|"nurbs", "points": [[x, y], ...]}` (2 to 32 points, x and y in 0..1,
    x strictly increasing) or `{"type": "linear"}`, in sRGB-gamma-encoded values. Setting a curve
    turns histogram_matching off (implied). For an S-curve use `contrast`."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    mode: CurveModeName | None = F("CurveMode", "How curve 1 is applied", default="Neutral", read_as=_LEGACY_MODES)
    mode2: CurveModeName | None = F(
        "CurveMode2", "How curve 2 is applied; omitted = same as mode",
        default="as mode", default_from="mode", read_as=_LEGACY_MODES,
    )  # fmt: skip
    histogram_matching: bool | None = F(
        "HistogramMatching", "Replace the curve by one matching a reference histogram", default=False
    )
    contrast: int | None = F(
        "Contrast",
        "Analytic contrast curve pivoting on scene middle grey; use it for an S-curve",
        ge=-100,
        le=100,
        default=0,
    )
    curve1: CurveSpec | None = F("Curve", "Curve 1: points or linear", default={"type": "linear"}, curve=True)
    curve2: CurveSpec | None = F("Curve2", "Curve 2: points or linear", default={"type": "linear"}, curve=True)


ShapeMode = Literal["add", "subtract", "intersect"]


class RectangleShape(CompactModel):
    """A rectangle (an ellipse at roundness 100) in image coordinates."""

    type: Literal["rectangle"]
    x: float | None = Field(
        None, ge=-100, le=100, description="Centre, -100 left .. 100 right"
    )
    y: float | None = Field(
        None, ge=-100, le=100, description="Centre, -100 top .. 100 bottom"
    )
    width: float | None = Field(None, ge=1, le=200, description="% of image width (100 = the image's)")
    height: float | None = Field(None, ge=1, le=200, description="% of image height (100 = the image's)")
    angle: float | None = Field(None, ge=-180, le=180, description="Rotation in degrees")
    roundness: float | None = Field(None, ge=0, le=100, description="0 = rectangle, 100 = ellipse")
    feather: float | None = Field(None, ge=0, le=100, description="Edge softness")
    blur: float | None = Field(None, ge=0, le=500, description="Blur of this shape's edge")
    mode: ShapeMode | None = Field(None, description="How the shape combines with the shapes before it")


class GradientShape(CompactModel):
    """A linear gradient across the image."""

    type: Literal["gradient"]
    x: float | None = Field(
        None, ge=-100, le=100, description="Position, -100 left .. 100 right"
    )
    y: float | None = Field(
        None, ge=-100, le=100, description="Position, -100 top .. 100 bottom"
    )
    strength_start: float | None = Field(None, ge=0, le=100, description="Mask strength where the gradient starts")
    strength_end: float | None = Field(None, ge=0, le=100, description="Mask strength where the gradient ends")
    angle: float | None = Field(None, ge=-180, le=180, description="Direction in degrees")
    feather: float | None = Field(None, ge=0, le=100, description="Width of the transition")
    blur: float | None = Field(None, ge=0, le=500, description="Blur of the gradient")
    mode: ShapeMode | None = Field(None, description="How the shape combines with the shapes before it")


MaskShape = Annotated[RectangleShape | GradientShape, Field(discriminator="type")]


class AreaMaskAdjustment(CompactModel):
    """An area mask: its shapes combined in order, then feathered, blurred and
    (inverted) flipped. Giving any mask field turns the mask on."""

    enabled: bool | None = Field(None, description="Turn the area mask on or off")
    inverted: bool | None = Field(
        None, description="Affect everything outside the shapes"
    )
    feather: float | None = Field(None, ge=0, le=100, description="Feather of the whole mask")
    blur: float | None = Field(None, ge=0, le=500, description="Blur of the whole mask")
    shapes: list[MaskShape | None] | None = Field(
        None,
        description="Shapes by position: edits the shape at its index (same type) or replaces it; "
        "one past the end appends; null keeps the position",
    )


class ChannelCdl(CompactModel):
    """One channel's slope, offset and power."""

    slope: float | None = Field(None, ge=0.01, le=10, description="Multiplier, applied first")
    offset: float | None = Field(
        None, ge=-0.15, le=0.15, description="Added after the slope, stored halved"
    )
    power: float | None = Field(
        None, ge=0.1, le=4, description="Inverse of the exponent applied"
    )


class ColorCorrectionRegion(CompactModel):
    """One Color Correction region in RGB mode: per-channel slope, offset and
    power, optionally restricted by an area mask."""

    r: ChannelCdl | None = None
    g: ChannelCdl | None = None
    b: ChannelCdl | None = None
    mask: AreaMaskAdjustment | None = None


class ColorCorrection(CompactModel):
    """Color Correction (ASC CDL-like), RGB-mode regions only. Linear working values: per channel
    `v = v*slope + offset/2`, then `v = v^(1/power)` (`power` is the inverse of the exponent
    applied). `regions` is by position; get_profile gives null for an untyped region, a null in
    a request skips it. Setting r, g or b switches a region to RGB mode, anything turns the tool
    on (`implied`). An entry past the end appends.

    Mask coordinates: origin at the image centre; x, y are % of HALF the width/height;
    width, height are % of the whole image."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    regions: list[ColorCorrectionRegion | None] | None = Field(
        None,
        description="Regions by position: r, g, b and an area mask",
        json_schema_extra={"key": "<Key>_<region number>", "art_default": None},
    )


def rgb_field(
    key: str,
    description: str,
    *,
    default: list[Any],
    allow_negative: bool = False,
) -> Any:
    """A curated field holding three numbers ``[r, g, b]`` (``rgb`` extra),
    stored as ``r;g;b``."""
    extra = {"key": key, "art_default": default, "rgb": True}
    if allow_negative:
        extra["allow_negative"] = True
    return Field(
        None, min_length=3, max_length=3, description=description,
        json_schema_extra=extra,
    )  # fmt: skip


class FilmNegative(CompactModel):
    """Film Negative: power_law or NamiColor (decode to signed linear RGB); references
    are as `sample_spots` reads them. Legacy power-law profiles (`BackCompat`, `RedBase`) stay
    raw: typed edits other than `enabled` are refused. Details: the film-negative skill."""

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    method: Literal["power_law", "namicolor"] | None = F(
        "Method",
        "Conversion method",
        # density was removed: ART loads it (text or 1) as power_law
        read_as={"0": "power_law", "1": "power_law", "density": "power_law", "2": "namicolor"},
        default="power_law",
    )  # fmt: skip
    film_type: Literal["negative", "reversal"] | None = F(
        "FilmType",
        "negative or reversal",
        read_as={"0": "negative", "1": "reversal"}, default="negative",
    )  # fmt: skip
    color_space: Literal["working", "input"] | None = F(
        "ColorSpace",
        "Space of references",
        stored_as={"working": "1", "input": "0"}, default="working",
    )  # fmt: skip
    red_ratio: float | None = F("RedRatio", "Red/green exponent", ge=0.3, le=5, default=1.36)
    green_exponent: float | None = F(
        "GreenExponent", "Master exponent", ge=0.3, le=4, default=1.5
    )
    blue_ratio: float | None = F("BlueRatio", "Blue/green exponent", ge=0.3, le=5, default=0.86)
    ref_input: list[Annotated[float, Field(ge=0)]] | None = rgb_field(
        "RefInput",
        "[r,g,b] 0..65535: spot's linear value; 0;0;0 = unset",
        default=[0.0, 0.0, 0.0],
    )
    ref_output: list[Annotated[float, Field(ge=0)]] | None = rgb_field(
        "RefOutput",
        "[r,g,b] 0..65535: level it gets; 0;0;0 = unset",
        default=[0.0, 0.0, 0.0],
    )
    input_gamma: float | None = F(
        "InputGamma",
        'Source exponent; not 1 only for an unprofiled non-RAW scan (profile "(none)")',
        ge=0.5,
        le=2.8,
        default=1.0,
    )
    namicolor_input_gain: float | None = F(
        "NamiColorInputGain", "Log-input slope", ge=0.0, le=2.0, default=1.0
    )
    namicolor_master_gain: float | None = F(
        "NamiColorMasterGain", "Master gain", ge=-0.5, le=0.5, default=0.0
    )
    namicolor_master_shift: float | None = F(
        "NamiColorMasterShift", "Master shift", ge=-1.0, le=1.0, default=0.0
    )
    namicolor_black: list[Annotated[float, Field(ge=-0.5, le=0.5)]] | None = rgb_field(
        "NamiColorBlack",
        "Black terms",
        default=[0.0, 0.0, 0.0],
        allow_negative=True,
    )
    namicolor_gain: list[Annotated[float, Field(ge=-1.0, le=1.0)]] | None = rgb_field(
        "NamiColorGain",
        "Denominator gains",
        default=[0.0, 0.0, 0.0],
        allow_negative=True,
    )
    namicolor_shift: list[Annotated[float, Field(ge=-1.0, le=1.0)]] | None = rgb_field(
        "NamiColorShift",
        "Log-code shifts",
        default=[0.0, 0.0, 0.0],
        allow_negative=True,
    )
    namicolor_fit_base: bool | None = F(
        "NamiColorFitBase",
        "NamiColor linear code remap, see fit_base_anchor",
        default=False,
    )
    fit_base_anchor: Literal["legacy", "code95"] | None = F(
        "NamiColorFitBaseAnchor",
        "code95: code 0 -> 95; legacy: 93/1023",
        default="code95",
    )
    flare: list[Annotated[float, Field(ge=0.0, le=0.5)]] | None = rgb_field(
        "Flare",
        "fraction removed pre-log",
        default=[0.0, 0.0, 0.0],
    )
    matrix_preset: Literal["identity", "status_m_reference", "custom"] | None = F(
        "MatrixPreset",
        "Mask preset",
        read_as={"0": "identity", "1": "status_m_reference", "2": "custom"},
        default="identity",
    )
    cineon_reference_white: float | None = F(
        "CineonReferenceWhite",
        "W: linear value of Cineon code 685",
        ge=1e-6,
        le=1e6,
        default=0.9,
    )
    matrix: list[Annotated[float, Field(ge=-10.0, le=10.0)]] | None = Field(
        None,
        min_length=9,
        max_length=9,
        description=(
            "Nine row-major coefficients; edits need custom"
        ),
        json_schema_extra={
            "key": "Matrix",
            "art_default": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            "matrix": True,
        },
    )
    matrix_basis: str | None = F(
        "MatrixBasis",
        "Binding JSON; needed if non-identity",
        default="",
    )
    calibration_note: str | None = F(
        "CalibrationNote",
        "Capture note",
        default="",
    )


class Adjustments(CompactModel):
    """Typed changes to curated tools. Set only what should change."""

    exposure: Exposure | None = None
    white_balance: WhiteBalance | None = None
    crop: Crop | None = None
    rotation: Rotation | None = None
    local_contrast: LocalContrast | None = None
    sharpening: Sharpening | None = None
    denoise: Denoise | None = None
    vignetting: Vignetting | None = None
    lens_profile: LensProfile | None = None
    tone_curve: ToneCurve | None = None
    color_correction: ColorCorrection | None = None
    film_negative: FilmNegative | None = None


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
    "tone_curve": ("ToneCurve", ToneCurve),
    "color_correction": ("ColorCorrection", ColorCorrection),
    "film_negative": ("Film Negative", FilmNegative),
}
"""Tool name -> ([Group] in the .arp, its model)."""


def _extra(model: type[BaseModel], name: str) -> dict[str, Any]:
    extra = model.model_fields[name].json_schema_extra
    assert isinstance(extra, dict)
    return extra


def field_key(model: type[BaseModel], name: str) -> str:
    return str(_extra(model, name)["key"])


def art_default(model: type[BaseModel], name: str) -> Any:
    """ART's built-in value for a field, what a key missing from the profile means."""
    return _extra(model, name).get("art_default")


def field_group(model: type[BaseModel], name: str, tool_group: str) -> str:
    """The [Group] a field sets: the tool's own, unless the field names
    another (Rotation's AutoFill)."""
    return str(_extra(model, name).get("group", tool_group))


def tool_groups(tool_group: str, model: type[BaseModel]) -> set[str]:
    """Every [Group] a curated tool's fields live in: its own, and the group
    of each field that names another."""
    return {tool_group} | {field_group(model, name, tool_group) for name in model.model_fields}


def stored_value(model: type[BaseModel], name: str, value: str) -> str:
    """How ART stores a field's value (Denoise's method is a number)."""
    return str(_extra(model, name).get("stored_as", {}).get(value, value))


def named_value(model: type[BaseModel], name: str, stored: str) -> str:
    """The inverse of ``stored_value``."""
    for named, as_stored in _extra(model, name).get("stored_as", {}).items():
        if as_stored == stored:
            return str(named)
    return str(_extra(model, name).get("read_as", {}).get(stored, stored))


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
        with full_schema():  # the compact one has no keys, defaults or units
            properties = model.model_json_schema()["properties"]
        fields: dict[str, FieldDescription] = {}
        for field, prop in properties.items():
            if _extra(model, field).get("ephemeral"):
                continue
            # Optional fields come as anyOf [<real schema>, null]: flatten.
            real = next((p for p in prop.get("anyOf", [prop]) if p.get("type") != "null"), prop)
            fields[field] = FieldDescription(
                group=field_group(model, field, group),
                key=prop["key"],
                type=real.get("type") or "curve",
                minimum=real.get("minimum"),
                maximum=real.get("maximum"),
                unit=prop.get("unit"),
                enum=real.get("enum"),
                default=prop["art_default"],
                description=prop.get("description", ""),
            )
        tools[name] = ToolDescription(group=group, description=(model.__doc__ or "").strip(), fields=fields)
    return AdjustmentsDescription(schema_ppversion=PPVERSION, tools=tools)


def _as_given(value: Any) -> Any:
    return value


AdjustmentsArg = Annotated[
    dict[str, Any] | None,
    BeforeValidator(_as_given, json_schema_input_type=Adjustments | None),
]
"""``edit_profile``'s `adjustments` argument (both servers). Validated by
hand (``parse_adjustments``) so a bad value is reported as out_of_range rather
than as a generic schema error; the published input schema is still the typed
one (compact: ``art_mcp.compactschema``), its models defined once under
`$defs`."""


class EditItem(CompactModel):
    """One image's own edit in an edit_profile call with `items`: the same
    `adjustments` and `raw_edits` as the call takes for `path`."""

    path: str
    adjustments: AdjustmentsArg = None
    raw_edits: list[RawEdit] | None = None


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
    if kind == "extra_forbidden" and len(loc) > 2:
        return "unknown_key", f"{where} is not accepted here"
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
    if kind in ("greater_than_equal", "less_than_equal"):
        ctx = error.get("ctx", {})
        lo, hi = ctx.get("ge"), ctx.get("le")
        bound = f">= {lo}" if lo is not None else f"<= {hi}"
        return "out_of_range", f"{where}={error['input']!r} is outside the range ({bound})"
    return "out_of_range", f"{where}: {error['msg'].removeprefix('Value error, ')}"


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
