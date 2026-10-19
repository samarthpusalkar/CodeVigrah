import unittest
from pathlib import Path

from codevigrah.config import Settings, load_dotenv
from helpers import TempDir


class DotenvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TempDir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_parses_quotes_comments_and_export(self):
        p = self.tmp.path / '.env'
        p.write_text(
            '# comment\n\nA=1\nexport B="two words"\nC=\'x # not a comment\'\nD=plain # trailing comment\nnot a line\n'
        )
        env = {}
        loaded = load_dotenv(p, env)
        self.assertEqual(env, {'A': '1', 'B': 'two words', 'C': 'x # not a comment', 'D': 'plain'})
        self.assertEqual(loaded, ['A', 'B', 'C', 'D'])

    def test_existing_variables_win(self):
        p = self.tmp.path / '.env'
        p.write_text('A=from-file\n')
        env = {'A': 'from-env'}
        load_dotenv(p, env)
        self.assertEqual(env['A'], 'from-env')

    def test_missing_file_is_fine(self):
        self.assertEqual(load_dotenv(self.tmp.path / 'nope', {}), [])


class SettingsTests(unittest.TestCase):
    def test_defaults_are_private_and_local(self):
        s = Settings.from_env({})
        self.assertEqual((s.host, s.port, s.public), ('127.0.0.1', 8765, False))
        self.assertTrue(s.allow_local_paths)
        self.assertEqual((s.rate_ai_per_hour, s.rate_analyze_per_hour), (0, 0))

    def test_network_host_disables_local_paths_unless_allowed(self):
        self.assertFalse(Settings.from_env({'CODEVIGRAH_HOST': '0.0.0.0'}).allow_local_paths)
        self.assertTrue(
            Settings.from_env({'CODEVIGRAH_HOST': '0.0.0.0', 'CODEVIGRAH_ALLOW_LOCAL_PATHS': '1'}).allow_local_paths
        )

    def test_public_mode_forces_safe_defaults(self):
        s = Settings.from_env({'CODEVIGRAH_PUBLIC': 'true', 'CODEVIGRAH_ALLOW_LOCAL_PATHS': '1'})
        self.assertTrue(s.public)
        self.assertFalse(s.allow_local_paths)
        self.assertEqual((s.rate_ai_per_hour, s.rate_analyze_per_hour), (30, 10))

    def test_flags_override_environment(self):
        s = Settings.from_env({'CODEVIGRAH_PORT': '9000'}, port=9100, workspace=Path('/tmp/ws'), host=None)
        self.assertEqual(s.port, 9100)
        self.assertEqual(s.workspace, Path('/tmp/ws'))
        self.assertEqual(s.host, '127.0.0.1')

    def test_bad_number_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'CODEVIGRAH_PORT'):
            Settings.from_env({'CODEVIGRAH_PORT': 'eighty'})

    def test_allowed_hosts_are_normalised(self):
        s = Settings.from_env({'CODEVIGRAH_ALLOWED_HOSTS': 'CodeVigrah.Example.com, localhost'})
        self.assertEqual(s.allowed_hosts, ('codevigrah.example.com', 'localhost'))


if __name__ == '__main__':
    unittest.main()
