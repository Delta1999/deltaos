"""Una investigación colgada falla y lo dice; mientras, «trabajos» enseña la etapa real (.venv/bin/python test_investigar.py)"""
import asyncio
from pathlib import Path

import acciones
import deltaos

# 21/10: una llamada a Gemini que no volvía dejó la investigación «en curso» 20 min y Delta se inventó «ultimando».
avisos = []
async def avisar(texto, *a, **k):
    avisos.append(texto)
deltaos.avisar = avisar
async def nada():
    return []
deltaos._biblioteca = nada
async def colgada(prompt):
    await asyncio.sleep(3600)
deltaos._json = colgada
deltaos.INVESTIGA_MAX = 0.3


async def main():
    t = asyncio.create_task(deltaos._investigar("skills financieras"))
    await asyncio.sleep(0.1)
    vivo = await acciones.ver_trabajos()
    assert "en curso · preparando" in vivo, vivo  # lo que «¿cómo va?» tiene que mirar, en vez de inventar
    await t
    return await acciones.ver_trabajos()

fin = asyncio.run(main())
assert "falló" in fin and "falló en «preparando»" in fin, fin
assert len(avisos) == 1 and "ha fallado" in avisos[0] and "no hay informe" in avisos[0], avisos
assert "NUNCA inventes" in Path("deltaos.py").read_text(), "la respuesta de investigar le dice que mire trabajos"

print("OK: la investigación colgada falla con aviso, y trabajos enseña su etapa")
