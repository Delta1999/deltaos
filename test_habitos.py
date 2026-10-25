"""Calendario de hábitos (.venv/bin/python test_habitos.py)
Alta y orden de hábitos, los tres estados de una casilla, los motivos con su color, el resumen hablado,
las fechas y meses dichos de palabra, y que la API del panel devuelva el mes ya pintado."""
import asyncio
import tempfile
from datetime import date, timedelta
from pathlib import Path

import habitos

# Base de usar y tirar: el test no toca el calendario de verdad.
habitos.BD = Path(tempfile.mkdtemp()) / "h.db"
habitos._con = None
corre = lambda c: asyncio.run(c)
hoy = date.today()
ayer = (hoy - timedelta(days=1)).isoformat()

# ---------- fechas y meses dichos de palabra ----------
assert habitos._dia("") == habitos._dia("hoy") == hoy.isoformat()
assert habitos._dia("ayer") == ayer
assert habitos._dia("2026-03-07") == "2026-03-07"
assert habitos._dia(str(hoy.day)) == hoy.isoformat(), "«el 25» es el 25 de este mes"
assert habitos._dia("no es una fecha") == hoy.isoformat(), "lo que no entiendo, hoy"
assert habitos._mes("2026-03") == (2026, 3) and habitos._mes("marzo") == (hoy.year, 3)
assert habitos._mes("") == (hoy.year, hoy.month)
assert habitos._mes("el mes pasado") == ((hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12))

# ---------- alta, orden y límite ----------
gim = habitos.anadir_habito("Gimnasio", "#5B9BF6")
leer = habitos.anadir_habito("Leer 20 min")
assert [h["nombre"] for h in habitos.datos_mes(hoy.year, hoy.month)["habitos"]] == ["Gimnasio", "Leer 20 min"]
try:
    habitos.anadir_habito("gimnasio")  # el mismo sin mayúsculas
    raise AssertionError("ha dejado repetir un hábito")
except ValueError:
    pass
habitos.mover_habito(leer, -1)
assert [h["nombre"] for h in habitos.datos_mes(hoy.year, hoy.month)["habitos"]] == ["Leer 20 min", "Gimnasio"], "no sube"
habitos.mover_habito(leer, 1)

# ---------- los tres estados de una casilla ----------
d = habitos.datos_mes(hoy.year, hoy.month)
assert f"{gim}:{hoy.isoformat()}" not in d["marcas"], "nace vacía"
habitos.marcar(gim, hoy.isoformat(), True)
assert habitos.datos_mes(hoy.year, hoy.month)["marcas"][f"{gim}:{hoy.isoformat()}"]["hecho"] == 1
enfermo = habitos._buscar_motivo("enfermo")
habitos.marcar(gim, ayer, False, enfermo["id"])
m = habitos.datos_mes(hoy.year, hoy.month)["marcas"].get(f"{gim}:{ayer}")
if m:  # ayer puede caer en el mes anterior
    assert m["hecho"] == 0 and m["motivo"] == enfermo["id"]
habitos.marcar(gim, hoy.isoformat(), None)
assert f"{gim}:{hoy.isoformat()}" not in habitos.datos_mes(hoy.year, hoy.month)["marcas"], "no vuelve a vacía"

# ---------- marcar de palabra ----------
r = corre(habitos.habitos_marcar("gimnasio", "si"))
assert "hecho" in r and habitos.datos_mes(hoy.year, hoy.month)["marcas"][f"{gim}:{hoy.isoformat()}"]["hecho"] == 1
assert "No tengo ningún hábito" in corre(habitos.habitos_marcar("pilates", "si")), "no inventa hábitos"
r = corre(habitos.habitos_marcar("leer", "no", "pereza"))
assert "NO hecho" in r and "pereza" in r
mk = habitos.datos_mes(hoy.year, hoy.month)["marcas"][f"{leer}:{hoy.isoformat()}"]
assert mk["hecho"] == 0 and mk["motivo"] == habitos._buscar_motivo("pereza")["id"]
corre(habitos.habitos_marcar("leer", "no", "se fue la luz"))  # motivo nuevo: se da de alta solo
assert habitos._buscar_motivo("se fue la luz"), "un motivo que no existía no se ha creado"
assert "Quitada" in corre(habitos.habitos_marcar("leer", "quitar"))
assert f"{leer}:{hoy.isoformat()}" not in habitos.datos_mes(hoy.year, hoy.month)["marcas"]

# ---------- racha y resumen hablado ----------
for i in range(3):
    habitos.marcar(gim, (hoy - timedelta(days=i)).isoformat(), True)
assert habitos._racha(gim) == 3, f"racha mal: {habitos._racha(gim)}"
habitos.marcar(gim, (hoy - timedelta(days=3)).isoformat(), False, enfermo["id"])
assert habitos._racha(gim) == 3, "un «no» corta la racha, no la borra"
texto = corre(habitos.habitos_resumen("", "gimnasio"))
assert "Gimnasio" in texto and "racha de 3" in texto, texto
assert "Leer" not in texto, "con un hábito pedido, no cuenta los demás"
assert "Leer" in corre(habitos.habitos_resumen()), "sin hábito, todos"

# ---------- configurar de palabra ----------
assert "añadido" in corre(habitos.habitos_configurar("anadir", "Meditar"))
assert "Meditar" in corre(habitos.habitos_configurar("listar"))
assert "Meditar" in corre(habitos.habitos_configurar("quitar", "meditar"))
assert "Meditar" not in corre(habitos.habitos_configurar("listar"))
assert "Error" in corre(habitos.habitos_configurar("hacer el pino")), "acción desconocida"

# ---------- lo que recibe la página ----------
d = habitos.datos_mes(hoy.year, hoy.month)
assert d["dias"] in (28, 29, 30, 31) and 0 <= d["primer_dia"] <= 6
assert d["hoy"] == hoy.isoformat()
assert all(set(h) >= {"id", "nombre", "color", "si", "no", "racha"} for h in d["habitos"])
assert all(mo["color"].startswith("#") for mo in d["motivos"]), "cada motivo con su color"

# ---------- los datos no salen de aquí ----------
import ast
import inspect
arbol = ast.parse(inspect.getsource(habitos))
importa = {a.name.split(".")[0] for n in ast.walk(arbol) if isinstance(n, ast.Import) for a in n.names} | \
          {n.module.split(".")[0] for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom) and n.module}
assert not importa & {"memoria", "notas", "claude_acp", "mcp_puente"}, f"no debe tocar {importa}"
assert "contexto" not in inspect.getsource(habitos.registrar), "no se engancha a ningún contexto"

print("✅ test_habitos OK")
