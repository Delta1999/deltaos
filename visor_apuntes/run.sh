#!/usr/bin/env bash
# Script de inicio para el Visor y Editor de Apuntes Manos Libres
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

VENV="../.venv"

if [ -f "$VENV/bin/python" ]; then
    PYTHON="$VENV/bin/python"
else
    PYTHON="python3"
fi

PORT="${PORT:-8766}"

echo "=========================================================="
echo "⚡ Visor y Editor de Apuntes Manos Libres (DeltaOS)"
echo "   URL local: http://127.0.0.1:${PORT}"
echo "   WebSocket: ws://127.0.0.1:${PORT}/ws/commands"
echo "=========================================================="

exec "$PYTHON" main.py
