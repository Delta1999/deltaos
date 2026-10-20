"""Puente MCP: cualquier servidor MCP se vuelve una capacidad de Delta sin escribir código.

MCP (Model Context Protocol) es el enchufe estándar entre un modelo y un servicio: el servidor
declara qué herramientas tiene y con qué argumentos, y el cliente las llama. Aquí Delta es el
cliente, así que un conector nuevo (calendario, correo, lo que venga) es una entrada en mcp.json
y no código nuevo.

Expone DOS herramientas a Gemini, no una por servidor: el presupuesto está lleno y el 19/10 hubo
que fusionar 55 herramientas en 12 porque el modelo se confundía (ver acciones.FUSIONES).
  conectores(accion="listar")                                   → qué conectores hay y qué saben hacer
  conectores(accion="usar", servidor, herramienta, argumentos)  → ejecuta una

Las credenciales NO van en mcp.json: van por variables de entorno (campo "env", que lee del
entorno de Delta). mcp.json sí se commitea; un .env no.
"""
import asyncio
import json
import os
import shlex
from pathlib import Path

from mcp import ClientSessionGroup, StdioServerParameters
from mcp.client.session_group import StreamableHttpParameters

import acciones
from acciones import AQUI

CONFIG = AQUI / "mcp.json"
ESPERA = 60.0      # s máximos que se le dan a una herramienta de un conector
ARRANQUE = 30.0    # s máximos para que un servidor conteste al arrancar
MAX_SALIDA = 4000  # lo que se le pasa al modelo de una respuesta (hay servidores muy verbosos)

_grupo = None        # ClientSessionGroup vivo; lo abre y lo sostiene vigilar()
_listo = asyncio.Event()
_fallos: dict = {}   # servidor → por qué no arrancó
_conectando = ""     # servidor que se está conectando ahora (lo usa _nombrar)


def _config():
    """mcp.json → {nombre: cfg}. Un fichero roto no tumba Delta: se queda sin conectores y lo dice."""
    if not CONFIG.exists():
        return {}
    try:
        d = json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"🔌 mcp.json ilegible ({e}): Delta arranca sin conectores")
        return {}
    return {k: v for k, v in d.items() if isinstance(v, dict) and not k.startswith("_")}


def _parametros(cfg):
    """cfg → parámetros del transporte. «comando» = servidor local por stdio; «url» = remoto por HTTP."""
    if cfg.get("url"):
        return StreamableHttpParameters(url=cfg["url"], headers=cfg.get("cabeceras") or None)
    comando = cfg.get("comando")
    if not comando:
        raise ValueError('necesita "comando" (servidor local) o "url" (remoto)')
    argv = shlex.split(comando) if isinstance(comando, str) else list(comando)
    # Solo las variables que pida, tomadas del entorno de Delta: así las claves no viven en mcp.json.
    env = {k: os.environ[k] for k in cfg.get("env", []) if k in os.environ}
    faltan = [k for k in cfg.get("env", []) if k not in os.environ]
    if faltan:
        raise ValueError(f"faltan variables de entorno: {', '.join(faltan)}")
    return StdioServerParameters(command=argv[0], args=argv[1:], env={**os.environ, **env} or None,
                                 cwd=cfg.get("cwd"))


def _nombrar(nombre, _info):
    """Las herramientas se aplanan en un catálogo común: se les pone delante el servidor de mcp.json
    (no el nombre que se da el servidor a sí mismo, que no tiene por qué coincidir)."""
    return f"{_conectando}.{nombre}"


async def vigilar():
    """Mantiene las sesiones MCP vivas mientras dure Delta.

    Una sola tarea las abre y las cierra: los flujos de anyio que usa el SDK no admiten que el
    context manager se cierre en una tarea distinta de la que lo abrió. Las llamadas sí pueden
    venir de otras tareas (la sesión MCP admite peticiones concurrentes).
    """
    global _grupo, _conectando
    activos = {n: c for n, c in _config().items() if c.get("activo", True)}
    if not activos:
        _listo.set()
        return
    try:
        async with ClientSessionGroup(component_name_hook=_nombrar) as g:
            _grupo = g
            for nombre, cfg in activos.items():
                _conectando = nombre
                try:
                    await asyncio.wait_for(g.connect_to_server(_parametros(cfg)), ARRANQUE)
                except Exception as e:
                    _fallos[nombre] = f"{type(e).__name__}: {e}"[:200]
                    print(f"🔌 conector {nombre}: ⚠️ no arrancó — {_fallos[nombre]}")
                else:
                    print(f"🔌 conector {nombre}: OK ({(n := sum(1 for t in g.tools if t.startswith(nombre + ".")))} herramienta{"s" if n != 1 else ""})")
            _conectando = ""
            _listo.set()
            await asyncio.Event().wait()  # vive hasta que muera Delta
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"🔌 puente MCP caído: {type(e).__name__}: {e}")
    finally:
        _grupo = None
        _listo.set()


def _catalogo():
    """{servidor: [(herramienta, descripción)]} de lo que hay conectado ahora."""
    por_servidor: dict = {}
    for clave, t in (_grupo.tools if _grupo else {}).items():
        servidor, _, corto = clave.partition(".")
        desc = (getattr(t, "description", "") or "").strip().replace("\n", " ")
        por_servidor.setdefault(servidor, []).append((corto, desc[:120]))
    return por_servidor


def _texto(r):
    """CallToolResult → texto plano para el modelo."""
    partes = []
    for c in getattr(r, "content", None) or []:
        t = getattr(c, "text", None)
        partes.append(t if t is not None else f"[{getattr(c, 'type', 'contenido')}]")
    s = "\n".join(p for p in partes if p).strip()
    if not s and getattr(r, "structuredContent", None):
        s = json.dumps(r.structuredContent, ensure_ascii=False)
    s = s or "(el conector no devolvió nada)"
    return s[:MAX_SALIDA] + ("…" if len(s) > MAX_SALIDA else "")


def _detallar(clave):
    """acciones.atender() ya creó el paso del panel, pero con la etiqueta genérica («Uso un conector ·
    usar»): se le pone qué conector y qué herramienta. Sin crear otro paso, que el recuadro tiene 7."""
    pasos = acciones.ST.get("pasos") or []
    if pasos and pasos[-1]["t"].startswith(acciones.ETIQUETAS["conectores"]):
        pasos[-1]["t"] = f"{acciones.ETIQUETAS['conectores']} · {clave.replace('.', ': ')}"


async def conectores(accion, servidor="", herramienta="", argumentos=""):
    await _listo.wait()
    cat = _catalogo()

    if accion == "listar":
        if not cat:
            if _fallos:
                return "No hay conectores en marcha. Fallaron: " + "; ".join(f"{k} ({v})" for k, v in _fallos.items())
            return "No hay ningún conector configurado todavía (mcp.json está vacío)."
        lineas = [f"{s}: " + " · ".join(f"{n} — {d}" if d else n for n, d in hs) for s, hs in cat.items()]
        if _fallos:
            lineas.append("No arrancaron: " + "; ".join(f"{k} ({v})" for k, v in _fallos.items()))
        return "\n".join(lineas)

    if accion != "usar":
        return "Error: conectores necesita accion = listar | usar"

    if not herramienta:
        return "Error: usar necesita herramienta (mírala primero con accion=listar)"
    # El modelo a veces manda «servidor.herramienta» entero en herramienta: se acepta igual.
    clave = herramienta if "." in herramienta else f"{servidor}.{herramienta}"
    if clave not in (_grupo.tools if _grupo else {}):
        candidatas = [k for k in (_grupo.tools if _grupo else {}) if k.endswith("." + herramienta)]
        if len(candidatas) != 1:
            return (f"Error: no existe la herramienta «{clave}». Hay: "
                    + "; ".join(f"{s}: {', '.join(n for n, _ in hs)}" for s, hs in cat.items()))
        clave = candidatas[0]

    if isinstance(argumentos, dict):
        args = argumentos
    elif not str(argumentos).strip():
        args = {}
    else:
        try:
            args = json.loads(argumentos)
        except json.JSONDecodeError as e:
            return f'Error: argumentos tiene que ser un objeto JSON, p.ej. {{"dias": 7}} ({e})'
        if not isinstance(args, dict):
            return 'Error: argumentos tiene que ser un objeto JSON, p.ej. {"dias": 7}'

    _detallar(clave)
    try:
        r = await _grupo.call_tool(clave, args, read_timeout_seconds=ESPERA)
    except asyncio.TimeoutError:
        return f"Error: {clave} no contestó en {ESPERA:.0f} s"
    except Exception as e:
        return f"Error al usar {clave}: {type(e).__name__}: {e}"
    salida = _texto(r)
    return f"Error del conector {clave}: {salida}" if getattr(r, "isError", False) else salida


acciones.ETIQUETAS["conectores"] = "Uso un conector"
acciones.registrar([
    acciones._fn("conectores",
                 "Servicios externos enchufados a Delta por MCP (calendario, correo y lo que se añada). "
                 "listar: qué conectores hay y qué herramientas tiene cada uno; úsalo ANTES de la primera vez, "
                 "para saber el nombre exacto y qué argumentos pide. usar: ejecuta una de esas herramientas. "
                 "Si listar dice que no hay ninguno, no es un fallo tuyo: aún no se ha configurado.",
                 {"accion": acciones._s("listar | usar"),
                  "servidor": acciones._s("usar: el conector, tal como lo dio listar (p.ej. calendario)"),
                  "herramienta": acciones._s("usar: la herramienta, tal como la dio listar"),
                  "argumentos": acciones._s('usar: objeto JSON con los argumentos que pida esa herramienta, '
                                            'p.ej. {"dias": 7}; vacío si no pide ninguno')},
                 req=["accion"]),
], (conectores,))
