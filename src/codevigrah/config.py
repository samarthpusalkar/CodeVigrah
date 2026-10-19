"""Runtime settings, read from environment variables and an optional ``.env`` file.

Every setting has a safe default, so CodeVigrah runs with no configuration at all. Secrets (API keys) are only
ever read from the environment, never from the code. ``.env.example`` documents every variable.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

LOOPBACK = ('127.0.0.1', 'localhost', '::1')
_LINE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$')


def load_dotenv(path: str | os.PathLike = '.env', environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Load ``KEY=VALUE`` lines from ``path`` into ``environ`` without overriding variables that are already set.

    Supports ``# comments``, blank lines, an optional ``export`` prefix and single or double quotes.
    Returns the names that were set. A missing file is not an error.
    """
    environ = os.environ if environ is None else environ
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return []
    loaded = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        key, value = m.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        elif ' #' in value:
            value = value.split(' #', 1)[0].rstrip()  # inline comment after an unquoted value
        if key not in environ:
            environ[key] = value
            loaded.append(key)
    return loaded


def env_str(environ: Mapping[str, str], name: str, default: str = '') -> str:
    return environ.get(name, default).strip()


def env_bool(environ: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    value = environ.get(name, '').strip()
    try:
        return int(value) if value else default
    except ValueError as e:
        raise ValueError(f'{name} must be a whole number, got {value!r}') from e


@dataclass(frozen=True)
class Settings:
    """Server and analysis settings. AI provider settings live in :mod:`codevigrah.llm`."""

    host: str = '127.0.0.1'
    port: int = 8765
    workspace: Path = Path('workspace')
    public: bool = False  # hosting for other people: settings locked, local paths off, rate limits on
    allow_local_paths: bool = True
    trust_proxy: bool = False  # take the client IP from X-Forwarded-For (only behind your own reverse proxy)
    allowed_hosts: tuple[
        str, ...
    ] = ()  # accepted Host headers; empty = loopback names when bound to loopback, else any
    max_jobs: int = 2  # analyses that may run at the same time
    max_repo_mb: int = 1000  # clones bigger than this are deleted and rejected
    clone_depth: int = 1000  # commits of history to fetch
    rate_ai_per_hour: int = 0  # per client IP; 0 = unlimited
    rate_analyze_per_hour: int = 0
    rate_tts_per_hour: int = 0  # sentences voiced fresh by the speech server (cached ones are free)
    listen_scripts: bool = True  # AI-written listening scripts for tour chapters, when an AI provider is set up
    tts_prepare: bool = False  # voice whole tour chapters in the background, so listening never waits for the server
    log_level: str = 'INFO'

    @property
    def is_loopback(self) -> bool:
        return self.host in LOOPBACK

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None, **overrides) -> Settings:
        """Build settings from environment variables; keyword ``overrides`` (e.g. CLI flags) win when not None."""
        env = os.environ if environ is None else environ
        values = {
            'host': env_str(env, 'CODEVIGRAH_HOST', cls.host),
            'port': env_int(env, 'CODEVIGRAH_PORT', cls.port),
            'workspace': Path(env_str(env, 'CODEVIGRAH_WORKSPACE', 'workspace')).expanduser(),
            'public': env_bool(env, 'CODEVIGRAH_PUBLIC'),
            'trust_proxy': env_bool(env, 'CODEVIGRAH_TRUST_PROXY'),
            'allowed_hosts': tuple(
                h.strip().lower() for h in env_str(env, 'CODEVIGRAH_ALLOWED_HOSTS').split(',') if h.strip()
            ),
            'max_jobs': max(1, env_int(env, 'CODEVIGRAH_MAX_JOBS', cls.max_jobs)),
            'max_repo_mb': env_int(env, 'CODEVIGRAH_MAX_REPO_MB', cls.max_repo_mb),
            'clone_depth': max(1, env_int(env, 'CODEVIGRAH_CLONE_DEPTH', cls.clone_depth)),
            'listen_scripts': env_bool(env, 'CODEVIGRAH_LISTEN_SCRIPTS', cls.listen_scripts),
            'tts_prepare': env_bool(env, 'CODEVIGRAH_TTS_PREPARE', cls.tts_prepare),
            'log_level': env_str(env, 'CODEVIGRAH_LOG_LEVEL', cls.log_level).upper() or 'INFO',
        }
        values.update({k: v for k, v in overrides.items() if v is not None and k != 'allow_local_paths'})
        public = values['public']
        # Public instances get rate limits unless the operator chose numbers explicitly.
        values['rate_ai_per_hour'] = env_int(env, 'CODEVIGRAH_RATE_AI_PER_HOUR', 30 if public else 0)
        values['rate_analyze_per_hour'] = env_int(env, 'CODEVIGRAH_RATE_ANALYZE_PER_HOUR', 10 if public else 0)
        values['rate_tts_per_hour'] = env_int(env, 'CODEVIGRAH_RATE_TTS_PER_HOUR', 600 if public else 0)
        # Local folders can only be analysed from this machine, unless explicitly allowed (never when public).
        explicit = overrides.get('allow_local_paths')
        if explicit is None:
            explicit = env_bool(env, 'CODEVIGRAH_ALLOW_LOCAL_PATHS')
        values['allow_local_paths'] = not public and (values['host'] in LOOPBACK or bool(explicit))
        return cls(**values)
