"""El puente MCP de punta a punta contra un servidor de verdad (.venv/bin/python test_mcp.py)"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import mcp_puente

SERVIDOR = '''
from mcp.server.mcpserver import MCPServer

m = MCPServer("prueba")


@m.tool()
def sumar(a: int, b: int) -> int:
    """Suma dos numeros."""
    return a + b


m.run()
'''


async def main():
    d = Path(tempfile.mkdtemp(prefix="delta-mcp-"))
    (d / "servidor.py").write_text(SERVIDOR)
    mcp_puente.CONFIG = d / "mcp.json"
    mcp_puente.CONFIG.write_text(json.dumps({
        "prueba": {"comando": [sys.executable, str(d / "servidor.py")]},
        "_nota": {"comando": "no arranco, empiezo por _"},
        "apagado": {"comando": "no arranco, activo=false", "activo": False},
    }))

    tarea = asyncio.create_task(mcp_puente.vigilar())
    try:
        cat = await mcp_puente.conectores("listar")
        assert "prueba: sumar — Suma dos numeros." in cat, cat
        assert "apagado" not in cat and "_nota" not in cat, cat  # apagado y comentario, fuera

        # El camino bueno.
        assert (await mcp_puente.conectores("usar", "prueba", "sumar", '{"a": 2, "b": 40}')).strip() == "42"

        # Sin servidor, si el nombre es único, se resuelve solo (el modelo lo omite a menudo).
        assert (await mcp_puente.conectores("usar", herramienta="sumar", argumentos='{"a": 1, "b": 1}')).strip() == "2"
        # Y con el nombre entero en «herramienta», también.
        assert (await mcp_puente.conectores("usar", herramienta="prueba.sumar", argumentos='{"a": 3, "b": 4}')).strip() == "7"

        # Los errores que puede cometer el modelo salen explicados, no como excepción.
        assert "objeto JSON" in await mcp_puente.conectores("usar", "prueba", "sumar", "a=2 b=40")
        assert "no existe" in await mcp_puente.conectores("usar", "prueba", "restar", "{}")
        assert "necesita herramienta" in await mcp_puente.conectores("usar", "prueba")
        assert "accion = listar | usar" in await mcp_puente.conectores("bailar")
        # Argumentos que el servidor rechaza: error del conector, no caída del puente.
        assert "Error" in await mcp_puente.conectores("usar", "prueba", "sumar", '{"a": "hola"}')

        # El paso del panel queda con el detalle, sin añadir una línea de más.
        mcp_puente.acciones.ST["pasos"] = [{"t": mcp_puente.acciones.ETIQUETAS["conectores"] + " · usar", "e": "en curso"}]
        await mcp_puente.conectores("usar", "prueba", "sumar", '{"a": 1, "b": 2}')
        pasos = mcp_puente.acciones.ST["pasos"]
        assert len(pasos) == 1 and pasos[-1]["t"].endswith("prueba: sumar"), pasos
    finally:
        tarea.cancel()
        await asyncio.gather(tarea, return_exceptions=True)

    print("OK: el puente MCP lista, llama y explica sus errores")


asyncio.run(main())
