"""Exercise the actual shell transaction; replace expensive dependency commands."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix' and shutil.which('flock'), 'Linux installer')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.bin = self.base/'bin'
        self.bin.mkdir()
        self.data = self.base/'data with spaces % $'
        self.env = dict(os.environ, XDG_DATA_HOME=str(self.data),
                        PATH=str(self.bin)+os.pathsep+os.environ['PATH'])
        self.python = self.bin/'python3'
        self.python.write_text('''#!/bin/bash
set -eu
if [[ "$1" == '-c' ]]; then exit 0; fi
if [[ "$1" != '-m' || "$2" != 'venv' ]]; then exit 9; fi
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'PYTHON'
#!/bin/bash
if [[ "$1" == '-m' ]]; then exit "${FAIL_PIP:-0}"; fi
exit "${FAIL_SMOKE:-0}"
PYTHON
chmod +x "$3/bin/python"
''')
        self.python.chmod(0o755)
        gs = self.bin/'gs'
        gs.write_text('#!/bin/bash\nexit 0\n')
        gs.chmod(0o755)
        self.install = self.data/'qcompresspdf'
        self.menu = self.data/'kio/servicemenus/qcompresspdf.desktop'

    def run_install(self, *args, **env):
        return subprocess.run(['bash', str(ROOT/'install_kde_service.sh'), *args],
                              cwd=self.base, env=dict(self.env, **env), capture_output=True,
                              text=True, timeout=15)

    def test_fresh_install_update_and_dependency_failure(self):
        first = self.run_install()
        self.assertEqual(first.returncode, 0, first.stderr)
        old = (self.install/'current').resolve()
        self.assertTrue((old/'pdf_core.py').exists())
        menu = self.menu.read_bytes()
        self.assertIn(b'%%', menu)
        self.assertIn(b'%f', menu)
        failed = self.run_install(FAIL_PIP='1')
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual((self.install/'current').resolve(), old)
        self.assertEqual(self.menu.read_bytes(), menu)
        self.assertEqual(len(list((self.install/'releases').iterdir())), 1)
        updated = self.run_install()
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertNotEqual((self.install/'current').resolve(), old)
        self.assertTrue(old.exists())

    def test_failed_smoke_test_preserves_legacy_install(self):
        self.install.mkdir(parents=True)
        legacy = self.install/'compress_qt.py'
        legacy.write_text('old working app')
        failed = self.run_install(FAIL_SMOKE='1')
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(legacy.read_text(), 'old working app')
        self.assertFalse((self.install/'current').exists())
        self.assertFalse(self.menu.exists())

    def test_menu_commit_failure_rolls_back_current(self):
        self.assertEqual(self.run_install().returncode, 0)
        previous = (self.install/'current').resolve()
        menu = self.menu.read_bytes()
        mv = self.bin/'mv'
        mv.write_text('''#!/bin/bash
case "${!#}" in *qcompresspdf.desktop) exit 1;; esac
exec /usr/bin/mv "$@"
''')
        mv.chmod(0o755)
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertEqual((self.install/'current').resolve(), previous)
        self.assertEqual(self.menu.read_bytes(), menu)

    def test_interrupt_during_commit_restores_previous_release(self):
        self.assertEqual(self.run_install().returncode, 0)
        previous = (self.install/'current').resolve()
        menu = self.menu.read_bytes()
        mv = self.bin/'mv'
        mv.write_text('''#!/bin/bash
/usr/bin/mv "$@" || exit $?
case "${!#}" in
  */current)
    if [[ ! -f "$XDG_DATA_HOME/interrupted" ]]; then
      touch "$XDG_DATA_HOME/interrupted"
      kill -TERM "$PPID"
    fi;;
esac
''')
        mv.chmod(0o755)
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertEqual((self.install/'current').resolve(), previous)
        self.assertEqual(self.menu.read_bytes(), menu)
        self.assertEqual(len(list((self.install/'releases').iterdir())), 1)

    def test_concurrent_install_fails_fast(self):
        import fcntl
        self.data.mkdir()
        with open(self.data/'.qcompresspdf-install.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Another', result.stderr)
        self.assertFalse(self.install.exists())

    def test_uninstall_does_not_require_python(self):
        self.assertEqual(self.run_install().returncode, 0)
        self.python.write_text('#!/bin/bash\nexit 99\n')
        self.assertEqual(self.run_install('uninstall').returncode, 0)
        self.assertFalse(self.install.exists())
        self.assertFalse(self.menu.exists())


if __name__ == '__main__':
    unittest.main()
