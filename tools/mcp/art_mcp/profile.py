"""The processing profile as agents see and change it (both servers).

Reads use one *read format*: curated tools typed under ``adjustments`` and
every other value as a raw string under ``raw`` (each value appears once).
Changes arrive as *adjustments* (typed, range-checked, see ``schema``) and/or
*raw edits* (single ``[Group] Key=value`` entries); both compile into one
partial profile.
"""

from collections.abc import Callable
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    RootModel,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    ValidationError,
    model_serializer,
)

from art_mcp.colorcorrection import GROUP as CC_GROUP
from art_mcp.colorcorrection import Created, is_region_key, read_color_correction
from art_mcp.colorcorrection import compile_edits as compile_color_correction
from art_mcp.curves import LinearCurve, PointCurve, curve_warnings, decode, drawn_points, encode
from art_mcp.filmnegative import GROUP as FILM_GROUP
from art_mcp.filmnegative import (
    Estimate,
    check_legacy,
    format_triple,
    is_legacy,
    parse_triple,
    picker_edits,
    read_triple_field,
)
from art_mcp.keyfile import KeyFile
from art_mcp.schema import (
    PPVERSION,
    TOOLS,
    Adjustments,
    RawEdit,
    art_default,
    crop_bounds_problem,
    field_group,
    field_key,
    named_value,
    stored_value,
    tool_groups,
)
from art_mcp.schema import Crop as CropAdjustment

VERSION_GROUP = "Version"


def version_warnings(ppversion: int | None) -> list[str]:
    """Warn when ART's profile version is newer than the schema's."""
    if ppversion is not None and ppversion > PPVERSION:
        return [
            f"this ART writes processing-profile version {ppversion}, newer than the "
            f"{PPVERSION} the adjustment schema was written for; adjustment ranges "
            "or fields may be out of date (edits keep working)"
        ]
    return []


class ProfileView(BaseModel):
    ppversion: int | None
    """ART's processing-profile version the values are written for."""
    adjustments: dict[str, dict[str, Any]]
    """Curated tools, typed."""
    raw: dict[str, dict[str, str]]
    """Every other [Group] -> Key -> value, as stored in the .arp."""
    warnings: list[str] = []


class UnknownKey(Exception):
    """A raw edit names a group or key the processing profile doesn't have."""


class Conflict(Exception):
    """An adjustment and a raw edit set the same key in one request."""


class EditOutcome(BaseModel):
    changed: list[RawEdit]
    """Every [Group] Key whose value the request changed, with its new value
    (re-setting a value is not a change)."""
    implied: list[RawEdit]
    """The changes in ``changed`` the agent didn't ask for: a disabled tool
    enabled because it was adjusted, White Balance switched to CustomTemp."""
    created: list[Created] = []
    """The regions and mask shapes the request created, each with the keys ART
    writes for it that the request set no value of: they are in the profile
    and the partial profile, but not in ``changed``."""
    warnings: list[str] = []
    """Notes on how the changes were computed (e.g. an estimated reference)."""


class EditResult(BaseModel):
    """What an ``edit_profile`` call reports: the change set, not the profile."""

    changed: dict[str, dict[str, str]]
    """The values this call changed that were asked for, as [Group] -> Key ->
    new value (re-setting a value is not a change)."""
    implied: dict[str, dict[str, str]]
    """The changes that were not asked for, in the same shape and not repeated
    in `changed`: a disabled tool enabled because it was adjusted, White
    Balance switched to CustomTemp, a computed film reference."""
    created: dict[str, list[str]] = {}
    """What this call created, as [Group] -> descriptions: a new Color
    Correction region (`region 2`) or mask shape (`region 2 mask shape 0`;
    regions count from 1, shapes from 0, as in the request's lists), each with
    how many of the keys ART writes for it were left at their defaults. Those
    keys are in the profile but not listed in `changed`, which has the ones
    the request set."""
    drawn: dict[str, list[list[float]]] = {}
    """For each tone curve this call set (`curve1`, `curve2`), the line ART's
    curve editor draws through it, as `get_profile` reads it back (nothing for
    a linear curve or a NURBS with 3+ points)."""
    warnings: list[str]
    profile: ProfileView | None = None
    """Only with `full`: the groups this call touched, as `get_profile` reads
    them after the change."""

    @model_serializer(mode="wrap")
    def _without_null_profile(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """The field is there only with `full`: leave it out rather than send
        `"profile": null` with every result."""
        data: dict[str, Any] = handler(self)
        if data.get("profile") is None:
            data.pop("profile", None)
        return data


MAX_EDIT_PATHS = 50
"""The most images one ``edit_profile`` call takes."""


class ImageEdit(BaseModel):
    """One image's part of an ``edit_profile`` call with `paths`."""

    path: str
    """The path as requested."""
    changed: int | None
    """How many of the values asked for this edit changed (as many as the
    single-image result lists in `changed`; 0: it had them all already); null
    when this image failed."""
    implied: dict[str, dict[str, str]] = {}
    """The changes that were not asked for, as in the single-image result."""
    warnings: list[str] = []
    error: str | None
    """`<code>: <message>` when this image failed; its profile is then
    untouched and the others still change."""


class EditBatch(BaseModel):
    """What an ``edit_profile`` call with `paths` reports: one entry per image,
    not each one's change set."""

    items: list[ImageEdit]
    """One per requested path, in request order."""
    failed: int


class EditOutput(RootModel[EditResult | EditBatch]):
    """The output schema of ``edit_profile``: a single image's ``EditResult``
    (with `path`) or an ``EditBatch`` (with `paths`). It is an object either
    way, which is what a tool's output schema must be."""

    model_config = ConfigDict(json_schema_extra={"type": "object"})


def edit_item(path: str, result: EditResult) -> ImageEdit:
    """``result``, the change set of the edit of ``path``, as its entry in an
    ``EditBatch``."""
    changed = sum(len(keys) for keys in result.changed.values())
    return ImageEdit(path=path, changed=changed, implied=result.implied, warnings=result.warnings, error=None)


def failed_edit(path: str, error: str) -> ImageEdit:
    """The entry of an image whose edit failed with ``error``."""
    return ImageEdit(path=path, changed=None, error=error)


def check_edit_targets(
    path: str | None, paths: list[str] | None, full: bool, error: Callable[[Any, str], Exception]
) -> list[str] | None:
    """The images an ``edit_profile`` call is for: ``paths``, or None for the
    one ``path``. Raises ``error("out_of_range", ...)`` unless exactly one of
    the two is given, ``paths`` holds 1 to ``MAX_EDIT_PATHS`` entries and
    ``full`` isn't asked of several images."""
    if path is not None and paths is not None:
        raise error("out_of_range", "give path or paths, not both")
    if path is None and paths is None:
        raise error("out_of_range", "give path or paths: one image or several")
    if paths is None:
        return None
    if full:
        raise error("out_of_range", "full is for one image: use path, not paths")
    if not paths:
        raise error("out_of_range", "paths is empty")
    if len(paths) > MAX_EDIT_PATHS:
        raise error("out_of_range", f"paths has {len(paths)} entries; the most one call takes is {MAX_EDIT_PATHS}")
    return paths


def _arp_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


WB_CUSTOM_TEMP_FIELDS = {"temperature", "green", "equal"}


class WorkingChanges:
    """A complete processing profile plus a record of which values the agent
    changed since it was loaded: the partial profile those changes make."""

    def __init__(self, profile: KeyFile) -> None:
        self.profile = profile
        self._loaded: dict[tuple[str, str], str | None] = {}
        """Value at load time (None: absent) of every key an edit has
        touched."""

    def _value(self, group: str, key: str) -> str | None:
        return self.profile.get(group, {}).get(key)

    def _disabled(self, group: str, model: type[BaseModel]) -> bool:
        """Whether the tool is off: its stored `Enabled`, or ART's default for
        it when the key is missing (as the read format reads it)."""
        if "enabled" not in model.model_fields:
            return False
        stored = self._value(group, "Enabled")
        if stored is None:
            return art_default(model, "enabled") is False
        return stored == "false"

    def _compile(
        self, adjustments: Adjustments, film_estimate: Estimate | None = None
    ) -> tuple[list[RawEdit], list[RawEdit], list[Created], list[str]]:
        """The (explicit, implied) edits an adjustments request amounts to,
        what it creates (with the keys ART gets at their defaults) and warnings
        about how they were computed."""
        explicit: list[RawEdit] = []
        implied: list[RawEdit] = []
        created: list[Created] = []
        warnings: list[str] = []
        for name, (group, model) in TOOLS.items():
            tool = getattr(adjustments, name)
            if tool is None:
                continue
            if name == "color_correction":
                cc_explicit, cc_implied, cc_created = compile_color_correction(tool, self.profile.get(group))
                explicit += cc_explicit
                implied += cc_implied
                created += cc_created
                continue
            values = {f: getattr(tool, f) for f in model.model_fields if getattr(tool, f) is not None}
            if not values:
                continue
            if name == "film_negative":
                check_legacy(tool, self.profile.get(group))
            for f, v in values.items():
                if isinstance(v, list):  # a reference: r;g;b
                    if parse_triple(self._value(group, field_key(model, f))) == tuple(v):
                        continue  # already that value: not a change
                    explicit.append(
                        RawEdit(group=group, key=field_key(model, f), value=format_triple(v))
                    )
                    continue
                edit = RawEdit(
                    group=field_group(model, f, group),
                    key=field_key(model, f),
                    value=encode(v)
                    if isinstance(v, (PointCurve, LinearCurve))
                    else stored_value(model, f, _arp_value(v)),
                )
                explicit.append(edit)
            own_group = any(field_group(model, f, group) == group for f in values)
            if "enabled" not in values and own_group and self._disabled(group, model):
                implied.append(RawEdit(group=group, key="Enabled", value="true"))
            if (
                name == "white_balance"
                and "setting" not in values
                and WB_CUSTOM_TEMP_FIELDS & values.keys()
                and self._value(group, "Setting") != "CustomTemp"
            ):
                implied.append(RawEdit(group=group, key="Setting", value="CustomTemp"))
            if name == "tone_curve":
                implied += self._tone_curve_implied(group, values)
            if name == "film_negative":
                picked, notes = picker_edits(tool, self.profile.get(group), film_estimate)
                implied += picked
                warnings += notes
        return explicit, implied, created, warnings

    def _tone_curve_implied(self, group: str, values: dict[str, Any]) -> list[RawEdit]:
        implied: list[RawEdit] = []
        if (
            ("curve1" in values or "curve2" in values)
            and "histogram_matching" not in values
            and self._value(group, "HistogramMatching") == "true"
        ):
            # ART would replace the curve by the histogram-matched one.
            implied.append(RawEdit(group=group, key="HistogramMatching", value="false"))
        mode2 = self._value(group, "CurveMode2")
        if "mode" in values and "mode2" not in values and mode2 not in (None, values["mode"]):
            # ART loads a CurveMode as both modes; keep the profile saying so.
            implied.append(RawEdit(group=group, key="CurveMode2", value=values["mode"]))
        return implied

    def edit(
        self,
        adjustments: Adjustments | None,
        raw_edits: list[RawEdit],
        film_estimate: Estimate | None = None,
    ) -> EditOutcome:
        """Apply adjustments and raw edits together, all or nothing.

        Raw edits must name an existing group and key (a typo would otherwise
        do nothing in ART, silently); keys an adjustment sets are valid by
        definition (ART omits some, e.g. ``Equal`` at its default). A raw edit
        and an adjustment on the same key conflict, but a raw edit of a key an
        adjustment only *implies* wins. ``film_estimate``: ART's current Film
        Negative medians as sampled, for a request that needs them
        (``filmnegative.current_estimate``)."""
        versioned = [e for e in raw_edits if e.group == VERSION_GROUP]
        if versioned:
            # Which ART version wrote the profile decides how ART migrates it.
            raise UnknownKey(f"{versioned[0].name} can't be edited")
        unknown = [e for e in raw_edits if e.key not in self.profile.get(e.group, {})]
        if unknown:
            names = ", ".join(e.name for e in unknown)
            raise UnknownKey(f"not in this image's processing profile: {names}")
        explicit, implied, created, warnings = (
            self._compile(adjustments, film_estimate) if adjustments else ([], [], [], [])
        )
        defaults = [e for c in created for e in c.defaults]
        raw_names = {e.name for e in raw_edits}
        clashes = [e.name for e in explicit + defaults if e.name in raw_names]
        if clashes:
            raise Conflict(
                f"set both as an adjustment and as a raw edit: {', '.join(clashes)}"
            )
        implied = [e for e in implied if e.name not in raw_names]

        edits = explicit + implied + raw_edits
        # What a created region or shape gets at ART's defaults goes in first,
        # under the edits: it is in the profile, not in the change set.
        before = {(e.group, e.key): self._value(e.group, e.key) for e in defaults + edits}
        for e in defaults + edits:
            self._loaded.setdefault((e.group, e.key), self._value(e.group, e.key))
            self.profile.setdefault(e.group, {})[e.key] = e.value

        def changed_edits(candidates: list[RawEdit]) -> list[RawEdit]:
            seen: set[tuple[str, str]] = set()
            out: list[RawEdit] = []
            for e in candidates:
                k = (e.group, e.key)
                final = self.profile[e.group][e.key]
                if k not in seen and final != before[k]:
                    seen.add(k)
                    out.append(RawEdit(group=e.group, key=e.key, value=final))
            return out

        if any(e.name == f"[{FILM_GROUP}] RefOutput" for e in raw_edits):
            warnings = []  # a raw RefOutput overrides the computed one
        return EditOutcome(
            changed=changed_edits(edits), implied=changed_edits(implied), created=created, warnings=warnings
        )

    def apply(self, edits: list[RawEdit]) -> list[RawEdit]:
        """Apply raw ``edits`` only; returns the values that changed."""
        return self.edit(None, edits).changed

    def layer(self, resolved: KeyFile) -> list[tuple[str, str]]:
        """Make ``resolved``, the complete profile art-cli built with a preset
        laid over this one, the working profile. Whatever it changes counts as
        the agent's change, like an edit's (so a save's merge and a partial
        profile include it); returns the ``(group, key)`` of each, in file
        order, leaving out ``[Version]``, which no edit sets. A key it lacks
        is dropped (ART replaces Color Correction regions wholesale)."""
        changed: list[tuple[str, str]] = []
        for group in [*resolved, *(g for g in self.profile if g not in resolved)]:
            old, new = self.profile.get(group, {}), resolved.get(group, {})
            for key in [*new, *(k for k in old if k not in new)]:
                if group != VERSION_GROUP and old.get(key) != new.get(key):
                    self._loaded.setdefault((group, key), old.get(key))
                    changed.append((group, key))
        self.profile = {group: dict(entries) for group, entries in resolved.items()}
        return changed

    def partial_profile(self) -> KeyFile:
        """Only the values the agent changed (and didn't change back)."""
        partial: KeyFile = {}
        regions_dropped = False
        for (group, key), loaded in self._loaded.items():
            current = self._value(group, key)
            if current == loaded:
                continue
            if current is None:
                # Dropped by a layered preset: a partial profile can't say so.
                regions_dropped = regions_dropped or (group == CC_GROUP and is_region_key(key))
                continue
            partial.setdefault(group, {})[key] = current
        return _with_whole_regions(partial, self.profile, force=regions_dropped)


def _with_whole_regions(partial: KeyFile, profile: KeyFile, force: bool = False) -> KeyFile:
    """``partial`` with every Color Correction region key of ``profile`` when it
    changes one (or ``force``: a region key was dropped): ART replaces all
    regions by the ones a profile lists, each from its own keys (defaults for
    the rest), so changing one region key sends every region whole."""
    changed = partial.get(CC_GROUP, {})
    if force or any(is_region_key(k) for k in changed):
        regions = {k: v for k, v in profile.get(CC_GROUP, {}).items() if is_region_key(k)}
        if regions:
            partial[CC_GROUP] = {**regions, **changed}
    return partial


def partial_vs_default(profile: KeyFile, default: KeyFile) -> KeyFile:
    """The values of ``profile`` that differ from ``default`` (ART's default
    profile for the image), whatever the profile was loaded from: a partial
    profile that describes the work in full relative to ART's default.

    Values are compared as the strings stored. A key equal to the default's is
    left out; so is one only the default has (a partial profile can't unset a
    key, and the target image's own value is its default anyway); a key only
    ``profile`` has counts as different. ``[Version]`` is never taken: it says
    which ART wrote the profile, and a partial profile without it is read as
    the current version, as the complete values it holds are."""
    partial: KeyFile = {}
    for group, entries in profile.items():
        if group == VERSION_GROUP:
            continue
        was = default.get(group, {})
        for key, value in entries.items():
            if was.get(key) != value:
                partial.setdefault(group, {})[key] = value
    return _with_whole_regions(partial, profile)


def split_exclusion(entry: str) -> tuple[str, str]:
    """The ``(group, key)`` of an exclusion entry, ``"Group"`` or
    ``"Group/Key"`` (key ``""`` for a whole group)."""
    group, _, key = entry.partition("/")
    return group, key


def check_exclusions(profile: KeyFile, exclude: list[str]) -> None:
    """``UnknownKey`` for an exclusion entry naming a group or key ``profile``
    (an image's complete processing profile) doesn't have."""
    for entry in exclude:
        group, key = split_exclusion(entry)
        if group not in profile or (key and key not in profile[group]):
            raise UnknownKey(f"exclude {entry!r}: not in this image's processing profile")


def drop_excluded(keys: KeyFile, exclude: list[str]) -> dict[str, int]:
    """Remove what the ``exclude`` entries name from ``keys`` (a partial
    profile, changed in place), and any group that is left without keys;
    returns, per entry, how many keys it dropped (0: ``keys`` had none of
    them)."""
    dropped: dict[str, int] = {}
    for entry in exclude:
        group, key = split_exclusion(entry)
        entries = keys.get(group, {})
        if key:
            count = 1 if entries.pop(key, None) is not None else 0
        else:
            count = len(entries)
            keys.pop(group, None)
        dropped[entry] = dropped.get(entry, 0) + count  # an entry given twice drops its keys once
    for group in [g for g, entries in keys.items() if not entries]:
        del keys[group]
    return dropped


def typed_adjustments(profile: KeyFile) -> tuple[dict[str, dict[str, Any]], set[tuple[str, str]]]:
    """Curated tools typed from the profile's strings, and the (group, key)
    pairs they consume. A tool whose group is absent is left out; a key absent
    from a present group reads as its ART default; a value that doesn't fit
    the schema (e.g. ``CustomMultLegacy``) is left out here, so it stays raw."""
    typed: dict[str, dict[str, Any]] = {}
    consumed: set[tuple[str, str]] = set()
    for name, (group, model) in TOOLS.items():
        entries = profile.get(group)
        if entries is None:
            continue
        if name == "color_correction":
            typed[name], cc_consumed = read_color_correction(entries)
            consumed |= cc_consumed
            continue
        if name == "film_negative" and is_legacy(entries):
            continue  # legacy forms stay raw
        values: dict[str, Any] = {}
        for field, info in model.model_fields.items():
            key = field_key(model, field)
            field_grp = field_group(model, field, group)
            stored = profile.get(field_grp, {}).get(key)
            extra = info.json_schema_extra
            assert isinstance(extra, dict)
            if extra.get("rgb"):
                triple = read_triple_field(stored) if stored is not None else extra["art_default"]
                if triple is None:
                    continue
                values[field] = triple
                if stored is not None:
                    consumed.add((field_grp, key))
                continue
            if stored is None:
                source = extra.get("default_from")
                if source is None:
                    values[field] = extra["art_default"]
                elif source in values:
                    values[field] = values[source]
                continue
            if extra.get("curve"):
                curve = decode(stored)
                if curve is None:
                    continue  # parametric or unparseable: stays raw
                if curve["type"] != "linear":
                    curve["drawn"] = drawn_points(curve)
                values[field] = curve
                consumed.add((field_grp, key))
                continue
            try:
                values[field] = TypeAdapter(info.annotation).validate_python(
                    named_value(model, field, stored)
                )
            except ValidationError:
                continue
            consumed.add((field_grp, key))
        typed[name] = values
    return typed, consumed


def crop_rect(profile: KeyFile) -> tuple[int, int, int, int]:
    """The ``[Crop]`` X, Y, W, H; -1 for each that is unset or not a number
    (ART's "no geometry")."""

    def number(key: str) -> int:
        try:
            return int(profile.get("Crop", {}).get(key, "-1"))
        except ValueError:
            return -1

    x, y, w, h = (number(k) for k in ("X", "Y", "W", "H"))
    return x, y, w, h


def crop_problem(
    profile: KeyFile, crop: CropAdjustment, frame: Callable[[], tuple[int, int]]
) -> str | None:
    """Why a crop adjustment doesn't fit the image's frame (``frame()``: its
    width and height, asked only when needed), or None if it does. Fields not
    in the request keep the profile's values."""
    given = (crop.x, crop.y, crop.w, crop.h)
    if all(v is None for v in given):
        return None
    current = crop_rect(profile)
    if any(v is None and c < 0 for v, c in zip(given, current, strict=True)):
        return "the image has no crop rectangle yet: give x, y, w and h together"
    x, y, w, h = (v if v is not None else c for v, c in zip(given, current, strict=True))
    frame_w, frame_h = frame()
    return crop_bounds_problem(x, y, w, h, frame_w=frame_w, frame_h=frame_h)


def edit_warnings(adjustments: Adjustments | None, profile: KeyFile) -> list[str]:
    """Warnings about an edit just applied to ``profile``: a newer profile
    version than the schema's, lens options that can't take effect, tone
    curves whose drawn line clips or reverses."""
    warnings = version_warnings(ppversion_of(profile))
    if (
        adjustments is not None
        and adjustments.lens_profile is not None
        and profile.get("LensProfile", {}).get("LcMode", "none") == "none"
    ):
        warnings.append(
            "lens_profile options have no effect while lc_mode is none; "
            "set lc_mode to turn lens correction on"
        )
    tone = adjustments.tone_curve if adjustments is not None else None
    if tone is not None:
        for field in ("curve1", "curve2"):
            curve = getattr(tone, field)
            if curve is not None:
                warnings += curve_warnings(field, curve)
    return warnings


def _grouped(edits: list[RawEdit]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for e in edits:
        grouped.setdefault(e.group, {})[e.key] = e.value
    return grouped


def _created_text(created: list[Created]) -> dict[str, list[str]]:
    """``EditResult.created``: ``region 2 (80 keys at their defaults)``."""
    text: dict[str, list[str]] = {}
    for c in created:
        n = len(c.defaults)
        keys = "1 key at its default" if n == 1 else f"{n} keys at their defaults"
        text.setdefault(c.group, []).append(f"{c.what} ({keys})")
    return text


def drawn_readback(adjustments: Adjustments | None, profile: KeyFile) -> dict[str, list[list[float]]]:
    """The drawn line (``curves.drawn_points``) of each tone curve the request
    set, as the profile holds it now."""
    tone = adjustments.tone_curve if adjustments is not None else None
    if tone is None:
        return {}
    group, model = TOOLS["tone_curve"]
    drawn: dict[str, list[list[float]]] = {}
    for field in ("curve1", "curve2"):
        stored = profile.get(group, {}).get(field_key(model, field))
        curve = decode(stored) if getattr(tone, field) is not None and stored is not None else None
        points = drawn_points(curve) if curve is not None and curve["type"] != "linear" else None
        if points is not None:
            drawn[field] = points
    return drawn


def edit_result(
    outcome: EditOutcome,
    profile: KeyFile,
    adjustments: Adjustments | None,
    raw_edits: list[RawEdit],
    warnings: list[str],
    *,
    full: bool = False,
) -> EditResult:
    """The result of an edit just applied to ``profile``. ``full`` adds the
    groups the request touched (those it names and those it changed) in the
    read format."""
    implied = {e.name for e in outcome.implied}
    view = None
    if full:
        touched = {e.group for e in outcome.changed} | {e.group for e in raw_edits}
        for name, (group, model) in TOOLS.items():
            if adjustments is not None and getattr(adjustments, name) is not None:
                touched |= tool_groups(group, model)
        view = read_format(profile, groups=sorted(touched & profile.keys()))
    return EditResult(
        changed=_grouped([e for e in outcome.changed if e.name not in implied]),
        implied=_grouped(outcome.implied),
        created=_created_text(outcome.created),
        drawn=drawn_readback(adjustments, profile),
        warnings=warnings,
        profile=view,
    )


def ppversion_of(profile: KeyFile) -> int | None:
    version = profile.get(VERSION_GROUP, {}).get("Version")
    return int(version) if version and version.isdigit() else None


def check_groups(profile: KeyFile, groups: list[str]) -> None:
    """``UnknownKey`` naming the valid groups when ``groups`` has one the
    profile lacks."""
    valid = sorted(g for g in profile if g != VERSION_GROUP)
    unknown = [g for g in groups if g not in valid]
    if unknown:
        raise UnknownKey(
            f"not a group of this image's processing profile: {', '.join(unknown)}; "
            f"its groups: {', '.join(valid)}"
        )


def read_format(
    profile: KeyFile, groups: list[str] | None = None, default: KeyFile | None = None
) -> ProfileView:
    """The profile in the read format. ``groups``: only those ``[Group]``s
    (``check_groups``); a curated tool is in when any group its fields live in
    is. ``default``: only what differs from that profile (ART's default): the
    typed fields with another value, the raw keys with another value or
    missing there."""
    if groups is not None:
        check_groups(profile, groups)
    view = _read_all(profile)
    if default is not None:
        view = _differing(view, _read_all(default))
    if groups is not None:
        view = _only_groups(view, set(groups))
    return view


_MISSING = object()


def _differing(view: ProfileView, base: ProfileView) -> ProfileView:
    """``view`` without what ``base`` says the same."""
    adjustments: dict[str, dict[str, Any]] = {}
    for name, values in view.adjustments.items():
        was = base.adjustments.get(name, {})
        differ = {f: v for f, v in values.items() if was.get(f, _MISSING) != v}
        if differ:
            adjustments[name] = differ
    raw: dict[str, dict[str, str]] = {}
    for group, entries in view.raw.items():
        was_raw = base.raw.get(group, {})
        differ_raw = {k: v for k, v in entries.items() if was_raw.get(k, _MISSING) != v}
        if differ_raw:
            raw[group] = differ_raw
    return view.model_copy(update={"adjustments": adjustments, "raw": raw})


def _only_groups(view: ProfileView, groups: set[str]) -> ProfileView:
    adjustments = {
        name: values
        for name, values in view.adjustments.items()
        if groups & tool_groups(*TOOLS[name])
    }
    raw = {group: entries for group, entries in view.raw.items() if group in groups}
    return view.model_copy(update={"adjustments": adjustments, "raw": raw})


def _read_all(profile: KeyFile) -> ProfileView:
    ppversion = ppversion_of(profile)
    typed, consumed = typed_adjustments(profile)
    raw: dict[str, dict[str, str]] = {}
    for group, entries in profile.items():
        if group == VERSION_GROUP:
            continue
        left = {k: v for k, v in entries.items() if (group, k) not in consumed}
        if left or not entries:
            raw[group] = left
    return ProfileView(
        ppversion=ppversion,
        adjustments=typed,
        raw=raw,
        warnings=version_warnings(ppversion),
    )
