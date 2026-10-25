"""Secretario: redacta documentos (PDF, Word, ODT, texto, Markdown), con búsquedas web si hace falta,
y convierte los informes de la investigación a PDF o Word. Todo en ~/Documentos/Delta/documentos.

PDF con Chromium sin cabeza, Word/ODT con LibreOffice sin cabeza: los dos ya están instalados.
Se registra en acciones al importarse (como deltaos).
"""
import asyncio
import html
import json
import re
import shutil
import tempfile
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

import acciones
import deltaos
import movil
import panel
from acciones import AQUI, avisar, paso, _run

DOCS = deltaos.DELTA / "documentos"
DOCS.mkdir(parents=True, exist_ok=True)
FORMATOS = ("pdf", "docx", "odt", "txt", "md")
VISIBLES = (".pdf", ".txt", ".md")  # los que el visor del panel sabe enseñar

# El HTML lo escribe un modelo que puede haber leído webs ajenas: sin scripts ni recursos externos.
PLANTILLA = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<title>{t}</title><style>
@page{{size:A4;margin:22mm 20mm}}
body{{font:11.5pt/1.55 "Noto Serif","DejaVu Serif",Georgia,serif;color:#111;max-width:170mm;margin:0 auto}}
h1{{font:600 21pt/1.2 "Noto Sans","DejaVu Sans",sans-serif;margin:0 0 6mm}}
h2{{font:600 13pt "Noto Sans","DejaVu Sans",sans-serif;margin:7mm 0 2mm}}
h3{{font:600 11.5pt "Noto Sans","DejaVu Sans",sans-serif}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #999;padding:4px 8px;text-align:left}}
th{{background:#eee}}a{{color:#111}}.c{{font-size:8pt;vertical-align:super}}
.f{{font-size:9pt;color:#444}}</style>
<body>{cuerpo}{fuentes}</body></html>"""


def _nombre(titulo, ext):
    return time.strftime("%Y%m%d-%H%M-") + (re.sub(r"[^\w]+", "-", titulo.lower())[:50].strip("-") or "documento") + ext


def _lugar():
    try:
        return json.loads((AQUI / "ubicacion_fija.json").read_text())["nombre"].split(",")[0]
    except (OSError, ValueError, KeyError):
        return ""


async def _pdf(origen, destino):
    """origen: URL (http:// o file://). Perfil propio para no chocar con el Chromium del panel."""
    with tempfile.TemporaryDirectory() as perfil:
        await _run(["chromium-browser", "--headless=new", f"--user-data-dir={perfil}", "--no-pdf-header-footer",
                    f"--print-to-pdf={destino}", origen], timeout=90)
    if not destino.is_file():
        raise RuntimeError("Chromium no generó el PDF")


async def _office(html_path, destino):
    """HTML → docx/odt. Perfil propio: con LibreOffice abierto, la conversión iría a esa instancia y no haría nada."""
    filtro = {"docx": "docx:MS Word 2007 XML", "odt": "odt:writer8"}[destino.suffix[1:]]
    with tempfile.TemporaryDirectory() as tmp:
        await _run(["soffice", f"-env:UserInstallation=file://{tmp}/perfil", "--headless",
                    "--infilter=HTML (StarWriter)", "--convert-to", filtro, "--outdir", tmp, str(html_path)], timeout=120)
        hecho = Path(tmp) / (html_path.stem + destino.suffix)
        if not hecho.is_file():
            raise RuntimeError("LibreOffice no generó el documento")
        shutil.move(hecho, destino)


async def _exportar(cuerpo_html, titulo, fuentes_html, destino):
    """Fragmento HTML → pdf/docx/odt en destino."""
    with tempfile.TemporaryDirectory() as tmp:
        h = Path(tmp) / (destino.stem + ".html")
        h.write_text(PLANTILLA.format(t=html.escape(titulo), cuerpo=cuerpo_html, fuentes=fuentes_html))
        if destino.suffix == ".pdf":
            await _pdf(h.as_uri(), destino)
        else:
            await _office(h, destino)


def _limpiar(fragmento):
    """Fuera scripts, estilos, iframes y manejadores on*: el documento solo es texto con formato."""
    f = re.sub(r"(?is)<(script|style|iframe|object|embed)\b.*?(</\1>|$)", "", fragmento)
    return re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)", "", f)


def _mostrar(destino, titulo):
    if destino.suffix in VISIBLES:
        deltaos._ver(f"/documentos/{quote(destino.name)}", f"DOCUMENTO · {titulo}")


async def _crear(encargo, formato, buscar, al_movil=False):
    p = paso(f"Redacto · {encargo[:60]}")
    try:
        notas, fuentes = "", []
        if buscar:
            plan = await deltaos._json(f"Hay que redactar este documento: «{encargo}». "
                                       'Devuelve JSON {"subpreguntas": [2 a 4 búsquedas web concretas con los datos que necesita]}.')
            paso(f"Busco {len(plan['subpreguntas'][:4])} cosas", "hecho")
            res = await asyncio.gather(*(deltaos._salto(s) for s in plan["subpreguntas"][:4]))
            fuentes = list({u: (t, u) for _, _, fs in res for t, u in fs}.values())
            num = {u: i + 1 for i, (_, u) in enumerate(fuentes)}
            notas = "\n\n".join(f"P: {q}\nR: {r}\nFuentes: {', '.join(f'[{num[u]}]' for _, u in fs)}" for q, r, fs in res)
        texto_plano = formato in ("txt", "md")
        forma = ("texto plano sin marcas" if formato == "txt" else "Markdown") if texto_plano else \
            "un fragmento HTML (h1, h2, h3, p, ul, ol, li, strong, em, table) sin estilos ni scripts"
        doc = await deltaos._json(
            f"Eres el secretario del usuario. Redacta en español este documento: «{encargo}».\n"
            f"Hoy es {time.strftime('%d/%m/%Y')}{' y el usuario está en ' + _lugar() if _lugar() else ''}. "
            "Si es una carta, instancia o similar, usa el formato formal habitual en España. Si el usuario ha dictado "
            "el texto, respétalo literal y solo dale formato. No inventes datos personales (nombre, DNI, dirección, "
            "teléfono, números de cuenta): deja un hueco entre corchetes, p. ej. [NOMBRE].\n"
            + (f"Usa estas notas de búsqueda. En documentos informativos cita con [n] lo que saques de ellas, solo con "
               f"esos números; en cartas, instancias y escritos formales NO pongas citas:\n{notas}\n" if notas else "")
            + f'Devuelve JSON {{"titulo": "título corto", "resumen": "una frase para decir en voz alta", '
              f'"cuerpo": "el documento completo como {forma}"}}.')
        titulo, cuerpo = doc["titulo"].strip() or encargo[:60], doc["cuerpo"].strip()
        destino = DOCS / _nombre(titulo, "." + formato)
        citadas = {int(n) for n in re.findall(r"\[(\d+)\]", cuerpo)}  # la lista solo lleva lo que el texto cita
        fuentes = [(i + 1, t, u) for i, (t, u) in enumerate(fuentes) if i + 1 in citadas]
        if texto_plano:
            if fuentes:
                cuerpo += "\n\nFuentes:\n" + "\n".join(f"[{n}] {t} — {u}" for n, t, u in fuentes)
            destino.write_text(cuerpo + "\n")
        else:
            cuerpo = re.sub(r"\[(\d+)\]", r'<span class="c">[\1]</span>', _limpiar(cuerpo))
            lista = "".join(f'<li>[{n}] <a href="{html.escape(u)}">{html.escape(t)}</a></li>' for n, t, u in fuentes)
            await _exportar(cuerpo, titulo, f'<h2>Fuentes</h2><ul class="f">{lista}</ul>' if lista else "", destino)
        p["e"] = "hecho"
        _mostrar(destino, titulo)
        panel.notificar("info", f"Documento listo: {destino.name}")
        envio = f" {await _al_movil(destino)}" if al_movil else ""
        await avisar(f"El documento «{titulo}» está listo en {destino}"
                     f"{' y en el panel' if destino.suffix in VISIBLES else ''}.{envio} Díselo al usuario en una frase: {doc.get('resumen', '')}")
    except Exception as e:
        p["e"] = "falló"
        await avisar(f"No he podido redactar el documento «{encargo[:80]}»: {e}")


async def crear_documento(encargo, formato="pdf", buscar="no", al_movil="no"):
    formato = formato.strip().lower().lstrip(".").replace("word", "docx").replace("texto", "txt").replace("markdown", "md")
    if formato not in FORMATOS:
        return f"Formato no válido: usa {', '.join(FORMATOS)}."
    acciones.tarea(_crear(encargo, formato, buscar.strip().lower() in ("sí", "si", "true", "yes"), al_movil.strip().lower() in ("sí", "si", "true", "yes")))
    return ("Redactando en segundo plano; los pasos salen en el panel y te aviso al terminar. "
            "Díselo al usuario en una frase.")


def _palabras(t):
    t = unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    return [w for w in re.split(r"[^a-z0-9]+", t) if w and w not in _RELLENO and not re.fullmatch(r"\d{8}|\d{4}", w)]


_RELLENO = set("de del la el los las lo y e o a al en un una unos unas para por con sin que mi me".split())


def _buscar(nombre):
    # 21/10: Delta pide por el título («Resumen provisional: Skills de…») y el fichero lleva el título
    # recortado y con guiones; por eso se compara por palabras y no como texto literal.
    pide = set(_palabras(nombre))
    mejor, nota = None, (0, 0)
    for f in (f for d in (deltaos.INFORMES, DOCS) for f in d.iterdir() if f.is_file()):
        tiene = set(_palabras(f.stem)) or {f.suffix}
        comun = len(pide & tiene)
        if nombre.lower() in f.name.lower() or (pide and comun >= min(2, len(pide)) and comun / min(len(pide), len(tiene)) >= 0.8):
            n = (comun, f.stat().st_mtime)
            if n > nota:
                mejor, nota = f, n
    return mejor


async def convertir_documento(nombre, formato="pdf"):
    formato = formato.strip().lower().lstrip(".").replace("word", "docx")
    if formato not in ("pdf", "docx", "odt"):
        return "Solo convierto a pdf, docx u odt."
    origen = _buscar(nombre.strip())
    if not origen:
        return f"No encuentro ningún informe ni documento que se llame «{nombre}»."
    destino = DOCS / (origen.stem + "." + formato)
    p = paso(f"Convierto {origen.name[:50]} a {formato}")
    try:
        if origen.suffix == ".html" and formato == "pdf":
            # por el panel, para que carguen sus fuentes; el informe trae su propio estilo de impresión
            await _pdf(f"http://127.0.0.1:{panel.PORT}/informes/{quote(origen.name)}", destino)
        elif origen.suffix == ".html":
            sin_estilo = re.sub(r"(?is)<style\b.*?</style>", "", origen.read_text())  # el tema negro saldría en blanco sobre blanco
            with tempfile.TemporaryDirectory() as tmp:
                h = Path(tmp) / origen.name
                h.write_text(sin_estilo)
                await _office(h, destino)
        elif origen.suffix in (".txt", ".md"):
            await _exportar(f"<pre style='white-space:pre-wrap;font:inherit'>{html.escape(origen.read_text())}</pre>",
                            origen.stem, "", destino)
        elif origen.suffix in (".docx", ".odt", ".pdf") and formato == "pdf":
            with tempfile.TemporaryDirectory() as tmp:
                await _run(["soffice", f"-env:UserInstallation=file://{tmp}/perfil", "--headless",
                            "--convert-to", "pdf", "--outdir", tmp, str(origen)], timeout=120)
                shutil.move(Path(tmp) / (origen.stem + ".pdf"), destino)
        else:
            return f"No sé convertir {origen.suffix} a {formato}."
    except Exception as e:
        p["e"] = "falló"
        return f"Falló la conversión: {e}"
    p["e"] = "hecho"
    _mostrar(destino, origen.stem)
    return f"Hecho: {destino}" + (" (abierto en el panel)." if destino.suffix in VISIBLES else ".")


async def _al_movil(f):
    d = await movil._movil()
    if not d:
        return f"No se ha enviado al móvil: {movil.NOMBRE} no está conectado a KDE Connect."
    rc, out = await _run(["kdeconnect-cli", "-d", d, "--share", str(f)], timeout=30)
    return f"Enviado al móvil ({f.name}); llega a su carpeta de descargas." if rc == 0 else f"Falló el envío al móvil: {out}"


async def enviar_al_movil(nombre):
    f = _buscar(nombre.strip())  # solo informes y documentos de Delta, nunca rutas arbitrarias
    if not f:
        return f"No encuentro ningún informe ni documento que se llame «{nombre}»."
    if f.suffix == ".html":  # el informe en HTML no se ve bien en el móvil: va en PDF
        pdf = DOCS / (f.stem + ".pdf")
        if not pdf.is_file():
            r = await convertir_documento(f.name, "pdf")
            if not r.startswith("Hecho"):
                return r
        f = pdf
    return await _al_movil(f)


async def _servir(request):
    f = (DOCS / request.match_info["n"]).resolve()
    if f.parent != DOCS.resolve() or not f.is_file():
        raise web.HTTPNotFound()
    tipo = {".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8"}.get(f.suffix)
    return web.FileResponse(f, headers={"Content-Security-Policy": "script-src 'none'",
                                        **({"Content-Type": tipo} if tipo else {})})

panel.RUTAS.append(("/documentos/{n}", _servir))


acciones.registrar([
    acciones._fn("crear_documento",
                 "Secretario: redacta un documento y lo guarda en ~/Documentos/Delta/documentos (carta, instancia, "
                 "reclamación, resumen, acta, lista, apuntes, dossier, notas dictadas…). Úsalo cuando pida «hazme un PDF», "
                 "«redáctame», «escríbeme una carta», «ponlo en un documento», «toma nota de esto en un archivo» (si dice «apunta en notas…», NO es esto). Con "
                 "buscar=sí hace antes unas búsquedas web y cita las fuentes. Para un informe de investigación a fondo usa "
                 "investigar y luego convertir_documento.",
                 {"encargo": acciones._s("qué documento quiere y para qué, con TODOS los datos que haya dado; si dicta "
                                         "el texto, cópialo literal"),
                  "formato": acciones._s("pdf (por defecto) | docx (Word) | odt | txt | md"),
                  "buscar": acciones._s("sí si hace falta buscar datos en internet, si no no"),
                  "al_movil": acciones._s("sí si quiere que se lo mande al móvil al terminar, si no no")}, req=["encargo"]),
    acciones._fn("enviar_al_movil",
                 "Manda al móvil del usuario (KDE Connect) un documento o informe ya hecho, p. ej. «mándame al móvil la "
                 "carta», «pásame el informe al teléfono». Los informes van en PDF.",
                 {"nombre": acciones._s("parte del nombre del documento o informe")}),
    acciones._fn("convertir_documento",
                 "Pasa un informe o documento ya hecho a PDF, Word (docx) u ODT, p. ej. «pásame el informe a PDF».",
                 {"nombre": acciones._s("parte del nombre del informe o documento"),
                  "formato": acciones._s("pdf | docx | odt")}, req=["nombre"]),
], (crear_documento, convertir_documento, enviar_al_movil))
