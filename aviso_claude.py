#!/usr/bin/env python3
"""Hook Stop de Claude Code (~/.claude/settings.json): cuando una sesión que lanzó el usuario termina un turno
largo, deja una nota en el buzón privado de Delta (avisos.py la lee y la dice en voz alta). Solo stdlib."""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

MIN_SEG = 90   # turnos más cortos: el usuario está delante, no hace falta avisar
BUZON = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "delta-avisos"


def turno(transcript):
    """(segundos desde el último mensaje real del usuario, último texto del asistente)."""
    t0, final = None, ""
    for linea in transcript.read_text(errors="replace").splitlines():
        try:
            e = json.loads(linea)
        except ValueError:
            continue
        c = (e.get("message") or {}).get("content")
        if e.get("type") == "user" and not e.get("isMeta") and (
                isinstance(c, str) or any(b.get("type") == "text" for b in c or [] if isinstance(b, dict))):
            t0 = e.get("timestamp")
        elif e.get("type") == "assistant" and isinstance(c, list):
            txt = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text").strip()
            final = txt or final
    if not t0:
        return 0, final
    return time.time() - datetime.fromisoformat(t0.replace("Z", "+00:00")).timestamp(), final


def main():
    if os.environ.get("DELTA_ORIGEN"):
        return  # la lanzó Delta, que ya avisa por su cuenta
    d = json.load(sys.stdin)
    if d.get("stop_hook_active"):
        return
    seg, final = turno(Path(d["transcript_path"]))
    if seg < MIN_SEG:
        return
    BUZON.mkdir(mode=0o700, exist_ok=True)
    nota = {"t": time.time(), "proyecto": Path(d.get("cwd", "?")).name, "min": round(seg / 60),
            "final": (d.get("last_assistant_message") or final)[-800:]}
    tmp = BUZON / f".{d.get('session_id', 'x')}.tmp"
    tmp.write_text(json.dumps(nota, ensure_ascii=False))
    tmp.rename(BUZON / f"{int(time.time())}-{d.get('session_id', 'x')[:8]}.json")  # atómico: Delta nunca lee a medias


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # un hook roto no debe estorbar a Claude Code
        print(f"aviso_claude: {e}", file=sys.stderr)
