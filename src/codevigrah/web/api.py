"""JSON API endpoints. Each handler takes ``(app, request)`` and returns a JSON-serialisable object.

Register a handler with ``@route(METHOD, PATH)``; raise :class:`HttpError` for client errors.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import __version__, llm, prompts, quiz, tour
from ..report import md_report
from ..sources import SourceError, normalise
from .app import App

MAX_CHAT_CHARS = 20_000  # per message
ROUTES: dict[tuple[str, str], Callable[[App, Request], object]] = {}


@dataclass
class Request:
    method: str
    path: str
    query: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)
    client: str = ''


class HttpError(Exception):
    def __init__(self, status: int, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or {}


def route(method: str, path: str):
    def register(fn):
        ROUTES[(method, path)] = fn
        return fn

    return register


# ------------------------------------------------------------------ helpers
def repo_or_404(app: App, rid: str) -> dict:
    r = app.get_repo(rid or '')
    if not r:
        raise HttpError(404, 'repository not analysed')
    return r


def rate_limit(app: App, req: Request, bucket: str) -> None:
    """Raise 429 when this client has used up its hourly allowance for ``bucket`` ('ai' or 'analyze')."""
    limit = app.settings.rate_ai_per_hour if bucket == 'ai' else app.settings.rate_analyze_per_hour
    if not app.limiter.allow(bucket, req.client, limit):
        wait = app.limiter.retry_after(bucket, req.client)
        what = 'AI requests' if bucket == 'ai' else 'analyses'
        raise HttpError(
            429,
            f'Too many {what} from your address; try again in {max(1, wait // 60)} min.',
            {'Retry-After': str(wait)},
        )


def ai_allowed(app: App, req: Request) -> str:
    """'' when an optional AI step may run, else the reason it is skipped (used where a static answer still works)."""
    try:
        rate_limit(app, req, 'ai')
    except HttpError as e:
        return e.message
    return ''


def chapter_list() -> list[dict]:
    return [{k: c[k] for k in ('key', 'title', 'sub')} for c in tour.CHAPTERS]


def int_arg(value, default: int) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        raise HttpError(400, 'expected a number') from None


# ------------------------------------------------------------------ meta
@route('GET', '/api/health')
def health(app: App, req: Request):
    return {'ok': True, 'version': __version__}


@route('GET', '/api/settings')
def get_settings(app: App, req: Request):
    return app.settings_json()


@route('POST', '/api/settings')
def set_settings(app: App, req: Request):
    if app.settings.public:
        raise HttpError(403, 'AI settings are managed by the operator of this site.')
    try:
        llm.router().update(req.body)
    except ValueError as e:
        raise HttpError(400, str(e)) from None
    return app.settings_json()


# ------------------------------------------------------------------ repositories and analysis jobs
@route('GET', '/api/repos')
def list_repos(app: App, req: Request):
    return app.list_repos()


@route('POST', '/api/analyze')
def start_analysis(app: App, req: Request):
    try:
        source = normalise(str(req.body.get('source', '')), allow_local=app.settings.allow_local_paths)
    except SourceError as e:
        raise HttpError(400, str(e)) from None
    rate_limit(app, req, 'analyze')
    return {'job': app.start_analysis(source, bool(req.body.get('refresh')))}


@route('GET', '/api/job')
def job_status(app: App, req: Request):
    job = app.jobs.get(req.query.get('id', ''))
    if not job:
        raise HttpError(404, 'unknown job')
    return job


@route('GET', '/api/analysis')
def get_analysis(app: App, req: Request):
    a = repo_or_404(app, req.query.get('id', ''))['a']
    return a | {'meta': {k: v for k, v in a['meta'].items() if k != 'root'}}  # never reveal server paths


@route('GET', '/api/file')
def get_file(app: App, req: Request):
    r = repo_or_404(app, req.query.get('id', ''))
    t = r['index'].read(req.query.get('path', ''), 400_000)
    return {'text': t if t is not None else '(unreadable)'}


# ------------------------------------------------------------------ guided tour and skill check
@route('POST', '/api/tour')
def get_chapter(app: App, req: Request):
    rid, key = req.body.get('id', ''), str(req.body.get('chapter', 'what'))
    r = repo_or_404(app, rid)
    keys = [c['key'] for c in tour.CHAPTERS]
    if key not in keys:
        raise HttpError(400, 'unknown chapter')
    regenerate = bool(req.body.get('regenerate'))
    if regenerate:
        rate_limit(app, req, 'ai')
    try:
        res = app.chapter(rid, key, regenerate)
    except llm.LLMError as e:
        res = {'markdown': tour.STATIC[key](r['a'], r['index']), 'source': 'static', 'error': str(e)}
    if keys.index(key) + 1 < len(keys):
        app.prefetch(rid, keys[keys.index(key) + 1])
    if key in ('why', 'limits', 'practice'):
        app.prefetch_quiz(rid, 1)  # the reader is near the end of the tour: get the skill check ready
    return res | {'chapters': chapter_list(), 'ready': tour.cached_keys(r['a'], app.work)}


@route('POST', '/api/tour_status')
def tour_status(app: App, req: Request):
    rid = req.body.get('id', '')
    r = repo_or_404(app, rid)
    return {
        'chapters': chapter_list(),
        'ready': tour.cached_keys(r['a'], app.work),
        'ai': llm.available(),
        'working': app.working(rid),
    }


@route('POST', '/api/quiz')
def get_quiz(app: App, req: Request):
    rid = req.body.get('id', '')
    r = repo_or_404(app, rid)
    level = int_arg(req.body.get('level'), 1)
    if level not in quiz.LEVELS:
        raise HttpError(400, 'level must be 1-3')
    regenerate = bool(req.body.get('regenerate'))
    if regenerate:
        rate_limit(app, req, 'ai')
    avoid = [str(x) for x in (req.body.get('avoid') or []) if isinstance(x, str)][:60]
    try:
        res = app.quiz(rid, level, regenerate, avoid)
    except llm.LLMError as e:
        res = quiz.fallback_level(r['a'], r['index'], level, e)
    app.prefetch_quiz(rid, level + 1)
    return res


@route('POST', '/api/quiz_status')
def quiz_status(app: App, req: Request):
    rid = req.body.get('id', '')
    r = repo_or_404(app, rid)
    return {
        'levels': dict(quiz.LEVELS),
        'ready': quiz.cached_levels(r['a'], app.work),
        'ai': llm.available(),
        'working': [int(k[4:]) for k in app.working(rid) if k.startswith('quiz')],
    }


# ------------------------------------------------------------------ change planner, file explainer, chat, report
@route('POST', '/api/locate')
def locate(app: App, req: Request):
    r = repo_or_404(app, req.body.get('id', ''))
    issue = str(req.body.get('issue', ''))[:MAX_CHAT_CHARS]
    res = r['index'].locate(issue)
    if req.body.get('ai') and llm.available():
        skipped = ai_allowed(app, req)
        if skipped:
            res['ai_error'] = skipped
            return res
        ctx, _ = r['index'].llm_context(issue, [p['path'] for p in res['primary'][:2]])
        cand = json.dumps({k: res[k] for k in ('recipe', 'primary', 'ripple', 'tests', 'chain')}, indent=1)[:12000]
        prompt = prompts.CHANGE_PLAN.format(context=ctx, candidates=cand, issue=issue)
        try:
            res['ai_plan'] = llm.complete(
                prompts.SYSTEM, [{'role': 'user', 'content': prompt}], 3500, cwd=r['a']['meta']['root']
            )
        except llm.LLMError as e:
            res['ai_error'] = str(e)
    return res


@route('POST', '/api/explain')
def explain(app: App, req: Request):
    r = repo_or_404(app, req.body.get('id', ''))
    path = str(req.body.get('path', ''))
    f = next((x for x in r['a']['files'] if x['path'] == path), None)
    if not f:
        raise HttpError(404, 'unknown file')
    idx = r['index']
    pos = idx.pos[path]
    info = {
        'file': f,
        'imports': [idx.files[j]['path'] for j in idx.out[pos]][:30],
        'imported_by': [idx.files[j]['path'] for j in idx.inc[pos]][:30],
        'co_changes': [{'path': p, 'n': n} for p, s, n in idx.co.get(path, [])[:8]],
    }
    if req.body.get('ai'):
        skipped = ai_allowed(app, req)
        if skipped:
            info['ai_error'] = skipped
            return info
        ctx, _ = idx.llm_context(path + ' ' + ' '.join(s[0] for s in f['sym'][:15]), [path])
        prompt = prompts.EXPLAIN_FILE.format(context=ctx, facts=json.dumps(info)[:5000], path=path)
        try:
            info['ai'] = llm.complete(
                prompts.SYSTEM, [{'role': 'user', 'content': prompt}], 2500, cwd=r['a']['meta']['root']
            )
        except llm.LLMError as e:
            info['ai_error'] = str(e)
    return info


@route('POST', '/api/chat')
def chat(app: App, req: Request):
    r = repo_or_404(app, req.body.get('id', ''))
    msgs = [
        {'role': m['role'], 'content': m['content'][:MAX_CHAT_CHARS]}
        for m in (req.body.get('messages') or [])
        if isinstance(m, dict)
        and m.get('role') in ('user', 'assistant')
        and isinstance(m.get('content'), str)
        and m['content']
    ][-12:]
    if not msgs or msgs[-1]['role'] != 'user':
        raise HttpError(400, 'last message must be from user')
    q = msgs[-1]['content']
    pins = [p for p in (req.body.get('pin') or []) if isinstance(p, str)][:3]
    ctx, sources = r['index'].llm_context(q, pins)
    if not llm.available():
        loc = r['index'].locate(q)
        lines = [
            '_No AI provider is configured, so this is static retrieval. Open Settings to set one up for full answers._',
            '',
            '**Most relevant files:**',
        ]
        lines += [
            f'- `{p["path"]}` ({p["role"]}; matched {", ".join(p["why"]) or "content"})' for p in loc['primary'][:6]
        ]
        if loc['ripple']:
            lines += ['', '**Connected files:**'] + [f'- `{x["path"]}`: {x["reasons"][0]}' for x in loc['ripple'][:5]]
        return {'answer': '\n'.join(lines), 'sources': sources}
    rate_limit(app, req, 'ai')
    try:
        ans = llm.complete(prompts.SYSTEM + '\n\n# Repository context\n' + ctx, msgs, 3000, cwd=r['a']['meta']['root'])
    except llm.LLMError as e:
        raise HttpError(502, str(e)) from None
    return {'answer': ans, 'sources': sources}


@route('POST', '/api/report')
def report(app: App, req: Request):
    r = repo_or_404(app, req.body.get('id', ''))
    narrative = ''
    if req.body.get('ai') and llm.available():
        skipped = ai_allowed(app, req)
        if skipped:
            narrative = f'_AI narrative skipped: {skipped}_'
        else:
            ctx, _ = r['index'].llm_context('architecture main flow entry point core', [])
            try:
                narrative = llm.complete(
                    prompts.SYSTEM,
                    [{'role': 'user', 'content': prompts.NARRATIVE.format(context=ctx)}],
                    2500,
                    cwd=r['a']['meta']['root'],
                )
            except llm.LLMError as e:
                narrative = f'_AI narrative failed: {e}_'
    return {'markdown': md_report(r['a'], narrative)}
