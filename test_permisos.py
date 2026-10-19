"""Claude Code (ACP) nunca le pide permiso al usuario (sin API): .venv/bin/python test_permisos.py"""
import asyncio
from types import SimpleNamespace as N

import claude_acp

opciones = [N(kind="reject_once", option_id="no"), N(kind="allow_once", option_id="si")]
llamada = N(title="Write designs/x.py", kind="edit", raw_input={})
r = asyncio.run(claude_acp._Cliente().request_permission("s", llamada, opciones))
assert r.outcome.option_id == "si", r
print("OK: los permisos de Claude Code se dan solos")
