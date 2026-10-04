# ART MCP servers

Status: ready for implementation. Decided on the map
[ART MCP servers](https://github.com/AhaiMk01/ART/issues/1); every section
links the ticket that holds its reasoning. Vocabulary follows
[`GLOSSARY.md`](../../GLOSSARY.md): *processing profile*, *partial profile*,
*sidecar*, *working profile*, *adjustment*, *raw edit*, *Render server*,
*Live server*, *control channel*.

## 1. Overview

Two local stdio MCP servers let an AI agent (Claude Code, Claude Desktop) work
with ART:

- **Render server** (`art-mcp-render`, built first): opens images headlessly,
  edits a working profile, renders previews and exports through `art-cli`,
  inspects metadata, and saves sidecars on request. No ART window needed.
- **Live server** (`art-mcp-live`): reads and changes images open in a running
  ART editor through the control channel. Every change is one undoable History
  entry the user can see.

Both share one Python package, one adjustment schema, one profile read format
and one preview delivery scheme.

## 2. Implementation shape

From [Implementation language and SDK](https://github.com/AhaiMk01/ART/issues/7).

- **Language / SDK:** Python >= 3.11, official `mcp` SDK, pinned `mcp>=2,<3`
  (`MCPServer` from `mcp.server.mcpserver`). The stdio transport moves fd 0/1
  off the wire, so `art-cli` child output can't corrupt the protocol.
- **Location:** `tools/mcp/` in the fork, outside `src/` and CMake.
- **Package:** `art_mcp`, managed with `uv` (`pyproject.toml` + `uv.lock`).
  Shared modules (schema, profile I/O, preview files, metadata) plus two entry
  points: `art-mcp-render`, `art-mcp-live`. Clients see two separate servers.
- **.arp I/O:** a small custom GLib KeyFile reader/writer (`;`-separated lists,
  escapes); not `configparser`.
- **Results:** `structuredContent` with an `outputSchema` from Pydantic return
  models, plus a text copy for older clients.
- **Errors:** MCP `isError` with a short code and a message. Codes:
  `not_open`, `not_found`, `out_of_range`, `unknown_key`, `conflict`, `exists`,
  `render_failed`, `timeout` (art-cli or exiftool), `metadata_unavailable` (no
  exiftool beside ART-cli), `metadata_failed`, `invalid_tag`, `open_in_editor`,
  `art_not_running`.

```
tools/mcp/
  pyproject.toml, uv.lock
  art_mcp/
    schema.py       # curated adjustments (Pydantic), PPVERSION it targets
    keyfile.py      # GLib KeyFile (.arp) reader/writer
    profile.py      # read format, adjustments+raw edits -> partial profile
    preview.py      # temp folder, JPEG files, inline ImageContent
    metadata.py     # exiftool wrapper
    artdir.py       # locating ART-cli.exe / exiftool.exe / config dir
    render/         # Render server: art-cli runner, working profiles, tools
    live/           # Live server: control channel client, tools
  tests/
```

## 3. Profile surface (both servers)

From [Which processing profile values agents can change](https://github.com/AhaiMk01/ART/issues/6).

### 3.1 Two ways to change a profile

- **Adjustment:** typed, range-checked values of one curated tool, e.g.
  `{"exposure": {"compensation": 0.7}}`.
- **Raw edit:** `{"group": "...", "key": "...", "value": "..."}` for any
  `[Group] Key=value` in a processing profile.

Both compile into one partial profile. Rules:

- Raw edits: the group and key must exist in a complete processing profile
  (else `unknown_key`); values are passed unchecked.
- Out-of-range adjustment: rejected with `out_of_range`, message names the
  range. No clamping.
- An adjustment and a raw edit setting the same key in one request: rejected
  with `conflict`, naming the key. A raw edit of a key an adjustment only
  *implies* (e.g. `Enabled`) is not a conflict: the raw edit wins.
- An unknown curated tool or field: `unknown_key`. Any other bad adjustment
  value (wrong type, bad enum value): `out_of_range`.
- An adjustment on a disabled tool also enables it (White Balance: switches
  to `CustomTemp`); implied changes are listed in the result. See Appendix A.

### 3.2 Curated tools (v1)

Exposure, White Balance, Crop, Rotation, Local Contrast, Sharpening, Denoise
(basic amounts), Vignetting Correction, Lens Profile. Fields, ranges and units:
see [Appendix A](#appendix-a-curated-adjustment-schema).

All other tools (curves, equalizers, masks, Spot Removal, Film Negative,
Color Management, RAW settings) are reachable through raw edits only. Typed
shapes for them are a later, separate effort.

### 3.3 Schema

- Hand-written Pydantic models in `schema.py` (name, range, unit, one-line
  description per field). Ranges mirror ART's GUI `Adjuster` ranges; the
  engine defines ranges only for White Balance (`src/engine/colortemp.h`).
- Exposed in `edit_profile`'s input schema and returned by
  `describe_adjustments`.
- The schema records the `PPVERSION` it was written for (currently 1045, in
  `src/utils/ppversion.h`). If ART reports a newer one, results carry a
  warning; edits keep working.

### 3.4 Read format

`get_profile` returns JSON:

```json
{
  "ppversion": 1045,
  "adjustments": { "exposure": { "compensation": 0.0, "...": "..." }, "...": {} },
  "raw": { "ToneCurve": { "Enabled": "true", "Curve": "..." }, "...": {} },
  "warnings": []
}
```

Curated tools appear typed under `adjustments`; every other group/key appears
as strings under `raw`. Each value appears once. A value that doesn't fit the
schema (e.g. White Balance `CustomMultLegacy`) stays under `raw`. `warnings`
carries the `PPVERSION` warning (3.3).

## 4. Preview delivery (both servers)

From [How the Render server hands previews to Claude](https://github.com/AhaiMk01/ART/issues/12)
and [Render server tool list and signatures](https://github.com/AhaiMk01/ART/issues/9).

- **Default: file path.** The preview is a JPEG; the tool returns its path and
  Claude opens it with its file-reading tool when it wants to look.
- **Optional inline:** the result also carries base64 `ImageContent`. Set per
  call (`inline`), defaulting to the launch flag `--inline-previews`.
- **Size:** long edge 1024 px by default; `max_size` up to 2576 (Claude
  downscales anything larger). JPEG quality 85.
- **Fast export (Render server):** whole-image previews use `art-cli -f`
  (~2x faster; resizes before processing, so sharpening and local effects
  are approximated). `region` previews, exports, and previews with `max_size`
  above the user's fast-export box never use `-f`. The box is the smaller of
  `[Fast Export] fastexport_resize_width`/`fastexport_resize_height` in ART's
  `options` file (legacy `MaxWidth`/`MaxHeight`), default 1920.
- **Files:** unique file per render in `%TEMP%/art-mcp-<pid>/` (system temp on
  other OSes), so earlier previews stay viewable for comparison. Folder deleted
  on exit; stale folders of dead pids swept at startup.

## 5. Locating ART (both servers)

`--art-dir` flag or `ART_DIR` env (folder with `ART-cli.exe` and
`exiftool.exe`), else PATH, else the newest `C:\Program Files\ART\<version>`.
The Render server fails at startup if none is found; the Live server needs it
only for `inspect_image` and fails that tool alone.

## 6. Render server

### 6.1 Tools

From [Render server tool list and signatures](https://github.com/AhaiMk01/ART/issues/9).
Every image is named by its absolute, normalized path (resolved; case-folded
on Windows). Any tool except `open_image` on a path not opened returns
`not_open`.

| Tool | Args | Returns |
|---|---|---|
| `open_image` | `path` | Working profile loaded; metadata summary; ART version |
| `get_profile` | `path` | Read format (3.4) |
| `edit_profile` | `path`, `adjustments?`, `raw_edits?` | Keys changed |
| `reset_profile` | `path`, `to: "sidecar" \| "default"` | Working-profile changes discarded |
| `render_preview` | `path`, `max_size=1024`, `region?`, `inline?` | JPEG path (+ `ImageContent` if inline) |
| `export_image` | `path`, `output`, `format: "jpeg" \| "tiff" \| "png"`, `quality?` (jpeg only, 1..100), `bit_depth?` (jpeg `8`; png `8`\|`16`; tiff `8`\|`16`\|`16f`\|`32`), `write_profile=false`, `overwrite=false` | Output path, `.arp` path when written |
| `save_sidecar` | `path`, `on_conflict?: "merge" \| "overwrite" \| "cancel"` | `saved`, path, `how` (written/merged/overwritten/cancelled), or conflict + changed keys |
| `save_partial_profile` | `path`, `dest`, `overwrite=false` | `written`, path, keys written |
| `inspect_image` | `path`, `tags?` | Fixed metadata fields + requested tags |
| `describe_adjustments` | none | Curated schema + `PPVERSION` warning |

`region` is `{x, y, w, h}` as fractions of the image as previewed: of the
working profile's crop when it has an enabled one, else of the whole frame
(the raw image after coarse rotation and the raw border). It renders that
area at 1:1 (still capped at `max_size`) through a temporary `[Crop]` layer;
the working profile is untouched. ART's `[Crop]` is in frame pixels, so the
frame size is measured once per image with two 1-pixel-strip `art-cli`
renders (~0.5 s each) and cached.

### 6.2 Working profile and sidecars

From [Sidecar write policy for the Render server](https://github.com/AhaiMk01/ART/issues/8).

- Edits accumulate in a **working profile**, in memory per server process,
  keyed by path, lost on restart.
- `open_image` seeds it from the image's sidecar, else from ART's default
  profile for that image type (same as the editor). A content hash of the
  sidecar is kept.
- To get the resolved, complete processing profile (default profile, dynamic
  rules, sidecar), `open_image` runs `art-cli` once (`-p <sidecar>` or `-d`,
  `-f`, `-O`) to a throwaway output and reads the `.arp` written beside it.
  The sidecar is passed with `-p` (not `-s`) so the file read is the file the
  server hashes and later saves. No resize layer is added: `-O` saves the
  layered profile, so a resize would leak into it (`-f`'s own resize is
  applied to a copy and doesn't). Later renders pass the working profile
  explicitly and never use `-d`. If ART is set to embed parameters in output
  metadata, `-O` writes no `.arp` and `open_image` fails with a hint.
- Only `save_sidecar` writes the sidecar. Renders and previews never do.
- **Conflict:** if the sidecar's hash changed since load, the server asks the
  user (merge = agent's changed keys onto the current sidecar / overwrite /
  cancel). It uses MCP elicitation when the connection allows it; otherwise
  it returns `conflict` with the changed keys, and the agent asks the user and
  calls again with `on_conflict`. Elicitation can be unavailable even when the
  client advertises it: newer protocol versions give a tool call no
  back-channel to ask on. The user is asked without holding the image's lock;
  if the sidecar changes again, or the image is reopened or reset, before the
  write, the save fails with `conflict` instead of overwriting.
- **Open in editor:** if a control-enabled ART reports the path open,
  `save_sidecar` returns `open_in_editor` and points to the Live server (ART
  doesn't reload sidecars and would overwrite on autosave/close). Without the
  control channel enabled this can't be detected; documented limitation.
- **Backup:** before overwriting, the previous sidecar is copied to
  `<sidecar>.bak` (one, replaced each save).
- **Atomic write:** temp file then rename.
- **Sidecar name** follows ART's "strip extension" preference
  (`[Profiles] ParamsSidecarStripExtension` in its `options` file):
  `IMG.arp` vs `IMG.CR2.arp`.
- After a save, the saved sidecar is the new baseline: its hash, and the start
  of change tracking.
- `save_partial_profile` writes only the keys the agent changed since load or
  the last `save_sidecar` to `dest`; refuses an existing file unless
  `overwrite=true`; writes nothing when nothing changed.
- `export_image` renders the working profile as it is, saved or not. It writes
  a `.arp` beside the output only with `write_profile=true` (art-cli `-O`).

### 6.3 art-cli backend

From [art-cli as the Render server's backend](https://github.com/AhaiMk01/ART/issues/3).

- One `art-cli` call per render: the working profile written as a temp `.arp`
  layered with `-p`, plus temporary layers (resize, crop region). Measured on
  a 24 MP raw at 1024 px: 0.37 s (neutral profile, `-f`), 0.93 s (user's
  default profile, `-f`), 1.81 s (default profile, no `-f`).
- Always pass `-a` (so ART's "parsed extensions" preference can't skip an
  input) and `-Y` into a server temp path, then verify and move. The
  `overwrite` rule for exports is enforced by the server before calling
  `art-cli`. Check the output file exists: some failures exit 0 (output exists
  without `-Y`, output == input). Exit codes: -3 bad args, -2 load/save or
  options-load failure, -1 unknown option or `-h`, 1 stray argument, 2 no
  input / skipped extension.
- Windows: spawn `ART-cli.exe` directly (no shell) with `CREATE_NO_WINDOW` and
  stdin closed.
- Timeouts: 60 s preview, 120 s export (configurable); kill `art-cli` on
  timeout -> `timeout`.
- `art-cli` reads the user's ART options (default profiles, sidecar naming),
  so results match the editor and may differ between machines.
- Concurrency: one lock per image path; at most 2 `art-cli` processes at once.

### 6.4 Metadata

`inspect_image` runs the `exiftool.exe` shipped with ART (13.59 in ART 1.26.9)
with `-j -n`. Fixed fields: make, model, lens, ISO, shutter, aperture, focal
length, capture date, pixel dimensions, orientation. `tags` adds named exiftool
tags. `art-cli` has no metadata output; Pillow can't read most raws.

## 7. Live server

From [Live server capabilities and control channel](https://github.com/AhaiMk01/ART/issues/10),
building on [How the ART editor applies a profile to the open image](https://github.com/AhaiMk01/ART/issues/4)
and [Control channel options for a running ART GUI](https://github.com/AhaiMk01/ART/issues/5).

### 7.1 Tools

Every image tool takes an absolute path that must be open in ART (else
`not_open`). If no control-enabled ART runs: `art_not_running`, with a hint to
start ART with `--live-control` or enable it in Preferences. The Live server
never launches ART.

| Tool | Args | Returns |
|---|---|---|
| `status` | none | Running?, ART version, open image paths + sizes |
| `get_profile` | `path` | Read format (3.4) + History position |
| `edit_profile` | `path`, `adjustments?`, `raw_edits?` | Keys changed; returns once the undo entry exists |
| `undo` / `redo` | `path` | New History position |
| `render_preview` | `path`, `max_size=1024`, `inline?` | JPEG path; waits until ART's processing queue drains (30 s timeout) |
| `open_image` | `path` | Opened |
| `save_sidecar` | `path` | Saved (editor's own save) |
| `describe_adjustments` | none | As Render server |
| `inspect_image` | `path`, `tags?` | As Render server (Python + exiftool; no C++) |

- History: one entry per `edit_profile`, labelled `Agent: <tools touched>`
  (e.g. `Agent: Exposure, White Balance`).
- Previews come from the editor's preview image: **monitor** colour space, not
  sRGB output.
- No guard against the user editing at the same time: partial profiles only
  touch the agent's keys; undo is the safety net.

### 7.2 Control channel

- **Transport:** TCP on `127.0.0.1`, ephemeral port, Gio `GSocketService` on
  the GTK main loop. Works in `-N`/`-s`/`-gimp` modes.
- **Enable:** off by default. Preferences toggle (stored in `Options`) or
  `--live-control` for one run.
- **Discovery:** ART writes `{port, token, pid, version}` to
  `live-control.json` in its config dir (user-only permissions), new random
  token each run, deleted on exit. The Live server checks the pid is alive.
- **Protocol:** JSON lines. First line `{"token": "..."}`. Then requests
  `{"id", "op", "args"}` and replies `{"id", "ok": true, "result"}` or
  `{"id", "ok": false, "error": {"code", "message"}}`.
- **Ops:** `status`, `get_profile` (returns .arp text + history position),
  `apply_profile` (.arp partial profile text + label), `undo`, `redo`,
  `preview` (target JPEG path + max size), `open`, `save_sidecar`. All schema
  work stays in Python; ART only parses and emits KeyFile text.

### 7.3 C++ changes (fork only)

- New module `src/gui/livecontrol.{h,cc}` (always built; add to
  `src/gui/CMakeLists.txt`): socket service, token check, JSON-lines dispatch,
  discovery file, hop onto the main thread with `IdleRegister::add`, deferred
  replies for previews.
- Hooks, kept small to limit upstream merge conflicts:
  - `EditorPanel *RTWindow::getActiveEditorPanel()` and lookup by filename
    (reusing `RTWindow::selectEditorPanel`).
  - Public `EditorPanel` methods for: get profile (`ipc->getParams` -> .arp
    text), history position, undo/redo, preview grab
    (`PreviewHandler::getRoughImage` -> `Gdk::Pixbuf::save` JPEG), sidecar
    save.
  - `ProfilePanel::applyPartialProfile(const PartialProfile&, label)` built
    from the paste path (select the custom row, then
    `profileChange(EvProfileChanged)`), so the profile combo stays correct and
    one History entry is made. The label goes in the existing `descr`
    argument; no new ProcEvent.
  - A small `KeyFilePartialProfile` that turns received .arp text into a
    `PartialProfile` (only the keys present are applied).
- Preferences toggle + `--live-control` option; strings in
  `data/languages/default`.

## 8. Installation

- Claude Code, per user:

  ```sh
  claude mcp add art-render -- uv run --directory <repo>/tools/mcp art-mcp-render
  claude mcp add art-live -- uv run --directory <repo>/tools/mcp art-mcp-live
  ```

- Repo-root `.mcp.json` registers both (project scope, the user approves on
  first use), with relative `--directory tools/mcp`.
- Claude Desktop: same command in `claude_desktop_config.json` under
  `mcpServers`, with an absolute path.
- Optional args: `--art-dir`, `--inline-previews`.

## 9. Testing

There is no C++ test suite. For the Python package:

- Unit tests (pytest) at these seams: KeyFile reader/writer round-trips,
  adjustments + raw edits -> partial profile (range, unknown key, conflict
  rules), read format, sidecar conflict/backup logic, art-cli argument
  building, control-channel message framing (against a fake server).
- Integration tests, skipped when ART isn't found: render a preview and an
  export from a sample raw with the real `art-cli`; `inspect_image` via
  exiftool.
- Live server C++ side: verified by building ART and driving it with the Live
  server against a fake/real image.

## 10. Later (not in this spec)

- Typed shapes for the hard tools (curves, equalizers, masks, Spot Removal).
- Extracting `tools/mcp/` into a standalone repo.
- Folder-wide catalog queries (ruled out).

## Appendix A: Curated adjustment schema

Typed field names are snake_case of the .arp key; each maps to exactly one
`[Group] Key`. Ranges are ART's GUI `Adjuster` ranges at `PPVERSION` 1045
(sources: `src/engine/procparams.cc`, `src/gui/<tool>.cc`). Every tool also has
`enabled: bool` (`Enabled`), except Lens Profile (enabled via `lc_mode`).
Setting any field of a disabled tool also sets `enabled: true`; the result
lists every implied change. (An explicit `enabled: false` in the same request
wins.) Only fields in the tool's own group count: Rotation's `auto_fill`,
which lives in `[Common Properties for Transformations]`, doesn't enable
Rotation. Lens Profile has no `enabled`; `lc_mode: none` is off. Values ART
stores differently are mapped both ways (Denoise `chrominance_method`
`manual`/`automatic` is stored as `0`/`1`). A key a tool's group lacks reads
as ART's default.

**exposure** -> `[Exposure]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `compensation` | float | -12 .. 12 | EV | 0 |
| `black` | float | -2 .. 2 | | 0 |
| `hl_recovery` | enum | `Off`, `Blend`, `Color`, `Balanced` | | `Off` |
| `hl_recovery_blur` | int | 0 .. 3 | | 0 |

**white_balance** -> `[White Balance]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `setting` | enum | `Camera`, `Auto`, `CustomTemp`, `CustomMult` | | `Camera` |
| `temperature` | int | 1500 .. 60000 | K | 6504 |
| `green` | float | 0.02 .. 10 | tint multiplier | 1.0 |
| `equal` | float | 0.8 .. 1.5 | blue/red balance | 1.0 |

Setting `temperature`, `green` or `equal` without `setting` also switches
`setting` to `CustomTemp` (reported as an implied change). `Multipliers` and `CustomMultLegacy` stay
raw-edit only.

**crop** -> `[Crop]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `x`, `y` | int | 0 .. image width-1 / height-1 | px | -1 (unset) |
| `w`, `h` | int | 1 .. image width / height | px | -1 (unset) |
| `fixed_ratio` | bool | | | true |
| `ratio` | enum | ART's ratio list (`3:2`, `4:3`, `16:9`, `1:1`, ... see `crop_ratios` in `src/gui/crop.cc`) | | `As Image` |
| `orientation` | enum | `Landscape`, `Portrait`, `As Image` | | `As Image` |

Pixel bounds are checked against the image's frame (measured as in 6.1, cached).
A partial rectangle on an image with no crop yet is rejected: give x, y, w
and h together. Known limit: the frame is the one before this request's raw
edits, so a coarse rotation changed in the same request isn't accounted for. `Guide`
(display overlay) stays raw-edit only.

**rotation** -> `[Rotation]` + `[Common Properties for Transformations]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `degree` | float | -45 .. 45 | deg | 0 |
| `auto_fill` | bool | (`AutoFill` in Common Properties) | | true |

**local_contrast** -> `[Local Contrast]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `contrast` | float | -100 .. 100 | | 0 |

First region only (`Contrast`); extra regions (`Contrast_N`), curves and masks
stay raw-edit only.

**sharpening** -> `[Sharpening]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `method` | enum | `usm`, `rld` | | `rld` |
| `contrast` | float | 0 .. 200 | threshold | 20 |
| `amount` | int | 1 .. 1000 | (usm) | 200 |
| `radius` | float | 0.3 .. 3 | px (usm) | 0.5 |
| `deconv_amount` | int | 0 .. 100 | (rld) | 100 |
| `deconv_radius` | float | 0.4 .. 2.5 | px (rld) | 0.75 |
| `deconv_auto_radius` | bool | | (rld) | true |

`psf` method and corner/edge parameters stay raw-edit only.

**denoise** -> `[Denoise]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `luminance` | float | 0 .. 100 | | 0 |
| `chrominance_method` | enum | `manual` (0), `automatic` (1) | | `automatic` |
| `chrominance_auto_factor` | float | 0 .. 1 | (automatic) | 1 |
| `chrominance` | float | 0 .. 100 | (manual) | 15 |

Colour space, aggressiveness, detail and other keys stay raw-edit only.

**vignetting** -> `[Vignetting Correction]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `amount` | int | -100 .. 100 | | 0 |
| `radius` | int | 0 .. 100 | | 50 |
| `strength` | int | 1 .. 100 | | 1 |
| `center_x`, `center_y` | int | -100 .. 100 | % of image width / height, offset from centre (`src/engine/iptransform.cc`) | 0 |

**lens_profile** -> `[LensProfile]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `lc_mode` | enum | `none`, `lfauto`, `lfmanual`, `lcp`, `exif` | | `none` |
| `use_distortion` | bool | | | true |
| `use_vignette` | bool | | | true |
| `use_ca` | bool | | | false |

`LCPFile` and the manual Lensfun camera/lens strings stay raw-edit only.

Defaults above are ART's built-in values; an image's actual starting values
come from its sidecar or default profile and are what `get_profile` reports.
