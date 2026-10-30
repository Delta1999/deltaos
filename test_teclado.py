"""Modo teclado (.venv/bin/python test_teclado.py)
Herramientas de Delta en formato OpenAI, bucle de herramientas, respaldo al modelo por defecto, modelo desconocido,
cuotas/gasto leídos de una base de OmniRoute de mentira y que la clave nunca salga en lo que se difunde."""
import asyncio
import json
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import acciones
import agentes
import panel
import teclado

corre = lambda c: asyncio.run(c)
tmp = Path(tempfile.mkdtemp())
teclado.USO = tmp / "uso.jsonl"

# --- herramientas: sin tipos en MAYÚSCULAS y con parámetros de objeto
ts = teclado.herramientas()
# --- catálogo de modelos: sin ids repetidos y con lo que pinta el panel
assert len(teclado.IDS) == len(teclado.MODELOS) and teclado.DEFECTO in teclado.IDS
assert all(m["id"] and m["nombre"] and m["corto"] and m["bueno"] and "cupo" in m for m in teclado.MODELOS)
assert ts and all(t["type"] == "function" and t["function"]["parameters"]["type"] == "object" for t in ts)
assert "STRING" not in json.dumps(ts) and "OBJECT" not in json.dumps(ts)
ab = next(t for t in ts if t["function"]["name"] == "abrir")["function"]["parameters"]
assert ab["properties"]["objetivo"]["type"] == "string" and ab["required"] == ["objetivo"], ab

# --- clave: del entorno o del .env de OmniRoute, y nunca en la información del panel
teclado.ENV_OMNI = tmp / ".env"
teclado.ENV_OMNI.write_text('FOO=1\nexport OMNIROUTE_API_KEY="sk-prueba-123"\n')
import os
os.environ.pop("OMNIROUTE_API_KEY", None)
assert teclado.clave() == "sk-prueba-123"
os.environ["OMNIROUTE_API_KEY"] = "sk-entorno"
assert teclado.clave() == "sk-entorno"

# --- bucle de herramientas con un OmniRoute de mentira
llamadas = []


async def hola(nombre=""):
    llamadas.append(nombre)
    return f"Hola {nombre}"


acciones.HANDLERS["hola"] = hola
acciones.DECLARATIONS.append(acciones._fn("hola", "prueba", {"nombre": acciones._s("nombre")}))
vistos = []


async def chat_falso(modelo, mensajes, tools):
    vistos.append((modelo, [m["role"] for m in mensajes]))
    if modelo == "roto":
        raise RuntimeError("OmniRoute respondió 429")
    if mensajes[-1]["role"] == "tool":
        assert mensajes[-1]["content"] == "Hola Ana"
        return {"model": "real-model", "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "choices": [{"message": {"content": "Saludado."}}]}
    return {"model": "real-model", "usage": {"prompt_tokens": 20, "completion_tokens": 3},
            "choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "hola", "arguments": '{"nombre": "Ana"}'}}]}}]}


teclado._chat = chat_falso
panel.S["frases"].clear()
r = corre(teclado.enviar("saluda a Ana", "modelo-que-no-existe"))
assert r == {"ok": True, "msg": "Saludado."}, r
assert llamadas == ["Ana"]
assert vistos[0][0] == teclado.DEFECTO, "un id desconocido nunca llega a OmniRoute"
assert vistos[1][1][-1] == "tool"
assert [f["rol"] for f in panel.S["frases"]] == ["tú", "delta"] and panel.S["frases"][-1]["t"] == "Saludado."
nodo = agentes._nodos["teclado"]
assert nodo["padre"] == "delta" and nodo["ult"] == "reposo" and any(s["tool"] == "hola" for s in nodo["segs"])
assert all(s["t1"] is not None for s in nodo["segs"]), "ningún tramo se queda abierto"
assert [e["tipo"] for e in agentes._eventos[-2:]] == ["encargo", "resultado"]
uso = json.loads(teclado.USO.read_text().splitlines()[-1])
assert uso["tin"] == 30 and uso["tout"] == 8, uso

# --- lo escrito en el bocadillo vale como de viva voz: no sale ventana de permiso
acciones.ST["t_tu"] = 0
corre(teclado.enviar("saluda a Ana"))
assert acciones.hablando_contigo(), "escribir en el panel autoriza la orden como si la dijera de viva voz"
acciones.ST["t_tu"] = 0

# --- el modelo elegido falla → contesta el de por defecto y lo dice
teclado.IDS.add("roto")
vistos.clear()
r = corre(teclado.enviar("saluda a Ana", "roto"))
assert r["ok"] and [v[0] for v in vistos][:2] == ["roto", teclado.DEFECTO], vistos
assert "contesto con el modelo por defecto" in panel.S["frases"][-1]["t"]
teclado.IDS.discard("roto")

# --- el defecto también falla: se cuenta en la conversación y no revienta
async def chat_roto(*a):
    raise RuntimeError("sin red")
teclado._chat = chat_roto
r = corre(teclado.enviar("hola"))
assert not r["ok"] and "sin red" in panel.S["frases"][-1]["t"]
assert corre(teclado.enviar("   "))["devolver"], "lo vacío no se envía y se devuelve al cuadro"

# --- panel de consumo: base de OmniRoute de mentira
bd = tmp / "omni.sqlite"
con = sqlite3.connect(bd)
con.executescript("""create table provider_connections(id text, provider text);
create table key_value(key text, value text);
create table request_cost_ledger(id integer primary key, provider text, model text, tokens_input int, tokens_output int, amount_usd real, timestamp text);""")
con.execute("insert into provider_connections values('a1','antigravity'),('c1','codex')")
reset = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
con.execute("insert into key_value values('a1', ?)", (json.dumps({"fetchedAt": reset, "quotas": {
    "gemini_weekly": {"used": 49, "total": 1000, "remainingPercentage": 95.09, "resetAt": reset},
    "claude_gpt_weekly": {"used": 1000, "total": 1000, "remainingPercentage": 0, "resetAt": reset}}}),))
con.execute("insert into key_value values('c1', ?)", (json.dumps({"quotas": {"session": {"used": 17, "total": 100, "remaining": 83, "resetAt": reset}}}),))
ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
con.executemany("insert into request_cost_ledger(provider,model,tokens_input,tokens_output,amount_usd,timestamp) values(?,?,?,?,?,?)",
                [("codex", "gpt-6-luna", 1000, 100, 0.5, ahora), ("antigravity", "gemini-3.8-flash-high", 500, 50, 0.0, ahora),
                 ("codex", "viejo", 10, 10, 9.0, "2020-01-01T00:00:00.000Z")])
con.commit()
con.close()
teclado.BD = bd
i = teclado.info()
assert not i["error"] and i["gasto"]["hoy"]["n"] == 2 and i["gasto"]["total"]["n"] == 3
assert abs(i["gasto"]["hoy"]["usd"] - 0.5) < 1e-9 and i["gasto"]["modelos"][0]["modelo"] == "gpt-6-luna"
por_id = {m["id"]: m for m in i["modelos"]}
assert por_id[teclado.DEFECTO]["libre"] == 95 and por_id[teclado.DEFECTO]["reset"] > time.time()
assert por_id["antigravity/claude-opus-5-5-high"]["libre"] == 0, "agotado se nota"
assert por_id["codex/gpt-6-luna"]["libre"] == 83
assert por_id["orcarouter/kimi/kimi-k3"]["libre"] is None
assert por_id["openrouter/anthropic/claude-fable-5.1"]["libre"] is None
assert por_id["openrouter/deepseek/deepseek-v4-pro"]["libre"] is None
assert i["propio"]["hoy"] >= 1 and i["clave"] is True
assert "sk-entorno" not in json.dumps(i), "la clave no sale nunca hacia el panel"

# --- sin base: no revienta
teclado.BD = tmp / "no-existe.sqlite"
assert teclado.info()["error"]
print("ok")
