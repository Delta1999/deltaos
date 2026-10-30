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
# Firma de los conectores de video, leida de /sys/class/drm: cambia al enchufar o quitar una
# pantalla. Fija CONS_NUEVO en vez de imprimirlo porque $(...) seria un fork, y esto se consulta
# una vez por segundo. Con «read» y el glob de bash no cuesta ni un proceso.
conectores() {
  local c s
  CONS_NUEVO=
  for c in /sys/class/drm/card*-*/status; do
    read -r s < "$c" 2>/dev/null && CONS_NUEVO+="$c=$s;"
  done
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
# que es lo único que sabe hacer una ventana transparente aquí). Se arranca con la interfaz y se coloca en
# la esquina de la pantalla del panel, o donde lo dejó el usuario (orbe_guardar); sigue a la interfaz si cambia de pantalla.
# Nace invisible (KWin lo pone donde quiere, no donde le decimos) y se muestra con SIGUSR1 cuando ya está colocado.
# NO se mata al salir de invisible: arrancarlo de cero tarda ~10 s (WebKit + WebGL) y era lo que se notaba al volver
# al modo invisible. Se queda vivo y oculto (SIGUSR2: ni se ve, ni recibe ratón, ni pinta) hasta la próxima vez.
ORBE_PID= ORBE_PUESTO= ORBE_NUEVO= ORBE_W= ORBE_EN=
ORBE_POS="${XDG_RUNTIME_DIR:-/tmp}/delta-orbe-pos"  # una línea «pantalla x y» por pantalla: dónde lo dejó el usuario al arrastrarlo
lanzar_orbe() {  # no espera: su arranque (~6-10 s) va en paralelo al de Chromium
  kill -0 "$ORBE_PID" 2>/dev/null && return
  /usr/bin/python3 "$DIR/orbe_flotante.py" "$URL" >/dev/null 2>&1 8>&- &   # python del sistema: PyGObject y WebKit no están en el .venv
  ORBE_PID=$! ORBE_PUESTO= ORBE_W= ORBE_EN= ORBE_NUEVO=1
}
orbe_sitio() {  # $1 = destino. Imprime «x y»: donde lo dejó el usuario en esa pantalla, y si no, la esquina de siempre
  local X Y AN AL pan px py
  read -r X Y AN AL _ <<<"$1"
  read -r pan px py <<<"$(grep -F "$X,$Y,$AN,$AL " "$ORBE_POS" 2>/dev/null | tail -1)"
  # vale si es la misma pantalla y el orbe (el círculo, arriba a la derecha de su ventana) sigue dentro de ella
  if [ "$pan" = "$X,$Y,$AN,$AL" ] && [ -n "$px" ] && [ -n "$py" ] \
     && [ $((px + ORBE_AN - 180)) -ge "$X" ] && [ $((px + ORBE_AN - 180)) -lt $((X + AN)) ] \
     && [ $((py + 180)) -ge "$Y" ] && [ $((py + 180)) -lt $((Y + AL)) ]; then
    echo "$px $py"
  else
    echo "$((X + AN - ORBE_AN - ORBE_M)) $((Y + ORBE_M))"
  fi
}
orbe_guardar() {  # apunta dónde está ahora, para volver ahí tras el panel
  local pos x y
  pos=$(kdotool getwindowgeometry "$ORBE_W" 2>/dev/null | sed -n 's/^ *Position: *//p')
  x=${pos%,*}; y=${pos#*,}; x=${x%.*}; y=${y%.*}
  [[ $x =~ ^-?[0-9]+$ && $y =~ ^-?[0-9]+$ ]] || return
  { grep -vF "$ORBE_EN " "$ORBE_POS" 2>/dev/null; echo "$ORBE_EN $x $y"; } > "$ORBE_POS.nuevo" && mv "$ORBE_POS.nuevo" "$ORBE_POS"
}
orbe() {  # $1 = destino, $2 = vista
  local X Y AN AL px py W= clave
  if [ "${2%%-*}" = invisible ]; then
    lanzar_orbe
    read -r X Y AN AL _ <<<"$1"; clave="$X,$Y,$AN,$AL"
    if [ -n "$ORBE_PUESTO" ]; then
      # ya a la vista: solo hace falta moverlo si la interfaz ha cambiado de pantalla («pásala al otro monitor»)
      [ "$clave" = "$ORBE_EN" ] && return
      orbe_guardar  # apunta dónde estaba en la pantalla que deja, por si vuelve
      read -r px py <<<"$(orbe_sitio "$1")"
      kdotool windowmove "$ORBE_W" "$px" "$py"; ORBE_EN=$clave
      return
    fi
    for i in $(seq 40); do W=$(kdotool search --name "Delta orbe" 2>/dev/null | head -1); [ -n "$W" ] && break; sleep .5; done
    [ -z "$W" ] && return
    [ -n "$ORBE_NUEVO" ] && sleep 1  # igual que el panel: KWin recoloca la ventana al mostrarla, y mover antes no se respeta
    ORBE_NUEVO=
    read -r px py <<<"$(orbe_sitio "$1")"
    kdotool windowstate --add NO_BORDER --add SKIP_TASKBAR --add ABOVE "$W"
    kdotool windowmove "$W" "$px" "$py"
    ORBE_W=$W ORBE_EN=$clave
    kill -USR1 "$ORBE_PID" 2>/dev/null; ORBE_PUESTO=1
  elif [ -n "$ORBE_PUESTO" ]; then  # solo si estaba a la vista: recién lanzado ya nace oculto y aún no escucha la señal
    orbe_guardar
    kill -USR2 "$ORBE_PID" 2>/dev/null; ORBE_PUESTO=
  fi
}
trap 'kill $ORBE_PID 2>/dev/null' EXIT
trap 'exit' INT TERM   # un trap sin exit hacía que kill no la parase (run.sh la mata al salir)

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

# Un solo panel (2026-10-29: un arranque fallido dejó una ventana.sh huérfana y, al arrancar otra, había dos
# ventanas). Si ya hay otra ventana.sh, esta la releva: se para a la vieja y se cierra su Chromium.
LOCK="${XDG_RUNTIME_DIR:-/tmp}/delta-ventana.lock"
exec 8<>"$LOCK"
if ! flock -n 8; then
  kill "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null
  flock -w 5 8 || exit 0
fi
echo $$ > "$LOCK"
pkill -f "user-data-dir=$DIR/.chromium" 2>/dev/null
for i in $(seq 20); do pgrep -f "user-data-dir=$DIR/.chromium" >/dev/null || break; sleep .25; done

D=$(destino); [ -n "$D" ] && regla "$D"
for i in $(seq 30); do curl -sf "$URL" >/dev/null && break; sleep 1; done
preparar_chromium
V0=$(cat "$VISTA" 2>/dev/null)
lanzar_orbe  # siempre, aunque se arranque en panel: así el primer «modo invisible» tampoco espera
# Chromium y no Chrome: Chrome ya no admite --load-extension, y sinmarcos/ deja incrustar webs en el panel.
# 2026-10-30: tras un reinicio de Delta la ventana salía a veces EN GRIS (existía, en su sitio, pero sin pintar la página:
# su título se quedaba en «127.0.0.1_/» en vez de «Delta»). Si a los 15 s no tiene el título de la página, se relanza Chromium (hasta 3 veces).
lanzar_chromium() {
  chromium-browser --user-data-dir="$DIR/.chromium" --load-extension="$DIR/sinmarcos" --app="$URL/" --no-first-run \
    --hide-crash-restore-bubble --disable-session-crashed-bubble --no-recovery-component --no-default-browser-check \
    --disable-features=Translate,OptimizationGuideOnDeviceModel --autoplay-policy=no-user-gesture-required 8>&- &
  CH=$!
}
for INTENTO in 1 2 3; do
  lanzar_chromium
  # Wayland ignora --window-position: se coloca con KWin una vez aparece la ventana
  W=
  for i in $(seq 200); do W=$(kdotool search --class "chrome.*127.0.0.1|127.0.0.1" 2>/dev/null | head -1); [ -n "$W" ] && break; sleep .1; done
  [ -z "$W" ] && { wait $CH; exit; }
  for i in $(seq 50); do [[ $(kdotool getwindowname "$W" 2>/dev/null) == Delta* ]] && break 2; sleep .3; done
  [ "$INTENTO" = 3 ] && break  # la última vez se queda con lo que haya
  echo "$(date +%d/%m\ %H:%M:%S) ⚠️ ventana.sh: el panel no cargó (ventana gris), intento $INTENTO: relanzo Chromium" >> "$DIR/../assistant.log"
  kill $CH 2>/dev/null; wait $CH 2>/dev/null
  pkill -f "user-data-dir=$DIR/.chromium" 2>/dev/null
  for i in $(seq 20); do pgrep -f "user-data-dir=$DIR/.chromium" >/dev/null || break; sleep .25; done
  preparar_chromium
done
if [ "${V0%%-*}" = invisible ] || [ "$V0" = oculto ]; then
  kdotool windowminimize "$W"  # el panel no se ve en estas vistas: fuera ya, sin dejar ver su CSS ni su sitio de nacimiento
else
  sleep 2  # KWin recoloca la ventana al mostrarla; mover antes no se respeta
fi
# Este bucle vive mientras viva el panel —horas—, asi que su camino rapido no hace ni un fork:
# lee la vista con «read» y nota que la han tocado con «-nt», los dos builtins de bash. Lo caro es
# destino() (kscreen-doctor + sed + awk, ~0,02 s de CPU y 4 procesos), y antes se llamaba una vez
# por segundo: ~5% de un nucleo y unas 21.000 llamadas por hora para devolver siempre lo mismo.
# Ahora solo se vuelve a preguntar cuando algo pudo cambiar de verdad:
#   - se enchufo o quito una pantalla      -> cambia la firma de conectores()
#   - se pidio otra pantalla por voz       -> $PANT es mas nuevo que su marca
#   - cada $REPOLL s                       -> red de seguridad: cambiar la resolucion desde los
#                                             ajustes de KDE no se ve en los conectores
# Tras un cambio de conectores, KWin tarda en habilitar la salida nueva, asi que se vuelve al
# sondeo de 1 Hz durante $VIGILIA vueltas hasta que la respuesta se estabiliza.
REPOLL=30 VIGILIA=10
MVISTA="$VISTA.visto" MPANT="$PANT.visto"   # marcas de mtime: «esto ya lo he atendido»
: > "$MVISTA"; : > "$MPANT"
ANT= FANT= VANT= CONS= CONS_NUEVO= D= URGE=1 ULTIMO=0
while kill -0 $CH 2>/dev/null; do
  conectores
  if [ "$CONS_NUEVO" != "$CONS" ]; then CONS=$CONS_NUEVO; URGE=$VIGILIA; fi
  if [ "$PANT" -nt "$MPANT" ]; then : > "$MPANT"; URGE=$VIGILIA; fi
  if [ "$URGE" -gt 0 ] || [ $((SECONDS - ULTIMO)) -ge "$REPOLL" ]; then
    [ "$URGE" -gt 0 ] && URGE=$((URGE - 1))
    ULTIMO=$SECONDS
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
  fi
  # contenido + «la han tocado»: repetir la vista tras mover el panel a mano (o con «ventanas»)
  # también se aplica. Los dos son builtins, a diferencia del cat + stat de antes.
  V=; [ -r "$VISTA" ] && { read -r V < "$VISTA" || :; }
  if [ -n "$D" ] && { [ "$V" != "$VANT" ] || [ "$VISTA" -nt "$MVISTA" ]; }; then
    : > "$MVISTA"
    orbe "$D" "$V"; aplicar "$W" "$D" "$V"; VANT=$V
  fi
  sleep 1
done
