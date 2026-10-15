#!/usr/bin/env python3
"""Clase → apuntes: audio de una clase + tema del temario → PDF anotado.

Uso: estudio_clase.py [--tema 1] (--audio parte1.mp3 [--audio parte2.mp3] | --url <página del vídeo> | nada)
Sin audio ni URL usa lo último que bajó la extensión de Vimeo. Sin tema, lo saca del nombre («T1_DDHH…»).
Cada etapa deja su caché en ~/Documentos/Delta/estudio/temaNN/<clase>/ y se reanuda sola.
"""
import argparse
import json
import re
import subprocess
import threading
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pymupdf
from google import genai
from google.genai import types

TEMARIO = Path.home() / "Escritorio/Temario_Guardia_Civil"
SALIDA = TEMARIO / "Editados por mi"
RESUMEN = Path.home() / "Escritorio/MEGARESUMIDO_GUARDIA CIVIL 2026 (DIGITAL).pdf"
TRABAJO = Path.home() / "Documentos/Delta/estudio"
EXTENSION = Path.home() / "Descargas/vimeoMediaDownloader"  # donde guarda la extensión Vimeo Media Downloader
MEDIOS = {".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".opus", ".mkv", ".wav", ".aac"}
TRANSCRIBE = "gemini-3.8-flash"
ANALIZA = "gemini-pro-latest"
TRAMO = 1800  # s por trozo de audio: ~8 k tokens de salida, holgado
RUIDO = re.compile(r"P\s?R\s?O\s?C\s?I\s?V\s?I\s?L|IVIL\.ES|INGRESO G[Cc]|Todos los derechos", re.I)

_cli = None
_cerrojo = threading.Lock()


def gem():
    # un único cliente: si dos hilos crean el suyo, el que se pierde lo recoge el GC y cierra el httpx compartido
    global _cli
    with _cerrojo:
        _cli = _cli or genai.Client()
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

def bajar(url):
    """yt-dlp con la página que se está viendo: el Vimeo embebido de la academia pide referer y sesión."""
    dest = TRABAJO / "descargas"
    dest.mkdir(parents=True, exist_ok=True)
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
    cache.write_text(json.dumps(limpio, ensure_ascii=False))
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
- ESQUEMAS: uno por cada bloque importante del tema (los epígrafes que el profesor trabajó). 10-30 nodos, etiquetas de ≤ 8 palabras
  con las cifras clave; jerarquía con «padre» (id del nodo padre, vacío para la raíz, solo UNA raíz por esquema).
  Tipo de nodo: titulo (raíz), rama, dato (cifra/plazo), ojo (trampa de examen). «despues_de_pagina» = última página del bloque.
- «resumen»: 5-8 frases con lo que trató la clase y lo que más insistió.

=== TRANSCRIPCIÓN DE LA CLASE ===
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
    ap.add_argument("--tema", type=int)
    ap.add_argument("--audio", action="append", default=[], type=Path)
    ap.add_argument("--url", default="")
    ap.add_argument("--fecha", default=date.today().isoformat())
    ap.add_argument("--abrir", action="store_true", help="abre el PDF en Okular al acabar")
    a = ap.parse_args()

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
    a.tema = a.tema or tema_de(a.audio[0].name)
    if not a.tema:
        sys.exit(f"No sé de qué tema es «{a.audio[0].name}»: dímelo (--tema N)")
    tema_pdf = pdf_tema(a.tema)
    clase = re.sub(r"[^\w-]+", "_", a.audio[0].stem)[:60].strip("_")
    base = TRABAJO / f"tema{a.tema:02d}" / clase
    base.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(tema_pdf)
    resumen = texto_resumen(a.tema)
    log(f"Clase: {', '.join(x.name for x in a.audio)}")
    log(f"Tema {a.tema}: {len(doc)} págs; resumen del año pasado: {resumen.count('=== PÁGINA')} págs")

    f_trans = base / "transcripcion.json"
    if not f_trans.exists():
        if not a.audio:
            sys.exit("Falta --audio (y no hay transcripción guardada)")
        log("Transcribiendo…")
        f_trans.write_text(json.dumps(transcribir(a.audio, base), ensure_ascii=False))
    trans = json.loads(f_trans.read_text())
    partes = max(s["parte"] for s in trans)
    texto_clase = "\n".join(f"[{minuto(s, partes)}] {s['quien']}: {s['texto']}" for s in trans)
    (base / "transcripcion.md").write_text(f"# Clase · Tema {a.tema} · {a.fecha}\n\n" + texto_clase.replace("\n", "\n\n"))
    log(f"Transcripción: {len(trans)} intervenciones, {len(texto_clase)} caracteres")

    f_sub = base / "subrayado.json"
    if not f_sub.exists():
        log("Subrayado de estudio…")
        f_sub.write_text(json.dumps(subrayado(doc, resumen), ensure_ascii=False))

    f_an = base / "analisis.json"
    if not f_an.exists():
        log(f"Análisis de profesorado con {ANALIZA}…")
        an = generar(ANALIZA, PIDE_ANALISIS.format(trans=texto_clase, tema=texto_paginas(doc, range(len(doc))),
                                                   resumen=resumen or "(no hay)"), ESQ_ANALISIS)
        f_an.write_text(json.dumps(an, ensure_ascii=False, indent=1))
    an = json.loads(f_an.read_text())
    log(f"Análisis: {len(an['notas'])} notas, {len(an['mnemotecnias'])} mnemotecnias, {len(an['esquemas'])} esquemas")

    import estudio_pdf
    SALIDA.mkdir(exist_ok=True)
    destino = SALIDA / f"{tema_pdf.stem} (Delta · clase {a.fecha}).pdf"
    informe = estudio_pdf.componer(tema_pdf, an, json.loads(f_sub.read_text()), destino, base)
    log(informe)
    print(f"LISTO {destino}")
    if a.abrir:
        subprocess.Popen(["okular", str(destino)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    main()
