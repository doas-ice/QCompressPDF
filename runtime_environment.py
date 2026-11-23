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


def close_application_mutex(mutex):
    import ctypes
    from ctypes import wintypes

    close = ctypes.WinDLL('kernel32', use_last_error=True).CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    if not close(mutex):
        raise ctypes.WinError(ctypes.get_last_error())


def start_windows_installer(path):
    """Start setup outside the bundled DLL search path."""
    import ctypes
    from ctypes import wintypes
    import subprocess

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    kernel.SetDllDirectoryW.restype = wintypes.BOOL
    bundle = getattr(sys, '_MEIPASS', None)
    if bundle and not kernel.SetDllDirectoryW(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        subprocess.Popen([str(path)], cwd=str(path.parent))
    finally:
        if bundle:
            kernel.SetDllDirectoryW(bundle)
