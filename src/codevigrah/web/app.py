"""State shared by all requests: loaded analyses, background analysis jobs and in-flight AI generations."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import traceback
import uuid
from collections import OrderedDict, defaultdict
from collections.abc import Callable

from .. import __version__, llm, quiz, speech, tour
from ..analysis import SCHEMA, analyze
from ..config import Settings
from ..retrieval import Index
from ..service import analyze_source
from ..sources import repo_id_for
from ..speech import listen
from ..speech import text as speech_text
from ..workspace import LOCAL_PREFIX, Workspace, safe_id
from .ratelimit import RateLimiter

log = logging.getLogger(__name__)
MAX_LOADED_REPOS = 8  # analyses + search indexes kept in memory (least recently used are dropped)
JOB_TTL = 3600  # finished jobs are forgotten after an hour
MAX_SCRIPTS = 300  # prepared read-aloud scripts kept in memory (the player asks again if one was dropped)
LISTEN_RETRY = 600  # seconds before a failed listening script is tried again


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ws = Workspace(settings.workspace)
        self.work = str(self.ws.root)
        self.jobs: dict[str, dict] = {}
        self._job_for: dict[tuple[str, bool], str] = {}  # (source, refresh) -> job id, to join a job already running
        self.limiter = RateLimiter()
        self._repos: OrderedDict[str, dict] = OrderedDict()
        self._inflight: dict[tuple[str, str], threading.Event] = {}
        self._repo_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._lock = threading.Lock()
        self._job_slots = threading.BoundedSemaphore(settings.max_jobs)
        self._scripts: OrderedDict[str, dict] = OrderedDict()
        self._listen_failed: dict[str, float] = {}  # listening-script path -> when it last failed
        self._speech_key = secrets.token_bytes(32)  # signs text this server wrote, so only that text is voiced

    # ------------------------------------------------------------------ analysis jobs
    def start_analysis(self, source: str, refresh: bool = False) -> str:
        """Start an analysis job, or return the one already running for the same source (a second click, or two
        visitors at once): a duplicate would only wait for the first one's lock with an empty log."""
        jid = uuid.uuid4().hex[:10]
        job = {'id': jid, 'status': 'queued', 'log': [], 'repo': None, 'created': time.time()}
        with self._lock:
            running = self.jobs.get(self._job_for.get((source, refresh), ''))
            if running and running['status'] in ('queued', 'running'):
                return running['id']
            self._job_for[(source, refresh)] = jid
            now = time.time()
            for k in [
                k for k, j in self.jobs.items() if j['status'] in ('done', 'error') and now - j['created'] > JOB_TTL
            ]:
                del self.jobs[k]
            self._job_for = {s: j for s, j in self._job_for.items() if j in self.jobs or j == jid}
            self.jobs[jid] = job
        threading.Thread(target=self._run_job, args=(job, source, refresh), daemon=True).start()
        return jid

    def _run_job(self, job: dict, source: str, refresh: bool) -> None:
        def note(msg: str) -> None:
            job['log'].append(f'{time.strftime("%H:%M:%S")} {msg}')

        if not self._job_slots.acquire(blocking=False):
            note('waiting for a free analysis slot')
            self._job_slots.acquire()
        try:
            job['status'] = 'running'
            rid = job['repo'] = repo_id_for(source)
            with self._lock:
                repo_lock = self._repo_locks[rid]
            with repo_lock:  # two visitors analysing the same repo must not clone into one folder at once
                rid, a = analyze_source(self.ws, self.settings, source, refresh, note)
                note('building search index')
                self._remember(rid, {'a': a, 'index': Index(a, a['meta']['root'])})
            job['status'] = 'done'
            note('ready')
            self.prefetch(rid, 'what')
        except Exception as e:  # any failure is reported to the UI through the job log
            job['status'] = 'error'
            job['error'] = str(e)
            note('ERROR ' + str(e))
            if isinstance(e, RuntimeError):  # expected failures (clone failed, repo too big): one line is enough
                log.warning('analysis of %s failed: %s', source, e)
            else:
                log.error('analysis of %s failed\n%s', source, traceback.format_exc())
        finally:
            self._job_slots.release()

    # ------------------------------------------------------------------ analysed repositories
    def get_repo(self, rid: str) -> dict | None:
        rid = safe_id(rid)
        if not rid or (rid.startswith(LOCAL_PREFIX) and not self.settings.allow_local_paths):
            return None
        with self._lock:
            if rid in self._repos:
                self._repos.move_to_end(rid)
                return self._repos[rid]
        a = self.ws.load_analysis(rid)
        if a is None:
            return None
        if a['meta'].get('schema', 0) < SCHEMA:
            a = self._upgrade(rid, a)
        r = {'a': a, 'index': Index(a, a['meta']['root'])}
        self._remember(rid, r)
        return r

    def _upgrade(self, rid: str, a: dict) -> dict:
        """An analysis saved by an older CodeVigrah lacks newer fields: re-run the analyzer on the copy already on disk.

        No network is needed, and cached tour chapters and quizzes stay valid because the commit is unchanged."""
        root = a['meta'].get('root', '')
        if not os.path.isdir(root):
            return a
        with self._lock:
            repo_lock = self._repo_locks[rid]
        with repo_lock:
            log.info('re-analysing %s: it was saved by an older version of CodeVigrah', rid)
            meta = {k: a['meta'][k] for k in ('id', 'name', 'source', 'commit', 'root') if k in a['meta']}
            new = analyze(root, meta, lambda msg: None)
            self.ws.save_analysis(rid, new)
            return new

    def _remember(self, rid: str, r: dict) -> None:
        with self._lock:
            self._repos[rid] = r
            self._repos.move_to_end(rid)
            while len(self._repos) > MAX_LOADED_REPOS:
                self._repos.popitem(last=False)

    def list_repos(self) -> list[dict]:
        return self.ws.list(include_local=self.settings.allow_local_paths)

    # ------------------------------------------------------------------ AI generations (one at a time per key)
    def single_flight(
        self, key: tuple[str, str], produce: Callable[[], dict], wait: float, after_wait: Callable[[], dict]
    ) -> dict:
        """Run ``produce`` unless the same key is already being produced; then wait for it and call ``after_wait``."""
        with self._lock:
            ev = self._inflight.get(key)
            owner = ev is None
            if owner:
                ev = self._inflight[key] = threading.Event()
        if not owner:
            ev.wait(wait)
            return after_wait()
        try:
            return produce()
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            ev.set()

    def working(self, rid: str) -> list[str]:
        with self._lock:
            return [k for (r, k) in self._inflight if r == rid]

    def chapter(self, rid: str, key: str, regenerate: bool = False) -> dict:
        r = self.get_repo(rid)

        def produce():
            prev = ''
            if key != 'what' and llm.available():
                p = tour.cache_path(self.work, rid, r['a']['meta'].get('commit', 'x'), 'what')
                if os.path.isfile(p):
                    with open(p, encoding='utf-8') as fh:
                        prev = fh.read()
            res = tour.chapter(r['a'], r['index'], key, self.work, regenerate, prev)
            if res['source'] == 'ai':
                self.prefetch_listen(rid, key)  # write the listening script while the reader reads
            return res

        return self.single_flight((rid, key), produce, 600, lambda: tour.chapter(r['a'], r['index'], key, self.work))

    def quiz(self, rid: str, level: int, regenerate: bool = False, avoid=()) -> dict:
        r = self.get_repo(rid)
        return self.single_flight(
            (rid, f'quiz{level}'),
            lambda: quiz.get_level(r['a'], r['index'], self.work, level, regenerate, avoid),
            900,
            lambda: quiz.get_level(r['a'], r['index'], self.work, level),
        )

    def _background(self, fn: Callable[[], object]) -> None:
        def run():
            try:
                fn()
            except Exception:
                log.debug('prefetch failed\n%s', traceback.format_exc())

        threading.Thread(target=run, daemon=True).start()

    def prefetch(self, rid: str, key: str) -> None:
        """Generate the next tour chapter while the reader is on the current one."""
        if not llm.available():
            return
        r = self.get_repo(rid)
        if r and key not in tour.cached_keys(r['a'], self.work) and key not in self.working(rid):
            self._background(lambda: self.chapter(rid, key))

    def prefetch_quiz(self, rid: str, level: int) -> None:
        if not llm.available() or level not in quiz.LEVELS:
            return
        r = self.get_repo(rid)
        if r and level not in quiz.cached_levels(r['a'], self.work) and f'quiz{level}' not in self.working(rid):
            self._background(lambda: self.quiz(rid, level))

    # ------------------------------------------------------------------ read-aloud
    def sign(self, text: str) -> str:
        return hmac.new(self._speech_key, text.encode(), hashlib.sha256).hexdigest()[:32]

    def signed(self, text: str, sig: str) -> bool:
        return hmac.compare_digest(self.sign(text), str(sig or ''))

    def chapter_markdown(self, rid: str, key: str) -> tuple[str, bool]:
        """The chapter text exactly as the page shows it, and whether it was written by AI."""
        r = self.get_repo(rid)
        p = tour.cache_path(self.work, rid, r['a']['meta'].get('commit', 'x'), key)
        if os.path.isfile(p):
            with open(p, encoding='utf-8') as fh:
                return fh.read(), True
        return tour.STATIC[key](r['a'], r['index']), False

    def listen_path(self, rid: str, key: str) -> str:
        r = self.get_repo(rid)
        md_path = tour.cache_path(self.work, rid, r['a']['meta'].get('commit', 'x'), key)
        return md_path[: -len('.md')] + f'.listen-{listen.VERSION}.json'

    def prefetch_listen(self, rid: str, key: str) -> bool:
        """Start writing the AI listening script for a chapter. True while one is (or will be) on its way."""
        if not (self.settings.listen_scripts and llm.available()):
            return False
        md, by_ai = self.chapter_markdown(rid, key)
        path = self.listen_path(rid, key)
        if not by_ai or listen.load(path, md) is not None:
            return False
        if time.time() - self._listen_failed.get(path, 0) < LISTEN_RETRY:
            return False
        if ('listen:' + key) in self.working(rid):
            return True
        title = next((c['title'] for c in tour.CHAPTERS if c['key'] == key), key)
        root = self.get_repo(rid)['a']['meta']['root']

        def produce():
            if listen.load(path, md) is None:
                try:
                    listen.save(path, md, listen.generate(md, title, cwd=root))
                except llm.LLMError as e:
                    self._listen_failed[path] = time.time()
                    log.warning('listening script for %s chapter %s failed: %s', rid, key, e)
            self.prevoice(rid, key)
            return {}

        self._background(lambda: self.single_flight((rid, 'listen:' + key), produce, 0, dict))
        return True

    def prevoice(self, rid: str, key: str) -> None:
        """With CODEVIGRAH_TTS_PREPARE, voice a whole chapter in the default voice, one sentence at a time. Slow
        engines (Kokoro on a Pi runs at about real time) then never make the listener wait, even at 1.5x speed."""
        eng = speech.engine()
        if not (self.settings.tts_prepare and eng.available()) or ('voice:' + key) in self.working(rid):
            return

        def produce():
            folder, voice = self.ws.repo_dir(rid) / 'audio', eng.default_voice()
            for s in self.speech_script(rid, chapter=key)['segments']:
                for part in s['parts']:
                    try:
                        eng.speak(folder, part, voice)
                    except speech.SpeechError as e:
                        log.warning('voicing %s chapter %s stopped: %s', rid, key, e)
                        return {}
            return {}

        self._background(lambda: self.single_flight((rid, 'voice:' + key), produce, 0, dict))

    def speech_script(self, rid: str, chapter: str | None = None, text: str | None = None, plain: bool = False) -> dict:
        """What the player should say, split into segments (one per block, with the line it starts on) and parts
        (about a sentence each, the unit that is voiced and cached)."""
        source, pending = 'plain', False
        if chapter:
            md, _ = self.chapter_markdown(rid, chapter)
            segments = None if plain else listen.load(self.listen_path(rid, chapter), md)
            if segments is not None:
                source = 'ai'
            else:
                segments = speech_text.script(md)
                pending = not plain and self.prefetch_listen(rid, chapter)
        else:
            segments = speech_text.script(text or '')
        # the first blocks get a short first part, so the first sound comes within a few seconds even on a Pi
        segs = [
            {**s, 'parts': speech_text.chunks(s['text'], first=110 if k < 3 else None)} for k, s in enumerate(segments)
        ]
        sid = hashlib.sha256(json.dumps([rid, segs]).encode()).hexdigest()[:16]
        with self._lock:
            self._scripts[sid] = {'rid': rid, 'segments': segs}
            self._scripts.move_to_end(sid)
            while len(self._scripts) > MAX_SCRIPTS:
                self._scripts.popitem(last=False)
        return {'sid': sid, 'source': source, 'pending': pending, 'segments': segs}

    def script_part(self, rid: str, sid: str, seg: int, part: int) -> str | None:
        with self._lock:
            sc = self._scripts.get(sid)
        if not sc or sc['rid'] != rid or not 0 <= seg < len(sc['segments']):
            return None
        parts = sc['segments'][seg]['parts']
        return parts[part] if 0 <= part < len(parts) else None

    # ------------------------------------------------------------------ settings
    def settings_json(self) -> dict:
        return llm.router().settings() | {
            'public': self.settings.public,
            'local_paths': self.settings.allow_local_paths,
            'version': __version__,
            'tts': speech.engine().info(),
        }
