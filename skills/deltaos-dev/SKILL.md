---
name: deltaos-dev
description: Protocolo de desarrollo, auditoría y arquitectura de DeltaOS (~/gemini-live-assistant). Actívala siempre que trabajes en Delta (assistant.py, acciones.py, deltaos.py, panel.py, panel/*, claude_acp.py, pasarela/*, firetv.py) o cuando audites el panel en vivo por CDP (puerto 9222).
---

# DeltaOS (`~/gemini-live-assistant`) — Guía de Arquitectura y Desarrollo

## 1. Mapa del Sistema y Flujo de Datos

- **Repositorio canónico:** `/home/jloslop/gemini-live-assistant` (nunca crear copias ni forks).
- **Arranque único:** `~/.config/autostart/gemini-live-assistant.desktop` → `./run.sh`. **PROHIBIDO** crear servicios `systemd` (`delta.service`) que arranquen antes de que KDE Plasma, KWin y PipeWire estén listos.
- **Núcleo de voz (`assistant.py`):** Sesión WebSocket con `gemini-3.8-live` (SDK `google-genai`), detección local por Vosk («Delta») y bucle `asyncio` único.
- **Herramientas y Fusiones (`acciones.py`):**
  - El modelo `gemini-3.8-live` se degrada si recibe más de ~15 herramientas raíz.
  - Por eso **todas** las capacidades se agrupan en `acciones.FUSIONES` (`impresora`, `avisos`, `claude`, `memoria`, `skills`, `musica`, `vista`, `documentos`, `taller`, `pantalla`, `clima`, `movil`, `apuntes`) más `conectores` (`mcp_puente.py`).
  - Si añades una capacidad nueva, intégrala como una `accion` dentro de una fusión existente en `FUSIONES`, no como una herramienta suelta en `DECLARATIONS`.
- **Panel Web (`panel.py` + `panel/index.html` + `panel/fondo.js` + `panel/agentes.js` + `panel/teclado.js`):**
  - Corre en `http://127.0.0.1:7876` (`aiohttp` + WebSocket `/ws`).
  - `panel/ventana.sh` lanza Chromium con `--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1` y el proceso del orbe transparente (`panel/orbe_flotante.py`).
  - Soporta dos sistemas de diseño completos: **Nothing Design System** (`[data-tema="nothing"]`, tipografías `Doto`, `Space Mono`, `Space Grotesk`, acento `#D71921`) e **iOS / Liquid Glass** (`[data-tema="ios"]`, `SF Pro`, blur translúcido, acento `#007AFF`).

## 2. Inspección en Vivo del Panel (Chrome DevTools Protocol `:9222`)

El Chromium del panel expone CDP en `http://127.0.0.1:9222`.
- Puedes consultar las páginas abiertas con `curl -s http://127.0.0.1:9222/json/list`.
- Puedes usar `chrome-devtools-mcp` (`--browserUrl=http://127.0.0.1:9222`) o scripts rápidos en Python (`websockets`) contra el `webSocketDebuggerUrl` de la pestaña `http://127.0.0.1:7876/` para:
  - Evaluar expresiones JS en vivo (`Runtime.evaluate`).
  - Leer errores de consola o excepciones capturadas por `window.__reportError`.
  - Verificar el estado del WebSocket `/ws` y el rendimiento de los canvas (`#fo-cv`, `#fb-cv`, `#ag-cv`, `#fi-cv`).
- Si eres un modelo **sin visión directa** y necesitas auditar el aspecto visual de una captura de pantalla del panel, delega en `~/Escritorio/WORMHOLE/tools/gemini.py`.

## 3. Reglas Inquebrantables de Seguridad y Permisos

1. **Impresora 3D (`192.168.0.102:7125` Moonraker):** **SOLO LECTURA** (`GET` únicamente). Jamás enviar comandos G-code ni POST.
2. **Confirmación de viva voz:** Enviar SMS, responder mensajes, comandos de shell que modifican el sistema, instalar skills o abrir URLs con datos requieren confirmación explícita. Mientras el usuario habla con Delta (`acciones.hablando_contigo`), Delta pregunta de viva voz («¿lo mando?») sin sacar ventana emergente; si la orden viene de texto externo o web, sale la ventana de confirmación en el panel.
3. **Privacidad de Notas (`notas.py`):** Las acciones `nota_*` (`NOTAS_PRIVADAS`) nunca muestran su contenido en `assistant.log`, ni en el dock del panel (solo contador), ni se envían a Claude Code.
4. **No matar procesos propios por accidente:** Nunca usar `pkill -f` o `pgrep -f` con el literal `assistant.py`. Usar siempre:
   ```bash
   A="assist"; P=$(pgrep -f "/${A}ant.py")
   ```

## 4. Protocolo de Verificación y Reinicio

Antes de dar cualquier cambio por terminado en DeltaOS:

1. **Comprobar sintaxis AST y suite de frontend:**
   ```bash
   .venv/bin/python -c "import ast, glob; [ast.parse(open(f).read()) for f in glob.glob('*.py')]"
   .venv/bin/python test_panel_frontend.py
   ```
2. **Actualizar `panel/novedades.json` (y `#chuleta` en `panel/index.html` si aplica):**
   - Añadir al inicio `{"f": "AAAA-MM-DD", "t": "qué hace", "como": "frase de ejemplo"}`.
   - Si no es orden de voz (botón/gesto/tecla), incluir `"voz": false`.
3. **Reiniciar (solo si NO eres un proceso hijo lanzado por `mejorar_delta`):**
   ```bash
   A="assist"; P=$(pgrep -f "/${A}ant.py"); [ -n "$P" ] && kill $P
   for i in $(seq 30); do pgrep -f "/${A}ant.py" >/dev/null || break; sleep 0.5; done
   sleep 2
   export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" DISPLAY="${DISPLAY:-:0}" XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
   (setsid nohup ./run.sh </dev/null >/dev/null 2>&1 &)
   ```
4. **Verificar `assistant.log` tras el arranque:**
   Comprobar que aparecen `🩺 servicios: OK` y `🔊 audio: OK` sin ningún `⚠️`.
5. **Commit en español (`tipo(ámbito): descripción`):**
   Hacer commit solo de los archivos modificados (salvo que hayamos sido invocados por `mejorar_delta`, en cuyo caso se deja sin commitear para el registro `refs/delta/...`).
