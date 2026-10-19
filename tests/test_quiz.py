import unittest

from codevigrah import llm, quiz, tour
from codevigrah.analysis import analyze
from codevigrah.retrieval import Index
from helpers import TempDir, make_repo


class ParsingTests(unittest.TestCase):
    def test_extract_json_from_fenced_or_bare_text(self):
        self.assertEqual(quiz._extract_json('Sure!\n```json\n{"questions": []}\n```'), {'questions': []})
        self.assertEqual(quiz._extract_json('noise {"a": 1} noise'), {'a': 1})

    def test_clean_rejects_invalid_questions(self):
        valid = {'a.py', 'b.py'}
        mcq = {
            'type': 'mcq',
            'question': 'Q?',
            'choices': ['x', 'y'],
            'answer': 1,
            'skill': 'nonsense',
            'refs': ['a.py:3', 'zzz.py:1'],
        }
        out = quiz._clean(dict(mcq), 2, valid)
        self.assertEqual((out['level'], out['skill'], out['scope'], out['refs']), (2, 'structure', 'repo', ['a.py:3']))
        self.assertIsNone(quiz._clean(dict(mcq, answer=5), 1, valid))
        files = {'type': 'files', 'scenario': 'Add X', 'must': ['a.py', 'ghost.py'], 'maybe': ['a.py', 'b.py']}
        out = quiz._clean(files, 3, valid)
        self.assertEqual((out['must'], out['maybe']), (['a.py'], ['b.py']))
        self.assertIsNone(quiz._clean({'type': 'files', 'scenario': 'x', 'must': ['ghost.py']}, 1, valid))


class StaticModeTests(unittest.TestCase):
    """Without an AI provider, every feature still produces useful static output."""

    @classmethod
    def setUpClass(cls):
        llm.configure({'CODEVIGRAH_AI_PROVIDERS': 'off'})
        cls.tmp = TempDir()
        root = make_repo(cls.tmp.path / 'shop')
        meta = {'id': 'local__shop', 'name': 'shop', 'source': str(root), 'commit': 'c0ffee', 'root': str(root)}
        cls.a = analyze(str(root), meta, lambda m: None)
        cls.idx = Index(cls.a, str(root))
        cls.work = str(cls.tmp.path / 'ws')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_static_quiz_levels(self):
        for level in (1, 2, 3):
            res = quiz.get_level(self.a, self.idx, self.work, level)
            self.assertEqual(res['source'], 'static')
            ids = [q['id'] for q in res['questions']]
            self.assertEqual(len(ids), len(set(ids)))
            for q in res['questions']:
                if q['type'] == 'files':
                    self.assertTrue(set(q['must']) <= set(q['candidates']))
        self.assertEqual(quiz.fallback_level(self.a, self.idx, 1, 'down')['error'], 'down')

    def test_history_exercises_come_from_real_commits(self):
        ex = quiz.history_exercises(self.a, self.idx)
        self.assertIn('Add user creation with validation', [e['scenario'] for e in ex])

    def test_static_tour_chapters(self):
        for c in tour.CHAPTERS:
            res = tour.chapter(self.a, self.idx, c['key'], self.work)
            self.assertEqual(res['source'], 'static')
            self.assertTrue(res['markdown'].strip(), c['key'])
        with self.assertRaises(ValueError):
            tour.chapter(self.a, self.idx, 'nope', self.work)


if __name__ == '__main__':
    unittest.main()
