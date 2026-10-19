#!/usr/bin/env python3
"""A small local text-to-speech server that speaks the OpenAI-style ``/v1/audio/speech`` API.

CodeVigrah (or anything else that speaks that API) sends text and gets audio back. Two engines, both fast enough on
a Raspberry Pi 5 CPU:

* ``kokoro``  Kokoro-82M through kokoro-onnx: the most natural voices. About 1.4x faster than real time on a Pi 5
              with the int8 model, so it is used sentence by sentence and every sentence is cached by the caller.
* ``piper``   Piper voices: lighter, about 9x faster than real time for "medium" voices, a little flatter.

It runs as its own process in its own virtual environment (see README.md), so CodeVigrah itself keeps no
dependencies. Endpoints:

    POST /v1/audio/speech   {"input": "...", "voice": "af_heart", "speed": 1.0, "response_format": "mp3"} -> audio
    GET  /v1/audio/voices   the voices this server can speak, with labels and the license of each voice
    GET  /health
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger('speech-server')
DATA = Path(os.environ.get('SPEECH_DATA', '~/.local/share/codevigrah-speech')).expanduser()
MAX_CHARS = 2000  # per request; callers send a sentence or two at a time
FORMATS = {  # response_format -> (ffmpeg output arguments, content type)
    'mp3': (['-f', 'mp3', '-b:a', '64k'], 'audio/mpeg'),
    'opus': (['-f', 'ogg', '-c:a', 'libopus', '-b:a', '32k'], 'audio/ogg'),
    'aac': (['-f', 'adts', '-b:a', '64k'], 'audio/aac'),
    'flac': (['-f', 'flac'], 'audio/flac'),
}
# Kokoro's English voices, best first (grades from the model's VOICES.md). Other English voices in the voices file
# are listed after these. Kokoro is Apache-2.0, and so are its voices.
KOKORO_PREFERRED = ['af_heart', 'af_bella', 'bf_emma', 'am_michael', 'am_fenrir', 'bm_george', 'bm_fable', 'af_nicole']
ACCENT = {'a': ('en-us', 'US'), 'b': ('en-gb', 'UK')}


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def encode(pcm: bytes, rate: int, fmt: str) -> tuple[bytes, str]:
    """16-bit mono PCM -> the requested format. Without ffmpeg everything is WAV (bigger, but every browser plays it)."""
    if fmt == 'pcm':
        return pcm, 'audio/L16'
    ffmpeg = shutil.which('ffmpeg')
    if fmt not in FORMATS or not ffmpeg:
        return pcm_to_wav(pcm, rate), 'audio/wav'
    args, ctype = FORMATS[fmt]
    cmd = [
        ffmpeg,
        '-hide_banner',
        '-loglevel',
        'error',
        '-f',
        's16le',
        '-ar',
        str(rate),
        '-ac',
        '1',
        '-i',
        '-',
        *args,
        '-',
    ]
    p = subprocess.run(cmd, input=pcm, capture_output=True, timeout=60)
    if p.returncode:
        log.warning('ffmpeg failed (%s); sending WAV', p.stderr.decode(errors='replace')[-200:])
        return pcm_to_wav(pcm, rate), 'audio/wav'
    return p.stdout, ctype


def model_card_license(card: Path) -> str:
    try:
        m = re.search(r'License:\s*(.+)', card.read_text(encoding='utf-8'))
    except OSError:
        return ''
    return m.group(1).strip() if m else ''


class Engines:
    """Loads models on first use and keeps them in memory. Synthesis runs one request at a time: each one already
    uses every CPU core, so running two at once would only make both slower."""

    def __init__(self, data: Path, kokoro_model: str, threads: int, all_voices: bool = False, providers: str = ''):
        self.data = data
        self.kokoro_path = data / 'kokoro' / kokoro_model
        self.threads = threads
        self.all_voices = all_voices
        self.providers = [p.strip() for p in providers.split(',') if p.strip()]
        self._kokoro = None
        self._piper: dict[str, object] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ catalogue
    def piper_models(self) -> dict[str, Path]:
        if importlib.util.find_spec('piper') is None:
            return {}  # piper-tts is optional (setup.sh skips it where it does not install)
        d = self.data / 'piper'
        return {p.name[: -len('.onnx')]: p for p in sorted(d.glob('*.onnx')) if p.with_suffix('.onnx.json').is_file()}

    def kokoro_voice_ids(self) -> list[str]:
        if not self.kokoro_path.is_file():
            return []
        names = self.kokoro().get_voices()
        english = [n for n in names if n[:1] in ACCENT]
        best = [n for n in KOKORO_PREFERRED if n in english]
        return best + sorted(n for n in english if n not in best) if self.all_voices else best

    def voices(self) -> list[dict]:
        out = []
        for v in self.kokoro_voice_ids():
            lang, accent = ACCENT[v[0]]
            gender = 'female' if v[1] == 'f' else 'male'
            out.append(
                {
                    'id': v,
                    'name': f'{v[3:].replace("_", " ").title()} ({accent} {gender}, Kokoro)',
                    'engine': 'kokoro',
                    'lang': lang,
                    'license': 'Apache-2.0',
                }
            )
        for v, path in self.piper_models().items():
            lang, _, rest = v.partition('-')
            speaker, _, quality = rest.rpartition('-')
            accent = {'en_US': 'US', 'en_GB': 'UK'}.get(lang, lang)
            out.append(
                {
                    'id': v,
                    'name': f'{speaker.replace("_", " ").title()} ({accent}, Piper {quality})',
                    'engine': 'piper',
                    'lang': lang.replace('_', '-').lower(),
                    'license': model_card_license(path.with_suffix('.MODEL_CARD')),
                }
            )
        return out

    # ------------------------------------------------------------------ engines
    def kokoro(self):
        if self._kokoro is None:
            import onnxruntime as ort
            from kokoro_onnx import Kokoro

            opts = ort.SessionOptions()
            if self.threads:
                opts.intra_op_num_threads = self.threads
            # CUDA when there is an NVIDIA GPU, else the CPU. CoreML (macOS) is opt-in through --providers: it can be
            # slower than the CPU for this model, which has many dynamic shapes.
            available = ort.get_available_providers()
            providers = [
                p for p in self.providers or ['CUDAExecutionProvider', 'CPUExecutionProvider'] if p in available
            ]
            session = ort.InferenceSession(str(self.kokoro_path), opts, providers=providers)
            self._kokoro = Kokoro.from_session(session, str(self.kokoro_path.parent / 'voices-v1.0.bin'))
            log.info('loaded Kokoro from %s (%s)', self.kokoro_path.name, ', '.join(session.get_providers()))
        return self._kokoro

    def piper(self, voice: str):
        if voice not in self._piper:
            from piper import PiperVoice

            self._piper[voice] = PiperVoice.load(str(self.piper_models()[voice]))
            log.info('loaded Piper voice %s', voice)
        return self._piper[voice]

    def synthesize(self, text: str, voice: str, speed: float) -> tuple[bytes, int]:
        """Return 16-bit mono PCM and its sample rate."""
        with self._lock:
            if voice in self.piper_models():
                from piper import SynthesisConfig

                chunks = list(self.piper(voice).synthesize(text, SynthesisConfig(length_scale=1 / speed)))
                rate = chunks[0].sample_rate if chunks else 22050
                pcm = b''.join(c.audio_int16_bytes for c in chunks)
            elif voice[:1] in ACCENT and voice in self.kokoro().get_voices():
                import numpy as np

                samples, rate = self.kokoro().create(text, voice=voice, speed=speed, lang=ACCENT[voice[0]][0])
                pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
            else:
                raise KeyError(voice)
        return pcm + b'\0\0' * int(rate * 0.12), rate  # a little silence at the end so players never clip the last word


class Handler(BaseHTTPRequestHandler):
    server_version = 'codevigrah-speech/0.1'
    engines: Engines
    api_key = ''

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def reply(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, code: int, message: str) -> None:
        self.reply(code, json.dumps({'error': {'message': message}}).encode(), 'application/json')

    def authorised(self) -> bool:
        return not self.api_key or self.headers.get('Authorization', '') == f'Bearer {self.api_key}'

    def do_GET(self):
        if self.path == '/health':
            return self.reply(200, b'{"ok": true}', 'application/json')
        if not self.authorised():
            return self.error(401, 'missing or wrong API key')
        if self.path.rstrip('/') in ('/v1/audio/voices', '/v1/voices'):
            return self.reply(200, json.dumps({'voices': self.engines.voices()}).encode(), 'application/json')
        self.error(404, 'not found')

    def do_POST(self):
        if not self.authorised():
            return self.error(401, 'missing or wrong API key')
        if self.path.rstrip('/') != '/v1/audio/speech':
            return self.error(404, 'not found')
        size = int(self.headers.get('Content-Length') or 0)
        if size > 64_000:
            return self.error(413, 'request too large')
        try:
            body = json.loads(self.rfile.read(size))
            text = str(body.get('input', '')).strip()
            voice = str(body.get('voice', ''))
            speed = min(2.0, max(0.5, float(body.get('speed') or 1.0)))
            fmt = str(body.get('response_format') or 'mp3')
        except (ValueError, TypeError, AttributeError):
            return self.error(400, 'send a JSON object with input and voice')
        if not text or len(text) > MAX_CHARS:
            return self.error(400, f'input must be 1-{MAX_CHARS} characters')
        t0 = time.time()
        try:
            pcm, rate = self.engines.synthesize(text, voice, speed)
        except KeyError:
            return self.error(400, f'unknown voice {voice!r}; see GET /v1/audio/voices')
        audio, ctype = encode(pcm, rate, fmt)
        seconds = len(pcm) / 2 / rate
        log.info('%s: %d chars -> %.1fs of audio in %.1fs', voice, len(text), seconds, time.time() - t0)
        self.reply(200, audio, ctype)


def main() -> None:
    env = os.environ.get
    ap = argparse.ArgumentParser(description='Local text-to-speech server (OpenAI-style /v1/audio/speech).')
    ap.add_argument('--host', default=env('SPEECH_HOST', '127.0.0.1'), help='default 127.0.0.1 (this machine only)')
    ap.add_argument('--port', type=int, default=int(env('SPEECH_PORT', '8880')))
    ap.add_argument('--data', type=Path, default=DATA, help=f'folder with kokoro/ and piper/ models (default {DATA})')
    ap.add_argument('--kokoro-model', default=env('SPEECH_KOKORO_MODEL', 'kokoro-v1.0.int8.onnx'))
    ap.add_argument('--threads', type=int, default=int(env('SPEECH_THREADS', '0')), help='CPU threads (0 = all)')
    ap.add_argument('--api-key', default=env('SPEECH_API_KEY', ''), help='require "Authorization: Bearer KEY"')
    ap.add_argument('--preload', default=env('SPEECH_PRELOAD', ''), help='voice to load and warm up at start')
    ap.add_argument(
        '--all-voices', action='store_true', help="list all of Kokoro's English voices, not just the best 8"
    )
    ap.add_argument(
        '--providers',
        default=env('SPEECH_PROVIDERS', ''),
        help='onnxruntime execution providers in order (default CUDAExecutionProvider,CPUExecutionProvider)',
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    engines = Engines(args.data.expanduser(), args.kokoro_model, args.threads, args.all_voices, args.providers)
    voices = engines.voices()
    if not voices:
        raise SystemExit(f'No voices found in {args.data}. Run setup.sh first (see README.md).')
    if args.preload:
        engines.synthesize('Ready.', args.preload, 1.0)  # the first run of a model is slow; do it before anyone waits
    Handler.engines, Handler.api_key = engines, args.api_key
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    log.info('%d voices on http://%s:%d/v1 (default %s)', len(voices), args.host, args.port, voices[0]['id'])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
