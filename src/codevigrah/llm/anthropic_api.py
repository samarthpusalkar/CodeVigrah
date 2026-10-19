"""Anthropic Messages API through the official ``anthropic`` Python SDK (optional: ``pip install anthropic``).

Responses are streamed so long answers never hit HTTP timeouts. On current models a refusal is retried
server-side on Anthropic's recommended fallback model (``fallbacks: "default"``).
"""

from __future__ import annotations

import importlib.util
import threading

from .base import LLMError, Provider

DEFAULT_MODEL = 'claude-opus-5-5'
FALLBACK_BETA = 'server-side-fallback-2026-07-01'
# Models that accept the server-side ``fallbacks: "default"`` parameter on the Claude API.
FALLBACK_MODELS = {'claude-opus-5-5', 'claude-opus-5', 'claude-fable-5-1', 'claude-fable-5', 'claude-sonnet-5-5'}


def sdk_installed() -> bool:
    return importlib.util.find_spec('anthropic') is not None


class AnthropicProvider(Provider):
    name = 'anthropic'
    label = 'Anthropic API'
    fields = ('api_key', 'model')

    def __init__(
        self,
        api_key: str = '',
        model: str = DEFAULT_MODEL,
        effort: str = 'high',
        fallbacks: bool = True,
        max_tokens: int = 32000,
        timeout: float = 600.0,
    ):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.effort = effort  # low | medium | high | xhigh | max; '' to omit for models without effort control
        self.fallbacks = fallbacks
        self.max_tokens = max_tokens  # includes thinking tokens, so keep it generous
        self.timeout = timeout
        self._client = None
        self._client_key = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.api_key) and sdk_installed()

    def problem(self) -> str:
        if not self.api_key:
            return 'no API key (set ANTHROPIC_API_KEY)'
        if not sdk_installed():
            return 'the anthropic package is not installed (pip install "codevigrah[anthropic]")'
        return ''

    def update(self, **values: str) -> None:
        super().update(**values)
        self.model = self.model or DEFAULT_MODEL

    def client(self):
        import anthropic

        with self._lock:
            if self._client is None or self._client_key != self.api_key:
                self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
                self._client_key = self.api_key
            return self._client

    def complete(self, system: str, messages: list[dict], max_tokens: int = 3000, cwd: str | None = None) -> str:
        if not self.available():
            raise LLMError(f'Anthropic API unavailable: {self.problem()}')
        import anthropic

        params = {
            'model': self.model,
            'max_tokens': max(self.max_tokens, max_tokens),
            'system': system,
            'messages': messages,
        }
        if self.effort:
            params['output_config'] = {'effort': self.effort}
        client = self.client()
        try:
            if self.fallbacks and self.model in FALLBACK_MODELS:
                with client.beta.messages.stream(**params, betas=[FALLBACK_BETA], fallbacks='default') as stream:
                    msg = stream.get_final_message()
            else:
                with client.messages.stream(**params) as stream:
                    msg = stream.get_final_message()
        except anthropic.AuthenticationError:
            raise LLMError('Anthropic API: the API key was rejected') from None
        except anthropic.PermissionDeniedError as e:
            raise LLMError(f'Anthropic API: permission denied ({e.message})') from None
        except anthropic.NotFoundError:
            raise LLMError(f'Anthropic API: model {self.model!r} was not found') from None
        except anthropic.RateLimitError:
            raise LLMError('Anthropic API: rate limited, try again in a minute') from None
        except anthropic.BadRequestError as e:
            raise LLMError(f'Anthropic API: bad request ({e.message})') from None
        except anthropic.APIStatusError as e:
            raise LLMError(f'Anthropic API error {e.status_code}: {e.message}') from None
        except anthropic.APIConnectionError as e:
            raise LLMError(f'Anthropic API: network error ({e})') from None
        if msg.stop_reason == 'refusal':
            details = getattr(msg, 'stop_details', None)
            raise LLMError(
                'Anthropic API declined this request'
                + (f' ({details.category})' if details and details.category else '')
            )
        text = ''.join(b.text for b in msg.content if b.type == 'text').strip()
        if not text:
            raise LLMError(f'Anthropic API returned no text (stop reason: {msg.stop_reason})')
        return text
