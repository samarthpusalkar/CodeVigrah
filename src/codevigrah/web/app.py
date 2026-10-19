"""State shared by all requests: loaded analyses, background analysis jobs and in-flight AI generations."""

from __future__ import annotations

import logging
import os
import threading
import time
import traceback
import uuid
from collections import OrderedDict, defaultdict
from collections.abc import Callable

from .. import __version__, llm, quiz, tour
from ..analysis import SCHEMA, analyze
from ..config import Settings
from ..retrieval import Index
from ..service import analyze_source
from ..sources import repo_id_for
from ..workspace import LOCAL_PREFIX, Workspace, safe_id
from .ratelimit import RateLimiter

log = logging.getLogger(__name__)
MAX_LOADED_REPOS = 8  # analyses + search indexes kept in memory (least recently used are dropped)
JOB_TTL = 3600  # finished jobs are forgotten after an hour


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ws = Workspace(settings.workspace)
        self.work = str(self.ws.root)
        self.jobs: dict[str, dict] = {}
        self.limiter = RateLimiter()
        self._repos: OrderedDict[str, dict] = OrderedDict()
        self._inflight: dict[tuple[str, str], threading.Event] = {}
        self._repo_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._lock = threading.Lock()
        self._job_slots = threading.BoundedSemaphore(settings.max_jobs)

    # ------------------------------------------------------------------ analysis jobs
    def start_analysis(self, source: str, refresh: bool = False) -> str:
        jid = uuid.uuid4().hex[:10]
        job = {'id': jid, 'status': 'queued', 'log': [], 'repo': None, 'created': time.time()}
        with self._lock:
            now = time.time()
            for k in [
                k for k, j in self.jobs.items() if j['status'] in ('done', 'error') and now - j['created'] > JOB_TTL
            ]:
                del self.jobs[k]
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
            return tour.chapter(r['a'], r['index'], key, self.work, regenerate, prev)

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

    # ------------------------------------------------------------------ settings
    def settings_json(self) -> dict:
        return llm.router().settings() | {
            'public': self.settings.public,
            'local_paths': self.settings.allow_local_paths,
            'version': __version__,
        }
