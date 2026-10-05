"""The curated adjustments: typed, range-checked values of one tool each.

Hand-written to mirror ART's GUI ranges (spec Appendix A). Every field maps to
exactly one ``[Group] Key`` of the processing profile, recorded in the field's
``key`` extra. Fields default to ``None`` = "not set in this request".
"""

from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, WithJsonSchema

from art_mcp.curves import CurveSpec

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
    coarse rotation and the raw border); checked against the image's size.

    ART's defaults keep a fixed aspect ratio (`fixed_ratio` true, `ratio`
    "As Image"): the editor's crop tool then re-fits the rectangle to the
    ratio whenever it is edited, so a free rectangle needs `fixed_ratio:
    false`. Headless renders (art-cli) use x, y, w, h as given and ignore the
    ratio; it only shapes the default rectangle when none is set."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    x: int | None = F("X", "Left edge", ge=0, unit="px", default=-1)
    y: int | None = F("Y", "Top edge", ge=0, unit="px", default=-1)
    w: int | None = F("W", "Width", ge=1, unit="px", default=-1)
    h: int | None = F("H", "Height", ge=1, unit="px", default=-1)
    fixed_ratio: bool | None = F("FixedRatio", "Keep `ratio` when the rectangle is edited in ART; false = free rectangle", default=True)
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


CurveModeName = Literal[
    "Standard", "WeightedStd", "FilmLike", "SatAndValueBlending", "Luminance", "Perceptual", "Neutral"
]
"""ART's tone curve modes, named as ART writes them."""

_LEGACY_MODES = {"OpenDisplayTransform": "Neutral"}
"""Older mode names ART's loader still accepts."""


class ToneCurve(BaseModel):
    """Tone curves 1 and 2 and the contrast slider. A curve is `{"type":
    "spline"|"catmull_rom"|"nurbs", "points": [[x, y], ...]}` (2 to 32 points,
    x and y in 0..1, x strictly increasing) or `{"type": "linear"}`. x and y are
    sRGB-gamma-encoded 0..1 values of the image at the curve's place in the
    pipeline, so they line up roughly with image_stats 8-bit values / 255.
    Setting a curve while histogram_matching is on turns histogram_matching off
    (implied). For an S-curve use `contrast` rather than curve points."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    mode: CurveModeName | None = F(
        "CurveMode", "How curve 1 is applied", default="Neutral", read_as=_LEGACY_MODES
    )
    mode2: CurveModeName | None = F(
        "CurveMode2", "How curve 2 is applied; omitted = same as mode",
        default="as mode", default_from="mode", read_as=_LEGACY_MODES,
    )  # fmt: skip
    histogram_matching: bool | None = F(
        "HistogramMatching", "Replace the curve by one matching a reference histogram", default=False
    )
    contrast: int | None = F(
        "Contrast",
        "ART's analytic contrast curve (a power curve pivoting on scene middle grey 0.18, or "
        "Log Encoding's target grey when that is enabled; it never overshoots); use it for an "
        "S-curve instead of curve points",
        ge=-100, le=100, default=0,
    )
    curve1: CurveSpec | None = F(
        "Curve", "Curve 1: points or linear", default={"type": "linear"}, curve=True
    )
    curve2: CurveSpec | None = F(
        "Curve2", "Curve 2: points or linear", default={"type": "linear"}, curve=True
    )


ShapeMode = Literal["add", "subtract", "intersect"]


class RectangleShape(BaseModel):
    """A rectangle (an ellipse at roundness 100) in image coordinates."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["rectangle"]
    x: float | None = Field(
        None, ge=-100, le=100, description="Centre, -100 = left edge, 0 = image centre, 100 = right edge"
    )
    y: float | None = Field(
        None, ge=-100, le=100, description="Centre, -100 = top edge, 0 = image centre, 100 = bottom edge"
    )
    width: float | None = Field(None, ge=1, le=200, description="% of image width (100 = the image's)")
    height: float | None = Field(None, ge=1, le=200, description="% of image height (100 = the image's)")
    angle: float | None = Field(None, ge=-180, le=180, description="Rotation in degrees")
    roundness: float | None = Field(
        None, ge=0, le=100, description="0 = rectangle, 100 = ellipse"
    )
    feather: float | None = Field(None, ge=0, le=100, description="Edge softness")
    blur: float | None = Field(None, ge=0, le=500, description="Blur of this shape's edge")
    mode: ShapeMode | None = Field(None, description="How the shape combines with the shapes before it")


class GradientShape(BaseModel):
    """A linear gradient across the image."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["gradient"]
    x: float | None = Field(
        None, ge=-100, le=100, description="Position, -100 = left edge, 0 = image centre, 100 = right edge"
    )
    y: float | None = Field(
        None, ge=-100, le=100, description="Position, -100 = top edge, 0 = image centre, 100 = bottom edge"
    )
    strength_start: float | None = Field(None, ge=0, le=100, description="Mask strength where the gradient starts")
    strength_end: float | None = Field(None, ge=0, le=100, description="Mask strength where the gradient ends")
    angle: float | None = Field(None, ge=-180, le=180, description="Direction in degrees")
    feather: float | None = Field(None, ge=0, le=100, description="Width of the transition")
    blur: float | None = Field(None, ge=0, le=500, description="Blur of the gradient")
    mode: ShapeMode | None = Field(None, description="How the shape combines with the shapes before it")


MaskShape = Annotated[RectangleShape | GradientShape, Field(discriminator="type")]


class AreaMaskAdjustment(BaseModel):
    """An area mask: its shapes combined in order, then feathered, blurred and
    (inverted) flipped. Giving any mask field turns the mask on."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = Field(None, description="Turn the area mask on or off")
    inverted: bool | None = Field(
        None, description="Flip the mask: the region then affects everything outside the shapes"
    )
    feather: float | None = Field(None, ge=0, le=100, description="Feather of the whole mask")
    blur: float | None = Field(None, ge=0, le=500, description="Blur of the whole mask")
    shapes: list[MaskShape] | None = Field(
        None,
        description="Shapes by position: an entry edits the shape at its index (same type) or "
        "replaces it (other type); an index one past the end appends",
    )


class ChannelCdl(BaseModel):
    """One channel's slope, offset and power."""

    model_config = ConfigDict(extra="forbid")

    slope: float | None = Field(None, ge=0.01, le=10, description="Multiplier, applied first (1 = unchanged)")
    offset: float | None = Field(
        None, ge=-0.15, le=0.15, description="Added after the slope (stored halved: v*slope + offset/2)"
    )
    power: float | None = Field(
        None, ge=0.1, le=4, description="Stored as the inverse of the exponent applied: 0.5 squares the channel"
    )


class ColorCorrectionRegion(BaseModel):
    """One Color Correction region in RGB mode: per-channel slope, offset and
    power, optionally restricted by an area mask."""

    model_config = ConfigDict(extra="forbid")

    r: ChannelCdl | None = None
    g: ChannelCdl | None = None
    b: ChannelCdl | None = None
    mask: AreaMaskAdjustment | None = None


class ColorCorrection(BaseModel):
    """Color Correction (ASC CDL-like grading; cast removal, per-channel
    contrast, split toning, faded film), RGB-mode regions only; other modes,
    pivots, compression and non-area masks are raw edits. Values are linear
    working-space values (0..1 = 0..65535). Per channel the region applies
    `v = v*slope + offset/2`, then `v = (v/pivot)^(1/power)*pivot` (pivot 1
    unless raw-edited): the slope acts before the power, and the stored
    `power` is the inverse of the exponent applied (power 0.5 squares the
    channel), as ART's GUI shows it. `regions` is by position (region 1 =
    regions[0]); get_profile gives null for a region that is not typed (other
    mode or an unsupported mask), and a null in a request skips that position.
    Setting r, g or b on a region switches it to RGB mode, and setting
    anything turns the tool on (both listed under `implied`). An entry past
    the end appends a region (the error names the next free index); a new
    region and new mask shapes get every key ART writes, with its defaults
    for what is not given. Mask coordinates: the origin is the image centre;
    x, y are % of the image's width and height from it (-100..100), width,
    height are % of the image's (100 = the whole image). An inverted mask
    affects everything outside its shapes: an inverted ellipse of 110% with
    feather 60 spares the middle and grades toward the edges."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    regions: list[ColorCorrectionRegion | None] | None = Field(
        None,
        description="Regions by position; each sets r, g, b (slope, offset, power) and an area mask",
        json_schema_extra={"key": "<Key>_<region number>", "art_default": None},
    )


def F3(key: str, description: str, *, default: list[Any]) -> Any:
    """A curated field holding three numbers ``[r, g, b]`` (``rgb`` extra),
    each at least 0, stored as ``r;g;b``."""
    return Field(
        None, min_length=3, max_length=3, description=description,
        json_schema_extra={"key": key, "art_default": default, "rgb": True},
    )  # fmt: skip


class FilmNegative(BaseModel):
    """Film Negative: inverts a camera-scanned colour negative. Per channel
    `out = mult * in ^ exp`, clipped at 65535, with
    `exp = -(green_exponent * (red_ratio, 1, blue_ratio))` for (r, g, b) and
    `mult_c = ref_output_c / ref_input_c ^ exp_c`, so a pixel equal to
    `ref_input` comes out as `ref_output`. `in` is the negative's linear value
    (higher = a darker part of the scene), 0..65535, in the working space
    (`color_space` working) or the camera space (input); `sample_spots` reads
    it. Unset references (`ref_input` 0;0;0) make ART estimate them from the
    channel medians of the central 60% of the frame and map those to
    65535/24 (grey, about 4% of full scale): the default look, which depends
    on the image content. Fit `red_ratio`/`blue_ratio` from neutral spots;
    `ref_input` is a neutral's measured value, `ref_output` the level it gets
    (grey `L;L;L` = neutral at level L, about reflectance x 65535; unequal
    channels = a deliberate tint). When a request changes `ref_input` and
    gives no `ref_output`, the server sets `ref_output` = (L, L, L) so the
    image keeps its brightness (ART's own reference-picker rule; listed under
    `implied`): L is the Rec.709 luminance (0.2126729, 0.7151521, 0.0721750)
    of what the profile as it is now (before this request) renders the new
    `ref_input` as. If the current reference is unset, ART's medians are first
    estimated by sampling (a grid of 64 spots, a warning says so); where
    sampling is unavailable `ref_output` becomes grey 65535/24 and a warning
    says brightness may change. Legacy profiles (`BackCompat`, `RedBase`)
    stay raw: typed edits other than `enabled` are refused on them."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = F("Enabled", "Turn the tool on or off", default=False)
    color_space: Literal["working", "input"] | None = F(
        "ColorSpace",
        "Space the references and `sample_spots` values are in: working (stored 1) or the "
        "camera's input space (stored 0)",
        stored_as={"working": "1", "input": "0"}, default="working",
    )  # fmt: skip
    red_ratio: float | None = F(
        "RedRatio", "Red exponent / green exponent", ge=0.3, le=5, default=1.36
    )
    green_exponent: float | None = F(
        "GreenExponent", "Master exponent (the green channel's)", ge=0.3, le=4, default=1.5
    )
    blue_ratio: float | None = F(
        "BlueRatio", "Blue exponent / green exponent", ge=0.3, le=5, default=0.86
    )
    ref_input: list[Annotated[float, Field(ge=0)]] | None = F3(
        "RefInput",
        "[r, g, b] >= 0: the negative's linear value (0..65535) of the reference spot, "
        "in the negative's terms; [0, 0, 0] = unset (ART estimates it from channel medians)",
        default=[0.0, 0.0, 0.0],
    )
    ref_output: list[Annotated[float, Field(ge=0)]] | None = F3(
        "RefOutput",
        "[r, g, b] >= 0: the linear output (0..65535) the reference gets; grey [L, L, L] = "
        "neutral at level L, unequal = a deliberate tint; [0, 0, 0] = unset (65535/24 grey)",
        default=[0.0, 0.0, 0.0],
    )


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
        properties = model.model_json_schema()["properties"]
        fields: dict[str, FieldDescription] = {}
        for field, prop in properties.items():
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
