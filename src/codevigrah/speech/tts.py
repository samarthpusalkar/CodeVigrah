"""Natural voices from speech servers that speak the OpenAI-style ``/v1/audio/speech`` API (standard library only).

That covers the local server in ``contrib/speech-server`` (Kokoro and Piper), Ollama's speech models (Phonon,
lfm3-audio), Kokoro-FastAPI or Speaches on a GPU machine, and hosted APIs such as OpenAI. Audio is cached on disk one
sentence at a time, so every sentence is voiced once per voice and replays cost nothing.

Several servers can be listed, best first, each with its own model and voices (for example Phonon on a GPU machine,
then Kokoro on this one). A server that does not answer is skipped for a minute and the next one speaks, with the
voice asked for when it has it and its own default voice otherwise. When none answers, natural voices are reported as
unavailable, so the page uses the device's own voices straight away instead of waiting on every sentence.
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
VOICES_TTL = 300  # seconds to trust a voice list (60 after a failure)
DOWN_FOR = 60  # seconds to skip a server that did not answer


class SpeechError(Exception):
    """The speech server failed or is not configured. Callers fall back to the browser's own voices."""


class Unreachable(SpeechError):
    """The server did not answer at all (off, asleep, wrong address), as opposed to answering with an error."""


class SpeechServer:
    """One speech server with its own model, voices, key and audio format."""

    def __init__(
        self,
        url: str,
        model: str = 'kokoro',
        voice: str = '',
        voices: tuple[str, ...] = (),
        api_key: str = '',
        fmt: str = 'mp3',
        timeout: int = 120,
    ):
        self.url = url.strip().rstrip('/')
        self.model = model or 'kokoro'
        self.voice = voice
        self.allow = tuple(voices)  # configured voices: the only ones offered (servers without a voice list need it)
        self.api_key = api_key
        self.fmt = fmt or 'mp3'
        self.timeout = timeout
        self.down_until = 0.0
        self._voices: list[dict] = []
        self._voices_at = 0.0
        self._voices_ok = False

    def __repr__(self) -> str:
        return f'{self.model} at {self.url}'

    def is_up(self) -> bool:
        return self.down_until <= time.time()

    def mark_down(self) -> None:
        self.down_until = time.time() + DOWN_FOR

    def answers(self) -> bool:
        """A quick TCP connect, so a sleeping machine costs two seconds instead of a full request timeout."""
        u = urllib.parse.urlsplit(self.url)
        try:
            socket.create_connection((u.hostname, u.port or (443 if u.scheme == 'https' else 80)), timeout=2).close()
            return True
        except OSError:
            return False

    def request(self, path: str, body: dict | None = None, timeout: float | None = None, native: bool = False):
        """Send one request. Raises :class:`Unreachable` when the server does not answer (and skips it for a while),
        :class:`SpeechError` when it answers with an error. ``native`` drops the ``/v1`` for a server's own API
        (Ollama's ``/api/...``)."""
        headers = {'User-Agent': f'codevigrah/{__version__}'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        data = json.dumps(body).encode() if body is not None else None
        root = self.url.removesuffix('/v1') if native else self.url
        req = urllib.request.Request(root + path, data=data, headers=headers, method='POST' if data else 'GET')
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')[:300]
            e.close()
            raise SpeechError(f'{self.url} answered {e.code}: {detail}') from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self.mark_down()
            raise Unreachable(f'cannot reach the speech server at {self.url} ({e})') from None

    # ------------------------------------------------------------------ voices
    def voices(self) -> list[dict]:
        """``[{id, label}]``: the server's list (filtered and ordered by the configured voices), or the configured
        voices alone when the server answers but has no list (OpenAI). Empty while the server is not answering.
        Cached briefly; never raises."""
        if not self.is_up():
            return []
        now = time.time()
        if now - self._voices_at < (VOICES_TTL if self._voices_ok else 60):
            return self._voices
        try:
            found = self._listed()
        except Unreachable:
            self._voices, self._voices_at, self._voices_ok = [], now, False
            return []
        ok = bool(found)
        if self.allow:
            known = {v['id']: v for v in found}
            found = [known.get(v, {'id': v, 'label': v}) for v in self.allow if not found or v in known]
        self._voices, self._voices_at, self._voices_ok = found, now, ok
        return found

    def _listed(self) -> list[dict]:
        """The server's own voice list: ``/audio/voices``, or Ollama's ``/api/show`` for the model."""
        try:
            with self.request('/audio/voices', timeout=3) as r:
                data = json.load(r)
            raw = data.get('voices', []) if isinstance(data, dict) else data
            found = []
            for v in raw if isinstance(raw, list) else []:
                vid = v if isinstance(v, str) else (v.get('id') or v.get('voice_id') or v.get('name'))
                if vid:
                    label = v.get('name') or vid if isinstance(v, dict) else vid
                    found.append({'id': str(vid), 'label': str(label)})
            if found:
                return found
        except Unreachable:
            raise
        except (SpeechError, ValueError, AttributeError):
            pass
        try:
            with self.request('/api/show', {'model': self.model}, timeout=5, native=True) as r:
                data = json.load(r)
        except Unreachable:
            raise
        except (SpeechError, ValueError):
            return []
        raw = data.get('voices') if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        # 'female-american-english' -> 'Female American English'
        return [{'id': str(v), 'label': str(v).replace('-', ' ').replace('_', ' ').title()} for v in raw if v]

    def voice_ids(self) -> list[str]:
        return [v['id'] for v in self.voices()]

    def default_voice(self) -> str:
        ids = self.voice_ids()
        return self.voice if self.voice in ids else (ids[0] if ids else '')

    def resolve(self, voice: str) -> str:
        """``voice`` when this server has it, else its default voice ('' when it has none or is not answering)."""
        return voice if voice and voice in self.voice_ids() else self.default_voice()

    # ------------------------------------------------------------------ audio
    def synthesize(self, text: str, voice: str) -> tuple[bytes, str]:
        body = {'model': self.model, 'input': text, 'voice': voice, 'response_format': self.fmt, 'speed': 1.0}
        with self.request('/audio/speech', body) as r:
            data = r.read()
            ctype = (r.headers.get('Content-Type') or 'audio/mpeg').split(';')[0].strip().lower()
        if not data or not ctype.startswith('audio/'):
            raise SpeechError(f'{self.url} sent {ctype or "nothing"} instead of audio')
        return data, ctype


class SpeechEngine:
    """The servers in order of preference, an on-disk cache per sentence, and fallback from one server to the next."""

    def __init__(self, servers: list[SpeechServer] | None = None, concurrency: int = 1):
        self.servers = list(servers or [])
        self.base_url = ', '.join(s.url for s in self.servers)  # for display
        self._slots = threading.Semaphore(max(1, concurrency))  # a Pi voices one sentence at a time
        self._inflight: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def _live(self) -> list[SpeechServer]:
        return [s for s in self.servers if s.is_up()]

    def primary(self) -> SpeechServer | None:
        """The first server that is answering and has voices: the one whose voices the player offers."""
        return next((s for s in self._live() if s.voices()), None)

    def available(self) -> bool:
        return self.primary() is not None

    def voices(self) -> list[dict]:
        p = self.primary()
        return p.voices() if p else []

    def voice_ids(self) -> list[str]:
        return [v['id'] for v in self.voices()]

    def default_voice(self) -> str:
        p = self.primary()
        return p.default_voice() if p else ''

    def info(self) -> dict:
        """For the settings API and the player's voice menu. Never includes a key."""
        if not self.servers:
            return {'available': False}
        p = self.primary()
        if p is None:
            return {'available': False}
        return {'available': True, 'voices': p.voices(), 'default': p.default_voice(), 'model': p.model}

    def status(self) -> list[str]:
        """One line per server, for the startup banner."""
        out = []
        for s in self.servers:
            n = len(s.voices())
            out.append(f'{s.model} at {s.url}: ' + (f'{n} voices' if n else 'not answering yet'))
        return out

    # ------------------------------------------------------------------ audio
    @staticmethod
    def key(model: str, voice: str, text: str) -> str:
        return hashlib.sha256(f'{model}\n{voice}\n{text}'.encode()).hexdigest()[:32]

    @staticmethod
    def _file(folder: Path, k: str) -> tuple[bytes, str] | None:
        for ext, ctype in TYPES.items():
            p = folder / f'{k}.{ext}'
            if p.is_file():
                return p.read_bytes(), ctype
        return None

    def cached(self, folder: Path, text: str, voice: str) -> tuple[bytes, str] | None:
        """The cached audio the preferred server would give for ``text`` (None when it has to be voiced)."""
        p = self.primary()
        if p is None:
            return None
        return self._file(folder, self.key(p.model, p.resolve(voice), text))

    def speak(self, folder: Path, text: str, voice: str) -> tuple[bytes, str]:
        """Cached audio for ``text``, voicing it first if needed: by the first server that answers, in ``voice`` when
        it has it and in its default voice otherwise."""
        errors = []
        live = self._live()
        for s in live:
            if len(live) > 1 and s is not live[-1] and not s.answers():
                s.mark_down()
                errors.append(f'{s.url} is not answering')
                continue
            v = s.resolve(voice)
            if not v:
                errors.append(f'{s.url} has no voices')
                continue
            try:
                return self._speak_on(s, folder, text, v)
            except SpeechError as e:
                if not isinstance(e, Unreachable) and len(self.servers) > 1:
                    s.mark_down()  # a failing server: let the next one speak for a while
                errors.append(str(e))
        raise SpeechError('; '.join(errors) or 'no speech server is answering')

    def _speak_on(self, s: SpeechServer, folder: Path, text: str, voice: str) -> tuple[bytes, str]:
        """Two requests for the same sentence share one job."""
        k = self.key(s.model, voice, text)
        while True:
            hit = self._file(folder, k)
            if hit:
                return hit
            with self._lock:
                ev = self._inflight.get(k)
                owner = ev is None
                if owner:
                    ev = self._inflight[k] = threading.Event()
            if owner:
                break
            ev.wait(s.timeout)
            if not self._file(folder, k):
                raise SpeechError('voicing this sentence failed')
        try:
            with self._slots:
                data, ctype = s.synthesize(text, voice)
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
        """Voice ``text`` without the cache, on the first server that manages it."""
        errors = []
        for s in self._live():
            v = s.resolve(voice)
            if not v:
                continue
            try:
                with self._slots:
                    return s.synthesize(text, v)
            except SpeechError as e:
                if not isinstance(e, Unreachable) and len(self.servers) > 1:
                    s.mark_down()
                errors.append(str(e))
        raise SpeechError('; '.join(errors) or 'no speech server is answering')
