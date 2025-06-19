# ShotGrid Render Cleanup Script
# This script identifies and deletes EXR render files based on specific rules:
# 1. All EXR renders linked to versions with status "na"
# 2. All older EXR renders linked to versions with status "bkdn" on shots with multiple "bkdn" versions, except the newest version
# 3. All older EXR renders linked to versions with status "note" on shots with more than 2 "note" versions, except the 2 latest versions

import os
import sys
import shutil
import traceback
from collections import defaultdict
import logging

# Get the current Nuke instance
import nuke

# Import Qt modules at the top level
try:
    from PySide2 import QtWidgets, QtCore, QtGui
except ImportError:
    try:
        from PySide import QtGui, QtCore
        QtWidgets = QtGui
    except ImportError:
        # Final fallback to sgtk's Qt imports
        from sgtk.platform.qt import QtGui, QtCore
        QtWidgets = QtGui

# Initialize empty variables to avoid reference errors
sg = None
engine = None
context = None

def setup_logger():
    """Set up a basic logger"""
    log = logging.getLogger("sg_render_cleanup")
    log.setLevel(logging.INFO)

    # Check if the logger already has handlers to avoid duplicates
    if not log.handlers:
        # Create console handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        log.addHandler(handler)

    return log

log = setup_logger()

class RenderCleanup(object):
    def __init__(self):
        # Initialize UI components as None
        self.dialog = None
        self.results_text = None
        self.dry_run_checkbox = None
        self.progress_bar = None
        self.status_label = None
        self.scan_button = None
        self.delete_button = None

        # Initialize data variables
        self.deleted_frames = []
        self.frames_to_delete = []
        self.dry_run = True

        # Import ShotGrid API with proper error handling
        try:
            # Try to get the current ShotGrid engine and context
            import sgtk
            self.engine = sgtk.platform.current_engine()
            if not self.engine:
                raise ImportError("No ShotGrid engine found. Are you running this from within ShotGrid?")

            self.context = self.engine.context
            if not self.context:
                raise ImportError("No ShotGrid context found. Are you in a valid ShotGrid context?")

            # Get the ShotGrid instance
            self.sg = self.context.sgtk.shotgun
            if not self.sg:
                raise ImportError("Could not connect to ShotGrid")

            # Log successful initialization
            self.log = log
            self.log.info(f"Successfully initialized ShotGrid connection")

            # Define excluded pipeline steps
            self.excluded_pipeline_steps = ["Roto", "Paint", "Prep", "Ingest", "v000"]

        except ImportError as e:
            error_message = f"Could not import ShotGrid Toolkit: {str(e)}"
            nuke.message(error_message)
            log.error(error_message)
            raise

    def show_dialog(self):
        """Display the cleanup dialog with proper error handling"""
        try:
            # Create dialog if it doesn't exist
            if not self.dialog:
                self.dialog = QtWidgets.QDialog()
                self.dialog.setWindowTitle("ShotGrid Render Cleanup")
                self.dialog.setMinimumWidth(500)
                self.dialog.setMinimumHeight(400)

                # Use a QVBoxLayout for the main layout
                layout = QtWidgets.QVBoxLayout()
                self.dialog.setLayout(layout)

                # Info label
                info_label = QtWidgets.QLabel(
                    "This tool will identify and delete EXR render files based on the following rules:"
                    "<ul>"
                    "<li>All EXR renders linked to versions with status 'na'</li>"
                    "<li>All older EXR renders linked to versions with status 'bkdn' on shots with multiple 'bkdn' versions, except the newest version</li>"
                    "<li>All older EXR renders linked to versions with status 'note' on shots with more than 2 'note' versions, except the 2 latest versions</li>"
                    "</ul>"
                    "This will only apply to internal artist renders (excluding 'Paint, 'Roto', 'Prep', 'Ingest', and 'v000' pipeline steps)."
                )
                info_label.setWordWrap(True)
                layout.addWidget(info_label)

                # Dry run checkbox
                self.dry_run_checkbox = QtWidgets.QCheckBox("Dry run (preview only, don't delete files)")
                self.dry_run_checkbox.setChecked(True)
                layout.addWidget(self.dry_run_checkbox)

                # Progress bar
                self.progress_bar = QtWidgets.QProgressBar()
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setVisible(False)
                layout.addWidget(self.progress_bar)

                # Status label
                self.status_label = QtWidgets.QLabel("")
                self.status_label.setVisible(False)
                layout.addWidget(self.status_label)

                # Results text area
                self.results_text = QtWidgets.QTextEdit()
                self.results_text.setReadOnly(True)
                layout.addWidget(self.results_text)

                # Buttons
                button_layout = QtWidgets.QHBoxLayout()

                self.scan_button = QtWidgets.QPushButton("Scan")
                self.scan_button.clicked.connect(self.run_scan)
                button_layout.addWidget(self.scan_button)

                self.delete_button = QtWidgets.QPushButton("Delete Files")
                self.delete_button.clicked.connect(self.delete_files)
                button_layout.addWidget(self.delete_button)

                close_button = QtWidgets.QPushButton("Close")
                close_button.clicked.connect(self.dialog.close)
                button_layout.addWidget(close_button)

                layout.addLayout(button_layout)

            # Log before showing dialog
            self.log.info("About to show dialog")

            # Show the dialog and make it stay open with exec_()
            self.dialog.exec_()

        except Exception as e:
            error_msg = f"Error creating dialog: {str(e)}\n{traceback.format_exc()}"
            self.log.error(error_msg)
            nuke.message(error_msg)

    def run_scan(self):
        """Run the scan to identify files to delete"""
        try:
            # Disable scan button during execution
            self.scan_button.setEnabled(False)

            # Show progress bar and reset it
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            self.status_label.setText("Starting scan...")
            self.status_label.setVisible(True)

            # Process UI events to update display
            QtWidgets.QApplication.processEvents()

            self.dry_run = self.dry_run_checkbox.isChecked()

            # Clear the results text
            if self.results_text:
                self.results_text.clear()

            self.log_message("Starting scan...")

            # Get current project
            project = self.context.project
            if not project:
                self.log_message("Error: No project found in context")
                return

            # Update progress
            self.update_progress(10, "Fetching versions...")

            # Get versions from this project
            self.log_message(f"Fetching versions for project: {project['name']}")

            # Step 1: Get all versions that aren't in excluded pipeline steps
            all_versions = self.get_versions_for_cleanup(project)
            self.log_message(f"Found {len(all_versions)} versions to analyze")

            # Update progress
            self.update_progress(40, "Grouping versions by shot...")

            # Step 2: Group versions by shot
            task_versions = self.group_versions_by_shot(all_versions)

            # Update progress
            self.update_progress(60, "Applying cleanup rules...")

            # Step 3: Apply cleanup rules
            self.frames_to_delete = self.apply_cleanup_rules(task_versions)

            # Update progress
            self.update_progress(90, "Finalizing results...")

            # Calculate total size to be deleted (approximately)
            total_size_bytes = 0
            for frame_path in self.frames_to_delete:
                if os.path.exists(frame_path):
                    if os.path.isdir(frame_path):
                        # For directories, calculate size of all contents
                        for dirpath, dirnames, filenames in os.walk(frame_path):
                            for f in filenames:
                                fp = os.path.join(dirpath, f)
                                if os.path.exists(fp):
                                    total_size_bytes += os.path.getsize(fp)
                    else:
                        # For files, get the direct size
                        total_size_bytes += os.path.getsize(frame_path)

            # Convert bytes to more readable format
            if total_size_bytes > 1099511627776:  # 1 TB
                size_str = f"{total_size_bytes / 1099511627776:.2f} TB"
            elif total_size_bytes > 1073741824:  # 1 GB
                size_str = f"{total_size_bytes / 1073741824:.2f} GB"
            elif total_size_bytes > 1048576:  # 1 MB
                size_str = f"{total_size_bytes / 1048576:.2f} MB"
            elif total_size_bytes > 1024:  # 1 KB
                size_str = f"{total_size_bytes / 1024:.2f} KB"
            else:
                size_str = f"{total_size_bytes} bytes"

            # Display individual paths first
            if self.frames_to_delete:
                self.log_message("Paths that will be deleted:")
                for frame_path in self.frames_to_delete:
                    self.log_message(f"Will delete: {frame_path}")
            else:
                self.log_message("No paths found to delete.")

            # Now display the summary
            self.log_message("\n" + "="*50)
            self.log_message(f"SCAN SUMMARY:")
            self.log_message(f"Total deletable paths: {len(self.frames_to_delete)}")
            self.log_message(f"Approximate total size: {size_str}")
            self.log_message("="*50)

            if self.dry_run:
                self.log_message("\nDRY RUN COMPLETE - No files were deleted")
                self.log_message("Uncheck 'Dry run' and click 'Delete Files' to perform actual deletion")

            # Scan complete
            self.update_progress(100, "Scan complete")

            # Re-enable scan button
            self.scan_button.setEnabled(True)

        except Exception as e:
            error_msg = f"Error during scan: {str(e)}"
            self.log_message(error_msg)
            self.log_message(traceback.format_exc())
            nuke.message(error_msg)

            # Re-enable scan button and hide progress
            self.scan_button.setEnabled(True)
            self.status_label.setText("Error during scan")
            self.update_progress(100, "Error")

    def update_progress(self, value, status_text=None):
        """Update the progress bar and status text"""
        try:
            if hasattr(self, 'progress_bar') and self.progress_bar:
                self.progress_bar.setValue(value)

            if status_text and hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(status_text)

            # Process UI events to update the display
            QtWidgets.QApplication.processEvents()

        except Exception as e:
            # Just log the error but don't interrupt the process
            self.log.error(f"Error updating progress: {str(e)}")

    def delete_files(self):
        """Delete the identified files"""
        try:
            if not self.frames_to_delete:
                self.log_message("No files to delete. Run scan first.")
                return

            if self.dry_run:
                self.log_message("Dry run is enabled. Uncheck 'Dry run' to delete files.")
                return

            # Disable delete button and show progress
            self.delete_button.setEnabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            self.status_label.setText("Starting deletion...")
            self.status_label.setVisible(True)

            self.log_message("Starting file deletion...")
            self.deleted_frames = []

            total_files = len(self.frames_to_delete)
            for i, frame_path in enumerate(self.frames_to_delete):
                # Update progress periodically
                progress_value = int((i / total_files) * 100)
                self.update_progress(progress_value, f"Deleting file {i+1} of {total_files}")

                if os.path.exists(frame_path):
                    # Check if it's a directory or a file
                    if os.path.isdir(frame_path):
                        self.log_message(f"Deleting directory: {frame_path}")
                        shutil.rmtree(frame_path)
                    else:
                        self.log_message(f"Deleting file: {frame_path}")
                        os.remove(frame_path)

                    self.deleted_frames.append(frame_path)
                else:
                    self.log_message(f"Path not found: {frame_path}")

            # Update progress to 100% when complete
            self.update_progress(100, "Deletion complete")

            self.log_message(f"Deletion complete. Deleted {len(self.deleted_frames)} out of {len(self.frames_to_delete)} frame sequences.")

            # Re-enable the delete button
            self.delete_button.setEnabled(True)

        except Exception as e:
            error_msg = f"Error during deletion: {str(e)}"
            self.log_message(error_msg)
            self.log_message(traceback.format_exc())
            nuke.message(error_msg)

            # Re-enable delete button and update status
            self.delete_button.setEnabled(True)
            self.status_label.setText("Error during deletion")
            self.update_progress(100, "Error")

    def get_versions_for_cleanup(self, project):
        """Get all versions that aren't in excluded pipeline steps"""
        try:
            # First get all versions with EXR paths in this project
            # Don't filter by pipeline step yet as that's causing the error
            filters = [
                ['project', 'is', project],
                ['sg_path_to_frames', 'is_not', None]  # Ensure path_to_frames exists
            ]

            fields = [
                'code',
                'sg_status_list',
                'entity',
                'sg_task',
                'sg_task.Task.step',  # Get the step entity
                'sg_path_to_frames',
                'created_at'
            ]

            versions = self.sg.find('Version', filters, fields, order=[{'field_name': 'created_at', 'direction': 'asc'}])
            self.log_message(f"Retrieved {len(versions)} total versions from ShotGrid")

            # Only keep versions with path_to_frames that ends with .exr
            # and also filter out versions with excluded pipeline steps
            filtered_versions = []
            excluded_count = 0
            non_exr_count = 0

            for v in versions:
                # Log verbose details about each version for debugging
                version_code = v.get('code', 'Unknown')
                path = v.get('sg_path_to_frames', 'No path')

                # Check if it's an EXR file
                if not path or not path.lower().endswith('.exr'):
                    non_exr_count += 1
                    continue

                # Check if this version has a task with a step
                step_info = "No step info"
                if v.get('sg_task.Task.step'):
                    step = v['sg_task.Task.step']
                    step_name = step.get('name', 'Unknown')
                    step_info = f"Step: {step_name}"

                    # If the step name is in the excluded list, skip this version
                    if step_name in self.excluded_pipeline_steps:
                        self.log_message(f"Excluding version {version_code} due to pipeline step: {step_name}")
                        excluded_count += 1
                        continue

                # Special case: check if path contains any of the excluded steps
                # This is a fallback for cases where the step info might be missing
                path_contains_excluded = False
                for excluded_step in self.excluded_pipeline_steps:
                    if excluded_step.upper() in path.upper():
                        self.log_message(f"WARNING: Path contains excluded step '{excluded_step}' but wasn't caught by step filter: {path}")
                        path_contains_excluded = True
                        break

                # Keep this version if it passed all filters
                if not path_contains_excluded:
                    filtered_versions.append(v)
                else:
                    excluded_count += 1

            # Log filter statistics
            self.log_message(f"Filter stats: {len(filtered_versions)} kept, {excluded_count} excluded by step, {non_exr_count} non-EXR")

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
                # Create a unique key combining entity ID and task ID
                key = f"{version['entity']['id']}_{version['sg_task']['id']}"
                task_versions[key].append(version)

        return task_versions

    def get_sequence_directory(self, frame_path):
        """Get just the immediate directory containing the EXR sequence

        Example:
        Input: C:/PROJECTS/Film/HAL/SUITE/2_WORK/1_SEQUENCES/042/HAL_042_1020/COMP/publish/renders/HAL_042_1020_comp_v001/4448x3096/HAL_042_1020_comp_v001.%04d.exr
        Output: C:/PROJECTS/Film/HAL/SUITE/2_WORK/1_SEQUENCES/042/HAL_042_1020/COMP/publish/renders/HAL_042_1020_comp_v001/4448x3096
        """
        # Simply return the directory containing the frame sequence
        try:
            return os.path.dirname(frame_path)
        except Exception as e:
            self.log_message(f"Error getting sequence directory: {str(e)}")
            return frame_path

    def apply_cleanup_rules(self, task_versions):
        """Apply the cleanup rules to identify frames to delete"""
        frames_to_delete = []
        missing_paths = 0

        try:
            # Process each shot+task combination
            for task_key, versions in task_versions.items():
                # Extract shot_id and task_id from the key
                shot_id, task_id = task_key.split('_')

                # Get shot and task names
                shot_name = versions[0]['entity']['name'] if versions and versions[0].get('entity') else f"ID: {shot_id}"
                task_name = versions[0]['sg_task']['name'] if versions and versions[0].get('sg_task') else f"ID: {task_id}"
                self.log_message(f"\nProcessing Shot: {shot_name}, Task: {task_name}")

                # Rule 1: All EXR renders linked to versions with status "na"
                na_versions = [v for v in versions if v['sg_status_list'] == 'na']
                for v in na_versions:
                    if v.get('sg_path_to_frames'):
                        # Get the directory containing the frame sequence
                        seq_dir = self.get_sequence_directory(v['sg_path_to_frames'])

                        # Only add to delete list if the path exists
                        if os.path.exists(seq_dir):
                            frames_to_delete.append(seq_dir)
                            self.log_message(f"Rule 1 (na status): {v['code']} - {seq_dir}")
                        else:
                            missing_paths += 1

                # Rule 2: Delete all older EXR renders linked to versions with status "bkdn" on shots with more than 1 "bkdn" version,
                # except the newest "bkdn" version
                bkdn_versions = [v for v in versions if v['sg_status_list'] == 'bkdn']
                if len(bkdn_versions) > 1:
                    # Keep only the newest bkdn version (last in the list since sorted by created_at)
                    versions_to_delete = bkdn_versions[:-1]  # All except the last one
                    for v in versions_to_delete:
                        if v.get('sg_path_to_frames'):
                            # Get the directory containing the frame sequence
                            seq_dir = self.get_sequence_directory(v['sg_path_to_frames'])

                            # Only add to delete list if the path exists
                            if os.path.exists(seq_dir):
                                frames_to_delete.append(seq_dir)
                                self.log_message(f"Rule 2 (older bkdn): {v['code']} - {seq_dir}")
                            else:
                                missing_paths += 1

                # Rule 3: Delete all older EXR renders linked to versions with status "note" on shots with more than 2 "note" versions,
                # except the 2 latest "note" versions
                note_versions = [v for v in versions if v['sg_status_list'] == 'note']
                if len(note_versions) > 2:
                    # Keep only the 2 newest note versions (last 2 in the list since sorted by created_at)
                    versions_to_delete = note_versions[:-2]  # All except the last two
                    for v in versions_to_delete:
                        if v.get('sg_path_to_frames'):
                            # Get the directory containing the frame sequence
                            seq_dir = self.get_sequence_directory(v['sg_path_to_frames'])

                            # Only add to delete list if the path exists
                            if os.path.exists(seq_dir):
                                frames_to_delete.append(seq_dir)
                                self.log_message(f"Rule 3 (older note): {v['code']} - {seq_dir}")
                            else:
                                missing_paths += 1

            # Log how many paths were skipped because they don't exist
            if missing_paths > 0:
                self.log_message(f"\nSkipped {missing_paths} paths that no longer exist on the file system")

            return frames_to_delete

        except Exception as e:
            self.log_message(f"Error applying cleanup rules: {str(e)}")
            self.log_message(traceback.format_exc())
            return frames_to_delete

    def log_message(self, message):
        """Log a message to both the logger and the UI"""
        try:
            # Log to system logger
            self.log.info(message)

            # Log to UI if available
            if hasattr(self, 'results_text') and self.results_text:
                self.results_text.append(message)

                # Scroll to bottom
                cursor = self.results_text.textCursor()
                cursor.movePosition(QtCore.QTextCursor.End)
                self.results_text.setTextCursor(cursor)

                # Process UI events to update the text display
                QtWidgets.QApplication.processEvents()

        except Exception as e:
            # Fall back to plain logging if UI fails
            self.log.error(f"Error in log_message: {str(e)}")
            self.log.info(message)

def run_in_nuke():
    """Run the cleanup tool from Nuke with robust error handling"""
    try:
        # First log that we're starting
        log.info("Starting ShotGrid Render Cleanup tool")

        # Create the cleanup instance
        cleanup = RenderCleanup()

        # Log the current context
        try:
            project = cleanup.context.project
            cleanup.log.info(f"Running in project context: {project['name']} (ID: {project['id']})")
        except Exception as e:
            error_msg = f"Error getting project context: {str(e)}"
            log.error(error_msg)
            nuke.message(error_msg)
            return

        # Show the dialog using exec_() to keep it open
        cleanup.show_dialog()

    except Exception as e:
        error_msg = f"Error initializing ShotGrid Render Cleanup: {str(e)}\n{traceback.format_exc()}"
        log.error(error_msg)
        nuke.message(error_msg)

# Run the script
if __name__ == "__main__":
    run_in_nuke()
