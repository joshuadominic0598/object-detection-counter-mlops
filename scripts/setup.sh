#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" = "--local" ]; then
    if [ ! -f .env ]; then
        cp .env.example .env
    fi
    HOST_PYTHON="${HOST_PYTHON:-python3}"
    "$HOST_PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Host workflows require Python 3.10+; set HOST_PYTHON to that interpreter"'
    if [ ! -d .venv ]; then
        "$HOST_PYTHON" -m venv .venv
    fi
    .venv/bin/python -m pip install -r requirements.txt
    exit 0
fi
python3 scripts/containers.py setup
