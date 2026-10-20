"""Memoria SQLite + FTS5: guardar, buscar y que el despertar deje de tragarse la libreta entera
(.venv/bin/python test_memoria.py)"""
import asyncio
import tempfile
from pathlib import Path

import memoria

# Base de datos de usar y tirar: el test no toca la memoria de verdad.
memoria.BD = Path(tempfile.mkdtemp()) / "m.db"
memoria.MD = Path(tempfile.mkdtemp()) / "no-existe.md"
corre = lambda c: asyncio.run(c)

# ---------- guardar ----------
assert memoria.guardar("el PETG va mejor que el PLA para exterior") == "Anotado."
assert memoria.guardar("  el PETG va mejor que el PLA para exterior  ") == "Ya lo tenía apuntado.", \
    "lo dicho dos veces no son dos notas"
assert memoria.cuantas() == 1
assert memoria.guardar("   ").startswith("Error")
assert memoria.guardar(None).startswith("Error")

# ---------- buscar ----------
memoria.guardar("la boquilla de la Sidewinder es de 0.4")
memoria.guardar("el niño pequeño se llama Mario y cumple en marzo")
memoria.guardar("a Ana no le gusta que la llamen antes de las diez")

# Esto se alimenta de voz dictada: lo que se transcribe sin tilde tiene que encontrar la nota.
assert any("Mario" in r["texto"] for r in memoria.buscar("nino")), "sin tilde no encuentra"
assert any("Mario" in r["texto"] for r in memoria.buscar("NIÑO")), "ni con mayúsculas"
assert any("0.4" in r["texto"] for r in memoria.buscar("qué dije de la boquilla"))
assert memoria.buscar("submarinos nucleares") == []
assert memoria.buscar("") == [] and memoria.buscar(None) == []

# FTS5 tiene lenguaje propio: una frase dictada con sus signos no puede reventar la consulta.
for veneno in ('comillas " dentro', "apóstrofo d'algo", "guion-medio", "AND OR NEAR", "*", "(((", '"'):
    memoria.buscar(veneno)  # basta con que no lance

# ---------- el contexto del despertar es PARCIAL ----------
for i in range(60):
    memoria.guardar(f"nota de relleno número {i}")
ctx = memoria.contexto()
assert memoria.cuantas() == 64, memoria.cuantas()
assert 0 < len(ctx.splitlines()) <= memoria.CONTEXTO_N + 4, len(ctx.splitlines())
assert "nota de relleno número 59" in ctx, "lo último tiene que estar"
assert "PETG" not in ctx, "lo viejo NO se inyecta: para eso está buscar"
# …pero sigue estando y se encuentra. Ésta es toda la gracia de la fase.
assert any("PETG" in r["texto"] for r in memoria.buscar("PETG")), "lo viejo no se ha perdido"

# Lo que se consulta sube al contexto, aunque sea viejo.
for _ in range(3):
    memoria.buscar("PETG exterior")
assert "PETG" in memoria.contexto(), "lo que se consulta tiene que volver al despertar"

# ---------- olvidar ----------
assert "1" in memoria.olvidar("Sidewinder")
assert memoria.buscar("boquilla") == [], "borrado de verdad, también del índice FTS"
assert memoria.olvidar("Sidewinder") == "No tenía nada apuntado con eso."
assert memoria.olvidar("").startswith("Error")

# ---------- enchufado a Delta, y sin herramienta plana nueva ----------
import acciones  # noqa: E402

acciones._mem = memoria
assert corre(acciones.recordar("prueba de enchufe")) == "Anotado."
assert "prueba de enchufe" in corre(acciones.buscar_memoria("enchufe"))
assert "No tengo nada apuntado" in corre(acciones.buscar_memoria("zzz inexistente"))
assert "buscar" in acciones.FUSIONES["memoria"][2], acciones.FUSIONES["memoria"][2].keys()
assert acciones._real("memoria", {"accion": "buscar", "texto": "x"}) == ("buscar_memoria", {"consulta": "x"})

print(f"OK: memoria con FTS5 — {memoria.cuantas()} notas, el despertar solo ve {len(ctx.splitlines())}")
