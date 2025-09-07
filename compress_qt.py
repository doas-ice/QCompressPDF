import sys
import os
import subprocess
from pathlib import Path
import tempfile
import shlex
import shutil
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QFileDialog,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QLineEdit,
    QInputDialog,
    QProgressDialog,
    QDialogButtonBox,
    QSpinBox,
    QSlider,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
import PyPDF2
import string
import re
import urllib.request
import json

PRESETS_DPI = {
    "300 DPI (Low Compression)": 300,
    "200 DPI (Medium)": 200,
    "150 DPI (High)": 150,
    "100 DPI (Ultra)": 100,
    "72 DPI (Extreme)": 72,
}


def get_gs_executable():
    if sys.platform.startswith("win"):
        for exe in ["gswin64c", "gswin32c", "gs"]:
            if any(
                os.access(os.path.join(path, exe + ".exe"), os.X_OK)
                for path in os.environ["PATH"].split(os.pathsep)
            ):
                return exe
        return "gswin64c"  # fallback
    else:
        return "gs"


GS_EXECUTABLE = get_gs_executable()


def get_file_size(path):
    size_bytes = os.path.getsize(path)
    size_kb = size_bytes / 1024
    size_mb = size_kb / 1024
    if size_mb >= 1:
        return f"{size_mb:.2f} MB"
    else:
        return f"{size_kb:.2f} KB"


def get_pdf_page_count(pdf_path):
    """Get the number of pages in a PDF file"""
    try:
        with open(pdf_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            return len(reader.pages)
    except Exception as e:
        print(f"Error getting page count: {e}")
        return 0


CURRENT_VERSION = "1.3.3"
GITHUB_REPO = "doas-ice/QCompressPDF"


def check_for_updates():
    """Check GitHub releases for newer version"""
    try:
        with urllib.request.urlopen(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                latest_version = data['tag_name'].lstrip('v').lstrip('V')
                if latest_version > CURRENT_VERSION:
                    return True, latest_version, data
        return False, None, None
    except Exception as e:
        print(f"Update check failed: {e}")
        return False, None, None


class UpdateDialog(QDialog):
    def __init__(self, new_version, release_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.new_version = new_version
        self.release_data = release_data
        self.download_url = None
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("A new version is available!"))
        layout.addWidget(QLabel(f"Current: {CURRENT_VERSION} → New: {new_version}"))

        if release_data and 'body' in release_data and release_data['body']:
            layout.addWidget(QLabel("Release notes:"))
            notes_text = QLabel(release_data['body'][:100] + "..." if len(release_data['body']) > 100 else release_data['body'])
            notes_text.setWordWrap(True)
            layout.addWidget(notes_text)

        # Find Windows installer download
        if release_data and 'assets' in release_data:
            for asset in release_data['assets']:
                if 'installer' in asset['name'].lower() or '/inno/' in asset['name'].lower() or '.exe' in asset['name'].lower():
                    self.download_url = asset['browser_download_url']
                    break

        button_box = QDialogButtonBox()
        if self.download_url:
            self.update_btn = QPushButton("Download && Install", self)
            self.update_btn.clicked.connect(self.download_and_install)
            button_box.addButton(self.update_btn, QDialogButtonBox.AcceptRole)
        self.skip_btn = QPushButton("Skip", self)
        self.skip_btn.clicked.connect(self.reject)
        button_box.addButton(self.skip_btn, QDialogButtonBox.RejectRole)

        layout.addWidget(button_box)
        self.setLayout(layout)

    def download_and_install(self):
        if not self.download_url:
            QMessageBox.critical(self, "Error", "Download URL not found")
            return

        try:
            temp_dir = tempfile.gettempdir()
            installer_path = os.path.join(temp_dir, f"QCompressPDF_{self.new_version}_installer.exe")

            # Download
            with urllib.request.urlopen(self.download_url) as response:
                with open(installer_path, 'wb') as f:
                    f.write(response.read())

            # Run installer
            subprocess.run([installer_path], check=True)

            # Close app after install
            QMessageBox.information(self, "Success", f"Updated to version {self.new_version}\nPlease restart the application.")
            self.accept()
            QApplication.instance().quit()

        except Exception as e:
            QMessageBox.critical(self, "Update Failed", f"Failed to download/install update: {e}")

    def get_result(self):
        return self.exec() == QDialog.Accepted


def show_update_if_available():
    """Check for updates and show dialog if available"""
    has_update, new_version, release_data = check_for_updates()
    if has_update:
        dialog = UpdateDialog(new_version, release_data)
        dialog.get_result()


class CompressThread(QThread):
    finished = Signal(bool, str)
    progress = Signal(int, int)  # current_page, total_pages

    def __init__(self, in_file, out_file, dpi):
        super().__init__()
        self.in_file = in_file
        self.out_file = out_file
        self.dpi = dpi
        self.total_pages = 0
        self.current_page = 0

    def run(self):
        temp_input = None
        process = None
        try:
            # Get total pages for progress tracking
            self.total_pages = get_pdf_page_count(self.in_file)
            if self.total_pages > 0:
                self.progress.emit(0, self.total_pages)
            
            # Always copy to a temp file with ASCII-only name
            temp_dir = tempfile.gettempdir()
            temp_input = os.path.join(
                temp_dir, f"pdfcompress_input_{os.getpid()}_{id(self)}.pdf"
            )
            shutil.copy2(self.in_file, temp_input)
            input_for_gs = temp_input
            
            # Set environment variable for unbuffered output
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            if sys.platform == "win32":
                # Force Ghostscript to output progress on Windows
                env["GSC_QUIET"] = "0"
                
            cmd_list = [
                GS_EXECUTABLE,
                "-dNOPAUSE",
                "-dBATCH",
                "-dSAFER",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                "-dPDFSETTINGS=/screen",
                f"-sOutputFile={self.out_file}",
                "-dDownsampleColorImages=true",
                f"-dColorImageResolution={self.dpi}",
                "-dColorImageDownsampleType=/Bicubic",
                "-dColorImageDownsampleThreshold=1.0",
            ]
            
            # Add verbose output for progress tracking
            if sys.platform == "win32":
                cmd_list.insert(-1, "-dDEBUG")  # Add debug output
            
            cmd_list.append(input_for_gs)
            
            kwargs = {
                'env': env,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.STDOUT,  # Redirect stderr to stdout
                'text': True,
                'bufsize': 0,  # Unbuffered
                'universal_newlines': True,
            }
            
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                
            print(f"Running command: {' '.join(cmd_list)}")
                
            # Run gs with real-time output capture
            process = subprocess.Popen(cmd_list, **kwargs)
            
            # Read output line by line in real-time
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    line = output.strip()
                    print(f"GS: {line}")  # Debug output
                    self.parse_progress_line(line)
                    
            # Wait for process to complete and get return code
            return_code = process.poll()
            print(f"Process returned with code: {return_code}")
            
            if return_code != 0:
                error_msg = f"Ghostscript failed with return code {return_code}"
                raise subprocess.CalledProcessError(return_code, cmd_list, error_msg)
            
            # Verify the output file exists and has size > 0
            if not os.path.exists(self.out_file):
                raise Exception(f"Output file was not created at: {self.out_file}")
            
            if os.path.getsize(self.out_file) == 0:
                raise Exception(f"Output file is empty: {self.out_file}")
            
            # Emit final progress
            if self.total_pages > 0:
                self.progress.emit(self.total_pages, self.total_pages)
            
            print("Compression completed successfully!")
            self.finished.emit(True, "")
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Process failed with code {e.returncode}:\n"
            error_msg += f"Command: {' '.join(e.cmd)}"
            print(f"Error occurred: {error_msg}")
            self.finished.emit(False, error_msg)
            
        except Exception as e:
            print(f"Exception occurred: {str(e)}")
            self.finished.emit(False, str(e))
            
        finally:
            # Clean up process resources
            if process:
                try:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)
                except Exception as e:
                    print(f"Error cleaning up process: {e}")
                    
            # Clean up temp file
            if temp_input and os.path.exists(temp_input):
                try:
                    os.remove(temp_input)
                except Exception as e:
                    print(f"Error removing temp file: {e}")

    def parse_progress_line(self, line):
        """Parse Ghostscript output for progress information"""
        try:
            # Look for various progress patterns that Ghostscript outputs
            patterns = [
                # Standard page processing patterns
                r"Processing pages \d+ through (\d+)",
                r"Page (\d+)",
                r"page (\d+)",
                # Debug output patterns
                r"%%Page:\s*(\d+)",
                r"showpage,\s*page\s+(\d+)",
                r".*page\s+(\d+)",
                # PDF processing patterns
                r".*Page\s+(\d+)\s+.*",
                r".*processing\s+page\s+(\d+)",
            ]
            
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    page_num = int(match.group(1))
                    if "through" in pattern.lower():
                        # This gives us total pages
                        if page_num > self.total_pages:
                            self.total_pages = page_num
                            self.progress.emit(0, self.total_pages)
                    else:
                        # This gives us current page
                        self.current_page = min(page_num, self.total_pages) if self.total_pages > 0 else page_num
                        if self.total_pages > 0:
                            self.progress.emit(self.current_page, self.total_pages)
                        print(f"Progress: Page {self.current_page} of {self.total_pages}")
                    return
                    
            # Look for other indicators of progress
            if any(keyword in line.lower() for keyword in ['processing', 'page', 'writing']):
                print(f"Potential progress line: {line}")
                
        except (ValueError, IndexError, AttributeError) as e:
            print(f"Error parsing line '{line}': {e}")


class DpiSelectorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select DPI for Compression")
        self.setMinimumWidth(350)
        layout = QVBoxLayout(self)
        self.selected_dpi = 300  # Default

        # DPI input box
        dpi_input_layout = QHBoxLayout()
        dpi_input_layout.addWidget(QLabel("DPI:"))
        self.dpi_edit = QLineEdit("300", self)
        self.dpi_edit.setMaxLength(4)
        self.dpi_edit.textChanged.connect(self.update_from_input)
        dpi_input_layout.addWidget(self.dpi_edit)
        layout.addLayout(dpi_input_layout)

        # Preset buttons
        presets_layout = QVBoxLayout()
        for preset_name, dpi_value in PRESETS_DPI.items():
            btn = QPushButton(preset_name, self)
            btn.clicked.connect(lambda checked, d=dpi_value: self.set_dpi(d))
            presets_layout.addWidget(btn)
        layout.addLayout(presets_layout)

        # Slider
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("10"))
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(10, 600)
        self.slider.setValue(300)
        self.slider.setTickInterval(50)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.valueChanged.connect(self.update_from_slider)
        slider_layout.addWidget(self.slider)
        slider_layout.addWidget(QLabel("600"))
        layout.addLayout(slider_layout)

        # Current DPI display
        self.dpi_label = QLabel("Selected DPI: 300")
        layout.addWidget(self.dpi_label)

        # OK/Cancel buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def set_dpi(self, dpi):
        self.selected_dpi = dpi
        self.dpi_edit.setText(str(dpi))
        self.slider.setValue(dpi)
        self.update_dpi_label()

    def update_from_input(self):
        try:
            dpi = int(self.dpi_edit.text())
            if 10 <= dpi <= 600:
                self.selected_dpi = dpi
                self.slider.setValue(dpi)
                self.update_dpi_label()
            else:
                self.dpi_edit.setText(str(self.selected_dpi))  # Revert to last valid
        except ValueError:
            pass

    def update_from_slider(self, value):
        self.selected_dpi = value
        self.dpi_edit.setText(str(value))
        self.update_dpi_label()

    def update_dpi_label(self):
        self.dpi_label.setText(f"Selected DPI: {self.selected_dpi}")

    def get_dpi(self):
        if self.exec() == QDialog.Accepted:
            return self.selected_dpi
        return None


class ManualSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Compression Settings")
        self.setMinimumWidth(250)
        layout = QVBoxLayout(self)
        dpi_layout = QHBoxLayout()
        dpi_label = QLabel("DPI:", self)
        self.dpi_spin = QSpinBox(self)
        self.dpi_spin.setRange(10, 600)
        self.dpi_spin.setValue(150)
        dpi_layout.addWidget(dpi_label)
        dpi_layout.addWidget(self.dpi_spin)
        layout.addLayout(dpi_layout)
        quality_layout = QHBoxLayout()
        quality_label = QLabel("Quality:", self)
        self.quality_spin = QSpinBox(self)
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(50)
        quality_layout.addWidget(quality_label)
        quality_layout.addWidget(self.quality_spin)
        layout.addLayout(quality_layout)
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_values(self):
        if self.exec() == QDialog.Accepted:
            return self.dpi_spin.value(), self.quality_spin.value()
        return None, None


def manual_settings(parent=None):
    dlg = ManualSettingsDialog(parent)
    return dlg.get_values()


class PreviewDialog(QDialog):
    def __init__(
        self, original, temp_compressed, dpi, quality, default_output, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Preview Compression")
        self.setMinimumWidth(420)
        self.accepted_result = False
        self.output_file = default_output
        self.temp_compressed = temp_compressed
        orig_bytes = os.path.getsize(original)
        comp_bytes = os.path.getsize(temp_compressed)
        orig_size = get_file_size(original)
        comp_size = get_file_size(temp_compressed)
        reduction = (1 - comp_bytes / orig_bytes) * 100 if orig_bytes else 0
        layout = QVBoxLayout(self)
        info = QLabel(
            f"DPI: {dpi}\nQuality: {quality}\n\n"
            f"Original size: {orig_size}\n"
            f"Compressed size: {comp_size}\n"
            f"Reduction: {reduction:.2f}%\n\n"
            f"Preview the PDF and then click Accept to save, or Retry to try different settings."
        )
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(info)
        layout.addWidget(QLabel("Output filename:"))
        self.filename_edit = QLineEdit(default_output, self)
        layout.addWidget(self.filename_edit)
        btn_layout = QHBoxLayout()
        preview_btn = QPushButton("Preview PDF", self)
        preview_btn.clicked.connect(self.preview_pdf)
        btn_layout.addWidget(preview_btn)
        split_btn = QPushButton("Split into 2 PDFs", self)
        split_btn.clicked.connect(self.split_pdf)
        btn_layout.addWidget(split_btn)
        accept_btn = QPushButton("Accept && Save", self)
        accept_btn.clicked.connect(self.accept_dialog)
        btn_layout.addWidget(accept_btn)
        retry_btn = QPushButton("Retry with other Settings", self)
        retry_btn.clicked.connect(self.reject)
        btn_layout.addWidget(retry_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def preview_pdf(self):
        path = self.temp_compressed  # Always preview the temp file
        # Ensure path is a string (Unicode-safe)
        path = os.fsdecode(path) if isinstance(path, bytes) else path
        try:
            if sys.platform.startswith("darwin"):
                subprocess.run(["open", path], check=True)
            elif os.name == "nt":
                os.startfile(path)
            elif os.name == "posix":
                subprocess.run(["xdg-open", path], check=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not preview file: {e}")

    def split_pdf(self):
        """Split PDF based on file size, ensuring each part is under 5MB"""
        base_output = self.filename_edit.text()
        base, ext = os.path.splitext(base_output)

        try:
            total_size = os.path.getsize(self.temp_compressed) / 1024 / 1024  # Size in MB

            if total_size <= 5:
                # File is already small enough
                resp = QMessageBox.question(
                    self,
                    "File Size OK",
                    f"The file is only {total_size:.1f} MB. Do you still want to split it into smaller parts?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if resp == QMessageBox.No:
                    return

            # Read the PDF
            with open(self.temp_compressed, "rb") as infile:
                reader = PyPDF2.PdfReader(infile)
                total_pages = len(reader.pages)

                if total_pages < 2:
                    QMessageBox.warning(
                        self, "Split PDF", "PDF has less than 2 pages, cannot split."
                    )
                    return

                # Estimate split points to keep parts under 5MB
                split_files = []
                current_part = 0

                while current_part < total_pages:
                    part_writer = PyPDF2.PdfWriter()
                    part_size = 0
                    page_count = 0

                    # Add pages until we approach 5MB or cover all remaining pages
                    while current_part < total_pages and (part_size / 1024 / 1024 < 4.5 or page_count == 0):
                        part_writer.add_page(reader.pages[current_part])
                        current_part += 1
                        page_count += 1

                    # Create temp file to check actual size
                    temp_part_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                    part_writer.write(temp_part_file)
                    temp_part_file.close()

                    actual_size = os.path.getsize(temp_part_file.name) / 1024 / 1024

                    if actual_size > 5 and page_count > 1:
                        # Remove last page and retry with fewer pages
                        part_writer = PyPDF2.PdfWriter()
                        current_part -= 1
                        for i in range(current_part - page_count + 1, current_part):
                            part_writer.add_page(reader.pages[i])
                        current_part = current_part - page_count + 1  # Reset to try again
                        temp_part_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                        part_writer.write(temp_part_file)
                        temp_part_file.close()

                    # Generate output filename
                    part_num = len(split_files) + 1
                    output_file = f"{base}_{part_num}{ext}"

                    # Check if output file exists
                    while os.path.exists(output_file):
                        resp = QMessageBox.question(
                            self,
                            "File Exists",
                            f"The file '{output_file}' already exists. Overwrite?",
                            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                        )
                        if resp == QMessageBox.Yes:
                            break
                        elif resp == QMessageBox.No:
                            # Prompt for new filename
                            new_file, ok = QFileDialog.getSaveFileName(
                                self, "Save Split PDF As", output_file, "PDF files (*.pdf)"
                            )
                            if ok and new_file:
                                output_file = new_file
                            else:
                                continue
                        else:
                            # Cancel
                            temp_part_file.close()
                            os.unlink(temp_part_file.name)
                            return

                    # Move temp file to final location
                    shutil.move(temp_part_file.name, output_file)
                    split_files.append(output_file)

                # Show results
                size_info = "\n".join(
                    f"{f}: {os.path.getsize(f) / 1024 / 1024:.1f} MB"
                    for f in split_files
                )

                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("PDF Split Complete")
                msg_box.setText(
                    f"PDF split into {len(split_files)} parts:\n\n{size_info}\n\nWhat would you like to do next?"
                )
                quit_btn = msg_box.addButton("Quit Program", QMessageBox.DestructiveRole)
                continue_btn = msg_box.addButton(
                    "Continue Compression (return to previous window)",
                    QMessageBox.AcceptRole,
                )
                msg_box.setDefaultButton(continue_btn)
                msg_box.exec()
                if msg_box.clickedButton() == quit_btn:
                    self.close()
                    QApplication.instance().quit()
                # else: just return to the preview dialog

        except Exception as e:
            QMessageBox.critical(self, "Split PDF Error", f"Failed to split PDF:\n{e}")

    def accept_dialog(self):
        self.accepted_result = True
        self.output_file = self.filename_edit.text()
        self.accept()

    def get_result(self):
        if self.exec() == QDialog.Accepted and self.accepted_result:
            return True, self.output_file
        return False, self.output_file


def show_loading_dialog(parent, text="Compressing PDF..."):
    dlg = QProgressDialog(text, None, 0, 100, parent)
    dlg.setWindowTitle("Compressing PDF")
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setCancelButton(None)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)  # Prevent auto-closing
    dlg.setAutoReset(False)  # Prevent auto-resetting
    dlg.setValue(0)
    # Center the dialog on the screen
    screen = QApplication.primaryScreen()
    screen_geometry = screen.availableGeometry()
    dlg_geometry = dlg.frameGeometry()
    x = screen_geometry.center().x() - dlg_geometry.width() // 2
    y = screen_geometry.center().y() - dlg_geometry.height() // 2
    dlg.move(x, y)
    return dlg


def main():
    app = QApplication(sys.argv)
    # Check for updates on startup
    show_update_if_available()
    # File selection
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file, _ = QFileDialog.getOpenFileName(
            None, "Select PDF File", "", "PDF files (*.pdf)"
        )
    if not input_file:
        return
    # DPI selection
    dpi_dialog = DpiSelectorDialog()
    dpi = dpi_dialog.get_dpi()
    if dpi is None:
        return
    quality = 85  # Dummy value for compatibility
    # Use temp file for output
    temp_dir = tempfile.gettempdir()
    temp_output_file = os.path.join(temp_dir, f"pdfcompress_{os.getpid()}.pdf")
    # Show loading dialog and compress in background
    loading = show_loading_dialog(None)
    thread = CompressThread(input_file, temp_output_file, dpi)
    result = {"success": False, "error": ""}

    def on_finished(success, error):
        result["success"] = success
        result["error"] = error
        loading.close()

    def on_progress(current, total):
        if total > 0:
            percent = min(100, (current * 100) // total)
            loading.setLabelText(f"Compressing PDF...\nPage {current} of {total}")
            loading.setValue(percent)
            # Force the dialog to repaint and process events
            QApplication.processEvents()
            # On Windows, we need to ensure the progress bar updates immediately
            if sys.platform == "win32":
                loading.repaint()

    thread.finished.connect(on_finished)
    thread.progress.connect(on_progress)
    thread.start()
    loading.exec()
    thread.wait()
    if not result["success"]:
        QMessageBox.critical(None, "Error", f"Compression failed:\n{result['error']}")
        if os.path.exists(temp_output_file):
            os.remove(temp_output_file)
        return
    # Preview dialog
    default_output_file = str(
        Path(input_file).with_name(Path(input_file).stem + f"_compressed.pdf")
    )
    while True:
        preview_dialog = PreviewDialog(
            input_file, temp_output_file, dpi, quality, default_output_file
        )
        accepted, final_output_file = preview_dialog.get_result()
        if accepted:
            # Check if output file exists and prompt user
            while os.path.exists(final_output_file):
                resp = QMessageBox.question(
                    None,
                    "File Exists",
                    f"The file '{final_output_file}' already exists. Overwrite?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                )
                if resp == QMessageBox.Yes:
                    break
                elif resp == QMessageBox.No:
                    # Prompt for new filename
                    new_file, ok = QFileDialog.getSaveFileName(
                        None,
                        "Save Compressed PDF As",
                        final_output_file,
                        "PDF files (*.pdf)",
                    )
                    if ok and new_file:
                        final_output_file = new_file
                    else:
                        continue
                else:
                    # Cancel
                    if os.path.exists(temp_output_file):
                        os.remove(temp_output_file)
                    return
            try:
                shutil.move(temp_output_file, final_output_file)
            except Exception as e:
                QMessageBox.critical(
                    None, "Error", f"Could not save as new filename: {e}"
                )
                continue
            QMessageBox.information(
                None, "Success", f"Compressed PDF saved as:\n{final_output_file}"
            )
            break
        else:
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)
            retry = QMessageBox.question(
                None,
                "Retry",
                "Do you want to retry with different settings?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if retry == QMessageBox.Yes:
                # Re-run DPI selection
                dpi_dialog = DpiSelectorDialog()
                new_dpi = dpi_dialog.get_dpi()
                if new_dpi is None:
                    break
                dpi = new_dpi
                # Re-compress to temp file
                loading = show_loading_dialog(None)
                thread = CompressThread(input_file, temp_output_file, dpi)
                result = {"success": False, "error": ""}
                
                def on_finished_retry(success, error):
                    result["success"] = success
                    result["error"] = error
                    loading.close()

                def on_progress_retry(current, total):
                    if total > 0:
                        percent = min(100, (current * 100) // total)
                        loading.setLabelText(f"Compressing PDF...\nPage {current} of {total}")
                        loading.setValue(percent)
                        # Force the dialog to repaint and process events
                        QApplication.processEvents()
                        # On Windows, we need to ensure the progress bar updates immediately
                        if sys.platform == "win32":
                            loading.repaint()
                
                thread.finished.connect(on_finished_retry)
                thread.progress.connect(on_progress_retry)
                thread.start()
                loading.exec()
                thread.wait()
                if not result["success"]:
                    QMessageBox.critical(
                        None, "Error", f"Compression failed:\n{result['error']}"
                    )
                    if os.path.exists(temp_output_file):
                        os.remove(temp_output_file)
                    break
                continue
            else:
                break


if __name__ == "__main__":
    main()
