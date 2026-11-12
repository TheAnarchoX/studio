#!/bin/sh
# Install Studio from this folder on macOS or Linux: a virtual environment in .venv, then a launcher
# (~/Applications/Studio.app on macOS, an app-menu entry on Linux).
#   ./install.sh            install or update
#   ./install.sh --desktop  also put a launcher on the desktop
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Studio needs Python 3.11 or newer: https://www.python.org/downloads/" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  if [ "$(uname)" = "Linux" ]; then
    # system site-packages, so a distro's GTK bindings (python3-gi) can give Studio its own window
    "$PY" -m venv --system-site-packages .venv
  else
    "$PY" -m venv .venv
  fi
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e ".[app]" || .venv/bin/python -m pip install --quiet -e .
.venv/bin/studio install "$@"

if ! command -v google-chrome >/dev/null 2>&1 && ! command -v chromium >/dev/null 2>&1 \
   && ! command -v chromium-browser >/dev/null 2>&1 && ! command -v microsoft-edge >/dev/null 2>&1 \
   && [ ! -d "/Applications/Google Chrome.app" ] && [ ! -d "/Applications/Chromium.app" ] && [ ! -d "/Applications/Microsoft Edge.app" ]; then
  echo
  echo "Note: Studio renders images with Chrome, Chromium or Edge, and none was found. Install one, or set its path in Settings."
fi

echo
echo "Studio is installed. Open it from your applications, or run: $(pwd)/.venv/bin/studio"
echo "Connect Claude Code:  claude mcp add studio --scope user -- $(pwd)/.venv/bin/studio mcp"
