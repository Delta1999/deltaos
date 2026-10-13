#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
export PYTHONUNBUFFERED=1

# La clave vive en ~/.bashrc; run.sh no es interactivo, así que la extraemos aquí.
if [ -z "$GEMINI_API_KEY" ]; then
  eval "$(grep -m1 '^export GEMINI_API_KEY=' "$HOME/.bashrc")"
fi

# Cancelación de eco (evita que el asistente se oiga a sí mismo por los altavoces).
if ! pactl list short sources | grep -q echo-cancel-source; then
  pactl load-module module-echo-cancel aec_method=webrtc \
    source_name=echo-cancel-source sink_name=echo-cancel-sink >/dev/null 2>&1
fi

exec "$DIR/.venv/bin/python3" "$DIR/assistant.py" "$@"
