#!/bin/bash
# Reinicia DeltaOS cuando el usuario lo pide de viva voz (herramienta reiniciar_delta de deltaos.py).
# Lo lanza Delta en una sesión aparte (start_new_session): sobrevive a que mate a Delta.
# La vista (panel / mascota / invisible) vive en $XDG_RUNTIME_DIR/delta-vista y la relee ventana.sh: no hay que tocarla.
cd "$(dirname "$0")" || exit 1
exec >>assistant.log 2>&1
echo "♻️ reinicio: lo ha pedido el usuario"
A="assist"; P=$(pgrep -f "/${A}ant.py"); [ -n "$P" ] && kill $P
for i in $(seq 30); do pgrep -f "/${A}ant.py" >/dev/null || break; sleep 0.5; done
sleep 2   # que suelte el candado delta.lock que coge run.sh
setsid nohup ./run.sh </dev/null >/dev/null 2>&1 &
