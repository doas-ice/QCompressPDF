import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import PyPDF2
import compress_qt as app
from pdf_core import estimate_page_indices, gs_command, signature, PdfEstimateHistory
from test_pdf_core import pdf_bytes


class EstimateTests(unittest.TestCase):
    def test_calibration_uses_nearest_dpi_and_unchanged_source_only(self):
        history = PdfEstimateHistory()
        history.record_sample((100, 'original'), 1000)
        history.record_actual((100, 'original'), 1500)
        history.record_sample((300, 'original'), 2000)
        history.record_actual((300, 'original'), 1600)
        self.assertEqual(history.correct((150, 'original'), 1200), (1800, True))
        self.assertEqual(history.correct((250, 'original'), 1500), (1200, True))
        self.assertEqual(history.correct((150, 'changed'), 1200), (1200, False))
        self.assertIsNone(history.actual_size((100, 'changed')))
        self.assertEqual(PdfEstimateHistory().correct((150, 'original'), 1200), (1200, False))

    def test_estimate_finishing_after_compression_can_still_calibrate(self):
        history = PdfEstimateHistory()
        key = (100, 'original')
        history.record_actual(key, 1500)
        self.assertEqual(history.actual_size(key), 1500)
        self.assertEqual(history.correct((150, 'original'), 1200), (1200, False))
        history.record_sample(key, 0)
        self.assertEqual(history.correct((150, 'original'), 1200), (1200, False))
        history.record_sample(key, 1000)
        self.assertEqual(history.correct((150, 'original'), 1200), (1800, True))

    def test_coverage_scales_is_bounded_and_includes_both_ends(self):
        previous = 0
        for pages in (1, 3, 7, 8, 12, 24, 25, 49, 50, 64, 100, 400, 1000, 10000):
            indices = estimate_page_indices(pages)
            self.assertEqual(indices, sorted(set(indices)))
            self.assertEqual(indices[0], 0)
            self.assertEqual(indices[-1], pages - 1)
            self.assertGreaterEqual(len(indices), previous)
            self.assertLessEqual(len(indices), min(pages, 32))
            if pages <= 8:
                self.assertEqual(indices, list(range(pages)))
            gaps = [b-a for a, b in zip(indices, indices[1:])]
            if gaps:
                self.assertLessEqual(max(gaps) - min(gaps), 1)
            previous = len(indices)
        self.assertEqual(len(estimate_page_indices(50)), 8)
        self.assertEqual(len(estimate_page_indices(100)), 10)
        self.assertEqual(len(estimate_page_indices(400)), 20)
        self.assertEqual(len(estimate_page_indices(1000)), 31)

    @unittest.skipUnless(shutil.which('gs') or os.name == 'nt', 'Ghostscript required')
    def test_full_document_estimate_matches_actual_small_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            source, actual = Path(directory)/'source.pdf', Path(directory)/'actual.pdf'
            source.write_bytes(pdf_bytes([30000, 0, 60000, 0, 10000], image=True))
            subprocess.run(gs_command(app.GS_EXECUTABLE, str(source), str(actual), 100),
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            results = queue.Queue()
            app.estimate_size(str(source), 100, (100, signature(source)), results)
            message = results.get()[1]
            self.assertIn('all 5 pages measured', message)
            number = float(re.search(r'≈ ([0-9.]+) MB', message)[1])
            expected = min(source.stat().st_size, actual.stat().st_size) / 1024**2
            self.assertAlmostEqual(number, expected, delta=0.0051)

    @unittest.skipUnless(shutil.which('gs') or os.name == 'nt', 'Ghostscript required')
    def test_spread_sample_beats_three_pages_on_mixed_document(self):
        with tempfile.TemporaryDirectory() as directory:
            source, actual = Path(directory)/'source.pdf', Path(directory)/'actual.pdf'
            # The old first/middle/last sample misses all raster content.
            source.write_bytes(pdf_bytes([0 if i in (0, 50, 99) else 30000 for i in range(100)], image=True))
            subprocess.run(gs_command(app.GS_EXECUTABLE, str(source), str(actual), 100),
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            results = queue.Queue()
            key = (100, signature(source))
            app.estimate_size(str(source), 100, key, results)
            improved = results.get()[1]
            self.assertIn('10 of 100', improved)
            history = PdfEstimateHistory()
            history.record_sample((150, key[1]), 2000)
            history.record_actual((150, key[1]), 1000)
            app.estimate_size(str(source), 100, key, results, history)
            adjusted = results.get()[1]
            self.assertIn('adjusted using this PDF', adjusted)
            self.assertAlmostEqual(float(re.search(r'≈ ([0-9.]+) MB', adjusted)[1]),
                                   float(re.search(r'≈ ([0-9.]+) MB', improved)[1]) / 2,
                                   delta=0.0076)
            old_sample, old_result = Path(directory)/'old.pdf', Path(directory)/'old-result.pdf'
            reader = PyPDF2.PdfReader(str(source))
            writer = PyPDF2.PdfWriter()
            for index in (0, 50, 99):
                writer.add_page(reader.pages[index])
            with open(old_sample, 'wb') as stream:
                writer.write(stream)
            subprocess.run(gs_command(app.GS_EXECUTABLE, str(old_sample), str(old_result), 100),
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            baseline = source.stat().st_size * min(1, old_result.stat().st_size / old_sample.stat().st_size) / 1024**2
            parse = lambda text: float(re.search(r'≈ ([0-9.]+) MB', text)[1])
            expected = min(source.stat().st_size, actual.stat().st_size) / 1024**2
            self.assertLess(abs(parse(improved)-expected), abs(baseline-expected))
            print(f'Estimation fixture: actual={expected:.3f} MB; old={baseline:.2f}; new={parse(improved):.2f}')

    @unittest.skipUnless(shutil.which('gs') or os.name == 'nt', 'Ghostscript required')
    def test_shared_image_and_fonts_do_not_scale_as_new_resources_per_page(self):
        with tempfile.TemporaryDirectory() as directory:
            source, actual = Path(directory)/'source.pdf', Path(directory)/'actual.pdf'
            source.write_bytes(pdf_bytes([30000]*200, shared=True, image=True))
            subprocess.run(gs_command(app.GS_EXECUTABLE, str(source), str(actual), 100),
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            results = queue.Queue()
            app.estimate_size(str(source), 100, (100, signature(source)), results)
            message = results.get()[1]
            estimate = float(re.search(r'≈ ([0-9.]+) MB', message)[1])
            expected = min(source.stat().st_size, actual.stat().st_size) / 1024**2
            self.assertAlmostEqual(estimate, expected, delta=0.01)

    def test_changed_source_is_not_reported_as_a_valid_estimate(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source.pdf'
            source.write_bytes(pdf_bytes([0]*3))
            key = (100, signature(source))
            source.write_bytes(pdf_bytes([0]*4))
            results = queue.Queue()
            with patch.object(app.subprocess, 'run') as run:
                app.estimate_size(str(source), 100, key, results)
            run.assert_not_called()
            self.assertIn('unavailable', results.get()[1])


if __name__ == '__main__':
    unittest.main()
