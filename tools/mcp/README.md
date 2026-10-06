# ART MCP servers

MCP servers that let AI agents (Claude Code, Claude Desktop) work with ART.
Design: [`docs/specs/mcp-servers.md`](../../docs/specs/mcp-servers.md).

- **`art-mcp-render`**: opens images and renders previews headlessly through
  `art-cli`, and reads metadata with ART's exiftool. Changes stay in an in-memory working profile; renders never write
  sidecars.
- **`art-mcp-live`**: talks to a running ART editor through its control
  channel. Start ART with `--live-control` (it then writes
  `live-control.json` with a port and a per-run token to its config folder,
  and removes it on exit). Tools so far: `status()` (ART's version and the
  images open in the editor, with sizes), `sample_spots` and `image_stats` (as on the Render server, from the open editor: `sample_spots` samples the profile it holds, unsaved edits included; `image_stats` analyses its preview saved as PNG); without a control-enabled ART it
  fails with `art_not_running`.

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and an ART install
(found via `--art-dir`, `ART_DIR`, `PATH`, then the usual install location:
the newest `C:\Program Files\ART\<version>` on Windows, `ART.app` in
`/Applications` or `~/Applications` on macOS, `/usr/local/bin`, `/usr/bin`,
`~/.local/bin` or `/opt/ART*` on Linux; details in spec section 5).

## Install

Claude Code picks the servers up from the repo's `.mcp.json` when you open the
fork (approve them on first use). Elsewhere:

```sh
claude mcp add art-render -- uv run --directory <repo>/tools/mcp art-mcp-render
claude mcp add art-live -- uv run --directory <repo>/tools/mcp art-mcp-live
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "art-render": {
      "command": "uv",
      "args": ["run", "--directory", "C:/path/to/ART/tools/mcp", "art-mcp-render"]
    }
  }
}
```

## Tools

| Tool | Does |
|---|---|
| `open_image(path?, profile?, paths?)` | Loads the image's processing profile (sidecar, else ART's default profile) as its working profile (`profile_from`: `sidecar` or `default`); also returns a short `metadata` summary (camera, lens, capture date, pixel size), or null if exiftool is unavailable or can't read the file. `profile`: an `.arp` file, complete or partial, to start from instead (`profile_from` `profile`; `not_found` if there is no such file): it is laid over ART's default profile as art-cli's `-d -p` does (so a complete profile gives all its values, a partial one only its own, and `export_batch`'s `profiles` render the same), for opening every image of a set from its preset. The image's own sidecar is neither read nor written; a later `save_sidecar` therefore finds an existing sidecar changed and asks (`conflict`). Live: opens the image in ART, then applies the file over the editor's profile (the sidecar's or default, or the current one if the image was already open) as one History entry `Agent: <file name>` that `undo` reverts; `[Version]` is left out; the result's `profile_applied` is the file. `paths` (1 to 50 images, instead of `path`; both or neither is `out_of_range`) opens each one the same way, with the same `profile` for all, and returns `{items, failed}`: per image, in request order, `{path, profile_from, metadata}` (`path` as given; `metadata` as for one image, left out when there is none; no `art_version`: it is one value per session, from a single-image call) or `{path, error}` (`not_found`, a render failure), the others still open; a `profile` that is no file fails the call (`not_found`) before any image opens. Render: art-cli runs through the same bounded pool as the other batch tools (up to two at once), progress per image. Live: sequentially, waiting for each to load (up to the open timeout, a `timeout` error for that image), items `{path, already_open, profile_applied}` or `{path, error}`. For a roll: one call instead of one per frame (about a second per image: 10 to 15 per call where the client's tool timeout is short, 30 s) |
| `inspect_image(path, tags?)` | Metadata of an opened image from `exiftool` (`-j -n`; found beside `ART-cli`, else on PATH, else in the system's usual install locations (spec section 5), so a fork build without one still works): make, model, lens, ISO, `shutter_seconds`, `aperture`, `focal_length_mm`, `capture_date` (local, ISO 8601), `width`, `height` (the size the file records, e.g. 6048x4024 for a Sony ARW), `orientation` (EXIF 1-8), each null when absent; `frame_width`, `frame_height` are the frame ART works in (6016x4016 for that ARW: after coarse rotation and the raw border), the space `crop` and `sample_spots` coordinates are in, so size a crop from these (Render measures them with art-cli the first time, about a second, null if that fails; Live takes them from the editor, null until it has loaded the image); `tags` adds named exiftool tags (e.g. `Software`) that the file has, under `tags`. ISO, shutter, aperture and focal length are those of the camera that took THIS file: for a negative digitised on a light table, the scanning camera's, not the film's original exposure (the file does not carry that; it is not needed); a manual lens records aperture 0, reported as null |
| `inspect_images(paths, tags?, frame=false)` | `inspect_image` for 1 to 100 images in one call, with one exiftool run for all of them: `items`, one `{path, metadata, error}` per path in request order (`metadata` as `inspect_image` returns it; an image that is not open, or that exiftool can't read, is its own `error` while the others still come back) and `failed`. Render: every path must be an opened image; `frame_width`, `frame_height` cost art-cli runs (about a second per image the first time, two at once, progress per image), so they are measured only with `frame=true`, else null. Live: the images must be open in ART; the frame size comes from the editor, null until it has loaded the image (no `frame` option) |
| `render_preview(path?, max_size=1024, region?, inline?, output?, overwrite=false, marks?, paths?)` | Renders the working profile to a JPEG and returns its path; `output` (an absolute `.jpg` path, folder must exist) writes it there instead of the server's temp folder, `exists` unless `overwrite`; see [Previews](#previews). `marks` (up to 64 `{x, y, size?, label?}`, in frame pixels like `sample_spots` and `crop`) boxes and numbers those positions on the picture, so one call shows where the spots you are about to sample (or `suggest_neutrals` candidates) sit. To look at many frames at once, `contact_sheet(record=false)` is one image instead of one preview each. Render only: `paths` (1 to 16 open images, instead of `path`) renders each the same way (the same `max_size`, `region`, `inline`), two at a time with progress per image, and returns `{items, failed}`: per image, in request order, `{path, preview_path}` or `{path, error}` (`not_open`, a render failure) while the others still render; inline, each rendered image also comes back as an image block, in that order. `marks`, `output` and `overwrite` go with one `path` and are `out_of_range` with `paths`; so is `path` together with `paths`, or neither, an empty list or more than 16 |
| `get_profile(path, groups?, changed_only=false)` | The working profile: curated tools typed under `adjustments`, every other value as a string under `raw` (each value once). A whole profile is about 15k tokens: `groups` (`[Group]` names as in `raw`, e.g. `["Film Negative", "ToneCurve"]`; an unknown one is `unknown_key` listing the valid ones) reads only those, `changed_only` only the values that differ from ART's default profile for the image (details below the table) |
| `edit_profile(path?, adjustments?, raw_edits?, full=false, paths?, items?)` | Changes the working profile of one image (`path`), the same change to several (`paths`: 1 to 50 open images) or a different change to each (`items`: 1 to 50 `{path, adjustments?, raw_edits?}`); exactly one of the three, else `out_of_range` (see below the table). Takes typed, range-checked `adjustments` (`exposure`, `white_balance`, `crop`, `rotation`, `local_contrast`, `sharpening`, `denoise`, `vignetting`, `lens_profile`, `tone_curve`, `color_correction`, `film_negative`; `crop` is checked against the image's size; a free rectangle needs `fixed_ratio: false`, see the crop entry of `describe_adjustments`) and/or `[Group] Key` raw edits; all or nothing. Returns the change set only (`changed`, `implied`, `created`, `drawn`, `warnings`; `full` adds the touched groups, and only then is there a `profile` field); `implied` lists the changes not asked for (a disabled tool gets enabled; White Balance switches to `CustomTemp`; `histogram_matching` turned off when a curve is set; a computed `RefOutput`, see `film_negative`); `created` names a new Color Correction region or mask shape with the number of its keys ART filled in at their defaults (`{"ColorCorrection": ["region 2 (78 keys at their defaults)"]}`), which `changed` doesn't list. The input schema is compact (about 16,600 characters, down from 30,000): no titles, defaults or ART keys, units folded into the descriptions, repeated shapes under `$defs`; `describe_adjustments` has the full documentation |
| `describe_adjustments()` | The curated adjustments with their full documentation: fields, ranges, units, defaults, the `[Group] Key` each sets, and the `PPVERSION` the schema targets |
| `reset_profile(path?, to, paths?)` | Reloads the working profile from the `sidecar` or ART's `default` profile. `paths` (1 to 50 open images, instead of `path`; both or neither is `out_of_range`) resets each the same way, up to two at once, progress per image, and returns `{items, failed}`: per image, in request order, `{path, profile_from}` or `{path, error}` (`not_open`; `not_found` when `to` is `sidecar` and the image has none), the others still reset. Render only |
| `apply_preset(paths, profile, exclude?)` | Lays the `.arp` at `profile` (partial or complete) over the working profile of each image in `paths` (all open): the file's keys win and every other value (crop, reference spot, rotation, earlier edits) stays, which `open_image`'s `profile` doesn't do (it starts over from the file). Done by art-cli (`-p <working profile> -p <file>`, no default profile under them), so ART's own loading rules apply (a file with `[Exposure] Enabled=false` also switches highlight recovery off); a complete profile sets every key it has, its `[Crop]` included. The changes count as the agent's, like `edit_profile`'s: `save_sidecar` still compares with the sidecar the image was loaded from, and `save_partial_profile` includes them. Per image, in request order: `path`, `keys_changed`, the `groups` they are in (the values are not listed: `get_profile` reads them) or an `error` (`not_open`, a render failure) while the others still apply; counts `applied` and `failed`. A missing or unreadable `profile` is `not_found`, empty `paths` `out_of_range`. `exclude`: `"Group"` or `"Group/Key"` entries (the same as `save_partial_profile`'s) dropped from the preset before it is laid over the frames, so a preset made on a representative can go to the others without its per-frame settings (its `Exposure/Compensation`, its tone curve): the frames keep theirs. art-cli layers a filtered copy of the file; the file is not touched. The result's `excluded` says what each entry took out of the preset (0: it had none of that); an entry that is in neither the preset nor the image's profile is that image's `unknown_key`. Up to two art-cli processes at once, progress per image; for a roll, see the `film-negative` skill |
| `export_image(path, output, format, quality?, bit_depth?, write_profile=false, profile_name="output", overwrite=false)` | Renders the working profile at full size as `jpeg` (quality 1..100, 8 bit), `png` (8/16 bit) or `tiff` (8/16/16f/32 bit) to `output` (its folder must exist); an existing `output` is refused unless `overwrite`; `write_profile` also saves `<output>.arp`, otherwise none is written; `profile_name="source"` names that profile after the image instead (`IMG.ARW.arp`, or `IMG.arp` with ART's strip-extension option) in the output's folder, ready to reopen the image with; the image's own sidecar is never written (an output in the image's own folder is `out_of_range`, even with `overwrite`) |
| `export_batch(items?, source?, pattern?, profiles?, folder, format, quality?, bit_depth?, name="{stem}", write_profile=false, profile_name="output", overwrite=false)` | Exports many images into `folder` as `<name>` (`{stem}` = image file name without extension). Give `items` or `source`. Each item `{path, profiles?}` exports its working profile (must be open), or the `profiles` `.arp` files layered over ART's default (no need to open). `source` is a folder: every raw, jpeg or tiff image directly in it (ART's default parsed extensions; not subfolders), in file name order, narrowed by `pattern` (a glob on the file name, any case); the top-level `profiles` are layered over ART's default for each, else each is exported with its working profile (must be open). Per-image results: one failing image doesn't stop the others; colliding names fail the call before rendering; an image is never exported over itself (`exists`). With `write_profile` and `profile_name="source"` the folder ends up holding a ready-to-use sidecar set (`IMG.ARW.arp` beside each image's export); an image that lives in `folder` itself fails on its own (its real sidecar is never written). Runs up to two art-cli processes at once and reports progress per image; a full-size render takes about a second, so where the client's tool timeout is short (30 s) export 10 to 15 images per call (a call the client gave up on keeps running and writes its files) |
| `contact_sheet(images, folder?, label?, columns?, thumb_size=400, record=true)` | `record=false`: a quick look at several frames, one image to read instead of a preview per frame: the same sheet saved as no pass (no number, JSON, `profiles.json` update or comparison; `folder` not needed or used) as a JPEG in the server's temp folder; `columns` defaults to a near-square grid (2 for 2 to 4 frames, 3 for 5 to 9, as wide as the 2576 px Claude shows allow), `index`, `json_path` and `changes` are null. Otherwise renders the open `images` (paths, or a folder standing for the open images in it) from their working profiles as small thumbnails and saves a labelled grid (file name under each frame) as the next numbered pass, `<folder>/sheets/pass-NN[-label].jpg`, with `pass-NN[-label].json` beside it: the images, label, time and per image the profile keys changed since the last pass it was in (numbers with at most 7 significant digits; the same 32-bit float, `6450.7` and `6450.7001953125`, is no change). The result carries a summary of those changes, not the per-frame lists: per image `changed` (a count) and `changes`, grouped by identical change with the frames it was made on. Earlier passes are never overwritten, so any two can be compared. `folder` is where the `sheets` subfolder is created: any existing folder you choose, for example your work folder; do not use the exports folder (the passes would mix with the exports). Without `folder` the call is `out_of_range`, unless an earlier `contact_sheet` call in this session used one (then that is the default); never an export folder; the result's `path` is the sheet to open (with `--inline-previews` the sheet also comes back as an image block). One failing image is a placeholder and an error in its entry. Same render pool and progress as `export_batch`; see [Contact sheets](#contact-sheets) |
| `compare_passes(first, second, folder?, images?, columns=2)` | Puts the same frames of two passes side by side (cut from their sheets; `images`: paths or file names, default every frame rendered in both) and saves `compare-NN-MM.jpg` beside the passes (a repeat gets `-2`, `-3`); returns its `path`. `folder` is the folder that holds the `sheets` subfolder (the one given to `contact_sheet`, not `sheets` itself); default: the folder the last `contact_sheet` call in this session used, else `out_of_range`; with `--inline-previews` the image also comes back as an image block |
| `queue_export(path, folder?, format?, name="{stem}", quality?, bit_depth?, profile?)` | Live only. Puts an image open in ART into ART's own export queue (the Queue tab) with its current profile (the sidecar is not saved); with `folder` and `format` the output is `<folder>/<name><suffix>`, else the queue's own folder, template and format apply. ART never replaces a file: a taken name gets `-1`, `-2` (unless its Preferences overwrite). `profile`: an `.arp` file layered over the working profile for this export. Starts by itself when the queue's "auto start" is on |
| `queue_start()` | Live only. Starts ART's export queue (`empty_queue` when it has no entries) |
| `queue_status()` | Live only. `running`, `auto_start`, and the entries in order with `state` (`queued`, `processing`, `failed`), `progress` and `error`. Exported entries leave the queue; a failed one goes to the end and the queue carries on with the others (it stops when only failed ones are left); `queue_start` tries them again |
| `save_sidecar(path, on_conflict?)` | The only tool that writes the sidecar (named per ART's strip-extension option): atomic, previous one kept as `<sidecar>.bak`. If the sidecar changed on disk since it was loaded, asks the user (merge / overwrite / cancel) when the client supports elicitation; else fails with `conflict` listing the changed keys, and the agent calls again with `on_conflict`. `merge` applies only the agent's changed keys onto the current sidecar. Afterwards the saved file is the new baseline |
| `save_partial_profile(path, dest, overwrite?, exclude?, vs?, verbose=false)` | Writes a partial profile to `dest`; `exists` error if `dest` exists unless `overwrite`; writes nothing if there is nothing to write. The result's `keys` is compact: `{Group: number of keys written}` in file order, plus `total` (a frame with a Color Correction region has about 95 keys, about 7 KB as a list); `verbose=true` makes `keys` the list of every `[Group] Key` instead. `vs` (the result says which was used): `"opened"` (default) writes only the keys the agent changed since load or the last save, so keys the profile came with (its sidecar, or `open_image`'s `profile`) are not in it; `"default"` writes every key that differs from ART's default profile for the image (not `[Version]`), so a preset saved from a frame opened from another preset carries that preset's settings too (any other value: `out_of_range`). `exclude`: `"Group"` or `"Group/Key"` entries left out (unknown name: `unknown_key`); settings that belong to one image (e.g. `Crop`) are usually excluded from a preset for other images; set-wide presets: see the skills below |
| `sample_spots(path, spots, size=32, space="working")` | What ART's own spot pickers read: for 1 to 64 `{x, y}` frame pixels per call (the coordinates of `[Crop]`), `avg` and `max` `[r, g, b]` of the `size` x `size` square (2 to 256), linear 0..65535, white-balanced, before any film inversion; `space` `working` or `input`. Out-of-frame spots are `out_of_range`; more than 16 spots are sampled in runs of at most 16 (Render: `max_processes` `art-cli` at once, Live: one request after the other) and come back as one result in request order, the frame measured once; a failing run fails the call (no partial result) with its error, which says which spots it covered; `space` `working` is the working profile's working space, `input` camera space. Step-by-step workflows (film negatives, faded slides): see the skills below. Needs an ART build with spot sampling (`art-cli -x`; a release `art-cli` gives `unsupported`: point `--art-dir`/`ART_DIR` at the fork) |
| `image_stats(path?, paths?, max_size=1024, histogram=false, detail?, region?, bins?, lum_min?, lum_max?)` | Renders like a whole-image preview (8-bit PNG, crop applied; a holder, a border or bright lamps in the image count in clipping and percentiles, so crop first, or give a `region`; Live's preview is uncropped) and returns per channel `r`, `g`, `b`, `lum` (0.2126 R + 0.7152 G + 0.0722 B, rounded to the nearest 8-bit value): `clipped_high`/`clipped_low` (fraction at 255/0) and `percentiles` (nearest rank on the 256-bin histogram), as many numbers as `detail` says: `"compact"` (percentiles 0.1, 50, 99.9 %; about 450 characters), `"standard"` (the default for one `path`: adds `mean` and percentiles 1, 5, 95, 99; about 700) or `"full"` (adds `std`, `min`/`max` (lowest/highest value present) and `mode` (most frequent value, the lowest on a tie)). `bins` (only when asked: 8, 16, 32 or 64 fractions of pixels in equal groups of values, dark to light; 16 shows the shape, e.g. a clipped end or a second hump) and `histogram` (256 counts, only when asked) add their fields at any detail; a field that carries nothing (`bins`, `histogram`, `region`) is left out, never null. Also the rendered image's `width`/`height`. `region` `{x, y, w, h}` (fractions of the image as the tool shows it, the same rectangle as `render_preview`'s) measures just that part of the same render; the result's `region` is its pixel rectangle (at least 16 pixels, else `out_of_range`). `lum_min`/`lum_max` (0 to 255, the scale of `lum`; either alone is fine) limit every number to the pixels whose `lum` lies in that band, ends included, within the `region` when one is given: `lum_max` leaves out lamps and speculars so `clipped_high` judges the rest, `lum_min` a black border, and a band of the shadows or the mid-tones gives the colour cast of just that range; `in_band` is the fraction of the measured pixels that the band holds (left out without a band; at least 16 pixels, else `out_of_range`, as for a limit outside 0 to 255 or `lum_min` above `lum_max`). `paths` (1 to 50 images, instead of `path`: neither or both is `out_of_range`) measures many images in one call, the other arguments the same for all, and returns `{items: [{path, stats | error}], failed}` in request order; an image that fails (not open, a render error) is its item's error and the others still come back; `detail` then defaults to `"compact"`. The result's shape differs: with `path` the statistics are the result's top level (`r`, `g`, `b`, `lum`, `width`, `height`, ...); with `paths` they are under `items[i].stats` (each item `{path, stats}` or `{path, error}`). Render renders them two at a time (the `export_batch` pool) with progress per image; Live asks the editor for each in turn (without ART running the whole call is `art_not_running`) |
| `suggest_neutrals(path, count=16, size=32, preview=false)` | Render only. Proposes where to look for neutral (grey/white) references: flat, low-saturation, mid-level cells of the current rendering (like a whole-image preview: crop applied, the outer 3% of a crop or 10% of an uncropped frame left out), up to 16 spread over the luminance range and the frame, sorted dark to light. Each has `x`, `y` (the centre in frame pixels, as `sample_spots` and `crop` use: pass the candidates to `sample_spots` unchanged), `level` (0..255), `saturation` (HSV, 0 = grey), `flatness` (luminance std over mean, 0 = flat) and a short `why`; plus the analysed `area` [x, y, w, h], the `cell` side and `warnings` (no crop, fewer candidates than asked). With `preview=true` the result also has `preview_path`: a JPEG of the rendering that was analysed (about 1600 px) with the candidates boxed and numbered 1..n in the order of the list (and the image itself with the result when the server was started with `--inline-previews`), so one call shows what each candidate sits on. A pre-filter, not an oracle: neutrality is decided by the material, which only looking tells, so look and check with `sample_spots`; "neutral" only means something once the rendering is roughly colour-correct. Rule: spec 4.3 |

A whole `get_profile` is about 15k tokens (over 500 keys), which adds up over a
roll. `groups` returns only the named `[Group]`s (a curated tool is in when a
group its fields live in is), and `changed_only` only what differs from ART's
default profile for the image (the one `open_image` starts from without a
sidecar; whatever is not listed equals it); together they combine. The default
is resolved with one `art-cli -d` run the first time `changed_only` needs it
for an opened image, then kept (Render: until the image is reopened or reset; Live: for
the life of the server, and only if `ART-cli` was found through `--art-dir`,
`ART_DIR`, `PATH` or the install location, else `unsupported`). The Live
editor's resolved values (the camera white balance's temperature and green, the
full-frame rectangle of a disabled crop) are not in the default, so they show
up as changed there.

`edit_profile` returns the change set, not the profile:

```json
{"changed": {"Film Negative": {"RedRatio": "1.335"}, "RAW Bayer": {"Method": "amaze"}},
 "implied": {"Film Negative": {"Enabled": "true"}},
 "drawn": {"curve1": [[0, 0], [0.125, 0.0112], "...", [1, 1]]},
 "warnings": []}
```

`changed` and `implied` are `[Group]` -> `Key` -> new value (the shape of
`raw`); a key is in one of them, never both (`implied`: not asked for; re-setting
a value is not a change). `created` is `[Group]` -> descriptions of what the
call created, each with the number of keys ART filled in at their defaults:
`region 2 (78 keys at their defaults)`, `region 2 mask shape 0 (5 keys at their
defaults)` (regions count from 1, shapes from 0, as the request's lists do);
those keys are in the profile but not in `changed`, which has only the ones the
request set (and `implied` the ones it caused). `drawn` is the line ART draws for each tone curve the
call set (as `get_profile` reads it back, so no read is needed after a curve).
`full=true` adds `profile`, the groups the call touched in the `get_profile`
format; it is several times the rest of the result (without it the field is
left out, not sent as `null`). The Live server adds `history_position`.

With `paths` (1 to 50 open images, instead of `path`; both or neither is
`out_of_range`, as is `full`) the same edit goes to every image, each its own
change (Live: its own History entry, labelled as for one image), and the
result is one compact entry per image instead of a change set each:

```json
{"items": [{"path": "A.ARW", "changed": 2, "implied": {"Film Negative": {"Enabled": "true"}}, "warnings": [], "error": null},
           {"path": "B.ARW", "changed": null, "implied": {}, "warnings": [], "error": "not_open: B.ARW is not open; call open_image first"}],
 "failed": 1}
```

`changed` counts the values asked for that changed in that image (0: it had
them already; Live then makes no History entry); the values are not listed, so
use one image's call to see them. An image that can't take the edit (not open,
a key it lacks, a crop outside its frame, any error a single-image edit has)
is its own `error`, `<code>: <message>`, its profile is untouched and the
others still change. Live's entries also carry `history_position`. Render runs
up to two images at once. For a set (a roll's base settings, its ratios, a
group's output level): one call instead of one per frame.

With `items` (1 to 50 entries `{path, adjustments?, raw_edits?}`, instead of
`path` or `paths`; more than one of the three, or none, is `out_of_range`, as is
`full`, and an `adjustments` or `raw_edits` beside `items`: they go in each
item) each image gets its own edit, for the values that differ per frame (its
white balance, its reference and level, its black point), and the result is the
same compact `{items, failed}`: one entry per item, in request order, with the
path as given. Each item is its own change as for `paths` (Live: its own History
entry), and one that fails is its own `error` while the others still change.
Two items for the same image are applied in order, each as its own change (Live:
its own History entry), so the second sees what the first set; items for
different images run as above (Render: up to two images at once). The item has
exactly `path`, `adjustments` and `raw_edits`; any other field is a schema error
before anything changes.

`color_correction` grades RGB-mode regions (`regions[0]` is ART's region 1; a
`null` entry is a region that isn't typed, other modes and non-area masks stay
under `raw`): each region has `r`/`g`/`b` `{slope, offset, power}` and an
optional `mask` (area mask: `inverted`, `feather`, `blur`, `shapes` of
`rectangle` or `gradient` in ART's own coordinates: position -100..100 from edge to edge,
0 = image centre; width/height 100 = the image's size). Values are linear working-space: per channel
`v = v*slope + offset/2`, then `v = (v/pivot)^(1/power)*pivot`: the slope acts
before the power and the stored `power` is the inverse of the exponent (0.5
squares the channel). An inverted mask affects everything outside its shapes.
Regions and shapes are matched by position and the first one past the end
appends; a new region or shape is written with every key ART saves (ART's loader
would skip an incomplete one), the ones the request doesn't set at ART's
defaults, which the result counts under `created` instead of listing. Setting `r`/`g`/`b` switches the region to RGB mode
and turns the tool on (listed as `implied`).

`film_negative` has the stored values as fields: `enabled`, `color_space`
(`working`/`input`), `red_ratio`, `green_exponent`, `blue_ratio` and the
references `ref_input`/`ref_output` as `[r, g, b]` (linear 0..65535 in the
negative's terms; `[0, 0, 0]` = unset, ART estimates it from channel medians
and maps those to 65535/24 grey). Per channel `out = mult * in ^ exp`, `exp =
-(green_exponent * (red_ratio, 1, blue_ratio))`, `mult_c = ref_output_c /
ref_input_c ^ exp_c`. Picker rule (ART's own): a request that changes
`ref_input` without `ref_output` gets `ref_output = (L, L, L)` under `implied`
so the image keeps its brightness; `L` is the Rec.709 luminance of what the
profile as it is before the request renders the new `ref_input` as (a ratio
changed in the same request does not alter it). With an unset current
reference the medians are estimated by sampling 64 spots in the central 60% of
the frame (`art-cli -x` on Render, the channel's `sample_spots` on Live), with
a warning; where sampling is unsupported `ref_output` becomes grey 65535/24
with a warning. An explicit `ref_output` wins. Legacy profiles (`BackCompat`,
`RedBase`) stay under `raw`.

`tone_curve` takes `mode`, `mode2` (omitted = same as `mode`; `get_profile`
always reports the effective one), `histogram_matching`, `contrast` (-100..100: ART's
analytic contrast curve, a power curve pivoting on middle grey 0.18 or Log
Encoding's target grey, never overshooting; use it for an S-curve instead of
curve points), and `curve1`/`curve2` as `{"type": "spline"|"catmull_rom"|"nurbs", "points": [[x, y], ...]}` (2 to 32
points in 0..1, x strictly increasing) or `{"type": "linear"}`. x and y are sRGB-gamma-encoded
0..1, roughly `image_stats` 8-bit values / 255. Curves read back as
`{"type", "points", "drawn"}`; parametric or unparseable curves stay under `raw`.
`drawn` is the line ART's curve editor draws through the points (a port of ART's
own `DiagonalCurve`): `[x, y]` at x = 0, 0.125, ..., 1, y to 4 decimals (`null`
for a NURBS with 3+ points, which isn't computed; omitted for `linear`). It is
read-only: sending it back is allowed and ignored, so `get_profile` output
round-trips; `edit_profile` returns the `drawn` line of each curve it set. A
spline can wiggle or overshoot, so `edit_profile` warns for a
curve it set that clips to 0 or goes above 1 (ART clamps only below 0) or
reverses, with the x range (e.g. `curve2 reverses for x 0.86-0.95`). ART
resamples the curve before applying it, so `drawn` is close, not bit-exact, to
what the image gets.

Errors come back as tool errors whose text starts with a code: `not_open`,
`not_found`, `unknown_key`, `render_failed`, `timeout`, `conflict`, `exists`,
`out_of_range` (adjustment value outside its range, or a spot outside the frame; nothing is clamped), `unsupported` (the ART build lacks spot sampling), and
for metadata `metadata_unavailable` (no exiftool beside
ART-cli, on PATH or in an ART install), `metadata_failed`, `invalid_tag`.

`render_failed` carries art-cli's exit code with its meaning (`-3` bad
arguments, `-2` load/save or options failure, `-1` unknown option, `1` stray
argument, `2` no input or skipped extension) and its output; an art-cli that
exits 0 without writing the file is `render_failed` too.

Robustness: art-cli is killed and the call reports `timeout` after 60 s
(`--preview-timeout SECONDS`; `--export-timeout SECONDS`, default 120, is for
exports). Calls about one image run one at a time, and at most two art-cli
processes run at once. On startup the server deletes `art-mcp-<pid>` folders
in the temp folder whose process is gone.

Results of `get_profile`, `edit_profile` and `describe_adjustments` carry a
`warnings` list when ART's profile version is newer than the schema's
(`PPVERSION` 1045); edits keep working.

## Previews

`render_preview` writes a JPEG (quality 85) into `%TEMP%/art-mcp-<pid>/` and returns its path.

- `max_size` (1 to 2576, default 1024): long edge in pixels. 2576 is the most Claude
  displays without downscaling. Anything else is `out_of_range`.
- `region` `{x, y, w, h}`: fractions (0 to 1) of the image; renders just that area at
  1:1 through a temporary `[Crop]` layer, shrunk only to fit `max_size`. The working
  profile is untouched. Fractions are of the image as previewed: of the working
  profile's crop when it has an enabled one, else of the whole frame (the raw image
  after coarse rotation and the raw border). The frame size is measured with two
  1-pixel-strip art-cli renders (about 0.5 s each) and cached per image file.
- `output` (Live too): an absolute path to a `.jpg` (its folder must exist) to write the
  preview to instead of the temp folder; the result's `path` is that file and the
  server keeps no copy. An existing file is `exists` unless `overwrite=true`; the
  image itself is never replaced (`exists`), a relative path or another extension is
  `out_of_range`. Checked before anything renders.
- `inline`: true also returns the image as an MCP image block, next to the path (it is
  shown directly, no file read); false returns the path only. Default: the
  `--inline-previews` launch flag (off unless given), so `claude mcp add art-render --
  uv run --directory <repo>/tools/mcp art-mcp-render --inline-previews` turns it on for
  every call.
- `marks` (Live too) `[{x, y, size?, label?}]`, up to 64: draws a box on the preview at
  each FRAME-pixel position, the coordinates `sample_spots`, `suggest_neutrals` and `crop`
  use, so a `suggest_neutrals` candidate goes in unchanged. `size` (2 to 256, default 32)
  is the square `sample_spots` would read; the box is a light ring just outside it and a
  dark one outside that (readable on dark and on light content; what is inside the square
  stays as it is) with a tab on its top left corner that says the mark's number, 1..n in
  request order, or its `label` (at most 4 characters). A square is at least one preview
  pixel, so its centre is where the spot is at any preview size. A mark outside the
  frame is `out_of_range`. Render: marks are placed on what the preview shows, so with a
  crop or a `region` the positions shift and scale with it, and a mark wholly outside
  it is not drawn (`warnings` counts them and says which). Live: the editor's preview
  shows the whole frame, whose size comes from the editor. The picture is re-saved as a
  JPEG (quality 92, colour profile kept); the result carries `warnings` only when there
  is something to say, among them that the picture is not the shape of the area it should
  show (then the marks may be misplaced). `suggest_neutrals(preview=true)` draws the same
  boxes on the rendering it analysed.
- Looking at several frames: one `contact_sheet(record=false)` (see below) is one image
  to read instead of a preview and a read per frame.
- Fast export (`art-cli -f`, about twice as fast, but it resizes before processing so
  sharpening and local effects are approximated) is used only for whole-image previews
  whose `max_size` fits your fast-export box (ART preferences, default 1920; the
  smaller side of `fastexport_resize_width`/`height` in `options`). `region` previews
  and bigger previews render without it.

## Contact sheets

`contact_sheet` is for judging a whole roll at a glance and keeping a record of
how it got there. Each call is one *pass*:

```
<folder>/sheets/
  pass-01-first-inversion.jpg      the grid (JPEG, quality 85)
  pass-01-first-inversion.json     what the pass holds
  pass-02-roll-ratios.jpg / .json
  compare-01-02.jpg                compare_passes(1, 2)
  profiles.json                    bookkeeping (below)
```

- Frames are rendered like a whole-image preview (`art-cli -f`, long edge
  `thumb_size`, 32 to 1024, default 400) from the working profiles as they are
  when the call starts, up to two at a time. `columns` frames per row (default
  6, at most 20); the sheet gets a title line (pass, label, time) and each frame
  its file name. Claude shows at most 2576 px on the long edge: a bigger sheet
  carries a `warnings` entry, and fewer images or a smaller `thumb_size` keeps
  the frames full size.
- `record=false` makes the same sheet as a quick look and keeps nothing of a
  pass: no number, no JSON, no `profiles.json` update, no comparison with
  earlier passes (`changes`, `index` and `json_path` are null; `changed` and
  `since_pass` null on every image), and `folder` is neither needed nor used.
  The JPEG is a new file in the server's own temp folder, named and removed
  like a preview (`%TEMP%/art-mcp-<pid>/sheet-NNNN.jpg`). `columns` then
  defaults to a grid about as wide as high, `ceil(sqrt(frames))`, narrowed so
  the sheet is at most 2576 px wide: 2 to 4 frames in 2 columns, 5 to 9 in 3
  (2 at `thumb_size` above 848), so 2 to 6 frames at `thumb_size` 700 to 1000
  read as one image with one file read. Pass `columns` to choose.
- Numbers come from the files already in `sheets` (highest + 1), so a new
  server process carries on. The label becomes part of the file name
  (letters, digits and `_`; anything else turns into `-`) and is kept as given
  in the JSON.
- The JSON: `index`, `label`, `time` (local, ISO 8601), `sheet`, `thumb_size`,
  `columns`, `width`, `height` and `images`, each with `path`, `name`, `box`
  (`[x, y, w, h]` of its frame on the sheet), `error`, `since_pass` and
  `changes`: the `{group, key, before, after}` of every profile value that
  differs from the last pass this image was in (`[]` when none, null the first
  time). Values are shown normalised: a decimal (also each `;`-separated
  token of a curve or `r;g;b;` list) with at most 7 significant digits (what a
  32-bit float holds), so ART's `1.3700000000000001` and `6450.7001953125`
  read `1.37` and `6450.7`; integers and other text as they are. ART keeps
  many numbers as 32-bit floats and writes back a different spelling of the
  number typed (`6450.7` comes back as `6450.7001953125`), which is not a
  change: two numbers that differ by less than a millionth of the larger one
  are the same value (integers are compared exactly; a zero is only the same
  as a zero), and so are two lists of equal tokens with or without the final
  `;`. `profiles.json` holds each image's complete
  working profile as of that pass, as ART wrote it, which is what the next
  pass is compared with; it is rewritten each pass and is not a pass record.
- The tool result is smaller than that JSON: the images carry `changed`
  (the number of `changes` they have, null when there is nothing to compare
  with) instead of the lists, and the result's `changes` groups the identical
  change made on several frames into one entry,
  `{group, key, before, after, images: [file names]}` (`images` null for a change made on every
  frame of a pass of more than 4 frames: the names would only repeat), the most shared first
  (then by group and key), at most 25 entries with `more` counting the rest
  (a `warnings` entry then names the JSON, which has every change per frame).
  A first pass (or one where no image had an earlier pass) has `changes` null
  and `changed` null on every image; with earlier passes but no difference it
  is `{"groups": [], "more": 0}`. A frame new to the roll counts for nothing
  in it.
- A pass is never overwritten: files are created exclusively and an
  unwritable pass leaves nothing behind. Two overlapping calls get different
  numbers.
- Where: `folder` is where the `sheets` subfolder is created: any existing
  folder you choose, for example your work folder. Do not use the exports
  folder: the passes would mix with the exports. Without `folder` the call
  fails with `out_of_range` and says so, unless an earlier `contact_sheet`
  call in this session saved a pass in one (then that folder is the default,
  for `compare_passes` too); the folder of an `export_batch`, the source
  images' folder and the temp folder are never a default.

## Skills

`skills/` holds Claude skills that teach an agent a workflow with these tools
(workflow knowledge that stays out of the tool descriptions, which describe the tools generically):

| Skill | For |
|---|---|
| `film-negative` | Inverting camera-scanned colour negatives with ART's Film Negative tool: base settings, fitting the colour ratios from `sample_spots`, reference spot, output level, a whole roll |
| `faded-slide` | Restoring faded colour slides: per-channel power-law fit against neutrals with `color_correction`, edge fading with masked regions |

Install for Claude Code by copying or symlinking the skill folder into your
user skills (all projects) or a project's skills:

```sh
# user level
mkdir -p ~/.claude/skills
cp -r <repo>/tools/mcp/skills/<skill> ~/.claude/skills/
# or: ln -s <repo>/tools/mcp/skills/<skill> ~/.claude/skills/<skill>

# one project
mkdir -p <project>/.claude/skills
cp -r <repo>/tools/mcp/skills/<skill> <project>/.claude/skills/
```

On Windows (PowerShell) use `Copy-Item -Recurse` into `$HOME\.claude\skills`
(a symlink needs developer mode or an admin shell). Restart Claude Code; the
skill loads when a request matches its description (e.g. "invert this negative
scan", "fix the colour of this faded slide"). The skills need the `art-render` server above (and an ART build with
`sample_spots`).

## Measuring a run

To see what an agent really did with the tools, whatever client drove it (Claude Code, omp,
another), set `ART_MCP_CALL_LOG` to a file in the environment the client starts the servers
with (`claude mcp add -e ART_MCP_CALL_LOG=<file> ...`, or `env` in the server's `.mcp.json`
entry). Both servers then append one JSON line per tool call, when the call ends; they can
share one file. Without the variable nothing is logged and nothing is added to the server.

```json
{"t":"2026-10-05T10:00:02.500Z","server":"art-render","tool":"edit_profile","ms":31.4,"ok":false,"error":"out_of_range","args":{"path":"C:\\raws\\a.ARW","raw_edits":[["group","key","value"],["group","key","value"],"...+10"]},"result_chars":212,"images":0,"in_flight":2}
```

- `t` is when the call arrived (UTC, milliseconds); `ms` how long it took, to completion
  (an async tool such as `export_batch` or `contact_sheet` included); `in_flight` how many
  tool calls were being handled when it started, itself included, so parallel calls show up.
- `ok` and `error`: the leading code of a tool error (`not_open`, `out_of_range`, ...), or
  `invalid_arguments` (the schema refused the arguments), `unknown_tool`, `exception` (the
  tool crashed), `cancelled`; null when `ok`.
- `result_chars` is the length of the result's text as the client gets it (the compact JSON
  of the structured result, else the text content), `images` the number of image contents:
  what each call cost the agent to read.
- `args`: the argument names with their values cut down: strings to 120 characters, lists to
  their first two items and `"...+<more>"`, dicts to their key names. Nothing from the
  environment is logged.
- A log that can't be written (an unwritable path) is reported once on stderr and the
  calls carry on; a missing folder is created.

```sh
uv run --directory <repo>/tools/mcp python -m art_mcp.calllog summarise <file>
```

prints the calls and wall time (first arrival to last completion), the number of tools used,
the most calls in flight at once, the images, calls, errors, result characters and time per
tool (most calls first), the largest results, the first five errors with their codes, and
the SEQUENCE of tools in order of arrival with runs collapsed
(`open_image x12, edit_profile x12, ...`). `--json` prints the summary as JSON.

To compare two runs, summarise each and read the reports side by side: the totals line, the
per-tool table and the sequence show at a glance which tools one agent used that the other
did not, how often it looked (`render_preview`, `contact_sheet`), what it asked for and
where it failed, and whether it overlapped calls.

## Development

The typed curated-tool modules (`curves.py`, `colorcorrection.py`, `filmnegative.py`)
live at the package root next to `schema.py`/`profile.py` and hold the tool-specific
compile/read/maths, while `profile.py` stays pure. `contactsheet.py` composes the
sheets and `marks.py` draws the marks of `render_preview` and `suggest_neutrals` (both
Pillow only).

Layout of the Render server (`art_mcp/render/`), in three layers:

- **Operations** (plain Python, no MCP): `session.py` holds `RenderSession`
  (per-image locks, running art-cli, the frame measurement) over a
  `ProfileStore` (`store.py`; `MemoryStore` keeps the working profiles, the
  loaded baseline for save's conflict check and the frame-size cache in the
  process, another store can keep them elsewhere). The `*_ops.py` modules
  (`profile_ops`, `preset_ops`, `preview_ops`, `export_ops`, `save_ops`, `metadata_ops`,
  `sampling_ops`, `sheet_ops`) hold one function per tool, taking the session first and the
  tool's arguments, returning the tool's Pydantic result and raising
  `RenderError(code, message)` (`errors.py`). Callable without MCP.
- **Tools**: the `*_tools.py` modules each have a `register(server, session)`
  adding thin MCP adapters over those operations (`adapter.py` turns a
  `RenderError` into the tool error `<code>: <message>`). What only MCP can
  do stays here: inline preview images, asking the user about a save
  conflict.
- **Wiring**: `server.py` builds the session and registers the tools.

An operation reaches a working profile only through `with session.image(path)
as wp:`, which holds that image's lock; after changing one it calls
`session.commit(wp)`.

```sh
uv run pytest                      # unit + fake-art-cli tests
uv run ruff check art_mcp tests    # lint (rules in pyproject.toml)
ART_MCP_TEST_RAW=/path/to/raw uv run pytest tests/test_integration_art.py
```

The integration tests copy the raw to a temp folder and are skipped when ART or
`ART_MCP_TEST_RAW` is missing. `tests/test_integration_exiftool.py` runs the real
exiftool on a generated JPEG (and, with `ART_MCP_TEST_RAW`, on the raw, read-only)
and is skipped when no exiftool is found.
