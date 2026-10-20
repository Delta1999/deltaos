"""Herramientas fusionadas por tema (sin API): .venv/bin/python test_fusion.py"""
import asyncio
import inspect

import assistant  # noqa: F401  (registra todos los módulos y fusiona, igual que al arrancar)
import acciones as a

nombres = [d.name for d in a.DECLARATIONS]
assert len(nombres) == len(set(nombres)), "herramienta declarada dos veces"
for f, (_, props, ramas) in a.FUSIONES.items():
    assert f in nombres and f in a.HANDLERS, f
    for accion, (real, ren, fijo) in ramas.items():
        assert real in a.HANDLERS and real not in nombres, (f, accion, real)
        acepta = inspect.signature(a.HANDLERS[real]).parameters
        assert set(ren) | set(fijo) <= set(acepta), (f, accion, real)
        assert set(ren.values()) <= set(props), (f, accion, ren)  # el parámetro fusionado está declarado
# todo handler declarado existe
assert all(n in a.HANDLERS for n in nombres)

assert a._real("musica", {"accion": "pausa"}) == ("controlar_musica", {"accion": "pausa"})
assert a._real("musica", {"accion": "poner", "busqueda": "lofi"}) == ("poner_musica", {"busqueda": "lofi"})
assert a._real("memoria", {"accion": "recordar", "texto": "x"}) == ("recordar", {"nota": "x"})
assert a._real("avisos", {"accion": "cancelar", "texto": "pizza", "tipo": "alarma"}) == ("cancelar_aviso", {"cual": "pizza"})
assert a._real("vista", {"accion": "mascota", "cual": "reloj"}) == ("cambiar_vista", {"modo": "mascota"})
assert a._real("vista", {"accion": "elegir_mascota", "cual": "gato"}) == ("elegir_mascota", {"cual": "gato"})
assert a._real("claude", {"accion": "tarea_suelta", "mensaje": "m"}) == ("preguntar_a_claude", {"tarea": "m"})
assert a._real("volumen", {"accion": "subir"}) == ("volumen", {"accion": "subir"})  # las no fusionadas, igual
assert a._real("musica", {"accion": "bailar"})[0] == "musica"
assert asyncio.run(a.HANDLERS["musica"](accion="bailar")).startswith("Error: musica necesita accion = poner | pausa")
print(f"ok: {len(nombres)} herramientas")
