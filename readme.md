## ShotGrid Render Cleanup Script

A Nuke tool that looks in your local render directories and clears out EXR sequences according to ShotGrid version status rules. It provides a simple Qt dialog for dry-runs, progress feedback, and one-click deletion.

---

## Overview

When working on VFX projects, large EXR renders can quickly accumulate on local disks. This script:

- Connects to your current ShotGrid project context.  
- Scans all **.exr** sequences for versions in ShotGrid.  
- Applies three deletion rules based on version status in ShotGrid.  
- Presents results in a Qt dialog for review.  
- Deletes selected image-sequence folders and files.

---

## Prerequisites

- **Nuke** (with Python API)  
- **ShotGrid Toolkit** (to obtain `sg`, `engine`, and `context`; must be running from within a Toolkit hook or engine)  
- Python modules:  
  - `PySide2`
  - Standard library: `os`, `sys`, `shutil`, `logging`, `collections`, `traceback`

Make sure your Nuke launcher has access to the same Python environment where ShotGrid Toolkit is installed.

---

## Optional Installation

1. Copy the script file (`cleanup.py`) into your Nuke plugin path or Toolkit hook folder.  
2. Add a menu item in your `menu.py`
3. Alternative: **Use** Cragl smartScripter tool to keep track of python script in Nuke.

---

## Usage

### Running from Script Editor

Copy and paste the cleanup.py contents into the nuke script editor while in the appropriate SG toolkit context. Run from there.


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

## Currently Baked-In Cleanup Rules

1. **Rule 1 – “na” Status**  
   Delete **all** EXR renders for versions whose `sg_status_list == "na"`.

2. **Rule 2 – “bkdn” Status**  
   On any shot/task with **multiple** `"bkdn"` (Baked Note) versions, delete all **older** frame sequences, preserving only the **newest** `"bkdn"` version.

3. **Rule 3 – “note” Status**  
   On any shot/task with **more than 2** `"note"` (client note) versions, delete all but the **two newest** `"note"` versions.

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
  Extend `apply_cleanup_rules()`— helpful to update the UI info text as well.  
- **Change Excluded Steps**  
  Modify `self.excluded_pipeline_steps` in the `RenderCleanup` initializer.  
- **Alternate File Types**  
  Adjust the `.exr` filter in `get_versions_for_cleanup()`.  
