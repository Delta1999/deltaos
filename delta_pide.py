"""Claude Code → Delta: le manda un encargo y enseña lo que hace (pasos y lo que dice) hasta que acaba.

    .venv/bin/python delta_pide.py "cancela la tarea de Claude Code" [--segundos 90]

Lo que Gemini pida en los 5 min siguientes no pregunta al usuario (acciones.autorizado), salvo que él hable en medio.
"""
import argparse
import asyncio
import json
import time

import aiohttp

PANEL = "ws://127.0.0.1:7876/ws"  # sin Origin: el panel solo rechaza las webs (que siempre lo mandan)


async def main(texto, segundos):
    async with aiohttp.ClientSession() as s, s.ws_connect(PANEL) as ws:
        d = json.loads((await ws.receive()).data)
        vistos = {(p["h"], p["t"]) for p in d.get("pasos", [])}
        await ws.send_str(json.dumps({"encargo": texto}))
        fin, quieto, dicho = time.monotonic() + segundos, None, ""
        while time.monotonic() < fin:
            try:
                d = json.loads((await asyncio.wait_for(ws.receive(), 2)).data)
            except asyncio.TimeoutError:
                pass
            for p in d.get("pasos", []):
                if p["e"] != "en curso" and (p["h"], p["t"]) not in vistos:
                    vistos.add((p["h"], p["t"]))
                    print(f"{p['h']} {'✓' if p['e'] == 'hecho' else '✗'} {p['t']}", flush=True)
            f = [x for x in d.get("frases", []) if x.get("rol") == "delta"]
            if f and f[-1].get("fin") and f[-1]["t"] != dicho:
                dicho = f[-1]["t"]
                print(f"🗣️ {dicho.strip()}", flush=True)
            ocupado = d.get("estado") in ("hablando", "trabajando") or d.get("confirma")
            quieto = None if ocupado else quieto or time.monotonic()
            if dicho and quieto and time.monotonic() - quieto > 6:
                return


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("texto")
    ap.add_argument("--segundos", type=float, default=90)
    a = ap.parse_args()
    asyncio.run(main(a.texto, a.segundos))
