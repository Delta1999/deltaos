"""Panel web de estado (estilo Nothing, matriz de puntos) para un monitor secundario.

assistant.py llama a start(ST, voz) y a habla()/texto()/fin_turno(); el resto se deriva de ST.
Todo va protegido: si el panel falla, el asistente sigue.
"""
import asyncio
import glob
import json
import time
from pathlib import Path

import httpx
from aiohttp import web

import acciones

PORT = 7876
AQUI = Path(__file__).parent
S = {"frases": [], "voz": "", "impresora": None, "clima": None, "sistema": {}, "evento": None}
_hablando_hasta = 0.0
_clientes: set = set()
_cpu_prev = None


# ---- llamados desde assistant.py (baratos y sin excepciones) ----
def habla():
    global _hablando_hasta
    _hablando_hasta = time.monotonic() + 0.8


def texto(rol: str, t: str):
    """Acumula fragmentos de transcripción; un cambio de rol abre frase nueva."""
    f = S["frases"]
    if f and f[-1]["rol"] == rol and not f[-1].get("fin"):
        f[-1]["t"] += t
    else:
        f.append({"rol": rol, "t": t})
        del f[:-2]  # solo las 2 últimas


def fin_turno():
    if S["frases"]:
        S["frases"][-1]["fin"] = True


# ---- derivación de estado ----
def _estado(ST):
    if not ST["activo"]:
        return "dormido"
    if time.monotonic() < _hablando_hasta:
        return "hablando"
    if ST.get("herramienta") or any(v == "en curso" for v in ST["trabajos"].values()):
        return "trabajando"
    return "escuchando"


def _memoria():
    notas = [l for l in acciones.leer_memoria().splitlines() if l.strip()]
    return {"n": len(notas), "ultima": notas[-1].lstrip("-• ")[:90] if notas else ""}


def _sistema():
    global _cpu_prev
    m = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in Path("/proc/meminfo").read_text().splitlines())}
    cpu = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    uso = 0
    if _cpu_prev:
        dt = sum(cpu) - sum(_cpu_prev)
        di = (cpu[3] + cpu[4]) - (_cpu_prev[3] + _cpu_prev[4])
        uso = round(100 * (1 - di / dt)) if dt else 0
    _cpu_prev = cpu
    temp = None
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        if Path(z, "type").read_text().strip() == "x86_pkg_temp":
            temp = round(int(Path(z, "temp").read_text()) / 1000)
    return {"ram": round(100 * (1 - m["MemAvailable"] / m["MemTotal"])),
            "swap": round(100 * (1 - m["SwapFree"] / m["SwapTotal"])) if m["SwapTotal"] else 0,
            "cpu": uso, "temp": temp}


def snapshot(ST):
    ahora = time.monotonic()
    claude = {n: e for n, e in ST["trabajos"].items() if n.startswith("claude")}
    return {
        **S,
        "estado": _estado(ST),
        "conexion": "conectado" if ST["session"] else "reconectando",
        "herramienta": ST.get("herramienta"),
        "trabajos": {n: e for n, e in ST["trabajos"].items() if n not in claude},
        "claude": claude,
        "memoria": _memoria(),
        "sueno": max(0, round(acciones.INACTIVIDAD - (ahora - ST["ultima"]))) if ST["activo"] else None,
        "ultima": round(ahora - ST["ultima"]),
        "hora": time.strftime("%H:%M"),
        "fecha": time.strftime("%a %d %b").upper(),
    }


# ---- pollers ----
async def _poll_sistema():
    while True:
        try:
            S["sistema"] = await asyncio.to_thread(_sistema)
        except Exception:
            pass
        await asyncio.sleep(3)


async def _poll_impresora():
    previo = None
    while True:
        try:
            st = await acciones._impresora()
            ps = st["print_stats"]
            S["impresora"] = {
                "online": True, "estado": ps["state"], "archivo": ps.get("filename", ""),
                "prog": round(st["virtual_sdcard"]["progress"] * 100),
                "boquilla": [round(st["extruder"]["temperature"]), round(st["extruder"]["target"])],
                "cama": [round(st["heater_bed"]["temperature"]), round(st["heater_bed"]["target"])],
            }
            if ps["state"] in ("printing", "paused"):
                S["impresora"]["quedan"] = (await acciones._tiempo_restante_impresora())[0]
            if previo == "printing" and ps["state"] == "complete":
                S["evento"] = {"tipo": "print_ok", "archivo": ps.get("filename", ""),
                               "total": acciones._hhmm(ps.get("total_duration") or ps.get("print_duration", 0)),
                               "id": time.time()}
            previo = ps["state"]
        except Exception:
            S["impresora"] = {"online": False}  # sin datos viejos: se muestra "sin conexión"
            previo = None
        await asyncio.sleep(5)


async def _poll_clima():
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                j = (await c.get("https://wttr.in/?format=j1")).json()
            cur = j["current_condition"][0]
            S["clima"] = {"temp": int(cur["temp_C"]), "sens": int(cur["FeelsLikeC"]), "hum": int(cur["humidity"]),
                          "desc": cur["weatherDesc"][0]["value"], "ciudad": j["nearest_area"][0]["areaName"][0]["value"],
                          "max": int(j["weather"][0]["maxtempC"]), "min": int(j["weather"][0]["mintempC"])}
        except Exception:
            pass  # conserva el último clima; 15 min es poco para que caduque
        await asyncio.sleep(900)


# ---- servidor ----
async def _ws(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _clientes.add(ws)
    try:
        await ws.send_str(json.dumps(snapshot(request.app["ST"])))  # estado completo al conectar
        async for _ in ws:
            pass
    finally:
        _clientes.discard(ws)
    return ws


async def _difusor(ST):
    ultimo = None
    while True:
        await asyncio.sleep(0.4)
        try:
            msg = json.dumps(snapshot(ST))
            if msg != ultimo and _clientes:
                ultimo = msg
                await asyncio.gather(*(c.send_str(msg) for c in list(_clientes)), return_exceptions=True)
        except Exception as e:
            print(f"panel: {e}")


async def start(ST, voz):
    """Arranca el servidor en 127.0.0.1; devuelve True si quedó escuchando."""
    S["voz"] = voz
    try:
        app = web.Application()
        app["ST"] = ST
        app.router.add_get("/", lambda r: web.FileResponse(AQUI / "panel" / "index.html"))
        app.router.add_get("/ws", _ws)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", PORT).start()
    except Exception as e:
        print(f"Panel no disponible: {e}")
        return False
    for f in (_poll_sistema, _poll_impresora, _poll_clima):
        asyncio.create_task(f())
    asyncio.create_task(_difusor(ST))
    print(f"Panel en http://127.0.0.1:{PORT}")
    return True
