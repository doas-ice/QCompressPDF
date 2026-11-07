"""Keep unrelated Python/Qt/Ghostscript installations out of this app's runtime."""
import os
import sys


def clean_environment():
    # Set before importing Qt. Preserve display/session variables needed by KDE.
    for name in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH',
                 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH', 'QML_IMPORT_PATH',
                 'GS_LIB', 'GS_OPTIONS', 'GS_FONTPATH'):
        os.environ.pop(name, None)
    if getattr(sys, 'frozen', False):
        os.environ.pop('QT_QPA_PLATFORM', None)
    if '--self-test' in sys.argv:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'


def application_mutex():
    """Inno detects this mutex; never terminate an in-progress compression to update."""
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    create = ctypes.windll.kernel32.CreateMutexW
    create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    handle = create(None, False, 'QCompressPDF.App')
    if not handle:
        raise ctypes.WinError()
    # The OS closes the handle at process exit. Concurrent app instances remain allowed.
    return handle
