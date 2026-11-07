import io
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
import PyPDF2
import compress_qt as app
from pdf_core import gs_command, signature
from test_pdf_core import pdf_bytes


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])
        cls.qt.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.source = Path(self.folder.name)/'source.pdf'
        self.output = Path(self.folder.name)/'preview.pdf'
        self.source.write_bytes(pdf_bytes([0, 0, 0]))
        self.output.write_bytes(self.source.read_bytes())
        os.utime(self.source, (time.time()-10, time.time()-10))

    def test_realtime_filename_validation(self):
        dialog = app.PreviewDialog(str(self.source), str(self.output), 100, 85,
                                   str(Path(self.folder.name)/'saved.pdf'))
        dialog.filename_edit.setText('bad<>:"/\\|?*name')
        self.assertEqual(dialog.filename_edit.text(), 'badname')
        self.assertTrue(dialog.accept_btn.isEnabled())
        dialog.filename_edit.setText('my ')
        self.assertEqual(dialog.filename_edit.text(), 'my ')
        QTest.keyClicks(dialog.filename_edit, 'file')
        self.assertEqual(dialog.filename_edit.text(), 'my file')
        dialog.filename_edit.setText('...')
        self.assertFalse(dialog.accept_btn.isEnabled())
        dialog.filename_edit.setText('source')
        self.assertFalse(dialog.accept_btn.isEnabled())
        dialog.filename_edit.setText('CON')
        dialog.accept_dialog()
        self.assertEqual(dialog.output_file, str(Path(self.folder.name)/'_CON.pdf'))
        dialog.close()

    def test_slow_update_check_does_not_block_gui(self):
        finished = threading.Event()
        def slow():
            finished.wait(2)
            return False, None, None
        with patch.object(app, 'check_for_updates', side_effect=slow):
            start = time.monotonic()
            checker = app.UpdateChecker(self.qt)
            self.assertLess(time.monotonic()-start, 0.1)
            dialog = app.DpiSelectorDialog()
            dialog.set_dpi(150)
            QTest.qWait(30)
            self.assertEqual(dialog.selected_dpi, 150)
            finished.set()
            checker.timer.stop()
            dialog.close()

    @unittest.skipUnless(shutil.which('gs') or os.name == 'nt', 'Ghostscript required')
    def test_vector_text_over_raster_compression(self):
        # Use actual Ghostscript, retain text and every page, never enlarge output.
        self.source.write_bytes(pdf_bytes([90000, 80000, 10000], image=True))
        worker = app.CompressThread(str(self.source), str(self.output), 100)
        events = []
        worker.finished.connect(lambda ok, error: events.append((ok, error)))
        worker.run()
        self.assertEqual(events, [(True, '')])
        reader = PyPDF2.PdfReader(str(self.output))
        self.assertEqual(len(reader.pages), 3)
        self.assertEqual([p.extract_text().strip() for p in reader.pages], ['Page 1', 'Page 2', 'Page 3'])
        self.assertLessEqual(self.output.stat().st_size, self.source.stat().st_size)

    @unittest.skipUnless(shutil.which('gs'), 'Ghostscript required')
    def test_missing_pages_are_rejected(self):
        original = app.gs_command
        def truncate(exe, source, dest, dpi):
            return original(exe, source, dest, dpi)[:-1] + ['-dLastPage=1', source]
        events = []
        worker = app.CompressThread(str(self.source), str(self.output), 100)
        worker.finished.connect(lambda ok, error: events.append((ok, error)))
        old = self.output.read_bytes()
        with patch.object(app, 'gs_command', side_effect=truncate):
            worker.run()
        self.assertFalse(events[0][0])
        self.assertIn('all source pages', events[0][1])
        self.assertEqual(self.output.read_bytes(), old)

    @unittest.skipUnless(shutil.which('gs'), 'Ghostscript required')
    def test_source_change_during_compression_rejected(self):
        original = app.gs_command
        def change(exe, source, dest, dpi):
            self.source.write_bytes(pdf_bytes([0]*4))
            return original(exe, source, dest, dpi)
        events = []
        worker = app.CompressThread(str(self.source), str(self.output), 100)
        worker.finished.connect(lambda ok, error: events.append((ok, error)))
        old = self.output.read_bytes()
        with patch.object(app, 'gs_command', side_effect=change):
            worker.run()
        self.assertFalse(events[0][0])
        self.assertIn('changed', events[0][1])
        self.assertEqual(self.output.read_bytes(), old)

    @unittest.skipUnless(shutil.which('gs'), 'Ghostscript required')
    def test_estimate_and_timeout_fallback(self):
        results = queue.Queue()
        key = (100, signature(self.source))
        app.estimate_size(str(self.source), 100, key, results)
        self.assertIn('sample-based', results.get()[1])
        with patch.object(app.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gs', 15)):
            app.estimate_size(str(self.source), 100, key, results)
        self.assertIn('unavailable', results.get()[1])

    def test_cancel_split_conflict_writes_no_parts(self):
        existing = Path(self.folder.name)/'saved_part2.pdf'
        existing.write_bytes(b'existing output')
        dialog = app.PreviewDialog(str(self.source), str(self.output), 100, 85,
                                   str(Path(self.folder.name)/'saved.pdf'))
        with patch.object(app.SplitModeDialog, 'get_result', return_value=('number', 5, 2)), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
            dialog.split_pdf()
        self.assertFalse((Path(self.folder.name)/'saved_part1.pdf').exists())
        self.assertEqual(existing.read_bytes(), b'existing output')
        dialog.close()

    def test_split_uses_selected_directory_and_keeps_page_order(self):
        dialog = app.PreviewDialog(str(self.source), str(self.output), 100, 85,
                                   str(Path(self.folder.name)/'saved.pdf'))
        with patch.object(app.SplitModeDialog, 'get_result', return_value=('number', 5, 2)), \
             patch.object(QMessageBox, 'exec', return_value=0):
            dialog.split_pdf()
        files = sorted(Path(self.folder.name).glob('saved_part*.pdf'))
        self.assertEqual(len(files), 2)
        self.assertEqual([page.extract_text() for f in files for page in PyPDF2.PdfReader(str(f)).pages],
                         ['Page 1', 'Page 2', 'Page 3'])
        dialog.close()


if __name__ == '__main__':
    unittest.main()
