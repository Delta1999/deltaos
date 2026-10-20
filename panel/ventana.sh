#!/bin/bash
# Abre el panel en una ventana sin marcos y reparte la interfaz entre el panel y la mascota (mascota.py).
# Vista (fichero $VISTA, lo escriben Delta, el panel y la mascota): «panel» = panel a pantalla completa en la
# pantalla secundaria, mascota oculta; «mascota» = panel minimizado, solo el mapache flotando;
# «invisible» = mascota oculta y el panel encogido a una tira de estado en la esquina superior derecha,
# siempre encima y sin robar el foco; «invisible-grande» = esa misma tira con una tarjeta desplegada.
# Al cambiar las pantallas se elige sola: con HDMI, panel; solo el portátil, mascota.
# Uso: ventana.sh [NOMBRE_SALIDA]   p.ej. eDP-1 o HDMI-A-1
DIR="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:7876"
SALIDA="${1:-$PANEL_PANTALLA}"
VISTA="${XDG_RUNTIME_DIR:-/tmp}/delta-vista"
TIRA_AN=700 TIRA_AL=152 TIRA_M=24  # la tira del modo invisible: ancho, alto y margen con la esquina
TIRA_ALTA=470  # «invisible-grande»: la misma tira con una tarjeta desplegada (Fase 8)

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
    # mostrarla sin activarla: la mascota es una capa del tamaño de la pantalla y se quedaría con el teclado
    kdotool windowminimize "$1"; [ -n "$M" ] && kdotool windowstate --remove MINIMIZED "$M"
  elif [ "${3%%-*}" = invisible ]; then
    # «invisible-grande» es la misma tira con la tarjeta abierta: solo cambia el alto, así que
    # no hace falta otra ventana, otra regla de KWin ni otro proceso al que perseguir.
    H=$TIRA_AL; [ "$3" = invisible-grande ] && H=$TIRA_ALTA
    # sin windowactivate: la tira no debe robarle el teclado a lo que esté haciendo el usuario
    [ -n "$M" ] && kdotool windowminimize "$M"
    TX=$((X + AN - TIRA_AN - TIRA_M)) TY=$((Y + TIRA_M))
    kdotool windowstate --remove FULLSCREEN --remove MINIMIZED "$1"
    kdotool windowstate --add NO_BORDER --add SKIP_TASKBAR --add KEEP_ABOVE "$1"
    kdotool windowmove "$1" "$TX" "$TY"; kdotool windowsize "$1" "$TIRA_AN" "$H"
    sleep 1; kdotool windowmove "$1" "$TX" "$TY"; kdotool windowsize "$1" "$TIRA_AN" "$H"
  else
    [ -n "$M" ] && kdotool windowminimize "$M"
    kdotool windowactivate "$1"
    kdotool windowstate --remove FULLSCREEN --remove KEEP_ABOVE "$1"
    kdotool windowstate --add NO_BORDER --add SKIP_TASKBAR "$1"
    kdotool windowmove "$1" "$X" "$Y"; kdotool windowsize "$1" "$AN" "$AL"
    sleep 1; kdotool windowmove "$1" "$X" "$Y"
  fi
}

# Regla de KWin: la ventana nace ya en su pantalla, sin aparecer antes en la otra y saltar
regla() {
  read -r X Y AN AL _ <<<"$1"
  local k="kwriteconfig6 --file kwinrulesrc --group delta-panel --key" r
  $k Description "Delta panel (ventana.sh)"; $k wmclass "127.0.0.1__"; $k wmclassmatch 2
  $k position "$X,$Y"; $k positionrule 3; $k size "$AN,$AL"; $k sizerule 3
  r=$(kreadconfig6 --file kwinrulesrc --group General --key rules)
  [[ ",$r," == *,delta-panel,* ]] || r="${r:+$r,}delta-panel"
  kwriteconfig6 --file kwinrulesrc --group General --key rules "$r"
  kwriteconfig6 --file kwinrulesrc --group General --key count "$(tr ',' '\n' <<<"$r" | grep -c .)"
  dbus-send --session --type=method_call --dest=org.kde.KWin /KWin org.kde.KWin.reconfigure
}
D=$(destino); [ -n "$D" ] && regla "$D"
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
  # contenido + fecha: repetir «modo mascota» tras mover el panel a mano (o con «ventanas») también se aplica
  V=$(cat "$VISTA" 2>/dev/null); T=$(stat -c %.9Y "$VISTA" 2>/dev/null)
  [ -n "$D" ] && [ "$V$T" != "$VANT" ] && { aplicar "$W" "$D" "$V"; VANT=$V$T; }
  sleep 1
done
