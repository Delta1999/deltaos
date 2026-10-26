"""Hablar con Delta desde el móvil: la web /movil, por Tailscale (https://<este PC>.ts.net/movil), hace de micro y
altavoz de Delta. Es la misma Delta, con la misma sesión y todas sus herramientas; el móvil solo lleva el audio.

Se toca el orbe → Delta despierta y oye por el móvil: el micro del PC queda sordo y su altavoz callado (como con el
mando de la tele) hasta que se vuelve a dormir; entonces todo vuelve al PC y el móvil cierra su micro.
Solo por el WebSocket /movil/ws, que comprueba Origin; y por Tailscale solo entra la cuenta dueña de este PC
(panel._guardia llama a permitido())."""
import asyncio
import json
import subprocess
import time

from aiohttp import web

import acciones
import panel

MIC_MAX = 16000 * 2 * 10  # 10 s de micro del móvil (16 kHz mono s16le): lo que tarda Delta en conectar al despertar, sin perder lo dicho
OTRA = 4000  # cierre del WS «te ha quitado el sitio otra pantalla»: si se reconectara sola, dos se echarían sin fin
COLA_MAX = 600      # trozos de voz para el móvil (~1 min): si se llena, el móvil no da abasto y se tira

_MIC = bytearray()
_CLI = {"ws": None, "cola": None}
MANDA = {"si": False}  # lo despertó el móvil: oye y habla por él
# Cómo le llega el micro del móvil a Delta en esta charla; se cuenta en el log al terminar (📱 mic: ...)
ESTAD = {"recib": 0, "tiradas": 0, "maxint": 0.0, "ult": None, "cortes": 0}


def _resumen():
    e = ESTAD.copy()
    if e["recib"]:
        print(f"📱 mic: {e['recib'] / 32000:.1f} s recibidos, {e['tiradas'] / 32000:.1f} s tirados por acumulación, "
              f"llegada más lenta {e['maxint']:.0f} ms, {e['cortes']} cortes de voz por interrupción")
    ESTAD.update(recib=0, tiradas=0, maxint=0.0, ult=None, cortes=0)


def _tailscale():
    """(origen https de este PC en la tailnet, login del dueño), o (None, None) sin Tailscale."""
    try:
        d = json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True,
                                      timeout=5).stdout)
        yo = d["Self"]
        return f"https://{yo['DNSName'].rstrip('.')}", d["User"][str(yo["UserID"])]["LoginName"]
    except Exception:
        return None, None


WEB_MOVIL = ("/movil", "/orbe.js")  # lo que carga la web del móvil además de /movil/ws y las fuentes
ORIGEN_TS, DUENO = _tailscale()
ORIGENES = panel.ORIGENES | ({ORIGEN_TS} if ORIGEN_TS else set())


def permitido(request):
    """Petición llegada por tailscale serve: solo la web del móvil y solo la cuenta dueña de este PC
    (tailscale serve pone Tailscale-User-Login y quita el que traiga el cliente)."""
    return DUENO is not None and request.headers.get("Tailscale-User-Login") == DUENO \
        and (request.path in WEB_MOVIL or request.path.startswith(("/movil/", "/fonts/")))


def manda():
    """¿Oye y habla Delta por el móvil? Mientras esté despierta, la despertara el móvil y siga con la web abierta."""
    if not acciones.ST["activo"] or _CLI["ws"] is None:
        if MANDA["si"]:
            _resumen()
        MANDA["si"] = False
    return MANDA["si"]


def trozo():
    """Todo el micro del móvil que haya llegado, para Delta en lugar del micro del PC (b"" si no hay). Va tal cual
    llega: rellenar con silencio los huecos de la red, al ritmo del micro del PC, lo mezclaba todo y Delta oía mal."""
    d = bytes(_MIC)
    _MIC.clear()
    return d


def audio(pcm):
    """Voz de Delta (24 kHz mono s16le) para el móvil."""
    try:
        _CLI["cola"].put_nowait(pcm)
    except (AttributeError, asyncio.QueueFull):
        pass


def cortar():
    """El usuario ha hablado encima: el móvil tira lo que le quede por decir."""
    c = _CLI["cola"]
    if c is not None:
        ESTAD["cortes"] += 1
        while not c.empty():
            c.get_nowait()
        c.put_nowait({"cortar": 1})


def _estado():
    st = acciones.ST
    e = ("privacidad" if st.get("privacidad") else "dormida" if not st["activo"]
         else "en el PC" if not manda() else "hablando" if st.get("hablando") else "escuchando")
    s = panel.S.get("sistema") or {}
    c, i = panel.S.get("clima"), panel.S.get("impresora")
    # el resumen de lo que enseña el panel: clima, impresión y los avisos de la semana (nada de ellos con privacidad)
    cl = {k: c.get(k) for k in ("temp", "desc", "min", "max", "lluvia", "sale", "pone")} if c else None
    im = {k: i.get(k) for k in ("online", "estado", "prog", "quedan")} if i else None
    sem = [] if st.get("privacidad") else \
        [{"t": a["t"], "texto": a["texto"][:40], "tipo": a["tipo"]} for a in (panel.S.get("semana") or [])[:30]]
    # «o»: el estado del orbe (el mismo que el del panel); «e»: lo que el móvil puede hacer con él
    return {"e": e, "o": panel._estado(st), "tema": panel.S.get("tema", "nothing"),
            "con": "conectado" if st["session"] else "en reposo" if st.get("reposo") else "reconectando",
            "sis": {k: s.get(k) for k in ("cpu", "ram", "temp")}, "cl": cl, "im": im, "sem": sem,
            "f": [{"rol": f["rol"], "t": f["t"][-300:]} for f in panel.S["frases"][-4:]]}


async def _enviar(ws, cola):
    """Voz y estado hacia el móvil, en orden y desde una sola tarea."""
    ultimo = None
    while not ws.closed:
        try:
            x = await asyncio.wait_for(cola.get(), 0.3)
            await (ws.send_bytes(x) if isinstance(x, bytes) else ws.send_json(x))
        except asyncio.TimeoutError:
            pass
        e = _estado()
        if e != ultimo:
            ultimo = e
            await ws.send_json(e)


async def _ws(request):
    # Los WebSocket no tienen CORS: sin esto cualquier web abierta en el PC podría hablarle a Delta.
    if request.headers.get("Origin") not in ORIGENES:
        raise web.HTTPForbidden()
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
    await ws.prepare(request)
    if _CLI["ws"] is not None:  # otra pestaña u otro móvil: manda la última; la echada no vuelve sola (ver OTRA)
        await _CLI["ws"].close(code=OTRA)
    cola = asyncio.Queue(COLA_MAX)
    _CLI.update(ws=ws, cola=cola)
    MANDA["si"] = False
    envio = acciones.tarea(_enviar(ws, cola))
    print("📱 móvil conectado")
    try:
        async for m in ws:
            if m.type == web.WSMsgType.BINARY:
                if MANDA["si"]:
                    ahora = time.monotonic()
                    if ESTAD["ult"] is not None:
                        ESTAD["maxint"] = max(ESTAD["maxint"], (ahora - ESTAD["ult"]) * 1000)
                    ESTAD["ult"] = ahora
                    ESTAD["recib"] += len(m.data)
                    _MIC.extend(m.data)
                    if len(_MIC) > MIC_MAX:
                        ESTAD["tiradas"] += len(_MIC) - MIC_MAX
                        del _MIC[:-MIC_MAX]
            elif m.type == web.WSMsgType.TEXT:
                cmd = json.loads(m.data).get("cmd")
                if cmd:
                    print(f"📱 móvil: {cmd}")
                if cmd == "hablar" and not acciones.ST.get("privacidad"):
                    _MIC.clear()
                    _resumen()
                    MANDA["si"] = True
                    acciones.activar()
                elif cmd == "dormir" and manda():
                    acciones.dormir_ahora()
    except Exception as e:
        print(f"📱 móvil: {e}")
    finally:
        if _CLI["ws"] is ws:
            _CLI.update(ws=None, cola=None)
            MANDA["si"] = False
        envio.cancel()
        _resumen()
        print("📱 móvil desconectado")
    return ws


async def _pagina(request):
    return web.FileResponse(acciones.AQUI / "panel" / "movil.html", headers={"Cache-Control": "no-cache"})


panel.RUTAS.append(("/movil", _pagina))
panel.RUTAS.append(("/movil/ws", _ws))
panel.POR_TAILSCALE = permitido
