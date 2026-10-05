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
| `open_image(path)` | Loads the image's processing profile (sidecar, else ART's default profile) as its working profile; also returns a short `metadata` summary (camera, lens, capture date, pixel size), or null if exiftool is unavailable or can't read the file |
| `inspect_image(path, tags?)` | Metadata of an opened image from `exiftool` (`-j -n`; found beside `ART-cli`, else on PATH, else in the system's usual install locations (spec section 5), so a fork build without one still works): make, model, lens, ISO, `shutter_seconds`, `aperture`, `focal_length_mm`, `capture_date` (local, ISO 8601), `width`, `height`, `orientation` (EXIF 1-8), each null when absent; `tags` adds named exiftool tags (e.g. `Software`) that the file has, under `tags` |
| `render_preview(path, max_size=1024, region?, inline?)` | Renders the working profile to a JPEG and returns its path; see [Previews](#previews) |
| `get_profile(path)` | The working profile: curated tools typed under `adjustments`, every other value as a string under `raw` (each value once) |
| `edit_profile(path, adjustments?, raw_edits?)` | Changes the working profile: typed, range-checked `adjustments` (`exposure`, `white_balance`, `crop`, `rotation`, `local_contrast`, `sharpening`, `denoise`, `vignetting`, `lens_profile`, `tone_curve`, `color_correction`, `film_negative`; `crop` is checked against the image's size; a free rectangle needs `fixed_ratio: false`, see the crop entry of `describe_adjustments`) and/or `[Group] Key` raw edits; all or nothing. Lists `implied` changes (a disabled tool gets enabled; White Balance switches to `CustomTemp`; `histogram_matching` turned off when a curve is set; a computed `RefOutput`, see `film_negative`) |
| `describe_adjustments()` | The curated adjustments: fields, ranges, units, the `[Group] Key` each sets, and the `PPVERSION` the schema targets |
| `reset_profile(path, to)` | Reloads the working profile from the `sidecar` or ART's `default` profile |
| `export_image(path, output, format, quality?, bit_depth?, write_profile=false, overwrite=false)` | Renders the working profile at full size as `jpeg` (quality 1..100, 8 bit), `png` (8/16 bit) or `tiff` (8/16/16f/32 bit) to `output` (its folder must exist); an existing `output` is refused unless `overwrite`; `write_profile` also saves `<output>.arp`, otherwise none is written |
| `save_sidecar(path, on_conflict?)` | The only tool that writes the sidecar (named per ART's strip-extension option): atomic, previous one kept as `<sidecar>.bak`. If the sidecar changed on disk since it was loaded, asks the user (merge / overwrite / cancel) when the client supports elicitation; else fails with `conflict` listing the changed keys, and the agent calls again with `on_conflict`. `merge` applies only the agent's changed keys onto the current sidecar. Afterwards the saved file is the new baseline |
| `save_partial_profile(path, dest, overwrite?, exclude?)` | Writes only the keys the agent changed since load or the last save to `dest`; `exists` error if `dest` exists unless `overwrite`; writes nothing if nothing changed. `exclude`: `"Group"` or `"Group/Key"` entries left out (unknown name: `unknown_key`); settings that belong to one image (e.g. `Crop`) are usually excluded from a preset for other images; roll presets: see the `film-negative` skill |
| `sample_spots(path, spots, size=32, space="working")` | What ART's own spot pickers read: for 1 to 16 `{x, y}` frame pixels (the coordinates of `[Crop]`), `avg` and `max` `[r, g, b]` of the `size` x `size` square (2 to 256), linear 0..65535, white-balanced, before the film negative tool; `space` `working` or `input`. Out-of-frame spots are `out_of_range`; `space` matches `[Film Negative] ColorSpace` (1 = `working`, 0 = `input`). Workflows for film scans (neutral-spot fits, reference spot): see the skills below. Needs an ART build with spot sampling (`art-cli -x`; a release `art-cli` gives `unsupported`: point `--art-dir`/`ART_DIR` at the fork) |
| `image_stats(path, max_size=1024, histogram=false)` | Renders like a whole-image preview (8-bit PNG, crop applied; a holder or border in the image counts in clipping and percentiles, so crop first; Live's preview is uncropped) and returns per channel `r`, `g`, `b`, `lum` (0.2126 R + 0.7152 G + 0.0722 B, rounded to the nearest 8-bit value): `mean`, `clipped_high`/`clipped_low` (fraction at 255/0), `percentiles` (0.1, 1, 5, 50, 95, 99, 99.9 %, nearest rank on the 256-bin histogram), `histogram` (256 counts, only when asked), and the rendered `width`/`height` |

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
would skip an incomplete one). Setting `r`/`g`/`b` switches the region to RGB mode
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
round-trips. A spline can wiggle or overshoot, so `edit_profile` warns for a
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
- `inline`: also return the image as an MCP image block, next to the path. Defaults to
  the `--inline-previews` launch flag (off), so `claude mcp add art-render -- uv run
  --directory <repo>/tools/mcp art-mcp-render --inline-previews` turns it on for every call.
- Fast export (`art-cli -f`, about twice as fast, but it resizes before processing so
  sharpening and local effects are approximated) is used only for whole-image previews
  whose `max_size` fits your fast-export box (ART preferences, default 1920; the
  smaller side of `fastexport_resize_width`/`height` in `options`). `region` previews
  and bigger previews render without it.

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

## Development

Layout of the Render server (`art_mcp/render/`), in three layers:

- **Operations** (plain Python, no MCP): `session.py` holds `RenderSession`
  (per-image locks, running art-cli, the frame measurement) over a
  `ProfileStore` (`store.py`; `MemoryStore` keeps the working profiles, the
  loaded baseline for save's conflict check and the frame-size cache in the
  process, another store can keep them elsewhere). The `*_ops.py` modules
  (`profile_ops`, `preview_ops`, `export_ops`, `save_ops`, `metadata_ops`,
  `sampling_ops`) hold one function per tool, taking the session first and the
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
uv run mypy --strict art_mcp       # typecheck
ART_MCP_TEST_RAW=/path/to/raw uv run pytest tests/test_integration_art.py
```

The integration tests copy the raw to a temp folder and are skipped when ART or
`ART_MCP_TEST_RAW` is missing. `tests/test_integration_exiftool.py` runs the real
exiftool on a generated JPEG (and, with `ART_MCP_TEST_RAW`, on the raw, read-only)
and is skipped when no exiftool is found.
