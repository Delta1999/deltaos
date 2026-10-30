"""Pruebas del puente entre DeltaOS y Antigravity (.venv/bin/python test_antigravity_puente.py)"""
import asyncio
import tempfile
from pathlib import Path

import acciones
import antigravity_puente

corre = asyncio.run

# Aislar en directorio temporal
tmp = Path(tempfile.mkdtemp())
antigravity_puente.MD_PENDIENTES = tmp / "antigravity_pendientes.md"
antigravity_puente.TXT_PENDIENTES = tmp / "antigravity_pendientes.txt"

# 1. Registrar una mejora
res = corre(antigravity_puente.registrar_mejora("Añadir atajo para silenciar micrófono", origen="Test"))
assert "Plan B" in res and "antigravity_pendientes.md" in res, res
assert antigravity_puente.MD_PENDIENTES.is_file()
assert antigravity_puente.TXT_PENDIENTES.is_file()

md_txt = antigravity_puente.MD_PENDIENTES.read_text(encoding="utf-8")
assert "Añadir atajo para silenciar micrófono" in md_txt
assert "🟡 PENDIENTE" in md_txt
assert "Test" in md_txt

txt_txt = antigravity_puente.TXT_PENDIENTES.read_text(encoding="utf-8")
assert "[Antigravity] Añadir atajo para silenciar micrófono" in txt_txt

# 2. Listar pendientes
tareas = antigravity_puente.listar_pendientes()
assert len(tareas) == 1
assert tareas[0][1] == "🟡 PENDIENTE"
assert "Añadir atajo" in tareas[0][2]

# 3. Marcar completada
ok = antigravity_puente.marcar_completada("silenciar micrófono")
assert ok is True
md_txt_despues = antigravity_puente.MD_PENDIENTES.read_text(encoding="utf-8")
assert "🟢 COMPLETADA" in md_txt_despues

# 4. Integración con acciones.py
acciones.ANTIGRAVITY_PENDIENTES = antigravity_puente.MD_PENDIENTES
res_accion = corre(acciones.mejorar_delta_antigravity("Subir volumen por defecto"))
assert "Plan B" in res_accion
assert "Subir volumen por defecto" in antigravity_puente.MD_PENDIENTES.read_text(encoding="utf-8")

print("✓ test_antigravity_puente: registro, listado, marcado y handlers en acciones.py funcionan correctamente")
