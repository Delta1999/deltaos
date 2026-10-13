#!/bin/bash
# Abre el panel en una ventana sin marcos en la pantalla indicada (por defecto, la que no es la principal).
# Uso: ventana.sh [NOMBRE_SALIDA]   p.ej. eDP-1 o HDMI-A-1
DIR="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:7876"
SALIDA="${1:-$PANEL_PANTALLA}"
INFO=$(kscreen-doctor -o 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk -v want="$SALIDA" '
  /^Output:/{n=$3} /priority/{p=$2} /Geometry:/{split($2,o,","); g[n]=$2" "$3; pr[n]=p}
  END{for(n in g){ if((want!="" && n==want) || (want=="" && pr[n]!=1)){print g[n]; exit}}}')
POS="${INFO%% *}"; TAM="${INFO##* }"
for i in $(seq 30); do curl -sf "$URL" >/dev/null && break; sleep 1; done
google-chrome --user-data-dir="$DIR/.chrome" --app="$URL" --no-first-run --disable-features=Translate &
CH=$!
# Wayland ignora --window-position: se coloca con KWin una vez aparece la ventana
for i in $(seq 40); do W=$(kdotool search --class "chrome.*127.0.0.1|127.0.0.1" 2>/dev/null | head -1); [ -n "$W" ] && break; sleep .5; done
if [ -n "$W" ] && [ -n "$POS" ]; then
  sleep 2  # KWin recoloca la ventana al mostrarla; mover antes no se respeta
  kdotool windowstate --remove FULLSCREEN "$W"; kdotool windowstate --add NO_BORDER --add SKIP_TASKBAR "$W"
  kdotool windowmove "$W" "${POS%,*}" "${POS#*,}"; kdotool windowsize "$W" "${TAM%x*}" "${TAM#*x}"
  sleep 1; kdotool windowmove "$W" "${POS%,*}" "${POS#*,}"
fi
wait $CH
