## ShotGrid Render Cleanup Script

A Nuke-hosted tool that scans your local render directories and deletes EXR frame sequences according to ShotGrid version status rules. It provides a simple Qt dialog for dry-runs, progress feedback, and one-click deletion.

---

### Table of Contents

1. [Overview](#overview)  
2. [Prerequisites](#prerequisites)  
3. [Installation](#installation)  
4. [Usage](#usage)  
   - 4.1 [Launching in Nuke](#launching-in-nuke)  
   - 4.2 [Dialog Workflow](#dialog-workflow)  
5. [Cleanup Rules](#cleanup-rules)  
6. [Logging](#logging)  
7. [Error Handling](#error-handling)  
8. [Extending or Customizing](#extending-or-customizing)  

---

## Overview

When working on VFX projects, intermediate EXR renders can quickly accumulate on local disks. This script:

- Connects to your current ShotGrid project context.  
- Scans all **.exr** sequences for versions in ShotGrid.  
- Applies three deletion rules based on version status in ShotGrid.  
- Presents results in a Qt dialog for review.  
- Deletes selected frame-sequence folders or files.

---

## Prerequisites

- **Nuke** (with Python API enabled)  
- **ShotGrid Toolkit** (to obtain `sg`, `engine`, and `context`; must be running from within a Toolkit hook or engine)  
- Python modules:  
  - `PySide2` (preferred) or `PySide` or `sgtk.platform.qt`  
  - Standard library: `os`, `sys`, `shutil`, `logging`, `collections`, `traceback`

Ensure your Nuke launcher has access to the same Python environment where ShotGrid Toolkit is installed.

---

## Installation

1. **Copy** the script file (e.g. `sg_render_cleanup.py`) into your Nuke plugin path or Toolkit hook folder.  
2. **Import** or `execfile()` it in your menu initialization, e.g.:

   ```python
   import sg_render_cleanup
   ```

3. **Add** a menu item in your `menu.py`:

   ```python
   import nuke
   from sg_render_cleanup import run_in_nuke

   nuke.menu("Nuke").addCommand("ShotGrid/Render Cleanup", run_in_nuke)
   ```

4. Alternative: **Use** Cragl smartScripter tool to keep track of python script in Nuke.

---

## Usage

### Launching in Nuke

Once installed, select **ShotGrid ▶ Render Cleanup** from the main menu. The tool will:

1. Initialize a ShotGrid connection.  
2. Retrieve your current project context.  
3. Display the cleanup dialog.

If initialization fails, a Nuke message box will report the error.

### Dialog Workflow

1. **Info Panel**  
   - Summarizes the three cleanup rules.  
2. **Dry Run Checkbox**  
   - Checked by default. Scans only; no deletion.  
3. **Scan Button**  
   - Fetches versions, groups by shot/task, applies rules.  
   - Updates progress bar and logs each candidate path.  
4. **Results Text Area**  
   - Shows each deletion candidate and a summary (count + size).  
5. **Delete Files Button**  
   - Only enabled after a scan.  
   - Deletes all listed paths when dry-run is off.  
6. **Close Button**  
   - Exits the dialog.

---

## Cleanup Rules

1. **Rule 1 – “na” Status**  
   Delete **all** EXR renders for versions whose `sg_status_list == "na"`.

2. **Rule 2 – “bkdn” Status**  
   On any shot/task with **multiple** `"bkdn"` versions, delete all **older** frame sequences, preserving only the **newest** `"bkdn"` version.

3. **Rule 3 – “note” Status**  
   On any shot/task with **more than 2** `"note"` versions, delete all but the **two newest** `"note"` versions.

> Versions belonging to excluded pipeline steps (`Roto`, `Paint`, `Prep`, `Ingest`, `v000`) are filtered out before applying rules.

---

## Logging

- All operations are reported at `INFO` level.  
- Filter statistics (kept vs. excluded vs. non-EXR) are displayed after version retrieval.  
- Each deletion candidate is logged with the rule that triggered it.  
- Errors include full stack traces in the UI and console.

---

## Error Handling

- **Missing Toolkit / Context**  
  Prompts Nuke message: “No ShotGrid engine found…”  
- **UI Build Errors**  
  Catches exceptions around widget creation; reports via `nuke.message()`.  
- **Scan/Delete Exceptions**  
  Logged and shown in the dialog; buttons re-enabled to allow retry.

---

## Extending or Customizing

- **Add New Rules**  
  Extend `apply_cleanup_rules()`—remember to update the UI info text.  
- **Change Excluded Steps**  
  Modify `self.excluded_pipeline_steps` in the `RenderCleanup` initializer.  
- **Alternate File Types**  
  Adjust the `.exr` filter in `get_versions_for_cleanup()`.  
- **Different Qt Binding**  
  Swap out PySide2 for PyQt5 or another Qt binding—ensure imports at top are updated.
