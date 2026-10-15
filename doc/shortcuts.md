# Keyboard shortcuts

All keyboard shortcuts of the ART GUI are defined in one place
(`src/gui/shortcutdefs.cc`), handled by the `ShortcutsManager`
(`src/gui/shortcutsmanager.h`), and can be remapped or disabled by the user.

## Customising

### The Preferences tab

The **Shortcuts** tab of the Preferences shows all the actions as a tree, with
the same hierarchy as the ids in `shortcuts.json` (`editor` → `zoom_fit`, ...).
Select an action, then:

* **Change...** (or double-click) records a key press that replaces all of its
  keys; **Add key...** records an additional one; **Disable** removes all of
  them; **Reset** goes back to the standard keys; **Reset all** does that for
  every action. Customised actions are shown in bold.
* The search box above the tree filters it by action name, id or key (a
  matching group is shown with everything in it).
* On macOS, the "Modifier of the mouse actions" choice below the tree sets
  `mouse_primary_modifier` (Cmd or Ctrl); it is not shown elsewhere, where the
  two are the same key. **Reset all** restores it too.
* If another action of the same context already uses the key, you are asked
  whether to take it away from that one.
* Nothing is written until you press OK, and the new keys are used from the
  next start of ART.

Saving **rewrites** your `shortcuts.json`: it will contain only the actions
that differ from the standard keys (the built-in defaults with the installed
`shortcuts.json` on top, see below), and comments are not kept. The first time
this replaces an existing file, the old one is saved as `shortcuts.json.bak`.

### Editing the file

Create `shortcuts.json` in the ART configuration folder (the one that
contains the `options` file, `~/.config/ART` by default). On startup ART
also writes `shortcuts_reference.json` there, listing every action with its
default keys: copy the entries you want to change into `shortcuts.json`.

```json
{
    "version": 1,
    "bindings": {
        // replace the default keys of an action
        "editor.undo": ["Primary+Alt+Z"],
        // more than one key is fine
        "editor.redo": ["Primary+Shift+Z", "Primary+Y"],
        // an empty list (or null) disables the shortcut
        "filebrowser.rename": []
    }
}
```

* Only the actions listed in the file change; the others keep their defaults.
  An action in the file *replaces* all of its default keys.
* The files are applied in layers, each on top of the previous one: the
  built-in defaults (`shortcuts_reference.json`), then the `shortcuts.json`
  that ART installs in its data folder (`data/shortcuts.json` in the sources),
  then yours. The installed one currently restores the older, Ctrl-based
  shortcuts: it replaces `Primary` with `Ctrl` everywhere (apart from quit)
  and sets `"mouse_primary_modifier": "Ctrl"`, which only makes a difference
  on macOS, where `Primary` is Cmd. Delete it,
  or its entries, to get the native shortcuts. The rule about clashes applies
  across the layers: a key of your file that another action of the same
  context already has (from any layer) is ignored.
* Comments (`// ...` and `/* ... */`) are allowed.
* Changes take effect when ART is restarted.
* Problems are reported on the standard error and never prevent ART from
  starting: an unknown action, an unreadable key, or a key that another action
  of the same context already uses is ignored, and the action keeps its
  default. Run ART with the environment variable `ART_SHORTCUTS_DEBUG=1`
  to also see which action each key press triggers.

### Mouse modifier

```json
{ "version": 1, "mouse_primary_modifier": "Ctrl", "bindings": { } }
```

`"mouse_primary_modifier"` (optional) is `"Primary"` (the default) or
`"Ctrl"`. It is the modifier of the mouse actions that used to need the Ctrl
key: Ctrl-click to reset a slider to its last saved value or to select the
parameters when loading, pasting or saving a profile, Ctrl-click on the save,
queue and send-to-editor buttons for a fast export, Ctrl-click and Ctrl-drag in
the crop, curve, mask, spot and gradient tools, Ctrl-click to extend the
selection in the thumbnails, and so on. `"Primary"` is Ctrl on Linux and
Windows and Cmd on macOS; `"Ctrl"` is always the physical Control key (on a
Mac, Ctrl-click is also what the system turns into a right click).
The two differ only on macOS. The tooltips follow the setting. Like the keys,
it is set by the layers in turn, so your file can override the installed one.

### Key syntax

`[Primary+][Ctrl+][Alt+][Shift+]<key>`

* `<key>` is a GDK key name: `z`, `5`, `F3`, `Delete`, `Return`, `space`,
  `Left`, `KP_Add`, `bracketleft`, ... The character `+` itself is written
  `plus` (and `-` is `minus`, `<` is `less`, `,` is `comma`, ...).
  The modifiers are not case sensitive.
* `Primary` is the usual "command" modifier of the platform: **Ctrl on Linux
  and Windows, Cmd on macOS**. All the defaults use it, so the same file works on
  every system. `Ctrl` is the physical Control key: on a Mac it is a different
  key from `Primary`, elsewhere it means the same.
* Keys that need Shift on some keyboard layouts (`plus`, `less`, `underscore`,
  ...) match however the layout types them. For letters and digits use an
  explicit `Shift+`: `Shift+R` and `Shift+r` are the same thing, and Caps Lock
  is ignored.
* Modifiers must match exactly: `Primary+S` does not fire for `Ctrl+Shift+S`.

### Contexts

Each action belongs to a context, i.e. a part of the GUI where it is active.
The same key can be used by actions of different contexts (for example `l`
toggles a panel in both the editor and the file browser); two actions of the same
context cannot share a key. The window decides which contexts are asked, and
in which order, so inside the editor the editor's shortcuts come first and the
file browser ones are tried after them.

## Developers

* Add the action to `defineDefaultShortcuts()` in `shortcutdefs.cc` (id,
  context, default keys), then, from the component that owns the code, call
  `ShortcutsManager::getInstance()->bind(owner, "id", handler [, enabled])` and
  `unbindOwner(owner)` in its destructor. Conditions such as "not in the
  simple editor" go in the `enabled` function, not in the handler.
* A window calls `dispatch(event, phase, chain)` from its key handlers, with
  the ordered list of `{context, owner}` it wants to ask.
* Tooltips and other translated strings can show the key of an action with
  `%shortcut(action.id)%`; it is replaced by the key as GTK displays it in menus
  (`Ctrl+S` on Linux and Windows, `⌘S` on macOS), and follows the user's
  remapping; the unit test checks that the ids exist. `%mouse_primary%` is the
  modifier of the mouse actions (see above), for "`%mouse_primary%`-click".
* `data/shortcuts.json` must list every action whose default uses `Primary`,
  with `Ctrl` instead (the unit test checks it, so a new action fails the test
  until the file is updated).
* Tests of the key syntax, the table and the config handling:
  `ninja art-shortcuts-test && ./src/gui/art-shortcuts-test` (or `ctest -R shortcuts`).
* `ART_SHORTCUTS_DEBUG=1` also prints, a little after startup, the actions
  that no component has bound a handler to.

## Actions and default keys

The keys are listed as in `shortcuts.json`; `Ctrl/Cmd` stands for `Primary`.
(Generated from `shortcuts_reference.json`.)


### `window` – Every window: fullscreen, close an editor tab

| Action | Default keys |
|---|---|
| `window.fullscreen` | `F11` |
| `window.close_tab` | `Ctrl/Cmd+W` |

### `mainwindow` – The main window: quit, switching between the main tabs

| Action | Default keys |
|---|---|
| `window.quit` | `Ctrl/Cmd+Q` |
| `window.show_file_browser` | `Ctrl/Cmd+F2` |
| `window.show_queue` | `Ctrl/Cmd+F3` |
| `window.show_editor` | `Ctrl/Cmd+F4` |

### `editor` – The editor

| Action | Default keys |
|---|---|
| `editor.toggle_top_panel` | `Shift+L` |
| `editor.toggle_history_panel` | `L` |
| `editor.toggle_history_and_right_panels` | `Alt+L` |
| `editor.toggle_right_panel` | `Ctrl/Cmd+L` |
| `editor.maximize_preview` | `M` |
| `editor.maximize_preview_fit` | `Shift+M` |
| `editor.toggle_preview_background` | `9` |
| `editor.rotate_right` | `bracketright` |
| `editor.rotate_left` | `bracketleft` |
| `editor.toggle_info` | `Shift+I` |
| `editor.toggle_before_after` | `Shift+A` |
| `editor.zoom_in` | `plus`, `equal`, `KP_Add` |
| `editor.zoom_out` | `minus`, `underscore`, `KP_Subtract` |
| `editor.zoom_100` | `Z` |
| `editor.zoom_fit` | `F` |
| `editor.toggle_red_preview` | `Shift+R` |
| `editor.toggle_green_preview` | `Shift+G` |
| `editor.toggle_blue_preview` | `Shift+B` |
| `editor.toggle_luminosity_preview` | `Shift+V` |
| `editor.toggle_sharpening_mask` | `Shift+O` |
| `editor.toggle_focus_mask` | `Shift+F` |
| `editor.toggle_false_colors` | `Shift+E` |
| `editor.toggle_shadow_clipping` | `less` |
| `editor.toggle_highlight_clipping` | `greater` |
| `editor.sync_file_browser` | `Y` |
| `editor.sync_file_browser_clear_filters` | `X` |
| `editor.save` | `Ctrl/Cmd+S` |
| `editor.save_fast` | `Ctrl/Cmd+Shift+S` |
| `editor.queue` | `Ctrl/Cmd+B` |
| `editor.queue_fast` | `Ctrl/Cmd+Shift+B` |
| `editor.send_to_external_editor` | `Ctrl/Cmd+E` |
| `editor.send_to_external_editor_alt` | `Ctrl/Cmd+Shift+E` |
| `editor.undo` | `Ctrl/Cmd+Z` |
| `editor.redo` | `Ctrl/Cmd+Shift+Z`, `Ctrl/Cmd+Y` |
| `editor.previous_snapshot` | `Ctrl/Cmd+comma` |
| `editor.next_snapshot` | `Ctrl/Cmd+period` |
| `editor.toggle_grid` | `Ctrl/Cmd+G` |
| `editor.add_snapshot` | `Alt+S` |
| `editor.previous_image` | `Shift+F3` |
| `editor.next_image` | `Shift+F4` |

### `editor-scroll` – The editor: moving the image with the keyboard

| Action | Default keys |
|---|---|
| `editor.scroll_up` | `Ctrl/Cmd+Up`, `Ctrl/Cmd+KP_Up` |
| `editor.scroll_down` | `Ctrl/Cmd+Down`, `Ctrl/Cmd+KP_Down` |
| `editor.scroll_left` | `Ctrl/Cmd+Left`, `Ctrl/Cmd+KP_Left` |
| `editor.scroll_right` | `Ctrl/Cmd+Right`, `Ctrl/Cmd+KP_Right` |

### `toolbar` – The tool buttons next to the preview

| Action | Default keys |
|---|---|
| `toolbar.white_balance_picker` | `Shift+W` |
| `toolbar.crop` | `Shift+C` |
| `toolbar.straighten` | `Shift+S` |
| `toolbar.hand` | `H`, `Shift+H` |
| `toolbar.perspective` | `Shift+P` |

### `toolpanel` – The tool panel tabs

| Action | Default keys |
|---|---|
| `toolpanel.tab_favorites` | `Alt+U` |
| `toolpanel.tab_exposure` | `Alt+E` |
| `toolpanel.tab_details` | `Alt+D` |
| `toolpanel.tab_color` | `Alt+C` |
| `toolpanel.tab_transform` | `Alt+T` |
| `toolpanel.tab_raw` | `Alt+R` |
| `toolpanel.tab_effects` | `Alt+F` |
| `toolpanel.tab_local` | `Alt+X` |
| `toolpanel.tab_metadata` | `Alt+M` |

### `tool` – Held-key shortcuts for the tool sliders, and the F1 help

| Action | Default keys |
|---|---|
| `tool.help` | `F1` |
| `tool.exposure.compensation` | `E` |
| `tool.exposure.black` | `Q` |
| `tool.tonecurve.contrast` | `C` |
| `tool.saturation.saturation` | `S` |
| `tool.saturation.vibrance` | `V` |
| `tool.labcurve.brightness` | `I` |
| `tool.labcurve.contrast` | `J` |
| `tool.labcurve.chromaticity` | `N` |
| `tool.whitebalance.temperature` | `T` |
| `tool.whitebalance.tint` | *(none)* |
| `tool.logencoding.gain` | `G` |
| `tool.logencoding.target_gray` | `B` |
| `tool.logencoding.white_ev` | `W` |
| `tool.logencoding.black_ev` | `D` |
| `tool.logencoding.highlight_compression` | `K` |
| `tool.toneequalizer.band.1` | `1` |
| `tool.toneequalizer.band.2` | `2` |
| `tool.toneequalizer.band.3` | `3` |
| `tool.toneequalizer.band.4` | `4` |
| `tool.toneequalizer.band.5` | `5` |
| `tool.softlight.strength` | `O` |

### `tool-value` – While such a key is held: change or reset the slider

| Action | Default keys |
|---|---|
| `tool.value_up` | `plus`, `equal`, `KP_Add` |
| `tool.value_down` | `minus`, `KP_Subtract` |
| `tool.value_zero` | `asterisk`, `KP_Multiply`, `0` |
| `tool.value_initial` | `slash`, `KP_Divide` |

### `filepanel` – The file browser panel

| Action | Default keys |
|---|---|
| `filepanel.toggle_right_notebook` | `Ctrl/Cmd+I`, `Ctrl/Cmd+Shift+I` |

### `filecatalog` – The file browser: filters, panels, trash, path and query boxes

| Action | Default keys |
|---|---|
| `filecatalog.toggle_left_panel` | `L` |
| `filecatalog.toggle_right_panel` | `Ctrl/Cmd+L` |
| `filecatalog.toggle_left_and_right_panels` | `Ctrl/Cmd+Alt+L` |
| `filecatalog.maximize` | `M` |
| `filecatalog.reset_path` | `Escape` |
| `filecatalog.filter_unranked` | `0`, `Ctrl/Cmd+0` |
| `filecatalog.filter_rank.1` | `1`, `Ctrl/Cmd+1` |
| `filecatalog.filter_rank.2` | `2`, `Ctrl/Cmd+2` |
| `filecatalog.filter_rank.3` | `3`, `Ctrl/Cmd+3` |
| `filecatalog.filter_rank.4` | `4`, `Ctrl/Cmd+4` |
| `filecatalog.filter_rank.5` | `5`, `Ctrl/Cmd+5` |
| `filecatalog.filter_not_edited` | `6`, `Ctrl/Cmd+6` |
| `filecatalog.filter_edited` | `7`, `Ctrl/Cmd+7` |
| `filecatalog.filter_no_label` | `Alt+0`, `Ctrl/Cmd+Alt+0` |
| `filecatalog.filter_label.1` | `Alt+1`, `Ctrl/Cmd+Alt+1` |
| `filecatalog.filter_label.2` | `Alt+2`, `Ctrl/Cmd+Alt+2` |
| `filecatalog.filter_label.3` | `Alt+3`, `Ctrl/Cmd+Alt+3` |
| `filecatalog.filter_label.4` | `Alt+4`, `Ctrl/Cmd+Alt+4` |
| `filecatalog.filter_label.5` | `Alt+5`, `Ctrl/Cmd+Alt+5` |
| `filecatalog.filter_not_recently_saved` | `Alt+6`, `Ctrl/Cmd+Alt+6` |
| `filecatalog.filter_recently_saved` | `Alt+7`, `Ctrl/Cmd+Alt+7` |
| `filecatalog.filter_clear` | `D`, `Shift+D` |
| `filecatalog.browse` | `Return`, `KP_Enter` |
| `filecatalog.toggle_exif` | `I`, `Alt+I` |
| `filecatalog.zoom_in` | `plus`, `equal`, `Alt+plus`, `Alt+equal` |
| `filecatalog.zoom_out` | `minus`, `underscore`, `Alt+minus`, `Alt+underscore` |
| `filecatalog.focus_path` | `Ctrl/Cmd+O`, `Ctrl/Cmd+Shift+O` |
| `filecatalog.focus_query` | `Ctrl/Cmd+F` |
| `filecatalog.toggle_trash` | `Ctrl/Cmd+T`, `Ctrl/Cmd+Shift+T` |
| `filecatalog.empty_trash` | `Ctrl/Cmd+Shift+Delete` |
| `filecatalog.toggle_toolbar` | `T`, `Shift+T` |
| `filecatalog.refresh` | `F5` |

### `filecatalog-session` – The file browser: session buttons (only when they are shown)

| Action | Default keys |
|---|---|
| `filecatalog.session_load` | `Ctrl/Cmd+O` |
| `filecatalog.session_add` | `Ctrl/Cmd+plus` |
| `filecatalog.session_remove` | `Ctrl/Cmd+minus` |
| `filecatalog.session_save` | `Ctrl/Cmd+S` |

### `filebrowser` – The thumbnails of the file browser

| Action | Default keys |
|---|---|
| `filebrowser.inspector_popover` | `Ctrl/Cmd+space` |
| `filebrowser.copy_to` | `Ctrl/Cmd+Shift+C` |
| `filebrowser.move_to` | `Ctrl/Cmd+Shift+M` |
| `filebrowser.copy_profile` | `Ctrl/Cmd+C`, `Ctrl/Cmd+Insert` |
| `filebrowser.paste_profile` | `Ctrl/Cmd+V`, `Shift+Insert` |
| `filebrowser.paste_profile_partial` | `Ctrl/Cmd+Shift+V` |
| `filebrowser.trash` | `Delete` |
| `filebrowser.untrash` | `Shift+Delete` |
| `filebrowser.remove` | `Ctrl/Cmd+Shift+Delete` |
| `filebrowser.queue` | `Ctrl/Cmd+B` |
| `filebrowser.queue_fast` | `Ctrl/Cmd+Shift+B` |
| `filebrowser.select_all` | `Ctrl/Cmd+A` |
| `filebrowser.rename` | `F2` |
| `filebrowser.add_to_session` | `Ctrl/Cmd+Shift+S` |
| `filebrowser.open_previous` | `F3` |
| `filebrowser.open_next` | `F4` |
| `filebrowser.select_previous` | `Left`, `BackSpace`, `Shift+Left`, `Shift+BackSpace` |
| `filebrowser.select_next` | `Right`, `space`, `Shift+Right`, `Shift+space` |
| `filebrowser.select_row_up` | `Up`, `Shift+Up` |
| `filebrowser.select_row_down` | `Down`, `Shift+Down` |
| `filebrowser.select_first` | `Home`, `Shift+Home` |
| `filebrowser.select_last` | `End`, `Shift+End` |
| `filebrowser.open` | `Return`, `KP_Enter` |
| `filebrowser.page_up` | `Page_Up` |
| `filebrowser.page_down` | `Page_Down` |
| `filebrowser.set_rank.0` | `Shift+0` |
| `filebrowser.set_label.0` | `Ctrl/Cmd+Shift+0` |
| `filebrowser.set_rank.1` | `Shift+1` |
| `filebrowser.set_label.1` | `Ctrl/Cmd+Shift+1` |
| `filebrowser.set_rank.2` | `Shift+2` |
| `filebrowser.set_label.2` | `Ctrl/Cmd+Shift+2` |
| `filebrowser.set_rank.3` | `Shift+3` |
| `filebrowser.set_label.3` | `Ctrl/Cmd+Shift+3` |
| `filebrowser.set_rank.4` | `Shift+4` |
| `filebrowser.set_label.4` | `Ctrl/Cmd+Shift+4` |
| `filebrowser.set_rank.5` | `Shift+5` |
| `filebrowser.set_label.5` | `Ctrl/Cmd+Shift+5` |

### `filebrowser-inspector` – The thumbnails, while the inspector is shown

| Action | Default keys |
|---|---|
| `filebrowser.inspector_set_rank.0` | `0` |
| `filebrowser.inspector_set_label.0` | `Ctrl/Cmd+0` |
| `filebrowser.inspector_set_rank.1` | `1` |
| `filebrowser.inspector_set_label.1` | `Ctrl/Cmd+1` |
| `filebrowser.inspector_set_rank.2` | `2` |
| `filebrowser.inspector_set_label.2` | `Ctrl/Cmd+2` |
| `filebrowser.inspector_set_rank.3` | `3` |
| `filebrowser.inspector_set_label.3` | `Ctrl/Cmd+3` |
| `filebrowser.inspector_set_rank.4` | `4` |
| `filebrowser.inspector_set_label.4` | `Ctrl/Cmd+4` |
| `filebrowser.inspector_set_rank.5` | `5` |
| `filebrowser.inspector_set_label.5` | `Ctrl/Cmd+5` |

### `inspector` – The inspector

| Action | Default keys |
|---|---|
| `inspector.toggle_histogram` | `H` |
| `inspector.toggle_cms` | `C` |
| `inspector.zoom_100` | `Z` |
| `inspector.zoom_fit` | `X` |
| `inspector.mode_jpeg` | `J` |
| `inspector.mode_raw_linear` | `R` |
| `inspector.mode_raw_film_curve` | `F` |
| `inspector.mode_raw_shadow_boost` | `S` |
| `inspector.mode_raw_clip_warning` | `W` |
| `inspector.toggle_split` | `Y` |
| `inspector.switch_pane` | `Tab` |
| `inspector.toggle_focus_mask` | `Shift+F` |
| `inspector.toggle_info` | `Shift+I` |

### `inspector-popover` – The inspector popup (Ctrl-Space)

| Action | Default keys |
|---|---|
| `inspector.popover.mode_jpeg` | `J` |
| `inspector.popover.mode_raw_linear` | `R` |
| `inspector.popover.mode_raw_film_curve` | `F` |
| `inspector.popover.mode_raw_shadow_boost` | `S` |
| `inspector.popover.mode_raw_clip_warning` | `W` |

### `queuepanel` – The processing queue tab

| Action | Default keys |
|---|---|
| `queue.start_stop` | `Ctrl/Cmd+S` |

### `queue` – The thumbnails of the processing queue

| Action | Default keys |
|---|---|
| `queue.select_all` | `Ctrl/Cmd+A` |
| `queue.open_in_editor` | `Ctrl/Cmd+E` |
| `queue.select_first` | `Home`, `Shift+Home` |
| `queue.select_last` | `End`, `Shift+End` |
| `queue.move_to_head` | `Ctrl/Cmd+Home` |
| `queue.move_to_tail` | `Ctrl/Cmd+End` |
| `queue.cancel` | `Delete` |
| `queue.select_previous` | `Left`, `Shift+Left` |
| `queue.select_next` | `Right`, `Shift+Right` |
| `queue.select_row_up` | `Up`, `Shift+Up` |
| `queue.select_row_down` | `Down`, `Shift+Down` |

### `drawnmask` – Drawn masks

| Action | Default keys |
|---|---|
| `drawnmask.undo` | `Ctrl/Cmd+Z` |
| `drawnmask.reset` | `Ctrl/Cmd+Shift+Z` |

### `maskspanel` – The masks list

| Action | Default keys |
|---|---|
| `masks.toggle_show` | `Ctrl/Cmd+M` |
| `masks.toggle_selected_enabled` | `Ctrl/Cmd+X` |

### `saveas` – The "Save as" dialog

| Action | Default keys |
|---|---|
| `saveas.ok` | `Ctrl/Cmd+Return`, `Ctrl/Cmd+KP_Enter` |
