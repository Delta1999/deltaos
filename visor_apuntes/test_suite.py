"""Suite de Pruebas Automatizadas para el Visor y Editor de Apuntes Manos Libres.

Verifica:
1. Endpoints HTTP de API y archivos estáticos.
2. Esquemas JSON de Function Calling para el agente de voz.
3. Canal WebSocket bidireccional (emisión de contexto y recepción de comandos).
4. Persistencia en archivo sidecar JSON (.notes.json).
5. Compilación y exportación vectorial permanente con PyMuPDF.
"""

import asyncio
import json
import urllib.request
import urllib.error
import pymupdf
import websockets

BASE_URL = "http://127.0.0.1:8766"
WS_URL = "ws://127.0.0.1:8766/ws/commands"


def test_index_and_static_served():
    """Comprueba que el visor web y sus assets estáticos se sirven correctamente."""
    with urllib.request.urlopen(f"{BASE_URL}/") as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert "Visor Apuntes AI" in html
        assert "pdf-container" in html

    with urllib.request.urlopen(f"{BASE_URL}/static/app.js") as resp:
        assert resp.status == 200
        js = resp.read().decode("utf-8")
        assert "executeVoiceCommand" in js
        assert "renderSchemaTree" in js

    with urllib.request.urlopen(f"{BASE_URL}/static/style.css") as resp:
        assert resp.status == 200
        css = resp.read().decode("utf-8")
        assert "active-recall-enabled" in css


def test_api_documents_and_tools():
    """Valida la lista de documentos y los esquemas Function Calling."""
    with urllib.request.urlopen(f"{BASE_URL}/api/documents") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "documents" in data
        assert "sample.pdf" in data["documents"]

    with urllib.request.urlopen(f"{BASE_URL}/api/tools") as resp:
        assert resp.status == 200
        tools = json.loads(resp.read().decode("utf-8"))
        tool_names = [t["name"] for t in tools]
        expected_tools = [
            "activate_grid",
            "highlight_passage",
            "create_schema",
            "add_schema_branch",
            "add_margin_note",
            "add_bracket_group",
            "add_stamp_symbol",
            "undo_last_action",
            "toggle_active_recall"
        ]
        for t in expected_tools:
            assert t in tool_names, f"Falta la herramienta {t} en el esquema"


def test_notes_sidecar_roundtrip():
    """Comprueba la lectura y persistencia en el archivo sidecar JSON sin tocar el original."""
    with urllib.request.urlopen(f"{BASE_URL}/api/notes/sample.pdf") as resp:
        assert resp.status == 200
        notes = json.loads(resp.read().decode("utf-8"))
        assert "pages" in notes

    # Guardar una anotación de prueba
    test_payload = json.dumps(notes).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/notes/sample.pdf",
        data=test_payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert res.get("status") == "ok"


def test_export_pdf_compilation():
    """Comprueba que PyMuPDF compila el PDF ampliando el MediaBox e insertando los gráficos vectoriales."""
    req = urllib.request.Request(f"{BASE_URL}/api/export/sample.pdf", data=b"", method="POST")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data.get("status") == "ok"
        assert "download_url" in data

    # Inspeccionar el PDF compilado
    doc = pymupdf.open("/home/jloslop/gemini-live-assistant/visor_apuntes/storage/sample_anotado.pdf")
    assert len(doc) >= 1
    page1 = doc[0]

    # Verificar que el ancho del MediaBox fue ampliado para el margen
    assert page1.mediabox.width > 595.0
    assert page1.cropbox.width > 595.0

    # Verificar que contiene texto en el margen extendido
    margin_text = page1.get_text("text", clip=pymupdf.Rect(595, 0, page1.mediabox.width, page1.mediabox.height))
    assert "MARGEN EXTENDIDO" in margin_text
    assert "Fases" in margin_text
    doc.close()


def test_commands_and_websocket():
    """Valida el canal WebSocket bidireccional y el contexto del cursor."""
    async def run_ws():
        async with websockets.connect(WS_URL) as ws:
            # 1. Enviar contexto de ratón simulado
            ctx_msg = {
                "type": "mouse_context",
                "page": 1,
                "nearest_cell": "C3",
                "mouse_pos": [195, 130],
                "nearest_text": "procedimiento administrativo",
                "timestamp": 123456789
            }
            await ws.send(json.dumps(ctx_msg))
            await asyncio.sleep(0.1)

            # Verificar que el backend actualizó el contexto
            with urllib.request.urlopen(f"{BASE_URL}/api/context") as resp:
                ctx = json.loads(resp.read().decode("utf-8"))
                assert ctx["nearest_cell"] == "C3"
                assert ctx["nearest_text"] == "procedimiento administrativo"

            # 2. Emitir comando de voz vía HTTP y recibirlo por WS
            cmd_payload = json.dumps({
                "command": "highlight_passage",
                "args": {"target_text": "iniciarse de oficio", "color": "#fef08a"}
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{BASE_URL}/api/commands",
                data=cmd_payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 200

            # Recibir evento por WebSocket
            msg_raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            msg = json.loads(msg_raw)
            assert msg.get("type") == "voice_command"
            assert msg.get("command") == "highlight_passage"
            assert msg["args"]["target_text"] == "iniciarse de oficio"

    asyncio.run(run_ws())


if __name__ == "__main__":
    print("\n🔍 Ejecutando suite de pruebas automatizadas...")
    test_index_and_static_served()
    print("  ✓ Servidor web y assets estáticos: OK")
    test_api_documents_and_tools()
    print("  ✓ API de documentos y esquemas Function Calling: OK")
    test_notes_sidecar_roundtrip()
    print("  ✓ Persistencia sidecar JSON: OK")
    test_export_pdf_compilation()
    print("  ✓ Compilación vectorial PyMuPDF: OK")
    test_commands_and_websocket()
    print("  ✓ WebSocket bidireccional y contexto espacial: OK")
    print("\n🎉 ¡TODAS LAS PRUEBAS PASARON EXITOSAMENTE!\n")
