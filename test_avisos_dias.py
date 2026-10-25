"""Avisos con día («jueves 17:30», «mañana 09:00»): Delta no sabe qué día es hoy, así que lo resuelve el código
(.venv/bin/python test_avisos_dias.py)"""
import asyncio
from datetime import datetime

import avisos

A = datetime(2026, 10, 25, 20, 30)          # domingo
f = lambda x: avisos.cuando("", x, A).strftime("%d/%m %H:%M")
for dicho, esperado in {
    "jueves 17:30": "29/10 17:30", "el jueves a las 17:30": "29/10 17:30", "Jueves 17.30": "29/10 17:30",
    "miércoles 8h30": "28/10 08:30", "sábado a las 9": "31/10 09:00",
    "mañana 09:00": "26/10 09:00", "pasado mañana 10": "27/10 10:00", "hoy 21:00": "25/10 21:00",
    "domingo 21:00": "25/10 21:00",           # hoy es domingo y aún no son las 21:00
    "domingo 20:00": "01/11 20:00",           # ya pasó: el de la semana que viene
    "22:00": "25/10 22:00", "07:00": "26/10 07:00", "2026-11-02 10:00": "02/11 10:00",   # los formatos de siempre siguen igual
}.items():
    assert f(dicho) == esperado, (dicho, f(dicho), esperado)
for mal in ("jueves 25:00", "jueves", "algún día", "jueves 17:75"):
    try:
        f(mal)
    except ValueError:
        continue
    raise AssertionError(f"«{mal}» debería dar error")
assert avisos.cuando("5", "", A).strftime("%H:%M") == "20:35", "en_minutos sigue funcionando"

# una hora de hoy que ya pasó no se programa (saldría disparada al instante)
avisos.FICHERO = avisos.Path(__import__("tempfile").mkdtemp()) / "a.json"
assert asyncio.run(avisos.programar_aviso("x", a_las="2020-01-01 10:00")).startswith("Error")
# ---------- lo que recibe la línea de la semana del panel ----------
import panel  # noqa: E402

lista = [{"t": "2026-10-29T17:30:00", "texto": "médico", "tipo": "aviso", "diario": False},
         {"t": "2026-10-26T07:00:00", "texto": "despertar", "tipo": "alarma", "diario": True},
         {"t": "2026-11-05T10:00:00", "texto": "lejos", "tipo": "aviso", "diario": False},
         {"t": "basura", "texto": "x", "tipo": "aviso"}]
sem = panel._semana(lista, A)
assert [x["texto"] for x in sem if x["texto"] != "despertar"] == ["médico"], sem
assert [x["t"] for x in sem if x["texto"] == "despertar"] == [f"2026-10-{d} 07:00" for d in (26, 27, 28, 29, 30, 31)], sem
assert all(x["t"] < "2026-11-01" for x in sem), "ni un día más allá de los 7"
assert sem == sorted(sem, key=lambda x: x["t"]) and sem[0]["texto"] == "despertar" and sem[0]["tipo"] == "alarma"
assert panel._semana([], A) == [] and len(panel._semana([{"t": "2026-10-25T21:00:00", "texto": "d", "diario": True}] * 40, A)) <= 60
print("OK: avisos con día de la semana")
