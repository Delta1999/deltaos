"""Delta en el móvil: web aparte (127.0.0.1:7877) con estado y chat de texto, para abrirla por Tailscale.

Proceso independiente de Delta: NO importa assistant/panel/acciones y no les manda órdenes.
Del panel solo LEE el estado por su WebSocket; de la impresora solo GET; de avisos.json solo lectura.
Si Delta está parado, el chat sigue funcionando (impresora y avisos los consulta directamente).
Arranque: .venv/bin/python delta_movil.py   (la clave de acceso está en movil_clave.txt)
"""
import asyncio
import datetime
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import httpx
from aiohttp import web
from google import genai
from google.genai import types

import movil_push

AQUI = Path(__file__).parent
WEB = AQUI / "panel_movil"
PORT = 7877
PANEL_WS = "http://127.0.0.1:7876/ws"
MOONRAKER = "http://192.168.0.102:7125"  # SOLO GET
MODELO = "gemini-3.8-flash"
CLAVE_F = AQUI / "movil_clave.txt"
COOKIE = "delta_m"
ESPERA_FALLO = 1.5  # s de castigo por clave mala (frena a quien pruebe a ciegas)

PANEL = {"sn": None, "t": 0.0}  # última instantánea del panel de Delta (None = Delta parado)


def _clave():
    if not CLAVE_F.exists():
        CLAVE_F.write_text(secrets.token_urlsafe(12) + "\n")
        CLAVE_F.chmod(0o600)
    return CLAVE_F.read_text().strip()


CLAVE = _clave()
FICHA = hashlib.sha256(("delta-movil:" + CLAVE).encode()).hexdigest()  # lo que guarda la cookie, no la clave


# ---- lectura del panel de Delta (sin Origin: el panel lo admite; aquí nunca se envía nada) ----
async def _escucha_panel():
    while True:
        try:
            async with aiohttp.ClientSession() as s, s.ws_connect(PANEL_WS, heartbeat=30) as ws:
                async for m in ws:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        PANEL["sn"], PANEL["t"] = json.loads(m.data), time.time()
                        _novedades(PANEL["sn"])
        except Exception:
            pass
        PANEL["sn"] = None
        await asyncio.sleep(5)


# ---- avisos al móvil (Web Push) ----
# Solo lo que importa fuera de casa; la salud interna de Delta (micro, sesión Gemini, impresora apagada) no.
AL_MOVIL = ("Impresión terminada", "La impresora está en error", "Claude Code", "Investigación lista", "Documento listo")
_visto = {"notif": None, "aviso": time.time()}


def _push(titulo, cuerpo, etiqueta):
    asyncio.get_running_loop().create_task(movil_push.enviar(titulo, cuerpo, etiqueta))


def _novedades(sn):
    ids = [n["id"] for n in sn.get("notifs") or []]
    if _visto["notif"] is None:  # al (re)conectar no se repite lo antiguo
        _visto["notif"] = max(ids, default=0)
        return
    for n in sn.get("notifs") or []:
        if n["id"] > _visto["notif"] and n["txt"].startswith(AL_MOVIL):
            _push("Delta", n["txt"], "impresora" if "mpresi" in n["txt"] else "delta")
    _visto["notif"] = max(ids + [_visto["notif"]])


async def _vigila_avisos():
    """Temporizadores/recordatorios de avisos.json que vencen: también al móvil (Delta los dice en casa)."""
    while True:
        await asyncio.sleep(5)
        ahora = time.time()
        try:
            lista = json.loads((AQUI / "avisos.json").read_text())
        except (OSError, ValueError):
            lista = []
        for a in lista:
            if _visto["aviso"] < a["t"] <= ahora:
                _push("⏰ " + {"alarma": "Alarma", "temporizador": "Temporizador"}.get(a["tipo"], "Recordatorio"), a["texto"], "aviso")
        _visto["aviso"] = ahora


def _resumen():
    """Lo que ve el móvil: sin la conversación ni el texto de las notificaciones del teléfono."""
    sn = PANEL["sn"]
    if not sn:
        return {"delta": False, "hora": time.strftime("%H:%M")}
    return {"delta": True, **{k: sn.get(k) for k in ("estado", "conexion", "hora", "fecha", "impresora", "clima",
                                                     "sistema", "avisos", "claude", "dispos")},
            "alertas": [n for n in (sn.get("notifs") or []) if n.get("tipo") == "alerta"][-3:]}


# ---- herramientas del chat (todas de solo lectura) ----
def ver_impresora() -> dict:
    """Estado actual de la impresora 3D (Klipper): estado, archivo, progreso %, temperaturas y tiempo restante en minutos."""
    try:
        r = httpx.get(f"{MOONRAKER}/printer/objects/query?print_stats&virtual_sdcard&extruder&heater_bed&display_status", timeout=4)
        st = r.json()["result"]["status"]
    except Exception as e:
        return {"online": False, "error": str(e)[:80]}
    ps, prog = st["print_stats"], st["virtual_sdcard"]["progress"]
    dur = ps.get("print_duration") or 0
    return {"online": True, "estado": ps["state"], "archivo": ps.get("filename", ""), "progreso": round(prog * 100),
            "boquilla": [round(st["extruder"]["temperature"]), round(st["extruder"]["target"])],
            "cama": [round(st["heater_bed"]["temperature"]), round(st["heater_bed"]["target"])],
            "quedan_min": round(dur / prog * (1 - prog) / 60) if prog > 0.01 and ps["state"] == "printing" else None}


def ver_avisos() -> list:
    """Temporizadores, alarmas y recordatorios programados en Delta (solo consulta)."""
    try:
        lista = json.loads((AQUI / "avisos.json").read_text())
    except (OSError, ValueError):
        return []
    return [{"cuando": time.strftime("%a %d %H:%M", time.localtime(a["t"])), "texto": a["texto"], "tipo": a["tipo"]}
            for a in sorted(lista, key=lambda a: a["t"])]


def ver_pc() -> dict:
    """Estado del PC de casa y de Delta: si Delta está en marcha, CPU/RAM/temperatura, Claude Code, móvil/tablet, alertas y el tiempo."""
    return _resumen()


# ---- chat ----
def _instrucciones(medio="TEXTO"):
    try:
        pers = (AQUI / "personalidad.txt").read_text()
    except OSError:
        pers = "Eres Delta, el asistente del usuario."
    try:
        lugar = json.loads((AQUI / "ubicacion_fija.json").read_text()).get("nombre", "")
    except (OSError, ValueError, AttributeError):
        lugar = ""
    return (f"{pers}\n\nAHORA hablas con el usuario por {medio} desde su MÓVIL (puede estar fuera de casa). "
            "Respuestas breves, sin markdown pesado. Puedes CONSULTAR la impresora, los avisos y el estado del PC con tus "
            "herramientas y buscar en internet; NO puedes mandar órdenes al PC, a la impresora ni al móvil: si te lo pide, "
            "dile que eso se hace desde casa con Delta. Español de España. "
            f"Fecha y hora: {time.strftime('%A %d/%m/%Y %H:%M')}. Casa del usuario: {lugar or 'desconocida'}.")


# ---- voz: el móvil habla directo con Gemini Live; aquí solo el token de un uso y las herramientas ----
MODELO_VOZ = "gemini-3.8-live"
VOZ = "Charon"
HERRAMIENTAS = {"ver_impresora": ver_impresora, "ver_avisos": ver_avisos, "ver_pc": ver_pc}
_cli_alfa = None


def _token_voz():
    """Token efímero de UN uso con toda la config bloqueada (el móvil no puede cambiar modelo, voz ni herramientas)."""
    global _cli_alfa
    _cli_alfa = _cli_alfa or genai.Client(http_options={"api_version": "v1alpha"})
    ahora = datetime.datetime.now(tz=datetime.timezone.utc)
    decl = [types.FunctionDeclaration(name=n, description=f.__doc__) for n, f in HERRAMIENTAS.items()]
    cfg = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(language_code="es-ES", voice_config=types.VoiceConfig(  # es-ES: sin acento latino
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOZ))),
        system_instruction=types.Content(parts=[types.Part(text=_instrucciones("VOZ (pulsa para hablar)") +
                                                           " Por voz: frases cortas, sin listas ni símbolos.")]),
        tools=[types.Tool(function_declarations=decl), types.Tool(google_search=types.GoogleSearch())],
        realtime_input_config=types.RealtimeInputConfig(  # pulsar para hablar: el móvil marca inicio y fin
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)),
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig())
    t = _cli_alfa.auth_tokens.create(config=types.CreateAuthTokenConfig(
        uses=1, expire_time=ahora + datetime.timedelta(minutes=30),
        new_session_expire_time=ahora + datetime.timedelta(minutes=1),
        live_connect_constraints=types.LiveConnectConstraints(model=MODELO_VOZ, config=cfg)))
    return t.name


_cli = None
_chat = {"c": None, "t": 0.0}
_lock = asyncio.Lock()
CADUCA_CHAT = 2 * 3600  # s sin escribir → conversación nueva (y hora del sistema al día)


def _nueva():
    global _cli
    _cli = _cli or genai.Client()
    _chat["c"] = _cli.aio.chats.create(model=MODELO, config=types.GenerateContentConfig(
        system_instruction=_instrucciones(),
        tools=[ver_impresora, ver_avisos, ver_pc, types.Tool(google_search=types.GoogleSearch())],
        tool_config=types.ToolConfig(include_server_side_tool_invocations=True)))  # búsqueda + funciones juntas


async def _responder(texto):
    async with _lock:
        if _chat["c"] is None or time.time() - _chat["t"] > CADUCA_CHAT:
            _nueva()
        _chat["t"] = time.time()
        r = await _chat["c"].send_message(texto)
        return (r.text or "").strip() or "(sin respuesta)"


# ---- web ----
def _dentro(request):
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), FICHA)


def _mismo_origen(request):
    """Los POST solo desde esta misma web (frena CSRF aunque la cookie ya sea SameSite=Strict)."""
    o = request.headers.get("Origin")
    return o is not None and urlparse(o).netloc == request.host


async def _inicio(request):
    return web.FileResponse(WEB / ("index.html" if _dentro(request) else "entrar.html"),
                            headers={"Cache-Control": "no-store"})


async def _entrar(request):
    if not _mismo_origen(request):
        raise web.HTTPForbidden()
    clave = (await request.post()).get("clave", "")
    if not hmac.compare_digest(str(clave).strip(), CLAVE):
        await asyncio.sleep(ESPERA_FALLO)
        raise web.HTTPFound("/?mal=1")
    r = web.HTTPFound("/")
    seguro = request.headers.get("X-Forwarded-Proto") == "https" or request.secure
    r.set_cookie(COOKIE, FICHA, max_age=180 * 86400, httponly=True, samesite="Strict", secure=seguro)
    raise r


async def _estado(request):
    if not _dentro(request):
        raise web.HTTPUnauthorized()
    return web.json_response(_resumen())


async def _hablar(request):
    if not _dentro(request) or not _mismo_origen(request):
        raise web.HTTPUnauthorized()
    d = await request.json()
    if d.get("nuevo"):
        _chat["c"] = None
        return web.json_response({"ok": True})
    texto = str(d.get("texto", "")).strip()[:4000]
    if not texto:
        raise web.HTTPBadRequest()
    try:
        return web.json_response({"r": await _responder(texto)})
    except Exception as e:
        print(f"chat: {e}")
        return web.json_response({"r": f"No he podido contestar ({type(e).__name__}). Pruebe otra vez."})


async def _vapid(request):
    if not _dentro(request):
        raise web.HTTPUnauthorized()
    return web.json_response({"clave": movil_push.PUBLICA, "n": len(movil_push.suscripciones())})


async def _suscribir(request):
    if not _dentro(request) or not _mismo_origen(request):
        raise web.HTTPUnauthorized()
    try:
        movil_push.suscribir(await request.json())
    except (KeyError, TypeError, ValueError):
        raise web.HTTPBadRequest()
    ok = await movil_push.enviar("Delta", "Avisos activados en este móvil, señor.", "prueba")
    return web.json_response({"ok": ok > 0})


async def _voz_token(request):
    if not _dentro(request) or not _mismo_origen(request):
        raise web.HTTPUnauthorized()
    try:
        return web.json_response({"token": await asyncio.to_thread(_token_voz), "modelo": MODELO_VOZ})
    except Exception as e:
        print(f"voz: {e}")
        return web.json_response({"error": type(e).__name__}, status=502)


async def _voz_herramienta(request):
    if not _dentro(request) or not _mismo_origen(request):
        raise web.HTTPUnauthorized()
    f = HERRAMIENTAS.get((await request.json()).get("nombre"))
    if f is None:
        raise web.HTTPBadRequest()
    return web.json_response({"resultado": await asyncio.to_thread(f)})


async def _arranque(app):
    app["panel"] = asyncio.create_task(_escucha_panel())
    app["avisos"] = asyncio.create_task(_vigila_avisos())


def main():
    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("Falta GEMINI_API_KEY (usa delta_movil.sh, que la saca de ~/.bashrc)")
    app = web.Application(client_max_size=64 * 1024)
    app.on_startup.append(_arranque)
    app.router.add_get("/", _inicio)
    app.router.add_post("/entrar", _entrar)
    app.router.add_get("/estado", _estado)
    app.router.add_post("/hablar", _hablar)
    app.router.add_post("/voz/token", _voz_token)
    app.router.add_post("/voz/herramienta", _voz_herramienta)
    app.router.add_get("/vapid", _vapid)
    app.router.add_post("/suscribir", _suscribir)
    app.router.add_get("/sw.js", lambda r: web.FileResponse(WEB / "sw.js", headers={"Cache-Control": "no-cache"}))
    for f in ("manifest.json", "icono.svg", "voz.js"):
        app.router.add_get("/" + f, lambda r, f=f: web.FileResponse(WEB / f, headers={"Cache-Control": "no-cache"}))
    app.router.add_static("/fonts", AQUI / "panel" / "fonts")
    print(f"Delta móvil en http://127.0.0.1:{PORT}")
    web.run_app(app, host="127.0.0.1", port=PORT, access_log=None, print=None)


if __name__ == "__main__":
    main()
