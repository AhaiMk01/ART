"""The typed ``film_negative`` adjustment: references as ``r;g;b`` lists, ART's
reference-picker rule and the estimate of ART's channel medians (spec
Appendix A).

Pure code: sampling is injected (a ``Sampler``), so nothing here runs art-cli
or talks to ART; the servers pass their own (Render: art-cli ``-x``, Live: the
channel's ``sample_spots`` op).

ART's maths (``src/engine/filmnegativeproc.cc``, ``doProcess``): per channel
``out = min(mult * in ^ exp, 65535)`` with ``exp = -(green_exponent * (red_ratio,
1, blue_ratio))`` and ``mult_c = ref_output_c / max(ref_input_c, 1) ^ exp_c``.
A reference whose green is <= 0 is unset: ``ref_input`` then comes from the
channel medians of the central 60% of the input (20% border cut) and
``ref_output`` is 65535/24 grey.
"""

import hashlib
import json
import math
import statistics
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from art_mcp.keyfile import KeyFile, unescape
from art_mcp.sampling import SpotSamples
from art_mcp.schema import AdjustmentError, Adjustments, FilmNegative, RawEdit

GROUP = "Film Negative"
MAXVALF = 65535.0
DEFAULT_OUTPUT = MAXVALF / 24.0
"""The grey ART maps the median estimate to when ``RefOutput`` is unset."""
LUMA = (0.2126729, 0.7151521, 0.0721750)
"""Rec.709 luminance weights, as ``Color::rgbLuminance`` in ART's picker."""
DEFAULTS = {"RedRatio": 1.36, "GreenExponent": 1.5, "BlueRatio": 0.86}

GRID = 8
"""The estimate samples a GRID x GRID grid (64 spots) of the central area."""
BORDER_PERCENT = 20
"""ART's median border cut (``getMedians(input, 20)``)."""
SPOT_SIZE = 64
SAMPLE_BATCH = 16
"""Spots per sampling run (``MAX_SPOTS``, the most one ``art-cli -x`` or channel request takes)."""

Triple = tuple[float, float, float]
Group = dict[str, str]


class SamplingUnsupported(Exception):
    """The ART in use can't sample spots (a release ``art-cli``)."""


Sampler = Callable[[list[tuple[int, int]], int, str], list[Triple]]
"""Given spots (frame pixels), their size and the space (``working`` or
``input``): each spot's average [r, g, b]. Raises ``SamplingUnsupported``."""


@dataclass(frozen=True)
class Estimate:
    """What sampling found for a request that needs ART's current medians."""

    medians: Triple | None
    """The estimated channel medians; None when they couldn't be sampled."""
    why: str | None = None
    """Why they couldn't (when ``medians`` is None)."""


def parse_triple(text: str | None) -> Triple | None:
    """``r;g;b`` (a trailing ``;`` is fine) as three numbers; None if absent
    or not three numbers."""
    if text is None:
        return None
    parts = [p for p in text.strip().split(";") if p != ""]
    if len(parts) != 3:
        return None
    try:
        r, g, b = (float(p) for p in parts)
    except ValueError:
        return None
    return r, g, b


def format_triple(values: list[float] | Triple) -> str:
    return ";".join(f"{v:.10g}" for v in values)


def profile_version(profile: KeyFile) -> int | None:
    """The stored ``[Version] Version``. ART treats a sidecar without one (or
    with an unreadable one) as current, so None means "no migration"."""
    text = (profile.get("Version") or {}).get("Version", "")
    return int(text) if text.isdigit() else None


def is_legacy(entries: Group, version: int | None = None) -> bool:
    """An active power-law profile whose references ART upgrades from V1/V2.
    Other methods retain this compatibility data inactive. Below Version 1039
    ART ignores RefInput/RefOutput/ColorSpace and converts the references."""
    if entries.get("Method") in ("density", "1", "namicolor", "2"):
        return False
    if version is not None and version < 1039:
        return True
    return entries.get("BackCompat", "0") not in ("0", "") or "RedBase" in entries


def _number(entries: Group, key: str) -> float:
    try:
        return float(entries[key])
    except (KeyError, ValueError):
        return DEFAULTS[key]


def _stored_triple(entries: Group, key: str) -> Triple:
    return parse_triple(entries.get(key)) or (0.0, 0.0, 0.0)


def exponents(entries: Group) -> Triple:
    """(rexp, gexp, bexp) of the stored settings."""
    green = _number(entries, "GreenExponent")
    return (
        -(green * _number(entries, "RedRatio")),
        -green,
        -(green * _number(entries, "BlueRatio")),
    )


def read_color_space(entries: Group) -> str:
    return "input" if entries.get("ColorSpace") == "0" else "working"


def read_cineon_lut_stage(profile: KeyFile) -> str:
    """The stored order, or ART's version-aware default for a missing key."""
    entries = profile.get(GROUP) or {}
    if "CineonLUTStage" in entries:
        return entries["CineonLUTStage"]
    version = profile.get("Version", {}).get("Version", "")
    if version.isdigit() and int(version) < 1056 and "CineonLUT" in entries:
        return "before_grade"
    return "after_grade"


def read_preserve_range(profile: KeyFile) -> str:
    """The stored flag, or ART's version-aware default for a missing key."""
    entries = profile.get(GROUP) or {}
    if "PreserveRange" in entries:
        return entries["PreserveRange"]
    version = profile.get("Version", {}).get("Version", "")
    return "false" if version.isdigit() and int(version) < 1057 else "true"


def read_cineon_reference_white(profile: KeyFile) -> str:
    """The stored W, or ART's version-aware default for a missing key."""
    entries = profile.get(GROUP) or {}
    if "CineonReferenceWhite" in entries:
        return entries["CineonReferenceWhite"]
    version = profile.get("Version", {}).get("Version", "")
    return "1" if version.isdigit() and int(version) < 1058 else "0.9"


def read_denoise_before_inversion(profile: KeyFile) -> str:
    """The stored flag, or ART's version-aware default for a missing key."""
    entries = profile.get(GROUP) or {}
    if "DenoiseBeforeInversion" in entries:
        return entries["DenoiseBeforeInversion"]
    version = profile.get("Version", {}).get("Version", "")
    return "false" if version.isdigit() and int(version) < 1059 else "true"


def read_fit_base_anchor(profile: KeyFile) -> str:
    """The stored anchor, or ART's version-aware default for a missing key."""
    entries = profile.get(GROUP) or {}
    if "NamiColorFitBaseAnchor" in entries:
        return entries["NamiColorFitBaseAnchor"]
    version = profile.get("Version", {}).get("Version", "")
    return "legacy" if version.isdigit() and int(version) < 1058 else "code95"


_DENSITY_FIELDS = (
    "film_type",
    "density_gamma",
    "density_dmax",
    "rgb_gains",
    "film_base_sample",
    "channel_gamma",
    "matrix_preset",
    "matrix",
    "matrix_basis",
    "calibration_note",
    "output_black_offset",
)
"""Fields whose keys ART reads only when the sidecar's Version is >= 1046."""


def film_version_edits(tool: FilmNegative, profile: KeyFile, mask_opt_in: bool) -> list[RawEdit]:
    """The implied edits of a film-negative request. [Version] is never raised:
    it decides how ART migrates every other tool. Keys ART only reads at a
    newer Version make the edit refuse instead, until ART has re-saved the
    sidecar."""
    entries = profile.get(GROUP) or {}
    version = profile_version(profile)
    if version is not None:
        resave = "open and re-save the sidecar in ART (which migrates it), then retry"
        gated = [f for f in _DENSITY_FIELDS if getattr(tool, f) is not None]
        if version < 1046 and gated:
            raise AdjustmentError(
                "out_of_range",
                f"film_negative: this sidecar is Version {version}; ART ignores "
                f"{', '.join(gated)} below Version 1046. {resave}",
            )
        if version < 1055 and mask_opt_in:
            raise AdjustmentError(
                "out_of_range",
                f"film_negative: this sidecar is Version {version}; ART resets a "
                f"NamiColor matrix preset to Identity below Version 1055. {resave}",
            )
        if (
            version < 1058
            and tool.namicolor_fit_base
            and tool.fit_base_anchor is None
            and "NamiColorFitBaseAnchor" not in entries
        ):
            raise AdjustmentError(
                "out_of_range",
                f"film_negative: this sidecar is Version {version}; ART reads namicolor_fit_base "
                f"as the legacy 93/1023 map below Version 1058, not the code 95 anchor. {resave}",
            )
    new_lut = (
        bool(tool.cineon_lut)
        and not entries.get("CineonLUT")
        and "CineonLUTStage" not in entries
        and tool.cineon_lut_stage is None
    )
    if (
        version is not None
        and version < 1054
        and bool(tool.cineon_lut)
        and not entries.get("CineonLUT")
        and _method_name(tool, entries) == "density"
        and (tool.color_space or read_color_space(entries)) == "input"
    ):
        raise AdjustmentError(
            "out_of_range",
            f"film_negative: this sidecar is Version {version}; ART would run a new print LUT "
            "in the legacy input domain for a density conversion in the input space. "
            "Open and re-save the sidecar in ART (which migrates it), then retry",
        )
    return [RawEdit(group=GROUP, key="CineonLUTStage", value="after_grade")] if new_lut else []


IDENTITY_MATRIX = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
STATUS_M_MATRIX = (
    1.0197,
    0.0317,
    0.0091,
    -0.0052,
    0.8933,
    0.0521,
    0.0131,
    -0.0011,
    0.9712,
)


def read_matrix_field(stored: str | None) -> list[float] | None:
    """Nine semicolon-separated coefficients, or None if the stored text
    is not nine finite numbers in -10..10."""
    if stored is None:
        return None
    parts = [p for p in stored.split(";") if p != ""]
    if len(parts) != 9:
        return None
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return None
    if any(not (-10.0 <= v <= 10.0) for v in values):
        return None
    return values


def _stored_name(stored: str | None, mapping: dict[str, str], default: str) -> str:
    """Text ids, plus the integer form written before they were stable."""
    if stored is None:
        return default
    return mapping.get(stored, stored)


_PRESET = {
    "0": "identity",
    "1": "status_m_reference",
    "2": "custom",
    "identity": "identity",
    "status_m_reference": "status_m_reference",
    "custom": "custom",
}
_METHOD = {
    "0": "power_law",
    "1": "density",
    "2": "namicolor",
    "power_law": "power_law",
    "density": "density",
    "namicolor": "namicolor",
}
_FILM_TYPE = {
    "0": "negative",
    "1": "reversal",
    "negative": "negative",
    "reversal": "reversal",
}
_TARGET = {
    "0": "linear",
    "1": "paper",
    "2": "cineon",
    "linear": "linear",
    "paper": "paper",
    "cineon": "cineon",
}


def _preset_name(tool: FilmNegative, entries: Group | None) -> str:
    if tool.matrix_preset is not None:
        return tool.matrix_preset
    return _stored_name((entries or {}).get("MatrixPreset"), _PRESET, "identity")


def _method_name(tool: FilmNegative, entries: Group) -> str:
    return tool.method or _stored_name(entries.get("Method"), _METHOD, "power_law")


def check_namicolor(tool: FilmNegative, entries: Group | None) -> None:
    """Validate the complete effective NamiColor settings before any edit lands."""
    entries = entries or {}
    if _method_name(tool, entries) != "namicolor":
        return
    scalar_defaults = {
        "namicolor_input_gain": ("NamiColorInputGain", 1.0),
        "namicolor_master_gain": ("NamiColorMasterGain", 0.0),
        "namicolor_master_shift": ("NamiColorMasterShift", 0.0),
    }
    scalars: dict[str, float] = {}
    vectors: dict[str, list[float]] = {}
    try:
        for name, (key, default) in scalar_defaults.items():
            value = getattr(tool, name)
            scalars[name] = float(entries.get(key, default) if value is None else value)
        for name, key in (
            ("namicolor_black", "NamiColorBlack"),
            ("namicolor_gain", "NamiColorGain"),
            ("namicolor_shift", "NamiColorShift"),
        ):
            value = getattr(tool, name)
            if value is None:
                value = parse_triple(entries[key]) if key in entries else (0.0,) * 3
            if value is None:
                raise ValueError("invalid triple")
            vectors[name] = list(value)
    except (ValueError, TypeError):
        raise AdjustmentError("out_of_range", "film_negative: NamiColor settings must be finite numbers") from None
    if any(
        not math.isfinite(value)
        for value in list(scalars.values()) + [value for vector in vectors.values() for value in vector]
    ):
        raise AdjustmentError("out_of_range", "film_negative: NamiColor settings must be finite numbers")
    master = scalars["namicolor_master_gain"]
    if any(
        1.0 - gain - master + black <= 0.0
        for gain, black in zip(vectors["namicolor_gain"], vectors["namicolor_black"], strict=True)
    ):
        raise AdjustmentError(
            "out_of_range",
            "film_negative: every NamiColor denominator "
            "(1 - channel gain - master gain + channel black) must be positive",
        )


def check_matrix_coefficients(tool: FilmNegative, entries: Group | None) -> None:
    """Coefficient edits require Custom. Sending the preset's own coefficients
    is not a change and is dropped."""
    if tool.matrix is None:
        return
    preset = _preset_name(tool, entries)
    if preset == "custom":
        return
    expected = IDENTITY_MATRIX if preset == "identity" else STATUS_M_MATRIX
    if len(tool.matrix) == 9 and all(abs(a - b) <= 1e-9 for a, b in zip(tool.matrix, expected, strict=True)):
        tool.matrix = None
        return
    raise AdjustmentError(
        "out_of_range",
        "film_negative: matrix coefficients can be edited only when "
        "matrix_preset is custom; select custom or omit matrix",
    )


def check_namicolor_matrix_basis(tool: FilmNegative, profile: KeyFile) -> bool:
    """Validate the known binding fields; ART checks source identity and ICC content.
    Return whether this request intentionally opts in to the active mask."""
    entries = profile.get(GROUP) or {}
    if _method_name(tool, entries) != "namicolor" or _preset_name(tool, entries) == "identity":
        return False
    opted_in = any(
        getattr(tool, name) is not None
        for name in ("matrix_preset", "matrix", "matrix_basis")
    )
    version = profile.get("Version", {}).get("Version", "")
    if version.isdigit() and int(version) < 1055 and not opted_in:
        return False  # ART will migrate this old dormant preset to Identity.
    if _preset_name(tool, entries) == "custom":
        matrix = tool.matrix if tool.matrix is not None else read_matrix_field(entries.get("Matrix"))
        if matrix is None or len(matrix) != 9 or any(not math.isfinite(value) for value in matrix):
            raise AdjustmentError(
                "out_of_range",
                "film_negative: custom NamiColor matrix must be nine finite coefficients",
            )
    check_matrix_binding(tool, profile, entries)
    return opted_in


def check_matrix_binding(tool: FilmNegative, profile: KeyFile, entries: Group) -> None:
    """The effective matrix_basis must bind the matrix to the active processing
    basis, as ART's activeDensityMatrix requires (an empty one is refused)."""
    basis = tool.matrix_basis if tool.matrix_basis is not None else unescape(entries.get("MatrixBasis", ""))
    color_space = tool.color_space or read_color_space(entries)
    icm = profile.get("Color Management") or {}
    active = unescape(
        icm.get("InputProfile", "(cameraICC)") if color_space == "input" else icm.get("WorkingProfile", "Rec2020")
    )
    gamma = tool.input_gamma if tool.input_gamma is not None else _stored_float(entries, "InputGamma", 1.0)
    try:
        binding = json.loads(basis)
        valid = (
            isinstance(binding, dict)
            and binding.get("v") == 1
            and binding.get("color_space") == color_space
            and binding.get("profile") == active
            and isinstance(binding.get("input_gamma"), str)
            and math.isfinite(float(binding["input_gamma"]))
            and abs(float(binding["input_gamma"]) - gamma) <= 1e-6
            and isinstance(binding.get("source"), str)
            and bool(binding["source"])
        )
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid:
        raise AdjustmentError(
            "out_of_range",
            "film_negative: nonidentity matrix requires a matching matrix_basis "
            "(version, processing space, profile, input gamma and source); "
            "select Identity or provide the calibration binding",
        )


def stamp_lut_sha(tool: FilmNegative, profile: KeyFile) -> None:
    """Record the SHA-256 of a newly chosen print LUT, as ART's panel does when
    a LUT is picked. A request that names the stored LUT again keeps the stored
    hash, so ART can still detect a replaced file."""
    if not tool.cineon_lut or tool.cineon_lut_sha256 is not None:
        return
    entries = profile.get(GROUP) or {}
    if tool.cineon_lut == unescape(entries.get("CineonLUT", "")) and entries.get("CineonLUTSha256", ""):
        return
    try:
        data = Path(tool.cineon_lut).read_bytes()
    except OSError as error:
        raise AdjustmentError(
            "out_of_range",
            f"film_negative: cannot read cineon_lut {tool.cineon_lut} to record its SHA-256 "
            f"({error.strerror or error}); give an absolute path, or cineon_lut_sha256",
        ) from None
    tool.cineon_lut_sha256 = hashlib.sha256(data).hexdigest()


def check_density_bindings(tool: FilmNegative, profile: KeyFile) -> None:
    """Fail closed for the density method as ART does at render time: a
    non-identity matrix needs its calibration binding and a print LUT needs
    its SHA-256."""
    entries = profile.get(GROUP) or {}
    if _method_name(tool, entries) != "density":
        return
    version = profile_version(profile)
    if (version is None or version >= 1046) and _preset_name(tool, entries) != "identity":
        check_matrix_binding(tool, profile, entries)
    lut = tool.cineon_lut if tool.cineon_lut is not None else entries.get("CineonLUT", "")
    sha = tool.cineon_lut_sha256 if tool.cineon_lut_sha256 is not None else entries.get("CineonLUTSha256", "")
    if lut and not sha:
        raise AdjustmentError(
            "out_of_range",
            "film_negative: cineon_lut requires cineon_lut_sha256 (the SHA-256 of the .cube bytes); "
            "ART refuses to render a print LUT without it",
        )


def check_legacy_lut_primaries(tool: FilmNegative, profile: KeyFile) -> None:
    """ART fails the render of the legacy input-space print LUT (density, input
    colour space, before_grade, LegacyInputLUT) when a LUT primaries map is set:
    the map would run on input-space pixels."""
    entries = profile.get(GROUP) or {}
    if _method_name(tool, entries) != "density":
        return
    if (tool.color_space or read_color_space(entries)) != "input":
        return
    if (tool.cineon_lut_stage or read_cineon_lut_stage(profile)) != "before_grade":
        return
    version = profile_version(profile)
    legacy = entries.get("LegacyInputLUT") == "true" or (
        "LegacyInputLUT" not in entries and version is not None and version < 1054 and bool(entries.get("CineonLUT"))
    )
    if not legacy:
        return
    lut = tool.cineon_lut if tool.cineon_lut is not None else entries.get("CineonLUT", "")
    if not lut:
        return  # primaries without a LUT do nothing
    for field, key in (
        ("cineon_lut_input_primaries", "CineonLUTInputPrimaries"),
        ("cineon_lut_output_primaries", "CineonLUTOutputPrimaries"),
    ):
        value = getattr(tool, field)
        if (value if value is not None else entries.get(key, "")):
            raise AdjustmentError(
                "out_of_range",
                f"film_negative: this profile runs its print LUT in the legacy input space "
                f"(density, input colour space, before_grade); ART refuses to render it with {field}. "
                "Clear the primaries, or use after_grade or the working colour space",
            )


def check_legacy(tool: FilmNegative, entries: Group | None, version: int | None = None) -> None:
    """Typed edits (other than ``enabled``) are refused on a legacy profile:
    ART would read the references through its V1/V2 conversion."""
    if entries is None or not is_legacy(entries, version):
        return
    if any(getattr(tool, f) is not None for f in FilmNegative.model_fields if f != "enabled"):
        raise AdjustmentError(
            "out_of_range",
            "film_negative: this profile has a legacy Film Negative "
            f"(BackCompat={entries.get('BackCompat', '?')}), which is raw-edit only "
            "(ART reads its references through a conversion); use raw_edits",
        )


def check_cineon_lut_excludes_paper(tool: FilmNegative, entries: Group | None) -> None:
    """A Cineon print LUT and a paper target cannot both be active."""
    entries = entries or {}
    if _method_name(tool, entries) == "namicolor":
        return  # NamiColor retains but never applies the density paper target.
    lut = tool.cineon_lut if tool.cineon_lut is not None else entries.get("CineonLUT", "")
    if tool.target_mode is not None:
        mode = tool.target_mode
    else:
        stored = entries.get("TargetMode")
        mode = _stored_name(stored, _TARGET, "linear")
    if lut and mode == "paper":
        raise AdjustmentError(
            "out_of_range",
            "film_negative: cineon_lut and target_mode paper are mutually exclusive; "
            "the paper curve is not applied when a Cineon print LUT is set",
        )


def check_paper_basis(tool: FilmNegative, entries: Group | None) -> None:
    """A paper basis is ``input|<profile>`` or ``working|<profile>``, or empty;
    ART refuses any other form when it renders a paper target."""
    if _method_name(tool, entries or {}) == "namicolor":
        return
    basis = tool.paper_basis
    if not basis:
        return
    space, bar, profile = basis.partition("|")
    if space in ("input", "working") and bar and profile:
        return
    raise AdjustmentError(
        "out_of_range",
        f"film_negative: paper_basis {basis!r} must be input|<profile> or "
        "working|<profile> (for example working|Rec2020), or empty",
    )


def _picker_applies(tool: FilmNegative, entries: Group) -> Triple | None:
    """The new ``ref_input`` when the picker rule applies: it is set, not the
    value already stored, and the request gives no ``ref_output``."""
    current_method = _stored_name(entries.get("Method"), _METHOD, "power_law")
    if current_method != "power_law" or _method_name(tool, entries) != "power_law":
        return None
    if tool.ref_input is None or tool.ref_output is not None:
        return None
    new = (tool.ref_input[0], tool.ref_input[1], tool.ref_input[2])
    if new[1] <= 0 or new == _stored_triple(entries, "RefInput"):
        return None
    return new


def estimate_space(tool: FilmNegative, entries: Group | None) -> str | None:
    """The space (``working``/``input``) to sample ART's current medians in,
    when this request needs them (the picker rule applies and the current
    ``ref_input`` is unset); else None. It is the profile's current
    ``ColorSpace``: the medians describe how it renders now."""
    entries = entries or {}
    if is_legacy(entries) or _picker_applies(tool, entries) is None:
        return None
    if _stored_triple(entries, "RefInput")[1] > 0:
        return None
    return read_color_space(entries)


def grid_spots(width: int, height: int) -> list[tuple[int, int]]:
    """GRID x GRID spot centres, one per equal cell of the frame minus ART's
    20% border cut."""
    x0 = width * BORDER_PERCENT // 100
    y0 = height * BORDER_PERCENT // 100
    cell_w = (width - 2 * x0) / GRID
    cell_h = (height - 2 * y0) / GRID
    return [(round(x0 + (i + 0.5) * cell_w), round(y0 + (j + 0.5) * cell_h)) for j in range(GRID) for i in range(GRID)]


def estimate_medians(sampler: Sampler, frame: tuple[int, int], space: str) -> Triple:
    """ART's channel medians, estimated: the per-channel median of the
    averages of a grid of spots over the central 60% of the frame (median of
    block means, not of pixels). Raises ``SamplingUnsupported``."""
    spots = grid_spots(*frame)
    averages: list[Triple] = []
    for start in range(0, len(spots), SAMPLE_BATCH):
        averages += sampler(spots[start : start + SAMPLE_BATCH], SPOT_SIZE, space)
    r, g, b = (statistics.median(a[c] for a in averages) for c in range(3))
    return r, g, b


def current_estimate(
    tool: FilmNegative | None,
    entries: Group | None,
    frame: Callable[[], tuple[int, int] | None],
    sampler: Sampler,
) -> Estimate | None:
    """The estimate an edit needs (None when it needs none): samples through
    ``sampler``. ``frame()`` is the frame's size, asked only when needed
    (None: not known)."""
    space = estimate_space(tool, entries) if tool is not None else None
    if space is None:
        return None
    size = frame()
    if size is None:
        return Estimate(None, "ART hasn't reported the image's size yet")
    try:
        return Estimate(estimate_medians(sampler, size, space))
    except SamplingUnsupported as e:
        return Estimate(None, str(e))


def estimate_for(
    adjustments: Adjustments | None,
    profile: KeyFile,
    frame: Callable[[], tuple[int, int] | None],
    fetch: Callable[[list[tuple[int, int]], int, str], SpotSamples],
) -> Estimate | None:
    """ART's current Film Negative medians for an edit that needs them (None
    when it needs none), sampled through ``fetch(points, size, space)``, which
    returns the spots' samples and raises ``SamplingUnsupported`` itself."""
    tool = adjustments.film_negative if adjustments is not None else None

    def sampler(spots: list[tuple[int, int]], size: int, space: str) -> list[Triple]:
        return [(v.avg[0], v.avg[1], v.avg[2]) for v in fetch(spots, size, space).spots]

    return current_estimate(tool, profile.get(GROUP), frame, sampler)


def luminance(rgb: Triple) -> float:
    return LUMA[0] * rgb[0] + LUMA[1] * rgb[1] + LUMA[2] * rgb[2]


def rendered(entries: Group, reference: Triple, current_in: Triple, current_out: Triple) -> Triple:
    """What the stored exponents render ``reference`` as, given the current
    mapping ``current_in`` -> ``current_out``: ``mult_c * ref_c ^ exp_c``
    with ``mult_c = out_c / max(in_c, 1) ^ exp_c``, clipped at 65535."""
    exps = exponents(entries)
    out = []
    for c in range(3):
        mult = current_out[c] / max(current_in[c], 1.0) ** exps[c]
        out.append(min(mult * max(reference[c], 1.0) ** exps[c], MAXVALF))
    return out[0], out[1], out[2]


def _ref_output(value: Triple) -> RawEdit:
    return RawEdit(group=GROUP, key="RefOutput", value=format_triple(value))


def picker_edits(
    tool: FilmNegative, entries: Group | None, estimate: Estimate | None
) -> tuple[list[RawEdit], list[str]]:
    """ART's picker rule as implied edits: the ``RefOutput`` (and warnings)
    that keep the image's brightness when ``ref_input`` changes without a
    ``ref_output``. ``L`` is the Rec.709 luminance of what the profile *as it
    is before this request* (its exponents, ``RefInput``, ``RefOutput``)
    renders the new ``ref_input`` as, clipped like ART's output; the new
    reference is then mapped to grey ``L;L;L`` whatever exponents this
    request sets. With an unset current ``RefInput``, ART's medians (the
    ``estimate``) stand in for it and 65535/24 grey for an unset
    ``RefOutput``; without an estimate ``RefOutput`` becomes 65535/24 grey."""
    entries = entries or {}
    new = _picker_applies(tool, entries)
    if new is None or is_legacy(entries):
        return [], []
    current_in = _stored_triple(entries, "RefInput")
    stored_out = _stored_triple(entries, "RefOutput")
    current_out = stored_out if stored_out[1] > 0 else (DEFAULT_OUTPUT,) * 3
    warnings: list[str] = []
    if current_in[1] <= 0:
        if estimate is not None and estimate.medians is not None:
            current_in = estimate.medians
            warnings.append(
                "ref_input was unset (ART estimates it from the channel medians): the "
                "current brightness is judged from medians estimated by sampling "
                f"{GRID * GRID} spots over the central {100 - 2 * BORDER_PERCENT}% of the "
                f"frame (median of block means, not of pixels): "
                f"[{', '.join(f'{m:.0f}' for m in estimate.medians)}]; the new ref_output "
                "keeps the brightness only approximately"
            )
        else:
            why = estimate.why if estimate is not None and estimate.why else "sampling was not run"
            warnings.append(
                "ref_input was unset and ART's medians could not be estimated "
                f"({why}): ref_output is set to grey 65535/24 = {DEFAULT_OUTPUT:.1f}, so the "
                "image's brightness may change"
            )
            return [_ref_output((DEFAULT_OUTPUT,) * 3)], warnings
    level = luminance(rendered(entries, new, current_in, current_out))
    return [_ref_output((level,) * 3)], warnings


def read_triple_field(stored: str | None, allow_negative: bool = False) -> list[float] | None:
    """A ``RefInput``/``RefOutput``/triple value as typed, None if it isn't three
    numbers (it then stays raw; if not allow_negative, each number must be >= 0)."""
    triple = parse_triple(stored)
    if triple is None:
        return None
    if not allow_negative and any(v < 0 for v in triple):
        return None
    return list(triple)


BASE_TARGET_DENSITY = 4.0
"""Rebate maps to linear 10^-4 before paper, LUT, and black offset."""
_RAW_SUFFIXES = {
    ".3fr",
    ".arw",
    ".arq",
    ".cr2",
    ".cr3",
    ".crf",
    ".crw",
    ".dcr",
    ".dng",
    ".fff",
    ".iiq",
    ".kdc",
    ".mef",
    ".mos",
    ".mrw",
    ".nef",
    ".nrw",
    ".orf",
    ".pef",
    ".raf",
    ".raw",
    ".rw2",
    ".rwl",
    ".rwz",
    ".sr2",
    ".srf",
    ".srw",
    ".x3f",
}


def path_is_raw(path: str) -> bool:
    """Whether ART would treat ``path`` as raw for the InputGamma override."""
    return Path(path).suffix.lower() in _RAW_SUFFIXES


def _f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", float(value)))[0]


def _stored_float(entries: Group, key: str, default: float) -> float:
    try:
        return float(entries[key])
    except (KeyError, ValueError):
        return default


def film_base_gains(
    sample: Triple,
    *,
    density_gamma: float,
    density_dmax: float,
    channel_gamma: Triple,
    matrix: tuple[float, ...],
    input_gamma: float,
) -> Triple:
    """``RGBGains = C - 4`` from a pre-inversion average. Raises
    ``AdjustmentError`` and returns nothing when any gain is unusable."""
    if any(not math.isfinite(v) or not v > 0 for v in sample):
        raise AdjustmentError(
            "out_of_range",
            "film_negative: film_base_sample is not a finite positive average",
        )
    p = _f32(0.7)
    dmax = _f32(density_dmax)
    dgamma = _f32(density_gamma)
    gamma = _f32(input_gamma)
    anchor = _f32(_f32(4.1) - dmax)
    scale = _f32(MAXVALF)
    slopes = tuple(_f32(v) for v in channel_gamma)
    coeffs = tuple(_f32(v) for v in matrix)
    if any(not math.isfinite(v) for v in coeffs + slopes + (dmax, dgamma, gamma)):
        raise AdjustmentError(
            "out_of_range",
            "film_negative: density settings for a film-base pick must be finite",
        )
    working = []
    for value in sample:
        norm = _f32(_f32(value) / scale)
        if gamma != _f32(1.0):
            sign = _f32(-1.0) if norm < 0 else _f32(1.0)
            norm = _f32(sign * math.pow(abs(norm), gamma))
        if not math.isfinite(norm):
            raise AdjustmentError(
                "out_of_range",
                "film_negative: film_base_sample is not a finite positive average",
            )
        tc = norm if norm > _f32(1e-10) else _f32(1e-10)
        dc = _f32(-math.log10(tc))
        ac = _f32(dmax - p - _f32(dgamma * _f32(dc - p)))
        if not math.isfinite(ac):
            raise AdjustmentError(
                "out_of_range",
                "film_negative: film_base_sample is not a finite positive average",
            )
        working.append(ac)
    mixed = []
    for row in range(3):
        total = _f32(0.0)
        for col in range(3):
            total = _f32(total + _f32(coeffs[row * 3 + col] * _f32(working[col] - anchor)))
        mixed.append(_f32(anchor + total))
    gains = []
    for channel in range(3):
        density = _f32(anchor + _f32(slopes[channel] * _f32(mixed[channel] - anchor)))
        gain = float(density) - BASE_TARGET_DENSITY
        if not math.isfinite(gain) or gain < -3.0 or gain > 3.0:
            raise AdjustmentError(
                "out_of_range",
                "film_negative: film-base pick would set a printer-light gain outside -3..3; no gains were changed",
            )
        gains.append(gain)
    return gains[0], gains[1], gains[2]


def film_base_edits(tool: FilmNegative, profile: KeyFile, raw_source: bool | None) -> list[RawEdit]:
    """``RGBGains`` for a density rebate sample. Refuses the edit when the
    pick cannot replace all three gains."""
    sample = tool.film_base_sample
    if sample is None:
        return []
    if tool.rgb_gains is not None:
        raise AdjustmentError(
            "out_of_range",
            "film_negative: set film_base_sample or rgb_gains, not both",
        )
    entries = profile.get(GROUP) or {}
    method = tool.method
    if method is None:
        method = _stored_name(entries.get("Method"), _METHOD, "power_law")
    film_type = tool.film_type
    if film_type is None:
        film_type = _stored_name(entries.get("FilmType"), _FILM_TYPE, "negative")
    if method != "density":
        raise AdjustmentError(
            "out_of_range",
            "film_negative: film_base_sample applies only to the density method",
        )
    if film_type != "negative":
        raise AdjustmentError(
            "out_of_range",
            "film_negative: the film-base picker is disabled for reversal",
        )
    preset = _preset_name(tool, entries)
    if preset == "identity":
        matrix = IDENTITY_MATRIX
    elif preset == "status_m_reference":
        matrix = STATUS_M_MATRIX
    else:
        stored = tool.matrix if tool.matrix is not None else read_matrix_field(entries.get("Matrix"))
        if stored is None:
            raise AdjustmentError(
                "out_of_range",
                "film_negative: custom density matrix is missing or not nine finite coefficients",
            )
        matrix = tuple(stored)
    if preset != "identity":
        check_matrix_binding(tool, profile, entries)
    input_gamma = tool.input_gamma if tool.input_gamma is not None else _stored_float(entries, "InputGamma", 1.0)
    icm = profile.get("Color Management") or {}
    applied_gamma = 1.0
    if input_gamma != 1.0:
        # ART's resolveInputGamma: only an unprofiled non-raw scan may carry one.
        if icm.get("InputProfile", "(cameraICC)") != "(none)":
            raise AdjustmentError(
                "out_of_range",
                "film_negative: input_gamma is not 1 on a profiled or raw source; "
                "ART refuses to render it, so no film-base gains were picked",
            )
        if raw_source is None:
            raise AdjustmentError(
                "out_of_range",
                "film_negative: InputGamma is not 1 on an unprofiled scan, and "
                "this edit did not say whether the file is raw",
            )
        if raw_source:
            raise AdjustmentError(
                "out_of_range",
                "film_negative: input_gamma is not 1 on a raw source; ART refuses to render it",
            )
        applied_gamma = input_gamma
    if tool.channel_gamma is not None:
        channel = tool.channel_gamma
    elif entries.get("ChannelGamma") is None:
        channel = [1.0, 1.0, 1.0]
    else:
        channel = list(_stored_triple(entries, "ChannelGamma"))
    gains = film_base_gains(
        (sample[0], sample[1], sample[2]),
        density_gamma=(
            tool.density_gamma if tool.density_gamma is not None else _stored_float(entries, "DensityGamma", 1.0)
        ),
        density_dmax=(
            tool.density_dmax if tool.density_dmax is not None else _stored_float(entries, "DensityDmax", 2.5)
        ),
        channel_gamma=(channel[0], channel[1], channel[2]),
        matrix=matrix,
        input_gamma=applied_gamma,
    )
    return [RawEdit(group=GROUP, key="RGBGains", value=format_triple(gains))]
