# ART MCP servers

MCP servers that let AI agents (Claude Code, Claude Desktop) work with ART.
Design: [`docs/specs/mcp-servers.md`](../../docs/specs/mcp-servers.md).

- **`art-mcp-render`**: opens images and renders previews headlessly through
  `art-cli`. Changes stay in an in-memory working profile; renders never write
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
| `open_image(path)` | Loads the image's processing profile (sidecar, else ART's default profile) as its working profile |
| `render_preview(path)` | Renders the working profile to a 1024 px JPEG and returns its path |
| `get_profile(path)` | The working profile: curated tools under `adjustments`, everything else as strings under `raw` |
| `edit_profile(path, raw_edits)` | Sets `[Group] Key` values (raw edits); the group and key must exist; all or nothing |
| `reset_profile(path, to)` | Reloads the working profile from the `sidecar` or ART's `default` profile |
| `export_image(path, output, format, quality?, bit_depth?, write_profile=false, overwrite=false)` | Renders the working profile at full size as `jpeg` (quality 1..100, 8 bit), `png` (8/16 bit) or `tiff` (8/16/16f/32 bit) to `output` (its folder must exist); an existing `output` is refused unless `overwrite`; `write_profile` also saves `<output>.arp`, otherwise none is written |

Errors come back as tool errors whose text starts with a code: `not_open`,
`not_found`, `unknown_key`, `render_failed`, `timeout`, `exists`,
`out_of_range`.

## Development

```sh
uv run pytest                      # unit + fake-art-cli tests
uv run mypy --strict art_mcp       # typecheck
ART_MCP_TEST_RAW=/path/to/raw uv run pytest tests/test_integration_art.py
```

The integration tests copy the raw to a temp folder and are skipped when ART or
`ART_MCP_TEST_RAW` is missing.
