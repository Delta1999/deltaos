"""La pantalla no viaja sola: despierto y sin directo no se manda nada; en directo, sí (.venv/bin/python test_pantalla_bajo_peticion.py)"""
import asyncio
import time

import assistant as A
import acciones


class Sesion:
    n = 0

    async def send_realtime_input(self, **kw):
        Sesion.n += 1


A.capture_screen_wayland = lambda *a, **k: (b"jpg", [0] * 4)
A.cambio = lambda a, b: 99


async def main():
    s = Sesion()
    acciones.ST.update(activo=True, vivo=0, privacidad=False)
    t = asyncio.create_task(A.screen_capture_loop(s, 0.05))
    await asyncio.sleep(1)
    assert Sesion.n == 0, "despierto y sin directo no debe mandar pantalla"
    acciones.ST["vivo"] = time.monotonic() + 30
    await asyncio.sleep(1)
    assert Sesion.n >= 1, "en directo sí"
    t.cancel()
    await asyncio.gather(t, return_exceptions=True)
    print("OK: la pantalla solo viaja en directo")

asyncio.run(main())
