import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import PyPDF2
from pdf_core import prepare_output_path, atomic_copy, _graphemes, _probe_filename
from test_pdf_core import pdf_bytes


class OutputNameTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / 'original.pdf'
        self.source.write_bytes(pdf_bytes([0, 0]))

    def test_valid_long_name_is_kept_and_saved_as_valid_pdf(self):
        # Both ASCII and Bangla names exceed the former 180-byte cap.
        for stem in ('a' * 190, 'বাংলা' * 13):
            desired = self.root / (stem + '.pdf')
            # Model the same destination's capabilities, not a presumed OS limit.
            try:
                _probe_filename(desired)
            except OSError as error:
                if error.errno == errno.ENAMETOOLONG or getattr(error, 'winerror', None) == 206:
                    continue  # Host's full path limit can be shorter on Windows CI.
                raise
            chosen = prepare_output_path(self.root, stem)
            self.assertEqual(chosen, str(desired))
            atomic_copy(self.source, chosen)
            self.assertEqual(len(PyPDF2.PdfReader(chosen).pages), 2)

    def test_rejected_name_is_middle_elided_with_split_suffix(self):
        stem = 'শুরু-' + 'শ্রেণিক্ষেত্রবাংলা' * 80 + '-শেষ'
        chosen = prepare_output_path(self.root, stem, '_part100')
        name = Path(chosen).name
        self.assertIn('…', name)
        self.assertTrue(name.startswith('শুরু-'))
        self.assertTrue(name.endswith('-শেষ_part100.pdf'))
        self.assertFalse(Path(chosen).exists())  # probes leave no output behind
        self.assertEqual(list(self.root.iterdir()), [self.source])
        atomic_copy(self.source, chosen)
        self.assertEqual(len(PyPDF2.PdfReader(chosen).pages), 2)

    def test_graphemes_preserve_bangla_conjuncts_and_emoji(self):
        self.assertEqual(_graphemes('ক্ষ'), ['ক্ষ'])
        self.assertEqual(_graphemes('কি'), ['কি'])
        self.assertEqual(_graphemes('👩🏽\u200d🏫'), ['👩🏽\u200d🏫'])
        unit = 'ক্ষি'
        stem = unit * 120
        result = Path(prepare_output_path(self.root, stem)).stem
        prefix, suffix = result.split('…')
        self.assertEqual(prefix, unit * (len(prefix) // len(unit)))
        self.assertEqual(suffix, unit * (len(suffix) // len(unit)))

    def test_existing_full_and_clipped_files_are_never_changed_by_probe(self):
        existing = self.root / 'existing.pdf'
        existing.write_bytes(b'keep this file')
        self.assertEqual(prepare_output_path(self.root, 'existing'), str(existing))
        self.assertEqual(existing.read_bytes(), b'keep this file')
        stem = 'begin-' + 'x' * 1000 + '-end'
        clipped = Path(prepare_output_path(self.root, stem))
        clipped.write_bytes(b'keep the clipped collision too')
        self.assertEqual(prepare_output_path(self.root, stem), str(clipped))
        self.assertEqual(clipped.read_bytes(), b'keep the clipped collision too')

    def test_only_length_errors_trigger_shortening(self):
        for error in (PermissionError(errno.EACCES, 'permission denied'),
                      OSError(errno.ENOSPC, 'disk full'), OSError(errno.EIO, 'I/O error')):
            with patch('pdf_core._probe_filename', side_effect=error) as probe:
                with self.assertRaises(OSError):
                    prepare_output_path(self.root, 'x' * 1000)
                self.assertEqual(probe.call_count, 1)

    def test_windows_crt_error_requires_native_length_confirmation(self):
        length_error = OSError(errno.ENOENT, 'filename too long')
        length_error.winerror = 206
        for code in (errno.EINVAL, errno.ENOENT):
            original = OSError(code, 'ambiguous CRT error')
            with patch('pdf_core.os.name', 'nt'), \
                 patch('pdf_core.os.open', side_effect=original), \
                 patch('pdf_core.os.stat', side_effect=length_error):
                with self.assertRaises(OSError) as caught:
                    _probe_filename('long.pdf')
                self.assertIs(caught.exception, length_error)
            for native_error in (FileNotFoundError(), PermissionError()):
                with patch('pdf_core.os.name', 'nt'), \
                     patch('pdf_core.os.open', side_effect=original), \
                     patch('pdf_core.os.stat', side_effect=native_error):
                    with self.assertRaises(OSError) as caught:
                        _probe_filename('invalid.pdf')
                    self.assertIs(caught.exception, original)

    def test_limits_come_from_the_destination_not_a_fixed_byte_cap(self):
        attempts = []
        def destination(path):
            attempts.append(Path(path).name)
            # Simulate an FS with a 70-byte component limit.
            if len(Path(path).name.encode('utf-8')) > 70:
                raise OSError(errno.ENAMETOOLONG, 'name too long')
        stem = 'start-' + 'বাংলা' * 20 + '-end'
        with patch('pdf_core._probe_filename', side_effect=destination):
            result = Path(prepare_output_path(self.root, stem, '_part2')).name
        self.assertEqual(attempts[0], stem + '_part2.pdf')
        self.assertLessEqual(len(result.encode('utf-8')), 70)
        self.assertTrue(result.startswith('start-'))
        self.assertTrue(result.endswith('-end_part2.pdf'))
        with patch('pdf_core._probe_filename'):
            self.assertEqual(Path(prepare_output_path(self.root, stem)).stem, stem)

    def test_unshortenable_directory_reports_an_error(self):
        with patch('pdf_core._probe_filename', side_effect=OSError(errno.ENAMETOOLONG, 'path too long')):
            with self.assertRaisesRegex(ValueError, 'shorter directory'):
                prepare_output_path(self.root, 'test filename')


if __name__ == '__main__':
    unittest.main()
