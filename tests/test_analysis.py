import unittest

from codevigrah.analysis import analyze
from codevigrah.analysis.graph import pagerank, pct_rank, tarjan
from codevigrah.analysis.scan import role_of
from codevigrah.analysis.symbols import file_doc, py_symbols, readme_parts
from codevigrah.retrieval import Index, tokens
from helpers import TempDir, make_repo


class GraphTests(unittest.TestCase):
    def test_tarjan_finds_cycles(self):
        comps = [sorted(c) for c in tarjan(4, [(0, 1), (1, 2), (2, 0), (2, 3)]) if len(c) > 1]
        self.assertEqual(comps, [[0, 1, 2]])

    def test_pagerank_favours_imported_files(self):
        pr = pagerank(3, [(0, 2), (1, 2)])
        self.assertAlmostEqual(sum(pr), 1.0, places=6)
        self.assertGreater(pr[2], pr[0])

    def test_pct_rank_ties(self):
        self.assertEqual(pct_rank([5, 1, 5, 3]), [2 / 3, 0.0, 2 / 3, 1 / 3])


class FileLevelTests(unittest.TestCase):
    def test_roles(self):
        cases = {
            'tests/test_x.py': 'test',
            'app/routes.py': 'route',
            'app/models.py': 'model',
            'docs/intro.md': 'docs',
            '.github/workflows/ci.yml': 'ci',
            'src/components/Button.tsx': 'ui',
            'cmd/root.go': 'cli',
            'db/migrations/0001_init.sql': 'migration',
            'lib/utils.js': 'util',
        }
        for path, role in cases.items():
            lang = 'Python' if path.endswith('.py') else 'Go' if path.endswith('.go') else 'JavaScript'
            self.assertEqual(role_of(path, lang, ''), role, path)

    def test_python_symbols_and_doc(self):
        syms, cx = py_symbols('class A:\n    def run(self):\n        if x:\n            pass\n\ndef f():\n    pass\n')
        self.assertEqual([s[:2] for s in syms], [['A', 'class'], ['A.run', 'method'], ['f', 'function']])
        self.assertEqual(cx, 2)
        self.assertEqual(
            file_doc('"""Parses the config file. More here."""\n', 'Python'), 'Parses the config file. More here.'
        )
        self.assertEqual(file_doc('# Copyright 2024 Someone\n', 'Python'), '')

    def test_readme_parts(self):
        tag, usage = readme_parts(
            '# Title\n\n[![badge](x)](y)\n\nA tool that does one thing very well for everyone.\n\n```sh\nrun it\n```\n'
        )
        self.assertEqual(tag, 'A tool that does one thing very well for everyone.')
        self.assertEqual(usage, 'run it')

    def test_tokens(self):
        self.assertEqual(
            tokens('getUserById parse_configs'), ['user', 'id', 'parse', 'config']
        )  # 'get' and 'by' are stop words


class AnalyzeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TempDir()
        cls.root = make_repo(cls.tmp.path / 'shop')
        meta = {'id': 'local__shop', 'name': 'shop', 'source': str(cls.root), 'commit': 'test', 'root': str(cls.root)}
        cls.a = analyze(str(cls.root), meta, lambda m: None)
        cls.files = {f['path']: f for f in cls.a['files']}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_imports_resolve_across_languages(self):
        paths = [f['path'] for f in self.a['files']]
        edges = {(paths[a], paths[b]) for a, b in self.a['edges']}
        for edge in [
            ('app/main.py', 'app/routes.py'),
            ('app/main.py', 'app/service.py'),
            ('app/service.py', 'app/models.py'),
            ('app/routes.py', 'app/service.py'),
            ('tests/test_service.py', 'app/service.py'),
            ('web/index.js', 'web/util.js'),
        ]:
            self.assertIn(edge, edges)

    def test_entities_and_domain(self):
        routes = {(r['method'], r['path']) for r in self.a['entities']['routes']}
        self.assertEqual(routes, {('GET', '/users'), ('POST', '/users')})
        self.assertEqual({m['name'] for m in self.a['entities']['models'] if m['kind'] == 'table'}, {'User', 'Order'})
        self.assertEqual(self.a['domains'][0]['key'], 'backend')
        self.assertIn('FastAPI', self.a['frameworks'])
        self.assertIn('app/main.py', [e['path'] for e in self.a['entries']])

    def test_tests_and_history(self):
        self.assertEqual(self.files['app/service.py']['tests'], ['tests/test_service.py'])
        self.assertEqual(self.a['git']['commits'], 4)
        self.assertEqual(self.a['git']['authors_total'], 2)
        self.assertEqual(self.files['app/routes.py']['authors'], 1)

    def test_brief_and_probes(self):
        self.assertIn('Shop is a small demo service', self.a['brief'])
        self.assertIn('no-migrations', {p['id'] for p in self.a['probes'] if p['flagged']})

    def test_change_localisation(self):
        idx = Index(self.a, str(self.root))
        res = idx.locate('validate the user name when creating a user')
        self.assertEqual(res['primary'][0]['path'], 'app/service.py')
        self.assertIn('tests/test_service.py', res['tests'])
        text, sources = idx.llm_context('create user', ['app/models.py'])
        self.assertEqual(sources[0], 'app/models.py')
        self.assertIn('## Repo map', text)
        self.assertIsNone(idx.read('../../etc/passwd'))


if __name__ == '__main__':
    unittest.main()
