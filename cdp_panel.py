#!/usr/bin/env python3
"""Inspector CDP en vivo del panel de DeltaOS (http://127.0.0.1:9222).

Uso:
  .venv/bin/python cdp_panel.py --status      # Estado del DOM, errores JS, WebSocket y FPS
  .venv/bin/python cdp_panel.py --eval "JS"   # Evalúa una expresión JS en el panel en vivo
  .venv/bin/python cdp_panel.py --agentes     # Abre la pantalla completa de Agentes
"""
import argparse
import asyncio
import json
import sys
import urllib.request
import websockets

CDP_URL = "http://127.0.0.1:9222/json/list"


def obtener_ws_panel():
    try:
        with urllib.request.urlopen(CDP_URL, timeout=3) as r:
            paginas = json.loads(r.read().decode())
    except Exception as e:
        raise RuntimeError(f"No responde CDP en :9222 ({e})")
    for p in paginas:
        if "127.0.0.1:7876" in p.get("url", "") and p.get("type") == "page":
            return p["webSocketDebuggerUrl"], p.get("title", ""), p.get("url", "")
    raise RuntimeError("No hay ninguna pestaña de http://127.0.0.1:7876 abierta en Chromium")


async def evaluar(expr: str):
    ws_url, _, _ = obtener_ws_panel()
    async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}
        }))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                res = msg.get("result", {})
                if "exceptionDetails" in res:
                    raise RuntimeError(f"Excepción JS: {res['exceptionDetails']}")
                return res.get("result", {}).get("value")


async def estado_panel():
    js = """
    (() => {
      const ov = document.getElementById('panel-error-overlay');
      const errVisible = ov && getComputedStyle(ov).display !== 'none';
      return {
        titulo: document.title,
        tema: document.documentElement.dataset.tema || 'nothing',
        clasesBody: document.body.className,
        estadoOrbe: (document.getElementById('orbe-wrap') || {}).dataset?.estado || null,
        estadoTexto: (document.getElementById('estado') || {}).textContent || '',
        agentesAbierto: !!(window.Agentes && window.Agentes.abierto && window.Agentes.abierto()),
        fondoActivo: !!window.FONDO_ON,
        errorOverlayVisible: !!errVisible,
        errorOverlayTexto: errVisible ? ov.textContent.slice(0, 300) : null,
        viewport: {w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio}
      };
    })()
    """
    return await evaluar(js)


def main():
    ap = argparse.ArgumentParser(description="Inspector CDP en vivo del panel de DeltaOS")
    ap.add_argument("--status", action="store_true", help="Estado general del DOM, tema y errores")
    ap.add_argument("--eval", type=str, help="Expresión JavaScript a evaluar en la página del panel")
    ap.add_argument("--agentes", action="store_true", help="Abrir la vista de Agentes en el panel")
    args = ap.parse_args()

    try:
        if args.agentes:
            res = asyncio.run(evaluar("window.Agentes && window.Agentes.abrir(); 'abierto'"))
            print(res)
        elif args.eval:
            res = asyncio.run(evaluar(args.eval))
            print(json.dumps(res, ensure_ascii=False, indent=2) if isinstance(res, (dict, list)) else res)
        else:
            res = asyncio.run(estado_panel())
            print(json.dumps(res, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error CDP: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
