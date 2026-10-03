# MCP SDK options for a local stdio server on Windows

Research for [#2](https://github.com/AhaiMk01/ART/issues/2), part of the
[ART MCP servers map](https://github.com/AhaiMk01/ART/issues/1). It covers both
planned servers: the **Render server** (headless processing via art-cli plus
inspecting a single image) and the **Live server** (controls a running ART GUI
through a new control channel). These are facts only. The choice of language
belongs to a later ticket.

Researched 2026-10-03. Version numbers come from the PyPI and npm registry JSON
on that date.

## TL;DR

- Python and TypeScript both have **Tier 1** official SDKs. Both shipped a v2
  line in 2026 that targets MCP spec `2026-07-28`, and both keep their v1 line
  on maintenance.
- In Python, the v2 SDK renamed `FastMCP` to `MCPServer`. The separate
  `fastmcp` package (PrefectHQ, 4.x) is a third-party framework, not the
  official SDK.
- Over the protocol, an image can only be returned **inline as base64**
  (`ImageContent`). A file path is just text, and a `resource_link` is a URI the
  client may or may not fetch. Claude Code shows the base64 image to Claude and
  also saves the full bytes to disk, then gives Claude that path.
- **Claude Code limits:** image results count toward `MAX_MCP_OUTPUT_TOKENS`
  (default 25,000; warning at 10,000). The per-tool `anthropic/maxResultSizeChars`
  override does **not** apply to images. The model then downscales anything over
  2576 px on the long edge (Claude 4.7+) or 1568 px (older models). The API
  allows at most 10 MB of base64 per image and 8000x8000 px.
- **Windows:**
  - `.cmd` shims such as `npx` cannot be spawned without a shell, while real
    `.exe` launchers can.
  - `ART-cli.exe` is a console-subsystem exe, so spawn it hidden
    (`CREATE_NO_WINDOW` / `windowsHide`) with stdin closed.
  - The Python v2 stdio transport already moves fd 0/1 away from the wire, so a
    child process cannot corrupt the protocol stream. The TS transport does not.
  - stdin EOF is the reliable way to shut down on Windows.

## 1. SDK maturity

| | Python official | TypeScript official | `fastmcp` (PrefectHQ) |
|---|---|---|---|
| Package | `mcp` on PyPI | `@modelcontextprotocol/server` (v2), `@modelcontextprotocol/sdk` (v1) | `fastmcp` on PyPI |
| Latest | 2.3.0 (2026-10-02); v1 line 1.30.0 (2026-09-07) | server 2.3.0 (2026-10-02); sdk v1 1.32.0 (2026-10-02) | 4.0.10 (2026-09-25) |
| Runtime | Python >= 3.10 | v2: Node >= 20 (also Bun and Deno); v1: Node >= 18 | Python >= 3.10 |
| Tier | Tier 1 | Tier 1 | not an official SDK, so no tier |
| Server API | `from mcp.server import MCPServer` with `@mcp.tool()` | `new McpServer(...)` with `server.registerTool(...)` | `FastMCP` with `@mcp.tool` |
| Schemas | type hints and Pydantic | Standard Schema (Zod v4, Valibot, ArkType) | type hints and Pydantic |

Sources:
[SDK list and tiers](https://modelcontextprotocol.io/docs/sdk),
[tier definitions](https://modelcontextprotocol.io/community/sdk-tiers),
[python-sdk](https://github.com/modelcontextprotocol/python-sdk),
[typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk),
[pypi mcp](https://pypi.org/project/mcp/),
[pypi fastmcp](https://pypi.org/project/fastmcp/),
[npm @modelcontextprotocol/server](https://www.npmjs.com/package/@modelcontextprotocol/server).

What the tiers mean, per the tier page:

- **Tier 1** requires:
  - a 100% pass rate on the conformance tests
  - new spec features before each spec release
  - issue triage within 2 business days
  - P0 (critical) fixes within 7 days
  - a stable release, comprehensive docs and a published roadmap
- **Tier 2** requires an 80% conformance pass rate and new spec features within
  6 months.

In this list, C#, Go, Rust and Ruby are also Tier 1, and Java is Tier 2.

Notes on v1 and v2:

- **Python v1 to v2**
  ([migration guide](https://py.sdk.modelcontextprotocol.io/migration/)):
  - `FastMCP` became `MCPServer`, imported from `mcp.server.mcpserver`.
  - Pydantic field names became snake_case.
  - Synchronous tool handlers now run on a worker thread.
  - The WebSocket transport was removed.
  - `httpx` was replaced by `httpx2`.
  - The guide says "The v1.x maintenance line keeps receiving critical bug fixes
    and security patches", and suggests pinning `mcp<2` until you migrate.
- **TypeScript**: the README says V2 is the current stable release and is
  aligned with spec 2026-07-28. V1.x gets bug fixes and security updates for at
  least 6 months after the v2 release.
- **Spec `2026-07-28` changes:**
  - Every request carries its protocol version and capabilities in `_meta`; the
    `initialize` handshake is gone.
  - Results carry `resultType`.
  - Earlier spec revisions are handled by version detection and fallback.

  Sources: the
  [transports overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)
  and [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
  pages. Whether a given Claude Code or Desktop build speaks 2026-07-28 or an
  earlier revision was **not verified**. Both SDKs' v2 lines claim backward
  compatibility.

## 2. How a tool returns an image

Spec, [tools: Tool Result](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).
The content block types are text, image, audio, `resource_link` and embedded
`resource`. The image block looks like this:

```json
{ "type": "image", "data": "base64-encoded-data", "mimeType": "image/png" }
```

- `resource_link` returns a URI, such as `file:///...`, that the client *may*
  fetch or subscribe to. Resource links are "not guaranteed to appear in the
  results of a `resources/list` request".
- An embedded `resource` can carry a `blob`. Servers that use it "SHOULD
  implement the `resources` capability".
- A plain file path in a text block is only text. The model has to read it with
  some other tool. It is not an MCP image.

How each SDK builds an image block:

- **Python v2:**
  ```python
  from mcp.server.mcpserver import Image
  ...
  return Image(path=...)               # MIME type comes from the extension
  return Image(data=bytes, format="png")
  ```
  Without a file name, a missing `format=` silently falls back to `image/png`
  ([media docs](https://py.sdk.modelcontextprotocol.io/servers/media/)).
- **fastmcp:** `fastmcp.utilities.types.Image(path=... | data=..., format=...)`.
  It also has `Audio` and `File` helpers; `File` becomes an EmbeddedResource
  ([fastmcp tools](https://gofastmcp.com/servers/tools)).
- **TypeScript:** return
  `{ content: [{ type: "image", data: <base64>, mimeType: "image/png" }] }`
  from the `registerTool` handler. The spec shape is used directly and there is
  no helper class.

How Claude Code handles an image result
([Claude Code MCP docs, "Images in tool results"](https://code.claude.com/docs/en/mcp)):

- For PNG, JPEG, GIF and WebP, "Claude sees the image inline … The inline copy
  may be scaled down or compressed to fit the model's image size limits."
- Claude Code "also saves the original bytes to a file in the session's
  `tool-results` directory … and gives Claude the path". Claude can then crop or
  convert the full-resolution file with Bash.
- This needs Claude Code **v2.1.283 or later**.
- With `--no-session-persistence`, only the inline copy is kept.

## 3. Size limits clients apply to returned images

Claude Code ([MCP output limits](https://code.claude.com/docs/en/mcp)):

- There is a warning at 10,000 tokens (a fixed threshold). The default cap is
  **25,000 tokens**, which you can raise with `MAX_MCP_OUTPUT_TOKENS`.
- "Tools that return image data are still subject to `MAX_MCP_OUTPUT_TOKENS`."
- `_meta["anthropic/maxResultSizeChars"]` (hard ceiling 500,000 characters)
  raises the limit for **text only**. "The annotation has no effect on tools
  that return image content; for those, raising `MAX_MCP_OUTPUT_TOKENS` is the
  only option."
- A result **with no image content** that goes over the limit is saved to a file
  and replaced by its path. The docs describe that fallback only for results
  without images.
- **Not documented:** how image bytes are converted into tokens for this check.
  It could be by base64 length or by visual tokens. A prototype should measure
  it.

Model and API limits apply after the client
([Vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)):

- Formats: JPEG, PNG, GIF and WebP only. Animations use the first frame only.
- An image larger than 8000x8000 px is rejected.
- If a request has more than 20 images, a stricter limit applies to every image
  in it: about 2000 px per side.
- The base64 payload can be at most 10 MB per image on the direct API, or 5 MB
  on Bedrock and Vertex. A request can be at most 32 MB.
- Images are downscaled to a long edge of 2576 px / 4784 visual tokens on
  Claude 4.7 and later, or 1568 px / 1568 tokens on other models.
- The cost is `ceil(w/28) * ceil(h/28)` visual tokens. Pixels beyond these caps
  are wasted bytes.

Claude Desktop:

- No official per-result size limit is documented.
- A user-reported error "Tool result is too large. Maximum size is 1MB." appears
  in
  [anthropics/claude-code#66519](https://github.com/anthropics/claude-code/issues/66519).
  The issue was filed under Claude Code, but the reported version string
  (1.111897.x) looks like a desktop app. Treat a **1 MB cap as plausible but
  unverified**.
- Claude Desktop config: `%APPDATA%\Claude\claude_desktop_config.json`. Logs go
  to `%APPDATA%\Claude\logs\mcp*.log`, and the server's stderr goes to
  `mcp-server-<NAME>.log`
  ([connect local servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)).

Claude Code timeouts that matter for slow renders
([MCP docs](https://code.claude.com/docs/en/mcp)):

- `MCP_TIMEOUT` sets the startup timeout.
- A per-server `"timeout"` in `.mcp.json`, in ms, is a hard wall-clock limit for
  each tool call. Progress notifications do not extend it.
- The idle timeout is 30 minutes for stdio servers (Claude Code v2.1.203+); set
  it with `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`.
- Calls that run longer than 2 minutes move to the background.

## 4. Windows stdio and process-spawn gotchas

### Protocol rules (all languages)

[stdio transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports):

- Messages are UTF-8, newline-delimited, and "MUST NOT contain embedded
  newlines".
- The server "MUST NOT write anything to its stdout that is not a valid MCP
  message".
- stderr is free for logging.

### Launching the server itself

- On Windows, `npx`, `npm` and `uvx` installed by npm are `.cmd` or `.ps1`
  shims. Node's docs say `.bat`/`.cmd` "are not executable on their own without
  a terminal". They need `shell` (deprecated, DEP0190), `exec`, or
  `cmd.exe /c` ([Node child_process](https://nodejs.org/api/child_process.html)).
  Older Claude Code docs told native-Windows users to wrap npx servers in
  `cmd /c`. The current MCP page no longer says this, and the current behaviour
  was **not verified**.
- These avoid the shim problem by pointing `command` at a real executable:
  `node.exe dist/server.js`, `python.exe -m ...`, or `uv.exe run ...`.
- Use absolute paths in `command` and `args`. The MCP docs list relative paths
  as a common cause of a server failing to start.
- If logs show a literal `${APPDATA}`, add the expanded `APPDATA` to the
  server's `env`
  ([connect local servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)).
- Claude Code expands `${VAR}` and `${VAR:-default}` in `command`, `args` and
  `env`. It sets `CLAUDE_PROJECT_DIR` in the server's environment
  ([MCP docs](https://code.claude.com/docs/en/mcp)).

### Stdout corruption and encoding inside the server

- **Python v2** `stdio_server()`
  ([source](https://github.com/modelcontextprotocol/python-sdk/blob/main/src/mcp/server/stdio.py)):
  - It re-wraps stdin and stdout as UTF-8. The code comment says "the std
    handles' platform encodings are unreliable".
  - "While serving, fd 0 points at the null device and fd 1 at stderr, so
    handlers and children read EOF and their stray output misses the wire."
  - It has explicit Windows handle-rebind code (`mcp.os.win32`). So a stray
    `print()`, or a child process that inherits handles, cannot break the
    protocol.
- **Python v1** (1.x) also wraps the streams as UTF-8, but it has **no** fd
  diversion
  ([v1.x source](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/src/mcp/server/stdio.py)).
- **TypeScript** `StdioServerTransport`
  ([source](https://github.com/modelcontextprotocol/typescript-sdk/blob/main/packages/server/src/server/stdio.ts)):
  - It reads and writes `process.stdin` and `process.stdout` directly, with no
    diversion. A `console.log` or an inherited child stdout goes straight onto
    the wire.
  - The read buffer has a default limit of 10 MB per incoming message. This
    covers client-to-server messages, not our image results.
  - It closes on stdin EOF. Its own comment says this is "the primary graceful
    shutdown signal, and on some platforms (e.g. Windows) the only reliable
    one".
- Other languages (general rule): if a runtime's console encoding follows the
  OEM or ANSI code page, non-ASCII text such as file paths gets mangled unless
  stdout is written as UTF-8 bytes. Both official SDKs handle this inside their
  transports.

### Spawning `ART-cli.exe` from the server (Render server)

- **Facts from this repo:**
  - The CMake target `art-cli` is built as `ART-cli`, and it is a **console**
    exe. Only the GUI `art` gets `-mwindows` (`src/gui/CMakeLists.txt`).
  - With a UCRT toolchain (`ART_USES_UCRT`), both exes embed `utf8.manifest`,
    which sets `activeCodePage` to UTF-8. In that case `main(int argc, char**
    argv)` receives UTF-8 argv, so non-ASCII paths pass through intact
    (`src/gui/utf8.rc`, `src/gui/main-cli.cc`).
  - Without UCRT there is no manifest, so argv uses the ANSI code page and
    non-ASCII paths can be lost.
- **Console window:**
  - When the parent has no console, as when Claude Desktop spawns it, starting a
    console exe can flash a console window.
  - Python: `creationflags=subprocess.CREATE_NO_WINDOW`
    ([subprocess docs](https://docs.python.org/3/library/subprocess.html)).
  - Node: `windowsHide: true` (default `false`).
  - Whether Claude Code or Desktop already start the MCP server itself hidden
    was **not verified**.
- **stdin:** pass `stdin=DEVNULL` (Python) or `stdio: ['ignore', ...]` (Node).
  This stops art-cli from inheriting, and possibly reading, the MCP wire. Python
  v2 already does this at fd level; TypeScript does not.
- **stdout/stderr:** capture both through pipes and never inherit them. In TS,
  an inherited stdout would write into the protocol stream. Decode the captured
  output explicitly:
  - Python's text mode defaults to `locale.getpreferredencoding(False)`, not
    UTF-8, so pass `encoding="utf-8", errors="replace"` or decode the bytes
    yourself.
  - Because ART calls `setlocale(LC_ALL, "")` on non-UCRT builds, its console
    output encoding depends on the build.
- **No shell:**
  - Pass an argv list. Python then quotes it with `list2cmdline`; Node quotes
    `spawn` args itself.
  - `shell=True` / `shell: true` brings in cmd.exe metacharacter injection risk
    for paths taken from tool arguments.
  - Python does not need `shell=True` to run a console exe.
- **Shutdown:** Windows has no POSIX signals for a graceful stop.
  - For the server: treat stdin EOF as the signal to exit, as the TS SDK does.
  - For a long art-cli run: kill the child (`TerminateProcess`, via `.kill()`)
    when the tool call is cancelled (`notifications/cancelled` on stdio).

## Open questions (not answered here)

- How Claude Code counts image bytes against `MAX_MCP_OUTPUT_TOKENS`. A
  prototype should measure where a JPEG preview of size N trips the 25k default.
- Whether Claude Desktop applies a 1 MB result cap, and whether it supports
  `resource_link` or embedded image blobs the way Claude Code does.
- Which MCP protocol revision the current Claude Code and Desktop builds
  negotiate.
