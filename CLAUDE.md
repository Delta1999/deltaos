# Delta — asistente de voz (Gemini Live) + panel DeltaOS + mascota

Repositorio canónico: `~/gemini-live-assistant`. Trabaja aquí, sobre estos archivos; nunca en copias ni carpetas paralelas.

## Mapa
- `assistant.py` — bucle principal: micro, palabra «Delta», sesión Gemini Live (`gemini-3.8-live`), instrucciones del sistema.
- `acciones.py` — herramientas que usa Gemini (`acciones._fn` + `acciones.registrar`), estado compartido `ST`, `avisar()`.
- `deltaos.py` — DeltaOS: visor del panel, buscar, investigar (informes en HTML), editar_informe, skills, fondo, leer_pegado.
- `claude_acp.py` — Claude Code por ACP: `hablar_con_claude` (repo WORMHOLE) y `mejorar_delta` (este repo, con registro).
- `panel.py` + `panel/index.html` + `panel/fondo.js` — panel web en 127.0.0.1:7876 (aiohttp + WebSocket; `S` = estado que se difunde).
- `mascota.py` — mascota PyQt6 (mapache 3D de puntos) que se pasea por el escritorio.
- `secretario.py` — documentos (crear_documento, convertir_documento).

## Reglas (obligatorias)
- La impresora (Moonraker 192.168.0.102:7125) es SOLO LECTURA: únicamente GET, nunca comandos.
- Enviar SMS o responder mensajes necesita confirmación explícita del usuario cada vez.
- No exponer endpoints HTTP que hagan hablar a Delta (para eso está el buzón 0700). Las órdenes del panel van por el WebSocket, que comprueba Origin.
- No integrar listas de canales de pago (DAZN/AceStream).
- No tocar `~/.config/opencode`, `~/.gemini` ni `~/.agents`.
- Commit sin preguntar al terminar cada cambio verificado (solo tus ficheros), formato `tipo(ámbito): descripción` en español. Push nunca sin pedirlo. Excepción: si te llama Delta (`mejorar_delta`), NO hagas commits; el registro antes/después depende de que los cambios queden sin commitear.
- Nunca `pkill -f`/`pgrep -f` con un patrón literal que aparezca en tu propio comando: usa `A="assist"; pgrep -f "/${A}ant.py"`.
- Respuestas y textos en español de España.

## Cada capacidad nueva → `panel/novedades.json`
Añade `{"f": "AAAA-MM-DD", "t": "qué hace", "como": "frase de ejemplo para pedirlo"}` al principio. Se ve al tocar la hora del panel.
Si actualizas la chuleta (`#chuleta` en index.html), mantenla coherente.

## Cambios pedidos desde Delta (`mejorar_delta`)
Quedan en `CAMBIOS_DELTA.md` con refs git `refs/delta/<fecha>/{antes,despues}` (fotos con `git stash create`).
Si te llama Delta: NO reinicies Delta (eres un proceso hijo suyo); di al final si hace falta reiniciar o basta con recargar el panel.

## Probar
- Sintaxis: `.venv/bin/python -c "import ast;ast.parse(open('X.py').read())"`.
- Panel: abrir http://127.0.0.1:7876 (los cambios de `panel/` solo necesitan recargar la página).
- Reiniciar Delta (solo desde fuera de Delta):
  `A="assist"; P=$(pgrep -f "/${A}ant.py"); kill $P; for i in $(seq 30); do pgrep -f "/${A}ant.py" >/dev/null || break; sleep 0.5; done; sleep 2; (setsid nohup ./run.sh </dev/null >/dev/null 2>&1 &)`
  y después `echo mascota > $XDG_RUNTIME_DIR/delta-vista` si estaba en modo mascota.
- Tras cada arranque/reinicio (lo pidió el usuario): revisar en `assistant.log` las líneas `🩺 servicios:` (`comprobar_servicios.sh`) y `🔊 audio:` (`comprobar_audio.sh`); si hay ⚠️, arreglarlo o decírselo antes de dar Delta por buena.

## Versión estable v2.1
Tag `v2.1` (antes `v2.0`, que sigue existiendo). El botón «↺ Volver a v2.1» del menú de la hora (ws `reset_v2` → `reset_v2.sh`) hace `git reset --hard v2.1` y reinicia Delta; antes guarda lo posterior en el tag `antes-del-reset-<fecha>` y lo no commiteado en un stash. Para una versión estable nueva, mover el tag solo si el usuario lo pide.
