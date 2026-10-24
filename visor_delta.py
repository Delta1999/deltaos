"""Control del Visor y Editor de Apuntes Manos Libres desde Gemini Live (Delta).

Permite interactuar por voz con el visor PDF (http://127.0.0.1:8766):
- Abrir el visor con un documento o tema.
- Activar o desactivar la cuadrícula espacial alfanumérica (A1, B2...).
- Subrayar pasajes de texto (o lo que señala el ratón).
- Crear esquemas y mapas conceptuales jerárquicos (Dagre.js) en el margen.
- Añadir ramas a esquemas existentes.
- Añadir notas y post-its al margen (aviso ⚠️, clave 💡, nota 📌).
- Activar o desactivar el modo de repaso activo (active recall).
- Deshacer la última intervención.
- Navegar entre páginas.
- Consultar el contexto espacial del ratón.
- Compilar el PDF físico vectorial con margen extendido de 400 pt (PyMuPDF).
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

import acciones
from acciones import _fn, _s

logger = logging.getLogger("visor_delta")

AQUI = Path(__file__).resolve().parent
VISOR_DIR = AQUI / "visor_apuntes"
STORAGE_DIR = VISOR_DIR / "storage"
PUERTO_VISOR = int(os.environ.get("VISOR_PORT", 8766))
URL_VISOR = f"http://127.0.0.1:{PUERTO_VISOR}"

COLORES = {
    "amarillo": "#fef08a",
    "naranja": "#fed7aa",
    "verde": "#bbf7d0",
    "azul": "#bae6fd",
    "rosa": "#fbcfe8",
    "morado": "#e9d5ff",
}


async def asegurar_servidor() -> bool:
    """Verifica si el servidor FastAPI del visor en el puerto 8766 está activo; si no, lo arranca."""
    try:
        async with httpx.AsyncClient(timeout=0.8) as client:
            resp = await client.get(f"{URL_VISOR}/api/context")
            if resp.status_code == 200:
                return True
    except Exception:
        pass

    py_bin = AQUI / ".venv" / "bin" / "python"
    if not py_bin.exists():
        py_bin = Path("python3")
    main_py = VISOR_DIR / "main.py"
    if not main_py.exists():
        logger.error(f"No existe {main_py}")
        return False

    env = dict(os.environ, PORT=str(PUERTO_VISOR))
    subprocess.Popen(
        [str(py_bin), str(main_py)],
        cwd=str(VISOR_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )

    for _ in range(15):
        await asyncio.sleep(0.2)
        try:
            async with httpx.AsyncClient(timeout=0.4) as client:
                resp = await client.get(f"{URL_VISOR}/api/context")
                if resp.status_code == 200:
                    return True
        except Exception:
            continue
    return False


async def enviar_comando(cmd: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Envía un comando al visor vía HTTP POST a /api/commands."""
    await asegurar_servidor()
    payload = {"command": cmd, "args": args or {}}
    async with httpx.AsyncClient(timeout=3.5) as client:
        resp = await client.post(f"{URL_VISOR}/api/commands", json=payload)
        resp.raise_for_status()
        return resp.json()


async def obtener_contexto() -> Dict[str, Any]:
    """Obtiene el contexto espacial actual del cursor del usuario en el visor."""
    await asegurar_servidor()
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{URL_VISOR}/api/context")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning(f"Error obteniendo contexto del visor: {e}")
    return {"page": 1, "nearest_cell": "E1", "mouse_pos": [0, 0], "nearest_text": ""}


# ─────────────────────────────────────────────────────────────────────────────
# Handlers de Acciones del Visor (asíncronos)
# ─────────────────────────────────────────────────────────────────────────────

async def apuntes_abrir(documento="", tema=""):
    """Abre el visor de apuntes en el navegador web."""
    listo = await asegurar_servidor()
    if not listo:
        return "Error: no se pudo iniciar el servidor del visor de apuntes."

    doc_a_abrir = "sample.pdf"
    if tema:
        num = "".join(c for c in str(tema) if c.isdigit())
        if num:
            estudio_dir = Path.home() / "Documentos" / "Delta" / "estudio" / f"tema{int(num):02d}"
            pdfs = list(estudio_dir.glob("**/*.pdf")) if estudio_dir.exists() else []
            if pdfs:
                dest = STORAGE_DIR / f"tema_{num}.pdf"
                if not dest.exists():
                    shutil.copy2(pdfs[0], dest)
                doc_a_abrir = dest.name
    elif documento:
        doc_path = Path(documento).expanduser()
        if doc_path.exists() and doc_path.is_file():
            dest = STORAGE_DIR / doc_path.name
            if not dest.exists():
                shutil.copy2(doc_path, dest)
            doc_a_abrir = dest.name
        else:
            coincidencias = list(STORAGE_DIR.glob(f"*{documento}*.pdf"))
            if coincidencias:
                doc_a_abrir = coincidencias[0].name

    url = f"{URL_VISOR}/"
    subprocess.Popen(["xdg-open", url], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if doc_a_abrir != "sample.pdf":
        await asyncio.sleep(0.5)
        try:
            await enviar_comando("open_document", {"doc_id": doc_a_abrir})
        except Exception:
            pass

    return f"Visor de apuntes abierto en {url} con {doc_a_abrir}."


async def apuntes_cuadricula(estado="ver"):
    """Muestra u oculta la cuadrícula de coordenadas alfanuméricas."""
    est = str(estado).lower().strip()
    show = est not in ("ocultar", "quitar", "no", "desactivar", "off", "false", "0")
    try:
        await enviar_comando("activate_grid", {"show": show})
        return "Cuadrícula alfanumérica activada en el visor." if show else "Cuadrícula desactivada."
    except Exception as e:
        return f"Error al cambiar cuadrícula: {e}"


async def apuntes_subrayar(texto="", color="amarillo", pagina=""):
    """Resalta un pasaje de texto en el visor de apuntes."""
    txt = str(texto).strip()
    ctx = await obtener_contexto()

    if not txt or txt.lower() in ("esto", "aqui", "aquí", "este parrafo", "este párrafo", "lo que señalo", "cursor"):
        txt = ctx.get("nearest_text", "").strip()
        if not txt:
            return "No he detectado texto bajo el cursor. Dime qué frase o palabra quieres subrayar."

    col_hex = COLORES.get(str(color).lower().strip(), color if str(color).startswith("#") else "#fef08a")

    try:
        pag = int(pagina) if str(pagina).strip().isdigit() else ctx.get("page", 1)
    except Exception:
        pag = 1

    try:
        await enviar_comando("highlight_passage", {
            "target_text": txt,
            "color": col_hex,
            "page": pag
        })
        return f"Subrayado en {color}: «{txt[:45]}…»."
    except Exception as e:
        return f"Error al subrayar: {e}"


async def apuntes_esquema(titulo="", celda="", nodos="", conexiones="", orientacion="TB", pagina=""):
    """Crea un mapa conceptual o árbol jerárquico en el margen derecho."""
    ctx = await obtener_contexto()
    c = str(celda).strip().upper()
    if not c or c in ("AQUI", "AQUÍ", "RATON", "RATÓN"):
        c = ctx.get("nearest_cell", "E1")

    try:
        pag = int(pagina) if str(pagina).strip().isdigit() else ctx.get("page", 1)
    except Exception:
        pag = 1

    root_label = titulo.strip() or "Esquema"
    schema_id = f"sch_{int(time.time())}"

    nodes_list = []
    edges_list = []

    if isinstance(nodos, list):
        nodes_list = nodos
    elif isinstance(nodos, str) and nodos.strip():
        if nodos.strip().startswith("["):
            try:
                nodes_list = json.loads(nodos)
            except Exception:
                pass
        if not nodes_list:
            items = [x.strip() for x in re.split(r"[,;\n]+", nodos) if x.strip()]
            nodes_list = [{"id": "root", "label": root_label, "details": []}]
            for i, it in enumerate(items, 1):
                nid = f"n_{i}"
                nodes_list.append({"id": nid, "label": it, "details": []})
                edges_list.append({"from": "root", "to": nid})
    else:
        nodes_list = [{"id": "root", "label": root_label, "details": []}]

    if isinstance(conexiones, list):
        edges_list = conexiones
    elif isinstance(conexiones, str) and conexiones.strip():
        if conexiones.strip().startswith("["):
            try:
                edges_list = json.loads(conexiones)
            except Exception:
                pass
        if not edges_list:
            for par in re.findall(r"(\w+)\s*->\s*(\w+)", conexiones):
                edges_list.append({"from": par[0], "to": par[1]})

    payload = {
        "schema_id": schema_id,
        "anchor_cell": c,
        "root_title": root_label,
        "orientation": orientacion if orientacion in ("TB", "LR", "BT", "RL") else "TB",
        "nodes": nodes_list,
        "edges": edges_list,
        "page": pag
    }

    try:
        await enviar_comando("create_schema", payload)
        return f"Esquema «{root_label}» creado en la celda {c} con {len(nodes_list)} conceptos."
    except Exception as e:
        return f"Error al crear esquema: {e}"


async def apuntes_rama(nodo_padre="", nuevo_nodo="", esquema_id="", pagina=""):
    """Añade un nuevo nodo y su conexión a un esquema existente."""
    ctx = await obtener_contexto()
    try:
        pag = int(pagina) if str(pagina).strip().isdigit() else ctx.get("page", 1)
    except Exception:
        pag = 1

    padre = str(nodo_padre).strip() or "root"
    label = str(nuevo_nodo).strip() or "Nuevo concepto"
    nid = f"node_{int(time.time() * 1000) % 100000}"

    payload = {
        "schema_id": esquema_id or None,
        "parent_node_id": padre,
        "new_node": {"id": nid, "label": label, "details": []},
        "page": pag
    }

    try:
        await enviar_comando("add_schema_branch", payload)
        return f"Rama «{label}» conectada al nodo «{padre}»."
    except Exception as e:
        return f"Error al añadir rama: {e}"


async def apuntes_nota(texto="", celda="", tipo="nota", pagina=""):
    """Inserta una tarjeta o post-it en el margen lateral a la altura de una celda."""
    txt = str(texto).strip()
    if not txt:
        return "Error: debes indicar el texto de la nota."

    ctx = await obtener_contexto()
    c = str(celda).strip().upper()
    if not c or c in ("AQUI", "AQUÍ", "RATON", "RATÓN"):
        c = ctx.get("nearest_cell", "F4")

    t = str(tipo).lower().strip()
    tipo_mapeado = "warning" if t in ("aviso", "warning", "alerta", "examen", "ojo") else \
                   "tip" if t in ("clave", "tip", "mnemotecnia", "truco", "idea") else "info"

    try:
        pag = int(pagina) if str(pagina).strip().isdigit() else ctx.get("page", 1)
    except Exception:
        pag = 1

    payload = {
        "cell": c,
        "text": txt,
        "note_type": tipo_mapeado,
        "page": pag
    }

    try:
        await enviar_comando("add_margin_note", payload)
        rotulo = "Aviso" if tipo_mapeado == "warning" else "Clave" if tipo_mapeado == "tip" else "Nota"
        return f"{rotulo} añadido en la celda {c}: «{txt[:45]}…»."
    except Exception as e:
        return f"Error al añadir nota: {e}"


async def apuntes_repaso(estado="activar"):
    """Activa o desactiva el modo de repaso activo (active recall)."""
    est = str(estado).lower().strip()
    enabled = est not in ("desactivar", "quitar", "no", "off", "false", "0")
    try:
        await enviar_comando("toggle_active_recall", {"enabled": enabled})
        return "Modo repaso activo activado: definiciones desenfocadas para autoevaluación." if enabled \
            else "Modo repaso activo desactivado."
    except Exception as e:
        return f"Error en modo repaso: {e}"


async def apuntes_deshacer():
    """Deshace la última acción en el visor."""
    try:
        await enviar_comando("undo_last_action", {})
        return "Última acción deshecha en el visor."
    except Exception as e:
        return f"Error al deshacer: {e}"


async def apuntes_pagina(numero=1):
    """Salta a una página específica en el visor."""
    try:
        pag = int(numero)
    except Exception:
        pag = 1
    try:
        await enviar_comando("go_to_page", {"page": pag})
        return f"Navegando a la página {pag}."
    except Exception as e:
        return f"Error al saltar de página: {e}"


async def apuntes_exportar(documento=""):
    """Compila las notas y esquemas en un PDF físico ensanchado con PyMuPDF."""
    await asegurar_servidor()
    doc_id = documento.strip() or "sample.pdf"
    if not doc_id.endswith(".pdf"):
        doc_id += ".pdf"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{URL_VISOR}/api/export/{doc_id}")
            if resp.status_code == 200:
                data = resp.json()
                filename = data.get("filename", "")
                return f"PDF exportado correctamente: {filename}. Compilado con margen extendido de 400 pt, esquemas y notas vectoriales."
            else:
                return f"Error al exportar PDF: {resp.text}"
    except Exception as e:
        return f"Error al exportar: {e}"


async def apuntes_cursor():
    """Consulta la posición del cursor, la celda actual y el texto más cercano."""
    ctx = await obtener_contexto()
    pag = ctx.get("page", 1)
    celda = ctx.get("nearest_cell", "A1")
    txt = ctx.get("nearest_text", "")
    if txt:
        return f"Página {pag}, celda {celda}. Texto bajo el cursor: «{txt[:120]}…»."
    return f"Página {pag}, celda {celda}. El cursor no está sobre ningún bloque de texto."


# ─────────────────────────────────────────────────────────────────────────────
# Registro en el Sistema de Herramientas de Delta
# ─────────────────────────────────────────────────────────────────────────────
acciones.ETIQUETAS.update({
    "apuntes": "Apuntes",
    "apuntes_abrir": "Abro visor de apuntes",
    "apuntes_cuadricula": "Cuadrícula de apuntes",
    "apuntes_subrayar": "Subrayo en apuntes",
    "apuntes_esquema": "Creo esquema en apuntes",
    "apuntes_rama": "Añado rama",
    "apuntes_nota": "Nota en margen",
    "apuntes_repaso": "Modo repaso activo",
    "apuntes_deshacer": "Deshago en apuntes",
    "apuntes_pagina": "Página en apuntes",
    "apuntes_exportar": "Compilo PDF de apuntes",
    "apuntes_cursor": "Posición del cursor",
})

acciones.registrar([
    _fn("apuntes_abrir", "Abre el visor de apuntes manos libres en el navegador web (http://127.0.0.1:8766).",
        {"documento": _s("nombre del PDF o archivo a abrir"), "tema": _s("número de tema")}),
    _fn("apuntes_cuadricula", "Muestra u oculta la cuadrícula espacial alfanumérica A1, B2... sobre el PDF.",
        {"estado": _s("ver | ocultar")}),
    _fn("apuntes_subrayar", "Resalta un texto o lo que el usuario señala con el ratón en el visor.",
        {"texto": _s("frase o pasaje a resaltar (vacío o «esto» para lo señalado con el ratón)"),
         "color": _s("amarillo | naranja | verde | azul | rosa"),
         "pagina": _s("número de página (1-based)")}),
    _fn("apuntes_esquema", "Genera un mapa conceptual jerárquico Dagre.js en el margen derecho.",
        {"titulo": _s("título principal"), "celda": _s("celda alfanumérica de anclaje (ej. E1, F4)"),
         "nodos": _s("lista de conceptos clave"), "conexiones": _s("relaciones origen->destino"),
         "pagina": _s("número de página")}),
    _fn("apuntes_rama", "Añade un nuevo concepto conectado a un esquema existente en el visor.",
        {"nodo_padre": _s("id o texto del nodo padre"), "nuevo_nodo": _s("concepto a añadir"),
         "pagina": _s("número de página")}),
    _fn("apuntes_nota", "Inserta una tarjeta o post-it en el margen lateral.",
        {"texto": _s("texto de la nota"), "celda": _s("celda de anclaje (ej. F4)"),
         "tipo": _s("aviso | clave | nota"), "pagina": _s("número de página")}),
    _fn("apuntes_repaso", "Activa o desactiva el modo de repaso activo (active recall).",
        {"estado": _s("activar | desactivar")}),
    _fn("apuntes_deshacer", "Deshace la última acción en el visor."),
    _fn("apuntes_pagina", "Salta a una página concreta del documento en el visor.",
        {"numero": _s("número de página a visualizar")}),
    _fn("apuntes_exportar", "Compila y exporta el PDF vectorial con el margen ensanchado de 400 pt.",
        {"documento": _s("nombre del documento")}),
    _fn("apuntes_cursor", "Consulta la celda, página y texto que el usuario está señalando con el ratón."),
], [
    apuntes_abrir, apuntes_cuadricula, apuntes_subrayar, apuntes_esquema,
    apuntes_rama, apuntes_nota, apuntes_repaso, apuntes_deshacer,
    apuntes_pagina, apuntes_exportar, apuntes_cursor
])
