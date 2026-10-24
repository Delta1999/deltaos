"""Pruebas de integración del Visor de Apuntes con Delta (Gemini Live)."""
import asyncio
import inspect
from pathlib import Path

import acciones
import visor_delta

AQUI = Path(__file__).parent


async def test_visor_integracion():
    print("1. Probando asegurar_servidor()...")
    listo = await visor_delta.asegurar_servidor()
    assert listo, "El servidor del visor de apuntes no está listo en el puerto 8766"

    print("2. Probando obtener_contexto()...")
    ctx = await visor_delta.obtener_contexto()
    assert "page" in ctx and "nearest_cell" in ctx, f"Contexto inválido: {ctx}"
    print(f"   Contexto detectado: pág {ctx.get('page')}, celda {ctx.get('nearest_cell')}")

    print("3. Probando cuadrícula...")
    r_on = await visor_delta.apuntes_cuadricula("ver")
    assert "activada" in r_on, r_on
    r_off = await visor_delta.apuntes_cuadricula("ocultar")
    assert "desactivada" in r_off, r_off

    print("4. Probando subrayado...")
    r_sub = await visor_delta.apuntes_subrayar(texto="Procedimiento", color="amarillo", pagina="1")
    assert "Subrayado" in r_sub, r_sub

    # Subrayado por contexto (si no pasa texto)
    r_sub_ctx = await visor_delta.apuntes_subrayar(texto="esto")
    assert "Subrayado" in r_sub_ctx or "No he detectado" in r_sub_ctx, r_sub_ctx

    print("5. Probando esquema con Dagre...")
    r_esq = await visor_delta.apuntes_esquema(
        titulo="Fases del Procedimiento",
        celda="E2",
        nodos="Iniciación, Instrucción, Finalización",
        pagina="1"
    )
    assert "Esquema" in r_esq and "creado" in r_esq, r_esq

    print("6. Probando añadir rama...")
    r_ram = await visor_delta.apuntes_rama(
        nodo_padre="root",
        nuevo_nodo="Recursos y Ejecución",
        pagina="1"
    )
    assert "Rama" in r_ram and "conectada" in r_ram, r_ram

    print("7. Probando nota al margen...")
    r_nota = await visor_delta.apuntes_nota(
        texto="Plazo general: 3 meses para resolver.",
        celda="F6",
        tipo="aviso",
        pagina="1"
    )
    assert "Aviso" in r_nota and "añadido" in r_nota, r_nota

    print("8. Probando modo repaso activo...")
    r_rep = await visor_delta.apuntes_repaso("activar")
    assert "activado" in r_rep, r_rep
    r_rep_off = await visor_delta.apuntes_repaso("desactivar")
    assert "desactivado" in r_rep_off, r_rep_off

    print("9. Probando salto de página...")
    r_pag = await visor_delta.apuntes_pagina(1)
    assert "Navegando" in r_pag, r_pag

    print("10. Probando deshacer...")
    r_undo = await visor_delta.apuntes_deshacer()
    assert "deshecha" in r_undo, r_undo

    print("11. Probando cursor...")
    r_cur = await visor_delta.apuntes_cursor()
    assert "celda" in r_cur, r_cur

    print("12. Probando exportación vectorial con PyMuPDF...")
    r_exp = await visor_delta.apuntes_exportar("sample.pdf")
    assert "PDF exportado correctamente" in r_exp, r_exp
    anotado = AQUI / "visor_apuntes" / "storage" / "sample_anotado.pdf"
    assert anotado.exists(), "sample_anotado.pdf no fue generado"

    print("\n✅ Todos los tests del visor y comandos de voz han pasado con éxito.")


if __name__ == "__main__":
    asyncio.run(test_visor_integracion())
