import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import PyPDF2
from PyPDF2.generic import (NameObject, DictionaryObject, DecodedStreamObject,
                           NumberObject)
from pdf_core import (safe_stem, output_path, stable_snapshot, signature,
                      assert_unchanged, atomic_copy, plan_split, write_range, version_tuple)


def pdf_bytes(weights, shared=False, image=False):
    writer = PyPDF2.PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica')}))
    shared_ref = None
    for i, weight in enumerate(weights):
        writer.add_blank_page(width=300, height=300)
        page = writer.pages[-1]
        resources = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        if weight:
            obj = DecodedStreamObject()
            obj.set_data(bytes((x * 17 + i) % 256 for x in range(weight)))
            obj.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                        NameObject('/Width'): NumberObject(weight), NameObject('/Height'): NumberObject(1),
                        NameObject('/ColorSpace'): NameObject('/DeviceGray'), NameObject('/BitsPerComponent'): NumberObject(8)})
            ref = shared_ref if shared and shared_ref else writer._add_object(obj)
            shared_ref = ref
            resources[NameObject('/XObject')] = DictionaryObject({NameObject('/Im1'): ref})
        page[NameObject('/Resources')] = resources
        contents = DecodedStreamObject()
        contents.set_data((('q 300 0 0 300 0 0 cm /Im1 Do Q\n' if image and weight else '') +
                           f'BT /F1 12 Tf 10 20 Td (Page {i+1}) Tj ET').encode())
        page[NameObject('/Contents')] = writer._add_object(contents)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class CoreTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(safe_stem('a<>:"/\\|?*\x00b. '), 'ab')
        self.assertEqual(safe_stem('CON'), '_CON')
        self.assertEqual(safe_stem('LPT1.notes'), '_LPT1.notes')
        self.assertEqual(safe_stem('বাংলা'), 'বাংলা')
        self.assertLessEqual(len(safe_stem('😀' * 1000).encode()), 180)
        self.assertEqual(safe_stem('...'), '')

    def test_output_directory_and_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            path = output_path(folder, 'a' * 400, '_part100')
            self.assertEqual(Path(path).parent, Path(folder))
            self.assertTrue(path.endswith('_part100.pdf'))
            self.assertLess(len(Path(path).name.encode()), 255)
            with self.assertRaises(ValueError):
                output_path(folder, '')
            with self.assertRaises(ValueError):
                output_path(Path(folder) / 'absent', 'name')

    def test_numeric_versions(self):
        self.assertGreater(version_tuple('v1.10.0'), version_tuple('1.9.9'))
        self.assertLess(version_tuple('1.4.0-beta'), version_tuple('1.4.0'))

    def test_stable_snapshot_and_later_change(self):
        with tempfile.TemporaryDirectory() as folder:
            src, dst = Path(folder)/'source.pdf', Path(folder)/'copy.pdf'
            src.write_bytes(pdf_bytes([0, 0, 0]))
            os.utime(src, (time.time()-10, time.time()-10))
            started = time.monotonic()
            stamp, pages = stable_snapshot(src, dst)
            self.assertLess(time.monotonic()-started, 0.6)
            self.assertEqual(pages, 3)
            self.assertEqual(src.read_bytes(), dst.read_bytes())
            src.write_bytes(pdf_bytes([0]*4))
            with self.assertRaisesRegex(ValueError, 'changed'):
                assert_unchanged(src, stamp)

    def test_incomplete_export_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            src, dst = Path(folder)/'source.pdf', Path(folder)/'copy.pdf'
            src.write_bytes(pdf_bytes([0])[:-6])
            os.utime(src, (time.time()-10, time.time()-10))
            with self.assertRaisesRegex(ValueError, 'still being written'):
                stable_snapshot(src, dst, timeout=0.25)
            self.assertFalse(dst.exists())

    def test_appending_export_waits_for_final_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            src, dst = Path(folder)/'source.pdf', Path(folder)/'copy.pdf'
            src.write_bytes(pdf_bytes([0]))
            def finish():
                time.sleep(0.15)
                src.write_bytes(pdf_bytes([0]*5))
            thread = threading.Thread(target=finish)
            thread.start()
            _, count = stable_snapshot(src, dst)
            thread.join()
            self.assertEqual(count, 5)

    def test_atomic_copy_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            src, dst = Path(folder)/'a.pdf', Path(folder)/'b.pdf'
            src.write_bytes(b'new')
            dst.write_bytes(b'old')
            with patch('pdf_core.shutil.copyfileobj', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    atomic_copy(src, dst)
            self.assertEqual(dst.read_bytes(), b'old')
            self.assertEqual(len(list(Path(folder).iterdir())), 2)
            atomic_copy(src, dst)
            self.assertEqual(dst.read_bytes(), b'new')

    def test_shared_resources_use_serialized_range_size(self):
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes([10000]*6, shared=True)))
        ranges = plan_split(reader, 'size', 15000)
        self.assertEqual(ranges, [(0, 6)])  # 6 standalone pages would exceed 60 KB

    def test_size_limits_page_order_and_oversize_page(self):
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes([800, 7000, 600, 600, 7000, 700])))
        ranges = plan_split(reader, 'size', 10500)
        restored = []
        for start, end in ranges:
            out = io.BytesIO()
            write_range(reader, start, end, out)
            self.assertLessEqual(len(out.getvalue()), 10500)
            pages = PyPDF2.PdfReader(out).pages
            restored.extend(p.extract_text() for p in pages)
        self.assertEqual(restored, [f'Page {i}' for i in range(1, 7)])
        with self.assertRaisesRegex(ValueError, 'Page 2 alone'):
            plan_split(reader, 'size', 3000)

    def test_number_balances_bytes_and_pages(self):
        reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes([12000, 12000] + [500]*8)))
        ranges = plan_split(reader, 'number', parts=2)
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], 10)
        self.assertEqual(ranges[0][1], ranges[1][0])
        self.assertGreater(ranges[0][1], 1)  # considers page counts, not only bytes
        self.assertLess(ranges[0][1], 5)  # considers bytes, not only page counts
        equal = PyPDF2.PdfReader(io.BytesIO(pdf_bytes([500]*8)))
        self.assertEqual(plan_split(equal, 'number', parts=2), [(0, 4), (4, 8)])
        with self.assertRaises(ValueError):
            plan_split(equal, 'number', parts=9)


if __name__ == '__main__':
    unittest.main()
