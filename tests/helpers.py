"""Test fixtures: a tiny multi-language git repository, and stubs of an OpenAI-compatible AI server and speech server."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FILES = {
    'README.md': 'Shop is a small demo service for managing users and orders over HTTP.\n\n```bash\npython -m app.main\n```\n',
    'pyproject.toml': '[project]\nname = "shop"\ndependencies = ["fastapi>=0.100", "sqlmodel"]\n',
    'app/__init__.py': '',
    'app/main.py': (
        '"""Entry point: wires the API together and starts the server."""\n'
        'from app import routes\n'
        'from app.service import create_user\n\n\n'
        'def main():\n    return routes, create_user\n\n\n'
        "if __name__ == '__main__':\n    main()\n"
    ),
    'app/models.py': (
        '"""Data models for users and orders."""\n'
        'from sqlmodel import SQLModel\n\n\n'
        'class User(SQLModel, table=True):\n    id: int\n    name: str\n\n\n'
        'class Order(SQLModel, table=True):\n    id: int\n'
    ),
    'app/service.py': (
        '"""Business logic for creating users."""\n'
        'from app.models import User\n\n\n'
        'def create_user(name):\n    if not name:\n        raise ValueError(name)\n    return User(id=1, name=name)\n'
    ),
    'app/routes.py': (
        '"""HTTP routes."""\n'
        'from fastapi import APIRouter\n\n'
        'from app.service import create_user\n\n'
        'router = APIRouter()\n\n\n'
        "@router.get('/users')\ndef list_users():\n    return []\n\n\n"
        "@router.post('/users')\ndef add_user(name: str):\n    return create_user(name)\n"
    ),
    'tests/test_service.py': (
        'from app.service import create_user\n\n\ndef test_create_user():\n    assert create_user("a").name == "a"\n'
    ),
    'web/index.js': "const util = require('./util');\nmodule.exports = () => util.greet('shop');\n",
    'web/util.js': 'function greet(name) { return `hi ${name}`; }\nmodule.exports = { greet };\n',
}
COMMITS = [
    (
        'Ada',
        ['README.md', 'pyproject.toml', 'app/__init__.py', 'app/main.py', 'app/models.py'],
        'Create the shop service skeleton',
    ),
    ('Ada', ['app/service.py', 'tests/test_service.py'], 'Add user creation with validation'),
    ('Linus', ['app/routes.py'], 'Expose users over the HTTP API'),
    ('Ada', ['web/index.js', 'web/util.js'], 'Add a tiny JavaScript greeting client'),
]


def git(cwd, *args, author='Ada'):
    env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'HOME': str(cwd)}
    cmd = [
        'git',
        '-c',
        f'user.name={author}',
        '-c',
        f'user.email={author.lower()}@example.com',
        '-c',
        'commit.gpgsign=false',
        *args,
    ]
    subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True)


def make_repo(root: str | os.PathLike) -> Path:
    """Create the fixture repository with a short, multi-author history and return its path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    git(root, 'init', '-q', '-b', 'main')
    for author, paths, message in COMMITS:
        for p in paths:
            f = root / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(FILES[p])
        git(root, 'add', *paths, author=author)
        git(root, 'commit', '-q', '-m', message, author=author)
    return root


class TempDir:
    """A temporary directory that is removed by ``cleanup()``; handy in setUpClass."""

    def __init__(self):
        self._td = tempfile.TemporaryDirectory(prefix='codevigrah-test-')
        self.path = Path(self._td.name)

    def cleanup(self):
        self._td.cleanup()


class StubOpenAI:
    """A local server that answers /v1/chat/completions, recording each request. ``fail=True`` returns HTTP 500.
    ``answer`` may be a function of the request body, to answer different prompts differently."""

    def __init__(self, answer='stub answer', fail=False):
        self.requests: list[dict] = []
        self.answer = answer
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                stub.requests.append({'path': self.path, 'auth': self.headers.get('Authorization'), 'body': body})
                if fail:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"error": "boom"}')
                    return
                content = stub.answer(body) if callable(stub.answer) else stub.answer
                out = json.dumps({'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/v1'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class StubSpeech:
    """A local stand-in for a speech server (``/v1/audio/voices`` and ``/v1/audio/speech``) that records requests."""

    AUDIO = b'ID3\x03 not really an mp3'

    def __init__(self, voices=({'id': 'af_heart', 'name': 'Heart (US female, Kokoro)'}, 'bf_emma'), fail=False):
        self.requests: list[dict] = []
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, body, ctype):
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == '/v1/audio/voices' and voices is not None:
                    return self.reply(200, json.dumps({'voices': list(voices)}).encode(), 'application/json')
                self.reply(404, b'{"error": "not found"}', 'application/json')

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                stub.requests.append({'path': self.path, 'auth': self.headers.get('Authorization'), 'body': body})
                if fail:
                    return self.reply(500, b'{"error": "boom"}', 'application/json')
                self.reply(200, stub.AUDIO, 'audio/mpeg')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/v1'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
