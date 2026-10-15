#!/bin/bash
# Rutina de audio al arrancar Delta: deja la tarjeta como funcionaba el 2026-10-14 y avisa de lo que corrige.
# Se puede lanzar a mano: ./comprobar_audio.sh
# Por qué: el 2026-10-15 arrancó con perfil solo-HDMI (sin micro), Master apagado y ganancia del micro
# al máximo (+40 dB): no oía, luego oía ruido como voz y, por HDMI, se oía a sí mismo.

CARD=alsa_card.pci-0000_00_1f.3
PERFIL=output:analog-stereo+input:analog-stereo   # altavoces del portátil + micro: mismo reloj, el AEC funciona
MIC=alsa_input.pci-0000_00_1f.3.analog-stereo
# Ganancia analógica fija (la tarjeta va con soft-mixer, ver ~/.config/wireplumber/wireplumber.conf.d/).
# Calibrable: subir BOOST si no te oye de lejos, bajar si oye la tele/ruido como voz.
BOOST=2
CAPTURA=21

log() { echo "🔊 audio: $*"; }
RECARGAR=0

activo=$(LC_ALL=C pactl -f json list cards 2>/dev/null | python3 -c "
import json, sys
print(next((c['active_profile'] for c in json.load(sys.stdin) if c['name'] == '$CARD'), ''))")
if [ "$activo" != "$PERFIL" ]; then
  log "perfil «$activo» → $PERFIL"
  pactl set-card-profile "$CARD" "$PERFIL" && RECARGAR=1
  sleep 1
fi

# control ALSA, valor esperado, y cómo ponerlo
fijar() {
  local actual
  actual=$(amixer -c0 cget name="$1" 2>/dev/null | grep -oP ': values=\K.*')
  if [ "$actual" != "$2" ]; then
    log "«$1» estaba en $actual → $2"
    amixer -c0 -q cset name="$1" "$2"
    CAMBIO=1
  fi
}
CAMBIO=0
fijar 'Internal Mic Boost Volume' "$BOOST,$BOOST"
fijar 'Capture Volume' "$CAPTURA,$CAPTURA"
fijar 'Capture Switch' 'on,on'
fijar 'Master Playback Switch' 'on'
fijar 'Speaker Playback Switch' 'on,on'
fijar 'PCM Playback Volume' '255,255'   # 0 dB; el 2026-10-15 arrancó a −51 dB y Delta casi no sonaba
fijar 'Digital Capture Volume' '60,60'  # 0 dB
[ "$(amixer -c0 cget name='Master Playback Volume' | grep -oP ': values=\K.*')" = 0 ] && { log "Master a 0 → 100%"; amixer -c0 -q sset Master 100%; CAMBIO=1; }
[ "$CAMBIO" = 1 ] && sudo -n alsactl store 0 2>/dev/null && log "estado del mezclador guardado"

pactl list short sources | grep -q "$MIC" || log "⚠️ SIN MICRO tras corregir el perfil: revisar a mano"

# El cancelador cargado antes de que existiera el micro queda sordo: recargarlo.
if [ "$RECARGAR" = 1 ] || { pactl list short sources | grep -q echo-cancel-source && ! pw-link -l 2>/dev/null | grep -A1 "^$MIC:capture_FL" | grep -q echo-cancel-capture; }; then
  pactl unload-module module-echo-cancel 2>/dev/null && log "cancelador de eco recargado"
fi
exit 0
