# How the ART editor applies a profile to the open image

Research for ticket [#4](https://github.com/AhaiMk01/ART/issues/4) (map: [#1](https://github.com/AhaiMk01/ART/issues/1)), Live server.
Source of truth: this repo at `bcc187845`. Every `file:line` below is relative to the repo root.

## Answer in brief

| Need | Minimal hook | Thread |
|---|---|---|
| (a) read current processing profile | `ipc->getParams(&pp)` on the active `EditorPanel`, then `pp.save(nullptr, keyfile)` + `keyfile.to_data()` to get .arp text | GTK main thread |
| (b) apply a partial profile with one undo entry | Do what `ProfilePanel::paste_clicked` does: select the "custom" row in the profile combo, then `tpc->profileChange(&partial, EvProfileChanged, label)` | GTK main thread |
| (c) grab the preview | `PreviewHandler::previewImg` (a `Gdk::Pixbuf`, downscaled whole image, monitor color space), via `getRoughImage(w, h, zoom)` | GTK main thread (it is mutex-guarded, but is replaced from an idle callback) |
| (c') full-size render | `create_processing_job(ipc->getInitialImage(), pp, ...)` + `art::engine::processImage` on a `ThreadPool` task (`ProgressConnector`), as Save As does | worker thread, result back via idle |

Everything a control channel touches in `src/gui/` must run on the GTK main thread. The channel's socket thread should marshal each request with `IdleRegister::add` / `gdk_threads_add_idle_full` (`src/gui/guiutils.cc:53-77`) and wait for the reply.

None of `tpc`, `history`, `ipc`, `profilep` or `previewHandler` is public on `EditorPanel`. Everything after `private:` at `src/gui/editorpanel.h:184` is private, and the members sit at `editorpanel.h:263,265,279`. So the hook has to be a **new public method on `EditorPanel`**, or a friend class. A thin `EditorPanel::liveGetProfile()` / `liveApplyProfile()` / `liveGetPreview()` trio is the minimal surface.

## 1. The paste path (what the GUI does today)

1. `ProfilePanel::paste_clicked` (`src/gui/profilepanel.cc:591-636`):
   - Ctrl+click opens `PartialPasteDlg` and gets a `ParamsEdited` mask (`:602-613`, `:631-632`).
   - It blocks the combo's change signal, selects or adds the **custom** row (`:616-627`), and builds `PEditedPartialProfile(pp, pe)` (partial) or `FullPartialProfile(pp)` (full) (`:630-635`).
   - It calls `changeTo(custom, M("HISTORY_FROMCLIPBOARD"))` → `tpc->profileChange(newpp, EvProfileChanged, profname)` (`:638-648`).
2. `ToolPanelCoordinator::profileChange` (`src/gui/toolpanelcoord.cc:568-664`) is the central apply routine:
   - `ProcParams *params = ipc->beginUpdateParams();` locks `paramsUpdateMutex` and returns `&nextParams` (`toolpanelcoord.cc:580`; `src/engine/improccoordinator.cc:1600-1605`).
   - It copies the current params to `mergedParams` and runs `nparams->applyTo(mergedParams)` (`toolpanelcoord.cc:582-591`). **This is where a partial profile is merged over the current profile.**
   - It skips the raw re-render if the raw, lensProf, filmNegative and wb settings are unchanged (`:595-610`).
   - It writes `*params = mergedParams`, trims the crop to the image (`:612-626`), and pushes the values into every tool widget with `toolPanel->read(params)` (`:629-636`). The GUI refreshes here.
   - `ipc->endUpdateParams(...)` ORs the refresh flags into `changeSinceLast`, unlocks, and calls `startProcessing()` (`toolpanelcoord.cc:651-659`; `improccoordinator.cc:1630-1636`).
   - It notifies `paramcListeners->procParamsChanged(params, event, descr)` (`toolpanelcoord.cc:661-664`). The listeners are `ProfilePanel`, `History` and `EditorPanel` (`src/gui/editorpanel.cc:908-910`).
3. `History::procParamsChanged` (`src/gui/history.cc:275-345`) records the undo entry:
   - It ignores `EvHistoryBrowsed` and `EvMonitorTransform` (`:281`).
   - It drops every row after the current selection (redo branch) (`:302-309`).
   - It appends a **new row** storing the full `ProcParams` snapshot when the event differs from the last row's event, or **always** for `EvProfileChanged` (`:320-327`). Otherwise it updates the last row in place, which coalesces repeated slider events (`:343+`).
   - Undo and redo only move the selection (`history.cc:442-474`). The selection handler re-applies the stored snapshot through `tpc->profileChange(&FullPartialProfile(pparams), EvHistoryBrowsed, ...)` (`history.cc:200-208`).
   - So an `EvProfileChanged` apply gives exactly one undoable history entry, labelled with the `descr` you pass.
4. `ProfilePanel::procParamsChanged` (`profilepanel.cc:706-728`) **ignores `EvProfileChanged` unless the custom row is already selected**. That is why `paste_clicked` selects the custom row first (`:620-627`). If you call `tpc->profileChange` directly without doing this, the image and history update, but the profile combo keeps showing the old profile name and `custom` is not refreshed. A Live-server apply should reproduce lines 616-635 (custom row, then `changeTo`). A small new public `ProfilePanel::applyPartialProfile(const PartialProfile&, label)` built from those lines is the cleanest hook.
5. The engine side is asynchronous. `ImProcCoordinator::startProcessing` queues `process()` on `ThreadPool` at HIGHEST priority, unless it is already running (`improccoordinator.cc:1497-1510`). `process()` loops while `changeSinceLast` is set: it copies `nextParams` to `params` and runs `updatePreviewImage` under `mProcessing` (`:1521-1598`). Repeated applies therefore coalesce, and the call returns before any pixels change.

## 2. PartialProfile semantics (what "partial" means)

- `PartialProfile` is an interface with `applyTo(ProcParams&)` (`src/engine/procparams.h:1709-1713`). Its implementations:
  - `FullPartialProfile` replaces everything (`procparams.cc:6409-6413`).
  - `FilePartialProfile` loads an .arp file over `pp` (`procparams.cc:6421-6426`).
  - `PEditedPartialProfile` takes either an .arp file or a `ProcParams` plus a `ParamsEdited` mask. It saves to a `KeyFile` and loads it back filtered by the mask (`procparams.cc:6441-6466`).
  - `MultiPartialProfile` chains several (`procparams.h:1752-1762`).
- Loading from a `KeyFile` only assigns keys that are present: `assignFromKeyfile` checks `keyfile.has_key` (`procparams.cc:317-325`). The `RELEVANT_` mask gates whole groups (`procparams.cc:4166`). So **an .arp text fragment containing only a few groups/keys is already a partial profile**, and the keys it lacks are left untouched.
- There is no in-memory text → `PartialProfile` class today. `FilePartialProfile` needs a path. The minimal addition is a tiny `KeyFilePartialProfile` that runs `KeyFile::load_from_data(text)` (`procparams.cc:231-234`) and then `pp.load(nullptr, keyfile, nullptr, false)` (`procparams.cc:6299-6304`). The other option is to write a temp file and use `FilePartialProfile`. A missing `[Version]` group defaults to the current `PPVERSION` (`procparams.cc:4176-4187`).
- Reading back as .arp text: `ProcParams::save(pl, keyFile, pedited, fname)` (`procparams.cc:4095-4100`), then `KeyFile::to_data()` (`procparams.cc:236`). This is the same sequence `ProcParams::save(fname)` uses (`procparams.cc:2869-2886`).

## 3. Reading the current profile

- `ImProcCoordinator::getParams(dst)` returns `*dst = params` (`src/engine/improccoordinator.h:211`). That is the **last params handed to the processing thread**, read without a lock. `nextParams` (pending, under `paramsUpdateMutex`) can be newer if processing is still catching up. The GUI uses it everywhere: on save (`editorpanel.cc:1287`), Save As (`:2267`), send-to-GIMP (`:2341`). On the GTK thread right after an apply, `process()` copies `nextParams` → `params` almost immediately (`improccoordinator.cc:1533`). If exactness matters, read `*ipc->beginUpdateParams()` and then call `endUpdateParams(0)`, or add a locked getter.
- `EditorPanel::saveProfile` (`editorpanel.cc:1274-1296`) shows how to persist the profile to the sidecar: `openThm->setProcParams(FullPartialProfile(params), EDITOR)`.

## 4. Grabbing the image

- **Preview (cheap).** `ImProcCoordinator::updatePreviewImage` converts to the monitor profile (`rgb2monitor`) into `previmg` and calls `imageListener->setImage(...)` / `imageReady(crop)` from the worker thread (`improccoordinator.cc:595`, `:622-634`). The listener is the editor's `PreviewHandler` (`editorpanel.cc:1154,1160`). `PreviewHandler::imageReady` posts an idle callback that wraps the 8-bit buffer as `previewImg` (a `Gdk::Pixbuf`) under `previewImgMutex` and fires `previewImageChanged()` (`src/gui/previewhandler.cc:119-146`, `:212-219`). Read it with `getRoughImage(desiredW, desiredH, zoom)` (`previewhandler.cc:183-210`) and encode it to PNG/JPEG with `Gdk::Pixbuf::save_to_buffer`. It is the whole frame, subsampled by the preview scale (set to 10 in `editorpanel.cc:1161`), in **monitor** color space. A post-apply hook can wait for `PreviewListener::previewImageChanged` (register through `addPreviewImageListener`, `previewhandler.h:69`). It can also watch `EditorPanel::setProgressState(false)`, which `process()` calls when the queue drains (`improccoordinator.cc:1594-1596`; `editorpanel.cc:1397-1417`).
- **The 100% detail view** is in `ImageArea`'s `CropHandler`/`CropWindow` (`editorpanel.cc:1197-1199`). It covers only the visible region, so it is not a good grab target.
- **Full-size render (export quality).** Copy Save As: `ipc->getParams(&pp)`, then `create_processing_job(ipc->getInitialImage(), pp, fast_export)`, then `ProgressConnector::startFunc(processImage, idle_done)` (`editorpanel.cc:2266-2290`). `startFunc` runs `processImage` on a `ThreadPool` NORMAL task (`src/gui/progressconnector.h:97-107`), and the end handler runs back on the GTK side. `EditorPanel::saveImmediately` (`editorpanel.cc:2361-2375`) is the synchronous version. **Do not** call it on the GTK thread for the Live server, because it would freeze the UI for seconds. The output is an `IImagefloat` in the output profile, which can be saved with `saveAsTIFF/PNG/JPEG`.

## 5. Threading rules

- GTK main thread: everything in `ProfilePanel`, `ToolPanelCoordinator`, `History` and the `EditorPanel` widgets, including `profileChange` (it calls `toolPanel->read`, which touches widgets).
- Engine worker: `ImProcCoordinator::process` (ThreadPool HIGHEST). It talks back only through listeners that re-post to the GUI with `IdleRegister` (`previewhandler.cc:57,90,123`; `editorpanel.cc:1391,1401`).
- `beginUpdateParams`/`endUpdateParams` is the only lock between the two threads for parameters (`paramsUpdateMutex`).
- Older code also uses `GThreadLock` (`gdk_threads_enter/leave`, `src/gui/guiutils.h:107-111`), for example in `main.cc` actions. New code should marshal with an idle callback instead: `IdleRegister::add` → `gdk_threads_add_idle_full` (`guiutils.cc:53-77`). The control-channel thread posts a closure and blocks on a promise/future for the reply.

## 6. Reaching the active EditorPanel

`RTWindow` (`src/gui/rtwindow.h:60`) owns the editors. The layout depends on mode:

- **Simple editor / GIMP plugin** (`simpleEditor` global, `src/gui/main.cc:76-77`): a single `RTWindow::epanel` is the main widget (`rtwindow.cc:408-413`).
- **Single-tab mode** (`isSingleTabMode()` = `!options.tabbedUI && multiDisplayMode == 0`, `rtwindow.h:155-158`): there is one reusable `epanel` created by `createSetmEditor` (`rtwindow.cc:1383-1388`) on a `mainNB` page.
- **Multi-tab mode**: each image is an `EditorPanel` page in `mainNB`, also tracked in `std::map<Glib::ustring, EditorPanel*> epanels` keyed by filename (`rtwindow.h:142`; `rtwindow.cc:738-786`). The active editor is `static_cast<EditorPanel*>(mainNB->get_nth_page(mainNB->get_current_page()))`, guarded by `isEditorPanel(page)`. `rtwindow.cc:807-815` and `:919-923` use exactly this pattern.
- **Multi-display mode** (`multiDisplayMode > 0`): the editors live in the separate `EditWindow` singleton, with its own `mainNB` and `epanels` (`src/gui/editwindow.h:38`; `editwindow.cc:216,236`). `addEditorPanel` routes there (`rtwindow.cc:740-745`).

Suggested hook: a new `EditorPanel *RTWindow::getActiveEditorPanel()` that covers the four cases (epanel in simple/single-tab mode, current `mainNB` page if it is an editor, `EditWindow`'s current page in multi-display mode), returning nullptr when no image is open (`EditorPanel::getFileName()` is empty, `editorpanel.cc:1306-1313`). The `RTWindow*` is created in `main.cc:254-263`. The control channel needs a pointer to it, for example passed in when the channel starts from `create_window()`. Optional selection by filename can reuse `RTWindow::selectEditorPanel(name)` (`rtwindow.cc:824-846`).

`src/gui/main.cc:342-353` already has a Gio::Application `on_command_line` handler (`remote` flag, `main.cc:78`) that forwards a second invocation's arguments to the running instance. It only opens files and sessions, so it is prior art for "talk to the running ART", not a profile channel.

## Open questions

- Should a Live apply be labelled with a custom history text (the `descr` argument), so that undo shows "Live: <tool>"? It is supported as-is.
- `ProfilePanel` behaviour: reuse paste's custom-row dance (recommended) or add a dedicated `EvProfileChanged` variant. A new ProcEvent would also need a `RefreshMapper` entry (`src/engine/refreshmap.cc`).
