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


def test_combos_de_omniroute():
    import asyncio
    import agentes
    import claude_acp
    assert [x["id"] for x in c.catalogo()["combos"]] == ["claude-code-auto", "combo-code-pro", "combo-deep-reasoning", "combo-fast-completion"]
    for malo in ("auto/best-coding", "../x", "", None, 3):
        assert c.combo_valido(malo) is None, malo
    env = claude_acp._por_combo("combo-code-pro")["claudeCode"]["options"]["settings"]["env"]
    assert env["ANTHROPIC_MODEL"] == "combo-code-pro" and "AUTH_TOKEN" not in str(env), "la clave no se copia: sale de settings.json"
    vistos = []

    async def conv(instruccion, texto, combo=None):
        vistos.append(("claude", combo)); return "Conversación nueva enviada a Claude Code."

    async def mejorar(texto, voz=True, combo=None):
        vistos.append(("cambiar", combo)); return "ok"
    viejo = claude_acp.nueva_conversacion, claude_acp.mejorar_delta
    claude_acp.nueva_conversacion, claude_acp.mejorar_delta = conv, mejorar
    try:
        asyncio.run(agentes.nueva("gen:Plan", "hola", "combo-deep-reasoning"))
        asyncio.run(agentes.nueva("gen:Plan", "hola", "inventado; rm -rf"))
        asyncio.run(agentes.nueva("delta:cambiar", "hola", "combo-fast-completion"))
    finally:
        claude_acp.nueva_conversacion, claude_acp.mejorar_delta = viejo
    assert vistos == [("claude", "combo-deep-reasoning"), ("claude", None), ("cambiar", "combo-fast-completion")], vistos
    print("✓ combos: lista fija, nombres inventados fuera y el elegido llega a Claude Code")


if __name__ == "__main__":
    test_catalogo_tiene_lo_prometido()
    test_arranque_solo_acepta_ids_del_catalogo()
    test_combos_de_omniroute()
