import os
import unittest
from unittest.mock import patch
from runtime_environment import clean_environment


class RuntimeEnvironmentTests(unittest.TestCase):
    def test_unrelated_toolchains_are_removed_but_desktop_session_is_preserved(self):
        env = dict(PYTHONHOME='other', PYTHONPATH='other', QT_PLUGIN_PATH='other',
                   QT_QPA_PLATFORM_PLUGIN_PATH='other', GS_LIB='other', GS_OPTIONS='other',
                   DISPLAY=':0', WAYLAND_DISPLAY='wayland-0', QT_QPA_PLATFORM='wayland')
        with patch.dict(os.environ, env, clear=True), patch('sys.frozen', True, create=True):
            clean_environment()
            for name in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH',
                         'QT_QPA_PLATFORM_PLUGIN_PATH', 'GS_LIB', 'GS_OPTIONS', 'QT_QPA_PLATFORM'):
                self.assertNotIn(name, os.environ)
            self.assertEqual(os.environ['DISPLAY'], ':0')
            self.assertEqual(os.environ['WAYLAND_DISPLAY'], 'wayland-0')

    def test_self_test_is_headless(self):
        with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['app', '--self-test']):
            clean_environment()
            self.assertEqual(os.environ['QT_QPA_PLATFORM'], 'offscreen')
