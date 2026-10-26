"""Comprobación de voz_movil: por Tailscale solo /movil y solo el dueño; el WebSocket exige Origin, despierta a
Delta con el micro del móvil y le lleva la voz (y el corte si el usuario habla encima)."""
import asyncio
import json
import sys
import tempfile
import types
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import acciones
import avisos_web
import panel
import voz_movil

_d = Path(tempfile.mkdtemp())  # las suscripciones y la clave de la prueba, no las de verdad
avisos_web.CLAVE, avisos_web.SUSCR = _d / "clave.pem", _d / "suscr.json"
APAGADOS = []


async def _energia(accion, minutos='0'):
    APAGADOS.append(accion)
    return 'Hecho'


sys.modules['deltaos'] = types.SimpleNamespace(energia=_energia)  # el apagado real no se prueba
acciones.activar = lambda: acciones.ST.update(activo=True)  # sin pitido ni música en la prueba
voz_movil.DUENO, TS = "yo@ejemplo", "fedora.tail0.ts.net"
voz_movil.ORIGENES.add(f"https://{TS}")


async def main():
    app = web.Application(middlewares=[panel._guardia])
    for ruta, h in panel.RUTAS:
        app.router.add_get(ruta, h)
    for ruta in ("/", "/orbe.js", "/fondo.js", "/fonts/doto-400.ttf", "/impresora/vivo"):
        app.router.add_get(ruta, lambda r: web.Response(text="panel"))
    async with TestClient(TestServer(app, host="127.0.0.1")) as c:
        # por Tailscale: el panel no, /movil sí pero solo con la cuenta dueña
        assert (await c.get("/", headers={"Host": TS, "Tailscale-User-Login": "yo@ejemplo"})).status == 403
        assert (await c.get("/movil", headers={"Host": TS})).status == 403
        assert (await c.get("/movil", headers={"Host": TS, "Tailscale-User-Login": "otro@x"})).status == 403
        assert (await c.get("/movil", headers={"Host": TS, "Tailscale-User-Login": "yo@ejemplo"})).status == 200
        assert (await c.get("/")).status == 200  # en local, el panel como siempre
        dueno = {"Host": TS, "Tailscale-User-Login": "yo@ejemplo"}
        r = await c.get("/movil/sw.js", headers=dueno)  # el service worker de los avisos: sí, y solo al dueño
        assert r.status == 200 and "showNotification" in await r.text()
        assert (await c.get("/movil/sw.js", headers={"Host": TS})).status == 403
        for ruta in ("/movil/manifest.webmanifest", "/movil/iconos/icono-192.png", "/movil/iconos/icono-maskable-512.png"):
            assert (await c.get(ruta, headers=dueno)).status == 200, ruta  # manifest e iconos de la web instalada
            assert (await c.get(ruta, headers={"Host": TS})).status == 403, ruta
        assert (await c.get("/movil/iconos/otro.png", headers=dueno)).status == 404
        for ruta in ("/orbe.js", "/fonts/doto-400.ttf"):  # lo que carga la web del móvil: sí, y solo al dueño
            assert (await c.get(ruta, headers=dueno)).status == 200, ruta
            assert (await c.get(ruta, headers={"Host": TS})).status == 403, ruta
        for ruta in ("/fondo.js", "/impresora/vivo"):  # el resto del panel, ni al dueño
            assert (await c.get(ruta, headers=dueno)).status == 403, ruta
        # WebSocket: sin Origin de los nuestros, fuera
        r = await c.get("/movil/ws", headers={"Origin": "https://malo.example", "Connection": "Upgrade",
                                              "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
                                              "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
        assert r.status == 403
        acciones.ST["activo"] = False
        ws = await c.ws_connect("/movil/ws", headers={"Origin": f"https://{TS}", "Host": TS,
                                                      "Tailscale-User-Login": "yo@ejemplo"})
        est = await ws.receive_json()
        assert est["e"] == "dormida" and est["o"] == "dormido" and est["tema"] in ("nothing", "ios")
        assert est["push"]["clave"] and est["push"]["n"] == avisos_web.cuantas()  # con qué clave se suscribe el móvil
        assert set(est["sis"]) == {"cpu", "ram", "temp"} and "con" in est  # lo que pinta el orbe de la web
        panel.S["clima"] = {"temp": 18, "sens": 17, "hum": 60, "desc": "Despejado", "ciudad": "Sevilla", "min": 11, "max": 22,
                            "lluvia": 5, "viento": 9, "dir": "NO", "uv": 3, "sale": 450, "pone": 1110, "code": 113, "presion": 1015,
                            "horas": [{"k": 12, "t": 20, "c": 113, "ll": 0, "v": 5, "s": 20, "hu": 50}],
                            "dias": [{"f": "2026-10-26", "min": 11, "max": 22, "c": 113, "ll": 5, "uv": 3, "sale": 450, "pone": 1110}]}
        panel.S["impresora"] = {"online": True, "estado": "printing", "prog": 40, "quedan": 3600, "archivo": "pieza.gcode",
                                "boquilla": [215, 215], "cama": [60, 60], "trabajo": 3}
        panel.S["semana"] = [{"t": "2026-10-29 09:45", "texto": "x" * 60, "tipo": "aviso"}]
        e2 = voz_movil._estado()  # clima, impresión y avisos de la semana, recortados a lo que pinta el móvil
        assert "presion" not in e2["cl"] and e2["cl"]["temp"] == 18 and e2["cl"]["horas"] == [{"k": 12, "t": 20, "c": 113, "ll": 0}]
        assert e2["cl"]["dias"] == [{"f": "2026-10-26", "min": 11, "max": 22, "c": 113, "ll": 5}]
        assert e2["im"] == {"online": True, "estado": "printing", "archivo": "pieza.gcode", "prog": 40, "quedan": 3600,
                            "boquilla": [215, 215], "cama": [60, 60]} and len(e2["sem"][0]["texto"]) == 40
        acciones.ST["privacidad"] = True
        assert voz_movil._estado()["sem"] == []  # con privacidad, los avisos no salen
        acciones.ST["privacidad"] = False
        await ws.send_bytes(b"\x05\x05")  # antes de tocar el orbe, el micro del móvil no cuenta
        await ws.send_str(json.dumps({"cmd": "hablar"}))
        assert (await ws.receive_json(timeout=2))["e"] == "escuchando"
        assert voz_movil.manda() and acciones.ST["activo"]
        await ws.send_bytes(b"\x01\x02" * 3)
        await ws.send_bytes(b"\x03\x04")
        await asyncio.sleep(0.1)
        assert voz_movil.trozo() == b"\x01\x02" * 3 + b"\x03\x04"  # todo lo llegado, en orden, sin rellenos
        assert voz_movil.trozo() == b""  # no hay más: nada, ni silencio inventado
        voz_movil.audio(b"\x09" * 4)
        assert (await ws.receive_bytes(timeout=2)) == b"\x09" * 4
        voz_movil.audio(b"\x08" * 4)
        voz_movil.cortar()  # lo pendiente se tira y el móvil recibe el corte
        assert (await ws.receive_json(timeout=2)) == {"cortar": 1}
        sus = {"endpoint": "https://push.ejemplo/yo", "keys": {"p256dh": "a", "auth": "b"}}
        await ws.send_str(json.dumps({"cmd": "suscribir", "sub": sus}))  # el móvil se apunta a los avisos
        await asyncio.sleep(0.2)
        assert any(s["endpoint"] == sus["endpoint"] for s in avisos_web._leer())
        await ws.send_str(json.dumps({"cmd": "apagar"}))  # el botón del móvil apaga sin preguntar
        await asyncio.sleep(0.2)
        assert APAGADOS == ["apagar"], APAGADOS
        acciones.ST["activo"] = False  # se duerme: todo vuelve al PC
        assert not voz_movil.manda()
        otra = await c.ws_connect("/movil/ws", headers={"Origin": "http://127.0.0.1:7876"})
        while not ws.closed:
            await ws.receive(timeout=2)  # (pueden colarse estados) otra pantalla le quita el sitio: se cierra con OTRA, para no reconectar sola
        assert ws.closed and ws.close_code == voz_movil.OTRA, ws.close_code
        await otra.close()
    print("OK: Tailscale solo deja /movil al dueño, el WS exige Origin y lleva micro, voz y corte")


asyncio.run(main())
