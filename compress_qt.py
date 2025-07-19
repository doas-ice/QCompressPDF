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
)
from PySide6.QtCore import Qt, QThread, Signal
import PyPDF2
import string
import re

PRESETS = {
    "Low Compression, Highest Quality (300dpi, Q85)": {"dpi": 300, "quality": 85},
    "Medium Compression, High Quality (200dpi, Q70)": {"dpi": 200, "quality": 70},
    "High Compression, Medium Quality (150dpi, Q50)": {"dpi": 150, "quality": 50},
    "Ultra Compression, Low Quality (100dpi, Q40)": {"dpi": 100, "quality": 40},
    "Extreme Compression, Low Quality (72dpi, Q30)": {"dpi": 72, "quality": 30},
    "Excessive Compression, Lower Quality (60dpi, Q20)": {"dpi": 60, "quality": 20},
    "Radical Compression, Potato Quality (45dpi, Q15)": {"dpi": 45, "quality": 15},
    "Manual DPI && Image Quality Selection": "manual",
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
GS_CMD_TEMPLATE = (
    "{gs_exe} -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -dPDFSETTINGS=/screen "
    "-dNOPAUSE -dQUIET -dBATCH -sOutputFile={out_file} -dDownsampleColorImages=true "
    "-dColorImageResolution={dpi} -dColorImageDownsampleType=/Bicubic -dColorImageDownsampleThreshold=1.0 "
    "{in_file}"
)


def get_file_size(path):
    size_bytes = os.path.getsize(path)
    size_kb = size_bytes / 1024
    size_mb = size_kb / 1024
    if size_mb >= 1:
        return f"{size_mb:.2f} MB"
    else:
        return f"{size_kb:.2f} KB"


class CompressThread(QThread):
    finished = Signal(bool, str)
    progress = Signal(int, int)  # current_page, total_pages

    def __init__(self, in_file, out_file, dpi, quality):
        super().__init__()
        self.in_file = in_file
        self.out_file = out_file
        self.dpi = dpi
        self.quality = quality

    def run(self):
        temp_input = None
        process = None
        try:
            # Always copy to a temp file with ASCII-only name
            temp_dir = tempfile.gettempdir()
            temp_input = os.path.join(
                temp_dir, f"pdfcompress_input_{os.getpid()}_{id(self)}.pdf"
            )
            shutil.copy2(self.in_file, temp_input)
            input_for_gs = temp_input
            
            # Set environment variable for unbuffered output
            env = os.environ.copy()
            if sys.platform == "win32":
                env["GSC_STDOUT"] = "1"  # Force stdout on Windows
            else:
                env["PYTHONUNBUFFERED"] = "1"
            
            cmd_list = [
                GS_EXECUTABLE,
                "-dNOPAUSE",
                "-dBATCH",
                "-dSAFER",  # Add safer mode
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                "-dPDFSETTINGS=/screen",
                f"-sOutputFile={self.out_file}",
                "-dDownsampleColorImages=true",
                f"-dColorImageResolution={self.dpi}",
                "-dColorImageDownsampleType=/Bicubic",
                "-dColorImageDownsampleThreshold=1.0",
                input_for_gs,
            ]
            
            kwargs = {
                'env': env,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE,
                'text': True,
                'bufsize': 0,  # Unbuffered output
            }
            
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                
            # Print command for debugging
            print(f"Running command: {' '.join(cmd_list)}")
                
            # Run gs with output capture
            process = subprocess.Popen(cmd_list, **kwargs)
            
            total_pages = None
            current_page = 0
            error_output = []
            
            import select
            import io
            
            # Set up non-blocking reading for Unix systems
            if sys.platform != "win32":
                import fcntl
                # Set stdout and stderr to non-blocking
                for pipe in [process.stdout, process.stderr]:
                    fd = pipe.fileno()
                    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            
            def read_line(pipe):
                if pipe is None:
                    return None
                if sys.platform == "win32":
                    return pipe.readline()
                else:
                    try:
                        return pipe.readline()
                    except io.BlockingIOError:
                        return None
            
            while process.poll() is None:
                if sys.platform == "win32":
                    stdout_line = read_line(process.stdout)
                    stderr_line = read_line(process.stderr)
                else:
                    # Use select for non-blocking reads on Unix
                    reads, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)
                    stdout_line = read_line(process.stdout) if process.stdout in reads else None
                    stderr_line = read_line(process.stderr) if process.stderr in reads else None
                
                # Process stdout
                if stdout_line:
                    line = stdout_line.strip()
                    if line:
                        error_output.append(f"STDOUT: {line}")
                        print(f"GS Output: {line}")
                        
                        # Look for total pages info
                        if "Processing pages" in line:
                            match = re.search(r"Processing pages \d+ through (\d+)", line)
                            if match:
                                total_pages = int(match.group(1))
                                self.progress.emit(0, total_pages)
                        # Look for current page progress
                        elif line.strip().startswith("Page"):
                            try:
                                current_page = int(line.strip().split()[1])
                                self.progress.emit(current_page, total_pages or 0)
                            except (IndexError, ValueError):
                                pass
                
                # Process stderr
                if stderr_line:
                    line = stderr_line.strip()
                    if line:
                        error_output.append(f"STDERR: {line}")
                        print(f"GS Error: {line}")
                
                # Small sleep to prevent CPU hogging
                self.msleep(10)
            
            # Read any remaining output
            stdout_remainder, stderr_remainder = process.communicate()
            if stdout_remainder:
                for line in stdout_remainder.splitlines():
                    if line.strip():
                        error_output.append(f"STDOUT: {line.strip()}")
                        print(f"GS Output: {line.strip()}")
            if stderr_remainder:
                for line in stderr_remainder.splitlines():
                    if line.strip():
                        error_output.append(f"STDERR: {line.strip()}")
                        print(f"GS Error: {line.strip()}")
            
            # Get the final return code
            return_code = process.returncode
            print(f"Process returned with code: {return_code}")
            
            if return_code != 0:
                error_msg = "\n".join(error_output[-10:])  # Last 10 lines of output
                raise subprocess.CalledProcessError(return_code, cmd_list, error_msg)
            
            # Verify the output file exists and has size > 0
            if not os.path.exists(self.out_file):
                raise Exception(f"Output file was not created at: {self.out_file}")
            
            if os.path.getsize(self.out_file) == 0:
                raise Exception(f"Output file is empty: {self.out_file}")
            
            # If we got here, everything succeeded
            print("Compression completed successfully!")
            self.finished.emit(True, "")
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Process failed with code {e.returncode}:\n"
            error_msg += f"Command: {' '.join(e.cmd)}\n"
            error_msg += f"Output:\n{e.output if e.output else 'No output captured'}"
            print(f"Error occurred: {error_msg}")  # Debug print
            self.finished.emit(False, error_msg)
            
        except Exception as e:
            print(f"Exception occurred: {str(e)}")  # Debug print
            self.finished.emit(False, str(e))
            
        finally:
            # Clean up process resources
            if process:
                try:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=1)
                except Exception as e:
                    print(f"Error cleaning up process: {e}")
                    
            # Clean up temp file
            if temp_input and os.path.exists(temp_input):
                try:
                    os.remove(temp_input)
                except Exception as e:
                    print(f"Error removing temp file: {e}")


class PresetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Compression Preset")
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        self.selected = None
        for preset in PRESETS:
            btn = QPushButton(preset, self)
            btn.clicked.connect(lambda checked, p=preset: self.select_preset(p))
            layout.addWidget(btn)
        button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def select_preset(self, preset):
        self.selected = preset
        self.accept()

    def get_choice(self):
        if self.exec() == QDialog.Accepted:
            return self.selected
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
        base_output = self.filename_edit.text()
        base, ext = os.path.splitext(base_output)
        out1 = base + "_1.pdf"
        out2 = base + "_2.pdf"
        try:
            # Check if split output files exist and prompt user
            for out_file in [out1, out2]:
                while os.path.exists(out_file):
                    resp = QMessageBox.question(
                        self,
                        "File Exists",
                        f"The file '{out_file}' already exists. Overwrite?",
                        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    )
                    if resp == QMessageBox.Yes:
                        break
                    elif resp == QMessageBox.No:
                        # Prompt for new filename
                        new_file, ok = QFileDialog.getSaveFileName(
                            self, "Save Split PDF As", out_file, "PDF files (*.pdf)"
                        )
                        if ok and new_file:
                            if out_file == out1:
                                out1 = new_file
                            else:
                                out2 = new_file
                            out_file = new_file
                        else:
                            continue
                    else:
                        return
            # Python 3+ open() is Unicode-safe on Windows and Linux
            with open(self.temp_compressed, "rb") as infile:
                reader = PyPDF2.PdfReader(infile)
                n = len(reader.pages)
                if n < 2:
                    QMessageBox.warning(
                        self, "Split PDF", "PDF has less than 2 pages, cannot split."
                    )
                    return
                mid = n // 2
                writer1 = PyPDF2.PdfWriter()
                writer2 = PyPDF2.PdfWriter()
                for i in range(mid):
                    writer1.add_page(reader.pages[i])
                for i in range(mid, n):
                    writer2.add_page(reader.pages[i])
                with open(out1, "wb") as f1:
                    writer1.write(f1)
                with open(out2, "wb") as f2:
                    writer2.write(f2)
            # Show a dialog with Quit and Continue options
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("PDF Split Complete")
            msg_box.setText(
                f"PDF split into:\n{out1}\n{out2}\n\nWhat would you like to do next?"
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
    # File selection
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file, _ = QFileDialog.getOpenFileName(
            None, "Select PDF File", "", "PDF files (*.pdf)"
        )
    if not input_file:
        return
    # Preset selection
    preset_dialog = PresetDialog()
    choice = preset_dialog.get_choice()
    if not choice:
        return
    if PRESETS[choice] == "manual":
        dpi, quality = manual_settings()
        if dpi is None or quality is None:
            return
    else:
        preset = PRESETS[choice]
        dpi, quality = preset["dpi"], preset["quality"]
    # Use temp file for output
    temp_dir = tempfile.gettempdir()
    temp_output_file = os.path.join(temp_dir, f"pdfcompress_{os.getpid()}.pdf")
    # Show loading dialog and compress in background
    loading = show_loading_dialog(None)
    thread = CompressThread(input_file, temp_output_file, dpi, quality)
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
                # Re-run preset selection
                preset_dialog = PresetDialog()
                choice = preset_dialog.get_choice()
                if not choice:
                    break
                if choice == "Manual":
                    dpi, quality = manual_settings()
                    if dpi is None or quality is None:
                        break
                else:
                    preset = PRESETS[choice]
                    dpi, quality = preset["dpi"], preset["quality"]
                # Re-compress to temp file
                loading = show_loading_dialog(None)
                thread = CompressThread(input_file, temp_output_file, dpi, quality)
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

