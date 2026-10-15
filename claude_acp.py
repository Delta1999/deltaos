"""Conversación persistente con Claude Code por ACP (Agent Client Protocol).

Una sesión de Claude Code viva mientras dure el asistente: Gemini le manda mensajes,
los pasos llegan en directo a ST["claude"] (los pinta el panel) y los permisos
se preguntan al usuario por voz o con [s/N] en teclado.
"""
import asyncio
import json
import os
import time
from contextlib import AsyncExitStack

import acp
from acp.helpers import text_block

import acciones
import panel
from acciones import ST, WORMHOLE, AQUI, avisar, _confirmar, _run

COMANDO = ("npx", "-y", "@agentclientprotocol/claude-agent-acp")
MAX_PASOS = 8

_conn = _pila = _sid = _sid_delta = _tarea = None
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
            ok = await _confirmar(f"Claude Code: {titulo}", voz=True)
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
        _conn, _ = await _pila.enter_async_context(acp.spawn_agent_process(
            _Cliente(), *COMANDO, cwd=str(WORMHOLE), env={**os.environ, "DELTA_ORIGEN": "1"}))
        await _conn.initialize(protocol_version=acp.PROTOCOL_VERSION)
        _sid = (await _conn.new_session(cwd=str(WORMHOLE))).session_id
    except BaseException:
        await cerrar()
        raise


async def cerrar():
    global _conn, _pila, _sid, _sid_delta
    pila, _conn, _pila, _sid, _sid_delta = _pila, None, None, None, None
    if pila:
        try:
            await pila.aclose()
        except Exception:
            pass


async def _turno(mensaje, propio=None, voz=True):
    """propio = (petición, foto «antes») cuando es un cambio en el propio Delta: otra sesión, con el repo de Delta como cwd."""
    global _tarea, _sid_delta
    _estado.update(estado="trabajando", tarea=(propio[0] if propio else mensaje)[:120], pasos=[], plan=[], texto="", inicio=time.time())
    try:
        if _conn is None:
            await _conectar()
        if propio and _sid_delta is None:
            _sid_delta = (await _conn.new_session(cwd=str(AQUI))).session_id
            try:  # editar sin preguntar cada archivo: el registro guarda el diff para deshacerlo
                await _conn.set_session_mode(session_id=_sid_delta, mode_id="acceptEdits")
            except Exception as e:
                print(f"ACP: sin modo acceptEdits ({e})")
        await _conn.prompt(session_id=_sid_delta if propio else _sid, prompt=[text_block(mensaje)])
        final = _estado["texto"].strip() or "(sin texto)"
        if propio:
            await _registrar(propio[0], propio[1], final)
        _estado.update(estado="libre", ultimo="hecho")
        panel.notificar("info", f"Claude Code terminó: {(propio[0] if propio else mensaje)[:60]}")
        if voz:
            await avisar(f"Claude Code ha terminado. Resume al usuario en una o dos frases: {final[-1200:]}")
    except asyncio.CancelledError:
        _estado["estado"] = "libre"
        raise
    except Exception as e:
        _estado.update(estado="libre", ultimo="falló")
        await cerrar()  # la próxima vez se reconecta
        panel.notificar("alerta", f"Claude Code falló: {e}")
        if voz:
            await avisar(f"Falló la conversación con Claude Code: {e}")
    finally:
        _tarea = None


# ---------- cambios en el propio Delta: pasarela Gemini Live → Claude Code, con registro ----------
REGISTRO = AQUI / "CAMBIOS_DELTA.md"
PROPIO = (
    "[PETICIÓN DESDE DELTA · pasarela Gemini Live → Claude Code] El usuario ha pedido por voz a Delta este cambio en el "
    "propio Delta. Trabaja SOLO en este repositorio (~/gemini-live-assistant), sobre sus archivos de verdad: nada de copias, "
    "forks, carpetas ni proyectos paralelos. Lee CLAUDE.md antes. No reinicies Delta (eres un proceso suyo y morirías con "
    "él) ni hagas commits. Al terminar di en dos frases qué has cambiado y si hace falta reiniciar Delta o basta con "
    "recargar el panel.\n\nPetición: "
)


async def _foto():
    """Instantánea del árbol de trabajo sin tocarlo (git stash create); vale HEAD si no hay cambios."""
    c, h = await _run(["git", "-C", str(AQUI), "stash", "create"], timeout=30)
    if c or not h.strip():
        _, h = await _run(["git", "-C", str(AQUI), "rev-parse", "HEAD"], timeout=30)
    _, nuevos = await _run(["git", "-C", str(AQUI), "ls-files", "--others", "--exclude-standard"], timeout=30)
    return h.strip(), set(nuevos.split())


async def _registrar(peticion, antes, final):
    despues = await _foto()
    marca = time.strftime("%Y%m%d-%H%M%S")
    for n, h in (("antes", antes[0]), ("despues", despues[0])):  # refs: que git no borre las fotos
        await _run(["git", "-C", str(AQUI), "update-ref", f"refs/delta/{marca}/{n}", h], timeout=30)
    _, stat = await _run(["git", "-C", str(AQUI), "diff", "--stat", antes[0], despues[0]], timeout=30)
    nuevos = sorted(despues[1] - antes[1])
    with REGISTRO.open("a") as f:
        f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')} · vía Delta (Gemini Live → Claude Code)\n\n"
                f"**Petición:** {peticion}\n\n**Claude:** {final[-800:]}\n\n```\n{stat.strip() or '(sin cambios en archivos con seguimiento)'}\n```\n"
                + (f"Archivos nuevos: {', '.join(nuevos)}\n" if nuevos else "")
                + f"\nVer: `git diff refs/delta/{marca}/antes refs/delta/{marca}/despues` · "
                  f"Deshacer: `git diff refs/delta/{marca}/antes refs/delta/{marca}/despues | git apply -R`\n")
    try:  # y en las novedades del panel, para verlo al tocar la hora
        nov = AQUI / "panel" / "novedades.json"
        lista = json.loads(nov.read_text())
        lista.insert(0, {"f": time.strftime("%Y-%m-%d"), "t": peticion[:200], "como": "vía Delta → Claude"})
        nov.write_text(json.dumps(lista, ensure_ascii=False, indent=1))
    except Exception as e:
        print(f"novedades: {e}")


def ocupado():
    return bool(_tarea and not _tarea.done())


async def mejorar_delta(peticion, voz=True):
    """voz=False: arreglos de la llave inglesa, que se lanzan solos con el PC libre y no deben despertar a Delta."""
    global _tarea
    if ocupado():
        return f"Claude Code sigue ocupado con: {_estado['tarea']}. Espera a que termine o cancélalo."
    antes = await _foto()
    _tarea = acciones.tarea(_turno(PROPIO + peticion, (peticion, antes), voz))
    return ("Enviado a Claude Code, que trabaja sobre el propio repositorio de Delta. Los pasos salen en el panel, "
            "queda registrado en CAMBIOS_DELTA.md y te aviso al terminar.")


# ---------- herramientas para Gemini ----------
async def hablar_con_claude(mensaje):
    global _tarea
    if _tarea and not _tarea.done():
        return f"Claude Code sigue ocupado con: {_estado['tarea']}. Espera a que termine o cancélalo."
    _tarea = acciones.tarea(_turno(mensaje))
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
    if not f.voz:
        return "Este permiso solo se puede dar con el teclado o el botón del panel. Díselo al usuario."
    if ST.get("t_tu", 0) <= f.t0:  # lo que hay en pantalla no puede dar permiso: tiene que hablar el usuario
        return "El usuario aún no ha contestado de viva voz. Pregúntale y espera a que hable."
    f.set_result("s" if str(acepta).strip().lower() in ("si", "sí", "s", "true", "yes", "sí.") else "n")
    return "Respuesta enviada."


# ---------- registro en acciones ----------
acciones.registrar([
    acciones._fn("hablar_con_claude",
                 "Conversa con Claude Code (el agente de código, repo WORMHOLE). Es UNA conversación persistente: recuerda lo anterior, "
                 "así que puedes pedir seguimientos («ahora hazlo más grueso»). Trabaja en segundo plano y avisa al terminar. "
                 "Úsala para toda petición de código, CAD o archivos del repo.",
                 {"mensaje": acciones._s("lo que quieres decirle a Claude Code, completo y claro")}),
    acciones._fn("mejorar_delta",
                 "Cambia, mejora o arregla el PROPIO Delta (tu interfaz, panel, DeltaOS, mascota, voz, herramientas, "
                 "fondos…) llamando a Claude Code sobre tu repositorio. Úsala cuando el usuario pida modificar algo de tu "
                 "sistema («cambia el panel para…», «añádete…», «arregla tu…»). Queda registrado para poder deshacerlo.",
                 {"peticion": acciones._s("lo que hay que cambiar, completo y con las palabras del usuario")}),
    acciones._fn("estado_claude", "Qué está haciendo Claude Code ahora y sus últimos pasos."),
    acciones._fn("cancelar_claude", "Interrumpe la tarea actual de Claude Code."),
    acciones._fn("responder_permiso",
                 "Contesta a un permiso que Claude Code o el sistema ha pedido al usuario, con lo que el usuario haya dicho.",
                 {"acepta": acciones._s("«si» o «no»")}),
], (hablar_con_claude, mejorar_delta, estado_claude, cancelar_claude, responder_permiso))
