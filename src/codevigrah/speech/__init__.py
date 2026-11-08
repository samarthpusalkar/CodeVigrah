"""Read-aloud: what to say (a listening script) and, optionally, natural voices from a speech server.

* ``text``    written Markdown -> speakable segments without AI, numbered by source line so the page can follow along
* ``listen``  the AI-written listening script for tour chapters (only the voice uses it; the page keeps the written text)
* ``tts``     a client for OpenAI-style ``/v1/audio/speech`` servers, in order of preference, with an on-disk cache per
              sentence

Without a speech server the browser speaks the same script with its own voices, on the viewer's device.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from ..config import env_int, env_str, ollama_base_url
from .tts import SpeechEngine, SpeechError, SpeechServer

__all__ = ['SpeechEngine', 'SpeechError', 'SpeechServer', 'configure', 'engine']

_engine = SpeechEngine()


OLLAMA_TTS_MODEL = 'phonon'  # Ollama's speech model; on Linux it needs Ollama's MLX package (lfm3-audio does not)


def _list(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(',') if v.strip())


def configure(environ: Mapping[str, str] | None = None) -> SpeechEngine:
    """Create the process-wide speech engine from ``CODEVIGRAH_TTS_*`` variables (unset base URL = browser voices only).

    ``CODEVIGRAH_TTS_BASE_URL`` lists the speech servers, best first. The word ``ollama`` stands for the Ollama server
    in ``OLLAMA_HOST`` (or ``CODEVIGRAH_OLLAMA_BASE_URL``) and takes its own ``CODEVIGRAH_TTS_OLLAMA_*`` settings
    (model ``phonon``, WAV audio); every other server uses ``CODEVIGRAH_TTS_MODEL``, ``_VOICE``, ``_VOICES``,
    ``_FORMAT`` and ``_API_KEY``. So ``ollama,http://127.0.0.1:8880/v1`` means Phonon first and Kokoro when Ollama is
    not answering; the device's own voices remain the last resort in the browser.
    """
    global _engine
    env = os.environ if environ is None else environ
    timeout = env_int(env, 'CODEVIGRAH_TTS_TIMEOUT', 120)
    servers = []
    for url in _list(env_str(env, 'CODEVIGRAH_TTS_BASE_URL')):
        if url.lower() == 'ollama':
            servers.append(
                SpeechServer(
                    ollama_base_url(env, 'http://127.0.0.1:11434/v1'),
                    model=env_str(env, 'CODEVIGRAH_TTS_OLLAMA_MODEL', OLLAMA_TTS_MODEL),
                    voice=env_str(env, 'CODEVIGRAH_TTS_OLLAMA_VOICE'),
                    voices=_list(env_str(env, 'CODEVIGRAH_TTS_OLLAMA_VOICES')),
                    fmt='wav',  # Ollama makes WAV or PCM, not MP3
                    timeout=timeout,
                )
            )
        else:
            servers.append(
                SpeechServer(
                    url,
                    model=env_str(env, 'CODEVIGRAH_TTS_MODEL', 'kokoro'),
                    voice=env_str(env, 'CODEVIGRAH_TTS_VOICE'),
                    voices=_list(env_str(env, 'CODEVIGRAH_TTS_VOICES')),
                    api_key=env_str(env, 'CODEVIGRAH_TTS_API_KEY'),
                    fmt=env_str(env, 'CODEVIGRAH_TTS_FORMAT', 'mp3'),
                    timeout=timeout,
                )
            )
    _engine = SpeechEngine(servers, concurrency=env_int(env, 'CODEVIGRAH_TTS_CONCURRENCY', 1))
    return _engine


def engine() -> SpeechEngine:
    return _engine
