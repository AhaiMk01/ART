"""The processing profile as agents see and change it (both servers).

Reads use one *read format*: curated tools typed under ``adjustments`` (none
yet) and every other value as a raw string under ``raw``. Changes arrive as
*raw edits*: single ``[Group] Key=value`` entries.
"""

from typing import Any

from pydantic import BaseModel

from art_mcp.keyfile import KeyFile

VERSION_GROUP = "Version"


class ProfileView(BaseModel):
    ppversion: int | None
    """ART's processing-profile version the values are written for."""
    adjustments: dict[str, dict[str, Any]]
    """Curated tools, typed."""
    raw: dict[str, dict[str, str]]
    """Every other [Group] -> Key -> value, as stored in the .arp."""


class RawEdit(BaseModel):
    group: str
    key: str
    value: str

    @property
    def name(self) -> str:
        return f"[{self.group}] {self.key}"


class UnknownKey(Exception):
    """A raw edit names a group or key the processing profile doesn't have."""


class WorkingChanges:
    """A complete processing profile plus a record of which values the agent
    changed since it was loaded: the partial profile those changes make."""

    def __init__(self, profile: KeyFile) -> None:
        self.profile = profile
        self._loaded: dict[tuple[str, str], str] = {}
        """Value at load time of every key an edit has touched."""

    def apply(self, edits: list[RawEdit]) -> list[RawEdit]:
        """Apply ``edits`` in order, all or nothing, and return the values that
        differ from before this call (final value, once per key). Every group
        and key must already exist: a typo would otherwise do nothing in ART,
        silently."""
        unknown = [e for e in edits if e.key not in self.profile.get(e.group, {})]
        if unknown:
            names = ", ".join(e.name for e in unknown)
            raise UnknownKey(f"not in this image's processing profile: {names}")
        before = {(e.group, e.key): self.profile[e.group][e.key] for e in edits}
        for e in edits:
            self._loaded.setdefault((e.group, e.key), self.profile[e.group][e.key])
            self.profile[e.group][e.key] = e.value
        return [
            RawEdit(group=group, key=key, value=self.profile[group][key])
            for (group, key), value in before.items()
            if self.profile[group][key] != value
        ]

    def partial_profile(self) -> KeyFile:
        """Only the values the agent changed (and didn't change back)."""
        partial: KeyFile = {}
        for (group, key), loaded in self._loaded.items():
            if self.profile[group][key] != loaded:
                partial.setdefault(group, {})[key] = self.profile[group][key]
        return partial


def read_format(profile: KeyFile) -> ProfileView:
    version = profile.get(VERSION_GROUP, {}).get("Version")
    return ProfileView(
        ppversion=int(version) if version and version.isdigit() else None,
        adjustments={},
        raw={g: dict(entries) for g, entries in profile.items() if g != VERSION_GROUP},
    )
