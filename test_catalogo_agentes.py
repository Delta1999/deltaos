"""Catálogo y arranque del selector «Nueva conversación» (.venv/bin/python test_catalogo_agentes.py)"""
import agentes_catalogo as c


def test_catalogo_tiene_lo_prometido():
    cat = c.catalogo()
    nombres = {a["n"] for a in cat["claude"]["agentes"]}
    assert {"general-purpose", "Explore", "Plan"} <= nombres, nombres
    assert {m["n"] for m in cat["claude"]["modos"]} == {"Workflow", "Juez"}
    assert len(cat["delta"]) == 3
    assert all(x["d"] for x in cat["claude"]["agentes"] + cat["claude"]["modos"] + cat["delta"]), "toda opción lleva su explicación"
    print("✓ catálogo: genéricos, modos y Delta con descripción")


def test_arranque_solo_acepta_ids_del_catalogo():
    assert c.arranque("modo:juez")[0] == "claude" and "JUEZ" in c.arranque("modo:juez")[1]
    assert "Workflow" in c.arranque("modo:workflow")[1] and "EXPRESAMENTE" in c.arranque("modo:workflow")[1]
    assert c.arranque("gen:Plan")[1].count("Plan") >= 1
    assert c.arranque("delta:cherry") == ("delta", "cherry", "cherry")
    for malo in ("fw:../../etc", "esp:no-existe", "modo:otro", "delta:rm", "xx:yy", "", "../x"):
        assert c.arranque(malo) is None, malo
    print("✓ arranque: ids válidos sí, rutas e ids inventados no")


if __name__ == "__main__":
    test_catalogo_tiene_lo_prometido()
    test_arranque_solo_acepta_ids_del_catalogo()
