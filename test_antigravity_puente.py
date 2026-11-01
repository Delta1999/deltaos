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

# 4. Integración con acciones.py (sin ejecutar agy de verdad)
antigravity_puente.EJECUTAR = False
acciones.ANTIGRAVITY_PENDIENTES = antigravity_puente.MD_PENDIENTES
res_accion = corre(acciones.mejorar_delta_antigravity("Subir volumen por defecto"))
assert "Plan B" in res_accion
assert "Subir volumen por defecto" in antigravity_puente.MD_PENDIENTES.read_text(encoding="utf-8")

# 5. Ejecución real con un «agy» falso en un repo git temporal: foto antes/después, registro y línea de uso
import json
import subprocess

repo = tmp / "repo"
repo.mkdir()
git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout
git("init", "-q")
git("config", "user.email", "t@t")
git("config", "user.name", "t")
(repo / "a.txt").write_text("uno\n")
git("add", "a.txt")
git("commit", "-qm", "base")
falso = tmp / "agy_falso.sh"
falso.write_text('#!/bin/sh\necho dos >> a.txt\necho \'{"status":"SUCCESS","response":"añadido dos","usage":{"total_tokens":42}}\'\n')
falso.chmod(0o755)
antigravity_puente.AQUI, antigravity_puente.CMD_AGY = repo, [str(falso)]
antigravity_puente.REGISTRO, antigravity_puente.USO = tmp / "CAMBIOS.md", tmp / "uso.jsonl"
res = corre(antigravity_puente.ejecutar_con_agy("Subir volumen por defecto"))
assert res == "añadido dos", res
assert (repo / "a.txt").read_text() == "uno\ndos\n"
reg = antigravity_puente.REGISTRO.read_text(encoding="utf-8")
assert "Plan B → Antigravity" in reg and "a.txt" in reg and "refs/delta/" in reg, reg
linea = json.loads(antigravity_puente.USO.read_text(encoding="utf-8").splitlines()[0])
assert linea["ok"] is True and linea["tokens"] == 42, linea
assert "refs/delta/" in git("for-each-ref"), "las fotos antes/después deben quedar como refs"

print("✓ test_antigravity_puente: registro, listado, marcado, handlers y ejecución con foto git + uso funcionan correctamente")
