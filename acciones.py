"""Herramientas (function calling) que Gemini puede invocar + estado compartido."""
import asyncio
import httpx
import shutil
import subprocess
import time
from pathlib import Path

from google.genai import types

AQUI = Path(__file__).resolve().parent
HOME = Path.home()
WORMHOLE = HOME / "Escritorio" / "WORMHOLE"
ETSY = HOME / "Escritorio" / "ETSY"
TOOLS_DIR = WORMHOLE / "tools"
MEMORIA = AQUI / "memoria.md"
TRABAJOS = AQUI / "trabajos"
MAX_OUT = 4000
MOONRAKER = "http://192.168.0.102:7125"
INACTIVIDAD = 25  # s sin actividad del modelo antes de volver a dormir

# Estado compartido con assistant.py
ST = {"session": None, "activo": False, "ultima": time.monotonic(),
      "pending": None, "trabajos": {}}


# ---------- activación / avisos ----------
def activar():
    if not ST["activo"]:
        print("\n🟢 Activo, te escucho...")
    ST["activo"] = True
    ST["ultima"] = time.monotonic()


def dormir_ahora():
    if ST["activo"]:
        print("\n💤 Dormido (di «Delta» o pulsa Enter)")
    ST["activo"] = False


async def avisar(texto: str):
    """Aviso proactivo: notificación de escritorio y, si hay sesión, el modelo lo dice en voz alta."""
    subprocess.Popen(["notify-send", "Gemini", texto[:200]], stderr=subprocess.DEVNULL)
    s = ST["session"]
    if s is None:  # ponytail: aviso perdido si justo se está reconectando; queda el notify-send
        return
    activar()
    try:
        await s.send_realtime_input(text=f"[AVISO DEL SISTEMA: no leas esta etiqueta, di solo el contenido al usuario en una frase] {texto}")
    except Exception as e:
        print(f"No pude avisar por voz: {e}")


# ---------- utilidades ----------
def _clip(s: str) -> str:
    s = s.strip()
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + "\n...[recortado]"


async def _run(argv, cwd=None, timeout=60):
    p = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        return -1, f"[timeout tras {timeout}s]"
    return p.returncode, _clip(out.decode(errors="replace"))


async def _confirmar(texto: str) -> bool:
    print(f"\n⚠️  Gemini quiere: {texto}\n   ¿Permitir? [s/N] ", end="", flush=True)
    ST["pending"] = asyncio.get_running_loop().create_future()
    try:
        resp = await ST["pending"]
    finally:
        ST["pending"] = None
    return resp.strip().lower() in ("s", "si", "sí", "y", "yes")


def entrada_stdin(linea: str):
    """Llamado por assistant.py con cada línea de teclado: confirma o alterna activación."""
    if ST["pending"] and not ST["pending"].done():
        ST["pending"].set_result(linea)
    elif ST["activo"]:
        dormir_ahora()
    else:
        activar()


# ---------- trabajos en segundo plano ----------
async def _trabajo(nombre, argv, cwd, timeout, pre=None):
    TRABAJOS.mkdir(exist_ok=True)
    log = TRABAJOS / f"{nombre}.log"
    ST["trabajos"][nombre] = "en curso"
    with open(log, "w") as f:
        p = await asyncio.create_subprocess_exec(*argv, cwd=cwd, stdout=f, stderr=asyncio.subprocess.STDOUT)
        try:
            await asyncio.wait_for(p.wait(), timeout)
            estado = "terminó bien" if p.returncode == 0 else f"falló (código {p.returncode})"
        except asyncio.TimeoutError:
            p.kill()
            estado = f"se cortó por timeout de {timeout}s"
    cola = _clip(log.read_text(errors="replace")[-700:])
    ST["trabajos"][nombre] = estado
    await avisar(f"El trabajo «{nombre}» {estado}. Final del log: {cola}")


def lanzar(nombre, argv, cwd=WORMHOLE, timeout=900):
    nombre = f"{nombre}-{int(time.time()) % 100000}"
    asyncio.create_task(_trabajo(nombre, argv, cwd, timeout))
    return f"Trabajo «{nombre}» lanzado en segundo plano; avisaré al terminar."


def _py_cad():
    return str(WORMHOLE / ".venv-cad" / "bin" / "python")


# ---------- handlers ----------
async def abrir(objetivo):
    argv = ["xdg-open", objetivo] if ("/" in objetivo or ":" in objetivo) else ["gtk-launch", objetivo]
    subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Abriendo {objetivo}"


async def ejecutar_herramienta_wormhole(script, args=""):
    name = Path(script).stem
    path = TOOLS_DIR / f"{name}.py"
    if not path.is_file():
        return f"No existe {name}.py. Disponibles: " + ", ".join(p.stem for p in sorted(TOOLS_DIR.glob("*.py")))
    return lanzar(name, [_py_cad(), str(path), *args.split()])


async def verificar_diseno(stl, spec=""):
    """Ciclo G3 (cadcheck) + G5 (slice_check) + G4 (render_views) en un solo trabajo."""
    stl = Path(stl).expanduser()
    spec = Path(spec).expanduser() if spec else stl.with_name("spec.yaml")
    if not stl.is_file() or not spec.is_file():
        return f"Falta el STL ({stl}) o el spec ({spec})."
    cmd = " ; ".join([
        f"{_py_cad()} tools/cadcheck.py --stl '{stl}' --spec '{spec}'",
        f"{_py_cad()} tools/slice_check.py --stl '{stl}' --spec '{spec}'",
        f"{_py_cad()} tools/render_views.py --stl '{stl}' --pieza '{stl.stem}' --quick"])
    return lanzar("ciclo-" + stl.stem[:20], ["bash", "-c", cmd], timeout=1800)


async def ejecutar_shell(comando):
    if not await _confirmar(f"ejecutar `{comando}`"):
        return "El usuario denegó la ejecución."
    code, out = await _run(["bash", "-lc", comando])
    return f"[código {code}]\n{out}"


async def preguntar_a_claude(tarea):
    if not await _confirmar(f"delegar en Claude Code: {tarea}"):
        return "El usuario denegó la tarea."
    if not shutil.which("claude"):
        return "claude no está en el PATH."
    return lanzar("claude", ["claude", "-p", tarea, "--permission-mode", "acceptEdits"], timeout=1800)


async def ver_trabajos():
    return "\n".join(f"{n}: {e}" for n, e in ST["trabajos"].items()) or "No hay trabajos."


async def estado_proyectos(nombre=""):
    estados = sorted(ETSY.glob("*/ESTADO.md")) + sorted(WORMHOLE.glob("*/ESTADO.md")) \
        + sorted(ETSY.glob("*/v*/ESTADO.md"))
    if not nombre:
        filas = sorted(estados, key=lambda p: p.stat().st_mtime, reverse=True)[:12]
        return "Proyectos (más recientes primero):\n" + "\n".join(
            f"- {p.parent.parent.name + '/' if p.parent.parent.name.startswith('Fuente') else ''}{p.parent.name} (tocado {time.strftime('%d/%m %H:%M', time.localtime(p.stat().st_mtime))})"
            for p in filas)
    hay = [p for p in estados if nombre.lower() in str(p.parent).lower()]
    if not hay:
        return f"No hay ESTADO.md que case con «{nombre}»."
    p = max(hay, key=lambda p: p.stat().st_mtime)
    return f"{p.parent.name}:\n" + _clip(p.read_text(errors="replace"))


# --- impresora (Moonraker, solo lectura) ---
async def _impresora():
    q = "extruder&heater_bed&print_stats&display_status&virtual_sdcard"
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{MOONRAKER}/printer/objects/query?{q}")
    return r.json()["result"]["status"]


def _hhmm(seg):
    if seg < 60:
        return f"{int(seg)} s"
    elif seg < 3600:
        return f"{int(seg // 60)} min"
    return f"{int(seg // 3600)} h {int(seg % 3600 // 60)} min"


async def _tiempo_restante_impresora():
    """Devuelve (segundos_restantes, filename, state, metodo)."""
    st = await _impresora()
    ps = st.get("print_stats", {})
    state = ps.get("state")
    if state not in ("printing", "paused"):
        return None, ps.get("filename", ""), state, None

    filename = ps.get("filename", "")
    print_duration = ps.get("print_duration", 0)
    prog = st.get("virtual_sdcard", {}).get("progress", 0)

    est_slicer = None
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{MOONRAKER}/server/files/metadata", params={"filename": filename})
            if r.status_code == 200:
                est_slicer = r.json().get("result", {}).get("estimated_time")
    except Exception:
        pass

    if est_slicer and est_slicer > print_duration:
        return est_slicer - print_duration, filename, state, "slicer"
    if prog > 0.02:
        return print_duration * (1 - prog) / prog, filename, state, "progreso"
    return None, filename, state, None


async def estado_impresora():
    try:
        st = await _impresora()
    except Exception as e:
        return f"No puedo hablar con la impresora ({MOONRAKER}): {e}"
    ps, ex, bed = st["print_stats"], st["extruder"], st["heater_bed"]
    out = (f"Estado: {ps['state']}. Boquilla {ex['temperature']:.0f}/{ex['target']:.0f} °C, "
           f"cama {bed['temperature']:.0f}/{bed['target']:.0f} °C.")
    if ps["state"] in ("printing", "paused"):
        prog = st["virtual_sdcard"]["progress"]
        out += f" Archivo {ps['filename']}, {prog * 100:.0f}% hecho, lleva {_hhmm(ps['print_duration'])}"
        restante, _, _, _ = await _tiempo_restante_impresora()
        if restante is not None:
            out += f", quedan unas {_hhmm(restante)}"
        out += "."
    return out


async def programar_aviso_impresora(minutos_antes="5"):
    try:
        m = float(str(minutos_antes).strip() or 5)
    except ValueError:
        m = 5.0
    seg_target = m * 60
    try:
        restante, fn, state, _ = await _tiempo_restante_impresora()
    except Exception as e:
        return f"Error consultando la impresora: {e}"

    if state not in ("printing", "paused"):
        return f"La impresora no está imprimiendo actualmente (estado: {state})."
    if restante is None:
        return "No hay suficiente progreso o metadatos para calcular el tiempo restante de impresión."
    if restante <= seg_target:
        return f"¡Atención! Ya quedan menos de {int(m)} minutos (quedan aproximadamente {_hhmm(restante)})."

    nombre_trabajo = f"aviso_{int(m)}m_{fn}"
    ST["trabajos"][nombre_trabajo] = f"esperando ({int(m)} min antes de fin)"

    async def _vigilante_tiempo():
        while True:
            await asyncio.sleep(20)
            try:
                r, _, s, _ = await _tiempo_restante_impresora()
                if s not in ("printing", "paused"):
                    ST["trabajos"][nombre_trabajo] = "finalizado o detenido"
                    break
                if r is not None and r <= seg_target:
                    ST["trabajos"][nombre_trabajo] = "notificado"
                    await avisar(f"Quedan aproximadamente {int(m)} minutos para terminar de imprimir {fn}.")
                    break
            except Exception:
                pass

    asyncio.create_task(_vigilante_tiempo())
    return (f"Aviso programado: te avisaré cuando falten {int(m)} minutos para terminar de imprimir {fn}. "
            f"Tiempo restante estimado actual: {_hhmm(restante)}.")


async def vigilar_impresora():
    """Avisa cuando una impresión termina, falla o se cancela."""
    previo = None
    while True:
        await asyncio.sleep(20)
        try:
            ps = (await _impresora())["print_stats"]
        except Exception:
            continue  # impresora apagada o sin red: reintenta
        if previo == "printing" and ps["state"] != "printing" and ps["state"] != "paused":
            await avisar(f"La impresora ha dejado de imprimir {ps['filename']}: estado {ps['state']}. {ps.get('message') or ''}")
        previo = ps["state"]


# --- memoria ---
def leer_memoria():
    return MEMORIA.read_text().strip() if MEMORIA.exists() else ""


async def recordar(nota):
    with open(MEMORIA, "a") as f:
        f.write(f"- {nota.strip()}\n")
    return "Anotado."


async def olvidar(fragmento):
    lineas = leer_memoria().splitlines()
    resto = [l for l in lineas if fragmento.lower() not in l.lower()]
    MEMORIA.write_text("\n".join(resto) + ("\n" if resto else ""))
    return f"Borradas {len(lineas) - len(resto)} notas."


MEJORAS_LOG = AQUI / "mejoras_pendientes.log"


async def anotar_mejora(descripcion):
    with open(MEJORAS_LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {descripcion.strip()}\n")
    print(f"\n💡 [MEJORA SOLICITADA]: {descripcion.strip()}\n")
    return "Anotado. He registrado esta solicitud para que se implemente lo antes posible."


# --- sistema (KDE / PipeWire) ---
async def volumen(accion, valor=""):
    sink = "@DEFAULT_AUDIO_SINK@"
    if accion == "fijar":
        argv = ["wpctl", "set-volume", sink, f"{max(0, min(150, int(str(valor).strip('% '))))}%"]
    elif accion in ("subir", "bajar"):
        argv = ["wpctl", "set-volume", sink, f"{int(str(valor or 10).strip('% '))}%{'+' if accion == 'subir' else '-'}"]
    elif accion in ("silenciar", "activar_sonido"):
        argv = ["wpctl", "set-mute", sink, "1" if accion == "silenciar" else "0"]
    else:
        argv = ["wpctl", "get-volume", sink]
    return (await _run(argv))[1] or "Hecho."


BRILLO = ["busctl", "--user", "call", "org.kde.Solid.PowerManagement",
          "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
          "org.kde.Solid.PowerManagement.Actions.BrightnessControl"]


async def brillo(porcentaje):
    mx = int((await _run([*BRILLO, "brightnessMax"]))[1].split()[-1])
    val = max(1, round(mx * max(1, min(100, int(porcentaje))) / 100))
    return (await _run([*BRILLO, "setBrightness", "i", str(val)]))[1] or f"Brillo al {porcentaje}%."


async def notificar(titulo, texto=""):
    subprocess.Popen(["notify-send", titulo, texto], stderr=subprocess.DEVNULL)
    return "Notificación enviada."


async def portapapeles(accion, texto=""):
    if accion == "escribir":
        subprocess.run(["wl-copy", texto])
        return "Copiado al portapapeles."
    return _clip(subprocess.run(["wl-paste", "-n"], capture_output=True, text=True).stdout) or "(vacío)"


async def ventanas(accion, nombre=""):
    if accion == "listar":
        ids = (await _run(["kdotool", "search", "--name", ""]))[1].split()
        nombres = [(await _run(["kdotool", "getwindowname", i]))[1] for i in ids]
        return "\n".join(n for n in nombres if n) or "Sin ventanas."
    if accion in ("mover_pantalla", "otra_pantalla"):
        if nombre:
            ids = (await _run(["kdotool", "search", "--name", nombre]))[1].split()
            if ids:
                await _run(["kdotool", "windowactivate", ids[0]])
                await asyncio.sleep(0.1)
        await _run(["qdbus-qt6", "org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component.invokeShortcut", "Window to Next Screen"])
        return f"Ventana {f'«{nombre}» ' if nombre else ''}movida a la otra pantalla."
    ids = (await _run(["kdotool", "search", "--name", nombre]))[1].split()
    if not ids:
        return f"No encuentro ventana «{nombre}»."
    cmd = {"activar": "windowactivate", "cerrar": "windowclose", "minimizar": "windowminimize"}.get(accion)
    if not cmd:
        return "Acción no válida."
    if accion == "cerrar" and not await _confirmar(f"cerrar la ventana «{nombre}»"):
        return "El usuario denegó cerrar la ventana."
    return (await _run(["kdotool", cmd, ids[0]]))[1] or "Hecho."


async def dormir():
    asyncio.get_running_loop().call_later(4, dormir_ahora)  # deja terminar la despedida
    return "Me duermo en unos segundos."


# ---------- declaraciones ----------
S, STR = types.Schema, types.Type.STRING


def _fn(name, desc, props=None, req=None):
    props = props or {}
    return types.FunctionDeclaration(
        name=name, description=desc,
        parameters=S(type=types.Type.OBJECT, properties=props, required=list(props) if req is None else req)
        if props else None)


def _s(d):
    return S(type=STR, description=d)


DECLARATIONS = [
    _fn("abrir", "Abre una URL, archivo/carpeta o aplicación (id .desktop, p.ej. firefox).",
        {"objetivo": _s("URL, ruta o id de aplicación")}),
    _fn("ejecutar_herramienta_wormhole",
        "Lanza EN SEGUNDO PLANO un script de WORMHOLE/tools (cadcheck, render_views, slice_check, stl_audit...). Avisa al terminar.",
        {"script": _s("nombre del script"), "args": _s("argumentos separados por espacios")}),
    _fn("verificar_diseno",
        "Lanza en segundo plano el ciclo completo cadcheck + slice_check + render_views sobre un STL. Avisa al terminar.",
        {"stl": _s("ruta del STL"), "spec": _s("ruta del spec.yaml (opcional, por defecto spec.yaml junto al STL)")},
        req=["stl"]),
    _fn("ejecutar_shell", "Ejecuta un comando de shell (pide confirmación al usuario en la terminal, máx 60 s).",
        {"comando": _s("comando completo")}),
    _fn("preguntar_a_claude",
        "Lanza una tarea suelta de Claude Code SIN memoria (un solo disparo, pide confirmación). Para conversar o encadenar peticiones usa hablar_con_claude.",
        {"tarea": _s("instrucción completa y autocontenida")}),
    _fn("estado_impresora", "Temperaturas, estado y progreso de la impresión actual (Klipper/Moonraker, solo lectura)."),
    _fn("programar_aviso_impresora",
        "Programa un aviso o alarma cuando falten N minutos para que termine la impresión 3D actual (por defecto 5 min).",
        {"minutos_antes": _s("minutos antes del final de la impresión para avisar (por ejemplo 5 o 10, por defecto 5)")},
        req=[]),
    _fn("ver_trabajos", "Lista los trabajos en segundo plano y su estado."),
    _fn("estado_proyectos",
        "Sin nombre: lista proyectos recientes. Con nombre: lee su ESTADO.md para decir dónde lo dejaron.",
        {"nombre": _s("parte del nombre del proyecto, opcional")}, req=[]),
    _fn("recordar", "Guarda una nota en la memoria persistente (sobrevive a reinicios).", {"nota": _s("hecho a recordar")}),
    _fn("olvidar", "Borra de la memoria las notas que contengan este texto.", {"fragmento": _s("texto a buscar")}),
    _fn("volumen", "Controla el volumen del sistema.",
        {"accion": _s("fijar | subir | bajar | silenciar | activar_sonido | consultar"),
         "valor": _s("porcentaje, si aplica")}, req=["accion"]),
    _fn("brillo", "Fija el brillo de pantalla.", {"porcentaje": _s("1-100")}),
    _fn("notificar", "Muestra una notificación de escritorio.",
        {"titulo": _s("título"), "texto": _s("cuerpo")}, req=["titulo"]),
    _fn("portapapeles", "Lee o escribe el portapapeles.",
        {"accion": _s("leer | escribir"), "texto": _s("texto si escribir")}, req=["accion"]),
    _fn("ventanas", "Gestiona ventanas de KDE.",
        {"accion": _s("listar | activar | minimizar | cerrar | mover_pantalla"),
         "nombre": _s("parte del título de la ventana (para activar, minimizar, cerrar o mover de monitor)")},
        req=["accion"]),
    _fn("anotar_mejora",
        "Invoca esto cuando el usuario te pida una acción o capacidad que aún no puedes hacer, para que el programador la implemente.",
        {"descripcion": _s("descripción clara de la función o acción solicitada")}),
    _fn("dormir", "Vuelve al modo espera cuando el usuario se despide o dice que ya está."),
]

TOOLS = [types.Tool(google_search=types.GoogleSearch()),
         types.Tool(function_declarations=DECLARATIONS)]

HANDLERS = {f.__name__: f for f in (
    abrir, ejecutar_herramienta_wormhole, verificar_diseno, ejecutar_shell, preguntar_a_claude,
    ver_trabajos, estado_impresora, programar_aviso_impresora, estado_proyectos, recordar, olvidar, anotar_mejora,
    volumen, brillo, notificar, portapapeles, ventanas, dormir)}


async def atender(session, tool_call):
    ST["ultima"] = time.monotonic()
    for fc in tool_call.function_calls:
        print(f"\n🔧 {fc.name}({dict(fc.args or {})})")
        ST["herramienta"] = fc.name
        try:
            out = await HANDLERS[fc.name](**(fc.args or {}))
        except Exception as e:
            out = f"Error: {e}"
        finally:
            ST["herramienta"] = None
        await session.send_tool_response(function_responses=[
            types.FunctionResponse(id=fc.id, name=fc.name, response={"output": out})])
