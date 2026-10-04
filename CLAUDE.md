# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ART is a raw image editor forked from RawTherapee (C++, GTKmm 3, CMake). Website: https://artraweditor.github.io

## Build

Out-of-source CMake build; Ninja is what CI uses. On Windows, build inside an MSYS2 shell (UCRT64 for x64, CLANGARM64 for arm64) — see `.github/workflows/windows.yml` for the full dependency list (gtkmm3, lcms2, fftw, lensfun, exiv2, LibRaw, optional OpenColorIO/CTL/Vulkan).

```sh
mkdir build && cd build
cmake -GNinja -DCMAKE_BUILD_TYPE=Release ..   # default build type is Release
ninja install                                  # installs a runnable bundle into build/<BuildType>/
```

Useful options (top-level `CMakeLists.txt`): `ENABLE_VULKAN` (GPU backend, off by default), `ENABLE_LIBRAW`, `ENABLE_OCIO`, `ENABLE_CTL`, `ENABLE_SIMDE` (needed on ARM), `OPTION_OMP`, `WITH_SAN`, `WITH_LTO`. `ccache` is used automatically if found.

Targets: `art_utils` and `art_engine` (static libs), `art` (GUI) and `art-cli` (batch/command-line) executables.

There is no test suite. Verify changes by building and running the app (or `art-cli` on a sample raw). Formatting: `.clang-format` (LLVM-based, 4-space indent, WebKit braces, 80 columns).

Notable compiler-flag constraints already handled in CMake: `-ffp-contract=off` on GCC ≥ 11 and `-fno-tree-loop-vectorize` on GCC 10.0–10.2 (known miscompiles). The codebase compiles with `-std=c++11` — don't use newer language features.

## Source layout

- `src/utils` — namespace `art::utils`: path helpers, threading, i18n (`multilangmgr`), `ppversion.h`.
- `src/engine` — namespace `art::engine`: everything that touches pixels. No GTK widgets.
- `src/gui` — namespace `art::gui`: GTKmm UI; `main.cc` → `art`, `main-cli.cc` → `art-cli`.
- `data` — runtime data installed alongside the binary: `languages/` (`default` is the English source of truth for all UI strings), profiles, themes, `camconst.json`/`cammatrices.json`, DCP/ICC/LUT files.
- `doc/gpu_pipeline.md` — detailed walkthrough of the Vulkan backend; read it before touching `src/engine/gpu/`.

## Engine architecture

**Image sources.** `ImageSource` (`imagesource.h`) is the input abstraction; `RawImageSource` handles raw files (demosaicing, raw preprocessing, dark/flat frames — the dcraw/LibRaw decoders live here too), `StdImageSource` handles JPEG/TIFF/PNG.

**Processing parameters.** `procparams.h/.cc` defines `ProcParams`, a struct of per-tool param structs, serialized to `.arp` sidecar files (GLib KeyFile format). When a tool's params or behaviour changes, bump `PPVERSION` in `src/utils/ppversion.h`, add a log entry there, and handle older versions in `ProcParams::load` to keep old sidecars rendering identically.

**Three pipeline drivers, one operator list.** The same `ImProcFunctions` (`improcfun.h/.cc`, with individual tools implemented in `ip*.cc` files) is driven from:
- `improccoordinator.cc` — interactive editor preview (scaled), plus histograms/scopes;
- `dcrop.cc` — 1:1 detail windows / crops in the editor;
- `simpleprocess.cc` — full-resolution output (export, batch queue, CLI);
- thumbnails go through their own path (`rtthumbnail.cc`).

Pre-demosaic and early steps (spot removal, film negative, denoise, transform/lens correction) are called explicitly in each driver; the bulk of tools run via `ImProcFunctions::process(Stage::STAGE_0..3)` in `improcfun.cc`, which is the canonical tool **order**. Each tool is invoked through the `STEP_` macro → `apply()`, which handles progress reporting, per-operator profiling (`ART_PROFILE=1`), and GPU→CPU pixel sync. Some tools run only for certain `Pipeline` kinds (e.g. sharpening only in PREVIEW/OUTPUT). Changes to the pipeline usually need to be mirrored across the drivers.

**Incremental preview updates.** `refreshmap.h` defines `M_*` bitflags (what part of the pipeline to recompute) and composite actions. GUI tools register events at runtime with `ProcEventMapper::getInstance()->newEvent(<action>, "HISTORY_MSG_...")` (`src/gui/eventmapper.h`, backed by the engine's `RefreshMapper`); the coordinator uses the event's action to decide how far back in the pipeline to restart.

**GPU (optional).** `src/engine/gpu/` is a Vulkan compute backend that never throws: every entry point returns false/null meaning "use the CPU path". Vulkan is `dlopen`ed, not linked. Shaders are `shaders/*.comp`, compiled to SPIR-V by CMake and embedded by default. Runtime env vars: `ART_GPU` (device preference, `off`/`0` disables), `ART_GPU_DISABLE_OPS` (comma-separated op names), `ART_VULKAN_LIBRARY`. `Imagefloat` tracks CPU/GPU residency (`residency.cc`); code that reads pixel planes directly must ensure `syncCpuForWrite()` has been called.

## GUI architecture

- `RTWindow` → `FileCatalog` (browser, thumbnails), `EditorPanel` (single-image editing), `BatchQueuePanel` (export queue).
- Each tool is a `ToolPanel` subclass (e.g. `exposure.cc`) with `read(const ProcParams*)` / `write(ProcParams*)` and events created in its constructor. Tools are instantiated and grouped into tabs in `toolpanelcoord.cc`, which also forwards param changes to the engine.
- `ParamsEdited` / `PartialProfile` track which fields are set, for partial paste and processing-profile application.
- All user-visible strings go through `M("KEY")`; add new keys to `data/languages/default` (other language files are optional/translations).
- `Options` (`options.cc`) holds persistent app preferences (stored in the user config dir, suffix controlled by `CACHE_NAME_SUFFIX`).

## Adding a new processing tool (cross-cutting checklist)

1. Params struct in `procparams.h`, plus `==`, defaults, `save`/`load` in `procparams.cc`; bump `PPVERSION`.
2. Implementation as an `ImProcFunctions` method (new `ip*.cc` file, add to `src/engine/CMakeLists.txt`) and a `STEP_` entry at the right place in `ImProcFunctions::process`.
3. GUI `ToolPanel` in `src/gui` (add to `src/gui/CMakeLists.txt`), registered in `toolpanelcoord.cc`, events with a suitable refresh action.
4. Strings in `data/languages/default`.

## Agent skills

### Issue tracker

GitHub Issues on the fork `AhaiMk01/ART` (not upstream `origin`); always pass `-R AhaiMk01/ART` to `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
