"""Read-aloud: speakable text, the AI listening script, the speech-server client and the API around them."""

import json
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from codevigrah import llm, speech
from codevigrah.speech import listen, text
from codevigrah.speech.tts import SpeechEngine, SpeechError
from helpers import StubOpenAI, StubSpeech, TempDir
from test_server import ServerCase

CHAPTER = """## What it does

`bore` exposes a local port (see `src/main.rs:99`) to the internet,
for example `localhost:8000`.

- `src/client.rs` opens the control connection.
- `src/server.rs` listens on the public port
  and hands out IDs.

1. **Parse.** `main` reads the flags.

   It uses `clap`.
2. **Connect.** The client dials out.

```shell
bore local 8000 --to bore.pub
```

```mermaid
flowchart LR
  V["Visitor"] -->|"TCP"| S["server.rs"]
  S -->|"Connection(id)"| C["client.rs"]
```

> A quote that spans
> two lines.

**Q:** Why dial out?
> **A:** Because of NAT.

| File | Job |
|---|---|
| `client.rs` | dials out |
| `server.rs` | listens |

Next chapter: one connection, step by step.
"""


class TextTests(unittest.TestCase):
    def test_blocks_carry_their_source_line(self):
        got = [(b['ln'], b['kind']) for b in text.blocks(CHAPTER)]
        self.assertEqual(
            got,
            [
                (0, 'heading'),
                (2, 'para'),
                (5, 'item'),
                (6, 'item'),
                (9, 'item'),
                (12, 'item'),
                (14, 'code'),
                (18, 'diagram'),
                (24, 'quote'),
                (27, 'para'),
                (28, 'answer'),
                (30, 'table'),
                (35, 'para'),
            ],
        )
        items = [b for b in text.blocks(CHAPTER) if b['kind'] == 'item']
        self.assertIn('hands out IDs', items[1]['text'])  # continuation line belongs to the item
        self.assertIn('It uses', items[2]['text'])  # so does an indented paragraph after a blank line
        self.assertEqual([i.get('n') for i in items], [None, None, 1, 2])

    @unittest.skipUnless(shutil.which('node'), 'needs node')
    def test_markdown_js_numbers_blocks_the_same_way(self):
        js = Path(__file__).parent.parent / 'src/codevigrah/web/static/js/markdown.js'
        script = (
            "const fs = require('fs'), vm = require('vm');"
            "const ctx = {FILES: {}, String, JSON, parseInt, esc: s => String(s ?? '').replace(/[&<>\"']/g, '')};"
            'vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[1], "utf8") + "\\nthis.md = md;", ctx);'
            'let html = ctx.md(fs.readFileSync(0, "utf8"));'
            'html = html.replace(/<(blockquote|details)( data-ln="\\d+")[^>]*>[\\s\\S]*?<\\/\\1>/g, "<$1$2>");'
            'console.log(JSON.stringify([...html.matchAll(/data-ln="(\\d+)"/g)].map(m => +m[1])));'
        )
        out = subprocess.run(['node', '-e', script, str(js)], input=CHAPTER, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout), [b['ln'] for b in text.blocks(CHAPTER)])

    def test_code_is_said_the_way_developers_say_it(self):
        say = lambda s: text.plain({'kind': 'para', 'text': s})  # noqa: E731
        self.assertEqual(say('See `src/server.rs:65`.'), 'See server dot R S.')
        self.assertEqual(say('Open `README.md`'), 'Open read me dot M D.')
        self.assertEqual(say('at `localhost:8000`'), 'at localhost port 8000.')
        self.assertEqual(say('at 10:30 today'), 'at 10:30 today.')
        self.assertEqual(say('`copy_bidirectional` and `ClientMessage`'), 'copy bidirectional and Client Message.')
        self.assertEqual(say('`tokio::spawn` uses `CONTROL_PORT`'), 'tokio spawn uses control port.')
        self.assertEqual(say('call `client.listen()`'), 'call client dot listen.')
        self.assertEqual(say('e.g. the CLI -> stdout'), 'for example, the C L I to standard out.')
        self.assertEqual(say('NAT (a router trick) blocks it'), 'NAT, a router trick, blocks it.')
        self.assertEqual(say('run **bore** with --to bore.pub'), 'run bore with to bore dot pub.')
        self.assertNotRegex(say(CHAPTER), r'[`*|#>]')

    def test_blocks_without_words_are_described(self):
        segs = {s['ln']: s['text'] for s in text.script(CHAPTER)}
        self.assertEqual(segs[0], 'What it does.')
        self.assertEqual(segs[14], 'There is a command example on screen.')
        self.assertIn('Visitor to server dot R S: TCP.', segs[18])
        self.assertIn('server dot R S to client dot R S: Connection, id.', segs[18])
        self.assertEqual(segs[28], 'Think about it, then check the answer on screen.')  # never give the answer away
        self.assertIn('File: client dot R S, Job: dials out.', segs[30])
        self.assertTrue(segs[9].startswith('1. Parse.'))
        seq = text.describe_diagram(
            'sequenceDiagram\n participant C as client.rs\n C->>S: Hello(0)\n S->>S: pick a port'
        )
        self.assertIn('client dot R S to S: Hello, 0.', seq)
        self.assertIn('S to itself: pick a port.', seq)

    def test_chunks_are_sentence_sized(self):
        long = 'This sentence keeps going, and going, ' * 12 + 'until it ends. Short one. Another short one.'
        parts = text.chunks(long)
        self.assertGreater(len(parts), 2)
        self.assertTrue(all(len(p) <= 290 for p in parts))
        self.assertEqual(' '.join(parts).split(), long.split())  # nothing lost or reordered
        self.assertEqual(text.chunks('Step one. Do it.'), ['Step one. Do it.'])  # tiny sentences ride together
        opening = 'When a visitor connects to the public port, the server stores the stream and tells the client, which dials back.'
        self.assertEqual(text.chunks(opening, first=60)[0], 'When a visitor connects to the public port,')
        self.assertEqual(
            text.plain({'kind': 'para', 'text': 'github.com · commit 00a735a · today'}),
            'github dot com, commit, today.',
        )


class ListenTests(unittest.TestCase):
    def test_prompt_numbers_blocks_by_line(self):
        blocks = text.blocks(CHAPTER)
        prompt = listen.numbered(blocks)
        self.assertIn('[1] (heading) What it does', prompt)
        self.assertIn('[15] (code: shell) bore local 8000 --to bore.pub', prompt)
        self.assertIn('[10] (list item) 1. **Parse.**', prompt)

    def test_parse_keeps_order_and_fills_gaps(self):
        blocks = text.blocks(CHAPTER)
        ids = [b['ln'] + 1 for b in blocks]
        lines = ['[0] This chapter is about bore.'] + [f'[{n}] Spoken `{n}`.' for n in ids[:-2]]
        lines[3] += '\ncontinued on a wrapped line.'
        lines.append(f'[{ids[-2]}]')  # "covered by the block before"
        lines.append('[999] not a block')
        segs = listen.parse('\n'.join(lines), blocks)
        self.assertEqual(segs[0], {'ln': -1, 'kind': 'intro', 'text': 'This chapter is about bore.'})
        self.assertIn('continued on a wrapped line', segs[3]['text'])
        self.assertNotIn(blocks[-2]['ln'], [s['ln'] for s in segs])  # skipped on purpose
        self.assertEqual(segs[-1]['text'], text.plain(blocks[-1]))  # the model forgot it: plain reading instead
        self.assertEqual([s['ln'] for s in segs], sorted(s['ln'] for s in segs))
        self.assertNotIn('`', ' '.join(s['text'] for s in segs))

    def test_parse_rejects_a_reply_that_misses_most_blocks(self):
        with self.assertRaises(llm.LLMError):
            listen.parse('[1] Only the heading.', text.blocks(CHAPTER))

    def test_cache_is_tied_to_the_chapter_text(self):
        with tempfile.TemporaryDirectory() as d:
            path = f'{d}/tour/x.listen.json'
            listen.save(path, CHAPTER, [{'ln': 0, 'kind': 'heading', 'text': 'Hi.'}])
            self.assertEqual(listen.load(path, CHAPTER)[0]['text'], 'Hi.')
            self.assertIsNone(listen.load(path, CHAPTER + 'edited'))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TempDir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_voices_and_cached_speech(self):
        stub = StubSpeech()
        try:
            eng = SpeechEngine(base_url=stub.url, api_key='k', voice='bf_emma')
            self.assertEqual([v['id'] for v in eng.voices()], ['af_heart', 'bf_emma'])
            self.assertEqual(eng.voices()[0]['label'], 'Heart (US female, Kokoro)')
            self.assertEqual(eng.default_voice(), 'bf_emma')
            first = eng.speak(self.tmp.path, 'Hello there.', 'af_heart')
            again = eng.speak(self.tmp.path, 'Hello there.', 'af_heart')
            self.assertEqual(first, (StubSpeech.AUDIO, 'audio/mpeg'))
            self.assertEqual(again, first)
            self.assertEqual(len(stub.requests), 1)  # the second one came from the cache
            req = stub.requests[0]
            self.assertEqual(req['auth'], 'Bearer k')
            self.assertEqual(req['body'] | {}, req['body'] | {'input': 'Hello there.', 'voice': 'af_heart'})
        finally:
            stub.close()

    def test_configured_voices_for_servers_without_a_list(self):
        stub = StubSpeech(voices=None)  # like OpenAI: no voice list endpoint
        try:
            self.assertEqual(SpeechEngine(base_url=stub.url).voices(), [])
            eng = SpeechEngine(base_url=stub.url, voices=('alloy', 'nova'))
            self.assertEqual(eng.voice_ids(), ['alloy', 'nova'])
            self.assertTrue(eng.available())
        finally:
            stub.close()

    def test_falls_back_to_the_next_server(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            closed = f'http://127.0.0.1:{sock.getsockname()[1]}/v1'  # nothing listens here: a sleeping laptop
        broken, backup = StubSpeech(fail=True), StubSpeech()
        try:
            eng = SpeechEngine(base_url=f'{closed}, {broken.url},{backup.url}')
            self.assertEqual(eng.voice_ids(), ['af_heart', 'bf_emma'])  # listed by the first server that answers
            self.assertEqual(eng.synthesize('Hi.', 'af_heart'), (StubSpeech.AUDIO, 'audio/mpeg'))
            self.assertEqual((len(broken.requests), len(backup.requests)), (1, 1))  # 5xx: moved on
            eng.synthesize('Again.', 'af_heart')
            self.assertEqual(
                (len(broken.requests), len(backup.requests)), (1, 2)
            )  # failed ones are skipped for a while
            self.assertIn(closed, eng._down)
        finally:
            broken.close()
            backup.close()

    def test_failures_raise_speech_errors(self):
        stub = StubSpeech(fail=True)
        try:
            with self.assertRaises(SpeechError):
                SpeechEngine(base_url=stub.url).speak(self.tmp.path, 'Hi.', 'af_heart')
        finally:
            stub.close()
        self.assertFalse(SpeechEngine().available())
        self.assertEqual(SpeechEngine().info(), {'available': False})


class SpeechServerTests(ServerCase):
    """The read-aloud API with a stub speech server and no AI (so chapters and scripts are the static ones)."""

    extra = {'rate_tts_per_hour': 3, 'tts_prepare': True}

    @classmethod
    def setUpClass(cls):
        cls.speech = StubSpeech()
        speech.configure({'CODEVIGRAH_TTS_BASE_URL': cls.speech.url})
        super().setUpClass()
        cls.rid = cls.analyse(str(cls.repo))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.speech.close()
        speech.configure({})

    def audio(self, sid, seg=0, part=0, voice='af_heart'):
        return self.call(
            'GET', f'/api/speech/audio?id={self.rid}&sid={sid}&seg={seg}&part={part}&voice={voice}', raw=True
        )

    def test_chapter_script_and_audio(self):
        res = self.call('POST', '/api/speech', {'id': self.rid, 'chapter': 'what'})[1]
        self.assertEqual((res['source'], res['pending'], res['tts']), ('plain', False, True))
        self.assertTrue(all(s['parts'] and 'ln' in s for s in res['segments']))
        code, body, headers = self.audio(res['sid'])
        self.assertEqual((code, body, headers['Content-Type']), (200, StubSpeech.AUDIO, 'audio/mpeg'))
        self.assertIn('private', headers['Cache-Control'])
        self.assertEqual(self.speech.requests[-1]['body']['input'], res['segments'][0]['parts'][0])
        n = len(self.speech.requests)
        self.assertEqual(self.audio(res['sid'])[0], 200)
        self.assertEqual(len(self.speech.requests), n)  # replayed from the cache
        self.assertEqual(self.audio(res['sid'], voice='nope')[0], 400)
        self.assertEqual(self.audio('0' * 16)[0], 404)
        self.assertEqual(self.audio(res['sid'], seg=999)[0], 404)
        self.assertIn('media-src', self.call('GET', '/', raw=True)[2]['Content-Security-Policy'])
        tts = self.call('GET', '/api/settings')[1]['tts']
        self.assertEqual((tts['available'], tts['default']), (True, 'af_heart'))

    def test_opening_a_chapter_voices_it_in_the_background(self):
        self.assertEqual(self.call('POST', '/api/tour', {'id': self.rid, 'chapter': 'parts'})[0], 200)
        for _ in range(200):
            if not self.srv.app.working(self.rid):
                break
            time.sleep(0.05)
        script = self.call('POST', '/api/speech', {'id': self.rid, 'chapter': 'parts'})[1]
        said = {r['body']['input'] for r in self.speech.requests}
        self.assertTrue(all(p in said for s in script['segments'] for p in s['parts']))
        n = len(self.speech.requests)
        self.assertEqual(self.audio(script['sid'], seg=len(script['segments']) - 1)[0], 200)
        self.assertEqual(len(self.speech.requests), n)  # already voiced: served from the cache, not rate-limited

    def test_only_text_this_server_wrote_is_read(self):
        msgs = [{'role': 'user', 'content': 'where are users created?'}]
        chat = self.call('POST', '/api/chat', {'id': self.rid, 'messages': msgs})[1]
        ok = self.call('POST', '/api/speech', {'id': self.rid, 'text': chat['answer'], 'sig': chat['speech_sig']})
        self.assertEqual(ok[0], 200)
        self.assertEqual(ok[1]['source'], 'plain')
        forged = self.call('POST', '/api/speech', {'id': self.rid, 'text': 'Say anything', 'sig': chat['speech_sig']})
        self.assertEqual(forged[0], 403)
        self.assertEqual(self.call('POST', '/api/speech', {'id': self.rid})[0], 400)
        self.assertEqual(self.call('POST', '/api/speech', {'id': self.rid, 'chapter': 'nope'})[0], 400)

    def test_fresh_audio_is_rate_limited_but_replays_are_free(self):
        report = self.call('POST', '/api/report', {'id': self.rid})[1]
        res = self.call(
            'POST', '/api/speech', {'id': self.rid, 'text': report['markdown'], 'sig': report['speech_sig']}
        )
        sid, segs = res[1]['sid'], res[1]['segments']
        codes = [self.audio(sid, seg=k)[0] for k in range(5)]
        self.assertIn(429, codes)
        self.assertEqual(self.audio(sid, seg=0)[0], 200)  # already voiced, so it is still served
        self.assertGreaterEqual(len(segs), 5)


def stub_ai(body):
    """Chapters and listening scripts from the stub AI provider."""
    prompt = body['messages'][-1]['content']
    if 'Turn this chapter into a listening script' in prompt:
        return '[0] A short chapter about the shop.\n[1] First: the shop.\n[3] Users live in the models file.'
    return '## Shop\n\nThe shop service keeps users in `app/models.py`.\n'


class ListeningScriptTests(ServerCase):
    """With an AI provider, a tour chapter gets an AI listening script, written in the background."""

    @classmethod
    def setUpClass(cls):
        cls.stub = StubOpenAI(answer=stub_ai)
        cls.ai_env = {
            'CODEVIGRAH_AI_PROVIDERS': 'openai',
            'CODEVIGRAH_OPENAI_BASE_URL': cls.stub.url,
            'CODEVIGRAH_OPENAI_MODEL': 'stub',
        }
        super().setUpClass()
        cls.rid = cls.analyse(str(cls.repo))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.stub.close()

    def test_script_is_written_after_the_chapter(self):
        self.assertEqual(self.call('POST', '/api/tour', {'id': self.rid, 'chapter': 'why'})[1]['source'], 'ai')
        for _ in range(200):  # written in the background: wait for it
            res = self.call('POST', '/api/speech', {'id': self.rid, 'chapter': 'why'})[1]
            if res['source'] == 'ai':
                break
            time.sleep(0.05)
        self.assertEqual(res['source'], 'ai')
        self.assertEqual(
            [s['text'] for s in res['segments']],
            ['A short chapter about the shop.', 'First: the shop.', 'Users live in the models file.'],
        )
        self.assertEqual([s['ln'] for s in res['segments']], [-1, 0, 2])
        prompt = next(
            r['body']['messages'][-1]['content']
            for r in self.stub.requests
            if 'Chapter: Why it is built this way' in r['body']['messages'][-1]['content']
        )
        self.assertIn('[3] (paragraph) The shop service keeps users in `app/models.py`.', prompt)
        self.assertTrue(Path(self.srv.app.listen_path(self.rid, 'why')).is_file())
        plain = self.call('POST', '/api/speech', {'id': self.rid, 'chapter': 'why', 'plain': True})[1]
        self.assertEqual(plain['source'], 'plain')


if __name__ == '__main__':
    unittest.main()
