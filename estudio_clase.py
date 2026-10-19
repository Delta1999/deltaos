#!/usr/bin/env python3
"""Clase → apuntes: audio de una clase + tema del temario → PDF anotado.

Uso: estudio_clase.py [--tema 1] (--audio clase.mp3 [--profe "Nombre"] … | --url <página del vídeo> | nada)
Sin audio ni URL coge la clase abierta en Chrome (historial) y, si no hay, lo último que bajó la extensión. Sin tema, lo saca del nombre («T1_DDHH…»).
Cada tema junta TODAS sus clases (temaNN/clases.json, en orden de llegada) en un solo PDF: una clase nueva se añade.
Cada etapa deja su caché en ~/Documentos/Delta/estudio/temaNN/<clase>/ y se reanuda sola.
"""
import argparse
import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pymupdf
from google import genai
from google.genai import types

TEMARIO = Path.home() / "Escritorio/Temario_Guardia_Civil"
SALIDA = TEMARIO / "DeltaOs"
RESUMEN = Path.home() / "Escritorio/MEGARESUMIDO_GUARDIA CIVIL 2026 (DIGITAL).pdf"
TRABAJO = Path.home() / "Documentos/Delta/estudio"
EXTENSION = Path.home() / "Descargas/vimeoMediaDownloader"  # donde guarda la extensión Vimeo Media Downloader
MEDIOS = {".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".opus", ".mkv", ".wav", ".aac"}
TRANSCRIBE = "gemini-3.8-flash"
ANALIZA = "gemini-pro-latest"
TRAMO = 1800  # s por trozo de audio: ~8 k tokens de salida, holgado
TIEMPO_MAX = 900  # s por petición a Gemini: sin esto una respuesta que no llega cuelga la clase entera
DUR_IGUAL = 2  # s: dos audios que difieren menos que esto son el mismo vídeo
CLASE_MIN = 300  # s: menos que esto es un corte o una descarga fallida, no una clase
RUIDO = re.compile(r"P\s?R\s?O\s?C\s?I\s?V\s?I\s?L|IVIL\.ES|INGRESO G[Cc]|Todos los derechos", re.I)

_cli = None
_cerrojo = threading.Lock()


def guardar(f, obj):
    """Escritura atómica: si el proceso muere a medias no queda una caché rota que tumbe la siguiente vuelta."""
    tmp = f.with_name(f".{f.name}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, f)


def gem():
    # un único cliente: si dos hilos crean el suyo, el que se pierde lo recoge el GC y cierra el httpx compartido
    global _cli
    with _cerrojo:
        _cli = _cli or genai.Client(http_options=types.HttpOptions(timeout=TIEMPO_MAX * 1000))
    return _cli


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def hms(s):
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def segundos(t):
    n = [int(x) for x in re.findall(r"\d+", str(t))][-3:]
    return sum(v * 60 ** i for i, v in enumerate(reversed(n)))


def duracion(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout)


def generar(modelo, contenido, esquema, intentos=6):
    """generate_content con salida JSON validada por esquema y reintentos (cuota, 5xx)."""
    for i in range(intentos):
        try:
            r = gem().models.generate_content(model=modelo, contents=contenido, config=types.GenerateContentConfig(
                response_mime_type="application/json", response_json_schema=esquema, temperature=0.4))
            return json.loads(r.text)
        except Exception as e:
            if i == intentos - 1:
                raise
            log(f"  reintento {i + 1} ({type(e).__name__}: {str(e)[:120]})")
            time.sleep(15 * (i + 1))


# ── 0. Conseguir el audio ───────────────────────────────────────────────────

VIDEO_ACADEMIA = re.compile(r"procivil\.es/content/video/(\d+)")  # el número es el id de Vimeo
CHROME = Path.home() / ".config/google-chrome"


def clase_abierta(horas=12):
    """(url, título) de la última clase abierta en Chrome, sacada del historial: leer la barra de una captura no es fiable."""
    mejor = None
    for hist in CHROME.glob("*/History"):
        with tempfile.TemporaryDirectory() as d:  # Chrome tiene la base bloqueada: se lee una copia
            shutil.copy(hist, Path(d) / "h")
            con = sqlite3.connect(Path(d) / "h")
            fila = con.execute("SELECT url, last_visit_time FROM urls WHERE url LIKE '%procivil.es/content/video/%' "
                               "ORDER BY last_visit_time DESC LIMIT 1").fetchone()
            con.close()
        if fila and (not mejor or fila[1] > mejor[1]):
            mejor = fila
    if not mejor or time.time() - (mejor[1] / 1e6 - 11644473600) > horas * 3600:  # tiempos de Chrome: µs desde 1601
        return None
    return mejor[0], parse_qs(urlparse(mejor[0]).query).get("title", [""])[0]


def profe_de(titulo):
    """La academia acaba el título con el profesor: «… - Parte 1 -  Paco Arriola»."""
    ult = titulo.rsplit(" - ", 1)[-1].strip() if " - " in titulo else ""
    return ult if re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+( [A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3}", ult) else ""


def bajar(url):
    """yt-dlp con la página que se está viendo: el Vimeo embebido de la academia pide referer y sesión."""
    dest = TRABAJO / "descargas"
    dest.mkdir(parents=True, exist_ok=True)
    m = VIDEO_ACADEMIA.search(url)
    if m:
        # la web de la academia es una app JS que yt-dlp no entiende; el reproductor de Vimeo con su referer, sí
        vid = m.group(1)
        hecho = [f for f in dest.iterdir() if f"[{vid}]" in f.name and f.suffix in MEDIOS]
        if hecho:
            return hecho[0]
        nombre = re.sub(r"[^\w-]+", "_", parse_qs(urlparse(url).query).get("title", [vid])[0])[:90].strip("_")
        r = subprocess.run(["yt-dlp", "-f", "bestaudio", "-N", "8", "--referer", "https://app.procivil.es/", "-o",
                            str(dest / f"{nombre} [{vid}].%(ext)s"), f"https://player.vimeo.com/video/{vid}"],
                           capture_output=True, text=True)
        hecho = [f for f in dest.iterdir() if f"[{vid}]" in f.name and f.suffix in MEDIOS]
        if r.returncode == 0 and hecho:
            return hecho[0]
        log("yt-dlp no pudo con Vimeo →", (r.stderr.strip().splitlines() or ["?"])[-1][:200])
    for galletas in (["--cookies-from-browser", "chrome"], ["--cookies-from-browser", "firefox"], []):
        antes = set(dest.iterdir())
        r = subprocess.run(["yt-dlp", "-f", "bestaudio/best", "--no-playlist", "--referer", url, *galletas,
                            "-o", str(dest / "%(title).90s.%(ext)s"), url], capture_output=True, text=True)
        nuevos = [f for f in set(dest.iterdir()) - antes if f.suffix in MEDIOS]
        if r.returncode == 0 and nuevos:
            return max(nuevos, key=lambda f: f.stat().st_mtime)
        log("yt-dlp no pudo", *galletas, "→", (r.stderr.strip().splitlines() or ["?"])[-1][:200])
    return None


def ultimo_descargado(horas=None):
    """Lo último que bajó la extensión; con «horas», solo si es de ahora (para no procesar una clase vieja por error)."""
    f = [x for x in EXTENSION.glob("*") if x.suffix.lower() in MEDIOS]
    f = max(f, key=lambda x: x.stat().st_mtime) if f else None
    return f if f and (horas is None or time.time() - f.stat().st_mtime < horas * 3600) else None


def comprobar_audio(f):
    """Antes de gastar horas de API: que exista, que la extensión haya terminado de bajarlo y que sea una clase."""
    if not f.exists():
        sys.exit(f"No existe {f}")
    if f.suffix.lower() not in MEDIOS:
        sys.exit(f"{f.name} no es un audio ni un vídeo")
    while time.time() - f.stat().st_mtime < 30:
        log(f"{f.name} aún se está bajando…")
        time.sleep(10)
    try:
        dur = duracion(f)
    except (subprocess.CalledProcessError, ValueError):
        sys.exit(f"No puedo leer {f.name}: ¿descarga a medias? Vuelve a bajarlo.")
    if dur < CLASE_MIN:
        sys.exit(f"{f.name} dura {hms(dur)}: no parece una clase (¿un trozo o el tráiler?)")


def juntar(clases, audios, profes):
    """Clases del tema en orden de llegada: las nuevas van AL FINAL (su posición fija audioN/ y las cachés de análisis,
    así que nunca se reordena); una que ya estaba solo actualiza su profe."""
    out = [dict(c) for c in clases]
    for i, au in enumerate(audios):
        p = profes[i] if i < len(profes) else ""
        ya = next((c for c in out if Path(c["audio"]).name == au.name), None)
        if ya is None:
            out.append({"audio": str(au), "profe": p})
        elif p:
            ya["profe"] = p
    return out


def misma_clase(f, clases):
    """El mismo vídeo bajado por otra vía (extensión o yt-dlp) se llama distinto pero dura lo mismo: se reutiliza la clase
    que ya estaba para no transcribirla dos veces ni meterla repetida en el PDF."""
    d = duracion(f)
    for c in clases:
        p = Path(c["audio"])
        if p.name != f.name and p.exists() and abs(duracion(p) - d) < DUR_IGUAL:
            log(f"{f.name} es la misma clase que {p.name} (dura lo mismo): no la duplico")
            return p
    return f


def tema_de(nombre):
    m = re.search(r"(?:^|[^a-z])t(?:ema)?[ _-]?0?(\d{1,2})(?:[^0-9]|$)", nombre.lower())
    return int(m.group(1)) if m else None


# ── 1. Temario y resumen en texto, con su número de página ──────────────────

def pdf_tema(n):
    f = sorted(TEMARIO.glob(f"Tema {n:02d} - *.pdf"))
    if not f:
        sys.exit(f"No encuentro el Tema {n:02d} en {TEMARIO}")
    return f[0]


def texto_paginas(doc, paginas):
    out = []
    for p in paginas:
        lineas = [l.strip() for l in doc[p].get_text().splitlines()]
        lineas = [l for l in lineas if len(l) > 3 and not RUIDO.search(l)]
        out.append(f"\n=== PÁGINA {p + 1} ===\n" + "\n".join(lineas))
    return "".join(out)


def texto_resumen(n):
    """Páginas del MEGARESUMIDO del año pasado de ese tema (cabecera «TEMA n - …»)."""
    if not RESUMEN.exists():
        return ""
    d = pymupdf.open(RESUMEN)
    pags = [i for i in range(len(d)) if re.search(rf"TEMA {n} -", d[i].get_text()[:300])]
    return texto_paginas(d, pags)


# ── 2. Audio → transcripción por tramos ─────────────────────────────────────

PIDE_TRANSCRIPCION = """Transcribe esta grabación de una clase de oposiciones a Guardia Civil (español de España).
Dura {dur}. Las marcas «t» son relativas al inicio de ESTE audio, en formato M:SS o H:MM:SS, y NUNCA superan {dur}.
- Literal y completo lo que se dice sobre la materia; corrige solo muletillas repetidas («eh», «vale» encadenados).
- Agrupa en intervenciones de 15-60 s; «quien» = PROFESOR, ALUMNO u OTRO.
- Música, canciones, vídeos de entrada, silencios y ruido: NO los transcribas (ni letras de canciones).
- Respeta la terminología jurídica (TEDH, CEDH, ECOSOC, BOE, artículos y números exactos)."""

ESQ_TRANSCRIPCION = {"type": "array", "items": {"type": "object", "properties": {
    "t": {"type": "string"}, "quien": {"type": "string", "enum": ["PROFESOR", "ALUMNO", "OTRO"]},
    "texto": {"type": "string"}}, "required": ["t", "quien", "texto"]}}


def trocear(audio, dirt):
    """MP3 → tramos Opus mono 16 kHz de TRAMO s (≈ 6 MB por media hora)."""
    dirt.mkdir(parents=True, exist_ok=True)
    if not list(dirt.glob("*.ogg")):
        if not audio.exists():
            sys.exit(f"Falta {audio} y su clase aún no estaba troceada: vuelve a bajarlo")
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "16000", "-c:a", "libopus",
                        "-b:a", "24k", "-f", "segment", "-segment_time", str(TRAMO), "-reset_timestamps", "1", str(dirt / "t%02d.ogg")], check=True)
    return sorted(dirt.glob("*.ogg"))


def transcribir_tramo(ogg):
    cache = ogg.with_suffix(".json")
    if cache.exists():
        return json.loads(cache.read_text())
    dur = duracion(ogg)
    f = gem().files.upload(file=str(ogg))
    try:
        while f.state and f.state.name == "PROCESSING":
            time.sleep(3)
            f = gem().files.get(name=f.name)
        segs = generar(TRANSCRIBE, [f, PIDE_TRANSCRIPCION.format(dur=hms(dur))], ESQ_TRANSCRIPCION)
    finally:
        gem().files.delete(name=f.name)
    # tiempos imposibles fuera (el fallo del intento anterior) y siempre crecientes
    limpio, ant = [], 0
    for s in segs:
        t = segundos(s["t"])
        if t > dur + 5 or not s["texto"].strip():
            continue
        ant = max(ant, t)
        limpio.append({**s, "t": ant})
    guardar(cache, limpio)
    log(f"  {ogg.parent.name}/{ogg.name}: {len(limpio)} intervenciones")
    return limpio


def transcribir_con_reintentos(ogg, veces=5):
    for i in range(veces):
        try:
            return transcribir_tramo(ogg)
        except Exception as e:  # cortes de red: la clase entera no puede caerse por un tramo
            if i == veces - 1:
                raise
            log(f"  {ogg.parent.name}/{ogg.name}: {type(e).__name__}, reintento en {30 * (i + 1)} s")
            time.sleep(30 * (i + 1))


def transcribir(audios, base):
    """Devuelve [{parte, t (s desde el inicio de su parte), quien, texto}]."""
    tramos = [(i, j, ogg) for i, a in enumerate(audios, 1) for j, ogg in enumerate(trocear(a, base / f"audio{i}"))]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda x: transcribir_con_reintentos(x[2]), tramos))
    return [{**s, "parte": i, "t": s["t"] + j * TRAMO} for (i, j, _), segs in zip(tramos, res) for s in segs]


def minuto(s, partes):
    return (f"P{s['parte']}·" if partes > 1 else "") + hms(s["t"])


# ── 3. Análisis de profesorado ──────────────────────────────────────────────

PIDE_ANALISIS = """Eres el mejor opositor a Guardia Civil de la academia: sacas plaza con nota y tus apuntes son los que todos fotocopian.
Tienes la transcripción de la clase del profesor, el tema oficial con su número de página y el resumen del año pasado
(trae marcadas las preguntas que cayeron en exámenes oficiales). Prepara las anotaciones que harías tú sobre el tema, a mano, con máximo esfuerzo.

QUÉ BUSCAR EN LA CLASE
- Todo lo que el profesor RECALCA: «ojo», «esto cae», «pregunta fija», repeticiones, cambios de tono, trampas típicas del test.
- Datos que hay que memorizar: plazos, números, mayorías, órganos, sedes, fechas, artículos.
- Sus explicaciones y ejemplos que hacen entender algo (resúmelos en una línea).
- Sus reglas mnemotécnicas y trucos, LITERALES.
- Lo que explica en clase y NO está en el tema (tipo «anadido»).
IGNORA: logística, bromas sin contenido, saludos, avisos, música, preguntas de alumnos sin respuesta útil.

REGLAS DE LAS ANOTACIONES
- «pagina»: la página del tema donde va (=== PÁGINA N ===).
- «subrayar»: 1-3 fragmentos COPIADOS LETRA A LETRA de esa página (4-18 palabras cada uno), lo justo: el dato, no el párrafo.
- «nota»: lo que escribirías en el margen, máx. 22 palabras, estilo apunte: abreviaturas (art., TEDH, CE), flechas →, «=», «!!»,
  sin frases de relleno. Que aporte algo que el texto subrayado no dice ya: el truco, la trampa, la comparación, el porqué.
- «cita»: la frase del profesor (corta, literal) y «minuto» tal como aparece en la transcripción (sin inventar).
- tipo «pregunta_fija» SOLO si el profesor lo dice o el resumen lo marca como pregunta de examen oficial.
- Reparte: cada página que el profesor trabajó debe llevar sus notas; no metas 10 en una y 0 en la siguiente.
- MNEMOTECNIAS: todas las del profesor (origen «profesor», con minuto) y propón TUS reglas (origen «delta») para las listas,
  cifras y plazos difíciles del tema que no tengan: acrónimos con sentido, frases absurdas que se recuerdan, asociaciones numéricas.
  Que funcionen de verdad; mejor 6 buenas que 20 flojas.
- ESQUEMAS: uno por cada bloque importante del tema (los epígrafes que el profesor trabajó). 16-30 nodos en 3-4 niveles
  (órgano → apartado → datos con cifra, y un «ojo» donde esté la trampa), etiquetas de ≤ 8 palabras
  con las cifras clave; jerarquía con «padre» (id del nodo padre, vacío para la raíz, solo UNA raíz por esquema).
  Tipo de nodo: titulo (raíz), rama, dato (cifra/plazo), ojo (trampa de examen). «despues_de_pagina» = última página del bloque.
- «resumen»: 5-8 frases con lo que trató la clase y lo que más insistió.

ESTA PETICIÓN: parte {k} de {n} de la clase ({desde} → {hasta}). Anota a fondo SOLO lo que se explica en esta parte:
espera 20-40 notas por hora de clase (todo lo que recalca, cada dato que da, cada explicación útil), las mnemotecnias de esta
parte y 0-2 esquemas de los bloques del tema que se trabajan aquí. Las demás partes las anota otro igual que tú.

=== TRANSCRIPCIÓN DE LA CLASE (parte {k} de {n}) ===
{trans}

=== TEMA OFICIAL ===
{tema}

=== RESUMEN DEL AÑO PASADO (orientativo: qué es importante y qué cayó en examen) ===
{resumen}"""

ESQ_ANALISIS = {"type": "object", "properties": {
    "profesor": {"type": "string"}, "resumen": {"type": "string"},
    "notas": {"type": "array", "items": {"type": "object", "properties": {
        "tipo": {"type": "string", "enum": ["pregunta_fija", "ojo", "dato", "explicacion", "anadido"]},
        "pagina": {"type": "integer"}, "subrayar": {"type": "array", "items": {"type": "string"}},
        "nota": {"type": "string"}, "cita": {"type": "string"}, "minuto": {"type": "string"}},
        "required": ["tipo", "pagina", "subrayar", "nota", "cita", "minuto"]}},
    "mnemotecnias": {"type": "array", "items": {"type": "object", "properties": {
        "regla": {"type": "string"}, "significa": {"type": "string"}, "pagina": {"type": "integer"},
        "subrayar": {"type": "string"}, "origen": {"type": "string", "enum": ["profesor", "delta"]},
        "minuto": {"type": "string"}}, "required": ["regla", "significa", "pagina", "subrayar", "origen", "minuto"]}},
    "esquemas": {"type": "array", "items": {"type": "object", "properties": {
        "titulo": {"type": "string"}, "despues_de_pagina": {"type": "integer"}, "pie": {"type": "string"},
        "nodos": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "padre": {"type": "string"}, "texto": {"type": "string"},
            "tipo": {"type": "string", "enum": ["titulo", "rama", "dato", "ojo"]}},
            "required": ["id", "padre", "texto", "tipo"]}}},
        "required": ["titulo", "despues_de_pagina", "pie", "nodos"]}}},
    "required": ["profesor", "resumen", "notas", "mnemotecnias", "esquemas"]}

HORA = 3600  # s de clase por petición de análisis: con la clase entera de golpe el modelo resume demasiado (20 notas en 7 h)


def analizar(trans, partes, doc, resumen, base, profes=()):
    bloques = {}
    for s in trans:
        bloques.setdefault((s["parte"], s["t"] // HORA), []).append(s)
    bloques = list(bloques.values())
    tema = texto_paginas(doc, range(len(doc)))
    log(f"Análisis de profesorado con {ANALIZA}: {len(bloques)} partes…")

    def una(k, bl):
        f = base / f"analisis_{k:02d}.json"
        if not f.exists():
            trozo = "\n".join(f"[{minuto(s, partes)}] {s['quien']}: {s['texto']}" for s in bl)
            an = generar(ANALIZA, PIDE_ANALISIS.format(k=k + 1, n=len(bloques), desde=minuto(bl[0], partes),
                                                       hasta=minuto(bl[-1], partes), trans=trozo, tema=tema,
                                                       resumen=resumen or "(no hay)"), ESQ_ANALISIS)
            guardar(f, an)
            log(f"  parte {k + 1}/{len(bloques)}: {len(an['notas'])} notas")
        return json.loads(f.read_text())

    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(una, range(len(bloques)), bloques))

    def profe(bl):  # el que se pasó con --profe para esa parte; el nombre que adivina el modelo no es fiable
        return profes[bl[0]["parte"] - 1] if bl[0]["parte"] <= len(profes) else ""

    firma = lambda bl, xs: [{**x, "profe": profe(bl)} if profe(bl) else x for x in xs]
    return {"profesor": " y ".join(dict.fromkeys(p for p in profes if p))
                        or next((r["profesor"] for r in res if r["profesor"].strip()), ""),
            "resumen": [f"{minuto(bl[0], partes)} → {minuto(bl[-1], partes)}{f' ({profe(bl)})' if profe(bl) else ''}: {r['resumen']}"
                        for bl, r in zip(bloques, res)],
            "notas": [x for bl, r in zip(bloques, res) for x in firma(bl, r["notas"])],
            "mnemotecnias": [x for bl, r in zip(bloques, res) for x in firma(bl, r["mnemotecnias"])],
            "esquemas": [x for r in res for x in r["esquemas"]]}


PIDE_ESQUEMAS = """Eres el mejor opositor a Guardia Civil de la academia y estás pasando a limpio los esquemas del tema para estudiarlos
la víspera del examen. Abajo tienes el tema oficial (con número de página), las notas que tomaste en clase y un primer borrador
de cada esquema. Rehaz CADA esquema del borrador (mismo título y «despues_de_pagina», en el mismo orden) para que sea completo:
- 16-30 nodos en 3-4 niveles: el bloque → sus apartados → los datos que caen en el test (cifras, plazos, mayorías, sedes,
  quién propone/elige/aprueba) → y un nodo «ojo» en cada trampa que marcó el profesor.
- Etiquetas de ≤ 8 palabras, estilo apunte (abreviaturas, «=», «→»); las cifras SIEMPRE con su número.
- Que se pueda estudiar SOLO con el esquema: nada que no esté en el tema o en las notas.
- «pie»: la idea que el profesor más repitió de ese bloque, una frase.
- Puedes añadir 1-3 esquemas nuevos si un bloque que el profesor trabajó mucho no tiene.

=== BORRADOR DE ESQUEMAS ===
{borrador}

=== NOTAS DE CLASE ===
{notas}

=== TEMA OFICIAL ===
{tema}"""


def esquemas(an, doc):
    borrador = "\n".join(f"- {e['titulo']} (después de pág. {e['despues_de_pagina']}): "
                         + "; ".join(n["texto"] for n in e["nodos"]) for e in an["esquemas"])
    notas = "\n".join(f"p.{n['pagina']} [{n['tipo']}] {n['nota']}" for n in an["notas"])
    notas += "\n" + "\n".join(f"p.{m['pagina']} [mnemotecnia] {m['regla']} = {m['significa']}" for m in an["mnemotecnias"])
    r = generar(ANALIZA, PIDE_ESQUEMAS.format(borrador=borrador, notas=notas, tema=texto_paginas(doc, range(len(doc)))),
                {"type": "object", "properties": {"esquemas": ESQ_ANALISIS["properties"]["esquemas"]}, "required": ["esquemas"]})
    return r["esquemas"]


# Subrayado de estudio (amarillo) página a página: lo que marcaría el alumno aunque el profe no lo diga.
PIDE_SUBRAYADO = """Eres un opositor a Guardia Civil subrayando su temario en amarillo. Para cada página de abajo, copia LETRA A LETRA
los fragmentos (3-14 palabras) que subrayarías para el test: cifras, plazos, mayorías, órganos, sedes, fechas, definiciones clave,
excepciones. 2-7 por página con contenido; 0 en portadas e índices. Nada de párrafos enteros.
{resumen}
{paginas}"""

ESQ_SUBRAYADO = {"type": "array", "items": {"type": "object", "properties": {
    "pagina": {"type": "integer"}, "fragmentos": {"type": "array", "items": {"type": "string"}}},
    "required": ["pagina", "fragmentos"]}}


def subrayado(doc, resumen):
    lotes = [range(i, min(i + 15, len(doc))) for i in range(0, len(doc), 15)]
    pista = f"Orientación (resumen del año pasado, lo que importa):\n{resumen[:60000]}" if resumen else ""
    with ThreadPoolExecutor(4) as ex:
        res = ex.map(lambda r: generar(TRANSCRIBE, PIDE_SUBRAYADO.format(resumen=pista, paginas=texto_paginas(doc, r)),
                                       ESQ_SUBRAYADO), lotes)
    return [x for lote in res for x in lote]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tema", type=int, choices=range(1, 24), metavar="1-23")
    ap.add_argument("--audio", action="append", default=[], type=Path)
    ap.add_argument("--profe", action="append", default=[], help="profesor de cada --audio, en el mismo orden")
    ap.add_argument("--url", default="")
    ap.add_argument("--fecha", default=date.today().isoformat())
    ap.add_argument("--abrir", action="store_true", help="abre el PDF en Okular al acabar")
    a = ap.parse_args()

    if not a.audio and not a.url:
        abierta = clase_abierta()
        if abierta:
            a.url = abierta[0]
            log(f"Clase abierta en Chrome: {abierta[1] or a.url}")
    if a.url and not a.audio and not a.profe:
        p = profe_de(parse_qs(urlparse(a.url).query).get("title", [""])[0])
        a.profe = [p] if p else []
    if not a.audio:
        f = bajar(a.url) if a.url else None
        if not f:
            f = ultimo_descargado(6 if a.url else None)
            if a.url and f:
                log(f"No pude bajar el vídeo de {a.url}; uso lo último de la extensión: {f}")
        if not f:
            sys.exit("No pude bajar el vídeo (la web de la academia lo protege). Bájalo con la extensión Vimeo "
                     "Media Downloader y vuelve a pedírmelo: cogeré lo último de " + str(EXTENSION))
        a.audio = [f]
    for f in a.audio:
        comprobar_audio(f)
    a.tema = a.tema or tema_de(a.audio[0].name)
    if not a.tema:
        sys.exit(f"No sé de qué tema es «{a.audio[0].name}»: dímelo (--tema N)")
    if not 1 <= a.tema <= 23:
        sys.exit(f"El temario va del 1 al 23, no hay tema {a.tema}")
    tema_pdf = pdf_tema(a.tema)

    carpeta = TRABAJO / f"tema{a.tema:02d}"
    carpeta.mkdir(parents=True, exist_ok=True)
    cerrojo = open(carpeta / ".cerrojo", "w")  # se suelta solo al salir el proceso
    try:
        fcntl.flock(cerrojo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(f"Otra clase del tema {a.tema} se está procesando: espero a que acabe y junto esta con ella")
        fcntl.flock(cerrojo, fcntl.LOCK_EX)
    f_clases = carpeta / "clases.json"
    clases = json.loads(f_clases.read_text()) if f_clases.exists() else []
    clases = juntar(clases, [misma_clase(f, clases) for f in a.audio], a.profe)
    guardar(f_clases, clases)
    audios, profes = [Path(c["audio"]) for c in clases], [c["profe"] for c in clases]

    clase = re.sub(r"[^\w-]+", "_", audios[0].stem)[:60].strip("_")
    base = carpeta / clase
    base.mkdir(exist_ok=True)
    doc = pymupdf.open(tema_pdf)
    resumen = texto_resumen(a.tema)
    log(f"Tema {a.tema}, {len(audios)} clase(s): " + "; ".join(f"{x.name} ({p or '¿profe?'})" for x, p in zip(audios, profes)))
    log(f"Tema {a.tema}: {len(doc)} págs; resumen del año pasado: {resumen.count('=== PÁGINA')} págs")

    f_trans = base / "transcripcion.json"
    if f_trans.exists() and max(s["parte"] for s in json.loads(f_trans.read_text())) != len(audios):
        # clase añadida al tema: los tramos y bloques ya hechos salen de su caché, solo se rehace lo que junta
        log("Clase nueva en el tema: la junto con las anteriores")
        for f in (f_trans, base / "esquemas.json"):
            f.unlink(missing_ok=True)
    if not f_trans.exists():
        log("Transcribiendo…")
        guardar(f_trans, transcribir(audios, base))
    trans = json.loads(f_trans.read_text())
    partes = max(s["parte"] for s in trans)
    texto_clase = "\n".join(f"[{minuto(s, partes)}] {s['quien']}: {s['texto']}" for s in trans)
    (base / "transcripcion.md").write_text(f"# Clase · Tema {a.tema} · {a.fecha}\n\n" + texto_clase.replace("\n", "\n\n"))
    log(f"Transcripción: {len(trans)} intervenciones, {len(texto_clase)} caracteres")

    f_sub = base / "subrayado.json"
    if not f_sub.exists():
        log("Subrayado de estudio…")
        guardar(f_sub, subrayado(doc, resumen))

    an = analizar(trans, partes, doc, resumen, base, profes)  # con los bloques en caché solo junta: sin coste
    guardar(base / "analisis.json", an)
    f_esq = base / "esquemas.json"
    if not f_esq.exists() and an["esquemas"]:
        log(f"Esquemas a fondo con {ANALIZA}…")
        guardar(f_esq, esquemas(an, doc))
    if f_esq.exists():
        an["esquemas"] = json.loads(f_esq.read_text())
    log(f"Análisis: {len(an['notas'])} notas, {len(an['mnemotecnias'])} mnemotecnias, {len(an['esquemas'])} esquemas")

    import estudio_pdf
    SALIDA.mkdir(exist_ok=True)
    destino = SALIDA / f"{tema_pdf.stem} (Delta).pdf"
    tmp = SALIDA / f".{destino.stem}.tmp.pdf"  # el PDF bueno no se toca hasta que el nuevo está entero
    informe = estudio_pdf.componer(tema_pdf, an, json.loads(f_sub.read_text()), tmp, base)
    viejas = SALIDA / "Versiones anteriores"
    for f in SALIDA.glob(f"{tema_pdf.stem} (Delta*.pdf"):
        # se guarda copia si tiene anotaciones suyas de Okular (o es de cuando el nombre llevaba fecha); si no, se pisa
        if f != destino or estudio_pdf.tocado_a_mano(f):
            viejas.mkdir(exist_ok=True)
            os.replace(f, viejas / f"{f.stem} hasta {time.strftime('%Y-%m-%d %H.%M', time.localtime(f.stat().st_mtime))}.pdf")
            log(f"Copia de la versión anterior en «{viejas.name}/»")
    os.replace(tmp, destino)
    log(informe)
    print(f"LISTO {destino}")
    if a.abrir:
        subprocess.Popen(["okular", str(destino)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    main()
