"""
ShotGrid Render Cleanup Script
This script identifies EXR render folders to move based on specific rules:
1. All EXR renders linked to versions with status "na"
2. All older EXR renders linked to versions with status "innote" (internal note) on shots with multiple "innote" versions, except the newest version
3. All older EXR renders linked to versions with status "note" (client note) on shots with more than 2 "note" versions, except the 2 latest versions

Workflow:
- Click "Scan" to preview all eligible EXR sequence directories in the "Preview:" box.
- Click "Move Files" to pick a destination and move those folders into a single flat list under that destination.
"""

import os
import sys
import shutil
import traceback
from collections import defaultdict
import logging
import nuke

# ---- Qt compat shim (PySide6 first, then PySide2, then PySide) ---
try:
    from PySide6 import QtWidgets, QtCore, QtGui
    QT_BINDING = "PySide6"
except ImportError:
    try:
        from PySide2 import QtWidgets, QtCore, QtGui
        QT_BINDING = "PySide2"
    except ImportError:
        from PySide import QtGui, QtCore  # legacy
        QtWidgets = QtGui
        QT_BINDING = "PySide"

# QTextCursor compat
try:
    QTextCursor = QtGui.QTextCursor
except Exception:
    QTextCursor = QtCore.QTextCursor

sg = None
engine = None
context = None

def setup_logger():
    log = logging.getLogger("sg_render_cleanup")
    log.setLevel(logging.INFO)
    if not log.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        log.addHandler(handler)
    return log

log = setup_logger()

class RenderCleanup(object):
    def __init__(self):
        self.dialog = None
        self.results_text = None
        self.progress_bar = None
        self.status_label = None
        self.scan_button = None
        self.move_button = None

        self.moved_paths = []
        self.paths_to_move = []

        try:
            import sgtk
            self.engine = sgtk.platform.current_engine()
            if not self.engine:
                raise ImportError("No ShotGrid engine found. Are you running this from within ShotGrid?")

            self.context = self.engine.context
            if not self.context:
                raise ImportError("No ShotGrid context found. Are you in a valid ShotGrid context?")

            self.sg = self.context.sgtk.shotgun
            if not self.sg:
                raise ImportError("Could not connect to ShotGrid")

            self.log = log
            self.log.info("Successfully initialized ShotGrid connection")

            self.excluded_pipeline_steps = ["Roto", "Paint", "Prep", "Ingest", "v000"]

        except ImportError as e:
            error_message = f"Could not import ShotGrid Toolkit: {str(e)}"
            nuke.message(error_message)
            log.error(error_message)
            raise

    def show_dialog(self):
        """Display the cleanup dialog"""
        try:
            if not self.dialog:
                self.dialog = QtWidgets.QDialog()
                self.dialog.setWindowTitle("ShotGrid Render Cleanup (Move EXR Folders)")
                self.dialog.setMinimumWidth(640)
                self.dialog.setMinimumHeight(520)

                layout = QtWidgets.QVBoxLayout()
                self.dialog.setLayout(layout)

                info_label = QtWidgets.QLabel(
                    "This tool identifies EXR render folders by rules and moves them to a destination you choose:"
                    "<ul>"
                    "<li>All EXR renders with Version status 'na'</li>"
                    "<li>Older EXR renders with status 'innote' (keep newest)</li>"
                    "<li>Older EXR renders with status 'note' when more than 2 exist (keep 2 newest)</li>"
                    "</ul>"
                    "Only applies to internal artist renders (excluding 'Paint', 'Roto', 'Prep', 'Ingest', and 'v000' pipeline steps)."
                )
                info_label.setWordWrap(True)
                layout.addWidget(info_label)

                # Progress bar + status
                self.progress_bar = QtWidgets.QProgressBar()
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setVisible(False)
                layout.addWidget(self.progress_bar)

                self.status_label = QtWidgets.QLabel("")
                self.status_label.setVisible(False)
                layout.addWidget(self.status_label)

                # Results preview area
                preview_label = QtWidgets.QLabel("<span style='color:#56BCF9; font-weight:bold;'>Preview:</span>")
                layout.addWidget(preview_label)

                self.results_text = QtWidgets.QTextEdit()
                self.results_text.setReadOnly(True)
                layout.addWidget(self.results_text)

                # Buttons
                button_layout = QtWidgets.QHBoxLayout()

                self.scan_button = QtWidgets.QPushButton("Scan")
                self.scan_button.clicked.connect(self.run_scan)
                button_layout.addWidget(self.scan_button)

                self.move_button = QtWidgets.QPushButton("Move Files")
                self.move_button.clicked.connect(self.move_files)
                button_layout.addWidget(self.move_button)

                close_button = QtWidgets.QPushButton("Close")
                close_button.clicked.connect(self.dialog.close)
                button_layout.addWidget(close_button)

                layout.addLayout(button_layout)

            if hasattr(self.dialog, "exec"):
                self.dialog.exec()
            else:
                self.dialog.exec_()

        except Exception as e:
            error_msg = f"Error creating dialog: {str(e)}\n{traceback.format_exc()}"
            self.log.error(error_msg)
            nuke.message(error_msg)

    def run_scan(self):
        """Run the scan to identify folders to move"""
        try:
            self.scan_button.setEnabled(False)

            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            self.status_label.setText("Starting scan...")
            self.status_label.setVisible(True)
            QtWidgets.QApplication.processEvents()

            if self.results_text:
                self.results_text.clear()

            self.log_message("Starting scan...")

            project = self.context.project
            if not project:
                self.log_message("Error: No project found in context")
                self.scan_button.setEnabled(True)
                return

            self.update_progress(10, "Fetching versions...")
            self.log_message(f"Fetching versions for project: {project['name']}")

            all_versions = self.get_versions_for_cleanup(project)
            self.log_message(f"Found {len(all_versions)} versions to analyze")

            self.update_progress(40, "Grouping versions by shot/task...")
            task_versions = self.group_versions_by_shot(all_versions)

            self.update_progress(60, "Applying cleanup rules...")
            self.paths_to_move = self.apply_cleanup_rules(task_versions)

            self.update_progress(90, "Finalizing results...")

            # Calculate total size (best-effort)
            total_size_bytes = 0
            for p in self.paths_to_move:
                if os.path.exists(p):
                    if os.path.isdir(p):
                        for dirpath, _, filenames in os.walk(p):
                            for f in filenames:
                                fp = os.path.join(dirpath, f)
                                if os.path.exists(fp):
                                    try:
                                        total_size_bytes += os.path.getsize(fp)
                                    except Exception:
                                        pass
                    else:
                        try:
                            total_size_bytes += os.path.getsize(p)
                        except Exception:
                            pass

            def _fmt_bytes(b):
                if b > 1099511627776:
                    return f"{b / 1099511627776:.2f} TB"
                if b > 1073741824:
                    return f"{b / 1073741824:.2f} GB"
                if b > 1048576:
                    return f"{b / 1048576:.2f} MB"
                if b > 1024:
                    return f"{b / 1024:.2f} KB"
                return f"{b} bytes"

            if self.paths_to_move:
                self.log_message("EXR sequence folders identified:")
                for p in self.paths_to_move:
                    self.log_message(f"  - {p}")
            else:
                self.log_message("No EXR sequence folders found to move.")

            self.log_message("\n" + "="*50)
            self.log_message("SCAN SUMMARY:")
            self.log_message(f"Total folders: {len(self.paths_to_move)}")
            self.log_message(f"Approximate total size: {_fmt_bytes(total_size_bytes)}")
            self.log_message("="*50)

            self.update_progress(100, "Scan complete")
            self.scan_button.setEnabled(True)

        except Exception as e:
            error_msg = f"Error during scan: {str(e)}"
            self.log_message(error_msg)
            self.log_message(traceback.format_exc())
            nuke.message(error_msg)
            self.scan_button.setEnabled(True)
            self.status_label.setText("Error during scan")
            self.update_progress(100, "Error")

    def update_progress(self, value, status_text=None):
        """Update the progress bar and status text"""
        try:
            if self.progress_bar:
                self.progress_bar.setValue(value)
            if status_text and self.status_label:
                self.status_label.setText(status_text)
            QtWidgets.QApplication.processEvents()
        except Exception as e:
            self.log.error(f"Error updating progress: {str(e)}")

    def _ensure_unique_dest(self, dest_root, base_name):
        """
        Return a destination path under dest_root that doesn't collide.
        If 'dest_root/base_name' exists, returns '.../base_name_1', '.../base_name_2', etc.
        """
        candidate = os.path.join(dest_root, base_name)
        if not os.path.exists(candidate):
            return candidate
        idx = 1
        while True:
            candidate_i = os.path.join(dest_root, f"{base_name}_{idx}")
            if not os.path.exists(candidate_i):
                return candidate_i
            idx += 1

    def move_files(self):
        """Move the identified EXR sequence directories into a single flat destination folder."""
        try:
            if not self.paths_to_move:
                self.log_message("No folders to move. Run a scan first.")
                return

            # Ask for destination folder
            self.log_message("Prompting for destination folder...")
            dlg = QtWidgets.QFileDialog(self.dialog)
            dlg.setFileMode(QtWidgets.QFileDialog.Directory)
            dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
            dlg.setWindowTitle("Choose Destination Folder (EXR sequence folders will be placed here)")
            if hasattr(dlg, "exec"):
                accepted = dlg.exec()
            else:
                accepted = dlg.exec_()
            if not accepted:
                self.log_message("Move cancelled: no destination selected.")
                return

            dest_root = dlg.selectedFiles()[0]
            if not dest_root or not os.path.isdir(dest_root):
                self.log_message("Invalid destination selected.")
                nuke.message("Please select a valid destination folder.")
                return

            self.move_button.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            self.status_label.setText("Starting move...")
            self.status_label.setVisible(True)

            self.log_message(f"Moving {len(self.paths_to_move)} folders to: {dest_root}")
            self.moved_paths = []

            total = len(self.paths_to_move)
            for i, seq_dir in enumerate(self.paths_to_move, start=1):
                progress_value = int((i - 1) / total * 100)
                self.update_progress(progress_value, f"Moving folder {i} of {total}")

                if not os.path.exists(seq_dir):
                    self.log_message(f"Path not found (skipping): {seq_dir}")
                    continue

                base_name = os.path.basename(seq_dir.rstrip(os.sep))
                dest_path = self._ensure_unique_dest(dest_root, base_name)

                try:
                    self.log_message(f"Moving: {seq_dir}  ->  {dest_path}")
                    shutil.move(seq_dir, dest_path)
                    self.moved_paths.append(dest_path)
                except Exception as move_err:
                    self.log_message(f"Move failed for {seq_dir}: {move_err}")

            self.update_progress(100, "Move complete")
            self.log_message(f"Move complete. Moved {len(self.moved_paths)} of {len(self.paths_to_move)} folders.")
            self.move_button.setEnabled(True)

        except Exception as e:
            error_msg = f"Error during move: {str(e)}"
            self.log_message(error_msg)
            self.log_message(traceback.format_exc())
            nuke.message(error_msg)
            self.move_button.setEnabled(True)
            self.status_label.setText("Error during move")
            self.update_progress(100, "Error")

    def get_versions_for_cleanup(self, project):
        """Get all versions that aren't in excluded pipeline steps and have EXR frames"""
        try:
            filters = [
                ['project', 'is', project],
                ['sg_path_to_frames', 'is_not', None]  # Ensure path_to_frames exists
            ]

            fields = [
                'code',
                'sg_status_list',
                'entity',
                'sg_task',
                'sg_task.Task.step',
                'sg_path_to_frames',
                'created_at'
            ]

            versions = self.sg.find('Version', filters, fields, order=[{'field_name': 'created_at', 'direction': 'asc'}])
            self.log_message(f"Retrieved {len(versions)} total versions from ShotGrid")

            filtered_versions = []
            excluded_count = 0
            non_exr_count = 0

            for v in versions:
                version_code = v.get('code', 'Unknown')
                path = v.get('sg_path_to_frames', 'No path')

                if not path or not path.lower().endswith('.exr'):
                    non_exr_count += 1
                    continue

                if v.get('sg_task') and v.get('sg_task.Task.step'):
                    step = v['sg_task.Task.step']
                    step_name = step.get('name', 'Unknown')
                    if step_name in self.excluded_pipeline_steps:
                        self.log_message(f"Excluding version {version_code} due to pipeline step: {step_name}")
                        excluded_count += 1
                        continue

                # Extra safeguard: skip if path text contains excluded keywords
                skip_by_path = False
                for excluded_step in self.excluded_pipeline_steps:
                    if excluded_step.upper() in path.upper():
                        self.log_message(f"WARNING: Path suggests excluded step '{excluded_step}': {path}")
                        skip_by_path = True
                        break
                if skip_by_path:
                    excluded_count += 1
                    continue

                filtered_versions.append(v)

            self.log_message(f"Filter stats: {len(filtered_versions)} kept, {excluded_count} excluded by step/path, {non_exr_count} non-EXR")
            return filtered_versions

        except Exception as e:
            self.log_message(f"Error retrieving versions: {str(e)}")
            self.log_message(traceback.format_exc())
            return []

    def group_versions_by_shot(self, versions):
        """Group versions by their shot entity AND task"""
        task_versions = defaultdict(list)
        for version in versions:
            if version.get('entity') and version.get('sg_task'):
                key = f"{version['entity']['id']}_{version['sg_task']['id']}"
                task_versions[key].append(version)
        return task_versions

    def get_sequence_directory(self, frame_path):
        """Return the directory containing the frame sequence"""
        try:
            return os.path.dirname(frame_path)
        except Exception as e:
            self.log_message(f"Error getting sequence directory: {str(e)}")
            return frame_path

    def apply_cleanup_rules(self, task_versions):
        """
        Return a list of EXR sequence directories to move,
        applying the three rules on a per-(shot,task) basis.
        """
        paths_to_move = []
        missing_paths = 0

        try:
            for task_key, versions in task_versions.items():
                shot_id, task_id = task_key.split('_')

                shot_name = versions[0]['entity']['name'] if versions and versions[0].get('entity') else f"ID: {shot_id}"
                task_name = versions[0]['sg_task']['name'] if versions and versions[0].get('sg_task') else f"ID: {task_id}"
                self.log_message(f"\nProcessing Shot: {shot_name}, Task: {task_name}")

                # Ensure chronological order by created_at (already asc in query, but safeguard)
                versions_sorted = sorted(versions, key=lambda v: v.get('created_at'))

                # Rule 1: All EXR renders linked to versions with status "na"
                na_versions = [v for v in versions_sorted if v.get('sg_status_list') == 'na']
                for v in na_versions:
                    p = v.get('sg_path_to_frames')
                    if p:
                        seq_dir = self.get_sequence_directory(p)
                        if os.path.exists(seq_dir):
                            paths_to_move.append(seq_dir)
                            self.log_message(f"Rule 1 (na): {v.get('code')}  ->  {seq_dir}")
                        else:
                            missing_paths += 1

                # Rule 2: For status "innote" on shots with >1, keep newest; move older
                innote_versions = [v for v in versions_sorted if v.get('sg_status_list') == 'innote']
                if len(innote_versions) > 1:
                    older = innote_versions[:-1]  # keep the newest
                    for v in older:
                        p = v.get('sg_path_to_frames')
                        if p:
                            seq_dir = self.get_sequence_directory(p)
                            if os.path.exists(seq_dir):
                                paths_to_move.append(seq_dir)
                                self.log_message(f"Rule 2 (older innote): {v.get('code')}  ->  {seq_dir}")
                            else:
                                missing_paths += 1

                # Rule 3: For status "note" when >2 exist, keep 2 newest; move older
                note_versions = [v for v in versions_sorted if v.get('sg_status_list') == 'note']
                if len(note_versions) > 2:
                    older = note_versions[:-2]  # keep 2 newest
                    for v in older:
                        p = v.get('sg_path_to_frames')
                        if p:
                            seq_dir = self.get_sequence_directory(p)
                            if os.path.exists(seq_dir):
                                paths_to_move.append(seq_dir)
                                self.log_message(f"Rule 3 (older note): {v.get('code')}  ->  {seq_dir}")
                            else:
                                missing_paths += 1

            if missing_paths > 0:
                self.log_message(f"\nSkipped {missing_paths} paths that no longer exist on the file system")

            # De-duplicate while preserving order
            seen = set()
            deduped = []
            for p in paths_to_move:
                if p not in seen:
                    seen.add(p)
                    deduped.append(p)

            return deduped

        except Exception as e:
            self.log_message(f"Error applying cleanup rules: {str(e)}")
            self.log_message(traceback.format_exc())
            return paths_to_move

    def log_message(self, message):
        """Log a message to both the logger and the UI"""
        try:
            self.log.info(message)
            if self.results_text:
                self.results_text.append(message)
                cursor = self.results_text.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.results_text.setTextCursor(cursor)
                QtWidgets.QApplication.processEvents()
        except Exception as e:
            self.log.error(f"Error in log_message: {str(e)}")
            self.log.info(message)

def run_in_nuke():
    """Run the cleanup tool from Nuke with robust error handling"""
    try:
        log.info("Starting ShotGrid Render Cleanup (Move EXR Folders)")

        cleanup = RenderCleanup()

        try:
            project = cleanup.context.project
            cleanup.log.info(f"Running in project context: {project['name']} (ID: {project['id']})")
        except Exception as e:
            error_msg = f"Error getting project context: {str(e)}"
            log.error(error_msg)
            nuke.message(error_msg)
            return

        cleanup.show_dialog()

    except Exception as e:
        error_msg = f"Error initializing ShotGrid Render Cleanup: {str(e)}\n{traceback.format_exc()}"
        log.error(error_msg)
        nuke.message(error_msg)

if __name__ == "__main__":
    run_in_nuke()
