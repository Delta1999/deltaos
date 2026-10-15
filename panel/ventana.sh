#!/bin/bash
# Abre el panel en una ventana sin marcos y reparte la interfaz entre el panel y la mascota (mascota.py).
# Vista (fichero $VISTA, lo escriben Delta, el panel y la mascota): «panel» = panel a pantalla completa en la
# pantalla secundaria, mascota oculta; «mascota» = panel minimizado, solo el mapache flotando.
# Al cambiar las pantallas se elige sola: con HDMI, panel; solo el portátil, mascota.
# Uso: ventana.sh [NOMBRE_SALIDA]   p.ej. eDP-1 o HDMI-A-1
DIR="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:7876"
SALIDA="${1:-$PANEL_PANTALLA}"
VISTA="${XDG_RUNTIME_DIR:-/tmp}/delta-vista"

# Imprime «x y ancho alto vista_por_defecto» de la pantalla del panel según las pantallas encendidas
destino() {
  kscreen-doctor -o 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk -v want="$SALIDA" '
    /^Output:/{n=$3; en=0} /^[ \t]*enabled/{en=1} /priority/{p=$2}
    /Geometry:/ && en {g[n]=$2" "$3; pr[n]=p; uno=n; k++}
    END{if(k>1) for(n in g) if((want!="" && n==want) || (want=="" && pr[n]!=1)){s=n; break}
      if(s=="") s=uno
      if(s=="") exit
      split(g[s],a," "); split(a[1],xy,","); split(a[2],wh,"x")
      print xy[1], xy[2], wh[1], wh[2], (k>1 ? "panel" : "mascota")}'
}
aplicar() {  # $1 = ventana del panel, $2 = destino, $3 = vista
  read -r X Y AN AL _ <<<"$2"
  M=$(kdotool search --class delta-mascota 2>/dev/null | head -1)
  if [ "$3" = mascota ]; then
    kdotool windowminimize "$1"; [ -n "$M" ] && kdotool windowactivate "$M"
  else
    [ -n "$M" ] && kdotool windowminimize "$M"
    kdotool windowactivate "$1"
    kdotool windowstate --remove FULLSCREEN "$1"; kdotool windowstate --add NO_BORDER --add SKIP_TASKBAR "$1"
    kdotool windowmove "$1" "$X" "$Y"; kdotool windowsize "$1" "$AN" "$AL"
    sleep 1; kdotool windowmove "$1" "$X" "$Y"
  fi
}

for i in $(seq 30); do curl -sf "$URL" >/dev/null && break; sleep 1; done
# Chromium y no Chrome: Chrome ya no admite --load-extension, y sinmarcos/ deja incrustar webs en el panel
chromium-browser --user-data-dir="$DIR/.chromium" --load-extension="$DIR/sinmarcos" --app="$URL" --no-first-run \
  --disable-features=Translate --autoplay-policy=no-user-gesture-required &
CH=$!
# Wayland ignora --window-position: se coloca con KWin una vez aparece la ventana
for i in $(seq 40); do W=$(kdotool search --class "chrome.*127.0.0.1|127.0.0.1" 2>/dev/null | head -1); [ -n "$W" ] && break; sleep .5; done
[ -z "$W" ] && { wait $CH; exit; }
sleep 2  # KWin recoloca la ventana al mostrarla; mover antes no se respeta
ANT= VANT= MANT=
while kill -0 $CH 2>/dev/null; do
  D=$(destino)
  if [ -n "$D" ] && [ "$D" != "$ANT" ]; then  # pantallas cambiadas (o arranque): vista por defecto
    [ -n "$ANT" ] && { sleep 2; D=$(destino); }
    echo "${D##* }" > "$VISTA"; ANT=$D; VANT=
  fi
  MM=$(kdotool search --class delta-mascota 2>/dev/null | head -1)
  [ "$MM" != "$MANT" ] && { MANT=$MM; VANT=; }  # la mascota (re)aparece: aplicarle la vista
  V=$(cat "$VISTA" 2>/dev/null)
  [ -n "$D" ] && [ "$V" != "$VANT" ] && { aplicar "$W" "$D" "$V"; VANT=$V; }
  sleep 1
done
