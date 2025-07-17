import sys
import os
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QFileDialog, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QLineEdit, QInputDialog
)
from PySide6.QtCore import Qt

PRESETS = {
    "Low (300dpi, Q85)": {"dpi": 300, "quality": 85},
    "Medium (200dpi, Q70)": {"dpi": 200, "quality": 70},
    "High (150dpi, Q50)": {"dpi": 150, "quality": 50},
    "Ultra (100dpi, Q40)": {"dpi": 100, "quality": 40},
    "Extreme (72dpi, Q30)": {"dpi": 72, "quality": 30},
    "Manual": None,
}

GS_CMD_TEMPLATE = (
    "gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -dPDFSETTINGS=/screen "
    "-dNOPAUSE -dQUIET -dBATCH -sOutputFile='{out_file}' -dDownsampleColorImages=true "
    "-dColorImageResolution={dpi} -dColorImageDownsampleType=/Bicubic -dColorImageDownsampleThreshold=1.0 "
    "'{in_file}'"
)

def get_file_size(path):
    size_bytes = os.path.getsize(path)
    size_kb = size_bytes / 1024
    size_mb = size_kb / 1024
    if size_mb >= 1:
        return f"{size_mb:.2f} MB"
    else:
        return f"{size_kb:.2f} KB"

def compress_pdf(in_file, out_file, dpi, quality):
    cmd = GS_CMD_TEMPLATE.format(out_file=out_file, in_file=in_file, dpi=dpi)
    subprocess.run(cmd, shell=True)

def manual_settings(parent=None):
    dpi, ok1 = QInputDialog.getInt(parent, "Manual DPI", "Enter DPI (e.g. 150):", 150, 10, 600)
    if not ok1:
        return None, None
    quality, ok2 = QInputDialog.getInt(parent, "Manual Quality", "Enter Quality (1-100):", 50, 1, 100)
    if not ok2:
        return None, None
    return dpi, quality

class PresetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Compression Preset")
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        self.list = QListWidget(self)
        for preset in PRESETS:
            self.list.addItem(preset)
        layout.addWidget(self.list)
        btn = QPushButton("Select", self)
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
    def get_choice(self):
        if self.exec() == QDialog.Accepted:
            items = self.list.selectedItems()
            if items:
                return items[0].text()
        return None

class PreviewDialog(QDialog):
    def __init__(self, original, compressed, dpi, quality, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview Compression")
        self.setMinimumWidth(420)
        self.accepted_result = False
        self.output_file = compressed
        orig_bytes = os.path.getsize(original)
        comp_bytes = os.path.getsize(compressed)
        orig_size = get_file_size(original)
        comp_size = get_file_size(compressed)
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
        self.filename_edit = QLineEdit(compressed, self)
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
        path = self.filename_edit.text()
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
    output_file = str(Path(input_file).with_name(Path(input_file).stem + f"_compressed.pdf"))
    compress_pdf(input_file, output_file, dpi, quality)
    # Preview dialog
    while True:
        preview_dialog = PreviewDialog(input_file, output_file, dpi, quality)
        accepted, final_output_file = preview_dialog.get_result()
        if accepted:
            if final_output_file != output_file:
                try:
                    os.replace(output_file, final_output_file)
                except Exception as e:
                    QMessageBox.critical(None, "Error", f"Could not save as new filename: {e}")
                    continue
            QMessageBox.information(None, "Success", f"Compressed PDF saved as:\n{final_output_file}")
            break
        else:
            os.remove(output_file)
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
                output_file = str(Path(input_file).with_name(Path(input_file).stem + f"_compressed.pdf"))
                compress_pdf(input_file, output_file, dpi, quality)
                continue
            else:
                break
if __name__ == "__main__":
    main() 