#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if [ ! -x ".venv/bin/python" ]; then
  printf '%s\n' "Virtual environment not found. Run: bash setup.sh"
  exit 1
fi

exec .venv/bin/python main.py