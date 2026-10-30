"""Revisión independiente de mejorar_delta (.venv/bin/python test_revision_delta.py)"""
import revision_delta as r


def test_veredicto_nunca_se_inventa_verde():
    assert r.veredicto("VEREDICTO: VERDE\nTodo bien.")[0] == "VERDE"
    assert r.veredicto("**VEREDICTO: ROJA**\n- a.py falla")[0] == "ROJA"
    assert r.veredicto("Me parece bien, adelante")[0] is None
    assert r.veredicto("")[0] is None and r.veredicto(None)[0] is None
    assert "falla" in r.veredicto("VEREDICTO: ROJA\n- a.py falla")[1]
    print("✓ veredicto: VERDE/ROJA solo si el revisor lo dice; sin formato = sin veredicto")


def test_prompt_lleva_peticion_diff_y_recorta():
    p = r.prompt("arregla X", "+línea nueva", [("n.py", "print(1)")])
    assert "arregla X" in p and "+línea nueva" in p and "FICHERO NUEVO n.py" in p and "VEREDICTO: VERDE" in p
    grande = r.prompt("x", "a" * (r.MAX_DIFF + 500), [])
    assert "recortado" in grande and len(grande) < len(r.REVISOR) + r.MAX_DIFF + 300
    assert "sin cambios" in r.prompt("x", "", [])
    print("✓ prompt: petición, diff y ficheros nuevos; el diff grande se recorta")


def test_sesiones_del_selector_y_revision_van_a_claude_real():
    import claude_acp
    env = claude_acp.CLAUDE_REAL["claudeCode"]["options"]["settings"]["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
    assert all(env[k] == "" for k in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"))
    src = open("claude_acp.py").read()
    assert src.count("**CLAUDE_REAL") == 2  # selector (conversación nueva) y revisión; mejorar_delta/hablar_con_claude no
    print("✓ selector y revisión: sesión directa a Claude (pisa el env de OmniRoute de settings.json)")


if __name__ == "__main__":
    test_veredicto_nunca_se_inventa_verde()
    test_prompt_lleva_peticion_diff_y_recorta()
    test_sesiones_del_selector_y_revision_van_a_claude_real()
