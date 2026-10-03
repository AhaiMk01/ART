# art-cli as the Render server's backend

Ticket: [#3](https://github.com/AhaiMk01/ART/issues/3), part of map [#1](https://github.com/AhaiMk01/ART/issues/1).

**Question:** Can art-cli be the Render server's render backend, with one art-cli call per render?

**Answer:** Yes. One process per render is fast enough. On the test machine a ~1024 px preview from a 24 MP raw takes **0.37 s** end to end with `-f`, or 0.46 s without it. Startup is about 0.12 s of that. Resize can be set entirely by a partial profile. Nothing here forces a persistent engine process. A persistent engine would only pay off for interactive scrubbing, where the decoded and demosaiced raw would need to stay cached between renders. That is the Live server's job (the GUI already does it), not the Render server's. A few failure modes need wrapping. Most importantly, some skipped or failed outputs still exit with code 0 (see below).

Sources: this tree at `1.26.9-21-gbcc187845`. Measurements use the installed upstream release `C:\Program Files\ART\1.26.9\ART-cli.exe`, which is close to this tree.

## Measurements

Machine: AMD Ryzen 7 9850X3D (8C/16T), Windows 11. Raw file: Sony ARW, 49 MB, 6016x4016 (`D:\012126\_DSC5809.ARW`). Each time is wall-clock for the whole process, measured with PowerShell `Measure-Command`. Where a run was repeated 3 times, the runs were within 0.01 s of each other.

| Run | Time | Output |
|---|---|---|
| Startup only: `-c nonexistent` (with or without `-q`) | 0.12 s | none, exit 2 |
| Neutral profile, full size JPEG | 0.83 s | 6016x4016 |
| Neutral + `-p resize1024.arp`, normal pipeline | 0.46 s | 1024x684 |
| Neutral + `-p resize1024.arp`, `-f` | **0.37 s** | 1024x684 |
| `-f`, no resize profile | 0.39 s | 1920x1282 (fast-export default box) |
| Neutral + `-p resize1024.arp`, `-f`, PNG 8-bit (`-n`) | 0.39 s | 1024x684, 670 KB |
| Neutral + `-p resize1024.arp`, TIFF 16-bit (`-t`) | 0.50 s | 1024x684 |
| `-d` (user's default raw profile) + resize, normal pipeline | 1.81 s | 1024x684 |
| `-d` + resize, `-f` | **0.93 s** | 1024x684 |
| `-d`, full size, normal pipeline | 1.99 s | full size |

What this shows:
- **Per-call startup is about 0.12 s.** `main()` calls `Options::load` and then `art::engine::init`. That init sets up lensfun, the profile store, ICC, DCP, camera constants, ImageIOManager and GPU (`src/gui/main-cli.cc:196-205`, `src/gui/options.cc:2997`, `src/engine/init.cc:72-176`). `-q` only skips eager loading (`loadAll = !lightweight`), and it made no measurable difference here.
- **Load and demosaic dominate the render, not startup.** A realistic profile benefits a lot from `-f`: 1.81 s goes down to 0.93 s.
- Other cameras or machines will differ. 40 to 60 MP files should scale roughly with pixel count during load and demosaic. That is an estimate; it was not measured.

## Resize from a partial profile: yes

Params come only from files. A partial profile that contains just a `[Resize]` group works:

```ini
[Resize]
Enabled=true
DataSpecified=3
Width=1024
Height=1024
```

- Keys read: `Enabled, Scale, AppliesTo, DataSpecified, Width, Height, AllowUpscaling, PPI, CopyPPIToExif, Unit` (`src/engine/procparams.cc:5065-5094`). Any key that is left out keeps its value from the earlier layers. Defaults are `dataspec=3` (fit box), `appliesTo="Cropped area"`, `unit=PX` and no upscaling (`procparams.cc:2247-2252`). A file without a `[Version]` group is treated as the current `PPVERSION` (`procparams.cc:4176-4185`).
- `DataSpecified`: 0 = scale, 1 = width, 2 = height, 3 = fit box (`src/engine/ipresize.cc:251-279`). Fit box never upscales unless `AllowUpscaling=true`. A long-edge preview is therefore `DataSpecified=3, Width=Height=N`.
- Layering order: neutral, then `-d` default, then each `-p` in order, then the sidecar (`-s`/`-S`) at its position on the command line (`main-cli.cc:921-973`; help text in `src/gui/printhelp.h:183-200`). The Render server can therefore pass `-p <user or sidecar edit> -p <resize-only partial profile>` so that its resize wins. Caveat: a sidecar loaded with `-s` is applied at the position of the `-s` flag, so `-s` must come before the resize `-p`. Otherwise the sidecar's own `[Resize]` overrides it.
- Afterwards, a per-format "save profile" from ImageIOManager is applied on top (`main-cli.cc:983-987`). This is normally empty for jpg/png/tif.

## What `-f` (fast export) changes

There are two layers.

1. **The GUI side rewrites the params** (`src/gui/fastexport.cc:28-46`). The resize is forced on, in px, as a fit box, applied to the cropped area, with no upscaling. If the profile already enables resize, the box is `min(profile size, options.fastexport_resize_width/height)`. Otherwise the box comes from those options. They default to 1920x1920 (`src/gui/options.cc:592-593`) and are read from the user's ART `options` file, `[Fast Export] MaxWidth/MaxHeight` (`options.cc:1964-1980`). **This means a preview can never be larger than the user's fast-export box when `-f` is used.**
2. **The engine runs a different pipeline** (`src/engine/simpleprocess.cc:81-101, 523-575`). Load, preprocess and demosaic still run at full size. The image is then downscaled with Lanczos (`stage_early_resize`) *before* denoise, transforms and all the processing stages. The normal pipeline instead resizes at the very end (`simpleprocess.cc:436-450`). In fast mode, `ipf.setScale(1/scale)` scales radius-based tools. Pixel Shift falls back to AMaZE, and X-Trans 3-pass falls back to 1-pass (`adjust_procparams`). If resize ends up disabled, it silently falls back to the normal pipeline.

As a result, `-f` previews are close to the full-size export but not pixel-identical. Local and sharpening effects are approximations at the reduced scale. That is fine for previews. A final export should not use `-f`.

## Output formats usable for previews

- `-j[q]` JPEG (8-bit, quality 0-100, `-js1..3` subsampling). This is the default when no type is given. It is the smallest: about 87 KB at 1024 px. This is the best fit for returning an MCP image.
- `-n` PNG 8/16-bit, lossless: about 670 KB at 1024 px.
- `-t[z]` TIFF 8/16/16f/32: for analysis, not for display.
- `-T<type>` uses a user-defined custom saver from ImageIOManager (`main-cli.cc:587-599, 1020-1024`). An unknown type fails at save time.
- **There is no stdout or pipe output.** Output always goes to a file. `-o /dev/null` is a special case that has no use here. The Render server has to render to a temp file and read it back. The output extension is always replaced with the type's extension (`main-cli.cc:858-884`): for example, `-o x.out -Tbogus` wrote `x.bogus`. The server should therefore build the path from the type, not trust the name it passed.

## Failure modes (verified by running the binary)

`processLineParams` return codes (`main-cli.cc:97-104, 1051`): `0` ok, `-1` bad option (help is printed to **stdout**), `-2` at least one processing or load/save error, `-3` bad arguments or a missing `-p` file, `2` no input files found. `1` means a bare filename without `-c` (the GUI-launch path). The process exit status is that value truncated. PowerShell showed -1/-2/-3, and bash saw 255/254/253. A Node or Python child-process API on Windows may report them as large unsigned values.

Message streams: `cpl.error` writes `Error: ...` to **stderr**. Info lines (`Processing:`, `Merging ...`) go to stdout (`main-cli.cc:359-369`).

| Case | Exit | Message |
|---|---|---|
| `-p` file missing | -3 | stderr `Error: "<f>" not found.` |
| Input file is not a raw (garbage `.ARW`) | -2 | `Error: impossible to load file: ...` |
| Output directory missing | -2 | `Error: failure in saving to: ...` |
| Unknown `-T` type | -2 | `Error: failure in saving to: ...` |
| Input does not exist | 2 | stderr `"<f>" doesn't exist!` |
| Extension not in user's Preferences "parsed extensions" | 2 | stdout `... Image skipped.` (`-a` widens the check to all extensions ART knows) |
| **Output exists, no `-Y`** | **0** | `Error: ... already exists ... skipped` (does not increment `errors`, `main-cli.cc:892-899`) |
| **Output path == input path** | **0** | `Error: cannot overwrite` (`main-cli.cc:886-890`) |
| **Malformed `.arp` (garbage text)** | **0** | none; it renders as if the file were empty |
| Unknown group or key in a partial profile | 0 | none; silently ignored (keys are read with `has_key` checks) |

Consequences for the Render server:
- Always pass `-Y` and a fresh temp output path. Then **check that the output file exists and is non-empty**, and do not rely on exit 0 alone.
- Validate partial profiles itself, or round-trip them through its own schema. art-cli does not report typos.
- Pass `-a`, so that the user's parsed-extension preference cannot silently skip an input.
- art-cli reads the **user's GUI `options` file**: default profiles (`-d`), parsed extensions, thread pool size, GPU settings and the fast-export box. A render is therefore not hermetic. Avoid `-d` unless the default processing profile is wanted on purpose. Pass explicit partial profiles instead.
- There is no built-in timeout. The server should apply one. Each call uses all cores through OpenMP, so concurrent renders should be serialised or run with a small limit.
- Do not use `-O`: it writes the final processing profile as an `.arp` next to the output, or embeds it (`main-cli.cc:1033-1040`). `-s`/`-S` only read the sidecar. art-cli never writes a sidecar next to the input image.

## Would anything force a persistent engine process?

Not for the Render server's stated job of rendering a preview or export from a raw plus partial profiles, and inspecting one image:
- Startup (0.12 s) is small next to load and demosaic. Load and demosaic would only be saved by a process that **caches the decoded and demosaiced raw** across renders of the same file. That is what the GUI's `ImProcCoordinator` does, and it is the Live server's domain.
- Possible reasons to revisit: (a) rapid repeated re-renders of one file while sweeping a parameter. Each call re-decodes, which costs about 0.25 s here and more on larger files. (b) Needing data that art-cli cannot emit, such as histograms, picker values or intermediate stages. art-cli only writes final images, so a histogram has to be computed from the output file. (c) Streaming output without temp files. None of these is a blocker.

## Not verified

- Timings for other cameras, sizes, X-Trans or the GPU path. Behaviour of the fork's own build of art-cli (only the upstream 1.26.9 binary was run).
- Whether art-cli can hang on a pathological input. No timeout behaviour was observed.
