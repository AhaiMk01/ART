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
  build lacks a fork feature; the Live server found no ART-cli for `changed_only`). Live server only: `timeout` also covers ART not answering
  on the control channel; `bad_reply` (ART's answer isn't the protocol); ART's
  own codes pass through (`bad_request`, `unknown_op`), except that for
  `sample_spots` ART's `unknown_op` (a fork build without spot sampling) becomes
  `unsupported`, as in the Render server.
- **Validation messages:** an out-of-range or unknown input names the field and
  the allowed range or values, for example `exposure.compensation=99 is outside
  -12..12 EV` or `tone_curve.mode='x' is not one of: Standard, ...`; several
  problems are joined with `; `.
- **Dependencies:** Pillow is a runtime dependency (`image_stats` and
  `suggest_neutrals` decode the rendered PNG with it, `contact_sheet` composes
  the sheets).

```
tools/mcp/
  pyproject.toml, uv.lock
  art_mcp/
    schema.py       # curated adjustments (Pydantic), PPVERSION it targets
    compactschema.py # base of those models: the compact JSON input schema (3.3)
    keyfile.py      # GLib KeyFile (.arp) reader/writer
    profile.py      # read format, adjustments+raw edits -> partial profile
    preview.py      # temp folder, JPEG files, inline ImageContent
    metadata.py     # exiftool wrapper
    contactsheet.py # contact-sheet composition (Pillow)
    neutrals.py     # neutral-candidate scoring and selection (pure, Pillow)
    marks.py        # numbered boxes drawn on a preview (6.1; pure, Pillow)
    artdir.py       # locating ART-cli.exe / exiftool.exe / config dir
    calllog.py      # opt-in call log (2.1) and its summariser
    render/         # Render server
      server.py         # build_server: wiring only; main() entry point
      session.py        # RenderSession: working profiles, per-image locks,
                        #   frame cache, art-cli runs; the only locking path
      artcli.py         # art-cli runner and argument builders
      defaults.py       # ART's default profile for an image (changed_only;
                        #   the Live server uses it too)
      profile_tools.py  # open_image, reset_profile, get/edit_profile,
                        #   describe_adjustments
      preset_tools.py   # apply_preset
      preview_tools.py  # render_preview
      export_tools.py   # export_image, export_batch
      sheet_tools.py    # contact_sheet, compare_passes
      sheet_changes.py  # what a pass changed (pure): short numbers, grouping
      save_tools.py     # save_sidecar, save_partial_profile
      metadata_tools.py # inspect_image, inspect_images
      neutrals_tools.py # suggest_neutrals
    live/           # Live server: control channel client, tools
  tests/
```

### 2.1 Call log (both servers)

A client-independent record of what an agent did with the tools, so runs by
different clients and models can be compared from the server side.

- **Interface:** when the environment variable `ART_MCP_CALL_LOG` names a file,
  each server appends one line of JSON (UTF-8, JSON Lines) per tool call to it,
  when the call has completed; several servers, processes and threads may share
  one file (every line is one write that others cannot split). Unset or empty:
  nothing is logged and no hook is installed. The variable is part of the
  servers' interface, like `--art-dir`.
- **Line:** `t` (ISO 8601 UTC, milliseconds; when the call arrived), `server`
  (`art-render`, `art-live`), `tool`, `ms` (duration, to completion: an async
  tool is timed until it returns), `ok`, `error` (null when `ok`, else the
  leading `code:` of the tool error, or `invalid_arguments`, `unknown_tool`,
  `exception` for a crash, `cancelled`), `args`, `result_chars` (the length of
  the result's text as the client receives it: the compact JSON of the
  structured result, else the text content), `images` (image contents),
  `in_flight` (tool calls being handled when this one started, itself
  included).
- **Arguments** are logged by name with the values cut down: a string to 120
  characters (ending `...` when cut), a list to its first two items (each cut
  the same way) and `"...+<more>"`, a dict to its key names (50 at most).
  Nothing from the environment is ever logged.
- **Hook:** one `ServerMiddleware` (`calllog.install(server)`, called by each
  `build_server`), outermost in the SDK's chain, so every tool is covered without
  touching it, and a call is timed through its `await`, whatever its kind. It
  observes `tools/call` only and never changes a request or a result.
- **Failure:** a log that cannot be written (or a record that cannot be built)
  prints one warning on stderr and the call goes on; a missing folder is made.
- **Summary:** `python -m art_mcp.calllog summarise <file>` (`--json` for the
  data): calls and wall time (first arrival to last completion), distinct tools,
  the maximum `in_flight`, images, per tool the calls, errors, result
  characters and time (most calls first), the largest results, the first five
  errors with their codes, and the sequence of tools in order of arrival with
  consecutive calls of one tool collapsed (`open_image x12, edit_profile x12,
  ...`).

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
  to `CustomTemp`); implied changes are listed in the result (3.5). See Appendix A.

### 3.2 Curated tools (v1)

Exposure, White Balance, Crop, Rotation, Local Contrast, Sharpening, Denoise
(basic amounts), Vignetting Correction, Lens Profile, Tone Curve (curves 1
and 2), Color Correction (RGB-mode regions with rectangle/gradient area masks), Film Negative (stored values 1:1; computed `RefOutput`, see Appendix A). Fields, ranges and units:
see [Appendix A](#appendix-a-curated-adjustment-schema).

All other tools (other curves, equalizers, masks, Spot Removal,
Color Management, RAW settings) are reachable through raw edits only. Typed
shapes for them are a later, separate effort.

### 3.3 Schema

- Hand-written Pydantic models in `schema.py` (name, range, unit, one-line
  description per field). Ranges mirror ART's GUI `Adjuster` ranges; the
  engine defines ranges only for White Balance (`src/engine/colortemp.h`).
- Exposed in `edit_profile`'s input schema and returned by
  `describe_adjustments`. The input schema is the compact form: every client
  loads it with every session, and pydantic's own was 29,984 characters (compact
  JSON), over 80% of the Render server's input schemas. It drops what a
  caller doesn't need (a `title` on every model and field, `default: null`,
  `additionalProperties: false`, the `anyOf: [<type>, null]` wrapper on every
  optional field: leaving a field out, or null, means "not set"; ART's stored
  keys, defaults and conversions; the read-only `drawn` of a curve), folds
  a field's unit into its description (`Exposure compensation (EV)`), shows of
  a tool's docstring only its first paragraph (the rest is reference text) and
  defines the shapes that repeat once under `$defs` (the channel `{slope,
  offset, power}` of a Color Correction region, the point and linear curves,
  the mask shapes). A list position that may be null (`regions`, `shapes`)
  keeps its null alternative. The result is 16,599 characters (-45%); the
  whole listing of input schemas is 22,961 characters on Render and 19,698 on
  Live, from 36,346 and 33,083. `describe_adjustments` keeps the full
  documentation of each field (description, unit, range, default,
  `[Group] Key`) and of each tool (the whole docstring). The schema is built
  by `CompactModel` (`compactschema.py`), the base of the models; validation is
  the models' own and unchanged, so the same requests are accepted and
  rejected as before (`tests/test_schema.py`), and `tests/test_schema_size.py`
  pins the size.
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

A whole profile is large (about 15k tokens for a raw: ART writes over 500
keys), so `get_profile` can read less:

- `groups` (list of `[Group]` names as `raw` and raw edits name them, e.g.
  `["Film Negative", "ToneCurve"]`): only those groups. A curated tool is in
  when any group its fields live in is (Rotation's `auto_fill` lives in
  `Common Properties for Transformations`). A name the profile doesn't have is
  `unknown_key`, and the message lists the valid ones (`Version` is not one:
  `ppversion` is always returned).
- `changed_only`: only what differs from ART's default profile for the image
  (the one `open_image` starts an image without a sidecar from): the typed
  fields with another value, the raw keys with another value or missing from
  the default. Whatever is not listed equals the default. Both together
  combine.

The default profile comes from one `art-cli -d` run (the same `-O` resolve as
`open_image`), made the first time `changed_only` needs it for an opened image
(Render: kept with the working profile until the image is reopened or reset; Live: kept
per image for the life of the server) and never for a read without
`changed_only`. A Live server without `ART-cli` found (7.1) answers
`changed_only` with `unsupported`.

### 3.5 Edit result

`edit_profile` returns the change set, not the profile:

```json
{
  "changed":  { "Film Negative": { "RedRatio": "1.335" }, "RAW Bayer": { "Method": "amaze" } },
  "implied":  { "Film Negative": { "Enabled": "true" } },
  "created":  { "ColorCorrection": ["region 2 (78 keys at their defaults)"] },
  "drawn":    { "curve1": [[0, 0], [0.125, 0.0112], "...", [1, 1]] },
  "warnings": []
}
```

- `changed`: `[Group]` -> `Key` -> new value (the shape of `raw`) for every
  value the request set and that changed; re-setting a value is not a change.
- `implied`: the changes the request didn't ask for (a disabled tool enabled,
  White Balance to `CustomTemp`, `histogram_matching` off, a computed film
  `RefOutput`, see 3.1), in the same shape. A key is in `changed` or in
  `implied`, never both (a raw edit of a key an adjustment only implies is in
  `changed`).
- `created`: `[Group]` -> what the request created, one string each: a new
  Color Correction region (`region 2`) or mask shape (`region 2 mask shape 0`;
  a region's number is its position + 1, a shape's its position, as the
  request's lists count them) and how many of the keys ART writes for it were
  left at their defaults (`region 2 (78 keys at their defaults)`; a region
  has 82 keys, a shape 9 or 10). ART needs all of them (Appendix A,
  `color_correction`), so they are in the profile and in what Live sends to
  ART, but they are not in `changed`: that has the keys the request set (the
  new region's `Mode_n`, the shape's `Type` included), and `implied` the ones
  it caused. A key is in at most one of `changed`, `implied` and the defaults
  counted here, so the three add up to the keys written. Empty (`{}`) when
  nothing was created; an edit of a region or shape that exists creates
  nothing, and a shape of another type that replaces one counts as a new
  shape.
- `drawn`: for each tone curve the request set (`curve1`, `curve2`), the line
  ART's curve editor draws, as `get_profile` reads it back (not for a linear
  curve or a NURBS with 3+ points). It saves a `get_profile` after every
  curve.
- `warnings`: as before; the Live server adds `history_position` (7.1).
- `full=true` also returns `profile`: the groups the request touched (those it
  names and those it changed) in the read format, as the profile is after the
  edit. Meant for checking what a tool ended up as; it is several times the
  size of the rest. Without `full` the field is left out of the result (a
  serializer drops the null), not sent as `"profile": null`.

#### Several images (`paths`)

`edit_profile` takes `path` (one image) or `paths` (1 to 50 images) and
applies the same `adjustments` and `raw_edits` to each. Exactly one of the
two: both, neither, an empty list, more than 50 entries, or `full=true` with
`paths` is `out_of_range`, before anything changes. Each image is its own
change (Render: its working profile, which must be open; Live: its own History
entry, labelled as for one image, none when nothing changed there). The
request is the same for every image but is checked and applied per image, so
what an image makes of it is that image's own: a problem with one (not open,
`unknown_key` for a raw key its profile lacks, `out_of_range` for a crop
outside its frame, `conflict`, ...) is that image's `error` and the others
still change. The result is compact, one entry per image in request order,
and no change set each:

```json
{
  "items": [
    { "path": "A.ARW", "changed": 2, "implied": { "Film Negative": { "Enabled": "true" } }, "warnings": [], "error": null },
    { "path": "B.ARW", "changed": null, "implied": {}, "warnings": [], "error": "not_open: B.ARW is not open; call open_image first" }
  ],
  "failed": 1
}
```

- `changed`: how many values the request changed in that image, the count of
  the keys the single-image result lists in `changed` (0: the image had them
  all already); null when the image failed. The values are not listed; the
  single-image call, or `get_profile`, shows them.
- `implied`, `warnings`: as for one image. `created` and `drawn` are not in an
  entry (they are for one image's read-back).
- `error`: `<code>: <message>` (the text of the error a single-image call would
  have raised), or null. Live entries add `history_position` (null when the
  image failed).
- `failed`: the number of entries with an `error`.

#### A different edit per image (`items`)

`edit_profile` also takes `items`: 1 to 50 entries `{ path, adjustments?,
raw_edits? }`, a third alternative to `path` and `paths`. Exactly one of the
three: more than one, none, an empty list, more than 50 entries, `full=true`,
or an `adjustments` or `raw_edits` beside `items` (they go in each item) is
`out_of_range`, before anything changes; an entry with no `path` or a field
other than those three is refused by the input schema, also before anything
changes. Each entry is its own change, checked and applied like one image of
a `paths` call (it may carry `adjustments`, `raw_edits` or both, each as for
`path`; one with neither changes nothing), and the result is the same compact
`{ items, failed }` of the previous section: one entry per item, in request
order, `path` as given. One entry that fails is its own `error` and the others
still change. Two entries for the same image are applied in request order,
each as its own change (Live: its own History entry), so the second is made
on what the first left; entries for different images are independent (Render:
up to `max_processes` images at once, an image's entries one after the other;
Live: one after the other). It is what a set's per-frame values (white
balance, film reference and level, black point) need: one call instead of one
per frame, and `paths` stays for the values every frame shares.

Render edits the images up to `max_processes` at once (an edit can need art-cli
to measure the frame or sample the picture), each under its own image lock, as
`apply_preset` and `export_batch` do; Live edits them one after the other, over
the one control channel. The tool's output schema is an `anyOf` of the two
shapes (`EditResult`, `EditBatch`; Live's `LiveEditResult`, `LiveEditBatch`)
with an explicit `"type": "object"`, which a tool's output schema must have.
`reset_profile` and `open_image` (6.1) publish their output the same way
(`ResetResult` or `ResetBatch`; `OpenedImage` or `OpenBatch`, Live's
`OpenedInEditor` or `OpenedBatch`).
`paths` exists because a roll of twelve frames took twelve identical calls for
each of its base settings, its ratios and its group's output level; `items`
because the next roll's per-frame values (white balance, level, offset) still
took one call per frame (141 `edit_profile` calls for twelve frames).

## 4. Preview delivery (both servers)

From [How the Render server hands previews to Claude](https://github.com/AhaiMk01/ART/issues/12)
and [Render server tool list and signatures](https://github.com/AhaiMk01/ART/issues/9).

- **Default: file path.** The preview is a JPEG; the tool returns its path and
  Claude opens it with its file-reading tool when it wants to look.
- **Optional inline:** the result also carries base64 `ImageContent`, which the
  agent sees without opening the file. Set per call (`inline`), defaulting to the
  launch flag `--inline-previews` (off unless given).
- **Optional `output`:** an absolute path to a `.jpg` in an existing folder (else
  `out_of_range`, `not_found`) to write the preview to instead of the temp
  folder; the result's `path` is that file. The render goes to the temp folder
  first and is moved over, so a failed render leaves nothing at `output`; an
  existing file is `exists` unless `overwrite`, the image itself is never
  replaced, and all of it is checked before anything renders. Both servers.
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
(e.g. the film negative tool's neutral-spot and reference-spot pickers).
Exact: both servers call the engine code the GUI
pickers use, not an approximation from a rendered file.

`sample_spots(path, spots, size=32, space="working")`:

- `spots`: 1 to 64 `{x, y}` per call (more or fewer is `out_of_range`), whole
  pixels in the **frame** (the raw image after coarse rotation and the raw
  border, the same coordinates as `[Crop]`), each the centre of a `size` x
  `size` square. A spot outside the frame is `out_of_range`. `size` is 2 to
  256 (the GUI offers 2 to 32; 32 is its default). One run, `art-cli -x` or the
  channel op, takes at most 16 spots (`MAX_SPOTS`; the C++ side caps there), so
  a call of more is split in request order into runs of at most 16
  (`MAX_SPOTS_PER_CALL` = 64 is the call's cap) and answered as one result,
  the same per-spot values in the same order as if one run had taken them:
  Render runs them through the pool of `inspect_images` and `export_batch`
  (`session.cli.max_processes` at once, 2 by default); Live sends one request
  after the other, each waiting for a busy editor on its own (30 s). The frame
  is measured once. A failing run fails the call with that run's error (the
  first in request order), no partial result, and the message ends with the
  spot numbers it covered, e.g. `(spots 17 to 32 of 40; no result returned)`
  (a call of 16 or fewer has one run and its plain error). `suggest_neutrals`
  candidates (1 to 16) go in unchanged.
- `space`: `"working"` (the profile's working space) or `"input"` (camera
  space). These are the film negative tool's two `ColorSpace` values
  (`[Film Negative] ColorSpace` 1 and 0).
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
  whole frame. The other way round, `render_preview(marks=...)` (6.1) draws
  frame-pixel positions on a preview, so spots need not be mapped by hand.
- The tool description is generic (what it reads, coordinates, scale,
  errors) and ends with one line pointing at the skills for scan workflows
  (`tools/mcp/skills`). The film negative maths and the workflow around it
  live in the `film-negative` skill and its `reference.md`: the two-spot
  formulas, the least-squares fit of `RedRatio`/`BlueRatio` over many neutral
  spots (and the pooled fit over a roll), `RefInput = avg`,
  `RefOutput = (L, L, L)` (the engine computes
  `out = RefOutput * (in / RefInput)^exponent`, clipped at 65535; `L` = the
  spot's intended reflectance x 65535, then checked against `image_stats`
  `clipped_high`), the default 65535/24 matching the image median, and that
  on a film negative the sampled values are the negative's (transmitted
  light; higher is a darker part of the scene).

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

`image_stats(path?, paths?, max_size=1024, histogram=false, detail?, region?, bins?)` replaces
watching the histogram and the clipping indicator. It renders the image as a
preview is rendered (Render: `art-cli -n -b8` to a PNG, crop applied, same `-f`
rule; Live: the editor's preview, saved as PNG: whole frame, uncropped,
~600 px, in the monitor colour space ART previews in), so the numbers describe
the output-referred 8-bit image, and returns per channel `r`, `g`, `b` and
`lum` (`0.2126 R + 0.7152 G + 0.0722 B` of the 8-bit values, rounded):

- `clipped_high` / `clipped_low`: fraction of pixels at 255 / at 0;
- `percentiles`: values at 0.1, 1, 5, 50, 95, 99, 99.9 % (nearest rank; only
  0.1, 50 and 99.9 at `detail` `compact`);
- `mean` (not at `compact`), `std` (population standard deviation), `min` /
  `max` (lowest and highest value that occurs), `mode` (most frequent value,
  the lowest on a tie) (the last four at `full` only), all from the same
  256-bin counts;
- `bins` (only when asked, with the `bins` parameter): the fractions of pixels
  (4 decimals, summing to about 1) in 8, 16, 32 or 64 equal groups of values,
  dark to light; any other count is `out_of_range`. 16 numbers per channel are
  enough to see a shape the percentiles don't show (a clipped shoulder or toe,
  a second hump);
- `histogram` (only when asked): the 256 raw counts.

`detail` (`"compact"`, `"standard"` or `"full"`; any other value is
`out_of_range`) sets how many of these numbers a result has, since a result
is what the caller pays for in tokens (an agent that checks a dozen frames
after every edit makes dozens of calls). `standard`, the default for one
`path`, is `mean`, `clipped_high`, `clipped_low` and the seven percentiles
(about 700 characters of JSON). `compact` is per channel only `clipped_low`,
`clipped_high` and the percentiles 0.1, 50 and 99.9 (about 450 characters, 370
when nothing is clipped: the fractions are not rounded). `full` is `standard`
plus `std`, `min`, `max` and `mode`. `bins` and `histogram` add their fields
at any detail.

A result carries no null fields: `bins` and `histogram` when not asked,
`region` without a `region`, and in an item of `paths` (below) the `stats` or
the `error` that does not apply, are left out of the structured content and of
its text form (a `model_serializer` on the models in `art_mcp/sampling.py`; the
text is compact JSON, not the SDK's indented one). The output schema keeps
them as optional properties and allows both result shapes (one image, or
`items` and `failed`).

A holder, a border or bright lamps in the image count in all of it: crop first
(Render applies the working profile's crop; Live's preview is uncropped), or
measure only a part with `region` `{x, y, w, h}`: fractions (0 to 1) of the
image as this tool shows it (Render: the working profile's crop applied; Live:
the whole frame), `x`, `y` the top-left corner. It is the same rectangle, with
the same rounding and the same `out_of_range` refusal, as `render_preview`'s
`region` (6.1), but is cut from the PNG of the one whole-image render (Live:
the one preview), not rendered separately: no frame measuring, no second
render, and the region has the pixels of that render, so a small one is coarse
(raise `max_size`). Every statistic above is then of that part only; `width` /
`height` stay the whole rendered image's size and the result's `region` is the
part's pixel rectangle `{x, y, w, h}` in that image (null without a `region`).
A region outside 0..1 is `out_of_range` before anything runs; one of fewer
than 16 pixels is `out_of_range` once the render's size is known.

Several images: `paths` (1 to 50, instead of `path`: neither or both, an empty
list or more than 50 is `out_of_range`) measures many images in one call, with
the same `max_size`, `histogram`, `detail`, `bins` and `region` for all, and
returns `{items: [{path, stats | error}], failed}`: one item per path in
request order, `stats` as for one image, or the `error` (`<code>: <message>`)
of an image that could not be measured while the others still come back.
The two shapes differ: with `path` the statistics are the result's top level (`r`, `g`, `b`, `lum`, `width`, `height`, ...); with `paths` they are under `items[i].stats` (each item `{path, stats}` or `{path, error}`).
`detail` defaults to `"compact"` here (and to `"standard"` for one `path`)
unless the caller gives one. A problem with the call as a whole (`path` and
`paths`, `max_size`, `region`, `bins`, `detail`) fails it before anything runs.
Render: `not_open`, a render error, or a `region` of fewer than 16 pixels in
that image's render is that item's error; the renders run through the same
bounded pool as `inspect_images` and `export_batch` (`session.cli.max_processes`
art-cli at once, 2 by default) with progress reported per finished image.
Live: the editor's preview is asked for each image in turn (no progress);
`not_open` and a preview that is not a readable image (`bad_reply`) are that
item's error, while ART not running fails the whole call (`art_not_running`).

The description ends with the same skills pointer as 4.1 (the film scan
workflow is in the skills). Downscaling hides clipping in tiny highlights.
Render: raise `max_size` (up to 2576) to see more. Live: `max_size` can only
shrink the ~600 px editor preview, never enlarge it.

### 4.3 Neutral candidates (Render server)

`suggest_neutrals(path, count=16, size=32)` proposes where to look for neutral
(grey/white) references: flat, low-saturation, mid-level patches of the
working profile's current rendering, as candidates for white balance, colour
calibration or ratio fitting. It is a pre-filter, not an oracle: whether a
patch is neutral depends on its material (white paint, bare metal, concrete:
yes; natural stone, dyed fabric, foliage, glass: no), which only looking can
tell. The tool narrows where to look; the caller judges by material and checks
with `sample_spots`. The description says so, and that "neutral" only means
something once the rendering is roughly colour-correct. It names no workflow.

The rule (constants in `art_mcp/neutrals.py`; deterministic, the same rendering
gives the same answer):

1. **Render** the working profile as an 8-bit PNG, long edge 1600 px, crop
   applied: the `image_stats` render (`-f` when 1600 fits the user's
   fast-export box).
2. **Cells.** The area is the working profile's crop, else the whole frame.
   It is cut from its top left corner into squares of
   `max(size, ceil(4 / scale))` frame pixels (`scale` = preview pixels per
   frame pixel, so a cell is at least 4 preview pixels and its texture can be
   measured; the strip that does not fill a square is not analysed). Per cell:
   `level` = mean luminance (0.2126 R + 0.7152 G + 0.0722 B of the 8-bit
   values), mean r, g, b, `flatness` = the standard deviation of the luminance
   over its mean, `saturation` = (max - min) / max of the mean colour (HSV).
3. **Usable cells.** The mean of every channel lies in 16..240 (not near black,
   not near clipped), `flatness` <= 0.06, `saturation` <= 0.10 (about twice
   what still counts as neutral: a 5% difference between channels is 0.05),
   and the centre is not in the outer border of the area: 3% with a crop, 10%
   without one (a border or mount of the picture may still be in the frame; a
   warning says so).
4. **Cost** = `saturation + flatness` (both unit-less fractions, lower is
   better).
5. **Choice.** The usable cells' level range is cut into `count // 2` equal
   bands. Two rounds, each taking the lowest-cost cell of every band in turn
   (ties: top to bottom, left to right) that lies at least 10% of the area's
   longer side from those already chosen; then the lowest-cost of the rest.
   If that leaves fewer than `count`, the minimum distance is halved, halved
   again, then dropped. So the candidates spread over the levels (dark to
   light) and over the frame, and are not all adjacent.
6. **Result.** Sorted by `level`, then `y`, `x`. Per candidate `x`, `y` (the
   cell centre, whole pixels of the frame: the coordinates of `sample_spots` and
   `crop`; a candidate goes to `sample_spots` unchanged, its extra fields are
   ignored), `level` (0..255), `saturation`, `flatness` (3 decimals) and a short
   `why` (flat / some texture, neutral / near-neutral / tinted, dark / mid /
   light). Plus `area` [x, y, w, h] (what was analysed), `size` (to sample
   with), `cell` (the cell side; more than `size` on a big frame with a small
   `size`) and `warnings`: no crop, and "only N of M candidates" when fewer
   cells than asked for were usable (nothing is padded with poor cells). About
   40 tokens per candidate.

`count` is 1 to 16 (what one `art-cli -x` run takes; a `sample_spots` call takes
up to 64, so the candidates go in unchanged) and `size` 2 to 256, else
`out_of_range` before anything is rendered; a `size` larger than the area is
`out_of_range` too. `not_open`, `render_failed` (art-cli failed or wrote an
unreadable image) as for `image_stats`. The call renders once (about a second
on a 24 MP raw) and analyses in about 0.1 to 0.5 s.

`preview` (default false): the result also has `preview_path`, a JPEG in the
preview folder (`neutrals-NNNN.jpg`, kept until the server exits like a
`render_preview` file) of the rendering that was analysed (1600 px on its long
edge, the picture of step 1) with every candidate marked by the drawing of
`render_preview`'s `marks` (6.1): the `size` x `size` square the candidate is
sampled with, numbered 1..n in the order of the `candidates` list, at the
frame position of the candidate mapped into the picture by the `area`. One
call then tells the caller what each candidate sits on (a poster, a window,
paint), which the numbers cannot. With a server started with
`--inline-previews` the image comes with the result as an `ImageContent`, as
for `render_preview`; there is no per-call `inline`. No extra render: the
picture is the one analysed. Without `preview` the result has no
`preview_path` key at all.

## 5. Locating ART (both servers)

`--art-dir` flag or `ART_DIR` env (the folder with the ART-cli binary), else
PATH, else the system's usual install locations below. The Render server
fails at startup if none is found; the Live server needs it only to find the
config folder of a portable install and exiftool, and (optionally) ART-cli
itself, to resolve ART's default profile for `get_profile`'s `changed_only`.

The binary is `ART-cli.exe` on Windows and `ART-cli` elsewhere (ART's CMake
`OUTPUT_NAME`; a lowercase `art-cli` is also accepted on macOS and Linux).
Lookup order after PATH, per OS:

| OS | ART-cli | exiftool (after beside ART-cli, then PATH) |
|---|---|---|
| Windows | newest `%ProgramFiles%\ART\<version>` | newest such folder that has `exiftool.exe` |
| macOS | `/Applications/ART.app/Contents/Frameworks`, then `.../Contents/MacOS`, then the same under `~/Applications`; then `/usr/local/bin`, `/opt/homebrew/bin`, `/opt/local/bin`, `/usr/bin` | the same folders (the ExifTool pkg installs to `/usr/local/bin`; the bundle ships none) |
| Linux | `/usr/local/bin`, `/usr/bin`, `~/.local/bin`, then `/opt/ART*` (newest by the numbers in the name) | the same folders, plus `<folder>/lib/exiftool/exiftool` (the layout of `tools/linux/bundle_ART.py`) |

The macOS bundle layout comes from `tools/osx/macosx_bundle.sh` (ART-cli moved
into `Contents/Frameworks`) and the `Contents/MacOS` install of the CMake
bundle (`BINDIR`); AppImages are not searched (use `ART_DIR` on a mounted or
extracted one).

**exiftool** is located separately from ART-cli, because a fork build has
none: beside ART-cli in that folder first (also `lib/exiftool/` on macOS and
Linux), else on PATH, else the locations in the table. If none is found
`inspect_image` fails with `metadata_unavailable` (both servers) and the
Render server's `open_image` reports its metadata as null (the Live server's
`open_image` has no metadata; use `inspect_image`).

ART's **config folder** (its `options` file, and the Live server's discovery
file) follows ART's own rules (`Options::load`): `ART_SETTINGS` if set; else
`<install>/mysettings` for a portable install whose own `options` says
`[General] MultiUser=false`; else `ART` (`CACHEFOLDERNAME`) in the per-user
config folder: `%LOCALAPPDATA%` on Windows; on macOS and Linux GLib's
`g_get_user_config_dir()`, i.e. an absolute `$XDG_CONFIG_HOME`, else
`~/.config`. ART does not use `~/Library/Application Support` itself (the
app bundle's Info.plist sets a relative `XDG_CONFIG_HOME`, which GLib
ignores), but on macOS, when `~/.config/ART` does not exist and
`~/Library/Application Support/ART` does, the latter is used. Builds with a
`CACHE_NAME_SUFFIX` use `ART<suffix>`: point `ART_SETTINGS` at it.

## 6. Render server

### 6.1 Tools

From [Render server tool list and signatures](https://github.com/AhaiMk01/ART/issues/9).
Every image is named by its absolute, normalized path (resolved; case-folded
on Windows). Any tool except `open_image` on a path not opened returns
`not_open`.

| Tool | Args | Returns |
|---|---|---|
| `open_image` | `path?` or `paths?` (1 to 50), `profile?` | Working profile loaded (`profile_from`: `sidecar`, `default` or `profile`); metadata summary; ART version. With `paths` each image is opened the same way, with the same `profile` (6.2), up to two at once through the art-cli pool, progress per image: `items`, one `{path, profile_from, metadata \| error}` per path in request order (`path` as given, no `art_version`; no null fields) and `failed`; one bad image (`not_found`, a render failure) doesn't stop the others, a `profile` that is no file fails the call before any image opens. Both or neither of `path` and `paths`, an empty list or more than 50 is `out_of_range` |
| `get_profile` | `path`, `groups?`, `changed_only=false` | Read format (3.4), whole, of the `groups`, and/or only what differs from ART's default profile |
| `edit_profile` | `path?`, `adjustments?`, `raw_edits?`, `full=false`, `paths?`, `items?` | One of `path`, `paths` (1 to 50 open images, the same edit for each) or `items` (1 to 50 `{path, adjustments?, raw_edits?}`, each image its own edit); more than one or none is `out_of_range`. For `path` the change set (3.5): `changed`, `implied`, `created`, `drawn`, `warnings`; `full` adds the touched groups. For `paths` or `items` per image, in request order: `path`, `changed` (a count), `implied`, `warnings`, `error`; and `failed` (3.5) |
| `reset_profile` | `path?` or `paths?` (1 to 50 open images), `to: "sidecar" \| "default"` | Working-profile changes discarded. With `paths` each image is reset the same way, up to two at once, progress per image: `items`, one `{path, profile_from \| error}` per path in request order (`not_open`; `not_found` for `to: "sidecar"` without a sidecar; no null fields) and `failed`. Both or neither of `path` and `paths`, an empty list or more than 50 is `out_of_range` |
| `apply_preset` | `paths`, `profile`, `exclude?` | A preset (`.arp`, partial or complete) laid over the working profile of each open image (6.2), less the `exclude` entries (`Group` or `Group/Key`, as `save_partial_profile`'s), which are dropped from the preset first. Per image, in request order: `path`, `keys_changed`, `groups`, `error`; counts `applied` and `failed`; `excluded` (per entry, the preset keys it took out) |
| `render_preview` | `path`, `max_size=1024`, `region?`, `inline?`, `output?`, `overwrite=false`, `marks?` | JPEG path (+ `ImageContent` if inline); with `output` (absolute `.jpg` path, existing folder) the JPEG is written there and that is the path (`exists` unless `overwrite`); `warnings` only when there are any. `marks`: up to 64 `{x, y, size?, label?}` boxed and numbered on the picture, at frame pixels (below) |
| `export_image` | `path`, `output`, `format: "jpeg" \| "tiff" \| "png"`, `quality?` (jpeg only, 1..100), `bit_depth?` (jpeg `8`; png `8`\|`16`; tiff `8`\|`16`\|`16f`\|`32`; a number or a string, `16f` only as a string), `write_profile=false`, `profile_name: "output" \| "source"` (default `"output"`), `overwrite=false` | Output path, `.arp` path when written |
| `export_batch` | `items?` (`{path, profiles?}`) or `source?` (a folder; with `pattern?` and `profiles?`), `folder`, `format`, `quality?`, `bit_depth?`, `name="{stem}"`, `write_profile=false`, `profile_name="output"`, `overwrite=false` | Per image, in request (or file name) order: `path`, `output`, `profile_path`, `error`; counts `exported` and `failed` |
| `save_sidecar` | `path`, `on_conflict?: "merge" \| "overwrite" \| "cancel"` | `saved`, path, `how` (written/merged/overwritten/cancelled), or conflict + changed keys |
| `save_partial_profile` | `path`, `dest`, `overwrite=false`, `exclude=[]`, `vs: "opened" \| "default"` (default `"opened"`), `verbose=false` | `written`, path, `keys` written (`{Group: number}`; with `verbose` the list of `[Group] Key`), `total`, `vs` (the baseline used) |
| `inspect_image` | `path`, `tags?` | Fixed metadata fields + requested tags. `width`/`height` are what the file records; `frame_width`/`frame_height` the frame ART's `[Crop]` and `sample_spots` address (after coarse rotation and the raw border; a Sony ARW records 6048x4024, its frame is 6016x4016), measured like the crop checks (`whole_frame`), null if that fails. `iso`, `shutter_seconds`, `aperture` and `focal_length_mm` are those of the camera that took THIS file (6.4) |
| `inspect_images` | `paths`, `tags?`, `frame=false` | `inspect_image` for 1 to 100 open images in one call (`out_of_range` otherwise): `items`, one `{path, metadata, error}` per path in request order (`metadata` as `inspect_image` returns it, null when that image failed; `error` is `<code>: <message>`: `not_open`, `metadata_failed`) and `failed`; one bad image doesn't stop the others. exiftool runs once for all the files. `frame_width`/`frame_height` cost art-cli runs (two probes per image the first time, cached), so they are measured only with `frame=true`, through the same pool (at most 2 art-cli at once) with progress per image, else null |
| `describe_adjustments` | none | Curated schema + `PPVERSION` warning |
| `sample_spots` | `path`, `spots` (1 to 64), `size=32`, `space="working"` | Linear spot values (4.1), more than 16 spots in several `art-cli` runs, one result in request order; `unsupported` with a release `art-cli` |
| `image_stats` | `path?` or `paths?` (1 to 50), `max_size=1024`, `histogram=false`, `detail?: "compact" \| "standard" \| "full"` (default `standard`; `compact` with `paths`), `region?`, `bins?` | Per channel clipping and percentiles (`compact`), plus mean (`standard`), plus std, min, max, mode (`full`), optional `bins`/`histogram`, of the image or of a `region` of it; no null fields. With `paths`: `items` (`{path, stats \| error}` per image in request order) and `failed` (4.2); with `path` the statistics are the result's top level (`r`, `g`, `b`, `lum`, `width`, `height`, ...); with `paths` they are under `items[i].stats` (each item `{path, stats}` or `{path, error}`). |
| `suggest_neutrals` | `path`, `count=16`, `size=32`, `preview=false` | Candidate spots for neutral references (4.3): per candidate `x`, `y` (frame pixels), `level`, `saturation`, `flatness`, `why`; plus `area`, `size`, `cell`, `warnings`; with `preview` also `preview_path`, the analysed rendering as a JPEG with the candidates boxed and numbered 1..n. Render only |
| `contact_sheet` | `images`, `folder?`, `label?`, `columns?`, `thumb_size=400`, `record=true` | The next numbered pass in `<folder>/sheets` (6.5; `folder`: any existing folder you choose, not the exports folder; required unless an earlier call used one; with `record=false` a quick look instead, no pass kept: the sheet as a JPEG in the preview folder, `index`, `json_path` and `changes` null): sheet path, JSON path, per image `box`, `error` and `changed` (the number of profile keys changed since the last pass it was in), and `changes`, those changes grouped by identical change with the frames they were made on (the JSON has them per frame) |
| `compare_passes` | `first`, `second`, `folder?`, `images?`, `columns=2` | Path of a side-by-side of the same frames of two passes (6.5); `folder` is the one that holds `sheets`, as in `contact_sheet` |

`region` is `{x, y, w, h}` as fractions of the image as previewed: of the
working profile's crop when it has an enabled one, else of the whole frame
(the raw image after coarse rotation and the raw border). It renders that
area at 1:1 (still capped at `max_size`) through a temporary `[Crop]` layer;
the working profile is untouched. ART's `[Crop]` is in frame pixels, so the
frame size is measured once per image with two 1-pixel-strip `art-cli`
renders (~0.5 s each) and cached.

`marks` (both servers; `art_mcp/marks.py`, Pillow only) draws boxes on the
returned JPEG so that the positions a caller works with in frame pixels (the
spots it is about to give `sample_spots`, the candidates of `suggest_neutrals`,
a crop's corners) can be seen in the picture instead of being mapped by hand
(which put a spot on the wrong object in a test run):

- `marks`: up to 64 `{x, y, size?, label?}` (more is `out_of_range`). `x`, `y`
  are whole pixels of the frame, the coordinates of `sample_spots`, `crop` and
  `suggest_neutrals`, so that tool's candidates go in unchanged (their other
  fields are ignored); `size` is 2 to 256, default 32: the `size` x `size`
  square `sample_spots` would read, centred on `x`, `y`; `label` at most 4
  characters (else `out_of_range`). The number of a mark without a label is its
  position in the request, 1..n, counted also for marks that are not drawn. A
  mark whose centre is outside the whole frame is `out_of_range`, checked before
  anything renders.
- **Placement.** The picture shows an area of the frame: Render, the working
  profile's crop when it has an enabled one, else the whole frame, and with a
  `region` that region's rectangle (the one the temporary `[Crop]` layer
  has); Live, the whole frame (its size from `status`, after the preview has
  waited for ART's processing; unknown: `bad_reply`). A frame pixel (`fx`) is
  at `(fx - area.x) * picture_w / area.w` in the picture (the same for y), the
  picture being the JPEG as rendered, whatever its size, so it holds with
  `max_size`, `region`, a crop and a Live preview smaller than asked for. This
  is the mapping 4.1 gives for reading a preview, run the other way. A square
  is as many picture pixels as it comes to, rounded to the nearest, at least
  one, so its centre stays exact however small the preview. It is exact for the
  frame ART's `[Crop]` addresses; a profile whose fine rotation, perspective or
  lens corrections move the picture makes it approximate.
- **Outside.** A mark whose square lies wholly outside the previewed area (in
  the frame, but beyond the crop or the `region`) is not drawn; the result's
  `warnings` says how many and which (their request positions) and the area
  shown. A square that overlaps the area is drawn where it overlaps. A picture
  whose shape is not that of the area (more than the rounding of whole pixels
  explains) is warned about too: the marks may be misplaced, e.g. a Live editor
  showing a crop.
- **Drawing.** Per mark a ring of light pixels just outside the square and a
  ring of dark ones outside that (1 px wide; 2 from a long edge of 1500 px, 3
  from 2500), so it shows on dark and on light content and the pixels it marks
  are untouched, and a tab on the box's top left corner (below the box when
  there is no room above, inside it when there is none either; moved left to
  fit) with the label in light on a dark fill with a light edge, its text 11 to
  24 px by the picture size. Later marks are drawn over earlier ones; all rings
  first, then all tabs.
- **File.** The render goes to the preview folder as before, is read back,
  drawn on and saved again as a JPEG (quality 92, no chroma subsampling so the
  1 px rings stay clean, the colour profile kept) in the same file, and then
  moved to `output` if given; `inline` returns the marked picture. A render
  that cannot be read back is `render_failed` (Live: `bad_reply`) and nothing is
  left behind. The result has `warnings` only when there is one.

### 6.2 Working profile and sidecars

From [Sidecar write policy for the Render server](https://github.com/AhaiMk01/ART/issues/8).

- Edits accumulate in a **working profile**, in memory per server process,
  keyed by path, lost on restart.
- `open_image` seeds it from the image's sidecar, else from ART's default
  profile for that image type (same as the editor). A content hash of the
  sidecar is kept.
- `open_image(path, profile)` seeds it from an `.arp` file instead
  (`profile_from` `profile`), complete or partial: art-cli draws no line
  between the two, `-p` loads whatever keys the file has over the profile
  built so far, so the file goes over ART's default profile (`-d -p <file>`).
  A complete profile sets every value and so replaces; a partial one changes
  only its own. It is the profile `export_batch` renders for the same file in
  `profiles`. The image's sidecar is not read, written or hashed: with no
  baseline, a later `save_sidecar` finds an existing sidecar changed and
  raises the usual conflict (merge applies only the edits made after the
  open, not the file's values; overwrite replaces the sidecar). A missing
  file is `not_found`.
- `open_image(paths, profile)` opens each of 1 to 50 images that way (one
  `profile` for all, checked once before any image opens). The loads run
  through the art-cli pool (at most `max_processes` at once, each image under
  its own lock), and an image's metadata summary is read right after its load.
  The result is `{items, failed}`, one `{path, profile_from, metadata}` or
  `{path, error}` per path in request order; `art_version` is left out (one
  value for the session, in a single-image result), and the per-image
  `metadata` is kept because it is small (about 100 characters: camera, lens,
  capture date, pixel size). `reset_profile(paths, to)` reloads each image
  from `to` the same way, one `{path, profile_from}` or `{path, error}` each.
- To get the resolved, complete processing profile (default profile, dynamic
  rules, sidecar), `open_image` runs `art-cli` once (`-p <sidecar>` or `-d`,
  or `-d -p <profile>`; `-f`, `-O`) to a throwaway output and reads the `.arp` written beside it.
  The sidecar is passed with `-p` (not `-s`) so the file read is the file the
  server hashes and later saves. No resize layer is added: `-O` saves the
  layered profile, so a resize would leak into it (`-f`'s own resize is
  applied to a copy and doesn't). Later renders pass the working profile
  explicitly and never use `-d`. If ART is set to embed parameters in output
  metadata, `-O` writes no `.arp` and `open_image` fails with a hint.
- `apply_preset(paths, profile, exclude?)` puts a preset on frames that are already
  open without losing what each frame has of its own (its crop, its film
  reference spot, its rotation: whatever was set before). `open_image`'s
  `profile` can't: it starts the working profile over from the file.
  The file (partial or complete) is laid over each image's *current* working
  profile: the file's keys win, every other key stays. This is done by
  `art-cli` rather than by merging keys in Python, because ART's loader has
  per-group rules a key merge would miss (a file with `[Exposure]
  Enabled=false` also turns the highlight recovery off). `-d` is left out:
  the working profile is complete and goes first, so nothing under it needs
  ART's default (`-O -f -p <working profile as a temp .arp> -p <preset> -c
  <image>`, the `.arp` read from beside the throwaway output, as `open_image`
  does). The complete result replaces the working profile's contents. The
  bookkeeping is `edit_profile`'s, not `open_image`'s: the sidecar hash and
  keys (the baseline of `save_sidecar`'s conflict check) stay as loaded, and
  every value the preset changed is recorded as the agent's change since load
  (`WorkingChanges.layer`), so `save_sidecar`'s merge and
  `save_partial_profile` include them. A key the result lacks is dropped (ART
  replaces Color Correction regions wholesale); a partial profile can't say
  so, except that region keys are then sent whole. A complete preset sets
  every key it has, `[Crop]` included; a roll or group preset is a partial
  profile from `save_partial_profile` with the per-frame settings excluded.
  `exclude` takes that tool's entries (`"Group"` or `"Group/Key"`, parsed by
  the same code, `profile.split_exclusion`) and drops them from the preset
  *before* it is layered, so a preset saved on a representative frame
  (`vs="default"` carries its exposure, tone curve and offsets too) can go to
  the other frames of its group without those keys: each frame keeps its own.
  The preset file is parsed (a file that does not parse is `out_of_range`),
  the entries removed (a group left without keys goes too), and the rest
  written to a copy in the preview folder, which is what art-cli layers; the
  copy is removed when the call ends and the file is never changed. The
  result's `excluded` maps each entry to the number of preset keys it took
  out; 0 says the preset had none of that. Unlike `save_partial_profile`, whose
  entries must be in the working profile, an entry that took nothing out of
  the preset (so cannot be checked against it) must at least name a group or
  key of the image's processing profile, else it is that image's
  `unknown_key` (a typo is caught, an exclusion of a key this preset happens
  not to have is a no-op, so one list serves several presets). A preset
  that excludes everything layers an empty file: nothing changes. Exclude
  Color Correction as the whole `ColorCorrection` group, not by single region
  keys: ART reads the regions a file lists wholesale, so a region short of
  some keys would get their defaults.
  Each image is handled under its own lock (the profile art-cli reads is the
  one that is replaced), up to `max_processes` at once like `export_batch`,
  with progress per image. A problem with the call is `not_found` (the file
  is missing or unreadable) or `out_of_range` (`paths` empty); a problem with
  one image (`not_open`, a render failure) is its result's `error`, its
  working profile is untouched and the others still apply. A result is a count
  of the values changed and the groups they are in, not the values (a preset
  has about a hundred; `get_profile` reads them). The Live server has no
  equivalent: its `open_image(profile=)` already layers over the editor's
  current state.
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
- `save_partial_profile` writes a partial profile to `dest`; refuses an
  existing file unless `overwrite=true`; writes nothing when there is nothing
  to write (also when `exclude` removes everything). The result's `keys` is
  compact: how many keys each `[Group]` got (`{"Exposure": 3, "Film Negative":
  2}`, in the file's order) and `total`, since a frame with a Color
  Correction region has about 95 keys, about 7 KB as a list of `[Group] Key`
  entries; `verbose=true` makes `keys` that list instead (`total` stays). The
  count and the list describe the same keys as the file. Which keys is `vs`,
  the baseline they are measured against (the result's `vs` says which was
  used; any other value is `out_of_range`):
  - `"opened"` (default): only the keys the agent changed since the profile was
    loaded or last saved with `save_sidecar`. What the profile came with (its
    sidecar, or the preset of `open_image`'s `profile`) counts as not
    changed, so a preset saved from a frame opened from another preset lacks
    that preset's keys.
  - `"default"`: the keys whose value differs from ART's default profile for
    the image (`session.default_profile`, the cached `art-cli -d` run
    `get_profile`'s `changed_only` uses), whatever the profile was opened from.
    Values are compared as the strings stored, so a key re-set to the default's
    value is not written. A key only the default has (the working profile
    dropped it) is not written either: a partial profile cannot unset a key,
    ART leaves a key it doesn't list as the image has it. A key only the
    working profile has is written. `[Version]` is never written: it says which
    ART wrote the profile, and a partial profile without it is read as the
    current version, which is what the complete values in it are. As with
    `"opened"`, one changed `[ColorCorrection]` region key carries every region
    key. The first call per opened image runs art-cli for the default
    (`render_failed`, `timeout`); `"opened"` never does.

  `exclude` (either `vs`) lists `"Group"` or `"Group/Key"` entries left out of
  the file; a group or key not in the working profile is `unknown_key`
  (`profile.check_exclusions`; `apply_preset`'s `exclude` shares the entry
  syntax and `profile.drop_excluded`, 6.2).
  Settings that belong to one image (e.g. `Crop`) are usually excluded from a
  preset meant for other images; which ones for a film roll is in the
  `film-negative` skill. The tool description says this generically and points
  at the skills. The Live server has no `save_partial_profile`.
- `export_image` renders the working profile as it is, saved or not. It writes
  a `.arp` beside the output only with `write_profile=true` (art-cli `-O`).
  `profile_name="source"` (with `write_profile`; also on `export_batch`) names
  that file after the image instead, in the output's folder, the way ART
  names the image's sidecar (`IMG.ARW.arp`, or `IMG.arp` with the user's
  strip-extension option; `artdir.sidecar_path`), so a folder of exports can
  double as a sidecar set. The same `overwrite` rule covers it. The sidecar
  next to the image is never written: an output folder that is the image's
  own is `out_of_range` (even with `overwrite`; per item in a batch). Two
  batch items cannot name the same sidecar without also naming the same
  output, which already fails the call before rendering.
- `export_batch` exports many images in one call: `items` (each its working
  profile, or `.arp` layers over ART's default, which needs no open image),
  or `source`, a folder whose raw, jpeg and tiff images (ART's default parsed
  extensions, no subfolders) are taken in file name order, narrowed by
  `pattern` (a glob on the file name, any case), each with the call's
  `profiles` layers or its working profile. A problem with the call (format,
  folder, items and source together, names that collide) fails it before
  anything renders; a problem with one image is that image's result and the
  others still run, up to `max_processes` art-cli at once. An image is never
  exported over itself.

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

`inspect_images` runs exiftool once for all the files (`-j -n file1 file2 ...`
as an argument file on stdin, one array back), matches each record to its file
by `SourceFile` and parses it as `inspect_image` does. A file exiftool can't
read (not found, an `Error:` line naming it) is that image's `metadata_failed`;
an invalid tag name, an exiftool that can't start or time out (30 s plus half a
second per further file), or output that isn't JSON fails the whole call. An
exiftool that is not found fails the call with `metadata_unavailable`.

Whose exposure: ISO, shutter, aperture and focal length are those of the
camera that took THIS file. For a negative photographed on a light table
(a Sony ILCE-7M3 `.ARW` with a manual lens, exposure program Manual) they are
the digitising camera's settings, not the film's original exposure, which the
file does not carry; they are what scales the scan's linear values (the
scan-exposure normalisation of the `film-negative` skill) and nothing else. A
manual lens records aperture 0, reported as null: the exposure factor then
uses shutter and ISO only.

### 6.5 Contact sheets

From [Contact sheets of a batch, kept per pass](https://github.com/AhaiMk01/ART/issues/45).

Judging a roll means looking at all its frames together, over several passes
(inversion, roll ratios, per-frame white balance, black points), and the
agent and the user want to see what each pass changed. `contact_sheet` renders
the frames and keeps every pass; it is a Render-server tool because the
working profiles live there.

- **Thumbnails** go through the preview path (`art-cli -f`, a resize layer,
  JPEG), not the full-size export of `export_batch`, because they are small;
  the pool is the batch's: up to `max_processes` at once, a failing image is
  that image's `error` (a placeholder on the sheet), progress per finished
  image. Working profiles are copied when the call starts. A call where no
  image renders saves nothing.
- **The sheet** is composed with Pillow (`contactsheet.py`, no ART): each
  frame fitted and centred in a `thumb_size` box, cells as high as the tallest
  frame, the file name under it, a title line (pass, label, time), a neutral
  dark grey ground. `images` entries are paths or a folder, which stands for
  the open images directly in it. The result warns when the sheet is longer
  than Claude shows (2576 px).
- **Passes** are `<folder>/sheets/pass-NN[-label].jpg` and `.json`, `NN` one
  more than the highest in the folder (so numbering survives a restart), the
  label slugged for the file name and kept as given in the JSON. Files are
  created exclusively under a lock on the folder: a pass is never overwritten
  and overlapping calls get different numbers; a pass that cannot be written
  completely leaves nothing.
- **What changed.** Per image the JSON has `changes`: every profile value that
  differs from the last pass the image was in (`since_pass`), as `{group, key,
  before, after}`; null the first time. That needs the earlier complete
  profile, which a pass JSON would bloat (hundreds of keys per frame), so
  `sheets/profiles.json` keeps the latest complete working profile per image
  (as ART wrote it) and is rewritten each pass. It is bookkeeping, not a
  record; a server restart loses nothing. A frame whose render failed still
  counts: its profile was recorded.
- **Numbers in `changes`** are shown with at most seven significant digits
  (`%.7g`, what a 32-bit float holds). ART keeps many numbers as 32-bit floats
  and writes them back as doubles with 17 digits: the `6450.7` an agent typed
  returns as `6450.7001953125`, `1.37` as `1.3700000047683716`
  (`1.3700000000000001` is another spelling), which costs context, says no more
  than `6450.7`, `1.37`, and is not a change. A value that is a number, or a
  `;`-separated list (a curve, `r;g;b;`), has each decimal token shown that
  way; an integer and any other text stay as written (a token is numeric only
  if it is a plain integer or decimal: not `nan`, `inf`, `1_000`, a token with
  spaces, or a number too big for a double). Two values are the same when they
  are the same text, or lists of the same number of tokens (a final `;` is the
  list's end, not a token: an agent types `a;b`, art-cli writes `a;b;`) each
  the same text or the same number. Two numbers are the same when they are
  equal (`1` and `1.0`) or differ by less than a millionth of the larger one
  (`6450.7` and `6450.7001953125`; a float32 is within 6e-8 of the decimal typed
  for it, and 1e-6 still tells an edit in the sixth digit); two integers are
  compared exactly, and a zero is the same only as a zero (`0` and `1e-9` differ,
  the difference being relative). A same value is never a change; the shown
  digits resolve every difference that counts. Normalising and comparing are
  pure functions (`sheet_changes.py`).
- **The result is a summary** of those changes, not the per-frame lists (in a
  real 12-frame pass the lists were most of a 10,000-character reply, more than
  the sheet cost): per image `changed`, the number of changes (null when there
  is nothing to compare with), and a top-level `changes`, the changes grouped
  by identical change (same group, key, before and after, after normalising),
  `{group, key, before, after, images}` with the file names of the frames it was
  made on in sheet order. Groups are sorted by how many frames share them, then
  by group, key, before, after, and the first 25 (`MAX_SHARED_CHANGES`) are
  listed; `more` counts the rest and a `warnings` entry then points at the pass
  JSON, which always has every change per frame. `changes` is null when no
  frame had an earlier pass (a first pass); it is `{groups: [], more: 0}` when
  some did and nothing differs. A frame with nothing to compare with counts for
  nothing; frames compared with different earlier passes (`since_pass`) are
  grouped together.
- **Where.** `folder` is where a `sheets` subfolder is created: any existing
  folder the caller chooses, for example the work folder; not the exports
  folder, the passes would mix with the exports (the old wording, "the batch's
  output folder", and the default of the last `export_batch` folder made a roll
  test pass the folder above its `export` folder instead). There is no guessed
  default: without `folder` the call is
  `out_of_range` and the message says what `folder` is, unless an earlier
  recorded `contact_sheet` call in this session saved a pass in one, kept in the
  session; that folder is then the default of `contact_sheet` and
  `compare_passes` (the last one used, whichever call). An `export_batch` never
  sets or changes it, and a sheet never lands next to the source images, in an
  export folder or in the temp folder by default. A call that saves no pass
  (`record=false`, a missing folder, nothing rendered) does not set it.
- **`record=false`** is the quick look: judging a few frames used to cost a
  preview and a file read each (a roll test made 28 previews and 32 reads),
  while the sheet is one image. It renders and composes the same sheet
  (thumbnails, grid, labels; `label` is in the title) but keeps nothing of a
  pass: no number, JSON, `profiles.json` update or comparison (`index`,
  `json_path`, `changes` null; `changed`, `since_pass` null per image), and
  `folder` is neither needed nor used. The JPEG is a new file in the preview
  folder (`sheet-NNNN.jpg`), so it goes with the server like a preview and
  never into the source or output folders. `columns` defaults to
  `ceil(sqrt(frames))` narrowed so the sheet is at most 2576 px wide
  (`quick_columns`; a pass keeps min(frames, 6)): 4 frames at 1000 px are 2 by
  2, 6 frames at 700 px 3 by 2, and `columns` overrides it.
- **`compare_passes(first, second)`** cuts the frames out of the two passes'
  sheets (the JSON's `box` says where each sits), puts each pair side by side
  (first left) at the smaller `thumb_size` and saves `compare-NN-MM.jpg` in
  `sheets`, `-2`, `-3` for a repeat. `images` (paths or file names) picks the
  frames; the default is every frame rendered in both passes. A named frame
  that was not is `not_found`.

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
| `get_profile` | `path`, `groups?`, `changed_only=false` | Read format (3.4), whole, of the `groups`, and/or only what differs from ART's default profile, + `history_position` (selected History row, 0 = oldest; null if none) |
| `edit_profile` | `path?`, `adjustments?`, `raw_edits?`, `full=false`, `paths?`, `items?` | The change set (3.5) + `history_position`; returns once the undo entry exists. With `paths` (1 to 50 images, instead of `path`) the per-image entries of 3.5, each with its `history_position`: one undo entry per image, none for an image that already had the values. With `items` (1 to 50 `{path, adjustments?, raw_edits?}`, instead of `path` and `paths`; each image its own edit) the same entries, one per item, applied one after the other in request order: one undo entry per item that changed something, two items for one image two entries |
| `undo` / `redo` | `path` | New History position |
| `render_preview` | `path`, `max_size=1024`, `inline?`, `output?`, `overwrite=false`, `marks?` | JPEG path + width/height; waits until ART's processing queue drains (30 s, else `timeout`). The editor's preview (~600 px wide, whole frame, uncropped) shrunk to fit `max_size`, never enlarged. `marks`: as 6.1, on the whole frame (its size from `status`); `warnings` only when there are any |
| `open_image` | `path?` or `paths?` (1 to 50), `profile?` | ART's name for it, `already_open`, `profile_applied`; returns once ART has loaded it (60 s, else `timeout`) and, with `profile`, applied it. With `paths` each image in turn, waiting for each to load, with the same `profile` (checked once before any image is opened): `items`, one `{path, already_open, profile_applied}` or `{path, error}` per path in request order (`path` as given; no null fields) and `failed`; an image that fails (`not_found`, `timeout`, ART's refusal of the profile) doesn't stop the others. Both or neither of `path` and `paths`, an empty list or more than 50 is `out_of_range` |
| `save_sidecar` | `path` | The sidecar written (editor's own save), null when ART keeps profiles in its cache only; `write_failed` when nothing was written |
| `queue_export` | `path`, `folder?`, `format?`, `name?`, `quality?`, `bit_depth?`, `profile?` | `queued` (entries in ART's export queue), `running`. Queues the open image through the GUI's own batch queue with its current profile (no sidecar written); output as `export_image` (named `-1`, `-2` when taken: ART's rule), `profile` an `.arp` over the working profile |
| `queue_start` | none | `running`, `already_running`; `empty_queue` when nothing is queued |
| `queue_status` | none | `running`, `auto_start`, `entries`: path, `output`, `state` (`queued`/`processing`/`failed`), `progress`, `error` |
| `describe_adjustments` | none | As Render server |
| `inspect_image` | `path`, `tags?` | As Render server (Python + exiftool; no C++); `frame_width`/`frame_height` come from `status`, null until the editor has the size |
| `inspect_images` | `paths`, `tags?` | As Render server's (1 to 100 images in one call, one `{path, metadata, error}` each, one exiftool run); the images are matched against one `status` reply (`not_open` per image), `frame_width`/`frame_height` from it, null until the editor has the size (there is no `frame` option: nothing is measured) |
| `sample_spots` | `path`, `spots` (1 to 64), `size=32`, `space="working"` | As Render server, from the open editor (4.1); more than 16 spots are asked for in several requests, one after the other (the op takes 16) |
| `image_stats` | `path?` or `paths?` (1 to 50), `max_size=1024`, `histogram=false`, `detail?`, `region?`, `bins?` | As Render server, from the editor's preview; with `paths` one preview per image in turn, a failing image is its item's `error` (4.2) |

- `get_profile` returns the profile as the editor holds it (`ipc->getParams`,
  as ART's own sidecar save does), so it includes what the engine resolved:
  the camera white balance's temperature/green, the automatic deconvolution
  radius, the disabled crop filled with the full frame. These can differ from
  the Render server's values for the same file, which come from the saved
  profile. `changed_only` compares this profile with ART's default profile
  (3.4), which the Live server resolves with `ART-cli` (found like the Render
  server's, `--art-dir`/`ART_DIR`; without one `changed_only` is
  `unsupported`), so those resolved values are listed as changed even when the
  user changed nothing. Paths go to ART absolute but unresolved (links and `subst` drives
  as given), because ART matches the name it opened the file under.
- History: one entry per `edit_profile` (per image with `paths`, per item with `items`); ART shows it as
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
  `queue_add`, `queue_start`, `queue_status` (the export queue),
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
  With `profile` (an `.arp`, complete or partial) it then sends the file as
  `apply_profile`, labelled `Agent: <file name>`: one History entry over what
  the editor holds (the sidecar's or default profile; the current one, with
  the user's changes, if the image was open already), which undo reverts and
  which doesn't write the sidecar. ART refuses `[Version]` in an applied
  profile, which a complete one carries, so the Python side drops it. The
  file is read and parsed before ART is asked to open anything
  (`not_found`, `bad_request`); if ART then refuses the values the image
  stays open and the error says so.
  `save_sidecar` is `EditorPanel::saveProfile` and returns the sidecar path
  (null when ART keeps profiles in its cache only).
- The queue ops use the GUI's `BatchQueue` as it is: `queue_add` makes the
  entry as the queue button does (`EditorPanel::createBatchQueueEntry`, the
  editor's current profile, the optional partial profile over it) without
  saving the sidecar, sets the entry's own output name and format as the
  Save-as dialog does (`outFileName`, `forceFormatOpts`; without them the
  queue's panel settings apply) and adds it through `RTWindow` so
  "auto start" works. Entries are the Queue tab's: the user can reorder
  and cancel them, and they persist as normal entries. Per-entry state is
  read from the queue (`BatchQueue::entryStatuses`). A failed export (a
  source that can't be loaded, an output that can't be written or its
  folder created) records its message on the entry (`BatchQueueEntry::error`,
  also in its tooltip), moves it behind the others and the queue carries on
  with the next entry (`BatchQueue::failProcessing`); it stops when only
  failed entries are left, and a start tries those again. Before, a failed
  load stopped the queue, and a failed save left it "running" with the
  entry stuck (and an output folder that couldn't be created dropped the
  entry unexported).
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
- Optional args: `--art-dir`, `--inline-previews`. Optional environment:
  `ART_MCP_CALL_LOG` (2.1).

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
| `fixed_ratio` | bool | | | true (keeps `ratio` when the rectangle is edited in ART; `false` = free rectangle) |
| `ratio` | enum | ART's ratio list (`3:2`, `4:3`, `16:9`, `1:1`, ... see `crop_ratios` in `src/gui/crop.cc`) | | `As Image` |
| `orientation` | enum | `Landscape`, `Portrait`, `As Image` | | `As Image` |

ART's defaults (`fixed_ratio` true, `ratio` `As Image`) keep a fixed aspect
ratio: the editor's crop tool re-fits the rectangle to the ratio when it is
edited (`Crop::adjustCropToRatio`, `src/gui/crop.cc`), so a free rectangle
needs `fixed_ratio: false`. The engine does not enforce it: `art-cli` (and the
Render server) use a complete x, y, w, h as given; the ratio only shapes the
default rectangle when none is set (`CropParams::setDefaultGeometry`,
`src/engine/procparams.cc`) and the perspective auto-crop.

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
| `center_x`, `center_y` | int | -100 .. 100 | % of image width / height, offset from centre: the centre is W/2 + x/100 * W, so 100 is a whole width away, outside the frame (unlike mask positions, which are % of half; `src/engine/iptransform.cc`) | 0 |

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
`edit_profile` returns the `drawn` line of each `curve1`/`curve2` it set (3.5)
and adds a warning for each one whose drawn line clips to 0 (`curve2 clips to 0 for x 0.02-0.07`), goes above 1, or reverses
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

**color_correction** -> `[ColorCorrection]`

ASC CDL-like grading (cast removal, per-channel contrast, split toning, faded
film), on regions in RGB mode. Values are linear working-space values (0..1 =
0..65535). Per channel ART computes `v = v * slope + offset / 2`, then
`v = (v / pivot) ^ (1 / power) * pivot` (`src/engine/ipcolorcorrection.cc`;
pivot 1 unless raw-edited): the slope acts **before** the power, and the stored
`power` is the **inverse** of the exponent applied (power 0.5 squares the
channel), as the GUI shows it.

| Field | Type | Range / values | Default |
|---|---|---|---|
| `enabled` | bool | (`Enabled`) | false |
| `regions` | list | by position, region 1 = `regions[0]`; entries are a region or `null` | |

A **region** is `{"r": c, "g": c, "b": c, "mask": m}` (all optional); a channel
`c` is `{slope, offset, power}`:

| Field | Range | Default | Key (region n) |
|---|---|---|---|
| `slope` | 0.01 .. 10 | 1 | `Slope<R/G/B>_n` |
| `offset` | -0.15 .. 0.15 | 0 | `Offset<R/G/B>_n` |
| `power` | 0.1 .. 4 | 1 | `Power<R/G/B>_n` |

The **area mask** `m` is `{enabled, inverted, feather, blur, shapes}`
(`AreaMaskEnabled_n`, `MaskInverted_n`, `AreaMaskFeather_n` 0..100,
`AreaMaskBlur_n` 0..500). `inverted` flips the mask: the region then affects
everything outside its shapes. A shape is typed by `type`:

- `rectangle`: `x`, `y` -100..100 (% of the image's half width / height:
  -100 = left / top edge, 0 = centre, 100 = right / bottom edge), `width`, `height` 1..200 (% of the image's, 100 = the
  whole image; the GUI's minimum, ART's header says 0), `angle` degrees
  (-180..180; the GUI allows 0..180), `roundness` 0..100 (100 = ellipse),
  `feather` 0..100 (`ShapeFeather`), `blur` 0..500 (`ShapeBlur`), `mode`
  `add`/`subtract`/`intersect`. Defaults: 0, 0, 100, 100, 0, 0, 0, 0, `add`.
- `gradient`: `x`, `y` -100..100 (as rectangle), angle 0 runs top to
  bottom, `strength_start` / `strength_end` 0..100,
  `angle` -180..180, `feather`, `blur`, `mode`. Defaults: 0, 0, 100, 0, 0, 25,
  0, `add`.

Shape feather is a blur radius of `feather` % of the shape's smaller half
size (`src/engine/masks.cc`), so a large feather also reaches into the shape
(on a 110% ellipse, feather 60 changes pixels well inside it). Shape i is
stored as `AreaMask<X>_n` for i = 0 and `AreaMask_i_<X>_n` for i > 0
(`Type`, `X`, `Y`, `Width`, `Height`, `Angle`, `Roundness`, `Mode`,
`ShapeFeather`, `ShapeBlur`; gradients `StrengthStart`, `StrengthEnd` in place
of `Width`..`Roundness`).

Editing:

- Regions and shapes are matched **by position**; an entry changes only the
  keys it gives. A `null` region or shape skips that position. The first entry
  past the end appends a region or shape (further is `out_of_range`, naming the
  next free index: ART's loader drops a shape whose keys are incomplete).
  A shape entry whose `type` differs from the stored shape replaces it. There
  is no deleting a region or shape (raw edits).
- Setting `r`/`g`/`b` on a region not in RGB mode switches it to RGB (`Mode_n`,
  implied); giving a `mask` field sets `AreaMaskEnabled_n` true unless `enabled`
  says otherwise (implied); anything turns `Enabled` on (implied).
- **Complete key sets.** ART's loader replaces all regions with the ones a
  profile lists and gives every missing key its default (a missing `Mode_n`
  means Jzazbz), and it skips a mask shape with a missing key. So a new region
  is written with every key ART's saver writes (`Region::Region()` and
  `Mask::save` in `src/engine/procparams.cc`; the 82 keys of a default region
  taken from a real default profile, `REGION_DEFAULTS` in
  `art_mcp/colorcorrection.py`) with `Mode_n=RGB`, and a new shape with all
  its keys. The edit result lists the keys the request set in `changed` and
  counts the rest, at their defaults, under `created` (3.5), so a new region
  does not echo its 80 default keys. For the same reason a partial profile (`save_partial_profile`, Live's
  `apply_profile`) in which any `[ColorCorrection]` region key changed carries
  every region key (a layer of changed keys alone drops edits when ART loads
  it).
- Raw edits keep the rule that a key must exist; a typed adjustment may create
  keys (a new region, a new shape).

Reading: `get_profile` gives `enabled` and `regions` with one entry per
region: a region in RGB mode whose mask is only an area mask of rectangles and
gradients (and `MaskCurve`, `AreaMaskContrast`, `MaskPosterization`,
`MaskSmoothing`, `MaskOpacity` at their defaults) is typed (always with a
`mask`); any other region (YUV, HSL, Jzazbz or LUT mode; parametric, deltaE,
drawn, linked or external masks; polygon shapes; a turned-off mask) is `null`
and **all** its keys stay under `raw`. A typed region's remaining keys (pivots,
compression, other-mode keys, unused masks) stay under `raw`. ART's default
region 1 is in Jzazbz mode, so a fresh profile reads `regions: [null]`. A
typed edit of such a region (values, or a mask on a region with a supported
mask) works; changing the mask of a region with an unsupported one is
`out_of_range` (use raw edits).

**film_negative** -> `[Film Negative]`

Fields mirror the stored values 1:1 (no GUI-slider conversion):

| Field | Key | Type / range | Default |
|---|---|---|---|
| `enabled` | `Enabled` | bool | false |
| `color_space` | `ColorSpace` | `working` (stored `1`) / `input` (`0`) | `working` |
| `red_ratio` | `RedRatio` | 0.3 .. 5 | 1.36 |
| `green_exponent` | `GreenExponent` | 0.3 .. 4 | 1.5 |
| `blue_ratio` | `BlueRatio` | 0.3 .. 5 | 0.86 |
| `ref_input` | `RefInput` | `[r, g, b]`, each >= 0, linear 0..65535 | `[0, 0, 0]` (unset) |
| `ref_output` | `RefOutput` | `[r, g, b]`, each >= 0 | `[0, 0, 0]` (unset) |

ART (`src/engine/filmnegativeproc.cc`, `doProcess`): per channel
`out = min(mult_c * in_c ^ exp_c, 65535)` with
`exp = -(green_exponent * (red_ratio, 1, blue_ratio))` and
`mult_c = ref_output_c / max(ref_input_c, 1) ^ exp_c`, so a pixel equal to
`ref_input` comes out as `ref_output`. `in` is the negative's value (higher =
a darker part of the scene), in the working space or the camera's input space
per `color_space`; it is what `sample_spots` returns (same `space`). A
reference whose green is <= 0 is unset: ART then estimates `ref_input` from
the channel medians of the central 60% of the input (20% border cut) and uses
65535/24 grey for `ref_output`. Ranges are the GUI's `Adjuster` ranges
(`src/gui/filmnegative.cc`). References are written as `r;g;b` (numbers to 10
significant digits); a `ref_input` equal to the stored one is no change.

**Picker rule** (computed, ART's own: `FilmNegative::button1Pressed`). When a
request sets `ref_input` to a value different from the stored one (green > 0)
and gives no `ref_output`, the server sets `RefOutput` = `L;L;L` (listed under
`implied`) so the image keeps its brightness:

- `L` is the Rec.709 luminance (0.2126729, 0.7151521, 0.0721750) of what the
  profile **as it is before the request** renders the new `ref_input` as:
  `out_c = min(mult_c * max(new_c, 1) ^ exp_c, 65535)` with the *stored*
  exponents, `RefInput` and `RefOutput` (an unset `RefOutput` counts as 65535/24
  grey). Only the new `ref_input` comes from the request: a ratio or exponent
  changed in the same request does not alter `L`, since the new reference maps
  to grey `L` whatever the exponents are.
- If the stored `RefInput` is unset, ART's medians stand in for it. The server
  **estimates** them by sampling: a grid of 8 x 8 = 64 `sample_spots` squares
  of 64 px (4 calls of 16), one per cell of the frame minus the 20% border on
  each side, in the stored `ColorSpace`; per channel the median of the 64
  averages (the mean of the two middle ones). A warning says it is an
  estimate (a median of block means, not of pixels) and lists the medians.
  Render samples with `art-cli -x` from the working profile, Live through the
  channel's `sample_spots` op from the editor's profile. This sampling lives
  in the service layer (`render/profile_ops.py`) and the Live adapter, with
  the pure maths in `art_mcp/filmnegative.py`; `profile.py` receives the
  result (`WorkingChanges.edit(..., film_estimate=)`).
- If sampling is unavailable (a release `art-cli`: `unsupported`; or Live has
  not reported the image's size), `RefOutput` becomes grey 65535/24
  (2730.625) and a warning says the brightness may change.
- An explicit `ref_output` in the request wins and nothing is computed (no
  sampling). A raw edit of `RefOutput` also wins.

Legacy profiles (`BackCompat` 1/2, `RedBase`/`GreenBase`/`BlueBase`) are not
typed: `get_profile` leaves all their keys under `raw`, and typed
`film_negative` edits other than `enabled` are `out_of_range`.
