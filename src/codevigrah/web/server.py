"""HTTP server (standard library only): static files, the JSON API, and the safety checks around them.

``http.server`` is fine for a personal tool or a small site behind a reverse proxy (Caddy, nginx, Cloudflare
Tunnel) that terminates HTTPS. See docs/deployment.md.
"""

from __future__ import annotations

import json
import logging
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..config import LOOPBACK, Settings
from .api import ROUTES, HttpError, Raw, Request
from .app import App

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / 'static'
MAX_BODY = 1_000_000
CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.ico': 'image/x-icon',
    '.json': 'application/json',
    '.woff2': 'font/woff2',
    '.txt': 'text/plain; charset=utf-8',
}
CSP = (
    "default-src 'self'; script-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
)
SECURITY_HEADERS = {
    'Content-Security-Policy': CSP,
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'DENY',
    'Cross-Origin-Opener-Policy': 'same-origin',
}


def host_name(host_header: str) -> str:
    """'example.com:8765' -> 'example.com', '[::1]:8765' -> '::1'."""
    h = (host_header or '').strip().lower()
    if h.startswith('['):
        return h[1:].split(']', 1)[0]
    return h.rsplit(':', 1)[0] if h.count(':') == 1 else h


class Handler(BaseHTTPRequestHandler):
    server_version = f'CodeVigrah/{__version__}'
    sys_version = ''  # don't advertise the Python version
    timeout = 60  # seconds a client may take to send its request

    def version_string(self):
        return self.server_version

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):
        log.debug('%s %s', self.client_ip(), fmt % args)

    # ------------------------------------------------------------------ responses
    def send_body(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in {'Cache-Control': 'no-cache', **SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def send_json(self, obj, code: int = 200, headers: dict | None = None) -> None:
        self.send_body(code, json.dumps(obj).encode(), 'application/json', headers)

    def static(self, name: str) -> None:
        root = STATIC.resolve()
        full = (root / name).resolve()
        if root not in full.parents or not full.is_file():
            return self.send_json({'error': 'not found'}, 404)
        self.send_body(200, full.read_bytes(), CONTENT_TYPES.get(full.suffix, 'application/octet-stream'))

    # ------------------------------------------------------------------ request checks
    def client_ip(self) -> str:
        if self.app.settings.trust_proxy:
            fwd = self.headers.get('X-Forwarded-For', '')
            if fwd:
                return fwd.split(',')[0].strip()
        return self.client_address[0] if self.client_address else ''

    def host_allowed(self) -> bool:
        """Reject unexpected Host headers: this stops DNS-rebinding pages from talking to a local instance."""
        s: Settings = self.app.settings
        name = host_name(self.headers.get('Host', ''))
        if s.allowed_hosts:
            return name in s.allowed_hosts
        return name in LOOPBACK if s.is_loopback else True

    def cross_site(self) -> bool:
        """True for a browser request sent by another website (CSRF). Our own page always sends JSON same-origin."""
        if self.headers.get('Sec-Fetch-Site', '') == 'cross-site':
            return True
        origin = self.headers.get('Origin')
        if origin and origin != 'null':
            return urlparse(origin).netloc.lower() != (self.headers.get('Host', '') or '').lower()
        return False

    def read_json(self) -> dict:
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            raise HttpError(413, 'request too large')
        if not n:
            return {}
        if not (self.headers.get('Content-Type') or '').startswith('application/json'):
            raise HttpError(415, 'send JSON (Content-Type: application/json)')
        try:
            body = json.loads(self.rfile.read(n))
        except ValueError:
            raise HttpError(400, 'invalid JSON') from None
        if not isinstance(body, dict):
            raise HttpError(400, 'expected a JSON object')
        return body

    # ------------------------------------------------------------------ dispatch
    def do_GET(self):
        self.dispatch('GET')

    def do_HEAD(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def dispatch(self, method: str) -> None:
        u = urlparse(self.path)
        try:
            if not self.host_allowed():
                raise HttpError(421, 'unexpected Host header')
            if method == 'GET' and u.path in ('/', '/index.html'):
                return self.static('index.html')
            if method == 'GET' and u.path.startswith('/static/'):
                return self.static(u.path[len('/static/') :])
            fn = ROUTES.get((method, u.path))
            if fn is None:
                known = any(p == u.path for _, p in ROUTES)
                raise HttpError(405 if known else 404, 'method not allowed' if known else 'not found')
            if method == 'POST' and self.cross_site():
                raise HttpError(403, 'cross-site request blocked')
            req = Request(
                method,
                u.path,
                {k: v[0] for k, v in parse_qs(u.query).items()},
                self.read_json() if method == 'POST' else {},
                self.client_ip(),
            )
            res = fn(self.app, req)
            if isinstance(res, Raw):
                return self.send_body(200, res.body, res.content_type, res.headers)
            self.send_json(res)
        except HttpError as e:
            self.send_json({'error': e.message}, e.status, e.headers)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser went away (e.g. the user navigated off a slow AI answer)
        except Exception as e:
            log.exception('error handling %s %s', method, u.path)
            self.send_json(
                {'error': 'internal error (see the server log)' if self.app.settings.public else str(e)}, 500
            )


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, settings: Settings, app: App | None = None):
        if ':' in settings.host:
            self.address_family = socket.AF_INET6
        self.app = app or App(settings)
        super().__init__((settings.host, settings.port), Handler)
