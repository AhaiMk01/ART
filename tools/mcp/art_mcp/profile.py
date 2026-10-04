"""The processing profile as agents see and change it (both servers).

Reads use one *read format*: curated tools typed under ``adjustments`` and
every other value as a raw string under ``raw`` (each value appears once).
Changes arrive as *adjustments* (typed, range-checked, see ``schema``) and/or
*raw edits* (single ``[Group] Key=value`` entries); both compile into one
partial profile.
"""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from art_mcp.keyfile import KeyFile
from art_mcp.schema import (
    PPVERSION,
    TOOLS,
    Adjustments,
    crop_bounds_problem,
    field_group,
    field_key,
    named_value,
    stored_value,
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


class RawEdit(BaseModel):
    group: str
    key: str
    value: str

    @property
    def name(self) -> str:
        return f"[{self.group}] {self.key}"


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

    def _compile(self, adjustments: Adjustments) -> tuple[list[RawEdit], list[RawEdit]]:
        """The (explicit, implied) edits an adjustments request amounts to."""
        explicit: list[RawEdit] = []
        implied: list[RawEdit] = []
        for name, (group, model) in TOOLS.items():
            tool = getattr(adjustments, name)
            if tool is None:
                continue
            values = tool.model_dump(exclude_none=True)
            if not values:
                continue
            explicit += [
                RawEdit(
                    group=field_group(model, f, group),
                    key=field_key(model, f),
                    value=stored_value(model, f, _arp_value(v)),
                )
                for f, v in values.items()
            ]
            own_group = any(field_group(model, f, group) == group for f in values)
            if "enabled" not in values and own_group and self._value(group, "Enabled") == "false":
                implied.append(RawEdit(group=group, key="Enabled", value="true"))
            if (
                name == "white_balance"
                and "setting" not in values
                and WB_CUSTOM_TEMP_FIELDS & values.keys()
                and self._value(group, "Setting") != "CustomTemp"
            ):
                implied.append(RawEdit(group=group, key="Setting", value="CustomTemp"))
        return explicit, implied

    def edit(self, adjustments: Adjustments | None, raw_edits: list[RawEdit]) -> EditOutcome:
        """Apply adjustments and raw edits together, all or nothing.

        Raw edits must name an existing group and key (a typo would otherwise
        do nothing in ART, silently); keys an adjustment sets are valid by
        definition (ART omits some, e.g. ``Equal`` at its default). A raw edit
        and an adjustment on the same key conflict, but a raw edit of a key an
        adjustment only *implies* wins."""
        unknown = [e for e in raw_edits if e.key not in self.profile.get(e.group, {})]
        if unknown:
            names = ", ".join(e.name for e in unknown)
            raise UnknownKey(f"not in this image's processing profile: {names}")
        explicit, implied = self._compile(adjustments) if adjustments else ([], [])
        raw_names = {e.name for e in raw_edits}
        clashes = [e.name for e in explicit if e.name in raw_names]
        if clashes:
            raise Conflict(
                f"set both as an adjustment and as a raw edit: {', '.join(clashes)}"
            )
        implied = [e for e in implied if e.name not in raw_names]

        edits = explicit + implied + raw_edits
        before = {(e.group, e.key): self._value(e.group, e.key) for e in edits}
        for e in edits:
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

        return EditOutcome(changed=changed_edits(edits), implied=changed_edits(implied))

    def apply(self, edits: list[RawEdit]) -> list[RawEdit]:
        """Apply raw ``edits`` only; returns the values that changed."""
        return self.edit(None, edits).changed

    def partial_profile(self) -> KeyFile:
        """Only the values the agent changed (and didn't change back)."""
        partial: KeyFile = {}
        for (group, key), loaded in self._loaded.items():
            if self.profile[group][key] != loaded:
                partial.setdefault(group, {})[key] = self.profile[group][key]
        return partial


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
        values: dict[str, Any] = {}
        for field, info in model.model_fields.items():
            key = field_key(model, field)
            field_grp = field_group(model, field, group)
            stored = profile.get(field_grp, {}).get(key)
            extra = info.json_schema_extra
            assert isinstance(extra, dict)
            if stored is None:
                values[field] = extra["art_default"]
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
    if any(v is None and c < 0 for v, c in zip(given, current)):
        return "the image has no crop rectangle yet: give x, y, w and h together"
    x, y, w, h = (v if v is not None else c for v, c in zip(given, current))
    frame_w, frame_h = frame()
    return crop_bounds_problem(x, y, w, h, frame_w=frame_w, frame_h=frame_h)


def edit_warnings(adjustments: Adjustments | None, profile: KeyFile) -> list[str]:
    """Warnings about an edit just applied to ``profile``: a newer profile
    version than the schema's, lens options that can't take effect."""
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
    return warnings


def ppversion_of(profile: KeyFile) -> int | None:
    version = profile.get(VERSION_GROUP, {}).get("Version")
    return int(version) if version and version.isdigit() else None


def read_format(profile: KeyFile) -> ProfileView:
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
