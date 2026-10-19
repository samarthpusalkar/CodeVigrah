import shutil
import unittest

from codevigrah.config import Settings
from codevigrah.service import analyze_source
from codevigrah.sources import SourceError, head_commit, normalise, repo_id_for, version_stamp
from codevigrah.workspace import Workspace, safe_id
from helpers import TempDir, make_repo


class NormaliseTests(unittest.TestCase):
    def test_accepts_common_forms(self):
        for given in (
            'pallets/click',
            'https://github.com/pallets/click',
            'https://github.com/pallets/click.git',
            'https://github.com/pallets/click/tree/main/src',
            'https://github.com/pallets/click/',
        ):
            self.assertEqual(normalise(given), 'https://github.com/pallets/click', given)

    def test_other_hosts(self):
        self.assertEqual(normalise('https://codeberg.org/forgejo/forgejo'), 'https://codeberg.org/forgejo/forgejo')

    def test_rejects_unsafe_or_unknown_sources(self):
        for bad in (
            '',
            'http://github.com/a/b',
            'git@github.com:a/b.git',
            'https://evil.example/a/b',
            'file:///etc',
            'https://github.com/a/b;rm -rf /',
            '--upload-pack=touch /tmp/x',
            'https://github.com/a',
        ):
            with self.assertRaises(SourceError, msg=bad):
                normalise(bad)

    def test_local_paths(self):
        tmp = TempDir()
        try:
            self.assertEqual(normalise(str(tmp.path) + '/'), str(tmp.path))
            with self.assertRaises(SourceError):
                normalise(str(tmp.path), allow_local=False)
            with self.assertRaises(SourceError):
                normalise(str(tmp.path / 'missing'))
        finally:
            tmp.cleanup()

    def test_repo_ids(self):
        self.assertEqual(repo_id_for('https://github.com/pallets/click'), 'pallets__click')
        rid = repo_id_for('/home/me/my project')
        self.assertTrue(rid.startswith('local__my_project_'))
        self.assertEqual(rid, safe_id(rid))


class WorkspaceTests(unittest.TestCase):
    def test_ids_cannot_escape(self):
        self.assertEqual(safe_id('owner__repo'), 'owner__repo')
        self.assertEqual(safe_id('../x'), 'x')  # only the last path component is ever used
        for bad in ('..', '.', '', 'a b', 'x;y'):
            self.assertEqual(safe_id(bad), '', bad)
        tmp = TempDir()
        try:
            ws = Workspace(tmp.path)
            with self.assertRaises(ValueError):
                ws.repo_dir('..')
            self.assertIsNone(ws.load_analysis('../../etc'))
        finally:
            tmp.cleanup()

    def test_save_and_load_round_trip(self):
        tmp = TempDir()
        try:
            ws = Workspace(tmp.path)
            a = {'meta': {'id': 'o__r', 'source': 'https://github.com/o/r', 'root': '/old/place/repo'}, 'files': []}
            ws.save_analysis('o__r', a)
            loaded = ws.load_analysis('o__r')
            self.assertEqual(loaded['meta']['root'], str(ws.clone_dir('o__r')))  # clone path re-derived
            self.assertEqual([x['id'] for x in ws.list()], ['o__r'])
            ws.save_analysis('local__x_123456', {'meta': {'source': '/x', 'root': '/x'}})
            self.assertEqual([x['id'] for x in ws.list(include_local=False)], ['o__r'])
        finally:
            tmp.cleanup()


class VersionStampTests(unittest.TestCase):
    """Cached AI output is keyed by this stamp, so it must change whenever the analysed code changes."""

    def setUp(self):
        self.tmp = TempDir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_without_git(self):
        repo = make_repo(self.tmp.path / 'shop')
        shutil.rmtree(repo / '.git')
        paths = ['app/service.py', 'README.md']
        first = version_stamp(repo, paths)
        self.assertTrue(first.startswith('snap-'))
        self.assertEqual(version_stamp(repo, paths), first)  # unchanged content, same stamp
        (repo / 'app/service.py').write_text('# changed\n')
        self.assertNotEqual(version_stamp(repo, paths), first)

    def test_git_checkout_clean_and_with_local_changes(self):
        repo = make_repo(self.tmp.path / 'shop')
        commit = head_commit(repo)
        self.assertEqual(version_stamp(repo, ['app/service.py']), commit)
        (repo / 'app/service.py').write_text('# work in progress\n')
        stamp = version_stamp(repo, ['app/service.py'])
        self.assertTrue(stamp.startswith(commit + '+'))

    def test_analysing_a_local_folder_uses_the_stamp(self):
        repo = make_repo(self.tmp.path / 'shop')
        shutil.rmtree(repo / '.git')
        settings = Settings(workspace=self.tmp.path / 'ws')
        ws = Workspace(settings.workspace)
        _, a = analyze_source(ws, settings, str(repo), log=lambda m: None)
        self.assertTrue(a['meta']['commit'].startswith('snap-'))
        self.assertIsNone(a['git'])


if __name__ == '__main__':
    unittest.main()
