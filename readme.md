## Full Documentation

#### **ShotGrid Render Cleanup Script**

A Nuke tool that finds and moves EXR render folders based on ShotGrid version status rules. It gives you a Qt dialog for scanning, previewing results, and moving folders to an archive destination.



#### **Overview**

![screenshot](./screenshot.png)

When working on VFX projects, large EXR renders can quickly build up. This script:

- Connects to your current ShotGrid project context.
- Scans all **.exr** sequences for versions in ShotGrid.
- Applies three cleanup rules based on version status in ShotGrid.
- Presents results in a Qt dialog for review.
- Moves identified EXR sequence folders to a destination you choose.



#### **Prerequisites**

- **Nuke** (with Python API)
- **ShotGrid Toolkit** (to obtain `sg`, `engine`, and `context`; must be running from within a Toolkit hook or engine)
- Python modules:
  - `PySide6`, `PySide2`, or `PySide` (auto-detects available version)
  - Standard library: `os`, `sys`, `shutil`, `logging`, `collections`, `traceback`

Make sure your Nuke launcher has access to the same Python environment where ShotGrid Toolkit is installed.



#### **Installation**

1. Copy the script file (`clean-up.py`) into your Nuke plugin path or Toolkit hook folder.
2. Add a menu item in your `menu.py`
3. Alternative: **Use** Cragl smartScripter tool to keep track of python script in Nuke.



#### **Running from Script Editor**

Copy and paste the `clean-up.py` contents into the Nuke script editor while in the appropriate SG toolkit context. Run from there.

#### **Dialog Workflow**

1. **Info Panel**
   - Summarizes the three cleanup rules and pipeline step exclusions.
2. **Scan Button**
   - Fetches versions from ShotGrid, groups by shot/task, applies rules.
   - Updates progress bar and logs each candidate path.
   - Shows total folder count and approximate size.
3. **Preview Text Area**
   - Shows each EXR sequence folder that will be moved and a summary.
4. **Move Files Button**
   - Only enabled after a scan.
   - Prompts for destination folder.
   - Moves all identified folders to the destination in a flat structure.
   - Handles naming conflicts by appending numbers (_1, _2, etc.).
5. **Close Button**
   - Exits the dialog.



#### **Cleanup Rules**

1. **Rule 1 – "na" Status**
   Move **all** EXR renders for versions whose `sg_status_list == "na"`.

2. **Rule 2 – "innote" Status**
   On any shot/task with **multiple** `"innote"` (internal note) versions, move all **older** frame sequences, preserving only the **newest** `"innote"` version.

3. **Rule 3 – "note" Status**
   On any shot/task with **more than 2** `"note"` (client note) versions, move all but the **two newest** `"note"` versions.

> Only applies to internal artist renders. Versions belonging to excluded pipeline steps (`Roto`, `Paint`, `Prep`, `Ingest`, `v000`) are filtered out before applying rules.



#### **File Operations**

- **Archive Structure**: All moved folders are placed in a flat structure under your chosen destination directory.
- **Conflict Resolution**: If a folder name already exists in the destination, it will be renamed with a numeric suffix (_1, _2, etc.).
- **Progress Tracking**: Real-time progress updates during the move operation.
- **Size Calculation**: Displays approximate total size of data to be moved during scan.



#### **Logging**

- All operations are reported at `INFO` level.
- Filter statistics (kept vs. excluded vs. non-EXR) are displayed after version retrieval.
- Each move candidate is logged with the rule that triggered it.
- Move operations show source and destination paths.
- Errors include full stack traces in the UI and console.



#### **Error Handling**

- **Missing Toolkit / Context**
  Prompts Nuke message: "No ShotGrid engine found…"
- **UI Build Errors**
  Catches exceptions around widget creation; reports via `nuke.message()`.
- **Scan/Move Exceptions**
  Logged and shown in the dialog; buttons re-enabled to allow retry.
- **Missing Files**
  Paths that no longer exist on the file system are skipped with warnings.



#### **Extending or Customizing**

- **Add New Rules**
  Extend `apply_cleanup_rules()` method and update the UI info text.
- **Change Excluded Steps**
  Modify `self.excluded_pipeline_steps` in the `RenderCleanup` initializer.
- **Alternate File Types**
  Adjust the `.exr` filter in `get_versions_for_cleanup()`.
- **Different Archive Structure**
  Modify the `move_files()` method to organize moved folders differently.

#### Full List of API Functions:

#### Nuke API
- `import nuke`
- **User messaging**
  - `nuke.message(str)` — error/info popups throughout error paths.
- *(You don’t touch nodes/knobs here; Nuke is mainly the host + message box.)*

#### Qt / PySide (GUI)

Compat shim selects one of these: **PySide6**, **PySide2**, or legacy **PySide**.

- **Core widgets & windowing**
  - `QtWidgets.QDialog()` — main window
  - `QtWidgets.QVBoxLayout()`, `QtWidgets.QHBoxLayout()` — layout managers
  - `QtWidgets.QLabel()` — info/status text
  - `QtWidgets.QProgressBar()` — scan/move progress
  - `QtWidgets.QTextEdit()` — the **Preview:** log/output pane
  - `QtWidgets.QPushButton()` — Scan / Move Files / Close
  - `QtWidgets.QFileDialog()` — destination folder chooser
  - `QtWidgets.QApplication.processEvents()` — keep UI responsive during long ops

- **Text cursor (autoscroll)**
  - `QtGui.QTextCursor` (or `QtCore.QTextCursor` fallback) — to move cursor to End for auto-scroll

- **Dialog control**
  - `dialog.setWindowTitle(...)`, `setMinimumWidth/Height(...)`, `setLayout(...)`, `exec()/exec_()`
  - `QFileDialog.setFileMode(QtWidgets.QFileDialog.Directory)`, `setOption(...)`, `selectedFiles()`


#### ShotGrid API (via Toolkit / `sgtk`)
- **Toolkit bootstrap**
  - `import sgtk`
  - `sgtk.platform.current_engine()` → `engine`
  - `engine.context` → `context`
  - `context.sgtk.shotgun` → `sg` (ShotGrid connection)

- **Project context**
  - `context.project` — dict with current project (`name`, `id`)

- **Fetching Versions**
  - `sg.find('Version', filters, fields, order=[...])`
  - **Filters used:** `['project','is',project]`, `['sg_path_to_frames','is_not',None]`
  - **Fields used:** `code`, `sg_status_list`, `entity`, `sg_task`,
    `sg_task.Task.step`, `sg_path_to_frames`, `created_at`
  - **Order:** by `created_at` ascending

- **Entity field access (read)**
  - `version['entity']` (Shot), `version['sg_task']` (Task), `version['sg_task']['id']`
  - `version['sg_task.Task.step'] → ['name']` (Pipeline Step)
  - `version['sg_status_list']`, `version['sg_path_to_frames']`, `version['code']`, `version['created_at']`

*(All SG interaction is read-only in this script.)*

#### shutil (file moves)
- **Moving folders**
  - `shutil.move(src_dir, dest_dir)` — moves each sequence folder into the chosen archive location
- *(No `rmtree` here; it’s a move-only tool.)*

#### os / filesystem helpers
- **Path inspection**
  - `os.path.exists(path)`, `os.path.isdir(path)`, `os.path.getsize(file)`
  - `os.path.dirname(frame_path)` — derive sequence directory from `sg_path_to_frames`
  - `os.path.basename(path)`, `os.path.join(a, b)`

- **Directory walking & sizing**
  - `os.walk(dirpath)` — estimate total bytes to move

- **De-dupe helper**
  - Logic uses Python `set()`s, not OS


#### Logging / diagnostics
- **Setup**
  - `logging.getLogger("sg_render_cleanup")`, `setLevel(logging.INFO)`
  - `logging.StreamHandler()`, `logging.Formatter(...)`, `addHandler(handler)`

- **Usage**
  - `log.info(...)`, `log.error(...)` — mirrored into UI via `results_text.append(...)`

- **Tracebacks**
  - `traceback.format_exc()` — included in UI and message boxes on errors

#### Python collections / data shaping
- **Grouping by (shot, task)**
  - `collections.defaultdict(list)` — `task_versions[key].append(version)`
