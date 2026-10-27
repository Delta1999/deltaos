#!/bin/bash
# Botón «Volver a la estable» del panel (menú de la hora): devuelve DeltaOS a la versión estable y lo reinicia.
# Lo posterior NO se pierde: commits en el tag antes-del-reset-<fecha>, cambios sin commit en un stash.
# No toca lo ignorado por git: memoria, avisos, logs, .venv, perfil del navegador.
# Lo lanza panel.py en una sesión aparte (start_new_session): sobrevive a que mate a Delta.
cd "$(dirname "$0")" || exit 1
VERSION=v7   # la última etiquetada; cambiar al etiquetar la siguiente
F=$(date +%F_%H%M%S)
exec >>assistant.log 2>&1
git rev-parse -q --verify "$VERSION" >/dev/null || { echo "♻️ reset: no existe $VERSION"; exit 1; }
echo "♻️ reset: vuelvo a $VERSION; lo anterior queda en el tag antes-del-reset-$F"
git tag "antes-del-reset-$F" HEAD
[ -n "$(git status --porcelain)" ] && git stash push -u -m "antes del reset $F" && echo "♻️ reset: cambios sin commit en el stash «antes del reset $F»"
git reset --hard "$VERSION"

A="assist"; P=$(pgrep -f "/${A}ant.py"); [ -n "$P" ] && kill $P
for i in $(seq 30); do pgrep -f "/${A}ant.py" >/dev/null || break; sleep 0.5; done
sleep 2
setsid nohup ./run.sh </dev/null >/dev/null 2>&1 &
