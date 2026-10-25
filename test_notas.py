"""Notas: el cajón desastre local (.venv/bin/python test_notas.py)
Guardar, buscar sin tildes y con palabras vacías, listar por fecha, borrado blando + purga, y que NADA salga
hacia la memoria, el panel ni Claude."""
import asyncio
import subprocess
import tempfile
import time
from pathlib import Path

import memoria
import notas

# Bases de usar y tirar: el test no toca ni las notas ni la memoria de verdad.
memoria.BD = Path(tempfile.mkdtemp()) / "m.db"
memoria.MD = Path(tempfile.mkdtemp()) / "no-existe.md"
notas.BD = Path(tempfile.mkdtemp()) / "n.db"
notas._con = None
notas._res = None
corre = lambda c: asyncio.run(c)
db = notas.db


def vivas():
    return db().execute("SELECT count(*) FROM notas WHERE borrada_en IS NULL").fetchone()[0]


# ---------- guardar: tal cual, sin dedupe, sin repetir la nota ----------
assert notas.resumen() == {"n": 0, "ultima": None}
r = notas.guardar("  Tengo que mirar el PETG-CF  ")
assert r.startswith("Anotado") and "PETG" not in r, "la respuesta no repite la nota"
assert notas.guardar("Tengo que mirar el PETG-CF").startswith("Anotado") and vivas() == 2, "sin quitar duplicados"
assert db().execute("SELECT texto FROM notas ORDER BY id").fetchone()[0] == "Tengo que mirar el PETG-CF", "se guarda tal cual (solo strip)"
assert notas.guardar("   ").startswith("Error") and notas.guardar(None).startswith("Error")
notas.guardar("el niño pequeño cumple en marzo", etiqueta="Familia numerosa")
assert db().execute("SELECT etiqueta FROM notas WHERE texto LIKE '%niño%'").fetchone()[0] == "familia", "etiqueta: una palabra"
notas.guardar("revisar la boquilla de la Sidewinder")

# ---------- buscar: sin tildes, con vacías, sin reventar ----------
assert any("niño" in f["texto"] for f in notas.buscar("nino")), "sin tilde no encuentra"
assert any("niño" in f["texto"] for f in notas.buscar("NIÑO"))
assert any("boquilla" in f["texto"] for f in notas.buscar("qué dije de la boquilla"))
assert notas.buscar("submarinos") == [] and notas.buscar("") == [] and notas.buscar(None) == []
for veneno in ('comillas " dentro', "d'algo", "guion-medio", "AND OR NEAR", "*", "(((", '"'):
    notas.buscar(veneno)
assert len(notas.buscar("PETG")) == 2

# ---------- listar por fecha ----------
ahora = time.time()
c = db()
c.execute("UPDATE notas SET creada = ? WHERE texto LIKE '%niño%'", (ahora - 3 * 86400,))     # hace 3 días
c.execute("UPDATE notas SET creada = ? WHERE texto LIKE '%boquilla%'", (ahora - 20 * 86400,))  # hace 20 días
c.commit()
assert len(notas.listar()) == 4 and len(notas.listar(n=2)) == 2
assert notas.listar()[0]["creada"] >= notas.listar()[-1]["creada"], "más reciente primero"
assert len(notas.listar("hoy")) == 2, len(notas.listar("hoy"))
assert len(notas.listar("semana")) == 3 and len(notas.listar("esta semana")) == 3
assert len(notas.listar("mes")) == 4
assert notas.listar("ayer") == []
assert notas.listar("loquesea", n="mal") and len(notas.listar(n=999)) == 4

# ---------- el resumen: lo único que sale hacia el panel ----------
res = notas.resumen()
assert set(res) == {"n", "ultima"} and res["n"] == 4 and abs(res["ultima"] - ahora) < 5, res

# ---------- borrar: blando, dice cuál, «la última» ----------
r = notas.borrar("la última")
assert r.startswith("Borrada: «Tengo que mirar el PETG-CF»") and "otras" not in r, r
assert vivas() == 3 and notas.resumen()["n"] == 3
assert "30 días" in r
r = notas.borrar("BOQUILLA")
assert "boquilla" in r and vivas() == 2
assert notas.buscar("boquilla") == [], "borrada no sale en la búsqueda"
assert all("boquilla" not in f["texto"] for f in notas.listar("mes"))
assert "No tengo ninguna nota con eso" in notas.borrar("zzz inexistente")
notas.guardar("otra nota PETG")
notas.guardar("tercera nota PETG")
r = notas.borrar("petg")
assert "tercera nota PETG" in r and "otras 2" in r, "borra la más reciente que coincide y avisa de las demás: " + r
db().execute("UPDATE notas SET borrada_en = NULL")
db().commit()

# ---------- purga a los 30 días ----------
db().execute("UPDATE notas SET borrada_en = ? WHERE texto LIKE '%niño%'", (time.time() - 31 * 86400,))
db().execute("UPDATE notas SET borrada_en = ? WHERE texto LIKE '%boquilla%'", (time.time() - 5 * 86400,))
db().commit()
assert notas.purgar() == 1, "solo la de hace 31 días"
assert db().execute("SELECT count(*) FROM notas WHERE texto LIKE '%niño%'").fetchone()[0] == 0
assert db().execute("SELECT count(*) FROM notas WHERE texto LIKE '%boquilla%'").fetchone()[0] == 1, "la de hace 5 días se conserva"
assert notas.buscar("nino") == [], "la purga también limpia el índice FTS"

# ---------- aislamiento: ni memoria.contexto() ni el panel ni Claude ----------
notas.guardar("SECRETO-DE-LAS-NOTAS-12345")
assert "SECRETO-DE-LAS-NOTAS" not in memoria.contexto(), "la nota NO se inyecta en la memoria"
assert memoria.buscar("SECRETO-DE-LAS-NOTAS-12345") == [], "ni se mezcla con la memoria"
import json  # noqa: E402
assert "SECRETO" not in json.dumps(notas.resumen())
fuentes = {p: Path(p).read_text(encoding="utf-8") for p in ("claude_acp.py", "conectores.py", "panel.py")
           if Path(p).exists()}
assert "notas" not in fuentes.get("claude_acp.py", "").replace("anotas", ""), "Claude Code no toca las notas"
assert "notas" not in fuentes.get("conectores.py", ""), "el puente MCP no toca las notas"
assert "notas.resumen()" in fuentes["panel.py"] and "notas.listar" not in fuentes["panel.py"] \
    and "notas.buscar" not in fuentes["panel.py"], "el panel solo recibe el resumen"

# ---------- git ignora la base (y sus archivos de SQLite) ----------
for f in ("notas.db", "notas.db-wal", "notas.db-shm", "notas.db-journal"):
    assert subprocess.run(["git", "check-ignore", "-q", f], cwd=Path(__file__).parent).returncode == 0, f"{f} no está en .gitignore"

# ---------- enchufado a Delta como acciones de la fusión «memoria», sin herramienta plana nueva ----------
import acciones  # noqa: E402

acciones._notas = notas
for accion in ("nota_guardar", "nota_listar", "nota_buscar", "nota_borrar"):
    assert accion in acciones.FUSIONES["memoria"][2], accion
assert acciones._real("memoria", {"accion": "nota_buscar", "texto": "x"}) == ("nota_buscar", {"consulta": "x"})
assert acciones._real("memoria", {"accion": "nota_borrar", "texto": "x"}) == ("nota_borrar", {"fragmento": "x"})
assert acciones._real("memoria", {"accion": "nota_guardar", "texto": "t"})[0] == "nota_guardar"
assert acciones._real("memoria", {"accion": "recordar", "texto": "t"})[0] == "recordar", "la memoria sigue siendo la memoria"
assert corre(acciones.nota_guardar("probando el enchufe")).startswith("Anotado")
assert "probando el enchufe" in corre(acciones.nota_listar("hoy"))
assert "probando el enchufe" in corre(acciones.nota_buscar("enchufe"))
assert "ninguna" in corre(acciones.nota_buscar("zzz inexistente")).lower()
assert "probando el enchufe" in corre(acciones.nota_borrar("enchufe"))
assert acciones.NOTAS_PRIVADAS >= {"nota_guardar", "nota_listar", "nota_buscar", "nota_borrar"}

print(f"OK: notas — {vivas()} vivas, FTS sin tildes, borrado blando con purga a {notas.PURGA_DIAS} días, aisladas de memoria, panel y Claude")
