"""AI access for CodeVigrah: a small router over interchangeable providers, with fallback.

Providers (see the modules in this package):

* ``claude-cli``  Claude Code on this machine; reads the repo itself with read-only tools
* ``anthropic``   Anthropic Messages API (``ANTHROPIC_API_KEY``; needs ``pip install anthropic``)
* ``ollama``      a local model through Ollama's OpenAI-compatible API
* ``groq``        Groq's hosted OpenAI-compatible API
* ``openai``      any other OpenAI-compatible endpoint (LM Studio, vLLM, OpenRouter, OpenAI, ...)

``CODEVIGRAH_AI_PROVIDERS`` sets the order, e.g. ``ollama,groq,claude-cli``: the first available provider answers
and the next ones take over if it fails. ``auto`` (the default) uses every configured provider in the order above,
except that a public instance never uses the owner's Claude Code login unless it is listed explicitly.

Callers use the module-level functions (``available``, ``describe``, ``complete``), which delegate to the router
created by :func:`configure`.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping

from ..config import env_bool, env_int, env_str
from .anthropic_api import DEFAULT_MODEL, AnthropicProvider
from .base import LLMError, Provider
from .claude_cli import ClaudeCodeProvider
from .openai_compat import OpenAICompatProvider

__all__ = ['LLMError', 'Provider', 'Router', 'available', 'complete', 'configure', 'describe', 'router']

log = logging.getLogger(__name__)
AUTO_ORDER = ('anthropic', 'claude-cli', 'ollama', 'groq', 'openai')
Context = str | Callable[[], str] | None


def providers_from_env(environ: Mapping[str, str]) -> dict[str, Provider]:
    """Build every known provider from environment variables (unconfigured ones simply report unavailable)."""

    def compat(name: str, key_fallback: str = '') -> OpenAICompatProvider:
        up = name.upper()
        return OpenAICompatProvider(
            name,
            base_url=env_str(environ, f'CODEVIGRAH_{up}_BASE_URL'),
            api_key=env_str(environ, f'CODEVIGRAH_{up}_API_KEY')
            or (env_str(environ, key_fallback) if key_fallback else ''),
            model=env_str(environ, f'CODEVIGRAH_{up}_MODEL'),
            timeout=env_int(environ, f'CODEVIGRAH_{up}_TIMEOUT', 0) or None,
            concurrency=env_int(environ, f'CODEVIGRAH_{up}_CONCURRENCY', 0) or None,
        )

    return {
        'anthropic': AnthropicProvider(
            api_key=env_str(environ, 'ANTHROPIC_API_KEY'),
            model=env_str(environ, 'CODEVIGRAH_ANTHROPIC_MODEL', DEFAULT_MODEL),
            effort=env_str(environ, 'CODEVIGRAH_ANTHROPIC_EFFORT', 'high'),
            fallbacks=env_bool(environ, 'CODEVIGRAH_ANTHROPIC_FALLBACKS', True),
            max_tokens=env_int(environ, 'CODEVIGRAH_ANTHROPIC_MAX_TOKENS', 32000),
        ),
        'claude-cli': ClaudeCodeProvider(
            binary=env_str(environ, 'CODEVIGRAH_CLAUDE_BIN', 'claude'),
            model=env_str(environ, 'CODEVIGRAH_CLAUDE_MODEL'),
            timeout=env_int(environ, 'CODEVIGRAH_CLAUDE_TIMEOUT', 420),
            concurrency=env_int(environ, 'CODEVIGRAH_CLAUDE_CONCURRENCY', 2),
        ),
        'ollama': compat('ollama'),
        'groq': compat('groq', 'GROQ_API_KEY'),
        'openai': compat('openai', 'OPENAI_API_KEY'),
    }


def parse_order(value: str) -> list[str] | str:
    value = (value or 'auto').strip().lower()
    if value in ('auto', ''):
        return 'auto'
    if value in ('off', 'none'):
        return []
    names = [n.strip() for n in value.split(',') if n.strip()]
    unknown = [n for n in names if n not in AUTO_ORDER]
    if unknown:
        raise ValueError(
            f'Unknown AI provider(s) {", ".join(unknown)}; choose from {", ".join(AUTO_ORDER)}, auto or off'
        )
    return list(dict.fromkeys(names))


def with_context(messages: list[dict], context: str) -> list[dict]:
    """Append repository excerpts to the last user message, for providers that cannot open files."""
    if not context:
        return messages
    last = messages[-1]
    note = (
        '\n\n## Repository source excerpts\nYou cannot open files yourself, so rely on these excerpts '
        "and the facts above; say so when something you'd need to check is not shown.\n\n"
    )
    return [*messages[:-1], {**last, 'content': last['content'] + note + context}]


class Router:
    def __init__(
        self,
        providers: dict[str, Provider],
        order: list[str] | str = 'auto',
        public: bool = False,
        context_chars: int = 60000,
    ):
        self.providers = providers
        self.order = order
        self.public = public
        self.context_chars = context_chars
        self._lock = threading.Lock()

    def names(self) -> list[str]:
        if self.order == 'auto':
            return [n for n in AUTO_ORDER if not (self.public and n == 'claude-cli')]
        return list(self.order)

    def chain(self) -> list[Provider]:
        """Available providers, in the order they are tried."""
        return [p for n in self.names() if (p := self.providers.get(n)) and p.available()]

    def available(self) -> bool:
        return bool(self.chain())

    def primary(self) -> Provider | None:
        chain = self.chain()
        return chain[0] if chain else None

    def describe(self) -> str | None:
        chain = self.chain()
        if not chain:
            return None
        return chain[0].describe() + (f' (+{len(chain) - 1} fallback)' if len(chain) > 1 else '')

    def complete(
        self, system: str, messages: list[dict], max_tokens: int = 3000, cwd: str | None = None, context: Context = None
    ) -> str:
        """Ask the first available provider; on failure try the next one. ``context`` is extra repository text
        (or a function producing it) that is only sent to providers which cannot read files themselves."""
        chain = self.chain()
        if not chain:
            raise LLMError(
                'No AI provider is configured. Log in to Claude Code, set ANTHROPIC_API_KEY, '
                'or configure Ollama/Groq (see docs/ai-providers.md).'
            )
        ctx_text = None
        errors = []
        for p in chain:
            msgs = messages
            if context and not p.reads_files:
                if ctx_text is None:
                    ctx_text = (context() if callable(context) else context)[: self.context_chars]
                msgs = with_context(messages, ctx_text)
            try:
                return p.complete(system, msgs, max_tokens, cwd)
            except LLMError as e:
                log.warning('AI provider %s failed: %s', p.name, e)
                errors.append(str(e))
        raise LLMError(' · then: '.join(errors))

    # ------------------------------------------------------------------ settings UI
    def settings(self) -> dict:
        p = self.primary()
        return {
            'ai': p is not None,
            'label': self.describe(),
            'reads_files': bool(p and p.reads_files),
            'order': self.order if self.order == 'auto' else ','.join(self.order) or 'off',
            'locked': self.public,
            'providers': [self.providers[n].info() for n in AUTO_ORDER if n in self.providers],
        }

    def update(self, body: dict) -> None:
        """Apply a change from the settings dialog (local instances only; the caller enforces that)."""
        with self._lock:
            name = body.get('provider')
            if name:
                if name not in self.providers:
                    raise ValueError('unknown provider')
                values = {k: body[k] for k in ('api_key', 'model', 'base_url') if isinstance(body.get(k), str)}
                if not values.get('api_key'):
                    values.pop('api_key', None)  # an empty key field means "keep the current key"
                self.providers[name].update(**values)
            if 'order' in body:
                self.order = parse_order(str(body['order']))


_router = Router({}, order=[])


def configure(environ: Mapping[str, str] | None = None, public: bool = False) -> Router:
    """Create the process-wide router from environment variables."""
    global _router
    env = os.environ if environ is None else environ
    _router = Router(
        providers_from_env(env),
        parse_order(env_str(env, 'CODEVIGRAH_AI_PROVIDERS', 'auto')),
        public=public,
        context_chars=env_int(env, 'CODEVIGRAH_AI_CONTEXT_CHARS', 60000),
    )
    return _router


def router() -> Router:
    return _router


def available() -> bool:
    return _router.available()


def describe() -> str | None:
    return _router.describe()


def complete(
    system: str, messages: list[dict], max_tokens: int = 3000, cwd: str | None = None, context: Context = None
) -> str:
    return _router.complete(system, messages, max_tokens, cwd, context)
