#!/bin/bash
# Delta en el móvil (web aparte en 127.0.0.1:7877). Independiente de run.sh: arrancarlo o pararlo no toca a Delta.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/delta-movil.lock"
flock -n 9 || { echo "Delta móvil ya está en marcha."; exit 0; }
[ -t 1 ] || exec >> "$DIR/delta_movil.log" 2>&1
[ -n "$GEMINI_API_KEY" ] || eval "$(grep -m1 '^export GEMINI_API_KEY=' "$HOME/.bashrc")"
export PYTHONUNBUFFERED=1
exec "$DIR/.venv/bin/python3" "$DIR/delta_movil.py"
