# Misión secundaria — FLYRADAR y SAILRADAR en DeltaOS

> Estado: **pendiente, no empezada**. Prompt preparado el 21/10/2026 para pegarlo cuando toque.
> Prioridad: baja — primero van otros arreglos.

---

## Prompt (pegar tal cual)

Quiero añadir a DeltaOS dos pantallas nuevas, FLYRADAR y SAILRADAR, con la estética de
puntos del panel. Trabaja en `~/gemini-live-assistant`, que es el repo canónico.

### Qué quiero ver

**Un icono nuevo en el carrusel del dock** (la cabecera donde está la hora y giran los
huecos con la rueda del ratón). Al hacer **clic** en ese hueco se despliega una pantalla
completa titulada **FLYRADAR**, con la misma apariencia NothingOS que ya tienen las
pantallas completas de la impresora, el sistema y el tiempo: fondo negro, matriz de
puntos, tipografía de puntos, rojo `--red` como único acento.

**FLYRADAR** muestra los aviones que hay ahora mismo sobre mi casa: un radar centrado en
mi posición, con los aviones como marcas orientadas según su rumbo, el indicativo al
lado, y una lista con altitud, velocidad y país. Que se vea de un vistazo lo que me pasa
por encima.

**SAILRADAR** es una pestaña dentro de la misma pantalla y hace lo mismo con los barcos,
con datos AIS. Debe poderse cambiar de FLYRADAR a SAILRADAR sin salir y volver.

**Localización automática.** No quiero escribir mis coordenadas: cógelas del GPS del
navegador y, si eso falla, de la IP.

### Lo que ya existe y hay que reutilizar

Esto ya lo he comprobado, no lo redescubras:

- **El código de vuelos ya está escrito**, en el Delta viejo (`~/projects/delta`, PyQt6,
  sin git). Son `panels/flights.py` (159 líneas: OpenSky, caché de 30 s, dataclass
  `Flight`, resumen para voz) y `ui/panel_flights.py` (138 líneas: mapa SVG a mano,
  proyección lat/lon→píxel, triángulos rotados por rumbo, color por altitud). **Pórtalo,
  no lo reinventes** — pero ojo con sus dos defectos: refrescaba cada 30 s contra un
  límite de 400 peticiones/día (se agotaba la cuota en 3 h y medía), y la proyección es
  equirectangular sin corregir por el coseno de la latitud, así que el eje este-oeste
  sale estirado. Arregla las dos cosas al portar.
- **Mi posición ya la tiene el panel.** `panel/index.html:612` (`geo()`) pide
  `navigator.geolocation` al abrir el WebSocket y la manda como `{geo:[lat,lon,acc]}`;
  `panel.py:560` la valida, la redondea a 2 decimales (~1 km) y la guarda en
  `panel/geo.json`. Ya hay una posición guardada. Úsala; el respaldo por IP solo si ese
  fichero no existe.
- **El carrusel del dock** es `#dock` + `#dock-pista` con 6 huecos (`#hora` y `k1`..`k5`),
  `DOCK_N=6` en `panel/index.html:630`, rellenados en `pintar()` (líneas 401-415) y
  girados con la rueda (líneas 633-636). Vuelve solo a la hora a los 12 s. Hoy **ningún
  hueco es clicable** (solo `#hora` abre la chuleta): hay que añadir el hueco nuevo, subir
  `DOCK_N`, y darle un `click` propio.
- **Las pantallas completas** viven en `#fondo` (`panel/index.html:305-312`) y las
  gobierna `panel/fondo.js`: se abren con `window.pantallaCompleta('impresora'|'sistema')`
  (línea 62), que hoy la llaman los clics en las tarjetas (`index.html:643-644`). **Aviso:
  `fondo.js:19` es un ternario que colapsa cualquier valor que no sea `'impresora'` en
  `'sistema'`** — hay que ampliarlo para que acepte la escena nueva, o no se abrirá nunca.
- **Un `.js` nuevo no se sirve solo:** hay que añadirlo a la lista de `panel.py:823`.
- `window.FONDO_ON` (`fondo.js:39`) apaga la matriz del panel mientras hay pantalla
  completa, para no gastar CPU (`index.html:519`). Respétalo: el radar no debe pintar
  cuando está tapado.

### Decisiones que te dejo a ti, pero justifícalas antes de escribir código

1. **Fuente de datos de vuelos.** El código viejo usa OpenSky anónimo
   (`/api/states/all` con *bounding box*) y **lo he probado el 21/10/2026: responde
   HTTP 200 con datos reales**. Pero 400 peticiones/día sin cuenta. Decide entre refrescar
   cada 5 minutos, registrar cuenta gratuita (4.000/día) o usar otra fuente sin clave.
   **Verifica la que elijas con una petición real antes de construir sobre ella.**
2. **Fuente de datos AIS.** Esta no la he comprobado y es el riesgo de la misión: el AIS
   gratuito es bastante peor que el ADS-B. Mira qué hay (aisstream.io por WebSocket con
   clave gratuita, AISHub, u otras) y **dime qué cobertura real tiene mi zona antes de
   montar SAILRADAR**. Si resulta que no hay datos decentes gratis en la costa de
   Chiclana, dímelo y nos quedamos solo con FLYRADAR: prefiero una pantalla que funcione
   a dos y una vacía.
3. **Dónde vive la lógica.** Decide si el radar tira de una ruta nueva en `panel.py`
   (Python pide los datos y el panel solo pinta) o si el JS llama a la API directamente.
   Ten en cuenta que el panel corre en Chromium local y que el `index.html` ya va por
   las 654 líneas: si abulta, saca el radar a su propio `.js`.

### Reglas del proyecto que aplican

- Español de España en todo: textos, comentarios y commits.
- **Cada capacidad nueva va a `panel/novedades.json`** al principio, con `f`, `t` y `como`,
  y la chuleta (`#chuleta` en `index.html`) coherente: entradas para «ponme el radar de
  aviones» y «qué barcos hay».
- Que se pueda abrir **también por voz**: una acción en `acciones.py` o `deltaos.py` para
  «ponme el radar», «qué aviones pasan por encima», «qué barcos hay».
- Los cambios de `panel/` solo necesitan recargar la página; si tocas `panel.py`,
  `acciones.py` o `deltaos.py`, hay que reiniciar Delta.
- Commit al terminar cada cambio verificado, formato `tipo(ámbito): descripción`.
- Verifica antes de decir que está hecho: abre el panel en http://127.0.0.1:7876, haz el
  clic de verdad y comprueba que salen aviones reales. Si la API falla, dímelo con la
  salida.

### Cómo sé que está terminado

- Giro la rueda sobre la hora y aparece el hueco de FLYRADAR.
- Un clic y se despliega la pantalla completa, con mi casa en el centro y los aviones que
  hay ahora mismo, con su indicativo y su altitud.
- Cambio a la pestaña SAILRADAR y veo los barcos (o un «sin cobertura AIS aquí» honesto,
  si en el punto 2 resultó que no hay datos).
- Sale del radar con Esc o doble clic, como las demás pantallas completas.
- Lo puedo pedir por voz.
- `panel/novedades.json` y la chuleta lo recogen.
