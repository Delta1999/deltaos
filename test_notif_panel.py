"""Ventana de notificaciones del panel: pedir una notificación devuelve su texto solo a quien la pide, y el «Enviar»
de la ventana responde por KDE Connect."""
import asyncio
import json
import sys
import types

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import panel

ENVIADAS = []


async def notificacion(nid):
    return {"id": nid, "app": "WhatsApp", "quien": "Ana", "texto": "¿Cenamos?", "resp": True}


async def responder_id(nid, mensaje):
    ENVIADAS.append((nid, mensaje))
    return "ok"


sys.modules["movil"] = types.SimpleNamespace(notificacion=notificacion, responder_id=responder_id)


async def main():
    app = web.Application()
    app["ST"] = panel.acciones.ST
    app.router.add_get("/ws", panel._ws)
    async with TestClient(TestServer(app, host="127.0.0.1")) as c:
        ws = await c.ws_connect("/ws")
        await ws.receive_json()  # el estado completo al conectar
        await ws.send_str(json.dumps({"notif_abrir": "7"}))
        m = await ws.receive_json(timeout=2)
        assert m == {"notif": {"id": "7", "app": "WhatsApp", "quien": "Ana", "texto": "¿Cenamos?", "resp": True}}, m
        await ws.send_str(json.dumps({"notif_responder": {"id": "7", "texto": "Vale, a las 9"}}))
        while "notif_res" not in (m := await ws.receive_json(timeout=2)):
            pass  # puede colarse algún estado difundido
        assert m == {"notif_res": "ok"} and ENVIADAS == [("7", "Vale, a las 9")], (m, ENVIADAS)
        await ws.close()
    print("OK: el panel abre una notificación y responde desde su ventana")


asyncio.run(main())
