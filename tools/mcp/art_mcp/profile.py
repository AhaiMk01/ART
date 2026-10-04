"""The processing profile as agents see and change it (both servers).

Reads use one *read format*: curated tools typed under ``adjustments`` and
every other value as a raw string under ``raw`` (each value appears once).
Changes arrive as *adjustments* (typed, range-checked, see ``schema``) and/or
*raw edits* (single ``[Group] Key=value`` entries); both compile into one
partial profile.
"""

from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from art_mcp.keyfile import KeyFile
from art_mcp.schema import PPVERSION, TOOLS, Adjustments, field_key

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
                RawEdit(group=group, key=field_key(model, f), value=_arp_value(v))
                for f, v in values.items()
            ]
            if "enabled" not in values and self._value(group, "Enabled") == "false":
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
            extra = info.json_schema_extra
            assert isinstance(extra, dict)
            if key not in entries:
                values[field] = extra["art_default"]
                continue
            try:
                values[field] = TypeAdapter(info.annotation).validate_python(entries[key])
            except ValidationError:
                continue
            consumed.add((group, key))
        typed[name] = values
    return typed, consumed


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
