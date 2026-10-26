"""Comprobación de voz_movil: por Tailscale solo /movil y solo el dueño; el WebSocket exige Origin, despierta a
Delta con el micro del móvil y le lleva la voz (y el corte si el usuario habla encima)."""
import asyncio
import json

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import acciones
import panel
import voz_movil

acciones.activar = lambda: acciones.ST.update(activo=True)  # sin pitido ni música en la prueba
voz_movil.DUENO, TS = "yo@ejemplo", "fedora.tail0.ts.net"
voz_movil.ORIGENES.add(f"https://{TS}")


async def main():
    app = web.Application(middlewares=[panel._guardia])
    for ruta, h in panel.RUTAS:
        app.router.add_get(ruta, h)
    app.router.add_get("/", lambda r: web.Response(text="panel"))
    async with TestClient(TestServer(app, host="127.0.0.1")) as c:
        # por Tailscale: el panel no, /movil sí pero solo con la cuenta dueña
        assert (await c.get("/", headers={"Host": TS, "Tailscale-User-Login": "yo@ejemplo"})).status == 403
        assert (await c.get("/movil", headers={"Host": TS})).status == 403
        assert (await c.get("/movil", headers={"Host": TS, "Tailscale-User-Login": "otro@x"})).status == 403
        assert (await c.get("/movil", headers={"Host": TS, "Tailscale-User-Login": "yo@ejemplo"})).status == 200
        assert (await c.get("/")).status == 200  # en local, el panel como siempre
        # WebSocket: sin Origin de los nuestros, fuera
        r = await c.get("/movil/ws", headers={"Origin": "https://malo.example", "Connection": "Upgrade",
                                              "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
                                              "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
        assert r.status == 403
        acciones.ST["activo"] = False
        ws = await c.ws_connect("/movil/ws", headers={"Origin": f"https://{TS}", "Host": TS,
                                                      "Tailscale-User-Login": "yo@ejemplo"})
        assert (await ws.receive_json())["e"] == "dormida"
        await ws.send_bytes(b"\x05\x05")  # antes de tocar el orbe, el micro del móvil no cuenta
        await ws.send_str(json.dumps({"cmd": "hablar"}))
        assert (await ws.receive_json(timeout=2))["e"] == "escuchando"
        assert voz_movil.manda() and acciones.ST["activo"]
        await ws.send_bytes(b"\x01\x02" * 3)
        await asyncio.sleep(0.1)
        assert voz_movil.trozo(4) == bytes(4) and len(voz_movil._MIC) == 6  # sin colchón aún: silencio, nada se pierde
        await ws.send_bytes(b"\x03\x04" * (voz_movil.COLCHON // 2 + 1))
        await asyncio.sleep(0.1)
        assert voz_movil.trozo(8) == b"\x01\x02" * 3 + b"\x03\x04"  # con colchón: en orden
        voz_movil._MIC.clear()
        assert voz_movil.trozo(4) == bytes(4)  # se vació: silencio y a juntar colchón otra vez
        await ws.send_bytes(b"\x07\x07" * 4)
        await asyncio.sleep(0.1)
        assert voz_movil.trozo(4) == bytes(4)
        voz_movil.audio(b"\x09" * 4)
        assert (await ws.receive_bytes(timeout=2)) == b"\x09" * 4
        voz_movil.audio(b"\x08" * 4)
        voz_movil.cortar()  # lo pendiente se tira y el móvil recibe el corte
        assert (await ws.receive_json(timeout=2)) == {"cortar": 1}
        acciones.ST["activo"] = False  # se duerme: todo vuelve al PC
        assert not voz_movil.manda()
        await ws.close()
    print("OK: Tailscale solo deja /movil al dueño, el WS exige Origin y lleva micro, voz y corte")


asyncio.run(main())
