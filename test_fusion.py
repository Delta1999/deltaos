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
assert a._real("vista", {"accion": "invisible", "cual": "reloj"}) == ("cambiar_vista", {"modo": "invisible"})
assert a._real("claude", {"accion": "tarea_suelta", "mensaje": "m"}) == ("preguntar_a_claude", {"tarea": "m"})
assert a._real("volumen", {"accion": "subir"}) == ("volumen", {"accion": "subir"})  # las no fusionadas, igual
assert a._real("apuntes", {"accion": "cuadricula", "tipo": "ver"}) == ("apuntes_cuadricula", {"estado": "ver"})
assert a._real("apuntes", {"accion": "subrayar", "texto": "plazo", "color": "amarillo", "pagina_num": "2"}) == ("apuntes_subrayar", {"texto": "plazo", "color": "amarillo", "pagina": "2"})
assert a._real("apuntes", {"accion": "nota", "texto": "ojo", "celda": "F4", "tipo": "aviso", "pagina_num": "1"}) == ("apuntes_nota", {"texto": "ojo", "celda": "F4", "tipo": "aviso", "pagina": "1"})
assert a._real("apuntes", {"accion": "deshacer"}) == ("apuntes_deshacer", {})
assert a._real("apuntes", {"accion": "cursor"}) == ("apuntes_cursor", {})
assert a._real("musica", {"accion": "bailar"})[0] == "musica"
e = asyncio.run(a.HANDLERS["musica"](accion="bailar"))
# sin fijar el orden entero: añadir una acción no debe romper el test, solo el error debe listarlas
assert e.startswith("Error: musica necesita accion =") and "poner" in e and "tele" in e, e
print(f"ok: {len(nombres)} herramientas")
