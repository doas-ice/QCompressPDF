import sys
import os
from runtime_environment import clean_environment, application_mutex
clean_environment()
import subprocess
from pathlib import Path
import tempfile
import shlex
import shutil
import queue
import threading
from pdf_core import (version_tuple, safe_stem, output_path, signature, assert_unchanged,
                      stable_snapshot, atomic_copy, gs_command, plan_split, write_range, watch_source_changes)
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
    "70 DPI (Extreme)": 70,
    "60 DPI (Extreme)": 60,
    "50 DPI (Extreme)": 50,
    "45 DPI (Extreme)": 45,
}


def get_gs_executable():
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).parent / "ghostscript" / "bin" / "gswin64c.exe"
        # A frozen release must never silently fall back to another installation.
        return str(bundled)

    def _find_on_path(names: list[str]) -> str | None:
        path_env = os.environ.get("PATH", "")
        for name in names:
            for folder in path_env.split(os.pathsep):
                folder = folder.strip('"')
                if not folder:
                    continue
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate
        return None

    def _find_windows_registry() -> str | None:
        try:
            import winreg  # type: ignore

            reg_roots = [
                r"SOFTWARE\GPL Ghostscript",
                r"SOFTWARE\Artifex Ghostscript",
                r"SOFTWARE\WOW6432Node\GPL Ghostscript",
                r"SOFTWARE\WOW6432Node\Artifex Ghostscript",
            ]
            for base_key in reg_roots:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_key) as k:
                        # Choose the highest version subkey
                        versions: list[str] = []
                        idx = 0
                        while True:
                            try:
                                versions.append(winreg.EnumKey(k, idx))
                                idx += 1
                            except OSError:
                                break
                        for ver in sorted(versions, reverse=True):
                            try:
                                with winreg.OpenKey(k, ver) as vk:
                                    for value_name in ("GS_DLL", "GS_LIB"):
                                        try:
                                            dll_or_lib, _ = winreg.QueryValueEx(vk, value_name)
                                        except OSError:
                                            continue
                                        if isinstance(dll_or_lib, str) and dll_or_lib:
                                            # GS_DLL is typically ...\bin\gsdll64.dll
                                            bin_dir = os.path.dirname(dll_or_lib)
                                            for exe in ("gswin64c.exe", "gswin32c.exe"):
                                                candidate = os.path.join(bin_dir, exe)
                                                if os.path.isfile(candidate):
                                                    return candidate
                            except OSError:
                                continue
                except OSError:
                    continue
        except Exception:
            return None
        return None

    def _find_common_locations() -> str | None:
        # Typical install: C:\Program Files\gs\gsX.YY.Z\bin\gswin64c.exe
        program_files = [
            os.environ.get("ProgramFiles", ""),
            os.environ.get("ProgramFiles(x86)", ""),
        ]
        for pf in filter(None, program_files):
            gs_root = os.path.join(pf, "gs")
            if not os.path.isdir(gs_root):
                continue
            try:
                versions = sorted(os.listdir(gs_root), reverse=True)
            except OSError:
                continue
            for ver in versions:
                bin_dir = os.path.join(gs_root, ver, "bin")
                for exe in ("gswin64c.exe", "gswin32c.exe"):
                    candidate = os.path.join(bin_dir, exe)
                    if os.path.isfile(candidate):
                        return candidate
        return None

    if sys.platform.startswith("win"):
        from_path = _find_on_path(["gswin64c.exe", "gswin32c.exe", "gs.exe"])
        if from_path:
            return from_path
        from_reg = _find_windows_registry()
        if from_reg:
            return from_reg
        from_common = _find_common_locations()
        if from_common:
            return from_common
        # Fallback to name; subprocess will try PATH.
        return "gswin64c"

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


CURRENT_VERSION = "1.6.0"

GITHUB_REPO = "doas-ice/QCompressPDF"


def check_for_updates():
    """Check GitHub releases for newer version"""
    try:
        with urllib.request.urlopen(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                latest_version = data['tag_name'].lstrip('v').lstrip('V')
                if version_tuple(latest_version) > version_tuple(CURRENT_VERSION):
                    return True, latest_version, data
        return False, None, None
    except Exception as e:
        print(f"Update check failed: {e}")
        return False, None, None


class UpdateChecker:
    """A daemon does network IO; a GUI timer consumes results without owning a thread."""
    def __init__(self, app):
        self.results = queue.Queue()
        self.timer = QTimer(app)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)
        threading.Thread(target=lambda: self.results.put(check_for_updates()), daemon=True).start()
        self.dialog = None

    def poll(self):
        try:
            available, version, data = self.results.get_nowait()
        except queue.Empty:
            return
        self.timer.stop()
        if available:
            self.dialog = QMessageBox()
            self.dialog.setWindowTitle("Update Available")
            self.dialog.setText(f"QCompressPDF {version} is available. You can keep working and update later.")
            self.dialog.addButton("Later", QMessageBox.RejectRole)
            release = self.dialog.addButton("Open Releases", QMessageBox.AcceptRole)
            def open_release(button):
                if button == release:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl
                    QDesktopServices.openUrl(QUrl(f"https://github.com/{GITHUB_REPO}/releases/latest"))
            self.dialog.buttonClicked.connect(open_release)
            self.dialog.setModal(False)
            self.dialog.show()


class SourceChangeMonitor:
    """Nonblocking advisory warning; no extra input or changes to the workflow."""
    def __init__(self, path, app):
        self.events = queue.Queue()
        self.stopped = threading.Event()
        self.changes = {}
        self.warning = None
        self.warned = False
        self.timer = QTimer(app)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)
        self.worker = threading.Thread(target=watch_source_changes,
                                       args=(path, self.stopped, self.events), daemon=True)
        self.worker.start()

    def poll(self):
        changed = False
        while True:
            try:
                field, before, after = self.events.get_nowait()
            except queue.Empty:
                break
            original = self.changes.get(field, (before, after))[0]
            self.changes[field] = original, after
            changed = True
        if not changed:
            return
        if not self.warned:
            self.warning = QMessageBox(QApplication.activeModalWidget())
            self.warning.setIcon(QMessageBox.Warning)
            self.warning.setWindowTitle("Source PDF is changing")
            self.warning.setText(
                "The selected PDF's file size or page count changed. "
                "It may still be exporting, copying, or syncing. "
                "Compressing it now may miss pages that arrive later.")
            self.warning.setStandardButtons(QMessageBox.Ok)
            self.warning.setModal(False)
            self.warned = True
            self.warning.show()
        # Update the existing warning rather than opening one for every page.
        # Its parent may have closed as the workflow advanced.
        try:
            self.warning.setInformativeText("\n".join(
                f"{field}: {before:,} → {after:,}" + (" bytes" if field == "File size" else " pages")
                for field, (before, after) in self.changes.items()))
        except RuntimeError:
            pass  # Qt already destroyed the warning with its parent.

    def stop(self):
        self.stopped.set()
        self.timer.stop()
        if self.warning is not None:
            try:
                self.warning.close()
            except RuntimeError:
                pass
        # Do not join: slow/cloud-backed IO may still be pending in the daemon.


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
        output_workspace = None
        try:
            # A short stability check is performed off the GUI thread. Keep the
            # source signature until completion so later appends cannot go unnoticed.
            fd, temp_input = tempfile.mkstemp(prefix="pdfcompress_input_", suffix=".pdf")
            os.close(fd)
            self.source_signature, self.total_pages = stable_snapshot(self.in_file, temp_input)
            self.progress.emit(0, self.total_pages)
            input_for_gs = temp_input

            # Set environment variable for unbuffered output
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            if sys.platform == "win32":
                # Force Ghostscript to output progress on Windows
                env["GSC_QUIET"] = "0"

            # Use a short ASCII output basename too: Ghostscript interprets %
            # sequences in output paths and some builds mishandle Unicode names.
            output_workspace = tempfile.TemporaryDirectory(prefix="qcompress-gs-")
            gs_output = os.path.join(output_workspace.name, "output.pdf")
            cmd_list = gs_command(GS_EXECUTABLE, input_for_gs, gs_output, self.dpi)

            kwargs = {
                'env': env,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.STDOUT,  # Redirect stderr to stdout
                'text': True,
                'bufsize': 1,
                'errors': 'replace',  # Unbuffered
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

            if get_pdf_page_count(gs_output) != self.total_pages:
                raise ValueError("Compression did not preserve all source pages; no output was saved.")
            assert_unchanged(self.in_file, self.source_signature)
            # Vector-heavy/already optimized PDFs can grow after pdfwrite. Keep
            # the validated source in that case instead of claiming a reduction.
            candidate = gs_output if os.path.getsize(gs_output) < os.path.getsize(temp_input) else temp_input
            atomic_copy(candidate, self.out_file)

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

            if process and process.stdout:
                process.stdout.close()
            if output_workspace is not None:
                output_workspace.cleanup()
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


def estimate_size(source, dpi, key, results):
    try:
        with tempfile.TemporaryDirectory(prefix="qcompress-estimate-") as folder:
            sample = os.path.join(folder, "sample.pdf")
            output = os.path.join(folder, "output.pdf")
            with open(source, 'rb') as stream:
                reader = PyPDF2.PdfReader(stream)
                count = len(reader.pages)
                if not count:
                    raise ValueError("No pages")
                writer = PyPDF2.PdfWriter()
                indices = sorted({0, count // 2, count - 1})
                for index in indices:
                    writer.add_page(reader.pages[index])
                with open(sample, 'wb') as out:
                    writer.write(out)
            assert_unchanged(source, key[1])
            kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
            subprocess.run(gs_command(GS_EXECUTABLE, sample, output, dpi),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=15, **kwargs)
            assert_unchanged(source, key[1])
            ratio = min(1, os.path.getsize(output) / max(os.path.getsize(sample), 1))
            estimated = os.path.getsize(source) * ratio / 1024 / 1024
            message = f"Estimated size: ≈ {estimated:.2f} MB (sample-based; actual size may vary)."
    except Exception:
        message = "Estimated size unavailable; you can still compress and inspect the actual size."
    results.put((key, message))


class SplitPlanThread(QThread):
    def __init__(self, path, mode, size_mb, parts):
        super().__init__()
        self.args = path, mode, size_mb, parts
        self.ranges = None
        self.error = None

    def run(self):
        path, mode, size_mb, parts = self.args
        try:
            with open(path, 'rb') as stream:
                self.ranges = plan_split(PyPDF2.PdfReader(stream), mode, int(size_mb * 1024 * 1024), parts)
        except Exception as error:
            self.error = str(error)


class DpiSelectorDialog(QDialog):
    def __init__(self, input_file=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select DPI for Compression")
        self.setMinimumWidth(350)
        layout = QVBoxLayout(self)
        self.selected_dpi = 300  # Default
        self.input_file = input_file
        self.estimate_results = queue.Queue()
        self.estimate_running = False
        self.estimate_cache = {}
        self.estimate_timer = QTimer(self)
        self.estimate_timer.setSingleShot(True)
        self.estimate_timer.timeout.connect(self.start_estimate)
        self.estimate_poll = QTimer(self)
        self.estimate_poll.timeout.connect(self.poll_estimate)
        self.estimate_poll.start(100)

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

        # Slider with +/- buttons
        slider_layout = QHBoxLayout()
        
        # Decrease button
        self.decrease_btn = QPushButton("-", self)
        self.decrease_btn.setMaximumWidth(40)
        self.decrease_btn.clicked.connect(self.decrease_dpi)
        slider_layout.addWidget(self.decrease_btn)
        
        slider_layout.addWidget(QLabel("10"))
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(10, 600)
        self.slider.setValue(300)
        self.slider.setTickInterval(50)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.valueChanged.connect(self.update_from_slider)
        slider_layout.addWidget(self.slider)
        slider_layout.addWidget(QLabel("600"))
        
        # Increase button
        self.increase_btn = QPushButton("+", self)
        self.increase_btn.setMaximumWidth(40)
        self.increase_btn.clicked.connect(self.increase_dpi)
        slider_layout.addWidget(self.increase_btn)
        
        layout.addLayout(slider_layout)

        # Current DPI display
        self.dpi_label = QLabel("Selected DPI: 300")
        layout.addWidget(self.dpi_label)
        self.estimate_label = QLabel("Estimated size: preparing sample…")
        self.estimate_label.setWordWrap(True)
        layout.addWidget(self.estimate_label)
        self.estimate_timer.start(400)

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
        if hasattr(self, "estimate_label"):
            self.estimate_label.setText("Estimated size: calculating…")
            self.estimate_timer.start(400)

    def start_estimate(self):
        if not self.input_file or self.estimate_running:
            return
        dpi = self.selected_dpi
        try:
            key = (dpi, signature(self.input_file))
        except OSError:
            self.estimate_label.setText("Estimated size unavailable: cannot read input.")
            return
        if key in self.estimate_cache:
            self.estimate_label.setText(self.estimate_cache[key])
            return
        self.estimate_running = True
        # The worker captures no Qt objects and can finish safely after closure.
        results, source = self.estimate_results, self.input_file
        threading.Thread(target=estimate_size, args=(source, dpi, key, results), daemon=True).start()

    def poll_estimate(self):
        try:
            key, message = self.estimate_results.get_nowait()
        except queue.Empty:
            return
        self.estimate_running = False
        self.estimate_cache[key] = message
        try:
            current = (self.selected_dpi, signature(self.input_file))
        except OSError:
            current = None
        if key == current:
            self.estimate_label.setText(message)
        else:
            self.estimate_timer.start(400)

    def increase_dpi(self):
        """Increase DPI by 1"""
        new_dpi = min(600, self.selected_dpi + 1)
        self.set_dpi(new_dpi)

    def decrease_dpi(self):
        """Decrease DPI by 1"""
        new_dpi = max(10, self.selected_dpi - 1)
        self.set_dpi(new_dpi)

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


class SplitModeDialog(QDialog):
    """Dialog to select split mode: Auto, By Size, or By Number"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Split Mode")
        self.setMinimumWidth(350)
        layout = QVBoxLayout(self)
        
        # Add description
        layout.addWidget(QLabel("Choose how to split the PDF:"))
        
        # Mode selection
        self.mode = None
        self.size_mb = 5.0
        self.num_splits = 2
        
        # Auto mode button
        auto_btn = QPushButton("Auto - Split under 5 MB with smart distribution", self)
        auto_btn.clicked.connect(lambda: self.select_mode("auto"))
        layout.addWidget(auto_btn)
        
        # By Size mode button
        size_btn = QPushButton("By Size - Specify custom size limit", self)
        size_btn.clicked.connect(lambda: self.select_mode("size"))
        layout.addWidget(size_btn)
        
        # By Number mode button
        number_btn = QPushButton("By Number - Specify number of splits", self)
        number_btn.clicked.connect(lambda: self.select_mode("number"))
        layout.addWidget(number_btn)
        
        # Cancel button
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)
        
        self.setLayout(layout)
    
    def select_mode(self, mode):
        """Handle mode selection"""
        self.mode = mode
        
        if mode == "size":
            # Ask for size limit
            size, ok = QInputDialog.getDouble(
                self, "Split by Size",
                "Enter maximum size per part (MB):",
                5.0, 0.1, 100.0, 1
            )
            if ok:
                self.size_mb = size
                self.accept()
            else:
                self.mode = None
        
        elif mode == "number":
            # Ask for number of splits
            num, ok = QInputDialog.getInt(
                self, "Split by Number",
                "Enter number of splits:",
                2, 2, 20, 1
            )
            if ok:
                self.num_splits = num
                self.accept()
            else:
                self.mode = None
        
        else:  # auto mode
            self.accept()
    
    def get_result(self):
        """Return the selected mode and parameters"""
        if self.exec() == QDialog.Accepted and self.mode:
            return self.mode, self.size_mb, self.num_splits
        return None, None, None


class PreviewDialog(QDialog):
    def __init__(
        self, original, temp_compressed, dpi, quality, default_output, parent=None, source_signature=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Preview Compression")
        self.setMinimumWidth(420)
        self.accepted_result = False
        self.output_file = default_output
        self.temp_compressed = temp_compressed
        self.original = os.path.abspath(original)
        self.source_signature = source_signature or signature(original)
        orig_bytes = os.path.getsize(original)
        comp_bytes = os.path.getsize(temp_compressed)
        orig_size = get_file_size(original)
        comp_size = get_file_size(temp_compressed)
        reduction = (1 - comp_bytes / orig_bytes) * 100 if orig_bytes else 0
        layout = QVBoxLayout(self)
        info = QLabel(
            f"DPI: {dpi}\nTotal pages: {get_pdf_page_count(temp_compressed)}\n\n"
            f"Original size: {orig_size}\n"
            f"Compressed size: {comp_size}\n"
            f"Reduction: {reduction:.2f}%\n"
            + ("Already optimized or vector-heavy: original quality retained.\n" if reduction <= 0 else "") + "\n"
            f"Preview the PDF and then click Accept to save, or Retry to try different settings."
        )
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(info)
        
        # Output file configuration section
        layout.addWidget(QLabel("Output directory:"))
        dir_layout = QHBoxLayout()
        self.directory_edit = QLineEdit(os.path.dirname(default_output), self)
        dir_layout.addWidget(self.directory_edit)
        browse_btn = QPushButton(self)
        browse_btn.setIcon(browse_btn.style().standardIcon(browse_btn.style().StandardPixmap.SP_DirIcon))
        browse_btn.setToolTip("Browse...")
        browse_btn.clicked.connect(self.browse_directory)
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)
        
        layout.addWidget(QLabel("Filename:"))
        filename_layout = QHBoxLayout()
        base_name = os.path.splitext(os.path.basename(default_output))[0]
        self.filename_edit = QLineEdit(base_name, self)
        filename_layout.addWidget(self.filename_edit)
        paste_btn = QPushButton(self)
        paste_btn.setIcon(paste_btn.style().standardIcon(paste_btn.style().StandardPixmap.SP_DialogSaveButton))
        paste_btn.setToolTip("Paste")
        paste_btn.clicked.connect(self.paste_filename)
        filename_layout.addWidget(paste_btn)
        self.extension_edit = QLineEdit(".pdf", self)
        self.extension_edit.setMaximumWidth(60)
        self.extension_edit.setReadOnly(True)
        filename_layout.addWidget(self.extension_edit)
        layout.addLayout(filename_layout)
        self.name_status = QLabel()
        self.name_status.setWordWrap(True)
        layout.addWidget(self.name_status)
        btn_layout = QHBoxLayout()
        preview_btn = QPushButton("Preview PDF", self)
        preview_btn.clicked.connect(self.preview_pdf)
        btn_layout.addWidget(preview_btn)
        split_btn = QPushButton("Split PDF", self)
        self.split_btn = split_btn
        split_btn.clicked.connect(self.split_pdf)
        btn_layout.addWidget(split_btn)
        accept_btn = QPushButton("Accept && Save", self)
        self.accept_btn = accept_btn
        accept_btn.clicked.connect(self.accept_dialog)
        btn_layout.addWidget(accept_btn)
        retry_btn = QPushButton("Retry with other Settings", self)
        self.filename_edit.textChanged.connect(self.validate_name)
        self.directory_edit.textChanged.connect(self.validate_name)
        self.validate_name()
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
        """Split PDF based on user-selected mode: Auto, By Size, or By Number"""
        # Show mode selection dialog
        mode_dialog = SplitModeDialog(self)
        mode, size_mb, num_splits = mode_dialog.get_result()
        
        if not mode:
            return  # User cancelled
        
        split_files = []
        try:
            assert_unchanged(self.original, self.source_signature)
            output_path(self.directory_edit.text(), self.filename_edit.text())
            worker = SplitPlanThread(self.temp_compressed, mode, size_mb, num_splits)
            loading = show_loading_dialog(self, "Measuring PDF parts…")
            loading.setRange(0, 0)
            worker.finished.connect(loading.accept)
            worker.start()
            loading.exec()
            worker.wait()
            if worker.error:
                raise ValueError(worker.error)
            assert_unchanged(self.original, self.source_signature)
            best_split = worker.ranges
            with open(self.temp_compressed, "rb") as infile:
                reader = PyPDF2.PdfReader(infile)
                total_pages = len(reader.pages)

                # Resolve every destination before writing, so cancelling a
                # conflict dialog cannot leave half of the requested split.
                targets = []
                for part_num in range(1, len(best_split) + 1):
                    target = output_path(self.directory_edit.text(), self.filename_edit.text(), f"_part{part_num}")
                    while os.path.exists(target):
                        answer = QMessageBox.question(
                            self, "File Exists", f"The file '{target}' already exists. Overwrite?",
                            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
                        if answer == QMessageBox.Cancel:
                            return
                        if answer == QMessageBox.Yes:
                            break
                        replacement, selected = QFileDialog.getSaveFileName(
                            self, "Save Split PDF As", target, "PDF files (*.pdf)")
                        if not selected or not replacement:
                            return
                        target = output_path(os.path.dirname(replacement), Path(replacement).stem)
                    canonical = os.path.normcase(os.path.realpath(target))
                    if canonical == os.path.normcase(os.path.realpath(self.original)):
                        raise ValueError("Choose a split output other than the original PDF.")
                    if canonical in {os.path.normcase(os.path.realpath(t)) for t in targets}:
                        raise ValueError("Each split part needs a different filename.")
                    targets.append(target)

                with tempfile.TemporaryDirectory(prefix="qcompress-parts-") as folder:
                    staged = []
                    for index, (start_page, end_page) in enumerate(best_split):
                        temporary = os.path.join(folder, f"part{index}.pdf")
                        with open(temporary, 'wb') as out_file:
                            write_range(reader, start_page, end_page, out_file)
                        if get_pdf_page_count(temporary) != end_page - start_page:
                            raise ValueError("Split page count validation failed.")
                        if mode != 'number' and os.path.getsize(temporary) > int(size_mb * 1024 * 1024):
                            raise ValueError("Serialized part exceeds the requested limit.")
                        staged.append(temporary)
                    assert_unchanged(self.original, self.source_signature)
                    for temporary, target in zip(staged, targets):
                        atomic_copy(temporary, target)
                        split_files.append(target)

                # Show results
                size_info = []
                for i, f in enumerate(split_files, 1):
                    part_size_mb = os.path.getsize(f) / 1024 / 1024
                    start_page, end_page = best_split[i-1]
                    page_count = end_page - start_page
                    size_info.append(f"Part {i}: {part_size_mb:.1f} MB ({page_count} pages)")

                total_parts = len(split_files)
                avg_size = sum(os.path.getsize(f) for f in split_files) / total_parts / 1024 / 1024
                size_range = max(os.path.getsize(f) for f in split_files) / 1024 / 1024 - min(os.path.getsize(f) for f in split_files) / 1024 / 1024

                mode_name = {"auto": "Auto (5 MB)", "size": f"By Size ({size_mb} MB)", "number": f"By Number ({num_splits} parts)"}[mode]
                
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle(f"PDF Split Complete - {mode_name}")
                msg_box.setText(
                    f"PDF split into {total_parts} parts ({total_pages} total pages):\n"
                    f"Average size: {avg_size:.1f} MB\n"
                    f"Size variation: {size_range:.1f} MB\n\n" +
                    "\n".join(size_info) +
                    f"\n\nWhat would you like to do next?"
                )
                quit_btn = msg_box.addButton("Quit Program", QMessageBox.DestructiveRole)
                continue_btn = msg_box.addButton("Continue Compression", QMessageBox.AcceptRole)
                msg_box.setDefaultButton(continue_btn)
                msg_box.exec()

                if msg_box.clickedButton() == quit_btn:
                    self.close()
                    QApplication.instance().quit()

        except Exception as e:
            QMessageBox.critical(self, "Split PDF Error", f"Failed to split PDF:\n{e}"
                                 + ("\n\nParts already saved:\n" + "\n".join(split_files) if split_files else ""))

    def validate_name(self):
        text = self.filename_edit.text()
        clean = safe_stem(text, self.directory_edit.text(), editing=True)
        if clean != text:
            cursor = self.filename_edit.cursorPosition()
            self.filename_edit.blockSignals(True)
            self.filename_edit.setText(clean)
            self.filename_edit.setCursorPosition(min(cursor, len(clean)))
            self.filename_edit.blockSignals(False)
        try:
            path = output_path(self.directory_edit.text(), clean)
            if os.path.realpath(path) == os.path.realpath(self.original):
                raise ValueError("Choose a different name to preserve the original PDF.")
            self.name_status.setText("Filename adjusted for filesystem compatibility." if clean != text else "")
            valid = True
        except ValueError as error:
            self.name_status.setText(str(error))
            valid = False
        self.accept_btn.setEnabled(valid)
        self.split_btn.setEnabled(valid)
        return valid

    def browse_directory(self):
        """Open directory browser dialog"""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self.directory_edit.text()
        )
        if directory:
            self.directory_edit.setText(directory)

    def paste_filename(self):
        """Paste filename from clipboard"""
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            # Remove any path separators and extension from pasted text
            text = os.path.basename(text)
            text = os.path.splitext(text)[0]
            self.filename_edit.setText(text)

    def accept_dialog(self):
        if not self.validate_name():
            return
        self.output_file = output_path(self.directory_edit.text(), self.filename_edit.text())
        self.accepted_result = True
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
    mutex = application_mutex()
    app = QApplication(sys.argv)
    # Keep a Python reference for the lifetime of the workflow.
    update_checker = UpdateChecker(app)
    # File selection
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file, _ = QFileDialog.getOpenFileName(
            None, "Select PDF File", "", "PDF files (*.pdf)"
        )
    if not input_file:
        return
    source_monitor = SourceChangeMonitor(input_file, app)
    try:
        # DPI selection
        dpi_dialog = DpiSelectorDialog(input_file)
        dpi = dpi_dialog.get_dpi()
        if dpi is None:
            return
        quality = 85  # Dummy value for compatibility
        # Use temp file for output
        workspace = tempfile.TemporaryDirectory(prefix="qcompress-preview-")
        temp_output_file = os.path.join(workspace.name, "compressed.pdf")
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
                input_file, temp_output_file, dpi, quality, default_output_file,
                source_signature=thread.source_signature
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
                            final_output_file = output_path(os.path.dirname(new_file), Path(new_file).stem)
                        else:
                            continue
                    else:
                        # Cancel
                        if os.path.exists(temp_output_file):
                            os.remove(temp_output_file)
                        return
                try:
                    if os.path.realpath(final_output_file) == os.path.realpath(input_file):
                        raise ValueError("Choose a different filename to preserve the original PDF.")
                    assert_unchanged(input_file, thread.source_signature)
                    atomic_copy(temp_output_file, final_output_file)
                    os.remove(temp_output_file)
                except Exception as e:
                    QMessageBox.critical(
                        None, "Error", f"Could not save as new filename: {e}"
                    )
                    continue
                QMessageBox.information(
                    None, "Success", f"Compressed PDF saved as:\n{final_output_file}\n\nTotal pages: {thread.total_pages}"
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
                    dpi_dialog = DpiSelectorDialog(input_file)
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
    finally:
        source_monitor.stop()


def self_test():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        source, output = os.path.join(folder, 'source.pdf'), os.path.join(folder, 'output.pdf')
        writer = PyPDF2.PdfWriter()
        writer.add_blank_page(width=100, height=100)
        with open(source, 'wb') as stream:
            writer.write(stream)
        subprocess.run(gs_command(GS_EXECUTABLE, source, output, 100), check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if get_pdf_page_count(output) != 1:
            raise RuntimeError('Ghostscript smoke test lost a page')


if __name__ == "__main__":
    if '--self-test' in sys.argv:
        try:
            self_test()
        except Exception as error:
            if sys.stderr is not None:
                print(f'Self-test failed: {error}', file=sys.stderr)
            sys.exit(1)
    else:
        main()
