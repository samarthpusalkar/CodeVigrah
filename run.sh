#!/usr/bin/env bash
# Start CodeVigrah from a source checkout, without installing anything.
#   ./run.sh                     http://127.0.0.1:8765
#   ./run.sh --host 0.0.0.0      reachable from other devices on your network
#   ./run.sh --help              all options (settings can also come from .env, see .env.example)
set -euo pipefail
cd "$(dirname "$0")"
PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m codevigrah "$@"
