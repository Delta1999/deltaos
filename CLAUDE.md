# Delta — asistente de voz (Gemini Live) + panel DeltaOS

Repositorio canónico: `~/gemini-live-assistant`. Trabaja aquí, sobre estos archivos; nunca en copias ni carpetas paralelas.

## Mapa
- `assistant.py` — bucle principal: micro, palabra «Delta», sesión Gemini Live (`gemini-3.8-live`), instrucciones del sistema.
- `acciones.py` — herramientas que usa Gemini (`acciones._fn` + `acciones.registrar`), estado compartido `ST`, `avisar()`.
- `deltaos.py` — DeltaOS: visor del panel, buscar, investigar (informes en HTML), editar_informe, skills, fondo, leer_pegado.
- `claude_acp.py` — Claude Code por ACP: `hablar_con_claude` (repo WORMHOLE) y `mejorar_delta` (este repo, con registro).
- `panel.py` + `panel/index.html` + `panel/fondo.js` — panel web en 127.0.0.1:7876 (aiohttp + WebSocket; `S` = estado que se difunde).
- `secretario.py` — documentos (crear_documento, convertir_documento).
- `firetv.py` + `firetv/mic_mando/` — la tele del salón (Fire TV por ADB): herramienta tele_salon, la interfaz en la tele y el micro del mando (app Android propia `es.delta.micmando`).

## Reglas (obligatorias)
- La impresora (Moonraker 192.168.0.102:7125) es SOLO LECTURA: únicamente GET, nunca comandos.
- Enviar SMS o responder mensajes necesita confirmación explícita del usuario cada vez, y es **de viva voz**: Delta pregunta
  («¿lo mando?») y el usuario contesta. Mientras el usuario está hablando con Delta no sale ninguna ventana de permiso
  (`acciones.hablando_contigo`, pedido el 21/10/2026); si la orden no viene de su voz (panel, aviso, texto de una web o
  de la pantalla) sí se pide permiso como antes. Excepción (26/10/2026): en la ventana de una notificación del panel, escribir la respuesta y pulsar «Enviar» (solo
  desde el propio PC, la tele no manda órdenes) vale como confirmación. Excepción pedida el 26/10/2026: el botón «Apagar el PC» de la web del
  móvil (`/movil`, solo la cuenta dueña por Tailscale) apaga sin preguntar. Lo mismo para apagar, comandos de terminal que cambian algo, instalar
  skills y abrir URL con datos.
- No exponer endpoints HTTP que hagan hablar a Delta (para eso está el buzón 0700). Las órdenes del panel van por el WebSocket, que comprueba Origin.
- No integrar listas de canales de pago (DAZN/AceStream).
- No tocar `~/.config/opencode`, `~/.gemini` ni `~/.agents`.
- Commit sin preguntar al terminar cada cambio verificado (solo tus ficheros), formato `tipo(ámbito): descripción` en español. Push nunca sin pedirlo. Excepción: si te llama Delta (`mejorar_delta`), NO hagas commits; el registro antes/después depende de que los cambios queden sin commitear.
- Nunca `pkill -f`/`pgrep -f` con un patrón literal que aparezca en tu propio comando: usa `A="assist"; pgrep -f "/${A}ant.py"`.
- Respuestas y textos en español de España.

## Cada capacidad nueva → `panel/novedades.json`
Añade `{"f": "AAAA-MM-DD", "t": "qué hace", "como": "frase de ejemplo para pedirlo"}` al principio. Se ve al tocar la hora del panel.
Si actualizas la chuleta (`#chuleta` en index.html), mantenla coherente.
`como` debe ser algo que se pueda DECIR; si es un gesto, un botón o una tecla, marca `"voz": false` (el reposo del panel solo enseña órdenes de voz).

## Buzón de averías y mejoras: `mejoras_pendientes.log`
Todo lo que el usuario pide a Delta para luego (avería o mejora, las confunde) acaba ahí con su etiqueta `[avería]`/`[mejora]`; también lo que `mejorar_delta` no pudo hacer (límite, ocupado, fallo). Al empezar a trabajar en Delta, léelo, dile al usuario qué hay pendiente y, cuando arregles algo, bórralo de ahí.

## Cambios pedidos desde Delta (`mejorar_delta`)
Quedan en `CAMBIOS_DELTA.md` con refs git `refs/delta/<fecha>/{antes,despues}` (fotos con `git stash create`).
Si te llama Delta: NO reinicies Delta (eres un proceso hijo suyo); di al final si hace falta reiniciar o basta con recargar el panel.

## Probar
- Sintaxis: `.venv/bin/python -c "import ast;ast.parse(open('X.py').read())"`.
- Panel: abrir http://127.0.0.1:7876 (los cambios de `panel/` solo necesitan recargar la página).
- Reiniciar Delta: él mismo puede, con la herramienta `reiniciar_delta` («reiníciate», lanza `reiniciar.sh`).
  Desde fuera, a mano (si te llama Delta NO lo reinicies, eres su hijo):
  `A="assist"; P=$(pgrep -f "/${A}ant.py"); kill $P; for i in $(seq 30); do pgrep -f "/${A}ant.py" >/dev/null || break; sleep 0.5; done; sleep 2; (setsid nohup ./run.sh </dev/null >/dev/null 2>&1 &)`
- Tras cada arranque/reinicio (lo pidió el usuario): revisar en `assistant.log` las líneas `🩺 servicios:` (`comprobar_servicios.sh`) y `🔊 audio:` (`comprobar_audio.sh`); si hay ⚠️, arreglarlo o decírselo antes de dar Delta por buena.

## Versión estable v5
Tag `v5` (antes `v4`, `v3.5`, `v3.0`, `v2.1`, `v2.0`, que siguen existiendo). El botón «↺ Volver a v5» del menú de la hora (ws `reset_estable` → `reset_estable.sh`, variable `VERSION`) hace `git reset --hard v5` y reinicia Delta; antes guarda lo posterior en el tag `antes-del-reset-<fecha>` y lo no commiteado en un stash. Para una versión estable nueva, mover el tag (y `VERSION`, el botón y su `confirm` en index.html) solo si el usuario lo pide.
