"""Conversación persistente con Claude Code por ACP (Agent Client Protocol).

Una sesión de Claude Code viva mientras dure el asistente: Gemini le manda mensajes,
los pasos llegan en directo a ST["claude"] (los pinta el panel) y los permisos
se preguntan al usuario por voz o con [s/N] en teclado.
"""
import asyncio
import time
from contextlib import AsyncExitStack

import acp
from acp.helpers import text_block

import acciones
import panel
from acciones import ST, WORMHOLE, avisar, _confirmar

COMANDO = ("npx", "-y", "@agentclientprotocol/claude-agent-acp")
ESPERA_PERMISO = 120  # s sin respuesta = denegar
MAX_PASOS = 8

_conn = _pila = _sid = _tarea = None
_estado = {"estado": "libre", "tarea": "", "pasos": [], "plan": [], "texto": ""}
ST["claude"] = _estado


def _paso(id_, titulo, estado="en curso"):
    for p in _estado["pasos"]:
        if p["id"] == id_:
            p["t"] = titulo or p["t"]
            p["e"] = estado
            return
    _estado["pasos"].append({"id": id_, "t": titulo or "…", "e": estado})
    del _estado["pasos"][:-MAX_PASOS]


class _Cliente:
    """Cliente ACP: sin capacidades de fichero/terminal, Claude Code usa las suyas propias."""

    def on_connect(self, conn):
        pass

    async def session_update(self, session_id, update, **kw):
        try:
            k = update.session_update
            if k == "agent_message_chunk" and getattr(update.content, "text", None):
                _estado["texto"] += update.content.text
            elif k == "tool_call":
                _paso(update.tool_call_id, update.title)
            elif k == "tool_call_update":
                est = {"completed": "hecho", "failed": "falló"}.get(str(update.status), "en curso")
                _paso(update.tool_call_id, update.title, est)
            elif k == "plan":
                _estado["plan"] = [{"t": e.content, "e": str(e.status)} for e in update.entries]
        except Exception as e:  # un evento raro nunca debe romper la conversación
            print(f"ACP update ignorado: {e}")

    async def request_permission(self, session_id, tool_call, options, **kw):
        titulo = tool_call.title or "una acción"
        previo = _estado["estado"]
        _estado["estado"] = "esperando permiso"
        _estado["permiso"] = titulo
        panel.notificar("alerta", f"Claude Code pide permiso: {titulo}")
        await avisar(f"Claude Code pide permiso para: {titulo}. Pregunta al usuario si lo permito y, cuando responda, usa responder_permiso.")
        try:
            ok = await asyncio.wait_for(_confirmar(f"Claude Code: {titulo}"), ESPERA_PERMISO)
        except asyncio.TimeoutError:
            ok = False
        finally:
            _estado["estado"] = previo
            _estado.pop("permiso", None)
        want = "allow_once" if ok else "reject_once"
        opt = next((o for o in options if str(o.kind) == want), None)
        if opt is None:
            return acp.RequestPermissionResponse(outcome={"outcome": "cancelled"})
        return acp.RequestPermissionResponse(outcome={"outcome": "selected", "optionId": opt.option_id})


async def _conectar():
    global _conn, _pila, _sid
    _pila = AsyncExitStack()
    try:
        _conn, _ = await _pila.enter_async_context(acp.spawn_agent_process(_Cliente(), *COMANDO, cwd=str(WORMHOLE)))
        await _conn.initialize(protocol_version=acp.PROTOCOL_VERSION)
        _sid = (await _conn.new_session(cwd=str(WORMHOLE))).session_id
    except BaseException:
        await cerrar()
        raise


async def cerrar():
    global _conn, _pila, _sid
    pila, _conn, _pila, _sid = _pila, None, None, None
    if pila:
        try:
            await pila.aclose()
        except Exception:
            pass


async def _turno(mensaje):
    global _tarea
    _estado.update(estado="trabajando", tarea=mensaje[:120], pasos=[], plan=[], texto="", inicio=time.time())
    try:
        if _conn is None:
            await _conectar()
        await _conn.prompt(session_id=_sid, prompt=[text_block(mensaje)])
        final = _estado["texto"].strip() or "(sin texto)"
        _estado["estado"] = "libre"
        panel.notificar("info", f"Claude Code terminó: {mensaje[:60]}")
        await avisar(f"Claude Code ha terminado. Resume al usuario en una o dos frases: {final[-1200:]}")
    except asyncio.CancelledError:
        _estado["estado"] = "libre"
        raise
    except Exception as e:
        _estado["estado"] = "libre"
        await cerrar()  # la próxima vez se reconecta
        panel.notificar("alerta", f"Claude Code falló: {e}")
        await avisar(f"Falló la conversación con Claude Code: {e}")
    finally:
        _tarea = None


# ---------- herramientas para Gemini ----------
async def hablar_con_claude(mensaje):
    global _tarea
    if _tarea and not _tarea.done():
        return f"Claude Code sigue ocupado con: {_estado['tarea']}. Espera a que termine o cancélalo."
    _tarea = asyncio.create_task(_turno(mensaje))
    return "Enviado a Claude Code. Trabaja en segundo plano, los pasos salen en el panel y te aviso al terminar. Es la misma conversación: recuerda lo anterior."


async def estado_claude():
    e = _estado
    if e["estado"] == "libre":
        return "Claude Code está libre." + (f" Última tarea: {e['tarea']}." if e["tarea"] else "")
    pasos = "; ".join(f"{p['t']} ({p['e']})" for p in e["pasos"][-4:]) or "sin pasos aún"
    return f"Claude Code está {e['estado']} con «{e['tarea']}». Últimos pasos: {pasos}."


async def cancelar_claude():
    if not (_tarea and not _tarea.done()):
        return "Claude Code no tiene nada en marcha."
    try:
        await _conn.cancel(session_id=_sid)
    except Exception:
        _tarea.cancel()
    return "Cancelación enviada a Claude Code."


async def responder_permiso(acepta):
    f = ST["pending"]
    if not f or f.done():
        return "No hay ningún permiso pendiente."
    f.set_result("s" if str(acepta).strip().lower() in ("si", "sí", "s", "true", "yes", "sí.") else "n")
    return "Respuesta enviada."


# ---------- registro en acciones ----------
acciones.registrar([
    acciones._fn("hablar_con_claude",
                 "Conversa con Claude Code (el agente de código, repo WORMHOLE). Es UNA conversación persistente: recuerda lo anterior, "
                 "así que puedes pedir seguimientos («ahora hazlo más grueso»). Trabaja en segundo plano y avisa al terminar. "
                 "Úsala para toda petición de código, CAD o archivos del repo.",
                 {"mensaje": acciones._s("lo que quieres decirle a Claude Code, completo y claro")}),
    acciones._fn("estado_claude", "Qué está haciendo Claude Code ahora y sus últimos pasos."),
    acciones._fn("cancelar_claude", "Interrumpe la tarea actual de Claude Code."),
    acciones._fn("responder_permiso",
                 "Contesta a un permiso que Claude Code o el sistema ha pedido al usuario, con lo que el usuario haya dicho.",
                 {"acepta": acciones._s("«si» o «no»")}),
], (hablar_con_claude, estado_claude, cancelar_claude, responder_permiso))
