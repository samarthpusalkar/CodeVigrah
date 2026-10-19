"""Read-aloud: what to say (a listening script) and, optionally, natural voices from a speech server.

* ``text``    written Markdown -> speakable segments without AI, numbered by source line so the page can follow along
* ``listen``  the AI-written listening script for tour chapters (only the voice uses it; the page keeps the written text)
* ``tts``     a client for any OpenAI-style ``/v1/audio/speech`` server, with an on-disk cache per sentence

Without a speech server the browser speaks the same script with its own voices, on the viewer's device.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from ..config import env_int, env_str
from .tts import SpeechEngine, SpeechError

__all__ = ['SpeechEngine', 'SpeechError', 'configure', 'engine']

_engine = SpeechEngine()


def configure(environ: Mapping[str, str] | None = None) -> SpeechEngine:
    """Create the process-wide speech engine from ``CODEVIGRAH_TTS_*`` variables (unset base URL = browser voices only)."""
    global _engine
    env = os.environ if environ is None else environ
    _engine = SpeechEngine(
        base_url=env_str(env, 'CODEVIGRAH_TTS_BASE_URL'),
        api_key=env_str(env, 'CODEVIGRAH_TTS_API_KEY'),
        model=env_str(env, 'CODEVIGRAH_TTS_MODEL', 'kokoro'),
        voice=env_str(env, 'CODEVIGRAH_TTS_VOICE'),
        voices=tuple(v.strip() for v in env_str(env, 'CODEVIGRAH_TTS_VOICES').split(',') if v.strip()),
        fmt=env_str(env, 'CODEVIGRAH_TTS_FORMAT', 'mp3'),
        timeout=env_int(env, 'CODEVIGRAH_TTS_TIMEOUT', 120),
        concurrency=env_int(env, 'CODEVIGRAH_TTS_CONCURRENCY', 1),
    )
    return _engine


def engine() -> SpeechEngine:
    return _engine
