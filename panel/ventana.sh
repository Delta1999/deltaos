#!/bin/bash
# Abre el panel en una ventana sin marcos y le aplica la vista.
# Vista (fichero $VISTA, lo escriben Delta y el panel): «panel» = panel a pantalla completa en la
# pantalla secundaria; «invisible» = el panel encogido a una barra de estado en la esquina superior derecha,
# siempre encima y sin robar el foco; «invisible-grande» = esa misma barra con una tarjeta desplegada;
# «oculto» = ni barra ni panel, todo minimizado (Delta sigue escuchando).
# Al cambiar las pantallas se elige sola: con HDMI, panel; solo el portátil, la barra.
# Uso: ventana.sh [NOMBRE_SALIDA]   p.ej. eDP-1 o HDMI-A-1
DIR="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:7876"
SALIDA="${1:-$PANEL_PANTALLA}"
VISTA="${XDG_RUNTIME_DIR:-/tmp}/delta-vista"
PANT="${XDG_RUNTIME_DIR:-/tmp}/delta-pantalla-panel"  # la pantalla elegida por voz (deltaos.mover_a_pantalla)
TIRA_AN=700 TIRA_AL=152 TIRA_M=24  # la tira del modo invisible: ancho, alto y margen con la esquina
TIRA_ALTA=470  # «invisible-grande»: la misma tira con una tarjeta desplegada (Fase 8)

# Imprime «x y ancho alto vista_por_defecto firma» de la pantalla del panel según las pantallas encendidas:
# la elegida por voz si está encendida, si no $SALIDA, si no la que no es la principal. La firma es el juego
# de pantallas: solo si cambia (enchufar o quitar el HDMI) se vuelve a la vista por defecto.
destino() {
  local want; want=$(cat "$PANT" 2>/dev/null); want=${want:-$SALIDA}
  kscreen-doctor -o 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk -v want="$want" '
    /^Output:/{n=$3; en=0} /^[ \t]*enabled/{en=1} /priority/{p=$2}
    /Geometry:/ && en {g[n]=$2" "$3; pr[n]=p; uno=n; k++; f=f n "@" $2 "+" $3 ";"}
    END{if(k>1 && (want in g)) s=want
      if(k>1 && s=="") for(n in g) if(pr[n]!=1){s=n; break}
      if(s=="") s=uno
      if(s=="") exit
      split(g[s],a," "); split(a[1],xy,","); split(a[2],wh,"x")
      print xy[1], xy[2], wh[1], wh[2], (k>1 ? "panel" : "invisible"), f}'
}
aplicar() {  # $1 = ventana del panel, $2 = destino, $3 = vista
  read -r X Y AN AL _ <<<"$2"
  if [ "$3" = oculto ]; then
    # «quita la barra»: nada en pantalla. Delta sigue escuchando; esto es solo la ventana.
    kdotool windowminimize "$1"
  elif [ "${3%%-*}" = invisible ]; then
    # «invisible-grande» es la misma tira con la tarjeta abierta: solo cambia el alto, así que
    # no hace falta otra ventana, otra regla de KWin ni otro proceso al que perseguir.
    H=$TIRA_AL; [ "$3" = invisible-grande ] && H=$TIRA_ALTA
    # sin windowactivate: la tira no debe robarle el teclado a lo que esté haciendo el usuario
    TX=$((X + AN - TIRA_AN - TIRA_M)) TY=$((Y + TIRA_M))
    kdotool windowstate --remove FULLSCREEN --remove MINIMIZED "$1"
    # ABOVE, no KEEP_ABOVE: kdotool rechaza el nombre largo y con él se caía el comando entero,
    # así que la tira se quedaba con marco, en la barra de tareas y DEBAJO de las demás ventanas.
    kdotool windowstate --add NO_BORDER --add SKIP_TASKBAR --add ABOVE "$1"
    kdotool windowmove "$1" "$TX" "$TY"; kdotool windowsize "$1" "$TIRA_AN" "$H"
    sleep 1; kdotool windowmove "$1" "$TX" "$TY"; kdotool windowsize "$1" "$TIRA_AN" "$H"
  else
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
  $k position "$X,$Y"; $k positionrule 1; $k size "$AN,$AL"; $k sizerule 1
  r=$(kreadconfig6 --file kwinrulesrc --group General --key rules)
  [[ ",$r," == *,delta-panel,* ]] || r="${r:+$r,}delta-panel"
  kwriteconfig6 --file kwinrulesrc --group General --key rules "$r"
  kwriteconfig6 --file kwinrulesrc --group General --key count "$(tr ',' '\n' <<<"$r" | grep -c .)"
  dbus-send --session --type=method_call --dest=org.kde.KWin /KWin org.kde.KWin.reconfigure
}

preparar_chromium() {
  local p="$DIR/.chromium"
  # Limpiar bloqueos huérfanos de sesiones anteriores o cierres abruptos
  rm -f "$p/SingletonLock" "$p/SingletonCookie" "$p/SingletonSocket"
  # Quitar sesiones previas con pestañas/ventanas para evitar que intente restaurar un crash
  rm -rf "$p/Default/Sessions"
  # Si Preferences quedó marcado como Crashed tras un kill/pkill, corregirlo a Normal
  if [ -f "$p/Default/Preferences" ]; then
    sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/g; s/"exited_cleanly":false/"exited_cleanly":true/g' "$p/Default/Preferences" 2>/dev/null || true
  fi
}

D=$(destino); [ -n "$D" ] && regla "$D"
for i in $(seq 30); do curl -sf "$URL" >/dev/null && break; sleep 1; done
preparar_chromium
# Chromium y no Chrome: Chrome ya no admite --load-extension, y sinmarcos/ deja incrustar webs en el panel
chromium-browser --user-data-dir="$DIR/.chromium" --load-extension="$DIR/sinmarcos" --app="$URL/" --no-first-run \
  --hide-crash-restore-bubble --disable-session-crashed-bubble --no-recovery-component --no-default-browser-check \
  --disable-features=Translate,OptimizationGuideOnDeviceModel --autoplay-policy=no-user-gesture-required &
CH=$!
# Wayland ignora --window-position: se coloca con KWin una vez aparece la ventana
for i in $(seq 40); do W=$(kdotool search --class "chrome.*127.0.0.1|127.0.0.1" 2>/dev/null | head -1); [ -n "$W" ] && break; sleep .5; done
[ -z "$W" ] && { wait $CH; exit; }
sleep 2  # KWin recoloca la ventana al mostrarla; mover antes no se respeta
ANT= FANT= VANT=
while kill -0 $CH 2>/dev/null; do
  D=$(destino)
  if [ -n "$D" ] && [ "${D##* }" != "$FANT" ]; then  # pantallas cambiadas: vista por defecto
    [ -n "$FANT" ] && { sleep 2; D=$(destino); }
    read -r _ _ _ _ VDEF FANT <<<"$D"
    # Al arrancar se respeta la vista que tenía puesta el usuario: antes cada reinicio de Delta se la
    # borraba y volvía a la de por defecto (con el portátil solo, la tira). Solo se impone la de por
    # defecto al cambiar de pantallas de verdad, o si no hay vista guardada (sesión nueva).
    if [ -n "$ARRANCADO" ] || [ ! -s "$VISTA" ]; then echo "$VDEF" > "$VISTA"; fi
    ARRANCADO=1; VANT=
  fi
  if [ -n "$D" ] && [ "$D" != "$ANT" ]; then  # otra pantalla para el panel (por voz): misma vista, en la nueva
    [ -n "$ANT" ] && regla "$D"; ANT=$D; VANT=
  fi
  # contenido + fecha: repetir la vista tras mover el panel a mano (o con «ventanas») también se aplica
  V=$(cat "$VISTA" 2>/dev/null); T=$(stat -c %.9Y "$VISTA" 2>/dev/null)
  [ -n "$D" ] && [ "$V$T" != "$VANT" ] && { aplicar "$W" "$D" "$V"; VANT=$V$T; }
  sleep 1
done
