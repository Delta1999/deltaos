"""Averías y mejoras de Delta llegan a Claude Code las llame como las llame el usuario (.venv/bin/python test_buzon_claude.py)"""
import asyncio
import tempfile
from pathlib import Path

import acciones
import claude_acp

import antigravity_puente

_tmp_dir = Path(tempfile.mkdtemp())
acciones.MEJORAS_LOG = _tmp_dir / "mejoras_pendientes.log"  # no tocar el registro de verdad
acciones.CHERRY_PENDIENTES = _tmp_dir / "cherry_pendientes.txt"
antigravity_puente.MD_PENDIENTES = _tmp_dir / "antigravity_pendientes.md"
antigravity_puente.TXT_PENDIENTES = _tmp_dir / "antigravity_pendientes.txt"
corre = asyncio.run
guardadas = []
acciones._mem.guardar = lambda nota: guardadas.append(nota) or "Guardado."

# Un solo buzón, con la etiqueta puesta sola: el usuario confunde avería y mejora y da igual.
assert "avería" in corre(acciones.anotar_mejora("El escudo no se muestra en la pantalla de arriba"))
assert "mejora" in corre(acciones.anotar_mejora("Que el mapa salga sin fotos de sitios"))
assert "Ya estaba" in corre(acciones.anotar_mejora("que el mapa salga sin fotos de sitios"))
log = acciones.MEJORAS_LOG.read_text()
assert "[avería] El escudo" in log and "[mejora] Que el mapa" in log, log
# Las de audio no se repiten a decenas.
assert "Anotado" in corre(acciones.anotar_mejora("micrófono saturado"))
assert "no la repitas" in corre(acciones.anotar_mejora("micrófono saturado otra vez"))

# «Recuérdalo» / «para mañana» sobre algo de Delta (lo que pasó el 21/10): al buzón, no a la memoria.
r = corre(acciones.recordar("Pendiente para mañana: cambiar Google Maps por Waze"))
assert "registro de Claude" in r and not guardadas and "Waze" in acciones.MEJORAS_LOG.read_text()
assert corre(acciones.recordar("Mi hermana se llama Ana")) == "Guardado." and guardadas == ["Mi hermana se llama Ana"]

# «Díselo a Claude» por el Claude de WORMHOLE, siendo de Delta: se desvía a mejorar_delta.
mandadas = []
async def falso_mejorar(peticion, voz=True):
    mandadas.append(peticion); return "Enviado a Claude Code."
real, claude_acp.mejorar_delta = claude_acp.mejorar_delta, falso_mejorar
assert "no a WORMHOLE" in corre(claude_acp.hablar_con_claude("Avería: tu panel no se mueve de pantalla"))
assert mandadas == ["Avería: tu panel no se mueve de pantalla"]
claude_acp.mejorar_delta = real
assert acciones._real("claude", {"accion": "mejorar_delta", "mensaje": "x"}) == ("mejorar_delta", {"peticion": "x"})
assert acciones._real("claude", {"accion": "antigravity", "mensaje": "x"}) == ("mejorar_delta_antigravity", {"peticion": "x"})
assert acciones._real("claude", {"accion": "cherry", "mensaje": "x"}) == ("mejorar_delta_cherry", {"peticion": "x"})

# Rutas hacia Antigravity (Plan B) y Cherry (Plan C)
assert "Antigravity" in corre(claude_acp.mejorar_delta("Dile a Antigravity que ajuste el brillo"))
assert "Antigravity" in corre(claude_acp.hablar_con_claude("Avería: agy arregla esto"))
assert "Cherry" in corre(claude_acp.mejorar_delta("Pasa esto a Cherry"))
assert "Cherry" in corre(claude_acp.hablar_con_claude("Dile a Cherry que revise esto"))

# Con el límite de sesión, o si Claude está ocupado, la petición no se pierde.
assert claude_acp.LIMITE.search("You've hit your session limit · resets 1:10am")
claude_acp._tarea = asyncio.Future(loop=asyncio.new_event_loop())  # «ocupado»
assert "queda anotada" in corre(claude_acp.mejorar_delta("Que la barra enseñe el logo"))
claude_acp._tarea = None
assert "[mejora] Que la barra enseñe el logo" in acciones.MEJORAS_LOG.read_text()

print("OK: averías y mejoras llegan al buzón de Claude Code las llame como las llame el usuario")
