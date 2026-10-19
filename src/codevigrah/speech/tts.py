"""Natural voices from a speech server that speaks the OpenAI-style ``/v1/audio/speech`` API (standard library only).

That covers the local server in ``contrib/speech-server`` (Kokoro and Piper on the Pi), Kokoro-FastAPI or Speaches
on a GPU machine, and hosted APIs such as OpenAI. Audio is cached on disk one sentence at a time, so every sentence
is voiced once per voice and replays cost nothing.

Several servers can be listed, fastest first (``http://mac.local:8880/v1,http://127.0.0.1:8880/v1``): a server that
does not answer is skipped for a minute and the next one is used, so a laptop that goes to sleep is no problem.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import __version__

EXT = {'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/ogg': 'ogg',
       'audio/opus': 'ogg', 'audio/aac': 'aac', 'audio/flac': 'flac'}  # fmt: skip
TYPES = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg', 'aac': 'audio/aac', 'flac': 'audio/flac'}
VOICES_TTL = 300  # seconds to trust the voice list (60 after a failure)
DOWN_FOR = 60  # seconds to skip a server that did not answer, when there are others to use


class SpeechError(Exception):
    """The speech server failed or is not configured. Callers fall back to the browser's own voices."""


class SpeechEngine:
    def __init__(
        self,
        base_url: str = '',
        api_key: str = '',
        model: str = 'kokoro',
        voice: str = '',
        voices: tuple[str, ...] = (),
        fmt: str = 'mp3',
        timeout: int = 120,
        concurrency: int = 1,
    ):
        self.urls = [u.strip().rstrip('/') for u in base_url.split(',') if u.strip()]
        self.base_url = ', '.join(self.urls)  # for display
        self.api_key = api_key
        self.model = model or 'kokoro'
        self.voice = voice
        self.allow = tuple(voices)  # configured voices: the only ones offered (servers without a voice list need it)
        self.fmt = fmt or 'mp3'
        self.timeout = timeout
        self._slots = threading.Semaphore(max(1, concurrency))  # a Pi voices one sentence at a time
        self._voices: list[dict] = []
        self._voices_at = 0.0
        self._voices_ok = False
        self._inflight: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._down: dict[str, float] = {}  # server -> time until which it is skipped

    def available(self) -> bool:
        return bool(self.base_url) and bool(self.voices())

    def _servers(self) -> list[str]:
        now = time.time()
        up = [u for u in self.urls if self._down.get(u, 0) <= now]
        return up or list(self.urls)  # every server failed recently: try them all again anyway

    @staticmethod
    def _answers(url: str) -> bool:
        """A quick TCP connect, so a sleeping machine costs two seconds instead of a full request timeout."""
        u = urllib.parse.urlsplit(url)
        try:
            socket.create_connection((u.hostname, u.port or (443 if u.scheme == 'https' else 80)), timeout=2).close()
            return True
        except OSError:
            return False

    def _request(self, path: str, body: dict | None = None, timeout: float | None = None):
        """Send to the first server that works. Unreachable servers and server errors (5xx) move on to the next
        one; a 4xx means the request itself is wrong, so it is reported at once."""
        headers = {'User-Agent': f'codevigrah/{__version__}'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        data = json.dumps(body).encode() if body is not None else None
        errors = []
        for url in self._servers():
            if len(self.urls) > 1 and not self._answers(url):
                self._down[url] = time.time() + DOWN_FOR
                errors.append(f'{url} is not answering')
                continue
            req = urllib.request.Request(url + path, data=data, headers=headers, method='POST' if data else 'GET')
            try:
                return urllib.request.urlopen(req, timeout=timeout or self.timeout)
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors='replace')[:300]
                e.close()
                if e.code < 500:
                    raise SpeechError(f'speech server error {e.code}: {detail}') from None
                errors.append(f'{url} failed ({e.code}: {detail})')
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(f'cannot reach the speech server at {url} ({e})')
            self._down[url] = time.time() + DOWN_FOR
        raise SpeechError('; '.join(errors) or 'no speech server is configured')

    # ------------------------------------------------------------------ voices
    def voices(self) -> list[dict]:
        """``[{id, label}]``: the server's list (filtered and ordered by the configured voices), or the configured
        voices alone when the server has no list (OpenAI). Cached briefly; never raises."""
        if not self.base_url:
            return []
        now = time.time()
        if now - self._voices_at < (VOICES_TTL if self._voices_ok else 60):
            return self._voices
        found: list[dict] = []
        try:
            with self._request('/audio/voices', timeout=3) as r:
                data = json.load(r)
            raw = data.get('voices', []) if isinstance(data, dict) else data
            for v in raw if isinstance(raw, list) else []:
                vid = v if isinstance(v, str) else (v.get('id') or v.get('voice_id') or v.get('name'))
                if vid:
                    label = v.get('name') or vid if isinstance(v, dict) else vid
                    found.append({'id': str(vid), 'label': str(label)})
            ok = bool(found)
        except (SpeechError, ValueError, AttributeError):
            ok = False
        if self.allow:
            known = {v['id']: v for v in found}
            found = [known.get(v, {'id': v, 'label': v}) for v in self.allow if not found or v in known]
        self._voices, self._voices_at, self._voices_ok = found, now, ok
        return found

    def voice_ids(self) -> list[str]:
        return [v['id'] for v in self.voices()]

    def default_voice(self) -> str:
        ids = self.voice_ids()
        return self.voice if self.voice in ids else (ids[0] if ids else '')

    def info(self) -> dict:
        """For the settings API and the player's voice menu. Never includes the key."""
        if not self.base_url:
            return {'available': False}
        voices = self.voices()
        return {'available': bool(voices), 'voices': voices, 'default': self.default_voice()}

    # ------------------------------------------------------------------ audio
    @staticmethod
    def key(model: str, voice: str, text: str) -> str:
        return hashlib.sha256(f'{model}\n{voice}\n{text}'.encode()).hexdigest()[:32]

    def cached(self, folder: Path, text: str, voice: str) -> tuple[bytes, str] | None:
        k = self.key(self.model, voice, text)
        for ext, ctype in TYPES.items():
            p = folder / f'{k}.{ext}'
            if p.is_file():
                return p.read_bytes(), ctype
        return None

    def speak(self, folder: Path, text: str, voice: str) -> tuple[bytes, str]:
        """Cached audio for ``text``, voicing it first if needed. Two requests for the same sentence share one job."""
        k = self.key(self.model, voice, text)
        while True:
            hit = self.cached(folder, text, voice)
            if hit:
                return hit
            with self._lock:
                ev = self._inflight.get(k)
                owner = ev is None
                if owner:
                    ev = self._inflight[k] = threading.Event()
            if owner:
                break
            ev.wait(self.timeout)
            if not self.cached(folder, text, voice):
                raise SpeechError('voicing this sentence failed')
        try:
            data, ctype = self.synthesize(text, voice)
            folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, prefix='.voice-')
            with os.fdopen(fd, 'wb') as fh:
                fh.write(data)
            os.replace(tmp, folder / f'{k}.{EXT.get(ctype, "mp3")}')
            return data, TYPES.get(EXT.get(ctype, 'mp3'), ctype)
        finally:
            with self._lock:
                self._inflight.pop(k, None)
            ev.set()

    def synthesize(self, text: str, voice: str) -> tuple[bytes, str]:
        body = {'model': self.model, 'input': text, 'voice': voice, 'response_format': self.fmt, 'speed': 1.0}
        with self._slots, self._request('/audio/speech', body) as r:
            data = r.read()
            ctype = (r.headers.get('Content-Type') or 'audio/mpeg').split(';')[0].strip().lower()
        if not data or not ctype.startswith('audio/'):
            raise SpeechError(f'the speech server sent {ctype or "nothing"} instead of audio')
        return data, ctype
