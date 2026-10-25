#!/bin/bash
# Abre el Visor y Editor de Apuntes en una ventana sin marcos (Nothing Design System / DeltaOS)
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8766}"
URL="http://127.0.0.1:$PORT"

# 1. Asegurar que el servidor FastAPI está respondiendo
for i in $(seq 20); do
  curl -sf "$URL/api/context" >/dev/null 2>&1 && break
  sleep 0.2
done

# 2. Preparar el perfil de Chromium exclusivo para el visor de apuntes
CH_DIR="$DIR/.chromium"
mkdir -p "$CH_DIR"
rm -f "$CH_DIR/SingletonLock" "$CH_DIR/SingletonCookie" "$CH_DIR/SingletonSocket"
rm -rf "$CH_DIR/Default/Sessions"
if [ -f "$CH_DIR/Default/Preferences" ]; then
  sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/g; s/"exited_cleanly":false/"exited_cleanly":true/g' "$CH_DIR/Default/Preferences" 2>/dev/null || true
fi

# 3. Configurar regla KWin para ventana sin marcos en Plasma 6
if command -v kwriteconfig6 >/dev/null 2>&1; then
  k="kwriteconfig6 --file kwinrulesrc --group delta-visor --key"
  $k Description "Delta Visor Apuntes (ventana.sh)"
  $k wmclass "127.0.0.1:$PORT"
  $k wmclassmatch 2
  $k noborder 1
  $k noborderrule 2
  r=$(kreadconfig6 --file kwinrulesrc --group General --key rules 2>/dev/null)
  [[ ",$r," == *,delta-visor,* ]] || r="${r:+$r,}delta-visor"
  kwriteconfig6 --file kwinrulesrc --group General --key rules "$r"
  kwriteconfig6 --file kwinrulesrc --group General --key count "$(tr ',' '\n' <<<"$r" | grep -c .)"
  dbus-send --session --type=method_call --dest=org.kde.KWin /KWin org.kde.KWin.reconfigure 2>/dev/null || true
fi

# 4. Lanzar Chromium en modo aplicación dedicada (sin barra de URL, pestañas ni marcos)
if command -v chromium-browser >/dev/null 2>&1; then
  BROWSER="chromium-browser"
elif command -v google-chrome >/dev/null 2>&1; then
  BROWSER="google-chrome"
elif command -v chromium >/dev/null 2>&1; then
  BROWSER="chromium"
else
  xdg-open "$URL/"
  exit 0
fi

$BROWSER --user-data-dir="$CH_DIR" \
  --app="$URL/" \
  --window-size=1600,1000 \
  --no-first-run \
  --hide-crash-restore-bubble \
  --disable-session-crashed-bubble \
  --no-recovery-component \
  --no-default-browser-check \
  --disable-features=Translate,OptimizationGuideOnDeviceModel \
  --autoplay-policy=no-user-gesture-required &
CH_PID=$!

# 5. Aplicar NO_BORDER de forma explícita mediante kdotool
if command -v kdotool >/dev/null 2>&1; then
  (
    for i in $(seq 35); do
      W=$(kdotool search --name "Delta Apuntes|Visor.*DeltaOS|127.0.0.1:$PORT" 2>/dev/null | head -1)
      if [ -n "$W" ]; then
        kdotool windowstate --add NO_BORDER "$W" 2>/dev/null || true
        kdotool windowactivate "$W" 2>/dev/null || true
        break
      fi
      sleep 0.2
    done
  ) &
fi
