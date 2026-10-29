"""Modo teclado de DeltaOS: escribirle a Delta en vez de hablarle, con un modelo de OmniRoute (ahorra tokens de voz de Gemini Live).

Usa las mismas herramientas que Delta (acciones.DECLARATIONS/HANDLERS), así que puede hacer lo mismo que por voz. Lo que escribe el
usuario llega por el WebSocket del panel (Origin comprobado, nunca desde la tele): no es «de viva voz», así que lo que pide permiso
lo sigue pidiendo (acciones.hablando_contigo no cuenta el teclado). La búsqueda en Google sigue siendo la de Delta (API de Gemini):
no se ha comprobado que el grounding pase por OmniRoute.

Solo LEE de la base de OmniRoute (SQLite en modo solo lectura) para el panel de consumo; la clave nunca se imprime ni se difunde.
"""
import asyncio
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp

import acciones
import panel

AQUI = Path(__file__).resolve().parent
BASE = os.environ.get("OMNIROUTE_URL", "http://localhost:20128").rstrip("/")
BD = Path.home() / ".omniroute" / "storage.sqlite"
ENV_OMNI = Path.home() / ".config" / "omniroute" / ".env"
USO = AQUI / "teclado_uso.jsonl"
DEFECTO = "combo-fast-completion"  # gemini-3.8-flash-high (antigravity) → DeepSeek V4.1 Flash → Haiku 4.5 → Gemini 3.1 Flash-Lite…
MAX_VUELTAS = 6   # idas y vueltas con herramientas por orden: cada una gasta una petición del cupo de antigravity (~1000/semana)
MAX_HIST = 12     # mensajes de conversación que se reenvían (solo texto; lo que devolvieron las herramientas no se guarda)
OLVIDA = 1800     # s sin escribir: conversación nueva
TIMEOUT = 150

# cupo = (proveedor, recurso) de la cuota que gasta, tal como la guarda OmniRoute; None = sin cuota medida (de pago o gratis sin contador)
MODELOS = [
    {"id": DEFECTO, "corto": "interfaz, informes, órdenes básicas", "nombre": "Gemini 3.8 Flash · antigravity (con respaldo)",
     "bueno": "Lo básico: manejar la interfaz, informes, órdenes sencillas. Si falla pasa a DeepSeek V4.1 Flash, Haiku 4.5 y Gemini Flash-Lite.",
     "cupo": ("antigravity", "gemini_weekly")},
    {"id": "antigravity/gemini-3.8-flash-high", "corto": "lo básico, sin respaldo", "nombre": "Gemini 3.8 Flash · solo antigravity",
     "bueno": "Rápido y con 1M de contexto; igual que el anterior pero sin respaldo (si se agota el cupo, falla).",
     "cupo": ("antigravity", "gemini_weekly")},
    {"id": "orcarouter/deepseek/deepseek-v4.1-flash-free", "corto": "tareas ligeras gratis", "nombre": "DeepSeek V4.1 Flash · gratis (OrcaRouter)",
     "bueno": "Tareas ligeras sin gastar cupo. Solo 128K de contexto; sus límites reales no están comprobados.", "cupo": None},
    {"id": "orcarouter/z-ai/glm-5.3-flash-free", "corto": "preguntas y resúmenes gratis", "nombre": "GLM-5.3 Flash · gratis (OrcaRouter)",
     "bueno": "Preguntas y resúmenes sencillos gratis. 128K de contexto; límites sin comprobar.", "cupo": None},
    {"id": "cheaperinference/glm-5.3", "corto": "razonar y usar herramientas", "nombre": "GLM-5.3 (CheaperInference)",
     "bueno": "Razonar y manejar herramientas con calidad cercana a lo mejor abierto; 1M de contexto; se paga por token.", "cupo": None},
    {"id": "orcarouter/kimi/kimi-k3", "corto": "agente y textos largos", "nombre": "Kimi K3 (OrcaRouter)",
     "bueno": "Agente con muchas herramientas y textos largos; 128K por esta vía; se paga por token.", "cupo": None},
    {"id": "codex/gpt-6-luna", "corto": "razonamiento y código", "nombre": "GPT-6 Luna · Codex",
     "bueno": "Razonamiento y código cuando lo básico se queda corto. Gasta el cupo mensual de Codex.", "cupo": ("codex", "session")},
    {"id": "grok-cli/grok-4.7", "corto": "contexto enorme, respuestas directas", "nombre": "Grok 4.7 · grok-cli",
     "bueno": "Contexto enorme (500K) y respuestas directas; cupo semanal propio.", "cupo": ("grok-cli", "weekly")},
    {"id": "antigravity/claude-opus-5-5-high", "corto": "lo más potente, cupo escaso", "nombre": "Claude Opus 5.5 · antigravity",
     "bueno": "Lo más potente para razonar o redactar con cuidado; el cupo de Claude y GPT en antigravity es semanal y escaso.",
     "cupo": ("antigravity", "claude_gpt_weekly")},
]
IDS = {m["id"] for m in MODELOS}

# Recursos de cuota que se enseñan en el panel (los mismos que omnistatus): proveedor → {nombre en OmniRoute: etiqueta}
CUOTAS = {
    "antigravity": {"gemini_session": "Gemini · sesión", "gemini_weekly": "Gemini · semana", "claude_gpt_weekly": "Claude y GPT · semana"},
    "codex": {"session": "Codex · mes"},
    "grok-cli": {"weekly": "Grok · semana"},
    "openrouter": {"free_daily": "OpenRouter · día (gratis)"},
    "github": {"premium_interactions": "Copilot premium"},
    "cloudflare-ai": {"neurons": "Cloudflare · neuronas/día"},
    "kiro": {"credit": "Kiro · créditos"},
}

_lock = asyncio.Lock()
_hist: list = []
_ultimo = 0.0


def clave():
    """Clave de OmniRoute: variable de entorno o el .env de OmniRoute. Nunca se imprime ni se guarda en el repo."""
    k = os.environ.get("OMNIROUTE_API_KEY")
    if k:
        return k.strip()
    try:
        for l in ENV_OMNI.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?OMNIROUTE_API_KEY\s*=\s*['\"]?([^'\"\s]+)", l)
            if m:
                return m.group(1)
    except OSError:
        pass
    return ""


def _json_schema(x):
    """Schema de google-genai (tipos en MAYÚSCULAS) → JSON Schema de OpenAI."""
    if isinstance(x, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _json_schema(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [_json_schema(v) for v in x]
    return x


def herramientas():
    """Las herramientas de Delta (ya fusionadas por tema) en el formato de OpenAI."""
    out = []
    for d in acciones.DECLARATIONS:
        p = d.parameters.model_dump(mode="json", exclude_none=True) if d.parameters else {"type": "OBJECT", "properties": {}}
        out.append({"type": "function", "function": {"name": d.name, "description": d.description or "", "parameters": _json_schema(p)}})
    return out


def sistema():
    try:
        persona = (AQUI / "personalidad.txt").read_text(encoding="utf-8")
    except OSError:
        persona = "Eres Delta, el asistente del usuario."
    return (persona + "\n\nMODO TECLADO: el usuario te escribe en el panel de DeltaOS (no te habla). Contesta por escrito, breve y en español de "
            "España, sin markdown pesado. Tienes las mismas herramientas que por voz: úsalas en vez de decir que no puedes. Lo que escribe aquí NO es de "
            "viva voz: si una herramienta necesita permiso, saldrá la ventana de permiso en el panel; no la esquives ni digas que ya está confirmado. "
            "No tienes reloj: la hora y la fecha, con avisos accion=ver. Nunca inventes el resultado de una herramienta.\n\n"
            "Memoria reciente del usuario:\n" + (acciones.leer_memoria() or "(ninguna todavía)"))


async def _chat(modelo, mensajes, tools):
    k = clave()
    if not k:
        raise RuntimeError("no encuentro la clave de OmniRoute (OMNIROUTE_API_KEY)")
    cuerpo = {"model": modelo, "messages": mensajes, "tools": tools, "max_tokens": 4096}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as s:
        async with s.post(f"{BASE}/v1/chat/completions", json=cuerpo, headers={"Authorization": f"Bearer {k}"}) as r:
            txt = await r.text()
            if r.status != 200:
                raise RuntimeError(f"OmniRoute respondió {r.status}: {txt[:200]}")
            return json.loads(txt)


async def _herramienta(nombre, argumentos):
    try:
        args = json.loads(argumentos or "{}")
    except ValueError:
        return "Error: argumentos que no son JSON"
    real, args = acciones._real(nombre, args)
    h = acciones.HANDLERS.get(real)
    if h is None:
        return f"Error: no existe la herramienta {nombre}"
    privada = real in acciones.NOTAS_PRIVADAS
    print(f"\n⌨️  {nombre}({'…' if privada else args})")
    import agentes
    seg = agentes.teclado_herramienta(real, "" if privada else next((str(v) for v in args.values() if v), ""))
    acciones.ST["herramienta"] = real
    paso = acciones._paso(real, args)
    try:
        out = str(await h(**args))
        paso["e"] = "falló" if out.startswith("Error") else "hecho"
    except Exception as e:
        out = f"Error: {e}"
        paso["e"] = "falló"
    finally:
        acciones.ST["herramienta"] = None
        agentes.teclado_herramienta_fin(seg, paso["e"] == "hecho")
    return out[:6000]


async def _turno(modelo, texto):
    """Un turno: manda la conversación, atiende las herramientas que pida el modelo y devuelve (respuesta, modelo que contestó, tokens)."""
    mensajes = [{"role": "system", "content": sistema()}, *_hist, {"role": "user", "content": texto}]
    tools, tin, tout, res = herramientas(), 0, 0, ""
    contesto = modelo
    for _ in range(MAX_VUELTAS):
        r = await _chat(modelo, mensajes, tools)
        contesto = r.get("model") or contesto
        u = r.get("usage") or {}
        tin, tout = tin + (u.get("prompt_tokens") or 0), tout + (u.get("completion_tokens") or 0)
        msg = (r.get("choices") or [{}])[0].get("message") or {}
        res = (msg.get("content") or "").strip()
        llamadas = msg.get("tool_calls") or []
        if not llamadas:
            break
        mensajes.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": llamadas})
        for c in llamadas:
            f = c.get("function") or {}
            mensajes.append({"role": "tool", "tool_call_id": c.get("id"), "content": await _herramienta(f.get("name", ""), f.get("arguments"))})
    else:
        res = res or "Me he quedado dando vueltas con las herramientas sin llegar a una respuesta."
    return res or "(sin respuesta)", contesto, tin, tout


def _apunta(**kw):
    try:
        with open(USO, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), **kw}) + "\n")
    except OSError:
        pass


async def enviar(texto, modelo=None):
    """Lo que el usuario escribe en el bocadillo del panel. El cliente solo manda el id del modelo (se valida contra MODELOS)."""
    global _ultimo
    texto = (texto or "").strip()[:4000]
    if not texto:
        return {"ok": False, "msg": "Escribe algo.", "devolver": True}
    if _lock.locked():
        return {"ok": False, "msg": "Sigo con la orden anterior.", "devolver": True}
    modelo = modelo if modelo in IDS else DEFECTO
    import agentes
    async with _lock:
        if time.monotonic() - _ultimo > OLVIDA:
            _hist.clear()
        panel.texto("tú", texto)
        panel.fin_turno()
        agentes.teclado_inicio(texto, modelo)
        p = acciones.paso(f"Teclado · {modelo.split('/')[-1]}")
        aviso = ""
        try:
            try:
                res, contesto, tin, tout = await _turno(modelo, texto)
            except Exception as e:
                if modelo == DEFECTO:
                    raise
                aviso = f"[{modelo.split('/')[-1]} falló ({str(e)[:80]}); contesto con el modelo por defecto] "
                res, contesto, tin, tout = await _turno(DEFECTO, texto)
            _hist.extend([{"role": "user", "content": texto}, {"role": "assistant", "content": res}])
            del _hist[:-MAX_HIST]
            _apunta(pedido=modelo, modelo=contesto, tin=tin, tout=tout)
            p["e"] = "hecho"
        except Exception as e:
            res, contesto = f"No he podido: {str(e)[:200]}", modelo
            p["e"] = "falló"
        finally:
            _ultimo = time.monotonic()
        panel.texto("delta", aviso + res)
        panel.fin_turno()
        agentes.teclado_fin(res, contesto)
    return {"ok": p["e"] == "hecho", "msg": res}


# ---------- panel de OmniRoute: modelos, cuotas y gasto (solo lectura) ----------
def _epoch(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _cuotas(con):
    prov = {i: p for i, p in con.execute("select id, provider from provider_connections")}
    out, vistos = [], {}
    for cid, raw in con.execute("select key, value from key_value where value like '%\"quotas\"%'"):
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        p = prov.get(cid)
        for nombre, etiqueta in CUOTAS.get(p, {}).items():
            q = (d.get("quotas") or {}).get(nombre)
            if not isinstance(q, dict) or q.get("total") is None:
                continue
            total, usado = q.get("total") or 0, q.get("used") or 0
            pct = q.get("remainingPercentage")
            if pct is None and total:
                pct = 100 * (total - usado) / total
            fila = {"prov": p, "nombre": nombre, "recurso": etiqueta, "usado": usado, "total": total,
                    "libre": None if pct is None else round(pct), "reset": _epoch(q.get("resetAt") or ""),
                    "visto": _epoch(d.get("fetchedAt") or ""), "pct": total == 100}
            out.append(fila)
            vistos[(p, nombre)] = fila
    out.sort(key=lambda f: (f["prov"], f["recurso"]))
    return out, vistos


def _gasto(con):
    ahora = datetime.now(timezone.utc)
    dia = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    corte = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S")
    res = {}
    for k, desde in (("hoy", dia), ("semana", ahora - timedelta(days=7)), ("mes", ahora - timedelta(days=30)), ("total", datetime(2000, 1, 1))):
        n, usd, tok = con.execute("select count(*), coalesce(sum(amount_usd),0), coalesce(sum(tokens_input+tokens_output),0) "
                                  "from request_cost_ledger where timestamp >= ?", (corte(desde),)).fetchone()
        res[k] = {"n": n, "usd": round(usd, 4), "tok": tok}
    res["modelos"] = [{"modelo": m, "n": n, "usd": round(u, 4), "tok": t} for m, n, u, t in con.execute(
        "select model, count(*), sum(amount_usd), sum(tokens_input+tokens_output) from request_cost_ledger where timestamp >= ? "
        "group by model order by 3 desc, 2 desc limit 6", (corte(dia),))]
    return res


def _propio():
    """Peticiones del modo teclado (las que cuentan contra el cupo de antigravity): hoy y últimos 7 días."""
    ahora, dia = time.time(), datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    hoy = sem = tin = tout = 0
    try:
        for l in USO.read_text().splitlines():
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if d["t"] > ahora - 7 * 86400:
                sem += 1
                if d["t"] >= dia:
                    hoy += 1
                    tin, tout = tin + d.get("tin", 0), tout + d.get("tout", 0)
    except OSError:
        pass
    return {"hoy": hoy, "semana": sem, "tin": tin, "tout": tout}


def info():
    """Todo lo del panel «OmniRoute»: modelos con su cupo, cuotas, gasto y lo gastado por el modo teclado."""
    datos = {"ahora": time.time(), "defecto": DEFECTO, "clave": bool(clave()), "propio": _propio(), "cuotas": [], "gasto": None, "error": ""}
    cupos = {}
    try:
        con = sqlite3.connect(f"file:{BD}?mode=ro", uri=True, timeout=1)
        try:
            datos["cuotas"], cupos = _cuotas(con)
            datos["gasto"] = _gasto(con)
        finally:
            con.close()
    except sqlite3.Error as e:
        datos["error"] = f"No puedo leer la base de OmniRoute ({e})"
    modelos = []
    for m in MODELOS:
        q = cupos.get(m["cupo"]) if m["cupo"] else None
        modelos.append({"id": m["id"], "nombre": m["nombre"], "corto": m["corto"], "bueno": m["bueno"],
                        "libre": q["libre"] if q else None, "reset": q["reset"] if q else None, "cupo": q["recurso"] if q else None})
    datos["modelos"] = modelos
    return datos
