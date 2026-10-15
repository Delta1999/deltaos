"""Panel web de estado (estilo Nothing, matriz de puntos) para un monitor secundario.

assistant.py llama a start(ST, voz) y a habla()/texto()/fin_turno(); el resto se deriva de ST.
Todo va protegido: si el panel falla, el asistente sigue.
"""
import asyncio
import glob
import json
import math
import os
import socket
import subprocess
import urllib.parse
import time
from pathlib import Path

import httpx
from aiohttp import web

import acciones

PORT = 7876
AQUI = Path(__file__).parent
S = {"frases": [], "voz": "", "dispos": [], "impresora": None, "clima": None, "sistema": {}, "evento": None,
     "modo": "chat", "notifs": [], "nuevas": 0, "aec": True}
_hablando_hasta = 0.0
GEO = AQUI / "panel" / "geo.json"  # última posición dada por el navegador (Chromium sin clave de Google: poco fiable)
FIJA = AQUI / "ubicacion_fija.json"  # la que dice el usuario («estoy en …»): manda sobre todo
_geo_nuevo = asyncio.Event()
_clientes: set = set()
RUTAS = []  # (ruta, handler) que añaden otros módulos (deltaos)
_cpu_prev = None


# ---- llamados desde assistant.py (baratos y sin excepciones) ----
def habla(nivel=0.0):
    """nivel: amplitud 0..1 del fragmento de audio que se está reproduciendo."""
    global _hablando_hasta
    _hablando_hasta = time.monotonic() + 0.8
    S["nivel"] = round(nivel, 2)


def texto(rol: str, t: str):
    """Acumula fragmentos de transcripción; un cambio de rol abre frase nueva."""
    f = S["frases"]
    if f and f[-1]["rol"] == rol and not f[-1].get("fin"):
        f[-1]["t"] += t
    else:
        f.append({"rol": rol, "t": t})
        del f[:-2]  # solo las 2 últimas


def notificar(tipo: str, txt: str):
    """Aviso importante para el modo ALERTAS del panel. tipo: 'alerta' (rojo) o 'info'."""
    S["notifs"].append({"t": time.strftime("%H:%M"), "tipo": tipo, "txt": txt[:140], "id": time.time()})
    del S["notifs"][:-8]
    S["nuevas"] += 1


# $ por 1M tokens del nivel de pago de gemini-3.8-live (ai.google.dev/gemini-api/docs/pricing, 2026-10):
# el nivel gratis no cobra; se enseña para saber cuánto costaría.
PRECIO_IN = {"TEXT": 0.75, "AUDIO": 3.00, "IMAGE": 1.00, "VIDEO": 1.00}
PRECIO_OUT = {"TEXT": 4.50, "AUDIO": 12.00}
CONTEXTO_MAX = 128_000


def uso(um):
    """usage_metadata llega una vez por turno: prompt_token_count es el contexto entero de ese turno."""
    u = S.setdefault("uso", {"ctx": 0, "tok": 0, "usd": 0.0, "turnos": 0})
    coste = lambda det, pr, dflt: sum(d.token_count * pr.get(getattr(d.modality, "value", str(d.modality)), dflt) for d in det or [])
    u["ctx"] = round(100 * (um.prompt_token_count or 0) / CONTEXTO_MAX, 1)
    u["tok"] += um.total_token_count or 0
    u["usd"] += (coste(um.prompt_tokens_details, PRECIO_IN, 3.0) + coste(um.response_tokens_details, PRECIO_OUT, 12.0)) / 1e6
    u["turnos"] += 1


def fin_turno():
    if S["frases"]:
        S["frases"][-1]["fin"] = True


# ---- derivación de estado ----
def _estado(ST):
    if not ST["activo"]:
        return "dormido"
    if time.monotonic() < _hablando_hasta:
        return "hablando"
    if ST.get("herramienta") or any(v == "en curso" for v in ST["trabajos"].values()) or ST.get("claude", {}).get("estado") in ("trabajando", "esperando permiso"):
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


def _db01(x):
    """Amplitud int16 -> 0..1 en escala log (-60..0 dBFS), como un VU."""
    return max(0.0, min(1.0, (20 * math.log10(max(x, 1) / 32768) + 60) / 60))


def _mic(ST):
    if ST.get("privacidad"):
        return {"nivel": 0, "db": None, "estado": "off"}
    viva = time.monotonic() - ST.get("mic_t", 0) < 2
    rms = ST.get("mic_rms", 0)
    if not viva:
        est = "mal"
    elif ST.get("mic_clip", 0) > 0.15 or ST.get("ruido", 0) >= 3:
        est = "mal"
    else:
        est = "ok"
    return {"nivel": round(_db01(rms), 2) if viva else 0, "db": round(20 * math.log10(max(rms, 1) / 32768)) if viva else None,
            "estado": est, "sat": ST.get("mic_clip", 0) > 0.15, "ruido": ST.get("ruido", 0) >= 3, "viva": viva}


def _salud(ST, mic):
    cl = ST.get("claude", {}).get("estado", "libre")
    imp = S["impresora"]
    return {"enlace": "ok" if ST["session"] else "off" if ST.get("reposo") else "mal", "mic": mic["estado"],
            "aec": "ok" if S["aec"] else "mal",
            "claude": {"libre": "ok", "trabajando": "act"}.get(cl, "mal"),
            "impresora": "off" if not imp or not imp.get("online") else "act" if imp.get("estado") == "printing" else "ok"}


def snapshot(ST):
    ahora = time.monotonic()
    mic = _mic(ST)
    return {
        **S,
        "mic": mic, "salud": _salud(ST, mic), "lat": ST.get("lat"), "priv": bool(ST.get("privacidad")),
        "estado": _estado(ST),
        "conexion": "conectado" if ST["session"] else "en reposo" if ST.get("reposo") else "reconectando",
        "herramienta": ST.get("herramienta"),
        "pasos": ST.get("pasos", []),
        "confirma": getattr(ST["pending"], "texto", None) if ST["pending"] and not ST["pending"].done() else None,
        "trabajos": ST["trabajos"],
        "claude": ST.get("claude"),
        "memoria": _memoria(),
        "sueno": max(0, round(acciones.INACTIVIDAD - (ahora - ST["ultima"]))) if ST["activo"] else None,
        "ultima": round(ahora - ST["ultima"]),
        "nivel": S.get("nivel", 0) if time.monotonic() < _hablando_hasta else 0,
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
            if ps["state"] == "error" and previo != "error":
                notificar("alerta", "La impresora está en error")
            if previo == "printing" and ps["state"] == "complete":
                notificar("info", f"Impresión terminada: {ps.get('filename', '')}")
                S["evento"] = {"tipo": "print_ok", "archivo": ps.get("filename", ""),
                               "total": acciones._hhmm(ps.get("total_duration") or ps.get("print_duration", 0)),
                               "id": time.time()}
            previo = ps["state"]
        except Exception:
            if previo is not None:
                notificar("alerta", "Impresora sin conexión")
            S["impresora"] = {"online": False}  # sin datos viejos: se muestra "sin conexión"
            previo = None
        await asyncio.sleep(5)


def _bus(ruta, iface, *props):
    """Propiedades D-Bus de KDE Connect; None si el objeto no existe (p.ej. batería de un móvil sin vincular)."""
    r = subprocess.run(["busctl", "--user", "--json=short", "get-property", "org.kde.kdeconnect", ruta, iface, *props],
                       capture_output=True, text=True, timeout=4)
    return [json.loads(l)["data"] for l in r.stdout.splitlines()] if r.returncode == 0 else None


def _dispositivos():
    ids = subprocess.run(["kdeconnect-cli", "-l", "--id-only"], capture_output=True, text=True, timeout=6).stdout.split()
    out = []
    for i in ids:
        ruta = f"/modules/kdeconnect/devices/{i}"
        nombre, vinculado, alcance, tipo = _bus(ruta, "org.kde.kdeconnect.device", "name", "isPaired", "isReachable", "type")
        bat = _bus(ruta + "/battery", "org.kde.kdeconnect.device.battery", "charge", "isCharging") if vinculado and alcance else None
        out.append({"nombre": nombre, "tipo": tipo, "vinculado": vinculado, "alcance": alcance,
                    "carga": bat[0] if bat and bat[0] >= 0 else None, "cargando": bool(bat and bat[1])})
    return out


async def _poll_dispositivos():
    """KDE Connect: qué dispositivos hay, si están al alcance y su batería."""
    while True:
        try:
            S["dispos"] = await asyncio.to_thread(_dispositivos)
        except Exception:
            pass
        await asyncio.sleep(30)


async def _poll_agenda():
    """Próximos avisos (avisos.json, cada 5 s) y notificaciones del móvil (cada minuto) para la tarjeta Agenda."""
    import movil
    n = 0
    while True:
        try:
            lista = json.loads((AQUI / "avisos.json").read_text())
            S["avisos"] = sorted(({"t": a["t"], "texto": a["texto"], "tipo": a["tipo"]} for a in lista), key=lambda a: a["t"])[:4]
        except Exception:
            S["avisos"] = []
        if n % 12 == 0:
            try:
                d = await movil._movil()
                # solo app y remitente: el panel puede estar en la tele
                S["movil"] = [{"app": x.get("appName", ""), "quien": x.get("title", "")} for x in await movil._notificaciones(d)] if d else None
            except Exception:
                pass
        n += 1
        await asyncio.sleep(5)


async def _poll_audio():
    """El AEC (echo-cancel-source) tiene que seguir existiendo: si PipeWire lo pierde, el eco rompe la conversación."""
    while True:
        try:
            out = await asyncio.to_thread(lambda: subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=4).stdout)
            S["aec"] = "echo-cancel-source" in out
        except Exception:
            pass
        await asyncio.sleep(5)


_AVISOS = {"enlace": "Sesión con Gemini perdida", "mic": "Problema con el micrófono (saturado, sin señal o solo ruido)",
           "aec": "Cancelación de eco perdida"}
_salud_previa: dict = {}


def _vigila(sn):
    """Una transición ok -> mal en la salud se convierte en alerta (una vez, no en cada ciclo)."""
    for k, txt in _AVISOS.items():
        if sn["salud"][k] == "mal" and _salud_previa.get(k) not in (None, "mal"):
            notificar("alerta", txt)
    _salud_previa.update(sn["salud"])


VISTA = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "delta-vista"  # ventana.sh la lee y coloca panel y mascota


def vista(modo):
    VISTA.write_text(modo)


def _cmd(ST, cmd):
    if cmd == "privacidad":
        ST["privacidad"] = not ST.get("privacidad")
        if ST["privacidad"]:
            acciones.dormir_ahora()
        notificar("info", "Privacidad ACTIVADA: el micrófono se ignora, ni la palabra «Delta»" if ST["privacidad"] else "Privacidad desactivada")
    elif cmd == "modo":
        S["modo"] = "alertas" if S["modo"] == "chat" else "chat"
        S["nuevas"] = 0
    elif cmd in ("vista_panel", "vista_mascota"):
        vista(cmd[6:])
    elif cmd == "tiempo":
        acciones.tarea(_abrir_tiempo())
    elif cmd == "cerrar_visor":
        S["visor"] = None
    elif cmd == "dormir":
        acciones.dormir_ahora() if ST["activo"] else acciones.activar()
    elif cmd in ("permitir", "denegar") and ST["pending"] and not ST["pending"].done():
        ST["pending"].set_result("s" if cmd == "permitir" else "n")


PRECISA = 5000  # m; GeoClue por IP da ~25 km, por wifi conocida < 1 km


async def posicion():
    """«lat,lon» para wttr.in: fijada por el usuario > GeoClue preciso (wifi) > navegador > "" (wttr usa la IP)."""
    try:
        f = json.loads(FIJA.read_text())
        return f"{f['lat']},{f['lon']}"
    except Exception:
        pass
    try:
        p = await asyncio.create_subprocess_exec(str(AQUI / "ubicacion.py"), stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.DEVNULL)
        lat, lon, prec = map(float, (await asyncio.wait_for(p.communicate(), 25))[0].split())
        if prec <= PRECISA:
            return f"{lat:.2f},{lon:.2f}"
    except Exception:
        pass
    try:
        return "{},{}".format(*json.loads(GEO.read_text()))
    except Exception:
        return ""


NOTHING_WEATHER = acciones.WORMHOLE / "nothing-weather"   # el otro proyecto del usuario (vite preview, 7875)


async def _abrir_tiempo():
    """Clic en el tiempo: Nothing Weather en el visor, en la posición del usuario. Arranca su servidor si hace falta."""
    def abierto():
        try:
            socket.create_connection(("127.0.0.1", 7875), 0.3).close()
            return True
        except OSError:
            return False
    if not abierto():
        subprocess.Popen([str(NOTHING_WEATHER / "run.sh")], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            await asyncio.sleep(0.25)
            if abierto():
                break
    q = ""
    if (lugar := await posicion()):
        lat, lon = lugar.split(",")
        ciudad = (S["clima"] or {}).get("ciudad", "")
        q = "?" + urllib.parse.urlencode({"lat": lat, "lon": lon, "city": ciudad})
    S["visor"] = {"url": f"http://127.0.0.1:7875/{q}", "titulo": "Nothing Weather", "id": time.time()}


async def _poll_clima():
    while True:
        try:
            lugar = await posicion()
            async with httpx.AsyncClient(timeout=10) as c:
                j = (await c.get(f"https://wttr.in/{lugar}?format=j1")).json()
            cur, hoy = j["current_condition"][0], j["weather"][0]
            def min24(s):  # "06:30 AM" -> minutos desde medianoche
                h, m = time.strptime(s, "%I:%M %p")[3:5]
                return h * 60 + m
            S["clima"] = {"temp": int(cur["temp_C"]), "sens": int(cur["FeelsLikeC"]), "hum": int(cur["humidity"]),
                          "desc": cur["weatherDesc"][0]["value"], "ciudad": j["nearest_area"][0]["areaName"][0]["value"],
                          "max": int(hoy["maxtempC"]), "min": int(hoy["mintempC"]), "code": int(cur["weatherCode"]),
                          "viento": int(cur["windspeedKmph"]), "dir": cur["winddir16Point"], "uv": int(cur["uvIndex"]),
                          "lluvia": max(int(h["chanceofrain"]) for h in hoy["hourly"]),
                          "sale": min24(hoy["astronomy"][0]["sunrise"]), "pone": min24(hoy["astronomy"][0]["sunset"]),
                          # horas de hoy y mañana: k = horas desde las 00:00 de hoy
                          "horas": [{"k": d * 24 + int(h["time"]) // 100, "t": int(h["tempC"]), "c": int(h["weatherCode"])}
                                    for d, w in enumerate(j["weather"][:2]) for h in w["hourly"]]}
        except Exception:
            pass  # conserva el último clima; 15 min es poco para que caduque
        try:
            await asyncio.wait_for(_geo_nuevo.wait(), 900)
            _geo_nuevo.clear()
        except asyncio.TimeoutError:
            pass


# ---- servidor ----
ORIGENES = {None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}


async def _ws(request):
    # Los WebSocket no tienen CORS: sin esto cualquier web abierta leería la conversación y pulsaría botones.
    if request.headers.get("Origin") not in ORIGENES:
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _clientes.add(ws)
    try:
        await ws.send_str(json.dumps(snapshot(request.app["ST"])))  # estado completo al conectar
        async for m in ws:
            try:  # el navegador manda su posición {"geo":[lat,lon]} o un botón {"cmd":"privacidad"}
                msg = json.loads(m.data)
                if msg.get("cmd") in ("privacidad", "modo", "dormir", "permitir", "denegar", "cerrar_visor", "vista_panel", "vista_mascota", "tiempo"):
                    _cmd(request.app["ST"], msg["cmd"])
                g = msg.get("geo")
                if g and len(g) == 3 and all(isinstance(x, (int, float)) for x in g) and g[2] <= PRECISA:
                    g = [round(g[0], 2), round(g[1], 2)]  # ~1 km: sobra para el tiempo
                    if not GEO.exists() or json.loads(GEO.read_text()) != g:
                        GEO.write_text(json.dumps(g))
                        _geo_nuevo.set()
            except Exception:
                pass
    finally:
        _clientes.discard(ws)
    return ws


async def _difusor(ST):
    ultimo = None
    while True:
        await asyncio.sleep(0.4)
        try:
            sn = snapshot(ST)
            _vigila(sn)
            if S["modo"] == "alertas":
                sn["nuevas"] = S["nuevas"] = 0
            msg = json.dumps(sn)
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
        app.router.add_get("/mapache.txt", lambda r: web.FileResponse(AQUI / "panel" / "mapache.txt"))
        app.router.add_static("/fonts", AQUI / "panel" / "fonts")
        for ruta, h in RUTAS:
            app.router.add_get(ruta, h)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", PORT).start()
    except Exception as e:
        print(f"Panel no disponible: {e}")
        return False
    for f in (_poll_sistema, _poll_impresora, _poll_clima, _poll_audio, _poll_dispositivos, _poll_agenda):
        acciones.tarea(f())
    acciones.tarea(_difusor(ST))
    print(f"Panel en http://127.0.0.1:{PORT}")
    return True


# ---- herramienta para Gemini ----
def _es(x):  # descripción en español si wttr la da
    return (x.get("lang_es") or x["weatherDesc"])[0]["value"]


async def consultar_clima(lugar="", dias=1):
    """Tiempo actual y previsión (hasta 3 días) de un sitio; sin sitio, el del usuario (GPS del panel)."""
    try:
        dias = max(1, min(3, int(dias or 1)))
        lugar = lugar or await posicion()
        async with httpx.AsyncClient(timeout=10) as c:
            j = (await c.get(f"https://wttr.in/{lugar}", params={"format": "j1", "lang": "es"})).json()
        cur = j["current_condition"][0]
        zona = j["nearest_area"][0]["areaName"][0]["value"]
        out = [f"{zona}: ahora {cur['temp_C']}°C (sensación {cur['FeelsLikeC']}°), {_es(cur)}, viento {cur['windspeedKmph']} km/h {cur['winddir16Point']}, humedad {cur['humidity']}%."]
        for d, w in enumerate(j["weather"][:dias]):
            h = w["hourly"]
            out.append(f"{['Hoy', 'Mañana', 'Pasado mañana'][d]} ({w['date']}): {w['mintempC']}° a {w['maxtempC']}°, {_es(h[4])}, "
                       f"lluvia hasta {max(int(x['chanceofrain']) for x in h)}%, viento hasta {max(int(x['windspeedKmph']) for x in h)} km/h, UV {w['uvIndex']}.")
        return " ".join(out)
    except Exception as e:
        return f"No pude consultar el tiempo: {e}"


async def fijar_ubicacion(lugar):
    if lugar.strip().lower() in ("", "auto", "automática", "automatica", "borrar"):
        FIJA.unlink(missing_ok=True)
        _geo_nuevo.set()
        return "Ubicación fija borrada: vuelvo a situarme por la red."
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = (await c.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": lugar, "count": 1, "language": "es"})).json()["results"][0]
    except Exception:
        return f"No encuentro «{lugar}». Prueba con el nombre del pueblo o ciudad."
    nombre = ", ".join(x for x in (r["name"], r.get("admin2") or r.get("admin1"), r.get("country")) if x)
    FIJA.write_text(json.dumps({"lat": round(r["latitude"], 3), "lon": round(r["longitude"], 3), "nombre": nombre},
                               ensure_ascii=False))
    _geo_nuevo.set()  # el panel refresca el tiempo ya
    return f"Ubicación fijada en {nombre}."


acciones.registrar([
    acciones._fn("fijar_ubicacion",
                 "Fija dónde está el usuario («estoy en Chiclana», «vivo en …») para el tiempo y lo demás. "
                 "Ni el portátil tiene GPS ni la red da una posición fiable, así que es lo que manda. «auto» la borra.",
                 {"lugar": acciones._s("pueblo o ciudad, o «auto»")}),
    acciones._fn("consultar_clima",
                 "Consulta el tiempo en este momento: temperatura, viento, lluvia y previsión de hoy y los próximos días (hasta 3). "
                 "Sin lugar usa la ubicación del usuario. Úsala siempre que pregunte por el tiempo, la temperatura, el viento o la lluvia.",
                 {"lugar": acciones._s("ciudad o sitio; vacío = donde está el usuario"),
                  "dias": acciones._s("cuántos días de previsión, 1 a 3 (por defecto 1)")}),
], (fijar_ubicacion, consultar_clima))


_visto = 0.0  # id de la última notificación ya contada en un saludo


def contexto(ST):
    """Resumen corto de lo que importa ahora; el saludo proactivo se lo da a Gemini."""
    global _visto
    c = []
    imp = S["impresora"]
    if imp and imp.get("online"):
        if imp["estado"] in ("printing", "paused"):
            c.append(f"impresora {imp['estado']} al {imp['prog']}% ({imp['archivo']})")
        elif imp["estado"] == "error":
            c.append("impresora EN ERROR")
    elif imp is not None:
        c.append("impresora sin conexión")
    nuevas = [n for n in S["notifs"] if n["id"] > _visto]
    _visto = max([_visto] + [n["id"] for n in nuevas])
    c += [f"aviso {n['tipo']}: {n['txt']}" for n in nuevas[-3:]]
    cl = ST.get("claude", {})
    if cl.get("estado") in ("trabajando", "esperando permiso"):
        c.append(f"Claude Code {cl['estado']}: {cl.get('tarea', '')[:60]}")
    w = S["clima"]
    if w:
        c.append(f"tiempo en {w['ciudad']}: {w['temp']}°C, {w['desc']}, viento {w['viento']} km/h, lluvia {w['lluvia']}%")
    c.append(f"son las {time.strftime('%H:%M')}")
    return "; ".join(c)
