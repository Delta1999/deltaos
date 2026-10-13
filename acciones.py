"""Herramientas (function calling) que Gemini puede invocar."""
import asyncio
import os
import shutil
import subprocess
from pathlib import Path

from google.genai import types

WORMHOLE = Path.home() / "Escritorio" / "WORMHOLE"
TOOLS_DIR = WORMHOLE / "tools"
MAX_OUT = 4000

S = types.Schema
STR = types.Type.STRING


def _fn(name, desc, props, behavior=None):
    return types.FunctionDeclaration(
        name=name, description=desc, behavior=behavior,
        parameters=S(type=types.Type.OBJECT, properties=props, required=list(props)))


NB = types.Behavior.NON_BLOCKING
DECLARATIONS = [
    _fn("abrir", "Abre una URL, un archivo/carpeta, o una aplicación por su id .desktop (p.ej. firefox, org.kde.dolphin).",
        {"objetivo": S(type=STR, description="URL, ruta o id de la aplicación")}),
    _fn("ejecutar_herramienta_wormhole",
        "Ejecuta un script de WORMHOLE/tools (cadcheck, render_views, slice_check, stl_audit...) con el venv CAD.",
        {"script": S(type=STR, description="nombre del script, con o sin .py"),
         "args": S(type=STR, description="argumentos separados por espacios, puede ser vacío")}, NB),
    _fn("ejecutar_shell", "Ejecuta un comando de shell en el PC del usuario. Pide confirmación al usuario en la terminal.",
        {"comando": S(type=STR, description="comando completo")}, NB),
    _fn("preguntar_a_claude",
        "Delega una tarea de código, CAD o análisis en Claude Code (corre en el repo WORMHOLE y puede editar archivos). Pide confirmación.",
        {"tarea": S(type=STR, description="instrucción completa y autocontenida")}, NB),
]

TOOLS = [types.Tool(google_search=types.GoogleSearch()),
         types.Tool(function_declarations=DECLARATIONS)]


def _clip(s: str) -> str:
    s = s.strip()
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + "\n...[recortado]"


async def _run(argv, cwd=None, timeout=60, shell=False):
    p = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        return f"[timeout tras {timeout}s]"
    return f"[código {p.returncode}]\n" + _clip(out.decode(errors="replace"))


async def _confirmar(texto: str) -> bool:
    print(f"\n⚠️  Gemini quiere: {texto}\n   ¿Permitir? [s/N] ", end="", flush=True)
    resp = await asyncio.to_thread(input)
    return resp.strip().lower() in ("s", "si", "sí", "y", "yes")


async def abrir(objetivo):
    if "/" in objetivo or ":" in objetivo:
        argv = ["xdg-open", objetivo]
    else:
        argv = ["gtk-launch", objetivo]
    subprocess.Popen(argv, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Abriendo {objetivo}"


async def ejecutar_herramienta_wormhole(script, args=""):
    name = Path(script).stem
    path = TOOLS_DIR / f"{name}.py"
    if not path.is_file():
        return f"No existe {name}.py. Disponibles: " + ", ".join(p.stem for p in sorted(TOOLS_DIR.glob("*.py")))
    py = WORMHOLE / ".venv-cad" / "bin" / "python"
    return await _run([str(py), str(path), *args.split()], cwd=WORMHOLE, timeout=300)


async def ejecutar_shell(comando):
    if not await _confirmar(f"ejecutar `{comando}`"):
        return "El usuario denegó la ejecución."
    return await _run(["bash", "-lc", comando], timeout=60)


async def preguntar_a_claude(tarea):
    if not await _confirmar(f"delegar en Claude Code: {tarea}"):
        return "El usuario denegó la tarea."
    if not shutil.which("claude"):
        return "claude no está en el PATH."
    return await _run(["claude", "-p", tarea, "--permission-mode", "acceptEdits"],
                      cwd=WORMHOLE, timeout=600)


HANDLERS = {f.__name__: f for f in (abrir, ejecutar_herramienta_wormhole, ejecutar_shell, preguntar_a_claude)}


async def atender(session, tool_call):
    """Ejecuta las llamadas de un tool_call y devuelve las respuestas a Gemini."""
    for fc in tool_call.function_calls:
        print(f"\n🔧 {fc.name}({dict(fc.args or {})})")
        try:
            out = await HANDLERS[fc.name](**(fc.args or {}))
        except Exception as e:
            out = f"Error: {e}"
        await session.send_tool_response(function_responses=[
            types.FunctionResponse(id=fc.id, name=fc.name, response={"output": out})])
