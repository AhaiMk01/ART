# ART

ART is a raw image editor (a RawTherapee derivative). This fork adds MCP servers that let AI agents process and edit images with ART.

## Editing

**Processing profile**:
The complete set of adjustment values ART applies to one image, from raw decoding through output.
_Avoid_: Edit, preset, settings, params

**Partial profile**:
A processing profile that sets only some of its values; applied on top of another profile, leaving the rest unchanged.
_Avoid_: Delta, patch, preset

**Sidecar**:
The `.arp` file holding an image's processing profile, stored alongside the image.
_Avoid_: XMP, settings file

**Working profile**:
The Render server's unsaved copy of one image's processing profile, holding an agent's edits until they are saved to the sidecar or discarded.
_Avoid_: Draft, session profile, scratch profile

**Adjustment**:
A typed change to one curated tool's values (e.g. exposure, white balance), checked against that value's range and described by name, range and unit.
_Avoid_: Typed edit, setting, param change

**Raw edit**:
A change to a single `[Group] Key=value` entry of a processing profile, passed through as-is; only the group and key are checked to exist.
_Avoid_: Passthrough, key edit, patch

## MCP servers

**Render server**:
The MCP server that processes images headlessly, without a running ART window, and inspects a single image's metadata and processing profile.
_Avoid_: Headless server, batch server, CLI server

**Live server**:
The MCP server that controls a running ART editor, reading and changing the image currently open in it.
_Avoid_: GUI server, remote control, editor server

**Control channel**:
The local connection a running ART editor opens, when the user enables it, so the Live server can read and change the images open in it.
_Avoid_: IPC, remote API, bridge, socket
