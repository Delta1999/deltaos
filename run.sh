#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
export PYTHONUNBUFFERED=1

# Si no corre en una terminal interactiva (p.ej. inicio automático), guardar log.
if [ ! -t 1 ]; then
  exec >> "$DIR/assistant.log" 2>&1
fi

# La clave vive en ~/.bashrc; run.sh no es interactivo, así que la extraemos aquí.
if [ -z "$GEMINI_API_KEY" ]; then
  eval "$(grep -m1 '^export GEMINI_API_KEY=' "$HOME/.bashrc")"
fi

# Guardar el dispositivo de salida original
ORIG_SINK="$(pactl get-default-sink 2>/dev/null)"

# Cancelación de eco acústico y supresión de ruido (filtra los audios del sistema y altavoces).
if ! pactl list short sources | grep -q echo-cancel-source; then
  pactl load-module module-echo-cancel aec_method=webrtc \
    source_name=echo-cancel-source sink_name=echo-cancel-sink \
    aec_args="analog_gain_control=0 digital_gain_control=1 high_pass_filter=1 noise_suppression=1" >/dev/null 2>&1
fi

# Configurar echo-cancel-sink como salida por defecto para que todo el audio del sistema
# (navegador, vídeos, música) pase por el cancelador de eco y el micrófono no lo capte.
if pactl list short sinks | grep -q echo-cancel-sink; then
  pactl set-default-sink echo-cancel-sink 2>/dev/null || true
  for id in $(pactl list short sink-inputs 2>/dev/null | awk '{print $1}'); do
    pactl move-sink-input "$id" echo-cancel-sink 2>/dev/null || true
  done
fi

cleanup() {
  if [ -n "$ORIG_SINK" ]; then
    pactl set-default-sink "$ORIG_SINK" 2>/dev/null || true
    for id in $(pactl list short sink-inputs 2>/dev/null | awk '{print $1}'); do
      pactl move-sink-input "$id" "$ORIG_SINK" 2>/dev/null || true
    done
  fi
}
trap cleanup EXIT INT TERM

case " $* " in *" --sin-panel "*) ;; *)
  [ -n "$WAYLAND_DISPLAY$DISPLAY" ] && { "$DIR/panel/ventana.sh" >/dev/null 2>&1 & VENTANA=$!; } ;;
esac
cleanup_ventana() { [ -n "$VENTANA" ] && pkill -f "user-data-dir=$DIR/panel/.chrome" 2>/dev/null; }
trap 'cleanup_ventana; cleanup' EXIT INT TERM

"$DIR/.venv/bin/python3" "$DIR/assistant.py" "$@"
