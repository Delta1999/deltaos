"""Servidor FastAPI para el Visor y Editor de Apuntes Manos Libres.

Gestiona:
- Servicio de archivos PDF y estáticos del frontend.
- Persistencia no destructiva con archivos sidecar JSON (.notes.json).
- Canal WebSocket bidireccional para comandos de voz y contexto espacial del ratón.
- Compilación y exportación vectorial nativa con PyMuPDF (ensanchado de MediaBox y estampado de esquemas, notas, llaves y sellos).
- Exposición de esquemas de herramientas Function Calling para agentes de IA (Gemini Live/Multimodal).
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymupdf
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("visor_apuntes")

BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
STORAGE_DIR = BASE_DIR / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

MARGIN_EXTEND_PT = 380.0  # Puntos añadidos a la derecha del PDF para el margen extendido

EMOJI_FALLBACK = {
    "⚠️": "[!]",
    "👁️": "[OJO]",
    "⭐": "[*]",
    "🎯": "[TEST]",
    "⚖️": "[LEY]",
    "💡": "[TIP]",
    "📌": "[NOTA]"
}

def clean_pdf_text(text: str) -> str:
    for em, rep in EMOJI_FALLBACK.items():
        text = text.replace(em, rep)
    return text


app = FastAPI(title="Visor y Editor de Apuntes Manos Libres", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Gestor de Conexiones WebSocket y Contexto Espacial ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.latest_mouse_context: Dict[str, Any] = {
            "page": 1,
            "nearest_cell": "A1",
            "mouse_pos": [0, 0],
            "nearest_text": "",
            "timestamp": 0,
        }

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Cliente WebSocket conectado. Conexiones activas: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Cliente WebSocket desconectado. Conexiones activas: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Error al enviar mensaje WS: {e}")
                disconnected.append(connection)
        for dead in disconnected:
            self.disconnect(dead)

    def update_mouse_context(self, context: Dict[str, Any]):
        self.latest_mouse_context.update(context)


manager = ConnectionManager()


# --- Modelos de Datos Pydantic ---
class CommandPayload(BaseModel):
    command: str
    args: Dict[str, Any] = {}


def _notes_path(doc_id: str) -> Path:
    base_name = doc_id[:-4] if doc_id.lower().endswith(".pdf") else doc_id
    return STORAGE_DIR / f"{base_name}.notes.json"


# --- Endpoints HTTP ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html no encontrado")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.get("/api/documents")
async def list_documents():
    """Lista todos los PDFs disponibles en el almacenamiento local."""
    files = sorted([f.name for f in STORAGE_DIR.glob("*.pdf") if not f.name.endswith("_anotado.pdf")])
    return {"documents": files}


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Permite subir un nuevo archivo PDF para estudio."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos en formato PDF.")

    target_path = STORAGE_DIR / file.filename
    with open(target_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    notes_file = _notes_path(file.filename)
    if not notes_file.exists():
        initial_notes = {"document_id": file.filename, "version": 1, "pages": {}}
        notes_file.write_text(json.dumps(initial_notes, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"status": "uploaded", "filename": file.filename}


@app.get("/api/pdf/{doc_id}")
async def get_pdf(doc_id: str):
    """Devuelve el archivo binario del PDF solicitado."""
    pdf_path = STORAGE_DIR / doc_id
    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail=f"PDF '{doc_id}' no encontrado.")
    return FileResponse(pdf_path, media_type="application/pdf", filename=doc_id)


@app.get("/api/notes/{doc_id}")
async def get_notes(doc_id: str):
    """Obtiene el JSON sidecar de notas no destructivas del documento."""
    path = _notes_path(doc_id)
    if not path.exists():
        return {"document_id": doc_id, "version": 1, "pages": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error leyendo sidecar {path}: {e}")
        raise HTTPException(status_code=500, detail="Error al leer las notas del documento.")


@app.post("/api/notes/{doc_id}")
async def save_notes(doc_id: str, notes: Dict[str, Any]):
    """Persiste las notas en el archivo sidecar JSON."""
    path = _notes_path(doc_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
        logger.info(f"Notas persistidas en {path.name}")
        await manager.broadcast({
            "type": "notes_saved",
            "document_id": doc_id
        })
        return {"status": "ok", "file": path.name}
    except Exception as e:
        logger.error(f"Error guardando {path}: {e}")
        raise HTTPException(status_code=500, detail="Error al guardar las notas.")


@app.get("/api/context")
async def get_context():
    """Devuelve el estado contextual actual del cursor para el orquestador de voz."""
    return manager.latest_mouse_context


@app.get("/api/tools")
async def get_tools_schema():
    """Devuelve los esquemas estándar de Function Calling para el LLM."""
    schema_file = BASE_DIR / "function_calling_schemas.json"
    if schema_file.exists():
        return json.loads(schema_file.read_text(encoding="utf-8"))
    return []


@app.post("/api/commands")
async def emit_command(cmd: CommandPayload):
    """Permite a agentes externos emitir llamadas a herramientas vía HTTP."""
    logger.info(f"Comando recibido por HTTP: {cmd.command} | Args: {cmd.args}")
    msg = {
        "type": "voice_command",
        "command": cmd.command,
        "args": cmd.args
    }
    await manager.broadcast(msg)
    return {"status": "dispatched", "command": cmd.command}


# --- Endpoint WebSocket ---

@app.websocket("/ws/commands")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
                msg_type = data.get("type")

                if msg_type == "mouse_context":
                    manager.update_mouse_context(data)
                elif msg_type == "execute_command":
                    await manager.broadcast({
                        "type": "voice_command",
                        "command": data.get("command"),
                        "args": data.get("args", {})
                    })
                elif msg_type == "save_notes":
                    doc_id = data.get("document_id")
                    notes_content = data.get("notes")
                    if doc_id and notes_content:
                        path = _notes_path(doc_id)
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(notes_content, f, ensure_ascii=False, indent=2)
                        await manager.broadcast({
                            "type": "notes_saved",
                            "document_id": doc_id
                        })
            except json.JSONDecodeError:
                logger.warning(f"Mensaje JSON no válido por WS: {raw_data[:80]}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Excepción en WebSocket: {e}")
        manager.disconnect(websocket)


# --- Motor de Compilación y Exportación con PyMuPDF ---

@app.post("/api/export/{doc_id}")
async def export_pdf(doc_id: str):
    """Compila las anotaciones vectoriales, esquemas, llaves y notas en un PDF físico ensanchado."""
    pdf_path = STORAGE_DIR / doc_id
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no encontrado.")

    notes_path = _notes_path(doc_id)
    notes_data = {}
    if notes_path.exists():
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                notes_data = json.load(f)
        except Exception as e:
            logger.error(f"Error cargando notas para exportación: {e}")

    output_filename = f"{pdf_path.stem}_anotado.pdf"
    output_path = STORAGE_DIR / output_filename

    try:
        doc = pymupdf.open(str(pdf_path))
        pages_notes = notes_data.get("pages", {})

        for page_idx in range(len(doc)):
            page_key = str(page_idx + 1)
            pdata = pages_notes.get(page_key, {})
            page = doc[page_idx]

            # 1. Ampliar MediaBox y CropBox hacia la derecha para el margen virtual
            mb = page.mediabox
            ancho_orig = mb.width
            nuevo_ancho = ancho_orig + MARGIN_EXTEND_PT
            extended_rect = pymupdf.Rect(mb.x0, mb.y0, nuevo_ancho, mb.y1)
            page.set_mediabox(extended_rect)
            page.set_cropbox(extended_rect)

            # Dibujar línea sutil divisoria del margen extendido
            page.draw_line(
                pymupdf.Point(ancho_orig, mb.y0),
                pymupdf.Point(ancho_orig, mb.y1),
                color=(0.80, 0.83, 0.88),
                width=0.75,
                dashes="[3 3] 0"
            )

            # Rótulo tenue "MARGEN EXTENDIDO"
            page.insert_textbox(
                pymupdf.Rect(ancho_orig + 10, mb.y0 + 10, ancho_orig + 180, mb.y0 + 24),
                "MARGEN EXTENDIDO (ESTUDIO)",
                fontsize=7.5,
                fontname="helv",
                color=(0.60, 0.65, 0.72)
            )

            # 2. Resaltados de texto (Highlights nativos)
            for hl in pdata.get("highlights", []):
                hex_color = hl.get("color", "#fef08a").lstrip("#")
                if len(hex_color) == 6:
                    r, g, b = (int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
                else:
                    r, g, b = (1.0, 0.94, 0.3)

                for r_box in hl.get("rects", []):
                    if len(r_box) >= 4:
                        rect = pymupdf.Rect(r_box[0], r_box[1], r_box[2], r_box[3])
                        annot = page.add_highlight_annot(quads=[rect.quad])
                        annot.set_colors(stroke=(r, g, b))
                        annot.set_info(content=clean_pdf_text(hl.get("text", "")), title="Visor Apuntes AI")
                        annot.update()

            # 3. Llaves verticales de agrupación (Bracket Groups)
            for br in pdata.get("brackets", []):
                y_start = float(br.get("y_start", 100))
                y_end = float(br.get("y_end", 250))
                y_mid = (y_start + y_end) / 2
                bx = float(br.get("x", ancho_orig - 12))
                bw = 10.0
                r_arc = 8.0

                # Trazado de la llave vertical { apuntando hacia el margen
                page.draw_bezier(
                    pymupdf.Point(bx, y_start),
                    pymupdf.Point(bx + bw, y_start),
                    pymupdf.Point(bx + bw, y_start),
                    pymupdf.Point(bx + bw, y_start + r_arc),
                    color=(0.25, 0.45, 0.75), width=1.4
                )
                page.draw_line(
                    pymupdf.Point(bx + bw, y_start + r_arc),
                    pymupdf.Point(bx + bw, y_mid - r_arc),
                    color=(0.25, 0.45, 0.75), width=1.4
                )
                page.draw_bezier(
                    pymupdf.Point(bx + bw, y_mid - r_arc),
                    pymupdf.Point(bx + bw, y_mid),
                    pymupdf.Point(bx + 2 * bw, y_mid),
                    pymupdf.Point(bx + 2 * bw, y_mid),
                    color=(0.25, 0.45, 0.75), width=1.4
                )
                page.draw_bezier(
                    pymupdf.Point(bx + 2 * bw, y_mid),
                    pymupdf.Point(bx + 2 * bw, y_mid),
                    pymupdf.Point(bx + bw, y_mid),
                    pymupdf.Point(bx + bw, y_mid + r_arc),
                    color=(0.25, 0.45, 0.75), width=1.4
                )
                page.draw_line(
                    pymupdf.Point(bx + bw, y_mid + r_arc),
                    pymupdf.Point(bx + bw, y_end - r_arc),
                    color=(0.25, 0.45, 0.75), width=1.4
                )
                page.draw_bezier(
                    pymupdf.Point(bx + bw, y_end - r_arc),
                    pymupdf.Point(bx + bw, y_end),
                    pymupdf.Point(bx, y_end),
                    pymupdf.Point(bx, y_end),
                    color=(0.25, 0.45, 0.75), width=1.4
                )

                lbl_text = clean_pdf_text(br.get("label", ""))
                if lbl_text:
                    lbl_rect = pymupdf.Rect(bx + 2 * bw + 6, y_mid - 11, bx + 2 * bw + 180, y_mid + 11)
                    page.draw_rect(lbl_rect, color=(0.25, 0.45, 0.75), fill=(0.92, 0.96, 1.0), radius=0.2, width=1.0)
                    page.insert_textbox(
                        pymupdf.Rect(lbl_rect.x0 + 4, lbl_rect.y0 + 2, lbl_rect.x1 - 4, lbl_rect.y1 - 2),
                        lbl_text,
                        fontsize=8.5,
                        fontname="helv",
                        color=(0.10, 0.20, 0.45)
                    )

            # 4. Sellos y Marcadores Rápidos (Stamps)
            for st in pdata.get("stamps", []):
                sx = float(st.get("x", 40))
                sy = float(st.get("y", 100))
                symbol_raw = st.get("symbol", "⚠️")
                sym_clean = clean_pdf_text(symbol_raw)
                stamp_rect = pymupdf.Rect(sx, sy, sx + 28, sy + 22)
                page.draw_rect(stamp_rect, color=(0.85, 0.50, 0.15), fill=(1.0, 0.97, 0.92), radius=0.25, width=1.0)
                page.insert_textbox(stamp_rect, sym_clean, fontsize=7.5, fontname="helv", color=(0.8, 0.3, 0.1))

            # 5. Notas en el margen (Margin Notes)
            for note in pdata.get("annotations", []):
                raw_x = float(note.get("x", 0))
                if raw_x < ancho_orig:
                    x = ancho_orig + float(note.get("rel_x", 15))
                else:
                    x = raw_x
                y = float(note.get("y", 60))
                w = float(note.get("width", 260))
                h = float(note.get("height", 65))
                box_rect = pymupdf.Rect(x, y, x + w, y + h)

                ntype = note.get("type", "warning")
                if ntype == "info":
                    color_bg = (0.94, 0.97, 1.0)
                    color_stroke = (0.23, 0.51, 0.96)
                    prefix = "[NOTA] "
                elif ntype == "tip":
                    color_bg = (0.94, 0.99, 0.96)
                    color_stroke = (0.06, 0.72, 0.51)
                    prefix = "[CLAVE] "
                elif ntype == "exam":
                    color_bg = (1.0, 0.93, 0.94)
                    color_stroke = (0.94, 0.27, 0.27)
                    prefix = "[EXAMEN] "
                else:
                    color_bg = (1.0, 0.98, 0.92)
                    color_stroke = (0.96, 0.62, 0.04)
                    prefix = "[ATENCIÓN] "

                page.draw_rect(box_rect, color=color_stroke, fill=color_bg, width=1.1, radius=0.08)

                text_rect = pymupdf.Rect(x + 8, y + 6, x + w - 8, y + h - 6)
                note_body = clean_pdf_text(note.get("text", ""))
                full_text = f"{prefix}\n{note_body}"
                page.insert_textbox(text_rect, full_text, fontsize=8.5, fontname="helv", color=(0.15, 0.20, 0.25))

            # 6. Esquemas vectoriales (Dagre layouts procesados o fallback automático)
            for schema in pdata.get("schemas", []):
                layout_nodes = schema.get("layout_nodes", [])
                layout_edges = schema.get("layout_edges", [])

                # Fallback de distribución vertical si no se procesó aún en frontend
                if not layout_nodes and schema.get("nodes"):
                    layout_nodes = []
                    anchor_y = 60.0
                    for idx, n in enumerate(schema.get("nodes", [])):
                        layout_nodes.append({
                            "id": n.get("id"),
                            "label": n.get("label"),
                            "details": n.get("details", []),
                            "isRoot": (idx == 0),
                            "x": ancho_orig + 20,
                            "y": anchor_y + (idx * 60),
                            "width": 180,
                            "height": 45
                        })

                # Nodos
                for node in layout_nodes:
                    raw_nx = float(node.get("x", 0))
                    nx = raw_nx if raw_nx >= ancho_orig else (ancho_orig + raw_nx)
                    ny = float(node.get("y", 50))
                    nw = float(node.get("width", 140))
                    nh = float(node.get("height", 45))
                    nrect = pymupdf.Rect(nx, ny, nx + nw, ny + nh)

                    is_root = node.get("isRoot", False)
                    if is_root:
                        page.draw_rect(nrect, color=(0.11, 0.23, 0.54), fill=(0.15, 0.30, 0.65), width=1.5, radius=0.08)
                        tcolor = (1.0, 1.0, 1.0)
                    else:
                        page.draw_rect(nrect, color=(0.23, 0.51, 0.96), fill=(0.96, 0.98, 1.0), width=1.2, radius=0.08)
                        tcolor = (0.06, 0.10, 0.20)

                    label_str = clean_pdf_text(node.get("label", ""))
                    details = node.get("details", [])
                    details_str = "\n".join([f"- {clean_pdf_text(str(d))}" for d in details]) if details else ""
                    node_text = f"{label_str}\n{details_str}".strip()

                    trect = pymupdf.Rect(nx + 6, ny + 5, nx + nw - 6, ny + nh - 5)
                    page.insert_textbox(trect, node_text, fontsize=8.0, fontname="helv", color=tcolor)

                # Aristas / Conexiones Bézier
                for edge in layout_edges:
                    points = edge.get("points", [])
                    if len(points) >= 2:
                        raw_x0 = points[0]["x"]
                        x_offset = 0 if raw_x0 >= ancho_orig else ancho_orig

                        p_start = pymupdf.Point(raw_x0 + x_offset, points[0]["y"])
                        p_end = pymupdf.Point(points[-1]["x"] + x_offset, points[-1]["y"])

                        if len(points) >= 4:
                            p_c1 = pymupdf.Point(points[1]["x"] + x_offset, points[1]["y"])
                            p_c2 = pymupdf.Point(points[2]["x"] + x_offset, points[2]["y"])
                            page.draw_bezier(p_start, p_c1, p_c2, p_end, color=(0.30, 0.40, 0.55), width=1.3)
                        else:
                            page.draw_line(p_start, p_end, color=(0.30, 0.40, 0.55), width=1.3)

        doc.save(str(output_path))
        doc.close()
        logger.info(f"PDF exportado vectorialmente en: {output_path.name}")
        return {
            "status": "ok",
            "download_url": f"/api/pdf/{output_filename}",
            "filename": output_filename
        }
    except Exception as e:
        logger.error(f"Error al compilar PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al compilar el PDF: {str(e)}")


# Montar archivos estáticos
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8766))
    print(f"\n🚀 Iniciando Visor de Apuntes en http://127.0.0.1:{port}")
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=True, reload_dirs=[str(BASE_DIR)])
