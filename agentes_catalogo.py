"""Catálogo del selector «Nueva conversación» de la pantalla Agentes.

Qué se puede lanzar: agentes genéricos y especialistas de Claude Code, frameworks (plugins con agentes, skills de
consejo/debate), los modos Workflow y Juez, y las vías hacia Delta. Se lee del disco cada vez, así que no se queda
anticuado. El navegador solo manda el id elegido; el texto de arranque se construye aquí (nunca se fía de una ruta del cliente).
"""
import json
import re
import sqlite3
from pathlib import Path

HOME = Path.home()
CLAUDE = HOME / ".claude"
ESCRITORIO = HOME / ".config" / "Claude" / "local-agent-mode-sessions"
WORMHOLE_AGENTES = HOME / "Escritorio" / "WORMHOLE" / ".claude" / "agents"
SKILLS_MARCO = re.compile(r"council|arena|debate|judge|juez", re.I)  # skills de consejo/debate que cuentan como framework

GENERICOS = [
    ("general-purpose", "Agente para todo: investiga, busca código y ejecuta tareas de varios pasos."),
    ("Explore", "Solo lectura: barre muchos ficheros y carpetas y devuelve la conclusión, sin editar nada."),
    ("Plan", "Arquitecto: diseña el plan de implementación, los ficheros críticos y las alternativas."),
]

MODOS = [
    ("workflow", "Workflow",
     "Orquestación multiagente: reparte la tarea entre varios subagentes con un script (herramienta Workflow). "
     "Equivale a pedírselo tú expresamente; gasta bastantes tokens.",
     "El usuario pide EXPRESAMENTE trabajar en modo Workflow: orquesta esta tarea con varios subagentes mediante la "
     "herramienta Workflow (carga antes la skill workflow-authoring). Si no está disponible, reparte el trabajo con la "
     "herramienta Agent en paralelo. Verifica el resultado antes de darlo por bueno."),
    ("juez", "Juez",
     "Varios agentes hacen el trabajo y un juez independiente, que no ve su razonamiento, da luz VERDE o ROJA con motivos concretos.",
     "Trabaja en modo Juez: 1) lanza con la herramienta Agent uno o varios subagentes que hagan la tarea; 2) lanza un subagente "
     "JUEZ nuevo que reciba SOLO la petición original, los criterios de éxito y el resultado (nunca el razonamiento de los demás); "
     "3) el juez responde VERDE (cumple) o ROJA (no cumple) con una lista de defectos concretos; 4) si es ROJA, corrige y vuelve a "
     "juzgar, como máximo dos rondas; 5) informa al usuario del veredicto final y de lo que se hizo."),
]

# Combos de OmniRoute que se pueden elegir tras Claude Code o DeltaOS (30/10/2026). «defecto» = sin combo: Claude Code va directo
# a Claude con el login y «Cambiar algo de Delta» usa ~/.claude/settings.json. El cliente solo manda el nombre: se valida aquí.
COMBOS = [("claude-code-auto", "Claude Code Auto"), ("combo-code-pro", "Code Pro"),
          ("combo-deep-reasoning", "Deep Reasoning"), ("combo-fast-completion", "Fast Completion")]
OMNI_BD = HOME / ".omniroute" / "storage.sqlite"


def _omniroute():
    """(modelos de cada combo en el orden en que OmniRoute los prueba, combo al que desvía lo que detecta como código o None).
    Base de OmniRoute en solo lectura. El desvío es su «enrutado por tarea» (30/10/2026: el usuario lo deja activado): pisa el
    modelo pedido, y como el prompt de Claude Code siempre parece código, sus sesiones acaban en ese combo."""
    try:
        con = sqlite3.connect(f"file:{OMNI_BD}?mode=ro", uri=True, timeout=2)
        try:
            cad = {n: [m.get("model", "") for m in json.loads(d).get("models", [])] for n, d in con.execute("SELECT name, data FROM combos")}
            f = con.execute("SELECT value FROM key_value WHERE namespace='settings' AND key='taskRouting'").fetchone()
        finally:
            con.close()
        tr = json.loads(f[0]) if f else {}
        return cad, (tr.get("taskModelMap", {}).get("coding") or None) if tr.get("enabled") and tr.get("detectionEnabled") else None
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        return {}, None


def combos():
    cad, desvio = _omniroute()
    ojo = f" · Ojo: OmniRoute manda lo que ve como código a {desvio}, así que Claude Code acaba ahí." if desvio else ""
    return [{"id": i, "n": n, "d": ("Prueba por orden: " + " → ".join(m.split("/")[-1] for m in cad[i][:4]) + (" …" if len(cad[i]) > 4 else "")
                                    if cad.get(i) else "Combo de OmniRoute.") + (ojo if i != desvio else "")} for i, n in COMBOS], desvio


def combo_valido(c):
    return c if c in {i for i, _ in COMBOS} else None


DELTA = [
    ("hablar", "Hablar con Delta", "Le dice algo a Delta (Gemini Live) como si se lo dijeras por voz; tiene que estar despierto."),
    ("cambiar", "Cambiar algo de Delta", "Claude Code modifica el propio repositorio de Delta y lo deja registrado en CAMBIOS_DELTA.md."),
    ("cherry", "Plan B: Cherry", "Pasa la tarea a Cherry cuando Claude Code se queda sin tokens."),
]


def _front(txt):
    m = re.match(r"---\s*\n(.*?)\n---", txt, re.S)
    d, clave = {}, None
    for linea in (m.group(1).splitlines() if m else []):
        k = re.match(r"([A-Za-z_-]+):\s*(.*)$", linea)
        if k and not linea.startswith(" "):
            clave = k.group(1)
            d[clave] = k.group(2).strip().strip("\"'")
            if d[clave] in ("|", ">", "|-", ">-"):
                d[clave] = ""
        elif clave and linea.strip():
            d[clave] += " " + linea.strip()
    return d


def _resumen(txt, n=300):
    t = re.sub(r"<example>.*", "", str(txt or ""), flags=re.S).replace("\\n", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[:n - 1] + "…"


def _leer_md(ruta):
    try:
        return _front(Path(ruta).read_text(encoding="utf-8", errors="replace")[:4000])
    except OSError:
        return {}


def _especialistas():
    vistos, res = set(), []
    for carpeta in (CLAUDE / "agents", WORMHOLE_AGENTES):
        for f in sorted(carpeta.glob("*.md")) if carpeta.is_dir() else []:
            fm = _leer_md(f)
            nombre = fm.get("name") or f.stem
            if nombre not in vistos:
                vistos.add(nombre)
                res.append({"id": f"esp:{nombre}", "n": nombre, "d": _resumen(fm.get("description")), "g": "especialista"})
    return res


def _raices_plugins():
    """Carpetas de plugins con agentes: los de la app de escritorio (gangsta, agentic-council, ruflo…) y los activados en ~/.claude."""
    raices = {}
    for pj in sorted(ESCRITORIO.glob("*/*/rpm/plugin_*/.claude-plugin/plugin.json"), key=lambda p: p.stat().st_mtime):
        try:
            raices[json.loads(pj.read_text()).get("name") or pj.parent.parent.name] = (pj.parent.parent, json.loads(pj.read_text()))
        except (OSError, ValueError):
            pass
    try:
        activos = [k for k, v in json.loads((CLAUDE / "settings.json").read_text()).get("enabledPlugins", {}).items() if v]
        instalados = json.loads((CLAUDE / "plugins" / "installed_plugins.json").read_text())
        instalados = instalados.get("plugins", instalados)
        for clave in activos:
            for it in instalados.get(clave, [])[:1]:
                raiz = Path(it.get("installPath", ""))
                pj = raiz / ".claude-plugin" / "plugin.json"
                if pj.is_file():
                    info = json.loads(pj.read_text())
                    raices.setdefault(info.get("name") or clave.split("@")[0], (raiz, info))
    except (OSError, ValueError, AttributeError):
        pass
    return raices


def _frameworks():
    res = []
    for nombre, (raiz, info) in sorted(_raices_plugins().items()):
        agentes = sorted((raiz / "agents").glob("*.md")) if (raiz / "agents").is_dir() else []
        if agentes:
            res.append({"id": f"fw:{nombre}", "n": nombre, "g": "framework", "ruta": str(raiz),
                        "d": _resumen(info.get("description")) + f" ({len(agentes)} agentes)"})
    skills = CLAUDE / "skills"
    for d in sorted(skills.iterdir()) if skills.is_dir() else []:
        if SKILLS_MARCO.search(d.name) and (d / "SKILL.md").is_file():
            res.append({"id": f"fw:{d.name}", "n": d.name, "g": "framework", "ruta": str(d),
                        "d": _resumen(_leer_md(d / "SKILL.md").get("description")) or "Skill de consejo o debate instalada por el usuario."})
    return res


def catalogo():
    return {
        "claude": {
            "agentes": [{"id": f"gen:{n}", "n": n, "d": d, "g": "genérico"} for n, d in GENERICOS] + _especialistas(),
            "frameworks": _frameworks(),
            "modos": [{"id": f"modo:{i}", "n": n, "d": d, "g": "modo"} for i, n, d, _ in MODOS],
        },
        "delta": [{"id": f"delta:{i}", "n": n, "d": d, "g": "delta"} for i, n, d in DELTA],
    } | dict(zip(("combos", "desvio"), combos()))


def arranque(id_):
    """(cliente, instrucción inicial, etiqueta) del id elegido, o None si no existe en el catálogo."""
    tipo, _, nombre = str(id_).partition(":")
    if tipo == "delta":
        return ("delta", nombre, nombre) if nombre in {i for i, _, _ in DELTA} else None
    cat = catalogo()["claude"]
    if tipo == "modo":
        for i, n, _, texto in MODOS:
            if i == nombre:
                return ("claude", texto, n)
    elif tipo in ("gen", "esp"):
        if any(a["id"] == id_ for a in cat["agentes"]):
            return ("claude", f"Para esta conversación trabaja a través del subagente «{nombre}» (herramienta Agent con "
                              f"subagent_type={nombre}): delega en él la tarea y verifica su resultado antes de darla por buena.", nombre)
    elif tipo == "fw":
        fw = next((f for f in cat["frameworks"] if f["id"] == id_), None)
        if fw:
            ruta = fw["ruta"]
            return ("claude", f"Trabaja con el framework «{nombre}», instalado en {ruta}. Lee su README o SKILL.md y las skills y agentes "
                              f"(carpetas skills/ y agents/ de esa ruta) que apliquen a la tarea, y orquesta a sus agentes con la herramienta "
                              f"Agent; si un agente no está registrado, pásale el contenido de su fichero .md como rol. Verifica el resultado.", nombre)
    return None
