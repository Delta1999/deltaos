"""Mapa en vivo de los agentes del PC para la pantalla completa «Agentes» de DeltaOS.

Solo LEE: las transcripciones de Claude Code (~/.claude/projects: sesiones y subagentes, con herramienta,
modelo y quién encargó qué), las llamadas reales de OmniRoute (SQLite en solo lectura) y el estado de Delta
(acciones.ST). Lo difunde GET /agentes.json (el panel lo consulta solo con la pantalla abierta).

Origen de cada agente: «claude» si su modelo es de Anthropic y la sesión no es de terceros (entrypoint *-3p);
«omniroute» en otro caso (la transcripción guarda el modelo real que contestó); «gemini» es Delta.
"""
import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from aiohttp import web

import panel
from acciones import ST

PROYECTOS = Path.home() / ".claude" / "projects"
OMNI = Path.home() / ".omniroute" / "storage.sqlite"
VENTANA = 1200       # s de historia que se guardan (el repaso rebobina hasta aquí)
COLA = 400_000       # al ver un fichero por primera vez solo se lee su final
MAX_SEGS, MAX_EVT = 80, 300
MAX_RES = 6000       # caracteres que se guardan de lo último que dijo un agente o de un resultado

_ficheros: dict = {}   # ruta -> {"off", "nodo", "sub"}
_nodos: dict = {}      # id -> nodo
_agent_calls: dict = {}  # tool_use_id de una llamada Agent/Task -> id del nodo que la hizo
_eventos: list = []
_cache = {"t": 0.0, "datos": {"ahora": 0, "desde": 0, "nodos": [], "eventos": []}}
_ultimo_scan = 0.0
_claude_prev = "libre"


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _nodo(id_, **kw):
    n = _nodos.get(id_)
    if n is None:
        n = _nodos[id_] = {"id": id_, "nombre": id_, "tipo": "sesion", "padre": None, "modelo": "", "origen": "claude", "t0": 0.0, "t1": 0.0,
                           "fin": None, "tarea": "", "segs": [], "tok": {}, "ult": "", "ruta": ""}
    n.update({k: v for k, v in kw.items() if v is not None})
    return n


def _detalle(nombre, inp):
    if not isinstance(inp, dict):
        return ""
    for k in ("description", "command", "file_path", "pattern", "url", "query", "path", "prompt"):
        v = inp.get(k)
        if isinstance(v, str) and v:
            v = os.path.basename(v) if k == "file_path" else v
            return v.replace("\n", " ")[:90]
    return ""


def _texto(c):
    if isinstance(c, str):
        return c
    return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text") if isinstance(c, list) else ""


def _evento(t, de, a, tipo, txt="", tid=None):
    # lo que vuelve de un agente se guarda casi entero (y con sus saltos de línea) para poder leerlo en la sala; los encargos, en corto
    _eventos.append({"t": t, "de": de, "a": a, "tipo": tipo, "txt": txt.strip()[:MAX_RES] if tipo == "resultado" else " ".join(txt.split())[:140], "tid": tid})
    del _eventos[:-MAX_EVT]


def _linea(f, d):
    t = _ts(d.get("timestamp") or "")
    if t is None:
        return
    n = _nodos[f["nodo"]]
    n["t0"] = n["t0"] or t
    n["t1"] = max(n["t1"], t)
    tipo, m = d.get("type"), d.get("message") or {}
    if d.get("cwd") and not f["sub"]:
        n["cwd"] = d["cwd"]
    if d.get("cwd") and not n.get("tit") and not f["sub"]:
        n["nombre"] = os.path.basename(d["cwd"].rstrip("/")) or "sesión"
    if d.get("entrypoint") and not n.get("entrypoint"):
        n["entrypoint"] = d["entrypoint"]
        if d["entrypoint"] == "sdk-ts" and not f["sub"]:  # el Claude Code que maneja Delta por ACP
            n["padre"] = "delta"
    if tipo == "assistant":
        mod = m.get("model")
        if mod and mod != "<synthetic>":
            n["modelo"] = mod
        if m.get("id") and (m.get("usage") or {}).get("output_tokens") is not None:
            n["tok"][m["id"]] = m["usage"]["output_tokens"]
        usa = False
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                usa = True
                nom = b.get("name", "?")
                seg = {"id": b.get("id"), "tool": nom, "det": _detalle(nom, b.get("input")), "t0": t, "t1": None, "ok": True}
                n["segs"].append(seg)
                del n["segs"][:-MAX_SEGS]
                n["ult"] = "usa"
                if nom in ("Agent", "Task") and b.get("id"):
                    _agent_calls[b["id"]] = n["id"]
            elif b.get("type") == "thinking":
                n["ult"] = "piensa"
            elif b.get("type") == "text" and b.get("text"):
                n["ult"] = "habla"
                n["texto"] = b["text"]
        if m.get("stop_reason") == "end_turn" and not usa:
            n["ult"] = "reposo"
            if f["sub"]:
                n["fin"] = t
                _evento(t, n["id"], None, "resultado", n.get("texto", ""), tid=n.get("tid"))
    elif tipo == "user":
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    for s in reversed(n["segs"]):
                        if s["id"] == b.get("tool_use_id") and s["t1"] is None:
                            s["t1"], s["ok"] = t, not b.get("is_error")
                            break
        txt = _texto(c).strip()
        if txt and not txt.startswith("<") and not f["sub"] and d.get("userType") != "internal":
            n["tarea"] = txt.replace("\n", " ")[:140]


def _leer(ruta, f):
    try:
        tam = ruta.stat().st_size
    except OSError:
        return
    if tam <= f["off"]:
        return
    with open(ruta, "rb") as fh:
        if f["off"] == 0 and tam > COLA:
            fh.seek(tam - COLA)
            fh.readline()  # descarta la línea cortada
            _nodos[f["nodo"]]["parcial"] = True  # los tokens contados son solo los del final
        else:
            fh.seek(f["off"])
        datos = fh.read()
    fin = datos.rfind(b"\n")
    if fin < 0:
        return
    f["off"] = (tam - len(datos)) + fin + 1
    for l in datos[:fin].splitlines():
        try:
            _linea(f, json.loads(l))
        except Exception:
            continue


def _titulo(dir_sesion):
    try:
        return json.loads((dir_sesion / "custom-title.json").read_text()).get("customTitle", "")
    except Exception:
        return ""


def _escanear(ahora):
    """Ficheros tocados en la ventana: sesiones y subagentes. Los nuevos se dan de alta."""
    if not PROYECTOS.is_dir():
        return
    corte = ahora - VENTANA
    for proy in PROYECTOS.iterdir():
        try:
            for e in os.scandir(proy):
                if e.name.endswith(".jsonl") and e.stat().st_mtime > corte and e.path not in _ficheros:
                    sid = e.name[:-6]
                    tit = _titulo(proy / sid)
                    _nodo(sid, nombre=tit or "sesión", tipo="sesion", tit=bool(tit))
                    _ficheros[e.path] = {"off": 0, "nodo": sid, "sub": False, "dir": proy / sid}
                elif e.is_dir():
                    sub = Path(e.path) / "subagents"
                    if sub.is_dir():
                        for s in os.scandir(sub):
                            if s.name.endswith(".jsonl") and s.stat().st_mtime > corte and s.path not in _ficheros:
                                aid = s.name[6:-6]
                                try:
                                    meta = json.loads(Path(s.path[:-6] + ".meta.json").read_text())
                                except Exception:
                                    meta = {}
                                _nodo(aid, nombre=meta.get("agentType", "subagente"), tipo="sub", tarea=meta.get("description", ""),
                                      modelo=meta.get("model", ""), tid=meta.get("toolUseId"), sesion=e.name)
                                _ficheros[s.path] = {"off": 0, "nodo": aid, "sub": True}
        except OSError:
            continue


def _omniroute(ahora):
    if not OMNI.exists():
        return []
    desde = datetime.utcfromtimestamp(ahora - VENTANA).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        con = sqlite3.connect(f"file:{OMNI}?mode=ro", uri=True, timeout=1)
        try:
            return con.execute(
                "select timestamp, model, provider, combo_name, duration, tokens_in, tokens_out, api_key_name from call_logs "
                "where timestamp > ? and path like '/v1/%' and model != 'connection-test' order by timestamp", (desde,)).fetchall()
        finally:
            con.close()
    except Exception:
        return []


def _delta(ahora):
    global _claude_prev
    n = _nodo("delta", nombre="Delta", tipo="delta", modelo="gemini-3.8-live", origen="gemini", tarea="orquestador de voz")
    n["t0"] = n["t0"] or ahora
    h = ST.get("herramienta")
    abierto = n["segs"][-1] if n["segs"] and n["segs"][-1]["t1"] is None else None
    if h and not abierto:
        n["segs"].append({"id": f"d{ahora}", "tool": h, "det": "", "t0": ahora, "t1": None, "ok": True})
        del n["segs"][:-MAX_SEGS]
    elif not h and abierto:
        abierto["t1"] = ahora
    if h or ST.get("activo"):
        n["t1"] = ahora
        n["ult"] = "usa" if h else "habla"
    cl = (ST.get("claude") or {}).get("estado", "libre")
    if cl != _claude_prev:
        acp = max((x for x in _nodos.values() if x.get("padre") == "delta"), key=lambda x: x["t1"], default=None)
        if acp:
            if cl == "trabajando":
                _evento(ahora, "delta", acp["id"], "encargo", (ST.get("claude") or {}).get("tarea", ""))
            else:
                _evento(ahora, acp["id"], "delta", "resultado", (ST.get("claude") or {}).get("ultimo", ""))
        _claude_prev = cl


def teclado_inicio(texto, modelo):
    """Modo teclado (teclado.py): lo que el usuario escribe en el panel abre un movimiento Delta → «Teclado» con el modelo de OmniRoute."""
    ahora = time.time()
    n = _nodo("teclado", nombre="Teclado", tipo="sesion", padre="delta", modelo=modelo.split("/")[-1], tarea=texto.replace("\n", " ")[:140], fin=None)
    n["t0"] = n["t0"] or ahora
    n["t1"], n["ult"] = ahora, "piensa"
    n["segs"].append({"id": f"k{ahora}", "tool": "OmniRoute", "det": modelo.split("/")[-1], "t0": ahora, "t1": None, "ok": True})  # la espera del modelo
    del n["segs"][:-MAX_SEGS]
    _evento(ahora, "delta", "teclado", "encargo", texto)


def teclado_herramienta(nombre, det=""):
    n = _nodo("teclado")
    seg = {"id": f"k{time.time()}", "tool": nombre, "det": " ".join(det.split())[:90], "t0": time.time(), "t1": None, "ok": True}
    n["segs"].append(seg)
    del n["segs"][:-MAX_SEGS]
    n["t1"], n["ult"] = seg["t0"], "usa"
    return seg


def teclado_herramienta_fin(seg, ok=True):
    seg["t1"], seg["ok"] = time.time(), ok
    n = _nodo("teclado")
    n["t1"], n["ult"] = seg["t1"], "piensa"


def teclado_fin(respuesta, modelo=""):
    ahora = time.time()
    n = _nodo("teclado", modelo=modelo.split("/")[-1] or None, texto=respuesta)
    n["t1"], n["ult"] = ahora, "reposo"
    for s in n["segs"]:
        if s["t1"] is None:
            s["t1"] = ahora
    _evento(ahora, "teclado", "delta", "resultado", respuesta)


def _salida(ahora):
    corte = ahora - VENTANA
    llamadas = _omniroute(ahora)
    nodos = []
    for n in _nodos.values():
        if n["tipo"] == "sub":
            n["padre"] = _agent_calls.get(n.get("tid")) or _sesion_de(n)
        if n["t1"] < corte and n["id"] != "delta":
            continue
        n["origen"] = n["origen"] if n["tipo"] == "delta" else (
            "omniroute" if (n["modelo"] and not n["modelo"].startswith("claude-")) or str(n.get("entrypoint", "")).endswith("-3p") else "claude")
        nodos.append(n)
    # OmniRoute: nodo propio con cada llamada como tramo, y a qué agente sirvió (mismo modelo, mismo instante)
    if llamadas:
        h = _nodo("omniroute", nombre="OmniRoute", tipo="router", origen="omniroute", tarea="enrutador de modelos")
        h["segs"] = []
        for ts, mod, prov, combo, dur, tin, tout, clave in llamadas:
            t1 = _ts(ts) or ahora
            h["segs"].append({"id": ts, "tool": f"{prov}/{mod}", "det": f"{combo or ''} · {tin or 0}→{tout or 0} tok", "t0": t1 - (dur or 0) / 1000, "t1": t1, "ok": True})
            for n in nodos:
                if n["origen"] == "omniroute" and n["modelo"] == mod and abs(n["t1"] - t1) < 15:
                    n["ruta"] = f"{prov} · {combo}" if combo else prov
        h["segs"] = h["segs"][-MAX_SEGS:]
        h["t0"], h["t1"] = h["segs"][0]["t0"], h["segs"][-1]["t1"]
        h["modelo"] = h["segs"][-1]["tool"]
        nodos.append(h)
    ids = {n["id"] for n in nodos}
    salida = []
    for n in nodos:
        abiertos = [s for s in n["segs"] if s["t1"] is None and ahora - s["t0"] < 900]
        if abiertos:
            est = "orquestando" if abiertos[-1]["tool"] in ("Agent", "Task") else "usando"
        elif ahora - n["t1"] < 6 and n["ult"] in ("piensa", "habla", "usa"):
            est = {"piensa": "pensando", "habla": "hablando", "usa": "usando"}[n["ult"]]
        elif n["fin"]:
            est = "hecho"
        else:
            est = "reposo"
        segs = [{"tool": s["tool"], "det": s["det"], "t0": s["t0"], "t1": s["t1"] if s["t1"] is not None else (ahora if s in abiertos else n["t1"]),
                 "ok": s["ok"], "abierto": s in abiertos} for s in n["segs"] if (s["t1"] or ahora) > corte]
        salida.append({"id": n["id"], "nombre": n["nombre"], "tipo": n["tipo"], "padre": n["padre"] if n["padre"] in ids else None,
                       "modelo": n["modelo"] or "?", "origen": n["origen"], "ruta": n.get("ruta", ""), "t0": n["t0"], "t1": n["t1"], "fin": n["fin"],
                       "tarea": n["tarea"], "estado": est, "ahora_usa": abiertos[-1]["tool"] + (": " + abiertos[-1]["det"] if abiertos[-1]["det"] else "") if abiertos else "",
                       "tok": sum(n["tok"].values()), "parcial": bool(n.get("parcial")), "segs": segs,
                       "texto": str(n.get("texto", "")).strip()[:MAX_RES],  # lo último que ha escrito, entero, para la ficha y la sala
                       "hablable": _hablable(n)})
    evs = []
    for e in _eventos:
        if e["t"] < corte:
            continue
        de = e["de"] if e["de"] in ids else None
        a = e["a"] if e["a"] in ids else None
        if e["tipo"] == "resultado" and a is None and e["tid"]:
            a = _agent_calls.get(e["tid"])
        if e["tipo"] == "resultado" and a is None:
            a = next((x["padre"] for x in salida if x["id"] == e["de"]), None)
        evs.append({"t": e["t"], "de": de, "a": a if a in ids else None, "tipo": e["tipo"], "txt": e["txt"]})
    for n in salida:  # encargo del padre al subagente en cuanto arranca
        if n["tipo"] == "sub" and n["padre"] and n["t0"] > corte:
            evs.append({"t": n["t0"], "de": n["padre"], "a": n["id"], "tipo": "encargo", "txt": n["tarea"][:140]})
    evs.sort(key=lambda e: e["t"])
    return {"ahora": ahora, "desde": corte, "nodos": salida, "eventos": evs[-MAX_EVT:]}


def _hablable(n):
    """Solo se puede hablar con lo que maneja Delta: él mismo y el Claude Code que lanza por ACP."""
    return n["id"] == "delta" or (n.get("entrypoint") == "sdk-ts" and n["tipo"] == "sesion")


async def decir(a, texto="", accion=None):
    """Lo que el usuario escribe en la pantalla «Agentes» para un agente. Llega por el WebSocket del panel (con Origin
    comprobado y nunca desde la tele), así que es suyo; no autoriza nada por sí solo: las acciones que piden permiso lo piden."""
    import acciones
    import claude_acp
    texto = texto.strip()
    n = _nodos.get(a)
    if n is None or not (texto or accion):
        return {"ok": False, "msg": "No hay nada que enviar."}
    if not _hablable(n):
        return {"ok": False, "msg": "Es otro proceso: desde aquí solo se puede leer."}
    if accion == "cancelar":
        if a == "delta":
            return {"ok": False, "msg": "A Delta no se le cancela nada: ya se calla si le hablas."}
        return {"ok": True, "msg": await claude_acp.cancelar_claude()}
    if a == "delta":
        return {"ok": await acciones.decir_a_delta(texto), "msg": "Enviado a Delta." if ST.get("session") else "Delta está en reposo: llámalo primero."}
    if n.get("cwd") == str(claude_acp.AQUI):
        msg = await claude_acp.mejorar_delta(texto)
    else:
        msg = await claude_acp.hablar_con_claude(texto)
    return {"ok": not msg.startswith("Claude Code sigue ocupado"), "msg": msg}


async def nueva(id_, texto="", combo=None):
    """El selector «Nueva conversación» de la pantalla Agentes: abre una conversación con lo elegido (el cliente solo manda el id
    y, si quiere, el nombre de un combo de OmniRoute, que se valida contra la lista fija)."""
    import acciones
    import agentes_catalogo
    import claude_acp
    texto = texto.strip()
    a = agentes_catalogo.arranque(id_)
    if a is None:
        return {"ok": False, "msg": "Eso ya no está en el catálogo."}
    if not texto:
        return {"ok": False, "msg": "Escribe qué quieres que haga."}
    cliente, instruccion, _ = a
    combo = agentes_catalogo.combo_valido(combo)
    if cliente == "claude":
        msg = await claude_acp.nueva_conversacion(instruccion, texto, combo)
        return {"ok": not msg.startswith("Claude Code sigue ocupado"), "msg": msg}
    if instruccion == "hablar":
        return {"ok": await acciones.decir_a_delta(texto), "msg": "Enviado a Delta." if ST.get("session") else "Delta está en reposo: llámalo primero."}
    if instruccion == "cambiar":
        return {"ok": True, "msg": await claude_acp.mejorar_delta(texto, combo=combo)}
    if instruccion == "antigravity":
        return {"ok": True, "msg": await acciones.mejorar_delta_antigravity(texto)}
    return {"ok": True, "msg": await acciones.mejorar_delta_cherry(texto)}


def _sesion_de(n):
    s = n.get("sesion", "")
    return s[:-6] if s.endswith(".jsonl") else s or None


def recoger():
    """Una pasada: ficheros nuevos, líneas nuevas, estado de Delta y la foto para el panel."""
    global _ultimo_scan
    ahora = time.time()
    if ahora - _ultimo_scan > 5:
        _escanear(ahora)
        _ultimo_scan = ahora
    for ruta, f in list(_ficheros.items()):
        _leer(Path(ruta), f)
    _delta(ahora)
    _cache["datos"], _cache["t"] = _salida(ahora), ahora
    return _cache["datos"]


async def vigilar():
    """Mantiene la historia aunque la pantalla esté cerrada (para poder rebobinar al abrirla)."""
    while True:
        try:
            await asyncio.to_thread(recoger)
        except Exception as e:
            print(f"agentes: {e}")
        await asyncio.sleep(1.5)


async def _json(request):
    datos = _cache["datos"] if time.time() - _cache["t"] < 3 else await asyncio.to_thread(recoger)
    return web.json_response(datos, headers={"Cache-Control": "no-store"})

panel.RUTAS.append(("/agentes.json", _json))
