#!/usr/bin/env bash
# Install the speech server: a virtual environment, Kokoro, and two Piper voices. Safe to run again.
#   ./setup.sh                  everything into ~/.local/share/codevigrah-speech
#   SPEECH_DATA=/srv/speech ./setup.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
data="${SPEECH_DATA:-$HOME/.local/share/codevigrah-speech}"
python="${PYTHON:-python3}"
mkdir -p "$data/kokoro" "$data/piper"
if ! "$python" -c 'import sys; sys.exit(not (3, 10) <= sys.version_info[:2] < (3, 14))'; then
  echo "Kokoro needs Python 3.10 to 3.13 ($python is $("$python" -V 2>&1))."
  echo "Run again with e.g. PYTHON=python3.13 (on a Mac: brew install python@3.13)."
  exit 1
fi

if [ ! -x "$data/venv/bin/python" ]; then
  echo "creating $data/venv"
  "$python" -m venv "$data/venv"
fi
"$data/venv/bin/pip" install --quiet --upgrade pip
"$data/venv/bin/pip" install --quiet "$(grep '^kokoro-onnx' "$here/requirements.txt" | cut -d' ' -f1)"
# Piper is optional: if it has no package for this machine, Kokoro still works on its own.
"$data/venv/bin/pip" install --quiet "$(grep '^piper-tts' "$here/requirements.txt" | cut -d' ' -f1)" \
  || echo "note: piper-tts did not install here; only the Kokoro voices will be offered"

fetch() {  # url file: download unless the file is already there
  if [ ! -s "$2" ]; then echo "downloading $(basename "$2")"; curl -fL --progress-bar -o "$2.part" "$1" && mv "$2.part" "$2"; fi
}
kokoro=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
fetch "$kokoro/kokoro-v1.0.int8.onnx" "$data/kokoro/kokoro-v1.0.int8.onnx"
fetch "$kokoro/voices-v1.0.bin" "$data/kokoro/voices-v1.0.bin"

# Piper voices with permissive licenses (each MODEL_CARD names its dataset and license).
piper=https://huggingface.co/rhasspy/piper-voices/resolve/main
for v in en/en_GB/cori/high en/en_US/libritts_r/medium ${PIPER_VOICES:-}; do
  name=$(echo "$v" | awk -F/ '{print $2"-"$3"-"$4}')
  fetch "$piper/$v/$name.onnx" "$data/piper/$name.onnx"
  fetch "$piper/$v/$name.onnx.json" "$data/piper/$name.onnx.json"
  fetch "$piper/$v/MODEL_CARD" "$data/piper/$name.MODEL_CARD"
done

command -v ffmpeg >/dev/null || echo "note: ffmpeg not found; audio will be sent as WAV (about 10x bigger than MP3)"
echo
echo "Done. Start it with:"
echo "  $data/venv/bin/python $here/speech_server.py --preload af_heart"
echo "then set CODEVIGRAH_TTS_BASE_URL=http://127.0.0.1:8880/v1 for CodeVigrah."
