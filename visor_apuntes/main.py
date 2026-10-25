"""PDF Voice Studio - Servidor FastAPI para Visor y Editor de Apuntes Manos Libres.

Gestiona:
- Servicio de visor PDF y estáticos del frontend interactivo (PDF.js, SVG overlay, Dagre.js).
- Persistencia no destructiva con archivos sidecar JSON (.notes.json).
- Canal WebSocket bidireccional (/ws/commands) para comandos de voz y contexto del ratón.
- Compilación y exportación vectorial nativa con PyMuPDF con doble margen extendido.
- Exposición de esquemas de herramientas Function Calling para agentes de IA (Gemini Live/Multimodal).
- Compatible con ejecución como script Python o como binario independiente compilado con PyInstaller.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymupdf
from fastapi import FastAPI, File, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pdf_voice_studio")


def get_bundle_dir() -> Path:
    """Devuelve el directorio base de recursos (soporta PyInstaller _MEIPASS)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.resolve()


def get_storage_dir() -> Path:
    """Devuelve el directorio de almacenamiento persistente."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent.resolve()
        try:
            test_file = exe_dir / ".test_perm"
            test_file.touch()
            test_file.unlink()
            target = exe_dir / "storage"
        except Exception:
            target = Path.home() / ".pdf-voice-studio" / "storage"
    else:
        target = Path(__file__).parent.resolve() / "storage"
    target.mkdir(parents=True, exist_ok=True)
    return target


BUNDLE_DIR = get_bundle_dir()
STATIC_DIR = BUNDLE_DIR / "static"
STORAGE_DIR = get_storage_dir()
STATIC_DIR.mkdir(parents=True, exist_ok=True)

MARGIN_LEFT_PT = 220.0   # Puntos añadidos a la izquierda del PDF (sellos, marcas, llaves)
MARGIN_RIGHT_PT = 380.0  # Puntos añadidos a la derecha del PDF para el margen extendido (notas, esquemas)

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


def ensure_sample_pdf(doc_id: str = "sample.pdf") -> Path:
    safe_doc_id = sanitize_doc_id(doc_id)
    pdf_path = STORAGE_DIR / safe_doc_id
    if pdf_path.exists():
        return pdf_path

    # Si hay un PDF en BUNDLE_DIR, copiarlo
    bundled_sample = BUNDLE_DIR / safe_doc_id
    if bundled_sample.exists():
        pdf_path.write_bytes(bundled_sample.read_bytes())
        base_name = safe_doc_id[:-4] if safe_doc_id.lower().endswith(".pdf") else safe_doc_id
        notes_src = BUNDLE_DIR / f"{base_name}.notes.json"
        notes_dst = _notes_path(safe_doc_id)
        if notes_src.exists() and not notes_dst.exists():
            notes_dst.write_bytes(notes_src.read_bytes())
        return pdf_path

    # Generador de respaldo de PDF
    doc = pymupdf.open()
    page = doc.new_page(width=595.0, height=842.0)
    page.draw_rect(pymupdf.Rect(40, 35, 555, 75), color=(0.12, 0.23, 0.54), fill=(0.94, 0.96, 1.0), width=1.2)
    page.insert_text(pymupdf.Point(55, 60), "TEMA 14: EL PROCEDIMIENTO ADMINISTRATIVO COMÚN (LEY 39/2015)", fontsize=12, fontname="helv")
    blocks = [
        (45, 110, 11, "Artículo 112. Objeto y clases de recursos administrativos."),
        (45, 130, 10, "1. Contra las resoluciones y los actos de trámite, si estos últimos deciden directa o indirectamente\nel fondo del asunto, determinan la imposibilidad de continuar el procedimiento, producen indefensión\no perjuicio irreparable a derechos e intereses legítimos, podrán interponerse por los interesados los\nrecursos de alzada y potestativo de reposición, que cabrá fundar en cualquiera de los motivos de\nnulidad o anulabilidad previstos en los artículos 47 y 48 de esta Ley."),
        (45, 215, 11, "Artículo 121. Objeto y plazos del Recurso de Alzada."),
        (45, 235, 10, "1. Las resoluciones y actos a que se refiere el artículo 112.1, cuando no pongan fin a la vía\nadministrativa, podrán ser recurridos en alzada ante el órgano superior jerárquico del que los dictó."),
        (45, 305, 10, "2. El plazo para la interposición del recurso de alzada será de un mes, si el acto fuera expreso.\nTranscurrido dicho plazo sin haberse interpuesto el recurso, la resolución será firme a todos los\nefectos."),
        (45, 395, 10, "3. El plazo máximo para dictar y notificar la resolución será de tres meses. Transcurrido este plazo\nsin que recaiga resolución, se podrá entender desestimado el recurso, salvo en el supuesto previsto\nen el artículo 24.1."),
        (45, 465, 11, "Artículo 123. Objeto y naturaleza del Recurso Potestativo de Reposición."),
        (45, 485, 10, "1. Los actos administrativos que pongan fin a la vía administrativa podrán ser recurridos\npotestativamente en reposición ante el mismo órgano que los hubiera dictado."),
        (45, 595, 11, "Artículo 124. Plazos del Recurso de Reposición."),
        (45, 615, 10, "1. El plazo para la interposición del recurso de reposición será de un mes, si el acto fuera expreso.\n2. El plazo máximo para dictar y notificar la resolución del recurso será de un mes.")
    ]
    for x, y, size, text in blocks:
        page.insert_text(pymupdf.Point(x, y), text, fontsize=size, fontname="helv", color=(0.1, 0.1, 0.15))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def sanitize_doc_id(doc_id: str) -> str:
    """Valida un identificador que debe ser un nombre de archivo plano."""
    if not isinstance(doc_id, str) or not doc_id:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
    if "\x00" in doc_id or "/" in doc_id or "\\" in doc_id:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
    safe_name = Path(doc_id).name
    if safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
    return safe_name


def _pdf_path(doc_id: str) -> Path:
    safe_name = sanitize_doc_id(doc_id)
    return STORAGE_DIR / safe_name


def _notes_path(doc_id: str) -> Path:
    safe_name = sanitize_doc_id(doc_id)
    base_name = safe_name[:-4] if safe_name.lower().endswith(".pdf") else safe_name
    return STORAGE_DIR / f"{base_name}.notes.json"


app = FastAPI(title="PDF Voice Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8766",
        "http://localhost:8766",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.latest_mouse_context: Dict[str, Any] = {
            "page": 1,
            "nearest_cell": "A1",
            "mouse_pos": [0, 0],
            "nearest_text": "",
            "doc_id": "sample.pdf",
            "timestamp": 0,
        }

    def is_active(self) -> bool:
        import time
        if len(self.active_connections) > 0:
            return True
        ts = self.latest_mouse_context.get("timestamp", 0)
        ts_sec = ts / 1000.0 if ts > 1e11 else ts
        return (time.time() - ts_sec) < 120.0

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


class CommandPayload(BaseModel):
    command: str
    args: Dict[str, Any] = {}


@app.on_event("startup")
async def startup_event():
    ensure_sample_pdf("sample.pdf")
    logger.info(f"PDF Voice Studio inicializado. Almacenamiento en: {STORAGE_DIR}")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html no encontrado en static/")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


@app.get("/api/documents")
async def list_documents():
    ensure_sample_pdf("sample.pdf")
    files = sorted([f.name for f in STORAGE_DIR.glob("*.pdf") if not f.name.endswith("_anotado.pdf")])
    return {"documents": files}


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    raw_name = file.filename or ""
    if not raw_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos en formato PDF.")

    safe_filename = Path(raw_name).name
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo PDF no válido.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo PDF subido está vacío.")

    try:
        test_doc = pymupdf.open(stream=content, filetype="pdf")
        if len(test_doc) == 0:
            test_doc.close()
            raise HTTPException(status_code=400, detail="El archivo PDF no contiene páginas legibles.")
        test_doc.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"El archivo no es un PDF válido o está dañado: {e}")

    target_path = STORAGE_DIR / safe_filename
    with open(target_path, "wb") as buffer:
        buffer.write(content)

    notes_file = _notes_path(safe_filename)
    if not notes_file.exists():
        initial_notes = {"document_id": safe_filename, "version": 1, "pages": {}}
        notes_file.write_text(json.dumps(initial_notes, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"status": "uploaded", "filename": safe_filename}


@app.get("/api/pdf/{doc_id}")
async def get_pdf(doc_id: str):
    pdf_path = _pdf_path(doc_id)
    if not pdf_path.exists():
        pdf_path = ensure_sample_pdf(doc_id)
    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail=f"PDF '{doc_id}' no encontrado.")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/api/notes/{doc_id}")
async def get_notes(doc_id: str):
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
    path = _notes_path(doc_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
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
    return manager.latest_mouse_context


@app.get("/api/status")
async def get_status():
    return {
        "active": manager.is_active(),
        "connections": len(manager.active_connections),
        "context": manager.latest_mouse_context
    }


@app.get("/api/page_text/{doc_id}/{page_num}")
async def get_page_text(doc_id: str, page_num: int):
    actual_doc = doc_id
    if actual_doc in ("", "current", "actual", "default"):
        actual_doc = manager.latest_mouse_context.get("doc_id", "sample.pdf")

    safe_doc = sanitize_doc_id(actual_doc)
    pdf_path = STORAGE_DIR / safe_doc
    if not pdf_path.exists():
        matches = [path for path in STORAGE_DIR.glob("*.pdf") if safe_doc in path.name]
        if matches:
            pdf_path = matches[0]
            safe_doc = pdf_path.name
        else:
            raise HTTPException(status_code=404, detail=f"Documento '{safe_doc}' no encontrado.")

    try:
        doc = pymupdf.open(str(pdf_path))
        if page_num < 1 or page_num > len(doc):
            doc.close()
            raise HTTPException(status_code=400, detail=f"Página {page_num} fuera de rango (1-{len(doc)}).")
        page = doc[page_num - 1]
        text = page.get_text("text").strip()
        doc.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error extrayendo texto del PDF: {e}")

    notes_path = _notes_path(safe_doc)
    page_notes = {}
    if notes_path.exists():
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                all_notes = json.load(f)
                page_notes = all_notes.get("pages", {}).get(str(page_num), {})
        except Exception as e:
            logger.warning(f"Error cargando notas de {actual_doc}: {e}")

    return {
        "doc_id": safe_doc,
        "page": page_num,
        "text": text,
        "notes": page_notes
    }


@app.get("/api/render/{doc_id}/{page_num}")
async def render_page_image(doc_id: str, page_num: int, dpi: int = 150):
    actual_doc = doc_id
    if actual_doc in ("", "current", "actual", "default"):
        actual_doc = manager.latest_mouse_context.get("doc_id", "sample.pdf")

    pdf_path = _pdf_path(actual_doc)
    if not pdf_path.exists():
        safe_actual_doc = sanitize_doc_id(actual_doc)
        matches = [path for path in STORAGE_DIR.glob("*.pdf") if safe_actual_doc in path.name]
        if matches:
            pdf_path = matches[0]
            actual_doc = pdf_path.name
        else:
            raise HTTPException(status_code=404, detail=f"Documento '{actual_doc}' no encontrado.")

    try:
        doc = pymupdf.open(str(pdf_path))
        if page_num < 1 or page_num > len(doc):
            doc.close()
            raise HTTPException(status_code=400, detail=f"Página {page_num} fuera de rango (1-{len(doc)}).")
        page = doc[page_num - 1]
        target_dpi = max(72, min(300, dpi))
        pix = page.get_pixmap(dpi=target_dpi)
        img_bytes = pix.tobytes("jpeg")
        doc.close()
        return Response(content=img_bytes, media_type="image/jpeg")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error renderizando página: {e}")


@app.get("/api/tools")
async def get_tools_schema():
    for candidate in [BUNDLE_DIR / "tools_schema.json", BUNDLE_DIR / "function_calling_schemas.json"]:
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                pass
    return []


@app.post("/api/commands")
async def emit_command(cmd: Dict[str, Any]):
    command_name = cmd.get("command") or cmd.get("action")
    args = cmd.get("args") if "args" in cmd else cmd
    logger.info(f"Comando recibido por HTTP: {command_name} | Args: {args}")
    msg = {
        "type": "voice_command",
        "command": command_name,
        "args": args
    }
    await manager.broadcast(msg)
    return {"status": "dispatched", "command": command_name}


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
                elif msg_type == "tool_call":
                    await manager.broadcast({
                        "type": "voice_command",
                        "command": data.get("tool_name"),
                        "args": data.get("parameters", {}),
                        "cursor_context": manager.latest_mouse_context
                    })
                elif "action" in data:
                    await manager.broadcast({
                        "type": "voice_command",
                        "command": data.get("action"),
                        "args": data,
                        "cursor_context": manager.latest_mouse_context
                    })
                elif msg_type == "save_notes":
                    doc_id = data.get("document_id")
                    notes_content = data.get("notes")
                    if doc_id and notes_content:
                        safe_doc_id = sanitize_doc_id(doc_id)
                        path = _notes_path(safe_doc_id)
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(notes_content, f, ensure_ascii=False, indent=2)
                        await manager.broadcast({
                            "type": "notes_saved",
                            "document_id": safe_doc_id
                        })
            except json.JSONDecodeError:
                logger.warning(f"Mensaje JSON no válido por WS: {raw_data[:80]}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Excepción en WebSocket: {e}")
        manager.disconnect(websocket)


@app.post("/api/export/{doc_id}")
async def export_pdf(doc_id: str):
    pdf_path = _pdf_path(doc_id)
    if not pdf_path.exists():
        pdf_path = ensure_sample_pdf(doc_id)
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
        src_doc = pymupdf.open(str(pdf_path))
        new_doc = pymupdf.open()
        pages_notes = notes_data.get("pages", {})

        for page_idx in range(len(src_doc)):
            page_key = str(page_idx + 1)
            pdata = pages_notes.get(page_key, {})
            src_page = src_doc[page_idx]

            orig_w = src_page.rect.width
            orig_h = src_page.rect.height
            total_w = orig_w + MARGIN_LEFT_PT + MARGIN_RIGHT_PT
            right_margin_x = MARGIN_LEFT_PT + orig_w

            new_page = new_doc.new_page(width=total_w, height=orig_h)
            target_rect = pymupdf.Rect(MARGIN_LEFT_PT, 0, right_margin_x, orig_h)
            new_page.show_pdf_page(target_rect, src_doc, page_idx)

            new_page.draw_line(
                pymupdf.Point(MARGIN_LEFT_PT, 0),
                pymupdf.Point(MARGIN_LEFT_PT, orig_h),
                color=(0.80, 0.83, 0.88),
                width=0.75,
                dashes="[3 3] 0"
            )
            new_page.insert_textbox(
                pymupdf.Rect(10, 10, MARGIN_LEFT_PT - 10, 24),
                "MARGEN IZQUIERDO (NOTAS / SELLOS)",
                fontsize=7.0,
                fontname="helv",
                color=(0.60, 0.65, 0.72)
            )

            new_page.draw_line(
                pymupdf.Point(right_margin_x, 0),
                pymupdf.Point(right_margin_x, orig_h),
                color=(0.80, 0.83, 0.88),
                width=0.75,
                dashes="[3 3] 0"
            )
            new_page.insert_textbox(
                pymupdf.Rect(right_margin_x + 10, 10, right_margin_x + 220, 24),
                "MARGEN EXTENDIDO (ESTUDIO)",
                fontsize=7.5,
                fontname="helv",
                color=(0.60, 0.65, 0.72)
            )

            for hl in pdata.get("highlights", []):
                hex_color = hl.get("color", "#fef08a").lstrip("#")
                if len(hex_color) == 6:
                    r, g, b = (int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
                else:
                    r, g, b = (1.0, 0.94, 0.3)

                style = hl.get("style", "solid_highlight")
                for r_box in hl.get("rects", []):
                    if len(r_box) >= 4:
                        rect = pymupdf.Rect(r_box[0], r_box[1], r_box[2], r_box[3])
                        if style == "underline":
                            p_start = pymupdf.Point(rect.x0, rect.y1 + 1)
                            p_end = pymupdf.Point(rect.x1, rect.y1 + 1)
                            new_page.draw_line(p_start, p_end, color=(r, g, b), width=1.8)
                        elif style == "strikethrough":
                            mid_y = (rect.y0 + rect.y1) / 2.0
                            p_start = pymupdf.Point(rect.x0, mid_y)
                            p_end = pymupdf.Point(rect.x1, mid_y)
                            new_page.draw_line(p_start, p_end, color=(r, g, b), width=1.6)
                        elif style in ("box", "rounded_box"):
                            new_page.draw_rect(rect, color=(r, g, b), width=1.4, radius=0.15)
                        else:
                            annot = new_page.add_highlight_annot(quads=[rect.quad])
                            annot.set_colors(stroke=(r, g, b))
                            annot.set_info(content=clean_pdf_text(hl.get("text", "")), title="PDF Voice Studio")
                            annot.update()

            for br in pdata.get("brackets", []):
                y_start = float(br.get("y_start", 100))
                y_end = float(br.get("y_end", 250))
                y_mid = (y_start + y_end) / 2
                bx = float(br.get("x", right_margin_x - 12))
                bw = 10.0
                r_arc = 8.0

                if br.get("bracket_type") == "bar":
                    new_page.draw_line(pymupdf.Point(bx + bw, y_start), pymupdf.Point(bx + bw, y_end), color=(0.15, 0.40, 0.85), width=2.5)
                else:
                    new_page.draw_bezier(
                        pymupdf.Point(bx, y_start),
                        pymupdf.Point(bx + bw, y_start),
                        pymupdf.Point(bx + bw, y_start),
                        pymupdf.Point(bx + bw, y_start + r_arc),
                        color=(0.25, 0.45, 0.75), width=1.4
                    )
                    new_page.draw_line(
                        pymupdf.Point(bx + bw, y_start + r_arc),
                        pymupdf.Point(bx + bw, y_mid - r_arc),
                        color=(0.25, 0.45, 0.75), width=1.4
                    )
                    new_page.draw_bezier(
                        pymupdf.Point(bx + bw, y_mid - r_arc),
                        pymupdf.Point(bx + bw, y_mid),
                        pymupdf.Point(bx + 2 * bw, y_mid),
                        pymupdf.Point(bx + 2 * bw, y_mid),
                        color=(0.25, 0.45, 0.75), width=1.4
                    )
                    new_page.draw_bezier(
                        pymupdf.Point(bx + 2 * bw, y_mid),
                        pymupdf.Point(bx + 2 * bw, y_mid),
                        pymupdf.Point(bx + bw, y_mid),
                        pymupdf.Point(bx + bw, y_mid + r_arc),
                        color=(0.25, 0.45, 0.75), width=1.4
                    )
                    new_page.draw_line(
                        pymupdf.Point(bx + bw, y_mid + r_arc),
                        pymupdf.Point(bx + bw, y_end - r_arc),
                        color=(0.25, 0.45, 0.75), width=1.4
                    )
                    new_page.draw_bezier(
                        pymupdf.Point(bx + bw, y_end - r_arc),
                        pymupdf.Point(bx + bw, y_end),
                        pymupdf.Point(bx, y_end),
                        pymupdf.Point(bx, y_end),
                        color=(0.25, 0.45, 0.75), width=1.4
                    )

                lbl_text = clean_pdf_text(br.get("label", ""))
                if lbl_text:
                    lbl_rect = pymupdf.Rect(bx + 2 * bw + 6, y_mid - 11, bx + 2 * bw + 180, y_mid + 11)
                    new_page.draw_rect(lbl_rect, color=(0.25, 0.45, 0.75), fill=(0.92, 0.96, 1.0), radius=0.2, width=1.0)
                    new_page.insert_textbox(
                        pymupdf.Rect(lbl_rect.x0 + 4, lbl_rect.y0 + 2, lbl_rect.x1 - 4, lbl_rect.y1 - 2),
                        lbl_text,
                        fontsize=8.5,
                        fontname="helv",
                        color=(0.10, 0.20, 0.45)
                    )

            for st in pdata.get("stamps", []):
                sx = float(st.get("x", 40))
                sy = float(st.get("y", 100))
                sym_clean = clean_pdf_text(st.get("symbol", "⚠️"))
                stamp_rect = pymupdf.Rect(sx, sy, sx + 28, sy + 22)
                new_page.draw_rect(stamp_rect, color=(0.85, 0.50, 0.15), fill=(1.0, 0.97, 0.92), radius=0.25, width=1.0)
                new_page.insert_textbox(stamp_rect, sym_clean, fontsize=7.5, fontname="helv", color=(0.8, 0.3, 0.1))

            for note in pdata.get("annotations", []):
                raw_x = float(note.get("x", 0))
                if raw_x < right_margin_x and raw_x > MARGIN_LEFT_PT:
                    x = right_margin_x + float(note.get("rel_x", 15))
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

                if note.get("connector_to"):
                    c = note["connector_to"]
                    c_x = float(c.get("x", 0))
                    c_y = float(c.get("y", 0))
                    if c_x > 0 and c_y > 0:
                        start_pt = pymupdf.Point(box_rect.x0 if box_rect.x0 >= right_margin_x else box_rect.x1, box_rect.y0 + 20)
                        end_pt = pymupdf.Point(c_x, c_y)
                        new_page.draw_line(start_pt, end_pt, color=color_stroke, width=1.0, dashes="[2 2] 0")
                        new_page.draw_circle(end_pt, 2.5, color=color_stroke, fill=color_stroke)

                new_page.draw_rect(box_rect, color=color_stroke, fill=color_bg, width=1.1, radius=0.08)
                text_rect = pymupdf.Rect(x + 8, y + 6, x + w - 8, y + h - 6)
                note_body = clean_pdf_text(note.get("text", ""))
                full_text = f"{prefix}\n{note_body}"
                new_page.insert_textbox(text_rect, full_text, fontsize=8.5, fontname="helv", color=(0.15, 0.20, 0.25))

            for schema in pdata.get("schemas", []):
                layout_nodes = schema.get("layout_nodes", [])
                layout_edges = schema.get("layout_edges", [])

                if not layout_nodes and schema.get("nodes"):
                    layout_nodes = []
                    anchor_y = float(schema.get("anchor_y", 60.0))
                    is_left = schema.get("side") == "left"
                    schema_x = 15.0 if is_left else (right_margin_x + 20.0)
                    for idx, n in enumerate(schema.get("nodes", [])):
                        layout_nodes.append({
                            "id": n.get("id"),
                            "label": n.get("label"),
                            "details": n.get("details", []),
                            "isRoot": (idx == 0),
                            "x": schema_x,
                            "y": anchor_y + (idx * 60),
                            "width": 180,
                            "height": 45
                        })

                for node in layout_nodes:
                    raw_nx = float(node.get("x", 0))
                    nx = raw_nx if (raw_nx >= right_margin_x or raw_nx < MARGIN_LEFT_PT) else (right_margin_x + 15)
                    ny = float(node.get("y", 50))
                    nw = float(node.get("width", 140))
                    nh = float(node.get("height", 45))
                    nrect = pymupdf.Rect(nx, ny, nx + nw, ny + nh)

                    is_root = node.get("isRoot", False)
                    if is_root:
                        new_page.draw_rect(nrect, color=(0.11, 0.23, 0.54), fill=(0.15, 0.30, 0.65), width=1.5, radius=0.08)
                        tcolor = (1.0, 1.0, 1.0)
                    else:
                        new_page.draw_rect(nrect, color=(0.23, 0.51, 0.96), fill=(0.96, 0.98, 1.0), width=1.2, radius=0.08)
                        tcolor = (0.06, 0.10, 0.20)

                    label_str = clean_pdf_text(node.get("label", ""))
                    details = node.get("details", [])
                    details_str = "\n".join([f"- {clean_pdf_text(str(d))}" for d in details]) if details else ""
                    node_text = f"{label_str}\n{details_str}".strip()

                    trect = pymupdf.Rect(nx + 6, ny + 5, nx + nw - 6, ny + nh - 5)
                    new_page.insert_textbox(trect, node_text, fontsize=8.0, fontname="helv", color=tcolor)

                for edge in layout_edges:
                    points = edge.get("points", [])
                    if len(points) >= 2:
                        raw_x0 = points[0]["x"]
                        x_offset = 0 if (raw_x0 >= right_margin_x or raw_x0 < MARGIN_LEFT_PT) else right_margin_x

                        p_start = pymupdf.Point(raw_x0 + x_offset, points[0]["y"])
                        p_end = pymupdf.Point(points[-1]["x"] + x_offset, points[-1]["y"])

                        if len(points) >= 4:
                            p_c1 = pymupdf.Point(points[1]["x"] + x_offset, points[1]["y"])
                            p_c2 = pymupdf.Point(points[2]["x"] + x_offset, points[2]["y"])
                            new_page.draw_bezier(p_start, p_c1, p_c2, p_end, color=(0.30, 0.40, 0.55), width=1.3)
                        else:
                            new_page.draw_line(p_start, p_end, color=(0.30, 0.40, 0.55), width=1.3)

        new_doc.save(str(output_path), garbage=4, deflate=True)
        new_doc.close()
        src_doc.close()
        logger.info(f"PDF exportado vectorialmente en: {output_path.name}")
        return {
            "status": "ok",
            "download_url": f"/api/pdf/{output_filename}",
            "filename": output_filename
        }
    except Exception as e:
        logger.error(f"Error al compilar PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al compilar el PDF: {str(e)}")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8766))
    host = os.environ.get("HOST", "127.0.0.1")
    url = f"http://{host}:{port}"

    print(f"\n=======================================================")
    print(f"🚀 PDF Voice Studio activo en: {url}")
    print(f"📂 Carpeta de documentos: {STORAGE_DIR}")
    print(f"=======================================================\n")

    if os.environ.get("NO_BROWSER") != "1":
        def _open():
            import time
            time.sleep(1.0)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")

# [Claude-Cherry] Corregir vulnerabilidad de path traversal en visor_apuntes/main.py (2026-10-24)
