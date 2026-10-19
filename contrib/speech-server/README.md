# Speech server

Natural voices for CodeVigrah's read-aloud, made on your own machine. A small HTTP server that speaks the OpenAI-style
`/v1/audio/speech` API, with two engines that run on a Raspberry Pi 5 CPU:

* **Kokoro-82M** (int8, through `kokoro-onnx`): the most natural voices; slightly faster than real time on a Pi 5.
* **Piper**: lighter and several times faster ("medium" voices), a little flatter.

It lives in `contrib/` because it is optional and separate: it runs in its own virtual environment, and CodeVigrah only talks
to it over HTTP, so CodeVigrah itself keeps no dependencies. See [docs/speech.md](../../docs/speech.md) for how read-aloud
uses it and for measured speeds.

## Install and run

```bash
./setup.sh                    # venv, Kokoro and two Piper voices into ~/.local/share/codevigrah-speech (about 500 MB)
~/.local/share/codevigrah-speech/venv/bin/python speech_server.py --preload af_heart
```

Then start CodeVigrah with `CODEVIGRAH_TTS_BASE_URL=http://127.0.0.1:8880/v1`. As a service: copy
`codevigrah-speech.service` to `~/.config/systemd/user/`, fix the two paths in it, then
`systemctl --user daemon-reload && systemctl --user enable --now codevigrah-speech`.

| Option | Environment | Default | |
|---|---|---|---|
| `--host` | `SPEECH_HOST` | `127.0.0.1` | keep it local unless another machine runs CodeVigrah |
| `--port` | `SPEECH_PORT` | `8880` | the same port as Kokoro-FastAPI, so either can be swapped in |
| `--data` | `SPEECH_DATA` | `~/.local/share/codevigrah-speech` | holds `kokoro/` and `piper/` |
| `--kokoro-model` | `SPEECH_KOKORO_MODEL` | `kokoro-v1.0.int8.onnx` | `kokoro-v1.0.fp16.onnx` is a little better and slower |
| `--threads` | `SPEECH_THREADS` | all cores | |
| `--api-key` | `SPEECH_API_KEY` | none | require `Authorization: Bearer KEY` |
| `--preload` | `SPEECH_PRELOAD` | none | voice to load and warm up at start |
| `--all-voices` | | off | list all 28 English Kokoro voices, not just the best 8 |
| `--providers` | `SPEECH_PROVIDERS` | CUDA if present, else CPU | e.g. `CoreMLExecutionProvider,CPUExecutionProvider` to try Apple's CoreML |

## On a Mac (Apple Silicon), for the Pi to use

A Mac with an M-series chip voices sentences much faster than a Pi. Run the server there and let CodeVigrah on the Pi use it,
with the Pi's own server as the fallback for when the Mac is asleep:

```bash
# on the Mac
brew install python@3.13 ffmpeg                      # Kokoro needs Python 3.10-3.13; ffmpeg makes MP3 instead of WAV
git clone https://github.com/samarthpusalkar/CodeVigrah.git && cd CodeVigrah   # the speech-server folder is all it needs
PYTHON=python3.13 contrib/speech-server/setup.sh
KEY=$(openssl rand -hex 16); echo "$KEY"             # a shared secret, so nothing else on the network can use it
caffeinate -is ~/.local/share/codevigrah-speech/venv/bin/python contrib/speech-server/speech_server.py \
  --host 0.0.0.0 --api-key "$KEY" --preload af_heart  # caffeinate: no idle sleep while it runs (on power)
```

macOS asks once whether Python may accept incoming connections: allow it. The Mac's network name is in System Settings →
General → Sharing (for example `my-mac.local`). Then, in CodeVigrah's `.env` on the Pi (git ignores that file):

```bash
CODEVIGRAH_TTS_BASE_URL=http://my-mac.local:8880/v1,http://127.0.0.1:8880/v1   # Mac first, the Pi's own server second
CODEVIGRAH_TTS_API_KEY=the-key-printed-above                                     # the Pi's server ignores it
```

A server that does not answer is skipped for a minute, so closing the laptop only costs one two-second check. Both servers
make the same audio for the same voice, and CodeVigrah caches it per sentence, so it does not matter which one voiced it.
Each sentence is logged with how long it took, so you can compare the two machines.

More Piper voices: `PIPER_VOICES="en/en_US/lessac/medium" ./setup.sh` (paths as in
[rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)). Check each voice's `MODEL_CARD` for its license first.

## API

```bash
curl -s localhost:8880/v1/audio/voices
curl -s localhost:8880/v1/audio/speech -H 'Content-Type: application/json' \
  -d '{"input": "Hello from the Pi.", "voice": "af_heart", "response_format": "mp3"}' -o hello.mp3
```

`response_format` is `mp3` (default), `opus`, `aac`, `flac`, `wav` or `pcm`; everything except WAV and PCM needs `ffmpeg`.
Requests are voiced one at a time, because each one already uses every CPU core.

## Licenses

This server's own code is MIT, like the rest of CodeVigrah. What it installs keeps its own license: `kokoro-onnx` (MIT),
the Kokoro-82M weights and voices (Apache-2.0), `onnxruntime` (MIT), `piper-tts` and espeak-ng (GPL-3.0). Because they run in
this separate process and are installed by you, CodeVigrah does not include or distribute them.
