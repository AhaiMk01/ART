# ART MCP servers

MCP servers that let AI agents (Claude Code, Claude Desktop) work with ART.
Design: [`docs/specs/mcp-servers.md`](../../docs/specs/mcp-servers.md).

- **`art-mcp-render`**: opens images and renders previews headlessly through
  `art-cli`, and reads metadata with ART's exiftool. Changes stay in an in-memory working profile; renders never write
  sidecars.

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and an ART install
(found via `--art-dir`, `ART_DIR`, `PATH`, or the newest
`C:\Program Files\ART\<version>`).

## Install

Claude Code picks the servers up from the repo's `.mcp.json` when you open the
fork (approve them on first use). Elsewhere:

```sh
claude mcp add art-render -- uv run --directory <repo>/tools/mcp art-mcp-render
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
| `inspect_image(path, tags?)` | Metadata of an opened image from the `exiftool` beside `ART-cli` (`-j -n`): make, model, lens, ISO, `shutter_seconds`, `aperture`, `focal_length_mm`, `capture_date` (local, ISO 8601), `width`, `height`, `orientation` (EXIF 1-8), each null when absent; `tags` adds named exiftool tags (e.g. `Software`) that the file has, under `tags` |
| `render_preview(path, max_size=1024, region?, inline?)` | Renders the working profile to a JPEG and returns its path; see [Previews](#previews) |
| `get_profile(path)` | The working profile: curated tools typed under `adjustments`, every other value as a string under `raw` (each value once) |
| `edit_profile(path, adjustments?, raw_edits?)` | Changes the working profile: typed, range-checked `adjustments` (`exposure`, `white_balance`) and/or `[Group] Key` raw edits; all or nothing. Lists `implied` changes (a disabled tool gets enabled; White Balance switches to `CustomTemp`) |
| `describe_adjustments()` | The curated adjustments: fields, ranges, units, the `[Group] Key` each sets, and the `PPVERSION` the schema targets |
| `reset_profile(path, to)` | Reloads the working profile from the `sidecar` or ART's `default` profile |
| `export_image(path, output, format, quality?, bit_depth?, write_profile=false, overwrite=false)` | Renders the working profile at full size as `jpeg` (quality 1..100, 8 bit), `png` (8/16 bit) or `tiff` (8/16/16f/32 bit) to `output` (its folder must exist); an existing `output` is refused unless `overwrite`; `write_profile` also saves `<output>.arp`, otherwise none is written |
| `save_sidecar(path, on_conflict?)` | The only tool that writes the sidecar (named per ART's strip-extension option): atomic, previous one kept as `<sidecar>.bak`. If the sidecar changed on disk since it was loaded, asks the user (merge / overwrite / cancel) when the client supports elicitation; else fails with `conflict` listing the changed keys, and the agent calls again with `on_conflict`. `merge` applies only the agent's changed keys onto the current sidecar. Afterwards the saved file is the new baseline |
| `save_partial_profile(path, dest, overwrite?)` | Writes only the keys the agent changed since load or the last save to `dest`; `exists` error if `dest` exists unless `overwrite`; writes nothing if nothing changed |

Errors come back as tool errors whose text starts with a code: `not_open`,
`not_found`, `unknown_key`, `render_failed`, `timeout`, `conflict`, `exists`,
`out_of_range` (adjustment value outside its range; nothing is clamped), and
for metadata `metadata_unavailable` (no exiftool beside
ART-cli), `metadata_failed`, `invalid_tag`.

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

## Development

```sh
uv run pytest                      # unit + fake-art-cli tests
uv run mypy --strict art_mcp       # typecheck
ART_MCP_TEST_RAW=/path/to/raw uv run pytest tests/test_integration_art.py
```

The integration tests copy the raw to a temp folder and are skipped when ART or
`ART_MCP_TEST_RAW` is missing. `tests/test_integration_exiftool.py` runs the real
exiftool on a generated JPEG (and, with `ART_MCP_TEST_RAW`, on the raw, read-only)
and is skipped when no exiftool is found.
