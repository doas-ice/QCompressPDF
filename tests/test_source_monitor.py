import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
import PyPDF2
import compress_qt as app
from pdf_core import watch_source_changes
from test_pdf_core import pdf_bytes


class SourceMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'export.pdf'
        self.stopped = threading.Event()
        self.events = queue.Queue()
        self.worker = None
        self.addCleanup(self.stop)

    def stop(self):
        self.stopped.set()
        if self.worker:
            self.worker.join(2)

    def start_and_wait_for_baseline(self):
        baseline = threading.Event()
        reader = PyPDF2.PdfReader
        def observed(*args, **kwargs):
            pdf = reader(*args, **kwargs)
            len(pdf.pages)
            baseline.set()
            return pdf
        with patch('pdf_core.PyPDF2.PdfReader', side_effect=observed):
            self.worker = threading.Thread(target=watch_source_changes,
                                           args=(self.path, self.stopped, self.events))
            self.worker.start()
            self.assertTrue(baseline.wait(2))
            time.sleep(0.05)

    def wait_for(self, field):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            event = self.events.get(timeout=3)
            if event[0] == field:
                return event
        self.fail(f'No {field} change detected')

    def test_unlocked_export_after_long_readable_pause_warns(self):
        self.path.write_bytes(pdf_bytes([0]))
        # No locking: the old snapshot check could accept this valid first page
        # during a pause, even though the exporter has more pages to write.
        with open(self.path, 'r+b') as exporter:
            self.start_and_wait_for_baseline()
            time.sleep(1.1)  # exceeds the previous 0.75-second quiet interval
            self.assertTrue(self.events.empty())
            exporter.seek(0)
            exporter.write(pdf_bytes([0] * 4))
            exporter.truncate()
            exporter.flush()
            size = self.wait_for('File size')
            self.assertGreater(size[2], size[1])
            self.assertEqual(self.wait_for('Page count'), ('Page count', 1, 4))

    def test_same_size_revision_still_detects_page_count_change(self):
        first, last = pdf_bytes([0]), pdf_bytes([0] * 3)
        padding = b'%' + b'x' * (len(last) - len(first) - 2) + b'\n'
        first = first.replace(b'startxref\n', padding + b'startxref\n')
        self.assertEqual(len(first), len(last))
        self.path.write_bytes(first)
        self.start_and_wait_for_baseline()
        self.path.write_bytes(last)
        self.assertEqual(self.wait_for('Page count'), ('Page count', 1, 3))

    def test_temporarily_missing_cloud_file_recovers(self):
        self.path.write_bytes(pdf_bytes([0] * 2))
        self.start_and_wait_for_baseline()
        self.path.unlink()
        time.sleep(0.65)
        self.assertTrue(self.worker.is_alive())
        self.path.write_bytes(pdf_bytes([0] * 5))
        self.assertEqual(self.wait_for('Page count'), ('Page count', 2, 5))

    def test_unchanged_file_is_not_reparsed(self):
        self.path.write_bytes(pdf_bytes([0]))
        self.start_and_wait_for_baseline()
        with patch('pdf_core.PyPDF2.PdfReader') as reader:
            time.sleep(1.1)
            reader.assert_not_called()
        self.assertTrue(self.events.empty())

    def test_warning_is_nonmodal_and_not_repeated(self):
        qt = QApplication.instance() or QApplication([])
        with patch('compress_qt.watch_source_changes'):
            monitor = app.SourceChangeMonitor(str(self.path), qt)
            self.addCleanup(monitor.stop)
            monitor.events.put(('File size', 100, 200))
            monitor.poll()
            warning = monitor.warning
            self.assertFalse(warning.isModal())
            self.assertIn('syncing', warning.text())
            monitor.events.put(('Page count', 1, 3))
            monitor.poll()
            self.assertIs(monitor.warning, warning)
            self.assertIn('1 → 3 pages', warning.informativeText())
            warning.accept()
            monitor.events.put(('Page count', 3, 4))
            monitor.poll()
            self.assertFalse(warning.isVisible())

    def test_slow_storage_does_not_block_start_or_stop(self):
        qt = QApplication.instance() or QApplication([])
        entered, release = threading.Event(), threading.Event()
        def slow_stat(_):
            entered.set()
            release.wait(3)
            raise OSError('temporarily unavailable')
        with patch('pdf_core.signature', side_effect=slow_stat):
            start = time.monotonic()
            monitor = app.SourceChangeMonitor(str(self.path), qt)
            try:
                self.assertLess(time.monotonic() - start, 0.2)
                self.assertTrue(entered.wait(1))
                start = time.monotonic()
                monitor.stop()
                self.assertLess(time.monotonic() - start, 0.2)
            finally:
                monitor.stop()
                release.set()
                monitor.worker.join(2)


if __name__ == '__main__':
    unittest.main()
