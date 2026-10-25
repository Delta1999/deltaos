#!/bin/bash
# Rutina al arrancar/reiniciar Delta: comprueba que está todo lo que necesita.
# Lo que puede arreglar lo arranca (y lo dice); lo demás solo lo avisa. Se puede lanzar a mano.
# Por qué: el 2026-10-15 un fallo del escritorio reinició PipeWire, WirePlumber no volvió y Delta arrancó sorda.

log() { echo "🩺 servicios: $*"; }
MAL=0

# Audio: sin estos tres no hay tarjeta, micro ni altavoces
for s in pipewire pipewire-pulse wireplumber; do
  systemctl --user is-active -q "$s" && continue
  log "$s estaba parado → lo arranco"
  systemctl --user start "$s" && sleep 2
  systemctl --user is-active -q "$s" || { log "⚠️ $s no arranca"; MAL=1; }
done

# Escritorio: ventanas, pantallas y capturas
[ -n "$WAYLAND_DISPLAY" ] || { log "⚠️ sin sesión Wayland: no habrá panel ni pantalla"; MAL=1; }
pgrep -x kwin_wayland >/dev/null || { log "⚠️ KWin no está en marcha"; MAL=1; }

# Móvil (KDE Connect): el demonio se activa por D-Bus
if ! pgrep -x kdeconnectd >/dev/null; then
  log "KDE Connect estaba parado → lo arranco"
  kdeconnect-cli --refresh >/dev/null 2>&1; sleep 1
  pgrep -x kdeconnectd >/dev/null || { log "⚠️ KDE Connect no arranca (móvil sin avisos)"; MAL=1; }
fi

# Programas que usan las herramientas
for p in parec pactl wpctl kdotool kscreen-doctor qdbus-qt6 spectacle chromium-browser mpv yt-dlp claude notify-send wl-copy; do
  command -v "$p" >/dev/null || { log "⚠️ falta el programa $p"; MAL=1; }
done

# Red y Gemini (sin esto Delta no habla)
[ -n "$GEMINI_API_KEY" ] || { log "⚠️ falta GEMINI_API_KEY"; MAL=1; }
curl -s -m 5 -o /dev/null https://generativelanguage.googleapis.com \
  || { log "⚠️ no llego a la API de Gemini (¿sin internet?)"; MAL=1; }

# Impresora: solo informativo (apagada es normal). SOLO LECTURA: un GET.
curl -s -m 3 -o /dev/null http://192.168.0.102:7125/server/info || log "impresora sin conexión (¿apagada?)"

# «Pasar C.O.S.» (comprobaciones operativas de sistemas, herramienta pasar_cos): además, lo de Delta ya en marcha
if [ "$1" = cos ]; then
  pw-link -l 2>/dev/null | grep -A1 '^alsa_input.*:capture_FL' | grep -q echo-cancel-capture \
    || { log "⚠️ el micro no llega al cancelador de eco (Delta no oye bien)"; MAL=1; }
  [ "$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null | grep -c MUTED)" = 0 ] || log "el sonido está silenciado"
  curl -s -m 2 -o /dev/null http://127.0.0.1:7876 || { log "⚠️ el panel (7876) no responde"; MAL=1; }
  pgrep -f "/[v]entana.sh" >/dev/null || { log "⚠️ ventana.sh no está en marcha (vistas del panel)"; MAL=1; }
  kdotool search --name '^Delta$' >/dev/null 2>&1 || { log "⚠️ no hay ventana del panel"; MAL=1; }
  pgrep -x kdeconnectd >/dev/null && ! kdeconnect-cli -a 2>/dev/null | grep -q . && log "el móvil no está conectado"
  read -r usado < <(df --output=pcent / | tail -1 | tr -dc 0-9)
  [ "$usado" -lt 90 ] || { log "⚠️ disco al $usado %"; MAL=1; }
  read -r _ total _ _ _ _ libre < <(free -m | grep -i '^mem')
  [ $((libre * 100 / total)) -ge 10 ] || { log "⚠️ RAM casi llena ($libre MB libres de $total)"; MAL=1; }
  t=$(sort -n /sys/class/thermal/thermal_zone*/temp 2>/dev/null | tail -1)
  [ -z "$t" ] || [ $((t / 1000)) -lt 85 ] || { log "⚠️ temperatura $((t / 1000)) °C"; MAL=1; }
fi

[ $MAL = 0 ] && log "OK"
exit 0
