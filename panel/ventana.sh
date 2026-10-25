#!/bin/bash
# Abre el panel en una ventana sin marcos y le aplica la vista.
# Vista (fichero $VISTA, lo escriben Delta y el panel): «panel» = panel a pantalla completa en la
# pantalla secundaria; «invisible» = el panel minimizado y, en su lugar, el ORBE FLOTANTE
# (orbe_flotante.py: ventana transparente con el orbe 2, que enseña la barra de estado al clicarlo);
# «oculto» = ni orbe ni panel, nada en pantalla (Delta sigue escuchando).
# Al cambiar las pantallas se elige sola: con HDMI, panel; solo el portátil, la barra.
# Uso: ventana.sh [NOMBRE_SALIDA]   p.ej. eDP-1 o HDMI-A-1
DIR="$(cd "$(dirname "$0")" && pwd)"
URL="http://127.0.0.1:7876"
SALIDA="${1:-$PANEL_PANTALLA}"
VISTA="${XDG_RUNTIME_DIR:-/tmp}/delta-vista"
PANT="${XDG_RUNTIME_DIR:-/tmp}/delta-pantalla-panel"  # la pantalla elegida por voz (deltaos.mover_a_pantalla)
ORBE_AN=700 ORBE_AL=850 ORBE_M=24  # la ventana del orbe flotante (medidas en orbe_flotante.py) y su margen

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
  if [ "${3%%-*}" = invisible ] || [ "$3" = oculto ]; then
    # En invisible el panel no se ve: lo que queda en pantalla es el orbe flotante, que es otra
    # ventana (orbe()). En oculto no queda nada. Delta sigue escuchando en los dos casos.
    kdotool windowminimize "$1"
  else
    kdotool windowactivate "$1"
    kdotool windowstate --remove FULLSCREEN --remove KEEP_ABOVE "$1"
    kdotool windowstate --add NO_BORDER --add SKIP_TASKBAR "$1"
    kdotool windowmove "$1" "$X" "$Y"; kdotool windowsize "$1" "$AN" "$AL"
    sleep 1; kdotool windowmove "$1" "$X" "$Y"
  fi
}

# El orbe flotante del modo invisible: otra ventana y otro proceso (orbe_flotante.py, GTK+WebKit,
# que es lo único que sabe hacer una ventana transparente aquí). Se arranca al entrar en invisible,
# se coloca en la misma esquina donde estaba la barra de estado, y se mata al salir.
# Nace invisible (KWin lo pone donde quiere, no donde le decimos) y se muestra con SIGUSR1 cuando ya está colocado.
ORBE_PID= ORBE_PUESTO=
lanzar_orbe() {  # no espera: su arranque (~6 s) va en paralelo al de Chromium
  kill -0 "$ORBE_PID" 2>/dev/null && return
  /usr/bin/python3 "$DIR/orbe_flotante.py" "$URL" >/dev/null 2>&1 &   # python del sistema: PyGObject y WebKit no están en el .venv
  ORBE_PID=$! ORBE_PUESTO=
}
orbe() {  # $1 = destino, $2 = vista
  if [ "${2%%-*}" = invisible ]; then
    lanzar_orbe
    [ -n "$ORBE_PUESTO" ] && return
    read -r X Y AN AL _ <<<"$1"
    local W=
    for i in $(seq 40); do W=$(kdotool search --name "Delta orbe" 2>/dev/null | head -1); [ -n "$W" ] && break; sleep .5; done
    [ -z "$W" ] && return
    sleep 1  # igual que el panel: KWin recoloca la ventana al mostrarla, y mover antes no se respeta
    kdotool windowstate --add NO_BORDER --add SKIP_TASKBAR --add ABOVE "$W"
    kdotool windowmove "$W" $((X + AN - ORBE_AN - ORBE_M)) $((Y + ORBE_M))
    kill -USR1 "$ORBE_PID" 2>/dev/null; ORBE_PUESTO=1
  elif [ -n "$ORBE_PID" ]; then
    kill "$ORBE_PID" 2>/dev/null; ORBE_PID=
  fi
}
trap 'kill $ORBE_PID 2>/dev/null' EXIT INT TERM

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
V0=$(cat "$VISTA" 2>/dev/null)
[ "${V0%%-*}" = invisible ] && lanzar_orbe
# Chromium y no Chrome: Chrome ya no admite --load-extension, y sinmarcos/ deja incrustar webs en el panel
chromium-browser --user-data-dir="$DIR/.chromium" --load-extension="$DIR/sinmarcos" --app="$URL/" --no-first-run \
  --hide-crash-restore-bubble --disable-session-crashed-bubble --no-recovery-component --no-default-browser-check \
  --disable-features=Translate,OptimizationGuideOnDeviceModel --autoplay-policy=no-user-gesture-required &
CH=$!
# Wayland ignora --window-position: se coloca con KWin una vez aparece la ventana
for i in $(seq 200); do W=$(kdotool search --class "chrome.*127.0.0.1|127.0.0.1" 2>/dev/null | head -1); [ -n "$W" ] && break; sleep .1; done
[ -z "$W" ] && { wait $CH; exit; }
if [ "${V0%%-*}" = invisible ] || [ "$V0" = oculto ]; then
  kdotool windowminimize "$W"  # el panel no se ve en estas vistas: fuera ya, sin dejar ver su CSS ni su sitio de nacimiento
else
  sleep 2  # KWin recoloca la ventana al mostrarla; mover antes no se respeta
fi
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
  [ -n "$D" ] && [ "$V$T" != "$VANT" ] && { orbe "$D" "$V"; aplicar "$W" "$D" "$V"; VANT=$V$T; }
  sleep 1
done
