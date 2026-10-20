# Delta v3 — plan

Estado: **acordado el 2026-10-20**, sin empezar.
v1 = el tag que se ponga a lo que hay hoy (los tags `v2.0`/`v2.1` son nomenclatura antigua,
no tocarlos). Lo siguiente es **v3** para que no haya confusión.

Principio que manda sobre todo lo demás: **el presupuesto de herramientas está lleno.**
El 19/10 hubo que fusionar 55 herramientas en 12 porque el modelo se confundía
(`acciones.py`, comentario de `FUSIONES`). Ninguna fase de v3 puede añadir una herramienta
suelta por capacidad: o entra en una fusión existente, o entra por el puente MCP.

---

## Fase 0 — v1 de verdad  ✅ HECHA (2026-10-20)

- [x] `claude` en el PATH de Delta. `run.sh` no exportaba PATH, y `~/.local/bin` no está en el
      de un arranque no interactivo. Verificado con `env -i`: encuentra claude 2.1.303.
- [x] Causa real de «tenemos problemas con el micro»: NO era `averias.log` (ese fichero solo se
      escribe, lo revisa Claude Code). Era `panel.contexto()`, que va a Gemini en cada despertar
      y arrastraba la alerta de `S["notifs"]`. Y debajo, un enganche: `ST["ruido"]` subía con cada
      `<noise>` y solo volvía a cero con una transcripción buena, así que 3 ruidos y marcharse
      dejaba `mic: "mal"` clavado para siempre. `mic_clip` sí decae solo; `ruido` no.
      Arreglado con `ruido_t` + `RUIDO_VALE = 60 s`. Comprobación: `test_mic.py`.
- [x] Averías de micro borradas de `averias.log` a mano (backup en `/tmp/averias.bak`).
- [ ] **Pendiente**: que las averías caduquen solas. Nadie purga `averias.log`, así que las notas
      para Claude Code envejecen sin fecha de caducidad. No es urgente: no afecta a lo que dice Delta.
- [ ] Tag de v1.

## Fase 1 — Puente MCP  ✅ HECHA (2026-10-20)

`mcp_puente.py`, sobre el SDK oficial (`mcp` 2.3.0 en el venv; ya estaban sus dependencias
`anyio`, `pydantic` y `httpx`). Usa `ClientSessionGroup`, que sostiene varios servidores a la vez
y agrega su catálogo; soporta servidor local por stdio (`comando`) y remoto por HTTP (`url`).

**UNA** herramienta nueva para el modelo, no una por servidor:
- `conectores(accion="listar")` → qué conectores hay y qué sabe hacer cada uno
- `conectores(accion="usar", servidor, herramienta, argumentos)` → la ejecuta (`argumentos` en JSON)

Un conector nuevo es ahora una entrada en `mcp.json`, sin código ni herramientas nuevas.

Detalles que importan:
- `vigilar()` es la ÚNICA tarea que abre y cierra las sesiones: los flujos de anyio del SDK no
  admiten cerrarse en otra tarea distinta de la que los abrió. Las llamadas sí vienen de cualquiera.
- Las credenciales no van en `mcp.json`: el campo `env` solo lista los NOMBRES de las variables,
  que se leen del entorno de Delta. Si falta una, el conector no arranca y lo dice.
- Un servidor que no arranca no tumba Delta: se anota en `_fallos` y `listar` lo cuenta.
- El paso del panel se renombra en vez de añadir otro (`atender()` ya crea uno).
- `test_mcp.py` lo prueba de punta a punta contra un `MCPServer` real: catálogo, llamada buena,
  nombre sin servidor, nombre entero, y los cuatro errores típicos del modelo.

## Fase 2 — Calendario  ← petición explícita: clases y citas médicas

**Decidido (20/10): Google Calendar.** Hoy las clases y las citas no están en ningún sitio; el
usuario las importa a Google Calendar. La autorización OAuth la tiene que dar él.

Sobre el puente MCP.
- Leer: «¿qué tengo mañana?», «¿cuándo es la cita del médico?»
- Crear y mover citas, con confirmación antes de escribir
- Widget en el panel + icono en el dock (Fase 8)
- Entra en la proactividad de la Fase 5: aviso con antelación de clase y de cita médica

## Fase 3 — Correo

Sobre el puente MCP. Leer y resumir sin fricción.
**Enviar exige confirmación explícita del usuario cada vez**, misma regla que ya rige los SMS.

## Fase 4 — Memoria real  ✅ HECHA (2026-10-20)

- [x] `memoria.py`: SQLite + FTS5. Cada nota es una fila con fecha, veces consultada y cuándo.
- [x] El despertar ya **no** inyecta toda la libreta: las 12 últimas + las más consultadas.
      Lo demás, a una búsqueda (`memoria accion=buscar`), y el prompt se lo dice a Delta.
- [x] Tokenizador sin acentos (`remove_diacritics 2`): esto come voz dictada y «nino» tiene
      que encontrar «niño».
- [x] Lista de palabras vacías: con OR a secas, «¿qué dije DE LA boquilla?» casaba con media
      libreta y le subía el contador a notas que nadie buscó.
- [x] `memoria.md` se importa una vez y queda como copia legible. No se reimporta si ya hay
      notas: resucitaría lo que mandaste olvidar.
- [x] Sin herramienta plana nueva (fusión `memoria`). `test_memoria.py`.

## Fase 5 — Proactividad ✅ (2026-10-20)

Hablar solo ya se podía (`acciones.avisar`), pero sin freno: cualquier aviso sonaba a cualquier
hora y tantas veces como hiciera falta. Lo que faltaba era la puerta.

`proactivo.py`:
- **Qué dice por su cuenta**: calor del procesador (≥ 88 °C), memoria (RAM ≥ 95 % *y* swap ≥ 70 %,
  que con la swap intacta el 86 % es lo normal en esta máquina), disco (< 4 GB) y batería (≤ 15 %
  sin enchufar). Calor y memoria piden dos rondas seguidas: un pico no es un problema.
- **Cuándo se calla**: privacidad, «no molestar», de noche (23:00–08:00) salvo urgencias, espera
  por motivo para no repetirse, y tope de 4 interrupciones por hora. Uno por ronda, nunca dos
  seguidos.
- La puerta vale para **todo** el que avise: `acciones.avisar(..., motivo=…)` pasa por ella. Sin
  `motivo` —alarmas, recordatorios, trabajos terminados— no se filtra nada, que lo pidió él.
- «No me molestes 45 minutos» entra en la fusión `avisos`, no como herramienta suelta (siguen 35).
- El panel lo enseña en el subtítulo y en la tira, para que no parezca que se ha quedado mudo.

`personalidad.txt` lleva el apartado PROACTIVIDAD: cómo entra (una frase, el dato, la cifra y se
aparta), nunca dos avisos juntos, una sola salida concreta, sin ironía en lo urgente, y si le
dicen que lo deje estar, se deja estar.

Test: `test_proactivo.py`.

## Fase 6 — Visión en vivo  ✅ HECHA (2026-10-20)

`gemini-3.8-live` acepta vídeo como entrada nativa. `mirar_detalle` es solo una captura puntual.
«Mira lo que estoy haciendo» mientras se monta una pieza o se pelea con OrcaSlicer.
No gasta ni un slot: es una modalidad de entrada, no una herramienta.

- [x] `ver_en_vivo(minutos)` en `assistant.py`. En reposo la pantalla ya se miraba cada 8 s y solo
      si cambiaba algo (`UMBRAL_CAMBIO = 1.5`); en directo es cada `VIVO_RITMO = 1.5` s y con
      `VIVO_UMBRAL = 0.4`, que nota un gesto o una pieza girando.
- [x] Mira aunque Delta esté dormida: le has pedido que te siga, no que te conteste.
- [x] Se apaga sola (`VIVO_MAX = 30` min) porque es la entrada más cara que tiene, y el modo
      privacidad la bloquea de entrada.
- [x] Sin herramienta plana: entra en la fusión `pantalla` junto a `mirar_detalle`. Siguen 35.
- [x] Testigo **● REC** en la cabecera del panel, y como chip en la tira del modo invisible.
      Fuera del dock a propósito: un testigo de grabación que hay que buscar con la rueda no sirve.
- [x] `test_vivo.py`. Destapó que aceptaba 0,5 min mientras el error prometía «entre 1 y 30».

## Fase 7 — Modo invisible ✅ (2026-10-20)

Tercera vista, junto a `panel` y `mascota` (fichero `$XDG_RUNTIME_DIR/delta-vista`,
lo aplica `panel/ventana.sh`).

Ni mascota ni interfaz: **solo la tira de estado** flotando — los pasos de `acciones.paso()`,
en qué anda Claude Code y qué hace DeltaOS. Sin bordes, sin barra de tareas, por encima del resto.

Hecho: `panel.snapshot()` lleva `vista` (lo lee del fichero, que también escribe `ventana.sh`);
`body.invisible` + `#tira` en `panel/index.html`; tercera rama en `ventana.sh` (700×152 arriba a la
derecha, `KEEP_ABOVE`, **sin** `windowactivate` para no robar el teclado); `fondo.js` para sus bucles
detrás de la tira. La tira lleva hora, estado, qué está haciendo, los pilotos, y un pie con
impresora, próximo aviso, móvil, RAM/CPU/temperatura y avisos nuevos. Test: `test_vista.py`.

De propina (lo pidió sobre la marcha): los subtítulos de la conversación tienen scroll y hora, y
el panel guarda 40 frases en vez de 2 (`panel.FRASES`).

Toca: `panel/ventana.sh` (rama nueva en `aplicar()` con su geometría), `panel/index.html`
(layout que solo pinta el recuadro de estado), y la fusión `vista` gana `invisible`.

## Fase 8 — Ventana emergente estilo terminal

Aparece cuando se pide información concreta, cuando hay una búsqueda, o cuando DeltaOS quiere
mostrar algo. Decoración de terminal pero minimalista. Se cierra sola al acabar.

**Decidido (20/10): la tira de la Fase 7 que crece**, no ventana aparte. Una sola ventana evita
otra regla de KWin y otro proceso que colocar a mano en Wayland, donde ya hay baile de
`kdotool` para el panel. Se despliega en tarjeta con decoración de terminal y se vuelve a encoger.

## Fase 9 — Dock de iconos con scroll  ✅ HECHA (2026-10-20)

Iconos de calendario, KDE Connect, impresora, clima… en el mínimo espacio: el ratón encima y
la rueda los va deslizando. Se añaden sin rediseñar nada.

**Decidido (20/10): va en el sitio de la hora, y la hora es el primer hueco**, en vez de en la
tira. La rueda sube el siguiente desde abajo como los rodillos de una tragaperras.

- [x] 6 huecos: hora+fecha, próximo aviso, impresora, sistema, tiempo, móvil.
- [x] Sin iconos nuevos: el panel habla en matriz de puntos, así que cada hueco es su cifra
      grande y su rótulo. Cada dato ya estaba en el panel; aquí solo se repite en pequeño.
- [x] Vuelve sola a la hora a los 12 s. Un reloj que se ha movido un momento tiene que volver
      a ser un reloj.
- [x] El clic de la hora sigue abriendo la chuleta: la rueda no se lo pisa.
- [ ] **Pendiente**: cuando haya calendario (Fase 2), añadir el hueco de la próxima clase/cita.

## Fase 10 — Impresora con escritura

**Decidido (20/10): sí, con doble confirmación.** Abrir **solo** pausar / reanudar / cancelar.
Delta pregunta dos veces antes de mandar la orden.
Hay que cambiar la regla «SOLO LECTURA» de `CLAUDE.md` al hacer esta fase: lo que queda
prohibido es todo lo demás (temperaturas, movimientos, G-code suelto, firmware).

## Fase 11 — Las dos baratas ya pedidas

De `mejoras_pendientes.log`:
- [ ] Modo «no molestar» / silencio: que deje de escuchar un rato (pedido el 13/10)
- [ ] Mandar capturas de pantalla al móvil por KDE Connect (pedido el 15/10)

## Fase 12 — Versión virgen para enseñar al público

Una copia presentable de Delta, sin nada personal dentro.

- **Repositorio nuevo, sin historial.** No se publica este repo: `personalidad.txt` está
  versionado desde el principio, así que el pasado de los commits lleva datos personales
  aunque el último commit no los lleve. Repo nuevo con un commit inicial, no reescritura.
- **`personalidad.ejemplo.txt` de carácter neutro**: el mismo esqueleto de apartados
  (tono, límites, PROACTIVIDAD…) pero sin la voz, los nombres ni las costumbres del usuario.
  En el repo público va este fichero; `personalidad.txt` pasa a `.gitignore` y se copia
  del ejemplo en la primera ejecución.
- Repasar el resto de lo que sí está versionado antes de publicar (chuleta, `novedades.json`,
  rutas absolutas con el nombre de usuario).

---

## Fuera de v3

- **Etsy**: descartado por el usuario.
- **Puente a `~/.claude/skills`** (11 skills ya escritas: `fdm-rules`, `fountain-design`,
  `design-protocol`, `openscad-design`, `blender-headless`…): buena idea, pero se trata con
  calma aparte. Hoy `usar_skill` solo ve `skills/karpathy-guidelines`.

## Cada fase

Una fase por sesión. Al cerrarla: entrada en `panel/novedades.json`, chuleta coherente,
y commit. Sin push salvo que el usuario lo pida.
