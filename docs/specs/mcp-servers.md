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
  exiftool found, 5), `metadata_failed`, `invalid_tag`, `open_in_editor`,
  `art_not_running`, `write_failed`, `busy`, `unsupported` (the ART
  build lacks a fork feature). Live server only: `timeout` also covers ART not answering
  on the control channel; `bad_reply` (ART's answer isn't the protocol); ART's
  own codes pass through (`bad_request`, `unknown_op`), except that for
  `sample_spots` ART's `unknown_op` (a fork build without spot sampling) becomes
  `unsupported`, as in the Render server.
- **Validation messages:** an out-of-range or unknown input names the field and
  the allowed range or values, for example `exposure.compensation=99 is outside
  -12..12 EV` or `tone_curve.mode='x' is not one of: Standard, ...`; several
  problems are joined with `; `.
- **Dependencies:** Pillow is a runtime dependency (`image_stats` decodes the
  rendered PNG with it).

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
    render/         # Render server
      server.py         # build_server: wiring only; main() entry point
      session.py        # RenderSession: working profiles, per-image locks,
                        #   frame cache, art-cli runs; the only locking path
      artcli.py         # art-cli runner and argument builders
      profile_tools.py  # open_image, reset_profile, get/edit_profile,
                        #   describe_adjustments
      preview_tools.py  # render_preview
      export_tools.py   # export_image
      save_tools.py     # save_sidecar, save_partial_profile
      metadata_tools.py # inspect_image
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
(basic amounts), Vignetting Correction, Lens Profile, Tone Curve (curves 1
and 2). Fields, ranges and units:
see [Appendix A](#appendix-a-curated-adjustment-schema).

All other tools (other curves, equalizers, masks, Spot Removal, Film Negative,
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

### 4.1 Spot sampling (both servers)

What ART's own pickers read, so an agent can do what a human does with them
(the film negative tool's neutral-spot and reference-spot pickers, from a
camera-scanned negative). Exact: both servers call the engine code the GUI
pickers use, not an approximation from a rendered file.

`sample_spots(path, spots, size=32, space="working")`:

- `spots`: 1 to 16 `{x, y}`, whole pixels in the **frame** (the raw image
  after coarse rotation and the raw border, the same coordinates as
  `[Crop]`), each the centre of a `size` x `size` square. A spot outside the
  frame is `out_of_range`. `size` is 2 to 256 (the GUI offers 2 to 32; 32 is
  its default).
- `space`: `"working"` (the profile's working space) or `"input"` (camera
  space). These are the film negative tool's two `ColorSpace` values
  (`[Film Negative] ColorSpace` 1 and 0); use the one the profile has.
- Returns the frame's `width`/`height`, `space`, `size`, and per spot `x`,
  `y`, `avg` and `max` as `[r, g, b]`: linear values on ART's 0..65535 scale,
  white-balanced with the profile's white balance, before the film negative
  tool and everything after it (the engine's `getSpotAvgMax`: demosaiced
  `ImageSource::getImage` of the square, converted to the working space for
  `"working"`; `avg` channels are raised to at least 1). One difference from
  the GUI pickers: the square is kept inside the frame (theirs can overhang
  the right and bottom edges), so spots near an edge can differ slightly.
  The Live op answers `busy` while the editor is processing or has nothing
  processed yet; the Live server retries for up to 30 s (`timeout` after).
- Mapping a preview pixel to the frame: a whole-image Render preview shows
  the crop when one is enabled, so `x = crop.x + px * crop.w / preview_w`
  (no crop: `x = px * frame_w / preview_w`); a Live preview always shows the
  whole frame.
- The tool description carries the film negative maths, so the agent doesn't
  have to read ART's source. Neutral spots `a` and `b` (the clearer one has
  the higher green): `RedRatio = log(clear.r/dense.r) / log(clear.g/dense.g)`,
  `BlueRatio` likewise with blue, `GreenExponent` unchanged. Reference spot:
  `RefInput = avg`; `RefOutput = (L, L, L)`: the linear output level
  (0..65535, before the tone curve) the reference spot gets, since the
  engine computes `out = RefOutput * (in / RefInput)^exponent`, clipped at
  65535. Choose `L` = the spot's intended reflectance x 65535 (18% grey about
  11800; ~0.3 about 19700), then check `image_stats` `clipped_high` and raise
  `L` until highlights just don't clip. ART's default 65535/24 corresponds to
  the image median, not a chosen spot (the GUI picks `L` so that the previous
  reference spot keeps its luminance, which the agent may do or not).
- On a film negative the sampled values are the negative's (transmitted
  light): higher is a darker part of the scene; ratios are unaffected. The
  description also recommends fitting `RedRatio = 1/slope` of ln r against
  ln g (and `BlueRatio` with b) over many neutral spots, dropping those with
  large residuals, instead of trusting one pair.

Render server: a new `art-cli` option in the fork,
`-x <size>,<space>,<x1>,<y1>[,<x2>,<y2>...]`, given with the usual `-p`
layers and `-c <image>`. It loads the image, applies the profile's raw
preprocessing, demosaic and white balance as an export does, samples, prints
one line `ART-SPOTS <json>` (`{"width", "height", "spots": [{"x", "y",
"avg", "max"}]}`) and writes no image. A release `art-cli` doesn't know `-x`
and exits -1 (its usage text is in the output; any other failure is
`render_failed`): the tool fails with `unsupported` ("needs an ART build with
spot sampling"). Point `--art-dir`/`ART_DIR` at a fork build to use it.

Live server: a control-channel op `sample_spots` (`path`, `spots`, `size`,
`space`) on the open editor, through `ImProcCoordinator` as the GUI pickers
are, so it samples the profile the editor holds (any unsaved edits
included). Same result shape. A fork build without the op answers `unknown_op`,
which the server reports as `unsupported`.

### 4.2 Image statistics (both servers)

`image_stats(path, max_size=1024, histogram=false)` replaces watching the
histogram and the clipping indicator. It renders the image as a preview is
rendered (Render: `art-cli -n -b8` to a PNG, crop applied, same `-f` rule;
Live: the editor's preview, saved as PNG: whole frame, uncropped, ~600 px,
in the monitor colour space ART previews in), so the numbers describe the
output-referred 8-bit image, and returns per channel `r`, `g`, `b` and `lum`
(`0.2126 R + 0.7152 G + 0.0722 B` of the 8-bit values):

- `clipped_high` / `clipped_low`: fraction of pixels at 255 / at 0;
- `percentiles`: values at 0.1, 1, 5, 50, 95, 99, 99.9 %;
- `mean`;
- `histogram` (only when asked): 256 counts.

Film scans include the holder/border, which dominates clipping and
percentiles: crop first (Render applies the working profile's crop; Live's
preview is uncropped). Plus the rendered `width`/`height`. Downscaling hides clipping in tiny
highlights. Render: raise `max_size` (up to 2576) to see more. Live: `max_size`
can only shrink the ~600 px editor preview, never enlarge it.

## 5. Locating ART (both servers)

`--art-dir` flag or `ART_DIR` env (folder with `ART-cli.exe`), else PATH, else
the newest `C:\Program Files\ART\<version>`. The Render server fails at
startup if none is found; the Live server needs it only to find the config
folder of a portable install and exiftool.

**exiftool** is located separately from ART-cli, because a fork build has
none: beside ART-cli in that folder first, else on PATH, else beside the
newest installed `C:\Program Files\ART\<version>` that has one. If none is
found `inspect_image` fails with `metadata_unavailable` and `open_image`'s
metadata is null (both servers).

ART's **config folder** (its `options` file, and the Live server's discovery
file) follows ART's own rules (`Options::load`): `ART_SETTINGS` if set; else
`<install>/mysettings` for a portable install whose own `options` says
`[General] MultiUser=false`; else `%LOCALAPPDATA%\ART` (XDG config dir
elsewhere). Builds with a `CACHE_NAME_SUFFIX` use `ART<suffix>`: point
`ART_SETTINGS` at it.

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
| `save_partial_profile` | `path`, `dest`, `overwrite=false`, `exclude=[]` | `written`, path, keys written |
| `inspect_image` | `path`, `tags?` | Fixed metadata fields + requested tags |
| `describe_adjustments` | none | Curated schema + `PPVERSION` warning |
| `sample_spots` | `path`, `spots`, `size=32`, `space="working"` | Linear spot values (4.1); `unsupported` with a release `art-cli` |
| `image_stats` | `path`, `max_size=1024`, `histogram=false` | Clipping, percentiles, mean per channel (4.2) |

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
  `overwrite=true`; writes nothing when nothing changed (also when `exclude`
  removes everything). `exclude` lists `"Group"` or `"Group/Key"` entries left
  out of the file; a group or key not in the working profile is `unknown_key`.
  For a roll preset the per-frame settings should be excluded: `Coarse
  Transformation`, `Crop`, `Film Negative/RefInput` (and `Film Negative/RefOutput`
  if set per frame). The Live server has no `save_partial_profile`.
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

`inspect_image` runs the `exiftool.exe` shipped with ART (13.59 in ART 1.26.9),
located as in section 5 (not necessarily beside ART-cli),
with `-j -n`. Fixed fields: make, model, lens, ISO, shutter, aperture, focal
length, capture date, pixel dimensions, orientation. `tags` adds named exiftool
tags. `art-cli` has no metadata output; Pillow can't read most raws.

## 7. Live server

From [Live server capabilities and control channel](https://github.com/AhaiMk01/ART/issues/10),
building on [How the ART editor applies a profile to the open image](https://github.com/AhaiMk01/ART/issues/4)
and [Control channel options for a running ART GUI](https://github.com/AhaiMk01/ART/issues/5).

### 7.1 Tools

Every image tool takes an absolute path that must be open in ART (else
`not_open`). If no control-enabled ART runs (no discovery file, its pid gone,
the connection refused, or the token refused): `art_not_running`, with a hint
to start ART with `--live-control` or turn on Preferences > General > AI
Assistants. The Live server never launches ART.

| Tool | Args | Returns |
|---|---|---|
| `status` | none | ART version, open images: path, `active`, width/height (the editor's full image size before crop; null until known) |
| `get_profile` | `path` | Read format (3.4) + `history_position` (selected History row, 0 = oldest; null if none) |
| `edit_profile` | `path`, `adjustments?`, `raw_edits?` | Keys changed; returns once the undo entry exists |
| `undo` / `redo` | `path` | New History position |
| `render_preview` | `path`, `max_size=1024`, `inline?` | JPEG path + width/height; waits until ART's processing queue drains (30 s, else `timeout`). The editor's preview (~600 px wide, whole frame, uncropped) shrunk to fit `max_size`, never enlarged |
| `open_image` | `path` | ART's name for it, `already_open`; returns once ART has loaded it (60 s, else `timeout`) |
| `save_sidecar` | `path` | The sidecar written (editor's own save), null when ART keeps profiles in its cache only; `write_failed` when nothing was written |
| `describe_adjustments` | none | As Render server |
| `inspect_image` | `path`, `tags?` | As Render server (Python + exiftool; no C++) |
| `sample_spots` | `path`, `spots`, `size=32`, `space="working"` | As Render server, from the open editor (4.1) |
| `image_stats` | `path`, `max_size=1024`, `histogram=false` | As Render server, from the editor's preview (4.2) |

- `get_profile` returns the profile as the editor holds it (`ipc->getParams`,
  as ART's own sidecar save does), so it includes what the engine resolved:
  the camera white balance's temperature/green, the automatic deconvolution
  radius, the disabled crop filled with the full frame. These can differ from
  the Render server's values for the same file, which come from the saved
  profile. Paths go to ART absolute but unresolved (links and `subst` drives
  as given), because ART matches the name it opened the file under.
- History: one entry per `edit_profile`; ART shows it as
  `ARP changed | Agent: <tools touched>` (its paste-entry prefix). A raw
  edit ART can't load is rejected (`bad_request`) before anything changes:
  ART tries the partial profile on a copy first. `[Version]` can't be
  edited on either server.
  (e.g. `Agent: Exposure, White Balance`).
- Previews come from the editor's preview image: **monitor** colour space, not
  sRGB output.
- No guard against the user editing at the same time: partial profiles only
  touch the agent's keys; undo is the safety net.

### 7.2 Control channel

- **Transport:** TCP on `127.0.0.1`, ephemeral port, Gio `GSocketService` on
  the GTK main loop. Works in the default and `-N` modes. If another ART is
  already running, a default-mode launch forwards its files to that one and
  `--live-control` is ignored (a warning says so): start with `-N` then.
- **Enable:** off by default. Either the Preferences toggle (General tab,
  "AI Assistants"; saved as `[General] LiveControl`, default false) or
  `--live-control` for one run. The channel runs when either is set; the flag
  never changes the saved preference. Changing the toggle takes effect on OK
  with no restart: on starts the channel if it isn't running (new port and
  token, new discovery file; a channel the flag already started keeps its port
  and token), off stops it (connections closed, discovery file removed), even
  if the flag had started it. OK acts only when the saved value changed. The
  status line under the checkbox reflects the state when Preferences opened.
  Known limit: ART's OK applies the toggle just before saving `options`, so a
  failed save leaves the channel switched but the preference unsaved.
- **Discovery:** ART writes `{port, token, pid, version}` (`version` is
  `RTVERSION`, a release number or a git hash) to `live-control.json` in its
  config dir: temp file (named with the pid) renamed into place; 0600 on
  POSIX, on Windows the config folder's own ACL. New random 128-bit token each
  run. Removed on a clean exit, only if it still holds this run's token; a
  crash leaves it, and the Live server then sees the pid is gone.
- **Protocol:** JSON lines. First line `{"token": "..."}`. Then requests
  `{"id", "op", "args"}` and replies `{"id", "ok": true, "result"}` or
  `{"id", "ok": false, "error": {"code", "message"}}`. A wrong token closes
  the connection (no reply). The Python client opens a fresh connection per
  request, re-reading the discovery file, with one deadline for the whole
  reply.
- **Limits** (a local process of any user can reach a loopback port): at most
  8 connections; a connection not authenticated within 5 s, or sending a
  pre-auth line over 1 KB, is closed before anything is parsed; the token is
  compared in constant time; requests over 1 MB or nested deeper than 32 get
  `bad_request`; JSON numbers follow RFC 8259 strictly. Replies are written
  asynchronously: reading pauses while 1 MB of replies is pending, and a
  connection whose replies don't drain for 30 s is dropped, so a client can't
  stall the GUI.
- **Ops:** `status`, `get_profile` (returns .arp text + history position),
  `apply_profile` (.arp partial profile text + label), `undo`, `redo`,
  `preview` (target JPEG or PNG path + max size), `open`, `save_sidecar`,
  `sample_spots` (4.1). All schema
  work stays in Python; ART only parses and emits KeyFile text.

### 7.3 C++ changes (fork only)

- New module `src/gui/livecontrol.{h,cc}` (always built): socket service,
  token check, JSON-lines dispatch, discovery file. Requests are handled in
  the GIO read callback, which already runs on the GTK main loop (under
  `GThreadLock`), so no `IdleRegister` hop is needed. `preview` replies
  later: it polls every 50 ms (low priority) until the editor isn't
  processing, at most 4 waiting per connection (`busy` beyond), 30 s
  (`timeout`); replies can therefore arrive out of order, matched by `id`.
  Its `output` must be a new `.jpg`/`.jpeg`/`.png` file (`exists`
  otherwise), so
  the channel can't be used to overwrite files; `write_failed` if saving
  it fails. `open` takes absolute paths only.
- Hooks, kept small to limit upstream merge conflicts:
  - `RTWindow::getActiveEditorPanel()` / `getEditorPanels()` (and the same on
    `EditWindow`, via a non-creating `EditWindow::getExistingInstance()`),
    `EditorPanel::getImageSize()`, `EditorPanel::getProfileText()` (profile
    as .arp text + History position) and `History::getPosition()`; editors
    are found by filename, case-insensitively on Windows. Known limit:
    `ipc->getParams` copies the engine's params without a lock, like every
    existing editor caller; a copy taken mid-processing can lag a just-made
    change.
  - Public `EditorPanel` methods for: get profile (`ipc->getParams` -> .arp
    text), `canApply` (a partial profile tried on a copy), history
    position, undo/redo, preview grab (a new
    `PreviewHandler::getPreviewImage` -> `Gdk::Pixbuf::save` JPEG),
    sidecar save.
  - `ProfilePanel::applyPartialProfile(const PartialProfile&, label)` built
    from the paste path (select the custom row, then
    `profileChange(EvProfileChanged)`), so the profile combo stays correct and
    one History entry is made. The label goes in the existing `descr`
    argument; no new ProcEvent.
  - A small `KeyFilePartialProfile` that turns received .arp text into a
    `PartialProfile` (only the keys present are applied). ART's loader can
    reset keys a group lacks (`[Exposure]` without `HLRecovery` turns
    highlight recovery off), so the given keys are laid over the current
    profile's own complete KeyFile, which is then loaded.
- Python side (`art-mcp-live`): `edit_profile` that changes nothing sends
  nothing (no empty History entry). It works from a `get_profile` snapshot;
  ART applies the partial profile over what it holds then, so a value the
  user changed meanwhile survives, but `changed`/`implied` describe the
  snapshot. The label names the adjusted tools, then the groups of raw edits.
  A crop is checked against `status`'s width/height; while ART hasn't
  reported them it is applied unchecked, with a warning.
- `open_image` opens through the file browser as a command-line file does
  (`FileCatalog::dirSelected`, so the browser shows its folder) and returns
  once `status` lists the image with its size (60 s, else `timeout`).
  `save_sidecar` is `EditorPanel::saveProfile` and returns the sidecar path
  (null when ART keeps profiles in its cache only).
- The Render server's `open_in_editor` check asks ART's `status` with a 5 s
  limit; no ART, an error or no answer means it can't tell, and the save
  proceeds.
- Preferences toggle + `--live-control` option; strings in
  `data/languages/default`. `RTWindow` owns the `LiveControl` instance
  (`initLiveControl(flag)` at startup, `setLiveControl(on)`,
  `liveControlPort()`, `liveControlFailed()`); `Preferences::workflowUpdate`
  calls `setLiveControl` when the option changed. A new frame at the bottom of
  the General tab holds the checkbox and a status line (Active with port,
  Active for this run (--live-control), Off, Could not start); the token is
  never shown.

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

- Typed shapes for the hard tools (other curves, equalizers, masks, Spot
  Removal).
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

**tone_curve** -> `[ToneCurve]`

| Field | Type | Range / values | Unit | Default |
|---|---|---|---|---|
| `mode` | enum | `Standard`, `WeightedStd`, `FilmLike`, `SatAndValueBlending`, `Luminance`, `Perceptual`, `Neutral` (`CurveMode`) | | `Neutral` |
| `mode2` | enum | as `mode` (`CurveMode2`); omitted = same as `mode` | | as `mode` |
| `histogram_matching` | bool | (`HistogramMatching`) | | false |
| `contrast` | int | -100..100 (`Contrast`) | | 0 |
| `curve1`, `curve2` | curve | see below (`Curve`, `Curve2`) | | linear |

Setting `mode` without `mode2` while the stored `CurveMode2` differs also
writes `CurveMode2 = mode` (implied; ART loads a `CurveMode` as both modes). A
legacy `CurveMode=OpenDisplayTransform` reads as `Neutral`.

A **curve** is explicit points or linear:

- `{"type": "spline" | "catmull_rom" | "nurbs", "points": [[x, y], ...]}`:
  2 to 32 points, `x` and `y` in 0..1, `x` strictly increasing. Written as
  ART's `<type code>;x1;y1;x2;y2;...;` (codes from `src/utils/curvetypes.h`:
  spline 1, NURBS 3, Catmull-Rom 4).
- `{"type": "linear"}`: identity, written `0;`.

`x` and `y` are sRGB-gamma-encoded 0..1 values of the image at the curve's
place in the pipeline (`src/engine/iptonecurve.cc`), so they line up roughly
with `image_stats` 8-bit values / 255 (later tools still change the output).
`get_profile` reads curves back as `{"type", "points", "drawn"}`; a parametric curve (code 2) or one that doesn't parse stays
under `raw`. `drawn` is what ART's curve editor draws through the points, a
port of `DiagonalCurve::getVal` (`src/engine/diagonalcurves.cc`; natural cubic
spline for `spline`, centripetal Catmull-Rom polyline for `catmull_rom`, a line
for two points or the identity): `[x, y]` pairs at x = 0, 0.125, ..., 1, y
rounded to 4 decimals. ART clamps only below 0 (`CLIPD`), so a spline or
Catmull-Rom can show y above 1. Every NURBS curve with three or more points (an identity one too) is not
computed (`drawn: null`); a two-point NURBS is a line and is drawn; `linear` has no `drawn`. `drawn` is read-only: input
that carries it (a `get_profile` curve sent back) is accepted and ignored.
`edit_profile` adds a warning for each `curve1`/`curve2` it set whose drawn line
clips to 0 (`curve2 clips to 0 for x 0.02-0.07`), goes above 1, or reverses
(decreases; `curve2 reverses for x 0.86-0.95`), scanned at 1001 x values; a NURBS
gets one warning that it can't be checked. ART resamples the drawn curve before
applying it (`src/engine/iptonecurve.cc`: about 30 samples, dense below 0.25 in
linear light, rebuilt as Catmull-Rom), so `drawn` is a close but not bit-exact
picture of what is applied. Setting `curve1`/`curve2` while `HistogramMatching` is on also
sets `histogram_matching: false` (implied): ART would replace the curve.
`contrast` is ART's analytic contrast curve (a power curve pivoting on scene
middle grey 0.18, or Log Encoding's target grey when that is enabled; it never
overshoots), applied before the curves; use it for an S-curve instead of curve
points. It is independent of histogram matching, which replaces only the
curves. `ContrastLegacyMode`, `Saturation`, `Saturation2`, `PerceptualStrength`, `WhitePoint`
and `BaseCurve` stay raw-edit only.

Defaults above are ART's built-in values; an image's actual starting values
come from its sidecar or default profile and are what `get_profile` reports.
