"""End-to-end tests: a real server on a free port, talking HTTP."""

import json
import logging
import os
import threading
import time
import unittest
import urllib.error
import urllib.request

from codevigrah import llm
from codevigrah.config import Settings
from codevigrah.web import Server
from helpers import StubOpenAI, TempDir, make_repo


class ServerCase(unittest.TestCase):
    public = False
    ai_env: dict = {'CODEVIGRAH_AI_PROVIDERS': 'off'}
    extra: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.tmp = TempDir()
        cls.repo = make_repo(cls.tmp.path / 'shop')
        llm.configure(cls.ai_env, public=cls.public)
        settings = Settings(
            port=0, workspace=cls.tmp.path / 'ws', public=cls.public, allow_local_paths=not cls.public, **cls.extra
        )
        cls.srv = Server(settings)
        cls.base = f'http://127.0.0.1:{cls.srv.server_address[1]}'
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, method, path, body=None, headers=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        h = {'Content-Type': 'application/json'} if body is not None else {}
        h.update(headers or {})
        req = urllib.request.Request(cls.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
                return r.status, (payload if raw else json.loads(payload)), r.headers
        except urllib.error.HTTPError as e:
            payload = e.read()
            e.close()
            return e.code, (payload if raw else json.loads(payload)), e.headers

    @classmethod
    def analyse(cls, source):
        code, res, _ = cls.call('POST', '/api/analyze', {'source': source})
        if code != 200:
            raise AssertionError(res)
        for _ in range(300):
            _, job, _ = cls.call('GET', f'/api/job?id={res["job"]}')
            if job['status'] in ('done', 'error'):
                if job['status'] != 'done':
                    raise AssertionError(job)
                return job['repo']
            time.sleep(0.1)
        raise AssertionError('analysis did not finish')


class PrivateServerTests(ServerCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rid = cls.analyse(str(cls.repo))

    def test_static_files_and_headers(self):
        code, body, headers = self.call('GET', '/', raw=True)
        self.assertEqual(code, 200)
        self.assertIn(b'/static/js/main.js', body)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.call('GET', '/static/js/core.js', raw=True)[0], 200)
        for bad in ('/static/../server.py', '/static/../../config.py', '/static/js/../../api.py', '/static/nope.js'):
            self.assertEqual(self.call('GET', bad, raw=True)[0], 404, bad)

    def test_analysis_endpoints(self):
        self.assertEqual(self.call('GET', '/api/health')[1]['ok'], True)
        self.assertIn(self.rid, [r['id'] for r in self.call('GET', '/api/repos')[1]])
        code, a, _ = self.call('GET', f'/api/analysis?id={self.rid}')
        self.assertEqual(code, 200)
        self.assertNotIn('root', a['meta'])  # server paths are never sent to the browser
        self.assertEqual(self.call('GET', f'/api/file?id={self.rid}&path=app/service.py')[1]['text'][:3], '"""')
        self.assertEqual(
            self.call('GET', f'/api/file?id={self.rid}&path=../../../../etc/passwd')[1]['text'], '(unreadable)'
        )
        self.assertEqual(self.call('GET', '/api/analysis?id=..')[0], 404)

    def test_old_analyses_are_upgraded(self):
        path = self.srv.app.ws.analysis_path(self.rid)
        a = json.loads(path.read_text())
        del a['meta']['schema']
        for f in a['files']:
            f.pop('doc', None)
        path.write_text(json.dumps(a))
        with self.srv.app._lock:
            self.srv.app._repos.clear()
        upgraded = self.call('GET', f'/api/analysis?id={self.rid}')[1]
        self.assertIn('schema', upgraded['meta'])
        self.assertIn('doc', upgraded['files'][0])
        self.assertEqual(self.call('POST', '/api/tour', {'id': self.rid, 'chapter': 'what'})[0], 200)

    def test_static_features_without_ai(self):
        body = {'id': self.rid}
        tour = self.call('POST', '/api/tour', body | {'chapter': 'what'})[1]
        self.assertEqual(tour['source'], 'static')
        self.assertEqual(len(tour['chapters']), 6)
        self.assertEqual(self.call('POST', '/api/tour', body | {'chapter': 'nope'})[0], 400)
        self.assertEqual(self.call('POST', '/api/quiz', body | {'level': 1})[1]['source'], 'static')
        self.assertEqual(self.call('POST', '/api/quiz', body | {'level': 'x'})[0], 400)
        plan = self.call('POST', '/api/locate', body | {'issue': 'validate user name on create', 'ai': True})[1]
        self.assertEqual(plan['primary'][0]['path'], 'app/service.py')
        self.assertIn(
            'app/main.py', self.call('POST', '/api/explain', body | {'path': 'app/service.py'})[1]['imported_by']
        )
        chat = self.call(
            'POST', '/api/chat', body | {'messages': [{'role': 'user', 'content': 'where are users created?'}]}
        )[1]
        self.assertIn('static retrieval', chat['answer'])
        self.assertIn('# shop: codebase report', self.call('POST', '/api/report', body)[1]['markdown'])

    def test_request_validation_and_csrf(self):
        self.assertEqual(self.call('GET', '/api/nope')[0], 404)
        self.assertEqual(self.call('GET', '/api/chat')[0], 405)
        req = urllib.request.Request(
            self.base + '/api/settings', data=b'{"order": "off"}', method='POST', headers={'Content-Type': 'text/plain'}
        )
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        cm.exception.close()
        self.assertEqual(cm.exception.code, 415)  # a cross-site <form> cannot send JSON
        self.assertEqual(
            self.call('POST', '/api/settings', {'order': 'off'}, {'Origin': 'https://evil.example'})[0], 403
        )
        self.assertEqual(self.call('POST', '/api/settings', {'order': 'off'}, {'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.call('GET', '/api/health', headers={'Host': 'rebind.evil.example:8765'})[0], 421)
        self.assertEqual(self.call('POST', '/api/analyze', {'source': 'https://evil.example/a/b'})[0], 400)

    def test_settings_dialog(self):
        code, s, _ = self.call('POST', '/api/settings', {'provider': 'ollama', 'model': 'llama3', 'order': 'ollama'})
        self.assertEqual(code, 200)
        self.assertEqual(s['order'], 'ollama')
        self.assertFalse(s['locked'])
        self.assertEqual(self.call('POST', '/api/settings', {'order': 'gpt9'})[0], 400)
        self.call('POST', '/api/settings', {'order': 'off'})


class PublicServerTests(ServerCase):
    public = True
    extra = {'rate_analyze_per_hour': 2}

    @classmethod
    def setUpClass(cls):
        cls._git_env = os.environ.get('GIT_ALLOW_PROTOCOL')
        os.environ['GIT_ALLOW_PROTOCOL'] = (
            'file'  # clones started by these tests fail at once instead of using the network
        )
        logging.getLogger('codevigrah').setLevel(logging.ERROR)  # those failures are expected
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls._git_env is None:
            os.environ.pop('GIT_ALLOW_PROTOCOL', None)
        else:
            os.environ['GIT_ALLOW_PROTOCOL'] = cls._git_env

    def test_settings_are_locked(self):
        self.assertTrue(self.call('GET', '/api/settings')[1]['locked'])
        self.assertEqual(self.call('POST', '/api/settings', {'order': 'off'})[0], 403)

    def test_local_paths_are_refused(self):
        code, res, _ = self.call('POST', '/api/analyze', {'source': str(self.repo)})
        self.assertEqual(code, 400)
        self.assertIn('Local folders', res['error'])

    def test_rate_limit(self):
        codes = [
            self.call('POST', '/api/analyze', {'source': 'https://github.com/o/does-not-exist-codevigrah-test'})[0]
            for _ in range(3)
        ]
        self.assertEqual(codes[:2], [200, 200])
        self.assertEqual(codes[2], 429)


class AIServerTests(ServerCase):
    """The AI paths, against a local stub of an OpenAI-compatible server (no real model, no cost)."""

    @classmethod
    def setUpClass(cls):
        cls.stub = StubOpenAI(answer='## From the stub\nSee `app/service.py`.')
        cls.ai_env = {
            'CODEVIGRAH_AI_PROVIDERS': 'openai',
            'CODEVIGRAH_OPENAI_BASE_URL': cls.stub.url,
            'CODEVIGRAH_OPENAI_MODEL': 'stub',
        }
        super().setUpClass()
        cls.rid = cls.analyse(str(cls.repo))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.stub.close()

    def test_chat_tour_and_plan_use_the_provider(self):
        body = {'id': self.rid}
        chat = self.call(
            'POST', '/api/chat', body | {'messages': [{'role': 'user', 'content': 'how are users created?'}]}
        )[1]
        self.assertIn('From the stub', chat['answer'])
        tour = self.call('POST', '/api/tour', body | {'chapter': 'flow'})[1]
        self.assertEqual(tour['source'], 'ai')
        self.assertIn('flow', tour['ready'])
        prompt = next(
            r for r in self.stub.requests if 'Follow one real operation' in r['body']['messages'][-1]['content']
        )
        self.assertIn(
            'Repository source excerpts', prompt['body']['messages'][-1]['content']
        )  # it cannot read files itself
        self.assertIn(
            'From the stub', self.call('POST', '/api/locate', body | {'issue': 'add a field', 'ai': True})[1]['ai_plan']
        )
        self.assertEqual(self.call('GET', '/api/settings')[1]['label'], 'OpenAI-compatible · stub')


if __name__ == '__main__':
    unittest.main()
