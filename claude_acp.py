"""Conversación persistente con Claude Code por ACP (Agent Client Protocol).

Una sesión de Claude Code viva mientras dure el asistente: Gemini le manda mensajes,
los pasos llegan en directo a ST["claude"] (los pinta el panel); sus permisos se dan siempre solos,
sin preguntar ni avisar al usuario.
"""
import asyncio
import json
import os
import re
import shlex
import time
from contextlib import AsyncExitStack

import acp
from acp.helpers import text_block

import acciones
import panel
import revision_delta
from acciones import ST, WORMHOLE, AQUI, avisar, _confirmar, _run

COMANDO = ("npx", "-y", "@agentclientprotocol/claude-agent-acp")
# ~/.claude/settings.json manda Claude Code a OmniRoute; las sesiones del selector y la revisión (30/10/2026) van directas a
# Claude con el login de `claude auth login`: los ajustes programáticos de la sesión pisan ese env.
CLAUDE_REAL = {"claudeCode": {"options": {"settings": {"env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com", "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_API_KEY": "", "ANTHROPIC_MODEL": ""}}}}}
MAX_PASOS = 8
# Claude Code solo MIRANDO (leer, buscar, ver estado) nunca pregunta al usuario: lo pidió así
MIRA = acciones.LECTURA | {"cd", "sed", "git", "sleep", "timeout", "tree", "diff", "jq", "realpath", "basename", "dirname",
                           "readlink", "nl", "printf", "true", "test", "[", "for", "done", "fi"}
GIT_MIRA = {"status", "log", "diff", "show", "ls-files", "rev-parse", "blame", "grep", "shortlog", "describe"}
CLAVE_SH = {"do", "then", "else", "if", "while", "until", "!"}
SALIDA_NULA = re.compile(r"\s*(\d?>\s*/dev/null|\d?>&\d)")


def solo_mira(comando):
    """True si el comando de shell solo lee (programas de MIRA en tuberías/&&/;/bucles), sin escribir ni ejecutar código."""
    c = SALIDA_NULA.sub(" ", comando)
    if re.search(r"[<>`]|\$\(", c):
        return False
    lex = shlex.shlex(c, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        toks = list(lex)
    except ValueError:
        return False
    tramos, actual = [], []
    for t in toks:
        if t in ("|", "&&", "||", ";", "\n"):
            tramos.append(actual); actual = []
        elif set(t) <= set("|&;()"):
            return False
        else:
            actual.append(t)
    tramos.append(actual)
    for t in tramos:
        while t and t[0] in CLAVE_SH:
            t = t[1:]
        while t and t[0] == "timeout":  # «timeout 60 grep …»: manda lo que viene detrás
            t = [a for a in t[1:] if not a.startswith("-")][1:]
        if not t:
            continue
        prog, args = t[0], t[1:]
        if prog not in MIRA or any(a.startswith(p) for a in args for p in acciones.PROHIBIDO.get(prog, ()) if prog != "grep"):
            return False
        if prog == "sed" and any(a.startswith(("-i", "--in-place")) or re.search(r"(^|[;/}])\s*[wWe]\b", a) for a in args):
            return False
        if prog == "git" and not (args and args[0] in GIT_MIRA):
            return False
        if prog in acciones.SUBORDEN and not set(args) & acciones.SUBORDEN[prog]:
            return False
    return True


def solo_lectura(tool_call):
    kind = str(tool_call.kind or "")
    if kind in ("read", "search", "fetch", "think"):
        return True
    cmd = (tool_call.raw_input or {}).get("command") if isinstance(tool_call.raw_input, dict) else None
    return kind == "execute" and solo_mira(cmd or (tool_call.title or "").strip("`"))

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
        # Claude Code nunca le pide permiso al usuario: se da solo y sin decir nada (lo pidió el 2026-10-19,
        # «claude está en modo omitir permisos»). Solo se distingue en el log lo que es mirar.
        titulo = tool_call.title or "una acción"
        print(f"\n{'👀 Claude Code mira' if solo_lectura(tool_call) else '🤖 Claude Code hace'} sin preguntar: {titulo}")
        opt = next((o for o in options if str(o.kind) == "allow_once"), None) \
            or next((o for o in options if str(o.kind).startswith("allow")), None)
        if opt is None:
            return acp.RequestPermissionResponse(outcome={"outcome": "cancelled"})
        return acp.RequestPermissionResponse(outcome={"outcome": "selected", "optionId": opt.option_id})


async def _conectar():
    global _conn, _pila, _sid
    _pila = AsyncExitStack()
    try:
        # Sin ANTHROPIC_*: las heredadas del arranque (clave de OmniRoute/Gemini) hacen que el adaptador ACP
        # falle con «Authentication required» (29/10/2026); sin ellas usa el inicio de sesión de Claude Code.
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
        _conn, _ = await _pila.enter_async_context(acp.spawn_agent_process(
            _Cliente(), *COMANDO, cwd=str(WORMHOLE), env={**env, "DELTA_ORIGEN": "1"}))
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


async def _turno(mensaje, propio=None, voz=True, nueva=None):
    """propio = (petición, foto «antes») cuando es un cambio en el propio Delta: otra sesión, con el repo de Delta como cwd.
    nueva = lo que ve el usuario como tarea cuando es una conversación nueva (selector de la pantalla Agentes): sesión ACP nueva."""
    global _tarea, _sid, _sid_delta
    cab = propio[0] if propio else (nueva or mensaje)
    _estado.update(estado="trabajando", tarea=cab[:120], pasos=[], plan=[], texto="", inicio=time.time(),
                   auto=acciones.autorizado())  # encargada por Claude Code: sus permisos se dan solos hasta que acabe
    try:
        if _conn is None:
            await _conectar()
        if propio and _sid_delta is None:
            _sid_delta = (await _conn.new_session(cwd=str(AQUI))).session_id
            try:  # editar sin preguntar cada archivo: el registro guarda el diff para deshacerlo
                await _conn.set_session_mode(session_id=_sid_delta, mode_id="acceptEdits")
            except Exception as e:
                print(f"ACP: sin modo acceptEdits ({e})")
        if nueva and not propio:
            _sid = (await _conn.new_session(cwd=str(WORMHOLE), **CLAUDE_REAL)).session_id
        await _conn.prompt(session_id=_sid_delta if propio else _sid, prompt=[text_block(mensaje)])
        final = _estado["texto"].strip() or "(sin texto)"
        if LIMITE.search(final):  # límite de tokens o sesión de Claude Code
            raise RuntimeError(f"Límite de tokens de Claude Code alcanzado: {final[:160]}")
        rev = ""
        if propio:
            despues = await _registrar(propio[0], propio[1], final)
            rev = await _revisar(propio[0], propio[1], despues)
        _estado.update(estado="libre", ultimo="hecho")
        panel.notificar("alerta" if rev and "VERDE" not in rev[:40] else "info", f"Claude Code terminó: {cab[:60]}" + (f" · {rev[:90]}" if rev else ""))
        if voz:
            await avisar(f"Claude Code ha terminado. Resume al usuario en una o dos frases: {final[-1200:]}"
                         + (f"\n{rev}\nDi también el veredicto de la revisión (verde o roja) y, si es roja o no hay veredicto, el motivo." if rev else ""),
                         movil=f"Claude Code ha terminado: {cab[:80]}" + (f" ({rev[:60]})" if rev else ""))
    except asyncio.CancelledError:
        _estado["estado"] = "libre"
        raise
    except Exception as e:
        _estado.update(estado="libre", ultimo="falló")
        await cerrar()  # la próxima vez se reconecta
        panel.notificar("alerta", f"Claude Code falló: {e}")
        guardada = ""
        es_limite = bool(LIMITE.search(str(e)))
        if propio:  # que no se pierda: al buzón que Claude revisa al ponerse con Delta
            await acciones.anotar_mejora(propio[0])
            if es_limite:
                await acciones.mejorar_delta_cherry(f"[Fallback falta de tokens en Claude] {propio[0]}")
                guardada = (" Claude Code no tiene tokens. La petición ha quedado anotada en cherry_pendientes.txt "
                            "para que Cherry se encargue de ella.")
            else:
                guardada = " La petición ha quedado anotada en el registro de averías y mejoras, así que no se pierde."
        elif es_limite:
            guardada = " Claude Code no tiene tokens. Puedes pedirme que se lo pase a Cherry diciendo «dile a Cherry que...»."
        if voz:
            await avisar(f"Falló la conversación con Claude Code: {e}.{guardada}")
    finally:
        _tarea = None
        _estado["auto"] = False


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
    return despues


REVISION_MAX = 300  # s que se le dan al revisor antes de dejar el cambio «sin veredicto»


async def _revisar(peticion, antes, despues):
    """Revisión independiente del cambio recién hecho (sesión ACP nueva, solo petición + diff): devuelve una línea
    «Revisión independiente: VERDE|ROJA|SIN VEREDICTO — …» que también queda en el registro, o "" si no hubo cambios."""
    nuevos = sorted(despues[1] - antes[1])
    if antes[0] == despues[0] and not nuevos:
        return ""
    tarea_antes = _estado["tarea"]
    try:
        ver = f"git diff {antes[0]} {despues[0]}"
        _, diff = await _run(["git", "-C", str(AQUI)] + ver.split()[1:], timeout=30)
        ficheros = []
        for n in nuevos[:5]:
            try:
                ficheros.append((n, (AQUI / n).read_text(errors="replace")[:revision_delta.MAX_NUEVO]))
            except OSError:
                pass
        _estado.update(tarea=f"Revisión independiente: {peticion[:90]}", pasos=[], plan=[], texto="")
        sid = (await _conn.new_session(cwd=str(AQUI), **CLAUDE_REAL)).session_id
        try:  # que el revisor no pueda editar
            await _conn.set_session_mode(session_id=sid, mode_id="plan")
        except Exception as e:
            print(f"ACP revisión: sin modo plan ({e})")
        try:
            await asyncio.wait_for(_conn.prompt(session_id=sid, prompt=[text_block(revision_delta.prompt(peticion, diff, ficheros, ver))]),
                                   REVISION_MAX)
            v, detalle = revision_delta.veredicto(_estado["texto"])
        except asyncio.TimeoutError:
            await _conn.cancel(session_id=sid)
            v, detalle = None, f"el revisor tardó más de {REVISION_MAX} s"
        detalle = re.sub(r"\s+", " ", detalle).strip()
        linea = f"Revisión independiente: {v or 'SIN VEREDICTO'}" + (f" — {detalle[:500]}" if detalle else "")
    except Exception as e:  # una revisión que falla nunca tumba el cambio ya hecho
        linea = f"Revisión independiente: SIN VEREDICTO — no se pudo revisar ({e})"
    finally:
        _estado["tarea"] = tarea_antes
    try:
        with REGISTRO.open("a") as f:
            f.write(f"\n**{linea}**\n")
    except OSError as e:
        print(f"registro de revisión: {e}")
    return linea


def ocupado():
    return bool(_tarea and not _tarea.done())


async def mejorar_delta(peticion, voz=True):
    """voz=False: arreglos de la llave inglesa, que se lanzan solos con el PC libre y no deben despertar a Delta."""
    global _tarea
    if re.search(r"\bcherry\b", peticion, re.I):
        return await acciones.mejorar_delta_cherry(peticion)
    if ocupado():
        await acciones.anotar_mejora(peticion)
        return (f"Claude Code sigue ocupado con: {_estado['tarea']}. La petición queda anotada en el registro de averías y "
                "mejoras, para que no se pierda; si corre prisa, pídela otra vez cuando acabe.")
    antes = await _foto()
    _tarea = acciones.tarea(_turno(PROPIO + peticion, (peticion, antes), voz))
    return ("Enviado a Claude Code, que trabaja sobre el propio repositorio de Delta. Los pasos salen en el panel, "
            "queda registrado en CAMBIOS_DELTA.md y te aviso al terminar.")


# ---------- herramientas para Gemini ----------
LIMITE = re.compile(r"hit your .{0,20}limit|session limit|usage limit|rate limit|l[ií]mite de (uso|sesi[oó]n)", re.I)
# Lo del propio Delta que llega por «hablar» (el repo WORMHOLE) se desvía a mejorar_delta (21/10: el usuario dice
# «díselo a Claude» y Delta elegía el Claude equivocado).
DE_DELTA = re.compile(r"\bdelta(os)?\b|barra de estado|\bescudo\b|tu (panel|interfaz|voz|barra)|aver[ií]as?\b|"
                      r"mejoras? (de|para|pendientes)", re.I)


async def hablar_con_claude(mensaje):
    global _tarea
    if re.search(r"\bcherry\b", mensaje, re.I):
        return await acciones.mejorar_delta_cherry(mensaje)
    if DE_DELTA.search(mensaje):
        return await mejorar_delta(mensaje) + " (Era del propio Delta: lo he mandado a su repositorio, no a WORMHOLE.)"
    if _tarea and not _tarea.done():
        return f"Claude Code sigue ocupado con: {_estado['tarea']}. Espera a que termine o cancélalo."
    _tarea = acciones.tarea(_turno(mensaje))
    return "Enviado a Claude Code. Trabaja en segundo plano, los pasos salen en el panel y te aviso al terminar. Es la misma conversación: recuerda lo anterior."


async def nueva_conversacion(instruccion, texto):
    """Conversación nueva con Claude Code (sesión ACP nueva): `instruccion` es el arranque del modo o agente elegido."""
    global _tarea
    if ocupado():
        return f"Claude Code sigue ocupado con: {_estado['tarea']}. Espera a que termine o cancélalo."
    _tarea = acciones.tarea(_turno(f"{texto}\n\n[Modo de trabajo pedido por el usuario] {instruccion}", nueva=texto, voz=False))
    return "Conversación nueva enviada a Claude Code. Los pasos salen en esta pantalla."


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
                 "Cambia, mejora o arregla el PROPIO Delta (tu interfaz, panel, DeltaOS, voz, herramientas, "
                 "fondos…) llamando a Claude Code sobre tu repositorio. Úsala cuando el usuario pida modificar algo de tu "
                 "sistema («cambia el panel para…», «añádete…», «arregla tu…»). Queda registrado para poder deshacerlo.",
                 {"peticion": acciones._s("lo que hay que cambiar, completo y con las palabras del usuario")}),
    acciones._fn("estado_claude", "Qué está haciendo Claude Code ahora y sus últimos pasos."),
    acciones._fn("cancelar_claude", "Interrumpe la tarea actual de Claude Code."),
    acciones._fn("responder_permiso",
                 "Contesta a un permiso que Claude Code o el sistema ha pedido al usuario, con lo que el usuario haya dicho.",
                 {"acepta": acciones._s("«si» o «no»")}),
], (hablar_con_claude, mejorar_delta, estado_claude, cancelar_claude, responder_permiso))
