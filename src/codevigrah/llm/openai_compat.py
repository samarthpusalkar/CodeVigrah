"""Any server that speaks the OpenAI-style ``/v1/chat/completions`` API (standard library only).

That covers local models through Ollama, LM Studio, llama.cpp or vLLM, and hosted APIs such as Groq,
OpenRouter or OpenAI. Presets give each a name with sensible defaults.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from .. import __version__
from .base import LLMError, Provider, strip_reasoning

PRESETS = {
    # name: (label, default base URL, key required, default timeout s, default concurrency)
    'ollama': ('Ollama (local)', 'http://localhost:11434/v1', False, 900, 1),
    'groq': ('Groq', 'https://api.groq.com/openai/v1', True, 300, 2),
    'openai': ('OpenAI-compatible', '', False, 600, 2),
}


class OpenAICompatProvider(Provider):
    fields = ('base_url', 'api_key', 'model')

    def __init__(
        self,
        name: str,
        base_url: str = '',
        api_key: str = '',
        model: str = '',
        timeout: int | None = None,
        concurrency: int | None = None,
    ):
        label, default_url, key_required, default_timeout, default_conc = PRESETS.get(name, (name, '', False, 600, 2))
        self.name = name
        self.label = label
        self.base_url = base_url or default_url
        self.api_key = api_key
        self.model = model
        self.key_required = key_required
        self.timeout = timeout or default_timeout
        self._slots = threading.Semaphore(max(1, concurrency or default_conc))

    def available(self) -> bool:
        return not self.problem()

    def problem(self) -> str:
        if not self.base_url:
            return 'no base URL'
        if not self.model:
            return 'no model selected'
        if self.key_required and not self.api_key:
            return 'no API key'
        return ''

    def complete(self, system: str, messages: list[dict], max_tokens: int = 3000, cwd: str | None = None) -> str:
        if self.problem():
            raise LLMError(f'{self.label} unavailable: {self.problem()}')
        body = json.dumps(
            {
                'model': self.model,
                'max_tokens': max_tokens,
                'stream': False,
                'messages': [{'role': 'system', 'content': system}, *messages],
            }
        ).encode()
        headers = {'Content-Type': 'application/json', 'User-Agent': f'codevigrah/{__version__}'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        req = urllib.request.Request(
            self.base_url.rstrip('/') + '/chat/completions', data=body, method='POST', headers=headers
        )
        with self._slots:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.load(r)
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors='replace')[:400]
                raise LLMError(f'{self.label} error {e.code}: {detail}') from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise LLMError(f'{self.label}: cannot reach {self.base_url} ({e})') from None
            except ValueError:
                raise LLMError(f'{self.label}: the server did not return JSON') from None
        try:
            choice = data['choices'][0]
            text = strip_reasoning(choice['message'].get('content') or '')
        except (KeyError, IndexError, TypeError, AttributeError):
            raise LLMError(f'{self.label}: unexpected response {str(data)[:300]}') from None
        if not text:
            raise LLMError(f'{self.label} returned no text (finish reason: {choice.get("finish_reason")})')
        return text
