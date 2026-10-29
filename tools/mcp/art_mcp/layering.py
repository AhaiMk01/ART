"""Laying a partial profile over a complete one, key by key.

ART's loader can change keys a profile doesn't list when it loads a group:
an ``[Exposure]`` group without ``HLRecovery`` turns highlight recovery off,
whatever the profile it is loaded over had. So a preset is not handed to
art-cli as a layer of its own (``-p working -p preset``). Its keys are written
over the complete profile here, and art-cli loads that one complete file,
which keeps every key the preset doesn't name. This is what the fork's
``KeyFilePartialProfile::applyTo`` does for the editor (procparams.cc), down
to the film negative rule below.
"""

from art_mcp.colorcorrection import GROUP as COLOR_CORRECTION
from art_mcp.filmnegative import GROUP as FILM_NEGATIVE
from art_mcp.keyfile import KeyFile

FILM_OLD_KEYS = (
    "RedRatio", "GreenExponent", "BlueRatio", "RedBase", "GreenBase", "BlueBase",
    "RefInput", "RefOutput", "ColorSpace", "BackCompat",
)  # fmt: skip
"""Film Negative keys of the processing methods before ``Method`` existed
(``kFilmNegativeOldKeys`` in procparams.cc)."""
FILM_METHOD_VERSION = 1046
"""The profile version that introduced ``[Film Negative] Method``."""


def overlay(base: KeyFile, *layers: KeyFile) -> KeyFile:
    """``base`` (a complete profile) with each of ``layers`` laid over it in
    turn: a layer's keys win, every other key of ``base`` stays. ``base`` is
    not changed."""
    merged = {group: dict(entries) for group, entries in base.items()}
    for layer in layers:
        for group, entries in layer.items():
            if group == COLOR_CORRECTION:
                # ART replaces every region by the ones a profile lists: merged
                # key by key, base regions the layer dropped would stay.
                merged[group] = dict(entries)
            else:
                merged.setdefault(group, {}).update(entries)
        if film_method_missing(layer):
            merged.setdefault(FILM_NEGATIVE, {})["Method"] = "power_law"
    return merged


def film_method_missing(layer: KeyFile) -> bool:
    """Whether ``layer`` is a pre-``Method`` (or versionless) partial that
    still carries old Film Negative keys: ART reads it as power_law, which the
    base's own ``Method`` must not override
    (``filmNegativeMissingMethodSelectsPowerLaw``)."""
    film = layer.get(FILM_NEGATIVE, {})
    if "Method" in film or not any(key in film for key in FILM_OLD_KEYS):
        return False
    version = layer.get("Version", {}).get("Version")
    try:
        return version is None or int(version) < FILM_METHOD_VERSION
    except ValueError:
        return True
