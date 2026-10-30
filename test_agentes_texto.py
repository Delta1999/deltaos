"""Lo que contesta un agente llega entero (con saltos de línea) a la ficha y a la sala, no recortado a 280 caracteres."""
import agentes

largo = "# Informe\n" + "linea de respuesta larga. " * 100
agentes._nodos.clear(); agentes._eventos.clear()
n = agentes._nodo("x1", nombre="Agente", tipo="sub", modelo="m", t0=1.0, t1=2.0, fin=2.0)
n["texto"] = largo
agentes._evento(2.0, "x1", None, "resultado", largo)
agentes._evento(2.0, "delta", "x1", "encargo", "haz\nalgo " + "x" * 300)
d = agentes._salida(10.0)
nodo = next(x for x in d["nodos"] if x["id"] == "x1")
assert nodo["texto"] == largo.strip() and "\n" in nodo["texto"], len(nodo["texto"])
res = next(e for e in agentes._eventos if e["tipo"] == "resultado")
enc = next(e for e in agentes._eventos if e["tipo"] == "encargo")
assert res["txt"] == largo.strip() and len(enc["txt"]) == 140 and "\n" not in enc["txt"]
print("ok")
