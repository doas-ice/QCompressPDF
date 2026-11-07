"""PDF and filesystem invariants shared by the UI and background workers."""
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

import PyPDF2


def version_tuple(version):
    match = re.fullmatch(r'[vV]?(\d+)\.(\d+)\.(\d+)', version)
    return tuple(map(int, match.groups())) if match else (0, 0, 0)


def safe_stem(text, directory='', editing=False):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '', text)
    if not editing:
        text = text.strip().rstrip('. ')
    if text.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$',
                                      *(f'COM{i}' for i in (*range(1, 10), '¹', '²', '³')),
                                      *(f'LPT{i}' for i in (*range(1, 10), '¹', '²', '³'))}:
        text = '_' + text
    # Reserve enough for .pdf, split suffixes and destination temporary names.
    budget = 180
    if os.name == 'nt':
        budget = min(budget, 235 - len(os.path.abspath(directory or '.')) - 20)
    text = text.encode('utf-8')[:max(0, budget)].decode('utf-8', errors='ignore')
    return text if editing else text.rstrip('. ')



def output_path(directory, stem, suffix=''):
    directory = Path(directory).expanduser().absolute()
    if not directory.is_dir():
        raise ValueError('Choose an existing output directory.')
    clean = safe_stem(stem, directory)
    if not clean:
        raise ValueError('Enter a filename; the directory path may also be too long.')
    path = directory / (clean + suffix + '.pdf')
    if os.name == 'nt' and len(str(path).encode('utf-16-le')) // 2 >= 250:
        raise ValueError('Output path is too long. Choose a shorter directory.')
    return str(path)


def signature(path):
    s = os.stat(path)
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def assert_unchanged(path, expected):
    if signature(path) != expected:
        raise ValueError('The source PDF changed while being processed. Wait for export to finish and retry.')


def has_eof(path):
    with open(path, 'rb') as stream:
        stream.seek(max(0, os.fstat(stream.fileno()).st_size - 1024))
        return stream.read().rstrip().endswith(b'%%EOF')


def watch_source_changes(path, stopped, events):
    """Observe unlocked exports/copies/syncs without interpreting quiet as done.

    All IO, including stat and PDF parsing, belongs on the caller's worker thread.
    Only reparse when metadata changes (or the previous parse was incomplete).
    An unreadable intermediate revision does not erase the last valid page count.
    """
    previous_size = None
    previous_pages = None
    parsed_signature = None
    while not stopped.is_set():
        try:
            current = signature(path)
            size = current[2]
            if previous_size is not None and size != previous_size:
                events.put(('File size', previous_size, size))
            previous_size = size
            if current != parsed_signature:
                with open(path, 'rb') as stream:
                    pages = len(PyPDF2.PdfReader(stream).pages)
                # Never use a count obtained across concurrent revisions.
                if signature(path) == current:
                    if previous_pages is not None and pages != previous_pages:
                        events.put(('Page count', previous_pages, pages))
                    previous_pages = pages
                    parsed_signature = current
        except (OSError, ValueError, PyPDF2.errors.PdfReadError, KeyError, IndexError, TypeError, AttributeError):
            # Exporters and sync clients can temporarily remove/replace the file
            # or leave it unparsable. Continue watching without a false zero count.
            pass
        if stopped.wait(0.5):
            break


def windows_writer_active(path):
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # FILE_SHARE_READ only: an already open writer causes sharing violation.
    handle = create(str(Path(path).absolute()), 0x80000000, 1, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        if error == 32:
            return True
        raise OSError(error, 'Cannot open the source PDF')
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle(handle)
    return False


def stable_snapshot(source, destination, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        before = signature(source)
        recent = time.time_ns() - before[3] < 2_000_000_000
        if not windows_writer_active(source):
            time.sleep(0.75 if recent else 0.1)
            if signature(source) == before and has_eof(source):
                shutil.copyfile(source, destination)
                if signature(source) == before and not windows_writer_active(source):
                    with open(destination, 'rb') as stream:
                        count = len(PyPDF2.PdfReader(stream).pages)
                    if count < 1:
                        raise ValueError('The PDF has no pages.')
                    return before, count
        time.sleep(0.1)
    raise ValueError('The PDF is still being written or has no complete EOF marker. Wait for export to finish and retry.')


def atomic_copy(source, destination):
    """Do not truncate an existing destination when copy/validation fails."""
    fd, temporary = tempfile.mkstemp(prefix='.qcompress-', suffix='.pdf', dir=Path(destination).parent)
    try:
        with os.fdopen(fd, 'wb') as out, open(source, 'rb') as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def gs_command(executable, source, destination, dpi):
    return [executable, '-dSAFER', '-dNOPAUSE', '-dBATCH', '-sDEVICE=pdfwrite',
            '-dCompatibilityLevel=1.7', f'-sOutputFile={destination}',
            '-dDownsampleColorImages=true', f'-dColorImageResolution={dpi}',
            '-dColorImageDownsampleType=/Bicubic', '-dColorImageDownsampleThreshold=1.0',
            '-dDownsampleGrayImages=true', f'-dGrayImageResolution={dpi}',
            '-dGrayImageDownsampleType=/Bicubic', '-dGrayImageDownsampleThreshold=1.0',
            '-dDownsampleMonoImages=true', f'-dMonoImageResolution={dpi}',
            '-dMonoImageFilter=/CCITTFaxEncode', '-dDetectDuplicateImages=true',
            '-dCompressFonts=true', '-dCompressStreams=true', source]


def write_range(reader, start, end, stream):
    writer = PyPDF2.PdfWriter()
    for index in range(start, end):
        writer.add_page(reader.pages[index])
    writer.write(stream)


def plan_split(reader, mode, limit_bytes=5 * 1024 * 1024, parts=2):
    """Measure serialized ranges including shared resources; never omit a page.

    Size mode uses bounded binary search for a fitting contiguous range. Number
    mode balances normalized byte and page-count errors at adjacent boundaries.
    Neither page weights nor equal-page assumptions determine the final sizes.
    """
    count = len(reader.pages)
    if count < 2:
        raise ValueError('At least two pages are needed to split a PDF.')
    cache = {}

    def size(start, end):
        key = start, end
        if key not in cache:
            with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as stream:
                write_range(reader, start, end, stream)
                cache[key] = stream.tell()
        return cache[key]

    if mode in ('size', 'auto'):
        ranges = []
        start = 0
        while start < count:
            if size(start, start + 1) > limit_bytes:
                raise ValueError(f'Page {start + 1} alone exceeds the size limit. Lower DPI or raise the limit.')
            low, high = start + 1, count
            while low < high:
                middle = (low + high + 1) // 2
                if size(start, middle) <= limit_bytes:
                    low = middle
                else:
                    high = middle - 1
            ranges.append((start, low))
            start = low
        return ranges
    if mode != 'number' or not 2 <= parts <= count:
        raise ValueError(f'Choose between 2 and {count} parts.')
    boundaries = [i * count // parts for i in range(parts + 1)]
    for _ in range(3):
        changed = False
        for i in range(1, parts):
            start, old, end = boundaries[i-1:i+2]

            def score(mid):
                left, right = size(start, mid), size(mid, end)
                byte_error = (left - right) / max(left + right, 1)
                page_error = (2 * mid - start - end) / (end - start)
                return byte_error ** 2 + page_error ** 2

            low, high = start + 1, end - 1
            candidates = {old, low, high, (start + end) // 2}
            while low < high:
                mid = (low + high) // 2
                candidates.add(mid)
                left, right = size(start, mid), size(mid, end)
                imbalance = (left - right) / max(left + right, 1) + (2 * mid - start - end) / (end - start)
                if imbalance < 0:
                    low = mid + 1
                else:
                    high = mid
            candidates.update((low, max(start + 1, low - 1)))
            candidates.update(b + offset for b in list(candidates) for offset in (-1, 1)
                              if start < b + offset < end)
            best = min(candidates, key=lambda b: (score(b), abs(b-old)))
            boundaries[i] = best
            changed |= best != old
        if not changed:
            break
    return list(zip(boundaries, boundaries[1:]))
