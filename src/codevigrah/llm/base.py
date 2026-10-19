"""The interface every AI provider implements (the adapter pattern).

A provider turns ``(system prompt, chat messages)`` into text. Adding a provider means writing one small class;
nothing else in CodeVigrah knows which model or API is behind it.
"""

from __future__ import annotations

import re


class LLMError(Exception):
    """An AI provider failed, refused, or is not configured. Callers fall back to static output."""


class Provider:
    name = 'base'  # stable id used in configuration (CODEVIGRAH_AI_PROVIDERS)
    label = 'Base provider'  # shown in the UI
    reads_files = False  # True when the provider opens repository files itself (it then gets less pasted context)
    fields: tuple[str, ...] = ()  # settings the UI may edit: api_key, model, base_url

    model = ''
    base_url = ''
    api_key = ''

    def available(self) -> bool:
        raise NotImplementedError

    def problem(self) -> str:
        """Why the provider is not available, in words a user can act on ('' when it is available)."""
        return ''

    def describe(self) -> str:
        return f'{self.label} · {self.model}' if self.model else self.label

    def complete(self, system: str, messages: list[dict], max_tokens: int = 3000, cwd: str | None = None) -> str:
        raise NotImplementedError

    def update(self, **values: str) -> None:
        """Apply settings from the UI. Only names listed in ``fields`` are accepted."""
        for k, v in values.items():
            if k in self.fields and v is not None:
                setattr(self, k, v.strip())

    def info(self) -> dict:
        """Public description for the settings UI. Never includes secrets."""
        d = {
            'name': self.name,
            'label': self.label,
            'available': self.available(),
            'problem': self.problem(),
            'model': self.model,
            'fields': list(self.fields),
            'reads_files': self.reads_files,
        }
        if 'base_url' in self.fields:
            d['base_url'] = self.base_url
        if 'api_key' in self.fields:
            d['has_key'] = bool(self.api_key)
        return d


THINK = re.compile(r'<think>.*?</think>\s*', re.S)


def strip_reasoning(text: str) -> str:
    """Some local reasoning models (e.g. via Ollama) prefix their answer with <think>...</think>."""
    return THINK.sub('', text or '').strip()
