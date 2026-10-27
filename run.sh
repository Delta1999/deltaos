#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
export PYTHONUNBUFFERED=1

# claude vive en ~/.local/bin, que NO está en el PATH de un arranque no interactivo
# (2026-10-20: «🩺 servicios: ⚠️ falta el programa claude»; sin él mueren hablar_con_claude y mejorar_delta).
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac

# Un solo Delta: el arranque automático y uno lanzado a mano se pisaban (dos voces a la vez).
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/delta.lock"
flock -n 9 || { echo "Delta ya está en marcha."; exit 0; }

# Rotación de logs (2026-10-25): sin ella assistant.log crecía sin tope. Al arrancar, el que pase
# del límite pasa a .1 (y el .1 anterior se pierde): queda el arranque de ahora y el historial justo
# de antes, que es lo que se mira cuando algo ha fallado.
LOG_MAX=$((2 * 1024 * 1024))
for l in assistant.log panel_error.log vision.log; do
  f="$DIR/$l"
  if [ -f "$f" ] && [ "$(stat -c %s "$f")" -gt "$LOG_MAX" ]; then mv -f "$f" "$f.1"; fi
done

# Si no corre en una terminal interactiva (p.ej. inicio automático), guardar log.
# Cada línea con su hora (2026-10-19: sin ella no se sabía cuándo pasó un fallo). 9>&-: el filtro no se queda el candado.
if [ ! -t 1 ]; then
  exec > >(exec 9>&-; while IFS= read -r l || [ -n "$l" ]; do
    if [ -n "$l" ]; then printf '%(%d/%m %H:%M:%S)T %s\n' -1 "$l"; else echo; fi
  done >> "$DIR/assistant.log") 2>&1
fi

# La clave vive en ~/.bashrc; run.sh no es interactivo, así que la extraemos aquí.
if [ -z "$GEMINI_API_KEY" ]; then
  eval "$(grep -m1 '^export GEMINI_API_KEY=' "$HOME/.bashrc")"
fi

# Rutina: que estén en marcha los servicios que necesita (audio, escritorio, red); arranca los que pueda.
"$DIR/comprobar_servicios.sh"

# Rutina: perfil, micro, ganancia y altavoces como funcionaban (corrige y lo anota en el log).
"$DIR/comprobar_audio.sh"

# Cancelación de eco acústico y supresión de ruido. El cancelador ya NO se carga aquí: vive en
# ~/.config/pipewire/pipewire.conf.d/50-delta-echo-cancel.conf, con monitor.mode = true.
#
# Antes se cargaba a mano y se ponía echo-cancel-sink como salida por defecto del sistema para
# que el micro no captase la música. Costaba dos cosas: un `systemctl --user restart pipewire`
# descargaba el módulo y dejaba a Delta sorda al eco sin avisar, y TODO el audio del sistema
# atravesaba un AEC sintonizado para voz, que con música fuerte saturaba y se comía la voz del
# usuario. En monitor.mode el cancelador lee la referencia del monitor del sink por defecto:
# la música va directa a los altavoces y el AEC la sigue conociendo para restarla del micro.
if pactl list short sources | grep -q echo-cancel-source; then
  echo "🔊 audio: OK (micro → cancelador de eco → Delta; música directa a los altavoces)"
else
  echo "🔊 audio: ⚠️ no existe echo-cancel-source: revisar 50-delta-echo-cancel.conf"
fi

case " $* " in *" --sin-panel "*) ;; *)
  [ -n "$WAYLAND_DISPLAY$DISPLAY" ] && { "$DIR/panel/ventana.sh" >/dev/null 2>&1 9>&- & VENTANA=$!; } ;;
esac
cleanup_ventana() { [ -n "$VENTANA" ] && pkill -f "user-data-dir=$DIR/panel/.chromium" 2>/dev/null; }
trap 'cleanup_ventana; cleanup' EXIT INT TERM

"$DIR/.venv/bin/python3" "$DIR/assistant.py" "$@"
