import sys
import os
import subprocess
from pathlib import Path
import tempfile
import shlex
import shutil
from PySide6.QtWidgets import (
    QApplication, QWidget, QFileDialog, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QLineEdit, QInputDialog, QProgressDialog, QDialogButtonBox, QSpinBox
)
from PySide6.QtCore import Qt, QThread, Signal

PRESETS = {
    "Low (300dpi, Q85)": {"dpi": 300, "quality": 85},
    "Medium (200dpi, Q70)": {"dpi": 200, "quality": 70},
    "High (150dpi, Q50)": {"dpi": 150, "quality": 50},
    "Ultra (100dpi, Q40)": {"dpi": 100, "quality": 40},
    "Extreme (72dpi, Q30)": {"dpi": 72, "quality": 30},
    "Manual": None,
}

def get_gs_executable():
    if sys.platform.startswith("win"):
        for exe in ["gswin64c", "gswin32c", "gs"]:
            if any(os.access(os.path.join(path, exe + ".exe"), os.X_OK) for path in os.environ["PATH"].split(os.pathsep)):
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
    def __init__(self, in_file, out_file, dpi, quality):
        super().__init__()
        self.in_file = in_file
        self.out_file = out_file
        self.dpi = dpi
        self.quality = quality
    def run(self):
        # Build command as a list for subprocess.run
        cmd = GS_CMD_TEMPLATE.format(
            gs_exe=GS_EXECUTABLE,
            out_file=shlex.quote(self.out_file),
            in_file=shlex.quote(self.in_file),
            dpi=self.dpi
        )
        # Split command into list (shlex.split handles quoting)
        cmd_list = shlex.split(cmd)
        try:
            subprocess.run(cmd_list, check=True)
            self.finished.emit(True, "")
        except subprocess.CalledProcessError as e:
            self.finished.emit(False, str(e))

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
    def __init__(self, original, temp_compressed, dpi, quality, default_output, parent=None):
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
        accept_btn = QPushButton("Accept", self)
        accept_btn.clicked.connect(self.accept_dialog)
        btn_layout.addWidget(accept_btn)
        retry_btn = QPushButton("Retry", self)
        retry_btn.clicked.connect(self.reject)
        btn_layout.addWidget(retry_btn)
        layout.addLayout(btn_layout)
    def preview_pdf(self):
        path = self.temp_compressed  # Always preview the temp file
        try:
            if sys.platform.startswith("darwin"):
                subprocess.run(["open", path])
            elif os.name == "nt":
                os.startfile(path)
            elif os.name == "posix":
                subprocess.run(["xdg-open", path])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not preview file: {e}")
    def accept_dialog(self):
        self.accepted_result = True
        self.output_file = self.filename_edit.text()
        self.accept()
    def get_result(self):
        if self.exec() == QDialog.Accepted and self.accepted_result:
            return True, self.output_file
        return False, self.output_file

def show_loading_dialog(parent, text="Compressing PDF..."):
    dlg = QProgressDialog(text, None, 0, 0, parent)
    dlg.setWindowTitle("Please Wait")
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setCancelButton(None)
    dlg.setMinimumDuration(0)
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
        input_file, _ = QFileDialog.getOpenFileName(None, "Select PDF File", "", "PDF files (*.pdf)")
    if not input_file:
        return
    # Preset selection
    preset_dialog = PresetDialog()
    choice = preset_dialog.get_choice()
    if not choice:
        return
    if choice == "Manual":
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
    result = {'success': False, 'error': ''}
    def on_finished(success, error):
        result['success'] = success
        result['error'] = error
        loading.close()
    thread.finished.connect(on_finished)
    thread.start()
    loading.exec()
    thread.wait()
    if not result['success']:
        QMessageBox.critical(None, "Error", f"Compression failed:\n{result['error']}")
        if os.path.exists(temp_output_file):
            os.remove(temp_output_file)
        return
    # Preview dialog
    default_output_file = str(Path(input_file).with_name(Path(input_file).stem + f"_compressed.pdf"))
    while True:
        preview_dialog = PreviewDialog(input_file, temp_output_file, dpi, quality, default_output_file)
        accepted, final_output_file = preview_dialog.get_result()
        if accepted:
            try:
                shutil.move(temp_output_file, final_output_file)
            except Exception as e:
                QMessageBox.critical(None, "Error", f"Could not save as new filename: {e}")
                continue
            QMessageBox.information(None, "Success", f"Compressed PDF saved as:\n{final_output_file}")
            break
        else:
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)
            retry = QMessageBox.question(None, "Retry", "Do you want to retry with different settings?", QMessageBox.Yes | QMessageBox.No)
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
                result = {'success': False, 'error': ''}
                thread.finished.connect(on_finished)
                thread.start()
                loading.exec()
                thread.wait()
                if not result['success']:
                    QMessageBox.critical(None, "Error", f"Compression failed:\n{result['error']}")
                    if os.path.exists(temp_output_file):
                        os.remove(temp_output_file)
                    break
                continue
            else:
                break
if __name__ == "__main__":
    main() 