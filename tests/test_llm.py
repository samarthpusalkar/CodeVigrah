import unittest

from codevigrah import llm
from codevigrah.llm import Router, parse_order, providers_from_env
from codevigrah.llm.anthropic_api import AnthropicProvider
from codevigrah.llm.base import LLMError, Provider, strip_reasoning
from codevigrah.llm.claude_cli import ClaudeCodeProvider
from codevigrah.llm.openai_compat import OpenAICompatProvider
from helpers import StubOpenAI


class Fake(Provider):
    def __init__(self, name, ok=True, reads_files=False, up=True):
        self.name, self.label, self.ok, self.reads_files, self.up = name, name, ok, reads_files, up
        self.calls = []

    def available(self):
        return self.up

    def complete(self, system, messages, max_tokens=3000, cwd=None):
        self.calls.append(messages)
        if not self.ok:
            raise LLMError(f'{self.name} failed')
        return f'answer from {self.name}'


MSG = [{'role': 'user', 'content': 'question'}]


class RouterTests(unittest.TestCase):
    def test_order_parsing(self):
        self.assertEqual(parse_order('auto'), 'auto')
        self.assertEqual(parse_order(''), 'auto')
        self.assertEqual(parse_order('off'), [])
        self.assertEqual(parse_order('ollama, groq,ollama'), ['ollama', 'groq'])
        with self.assertRaises(ValueError):
            parse_order('ollama,gpt')

    def test_fallback_to_next_provider(self):
        a, b = Fake('anthropic', ok=False), Fake('ollama')
        r = Router({'anthropic': a, 'ollama': b}, order=['anthropic', 'ollama'])
        self.assertEqual(r.complete('sys', MSG), 'answer from ollama')
        self.assertEqual(len(a.calls), 1)

    def test_all_failing_reports_every_error(self):
        r = Router(
            {'anthropic': Fake('anthropic', ok=False), 'ollama': Fake('ollama', ok=False)},
            order=['anthropic', 'ollama'],
        )
        with self.assertRaisesRegex(LLMError, 'anthropic failed.*ollama failed'):
            r.complete('sys', MSG)

    def test_unavailable_providers_are_skipped(self):
        r = Router({'anthropic': Fake('anthropic', up=False), 'ollama': Fake('ollama')}, order='auto')
        self.assertEqual(r.describe(), 'ollama')
        r = Router({'anthropic': Fake('anthropic', up=False)}, order='auto')
        self.assertFalse(r.available())
        with self.assertRaisesRegex(LLMError, 'No AI provider'):
            r.complete('sys', MSG)

    def test_context_only_for_providers_that_cannot_read_files(self):
        reader, plain = Fake('claude-cli', reads_files=True), Fake('ollama')
        calls = []

        def ctx():
            calls.append(1)
            return 'EXCERPTS'

        Router({'claude-cli': reader}, order=['claude-cli']).complete('sys', MSG, context=ctx)
        self.assertEqual(reader.calls[0], MSG)
        self.assertEqual(calls, [])  # never computed when nobody needs it
        Router({'ollama': plain}, order=['ollama']).complete('sys', MSG, context=ctx)
        self.assertIn('EXCERPTS', plain.calls[0][-1]['content'])

    def test_public_auto_never_uses_the_owners_claude_login(self):
        cli = Fake('claude-cli', reads_files=True)
        self.assertFalse(Router({'claude-cli': cli}, order='auto', public=True).available())
        self.assertTrue(Router({'claude-cli': cli}, order=['claude-cli'], public=True).available())

    def test_settings_never_expose_keys(self):
        provs = providers_from_env({'ANTHROPIC_API_KEY': 'sk-ant-secret', 'GROQ_API_KEY': 'gsk-secret'})
        r = Router(provs)
        text = repr(r.settings())
        self.assertNotIn('secret', text)
        groq = next(p for p in r.settings()['providers'] if p['name'] == 'groq')
        self.assertTrue(groq['has_key'])

    def test_update_from_settings_dialog(self):
        r = Router(providers_from_env({}))
        r.update({'provider': 'ollama', 'model': 'qwen2.5-coder:14b', 'api_key': '', 'order': 'ollama,claude-cli'})
        self.assertEqual(r.providers['ollama'].model, 'qwen2.5-coder:14b')
        self.assertEqual(r.order, ['ollama', 'claude-cli'])
        r.update({'provider': 'groq', 'api_key': 'k1'})
        r.update({'provider': 'groq', 'api_key': ''})  # empty means keep
        self.assertEqual(r.providers['groq'].api_key, 'k1')
        with self.assertRaises(ValueError):
            r.update({'provider': 'nope'})


class ProviderTests(unittest.TestCase):
    def test_env_configuration(self):
        p = providers_from_env(
            {'CODEVIGRAH_OLLAMA_MODEL': 'llama3', 'CODEVIGRAH_GROQ_MODEL': 'm', 'CODEVIGRAH_AI_PROVIDERS': 'x'}
        )
        self.assertTrue(p['ollama'].available())
        self.assertEqual(p['ollama'].base_url, 'http://localhost:11434/v1')
        self.assertFalse(p['groq'].available())  # Groq needs a key
        self.assertEqual(p['groq'].problem(), 'no API key')
        self.assertEqual(p['anthropic'].model, 'claude-opus-5-5')

    def test_missing_cli_is_reported(self):
        p = ClaudeCodeProvider(binary='definitely-not-installed-claude')
        self.assertFalse(p.available())
        with self.assertRaises(LLMError):
            p.complete('s', MSG)

    def test_anthropic_without_key(self):
        p = AnthropicProvider(api_key='')
        self.assertFalse(p.available())
        self.assertIn('ANTHROPIC_API_KEY', p.problem())

    def test_strip_reasoning(self):
        self.assertEqual(strip_reasoning('<think>hmm\nlong</think>\n\nThe answer.'), 'The answer.')

    def test_openai_compatible_round_trip(self):
        stub = StubOpenAI(answer='<think>x</think>Hello from the stub')
        try:
            p = OpenAICompatProvider('groq', base_url=stub.url, api_key='k', model='m')
            self.assertEqual(p.complete('be brief', MSG, 100), 'Hello from the stub')
            req = stub.requests[0]
            self.assertEqual(req['path'], '/v1/chat/completions')
            self.assertEqual(req['auth'], 'Bearer k')
            self.assertEqual(req['body']['messages'][0], {'role': 'system', 'content': 'be brief'})
            self.assertEqual(req['body']['max_tokens'], 100)
        finally:
            stub.close()

    def test_openai_compatible_errors(self):
        stub = StubOpenAI(fail=True)
        try:
            with self.assertRaisesRegex(LLMError, 'error 500'):
                OpenAICompatProvider('ollama', base_url=stub.url, model='m').complete('s', MSG)
        finally:
            stub.close()
        with self.assertRaisesRegex(LLMError, 'cannot reach'):
            OpenAICompatProvider('ollama', base_url='http://127.0.0.1:9/v1', model='m', timeout=2).complete('s', MSG)

    def test_module_level_configure(self):
        llm.configure({'CODEVIGRAH_AI_PROVIDERS': 'off'})
        self.assertFalse(llm.available())
        self.assertIsNone(llm.describe())


if __name__ == '__main__':
    unittest.main()
