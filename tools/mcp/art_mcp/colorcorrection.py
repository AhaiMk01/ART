"""The typed ``color_correction`` adjustment: regions in RGB mode with area
masks (spec Appendix A).

A region is a family of ``[ColorCorrection]`` keys ending in ``_<n>`` (region
n, from 1); an area-mask shape adds ``AreaMask<_i_>``-infixed keys (shape 0
has no infix, shape i>0 has ``_i_``). ART's loader reads regions and shapes
whole, with its defaults for any key that is missing, and *replaces* all
regions with what a profile or partial profile lists. So a new region or
shape is written with every key ART's saver writes (``REGION_DEFAULTS`` and
``SHAPE_DEFAULTS``, taken from ``ColorCorrectionParams::Region``/``Mask``
saving in ``src/engine/procparams.cc`` and a real default profile), and a
partial profile that changes any region key carries all region keys
(``WorkingChanges.partial_profile``, ``partial_vs_default``). The keys a
request doesn't set are not part of the edit's change set: ``Created`` counts
them (``EditResult.created``).
"""

import re
from typing import Any

from pydantic import BaseModel, ValidationError

from art_mcp.schema import (
    AdjustmentError,
    ColorCorrection,
    ColorCorrectionRegion,
    GradientShape,
    RawEdit,
    RectangleShape,
)

GROUP = "ColorCorrection"

REGION_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("Mode", "Jzazbz"),
    ("SlopeH", "0"), ("SlopeS", "0"), ("SlopeL", "0"),
    ("OffsetH", "0"), ("OffsetS", "0"), ("OffsetL", "0"),
    ("PowerH", "0"), ("PowerS", "0"), ("PowerL", "0"),
    ("SlopeR", "1"), ("OffsetR", "0"), ("PowerR", "1"), ("PivotR", "1"), ("CompressionR", "0"),
    ("SlopeG", "1"), ("OffsetG", "0"), ("PowerG", "1"), ("PivotG", "1"), ("CompressionG", "0"),
    ("SlopeB", "1"), ("OffsetB", "0"), ("PowerB", "1"), ("PivotB", "1"), ("CompressionB", "0"),
    ("A", "0"), ("B", "0"), ("ABScale", "1"), ("InSaturation", "0"), ("OutSaturation", "0"),
    ("Slope", "1"), ("Offset", "0"), ("Power", "1"), ("Pivot", "1"), ("Compression", "0"),
    ("RGBLuminance", "false"), ("HueShift", "0"), ("LUTFilename", ""), ("LUTParams", ""),
    ("HSLGamma", "2.3999999999999999"),
    ("MaskEnabled", "true"), ("MaskInverted", "false"), ("MaskName", ""), ("MaskCurve", "0;"),
    ("MaskPosterization", "0"), ("MaskSmoothing", "0"), ("MaskOpacity", "100"),
    ("ParametricMaskEnabled", "false"),
    ("HueMask", "1;0.16666666699999999;1;0.34999999999999998;0.34999999999999998;"
                "0.82877752459999998;1;0.34999999999999998;0.34999999999999998;"),
    ("ChromaticityMask", "1;0;1;0.34999999999999998;0.34999999999999998;1;1;"
                         "0.34999999999999998;0.34999999999999998;"),
    ("LightnessMask", "1;0;1;0.34999999999999998;0.34999999999999998;1;1;"
                      "0.34999999999999998;0.34999999999999998;"),
    ("LightnessMaskDetail", "0"), ("ContrastThresholdMask", "0"), ("ParametricMaskBlur", "0"),
    ("AreaMaskEnabled", "false"), ("AreaMaskFeather", "0"), ("AreaMaskBlur", "0"),
    ("AreaMaskContrast", "0;"),
    ("DeltaEMaskEnabled", "false"), ("DeltaEMaskL", "0"), ("DeltaEMaskC", "0"),
    ("DeltaEMaskH", "0"), ("DeltaEMaskRange", "1"), ("DeltaEMaskDecay", "1"),
    ("DeltaEMaskStrength", "100"), ("DeltaEMaskWeightL", "50"), ("DeltaEMaskWeightC", "75"),
    ("DeltaEMaskWeightH", "100"),
    ("DrawnMaskEnabled", "false"), ("DrawnMaskFeather", "0"), ("DrawnMaskOpacity", "1"),
    ("DrawnMaskSmoothness", "0"), ("DrawnMaskContrast", "0;"), ("DrawnMaskMode", "0"),
    ("DrawnMaskStrokes", ""),
    ("LinkedMaskEnabled", "false"), ("LinkedMaskInverted", "false"), ("LinkedMask", ""),
    ("ExternalMaskEnabled", "false"), ("ExternalMaskInverted", "false"),
    ("ExternalMaskFilename", ""), ("ExternalMaskFeather", "0"),
)  # fmt: skip
"""Every per-region key ART saves (without the ``_<n>`` suffix), with the
value of ART's default region: ``procparams.cc`` ``Region::Region()`` and
``Mask::Mask()``, as a real art-cli writes them."""

SHAPE_DEFAULTS: dict[str, tuple[tuple[str, str], ...]] = {
    "rectangle": (
        ("Type", "rectangle"), ("X", "0"), ("Y", "0"), ("Width", "100"), ("Height", "100"),
        ("Angle", "0"), ("Roundness", "0"), ("Mode", "add"), ("ShapeFeather", "0"), ("ShapeBlur", "0"),
    ),
    "gradient": (
        ("Type", "gradient"), ("X", "0"), ("Y", "0"), ("StrengthStart", "100"), ("StrengthEnd", "0"),
        ("Angle", "0"), ("Mode", "add"), ("ShapeFeather", "25"), ("ShapeBlur", "0"),
    ),
}  # fmt: skip
"""Every key ART saves for an area-mask shape of each type (``Mask::save``),
with the defaults of ``AreaMask::Rectangle``/``Gradient``."""

SHAPE_KEYS = {
    "rectangle": {
        "x": "X", "y": "Y", "width": "Width", "height": "Height", "angle": "Angle",
        "roundness": "Roundness", "feather": "ShapeFeather", "blur": "ShapeBlur", "mode": "Mode",
    },
    "gradient": {
        "x": "X", "y": "Y", "strength_start": "StrengthStart", "strength_end": "StrengthEnd",
        "angle": "Angle", "feather": "ShapeFeather", "blur": "ShapeBlur", "mode": "Mode",
    },
}  # fmt: skip
"""Typed shape field -> key, per shape type."""

CHANNELS = {"r": "R", "g": "G", "b": "B"}
CDL = {"slope": "Slope", "offset": "Offset", "power": "Power"}
CDL_DEFAULTS = {"slope": 1.0, "offset": 0.0, "power": 1.0}

REGION_KEY = re.compile(r"_\d+$")


def is_region_key(key: str) -> bool:
    """Whether a ``[ColorCorrection]`` key belongs to a region (ends ``_<n>``)."""
    return REGION_KEY.search(key) is not None


Group = dict[str, str]


class Created(BaseModel):
    """A region or mask shape a typed edit created: ART's saver writes ~80 keys
    for a region, so the edit result counts those the request left at their
    defaults (``defaults``, written to the profile all the same) instead of
    listing them."""

    group: str
    what: str
    """What it is: ``region 2``, ``region 2 mask shape 0`` (a region's
    number is its position + 1, a shape's its position)."""
    defaults: list[RawEdit]
    """The keys ART writes for it that the request set no value of."""


def _shape_key(base: str, shape: int, region: int) -> str:
    infix = "" if shape == 0 else f"_{shape}_"
    return f"AreaMask{infix}{base}_{region}"


def region_count(group: Group) -> int:
    """How many regions the group lists: ART reads region n while any key
    ends ``_<n>``."""
    count = 0
    while any(key.endswith(f"_{count + 1}") for key in group):
        count += 1
    return count


def shape_count(group: Group, region: int) -> int:
    """How many area-mask shapes region ``region`` has (ART reads shape i
    while its ``Type`` key exists)."""
    count = 0
    while _shape_key("Type", count, region) in group:
        count += 1
    return count


def mask_problem(group: Group, region: int) -> str | None:
    """Why region ``region``'s mask can't be typed (names what it uses), or
    None if it is only an area mask of rectangles and gradients."""
    n = f"_{region}"
    if group.get(f"MaskEnabled{n}", "true") != "true":
        return "is turned off"
    for kind in ("ParametricMask", "DeltaEMask", "DrawnMask", "LinkedMask", "ExternalMask"):
        if group.get(f"{kind}Enabled{n}", "false") != "false":
            return f"uses a {kind.removesuffix('Mask').lower()} mask"
    for key, default in (
        ("MaskCurve", "0;"), ("AreaMaskContrast", "0;"), ("MaskPosterization", "0"),
        ("MaskSmoothing", "0"), ("MaskOpacity", "100"),
    ):  # fmt: skip
        if group.get(f"{key}{n}", default) != default:
            return f"has a non-default {key}"
    for i in range(shape_count(group, region)):
        kind = group[_shape_key("Type", i, region)]
        if kind not in SHAPE_KEYS:
            return f"has a {kind} area shape"
    return None


# -- reading --------------------------------------------------------------


def _number(group: Group, key: str, default: float) -> float | None:
    """The key's value as a number, ``default`` if it is absent, None if it
    isn't one."""
    if key not in group:
        return default
    try:
        return float(group[key])
    except ValueError:
        return None


def _read_shape(group: Group, i: int, region: int) -> tuple[dict[str, Any], set[str]] | None:
    kind = group[_shape_key("Type", i, region)]
    defaults = dict(SHAPE_DEFAULTS[kind])
    shape: dict[str, Any] = {"type": kind}
    keys = {_shape_key("Type", i, region)}
    for field, base in SHAPE_KEYS[kind].items():
        key = _shape_key(base, i, region)
        keys.add(key)
        if field == "mode":
            shape[field] = group.get(key, defaults[base])
            continue
        value = _number(group, key, float(defaults[base]))
        if value is None:
            return None
        shape[field] = value
    return shape, keys


def _read_region(group: Group, n: int) -> tuple[dict[str, Any], set[str]] | None:
    """Region ``n`` typed and the keys that gave it, or None when it isn't
    typed: another mode, an unsupported mask, a value that doesn't fit."""
    if group.get(f"Mode_{n}") != "RGB" or mask_problem(group, n) is not None:
        return None
    keys = {f"Mode_{n}"}
    region: dict[str, Any] = {}
    for field, letter in CHANNELS.items():
        channel: dict[str, float] = {}
        for name, base in CDL.items():
            key = f"{base}{letter}_{n}"
            value = _number(group, key, CDL_DEFAULTS[name])
            if value is None:
                return None
            channel[name] = value
            keys.add(key)
        region[field] = channel
    inverted = group.get(f"MaskInverted_{n}", "false")
    enabled = group.get(f"AreaMaskEnabled_{n}", "false")
    feather = _number(group, f"AreaMaskFeather_{n}", 0.0)
    blur = _number(group, f"AreaMaskBlur_{n}", 0.0)
    if inverted not in ("true", "false") or enabled not in ("true", "false") or None in (feather, blur):
        return None
    keys |= {f"MaskInverted_{n}", f"AreaMaskEnabled_{n}", f"AreaMaskFeather_{n}", f"AreaMaskBlur_{n}"}
    shapes: list[dict[str, Any]] = []
    for i in range(shape_count(group, n)):
        read = _read_shape(group, i, n)
        if read is None:
            return None
        shapes.append(read[0])
        keys |= read[1]
    region["mask"] = {
        "enabled": enabled == "true", "inverted": inverted == "true",
        "feather": feather, "blur": blur, "shapes": shapes,
    }  # fmt: skip
    try:
        valid = ColorCorrectionRegion.model_validate(region)
    except ValidationError:
        return None  # e.g. a value outside the range ART's GUI allows
    return valid.model_dump(), keys


def read_color_correction(group: Group) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    """The tool typed from the profile's ``[ColorCorrection]`` group and the
    keys it consumed: ``regions`` has one entry per region, None for one that
    isn't typed (its keys stay raw)."""
    typed: dict[str, Any] = {"enabled": False}
    consumed: set[tuple[str, str]] = set()
    stored = group.get("Enabled")
    if stored in ("true", "false"):
        typed["enabled"] = stored == "true"
        consumed.add((GROUP, "Enabled"))
    elif stored is not None:
        del typed["enabled"]
    regions: list[dict[str, Any] | None] = []
    for n in range(1, region_count(group) + 1):
        read = _read_region(group, n)
        regions.append(read[0] if read else None)
        if read:
            consumed |= {(GROUP, key) for key in read[1]}
    typed["regions"] = regions
    return typed, consumed


# -- editing ----------------------------------------------------------------


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def _problem(where: str, message: str) -> AdjustmentError:
    return AdjustmentError("out_of_range", f"color_correction.{where}: {message}")


def _edit_shapes(
    mask_shapes: list[RectangleShape | GradientShape | None],
    group: Group,
    region: int,
    explicit: dict[str, str],
    filled: dict[str, str],
    created: list[tuple[str, list[str]]],
    existing: int,
    where: str,
) -> None:
    """Shapes by position into ``explicit``: an entry edits the shape at its
    index, replaces it when the type differs, or appends at the end (its keys
    at ART's defaults go to ``filled`` and the shape to ``created``). A gap is
    refused: ART stops reading shapes at the first one missing a key."""
    count = existing
    for j, shape in enumerate(mask_shapes):
        if shape is None:
            continue
        kind = shape.type
        if j > count:
            raise _problem(
                f"{where}.shapes.{j}",
                f"region {region}'s mask has {count} shape(s), so a new shape goes at index {count}",
            )
        if j == count or group.get(_shape_key("Type", j, region)) != kind:
            keys = {_shape_key(base, j, region): default for base, default in SHAPE_DEFAULTS[kind]}
            filled.update(keys)
            explicit[_shape_key("Type", j, region)] = kind
            created.append((f"region {region} mask shape {j}", list(keys)))
            count = max(count, j + 1)
        for field, base in SHAPE_KEYS[kind].items():
            value = getattr(shape, field)
            if value is not None:
                explicit[_shape_key(base, j, region)] = _text(value)


def compile_edits(
    cc: ColorCorrection, group: Group | None
) -> tuple[list[RawEdit], list[RawEdit], list[Created]]:
    """The edits of the ``[ColorCorrection]`` group a ``color_correction``
    request amounts to: (explicit, implied, created). A region past the end is
    appended with every key ART writes, and so is a new shape: the keys the
    request sets (and the implied ones) are in ``explicit`` and ``implied``,
    the rest, at ART's defaults, with the region or shape they complete in
    ``created``. Raises ``AdjustmentError`` for a position that would leave a
    gap or a mask edit on a mask that isn't typed."""
    current = group or {}
    explicit: dict[str, str] = {}
    implied: dict[str, str] = {}
    filled: dict[str, str] = {}
    created: list[tuple[str, list[str]]] = []
    regions = cc.regions or []
    count = region_count(current)
    for idx, region in enumerate(regions):
        if region is None:
            continue
        if idx > count:
            raise _problem(
                f"regions.{idx}",
                f"the profile has {count} region(s), so a new region goes at index {count}",
            )
        n = idx + 1
        new = idx == count
        if new:
            count += 1
            keys = {f"{base}_{n}": default for base, default in REGION_DEFAULTS}
            filled.update(keys)
            created.append((f"region {n}", list(keys)))
            explicit[f"Mode_{n}"] = "RGB"
        graded = False
        for field, letter in CHANNELS.items():
            channel = getattr(region, field)
            for name, base in CDL.items():
                value = getattr(channel, name) if channel is not None else None
                if value is not None:
                    explicit[f"{base}{letter}_{n}"] = _text(value)
                    graded = True
        if graded and not new and current.get(f"Mode_{n}") != "RGB":
            implied[f"Mode_{n}"] = "RGB"
        mask = region.mask
        if mask is None:
            continue
        if not new:
            why = mask_problem(current, n)
            if why is not None:
                raise _problem(
                    f"regions.{idx}.mask",
                    f"region {n}'s mask {why}, which a typed edit can't change; use raw edits",
                )
        for field, key in (("inverted", "MaskInverted"), ("feather", "AreaMaskFeather"), ("blur", "AreaMaskBlur")):
            value = getattr(mask, field)
            if value is not None:
                explicit[f"{key}_{n}"] = _text(value)
        if mask.enabled is not None:
            explicit[f"AreaMaskEnabled_{n}"] = _text(mask.enabled)
        else:
            implied[f"AreaMaskEnabled_{n}"] = "true"
        if mask.shapes:
            _edit_shapes(
                mask.shapes, current, n, explicit, filled, created, 0 if new else shape_count(current, n),
                f"regions.{idx}.mask",
            )
    touched = any(r is not None for r in regions)
    if cc.enabled is not None:
        explicit["Enabled"] = _text(cc.enabled)
    elif touched and current.get("Enabled") != "true":
        implied["Enabled"] = "true"

    def at_defaults(keys: list[str]) -> list[RawEdit]:
        """Of a created region's or shape's keys, those nothing else sets."""
        return [
            RawEdit(group=GROUP, key=k, value=filled[k]) for k in keys if k not in explicit and k not in implied
        ]

    return (
        [RawEdit(group=GROUP, key=k, value=v) for k, v in explicit.items()],
        [RawEdit(group=GROUP, key=k, value=v) for k, v in implied.items()],
        [Created(group=GROUP, what=what, defaults=at_defaults(keys)) for what, keys in created],
    )
