"""Herramientas (function calling) que Gemini puede invocar + estado compartido."""
import asyncio
import inspect
import json
import os
import re
import shlex
import socket
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
ST = {"session": None, "activo": False, "hablando": False, "ultima": time.monotonic(),
      "pending": None, "trabajos": {}}


_TAREAS = set()


def tarea(coro):
    """create_task guardando referencia: asyncio solo guarda una débil y el GC puede matar la tarea a medias."""
    t = asyncio.create_task(coro)
    _TAREAS.add(t)
    t.add_done_callback(_TAREAS.discard)
    return t


# ---------- activación / avisos ----------
def activar():
    if not ST["activo"]:
        print("\n🟢 Activo, te escucho...")
        try:
            subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/audio-volume-change.oga"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    ST["activo"] = True
    ST["ultima"] = time.monotonic()
    _musica_vol()


def dormir_ahora():
    if ST["activo"]:
        print("\n💤 Dormido (di «Delta» o pulsa Enter)")
    ST["activo"] = False
    ST["hablando"] = False
    _musica_vol()


async def avisar(texto: str, notificar=True):
    """Aviso proactivo: notificación de escritorio y el modelo lo dice en voz alta.
    Sin sesión (colgada en reposo o reconectando): se guarda y se despierta; assistant.py lo dice al conectar."""
    if notificar:
        subprocess.Popen(["notify-send", "Delta", texto[:200]], stderr=subprocess.DEVNULL)
    activar()
    s = ST["session"]
    if s is None:
        ST.setdefault("avisos", []).append(texto)
        return
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


ESPERA_CONFIRMAR = 120  # s sin respuesta = denegar


AUTO_CLAUDE = 300  # s tras un encargo de Claude Code en los que lo que pida Gemini no pregunta (el usuario lo pidió, 2026-10-19)


def autorizado():
    """¿Hay un encargo de Claude Code reciente? Entonces todo permiso se da solo y sin decirle nada al usuario (lo pidió así)."""
    t = ST.get("auto_claude")
    return bool(t) and time.monotonic() - t < AUTO_CLAUDE


async def encargo_claude(texto):
    """Claude Code (la sesión de programación del usuario, en modo sin permisos) le pide algo a Delta."""
    activar()
    s = ST["session"]
    if s is None:  # en reposo: assistant.py lo entrega al conectar
        ST.setdefault("encargos", []).append(texto)
        return
    ST["auto_claude"] = time.monotonic()
    print(f"\n🤖 Encargo de Claude Code: {texto}")
    paso(f"Encargo de Claude Code · {texto[:60]}", "hecho")
    await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=(
        "[ENCARGO DE CLAUDE CODE, el asistente de programación del usuario, que trabaja con su permiso: hazlo con tus "
        f"herramientas sin pedir confirmación y cuéntalo en una frase. No menciones esta etiqueta.] {texto}"))]), turn_complete=True)


async def _confirmar(texto: str, voz=False) -> bool:
    """Pregunta al usuario por teclado [s/N] o botón del panel. voz=True deja contestar también
    con responder_permiso, pero solo si el usuario habla después de la pregunta (ver ST["t_tu"])."""
    if autorizado():
        print(f"\n🤖 Autorizado por el encargo de Claude Code: {texto}")
        return True
    print(f"\n⚠️  Gemini quiere: {texto}\n   ¿Permitir? [s/N] ", end="", flush=True)
    f = ST["pending"] = asyncio.get_running_loop().create_future()
    f.texto, f.voz, f.t0 = texto, voz, time.monotonic()
    try:
        resp = await asyncio.wait_for(f, ESPERA_CONFIRMAR)
    except asyncio.TimeoutError:
        print("\n⏱️  Sin respuesta: denegado.")
        resp = "n"
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
def etapa(log):
    """Etapa y % de un trabajo según su log: la última línea con «[NN%]» (estudio_clase las pone) o, si no hay, la última."""
    with open(log, "rb") as f:
        f.seek(max(0, f.seek(0, 2) - 4096))
        lineas = [re.sub(r"^\d\d:\d\d:\d\d ", "", l).strip() for l in f.read().decode(errors="replace").splitlines()]
    lineas = [l for l in lineas if l]
    con = [l for l in lineas if re.match(r"\[\d+%\]", l)]
    if con:
        m = re.match(r"\[(\d+)%\]\s*(.*)", con[-1])
        return {"pct": int(m.group(1)), "etapa": m.group(2)[:120]}
    return {"pct": None, "etapa": (lineas[-1] if lineas else "")[:120]}


async def _trabajo(nombre, argv, cwd, timeout, pre=None):
    TRABAJOS.mkdir(exist_ok=True)
    log = TRABAJOS / f"{nombre}.log"
    ST["trabajos"][nombre] = "en curso"
    prog = ST.setdefault("progreso", {})[nombre] = {"etapa": "", "pct": None, "ini": time.time(), "fin": None}
    fin = time.monotonic() + timeout
    with open(log, "w") as f:
        p = await asyncio.create_subprocess_exec(*argv, cwd=cwd, stdout=f, stderr=asyncio.subprocess.STDOUT)
        while True:
            try:
                await asyncio.wait_for(p.wait(), 2)
                estado = "terminó bien" if p.returncode == 0 else f"falló (código {p.returncode})"
                break
            except asyncio.TimeoutError:
                prog.update(etapa(log))  # el HUD enseña lo que dice el log, no lo que cuente Gemini
                if time.monotonic() > fin:
                    p.kill()
                    estado = f"se cortó por timeout de {timeout}s"
                    break
    cola = _clip(log.read_text(errors="replace")[-700:])
    prog.update(etapa(log), fin=time.time())
    ST["trabajos"][nombre] = estado
    await avisar(f"El trabajo «{nombre}» {estado}. Final del log: {cola}")


def huerfanos():
    """{nombre: (pid, log)} de los trabajos vivos que no sigue nadie: su salida va a trabajos/<nombre>.log pero Delta se
    reinició mientras corrían (ST["trabajos"] solo vive en memoria). Con hijos que heredan el log, el de pid menor."""
    vivos = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            log = Path(os.readlink(f"/proc/{pid}/fd/1"))
        except OSError:
            continue
        if log.parent == TRABAJOS and log.suffix == ".log" and log.stem not in ST["trabajos"]:
            if log.stem not in vivos or int(pid) < vivos[log.stem][0]:
                vivos[log.stem] = (int(pid), log)
    return vivos


def _arranque(pid):
    """Hora (epoch) a la que arrancó el proceso, de /proc."""
    btime = next(int(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime"))
    ticks = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19])
    return btime + ticks / os.sysconf("SC_CLK_TCK")


async def _seguir_huerfano(nombre, pid, log):
    """Como _trabajo pero de un proceso que no es hijo nuestro: sin código de salida, falla si el log trae un Traceback."""
    ST["trabajos"][nombre] = "en curso"
    prog = ST.setdefault("progreso", {})[nombre] = {"etapa": "", "pct": None, "ini": _arranque(pid), "fin": None}
    while os.path.exists(f"/proc/{pid}"):
        prog.update(etapa(log))
        await asyncio.sleep(2)
    texto = log.read_text(errors="replace")
    estado = "falló (Traceback en el log)" if "Traceback (most recent call last)" in texto else "terminó bien"
    prog.update(etapa(log), fin=time.time())
    ST["trabajos"][nombre] = estado
    await avisar(f"El trabajo «{nombre}» {estado}. Final del log: {_clip(texto[-700:])}")


def adoptar_trabajos():
    """Al arrancar Delta: los trabajos que siguen vivos vuelven a la barra y al panel, y avisan al acabar."""
    for nombre, (pid, log) in huerfanos().items():
        print(f"🔁 Retomo el trabajo «{nombre}» (pid {pid}), que seguía en marcha")
        tarea(_seguir_huerfano(nombre, pid, log))


def lanzar(nombre, argv, cwd=WORMHOLE, timeout=900):
    nombre = f"{nombre}-{int(time.time()) % 100000}"
    tarea(_trabajo(nombre, argv, cwd, timeout))
    return f"Trabajo «{nombre}» lanzado en segundo plano; avisaré al terminar."


def _py_cad():
    return str(WORMHOLE / ".venv-cad" / "bin" / "python")


# ---------- handlers ----------
async def abrir(objetivo):
    # una URL con ?… puede llevar datos fuera (instrucción inyectada desde la pantalla o una web): que lo vea el usuario
    # ponytail: un dato metido en la ruta (web.com/DATO) no pregunta; si se ve abuso, preguntar por todo host nuevo
    if re.match(r"https?://[^?#]*[?#]..", objetivo) and not await _confirmar(f"abrir {objetivo[:160]}", voz=True):
        return "El usuario no quiso abrir esa URL."
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


# Consultas que el usuario autorizó sin preguntar (2026-10-15): solo programas que leen.
# Nada de red (curl/wget podrían mandar órdenes a la impresora), ni nada que lance otros comandos.
LECTURA = {"ps", "pgrep", "top", "free", "df", "du", "uptime", "uname", "lscpu", "lsblk", "lsusb", "lspci", "lsmod",
           "sensors", "nproc", "whoami", "id", "date", "cal", "hostname", "ip", "ss", "cat", "head", "tail", "wc", "ls",
           "stat", "file", "grep", "rg", "find", "which", "whereis", "echo", "sort", "uniq", "cut", "tr", "column",
           "journalctl", "systemctl", "pactl", "rpm", "flatpak", "vmstat", "iostat", "zramctl", "swapon", "last", "w",
           "who", "basename", "dirname", "realpath", "readlink", "md5sum", "sha256sum", "nvidia-smi"}
PROHIBIDO = {"find": ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"),
             "sort": ("-o", "--output", "--compress"), "rg": ("--pre", "--hidden", "-u", "-.", "--no-ignore"),
             "file": ("-C", "--compile"), "journalctl": ("--vacuum", "--rotate", "--flush", "--sync", "--setup-keys"),
             "grep": ("-r", "-R", "--recursive", "--dereference-recursive", "-d", "--directories"),
             "swapon": ("",)}  # swapon sin argumentos: con ellos activa swap
# 2026-10-19: Gemini ve la pantalla y lee webs; una orden inyectada podía pedir «cat ~/.bashrc» sin preguntar y sacar
# la clave por abrir(). Lo que toque secretos pide permiso aunque el programa sea de LECTURA:
# variables ($), entornos de procesos, ficheros/carpetas ocultos (~/.bashrc, ~/.ssh, ~/.config) y nombres de claves.
_SECRETO = re.compile(r"environ|(^|/)\.[^./]|clave|key|secret|token|passw|credential|\.pem$|id_(rsa|ed25519|ecdsa)|vapid|cookie", re.I)
_COMODIN = re.compile(r"[*?\[{]")  # «cat movil_cl*» o «cat movil_cl{a,}ve.txt» esquivarían los nombres de arriba
SUBORDEN = {"systemctl": {"status", "list-units", "list-timers", "list-unit-files", "is-active", "is-enabled", "show"},
            "pactl": {"list", "info", "get-default-sink", "get-default-source", "get-sink-volume", "get-sink-mute"},
            "rpm": {"-q", "-qa", "-qi", "-ql", "-qf"}, "flatpak": {"list", "info"}}


def _solo_lectura(comando):
    """True si todo el comando son programas de LECTURA unidos por tuberías, && o ;, sin redirecciones ni subcomandos."""
    if re.search(r"[<>`\n$]", comando):  # $ también: «echo $GEMINI_API_KEY»
        return False
    lex = shlex.shlex(comando, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        toks = list(lex)
    except ValueError:
        return False
    tramos, actual = [], []
    for t in toks:
        if t in ("|", "&&", "||", ";"):
            tramos.append(actual); actual = []
        elif set(t) <= set("|&;()"):
            return False  # &, (, ), ;; …
        else:
            actual.append(t)
    tramos.append(actual)
    for t in tramos:
        if not t or t[0] not in LECTURA:
            return False
        prog, args = t[0], t[1:]
        if any(a.startswith(p) for a in args for p in PROHIBIDO.get(prog, ())):
            return False
        if any(_SECRETO.search(a) for a in args):
            return False
        patron = 1 if prog in ("grep", "rg") else 0  # el primer argumento suelto de grep es el patrón, no un fichero
        sueltos = [a for a in args if not a.startswith("-")]
        if prog != "find" and any(_COMODIN.search(a) for a in sueltos[patron:]):
            return False
        if prog == "grep" and any(re.fullmatch(r"-[^-]*[rR]\w*", a) for a in args):
            return False  # -nr, -ir… recorren carpetas enteras (~ con .bashrc dentro)
        if prog == "ps" and any(re.fullmatch(r"[a-zA-Z]*e[a-zA-Z]*", a) for a in sueltos):
            return False  # «ps e», «ps auxe»: enseña las variables de entorno de cada proceso
        if prog in SUBORDEN and (not args or args[0] not in SUBORDEN[prog]):
            return False
        if prog == "uniq" and len([a for a in args if not a.startswith("-")]) > 1:
            return False  # uniq ENTRADA SALIDA escribe en SALIDA
        if prog == "top" and "-b" not in args:
            return False  # top interactivo no termina nunca
    return True


# 2026-10-15: «kill $(ps … nice < 0)» se aprobó sin ver qué mataba y tiró PipeWire, WirePlumber y KWin
_MATAR = re.compile(r"\b(kill|pkill|killall)\b")
_VITALES = re.compile(r"\$\(|`|pipewire|wireplumber|kwin|plasma|kded|xwayland|systemd|\s-1\b|\s0\s*$")


def _mata_sesion(c):
    """kill con objetivos calculados ($(…)) o que tocan el audio/escritorio: no se pide permiso, se rechaza."""
    return bool(_MATAR.search(c) and _VITALES.search(c.lower()))


async def ejecutar_shell(comando):
    if _mata_sesion(comando):
        return ("Rechazado: ese kill calcula a quién mata o toca el audio/escritorio (PipeWire, WirePlumber, KWin…), "
                "y tumbaría la sesión. Lista primero los procesos y mata solo uno concreto por su nombre o PID.")
    if not _solo_lectura(comando) and not await _confirmar(f"ejecutar `{comando}`"):
        return "El usuario denegó la ejecución."
    code, out = await _run(["bash", "-lc", comando])
    return f"[código {code}]\n{_tapar(out)}"


def _tapar(texto):
    """Último cinturón: si una clave conocida sale igualmente (comando aprobado sin mirar), Gemini no la ve.
    ponytail: solo tapa el valor exacto; troceado o codificado (cut, tr) pasaría: para eso está _solo_lectura."""
    claves = [v for k, v in os.environ.items() if re.search(r"KEY|TOKEN|SECRET|PASS", k) and len(v) >= 12]
    f = Path(__file__).with_name("movil_clave.txt")
    if f.exists():
        claves.append(f.read_text().strip())
    for c in filter(None, claves):
        texto = texto.replace(c, "[secreto tapado]")
    return texto


async def preguntar_a_claude(tarea):  # pasarle algo a Claude Code no se pregunta nunca (lo pidió el usuario)
    if not shutil.which("claude"):
        return "claude no está en el PATH."
    return lanzar("claude", ["env", "DELTA_ORIGEN=1", "claude", "-p", tarea, "--permission-mode", "acceptEdits"], timeout=1800)


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
    q = "extruder&heater_bed&print_stats&display_status&virtual_sdcard&gcode_move&fan&webhooks&toolhead"
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
        gm, meta = st["gcode_move"], await _get("/server/files/metadata", filename=ps["filename"])
        z, lh = gm["gcode_position"][2], meta.get("layer_height")
        out += f" Altura {z:.1f}" + (f" de {meta['object_height']:.0f} mm" if meta.get("object_height") else " mm")
        out += f" (capa ~{round(z / lh)})" if lh else ""
        out += (f". Velocidad {gm['speed_factor'] * 100:.0f}%, flujo {gm['extrude_factor'] * 100:.0f}%, "
                f"ventilador de capa {st['fan']['speed'] * 100:.0f}%, filamento gastado {ps['filament_used'] / 1000:.1f} m.")
    if st["webhooks"]["state"] != "ready":
        out += f" Klipper: {st['webhooks']['state']} ({st['webhooks']['state_message']})."
    if ps.get("message"):
        out += f" Mensaje: {ps['message']}."
    return out


async def _get(ruta, **params):
    """GET a Moonraker: solo lectura, nunca se envía G-code ni comandos."""
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{MOONRAKER}{ruta}", params=params)
    return r.json().get("result", {}) if r.status_code == 200 else {}


async def historial_impresora():
    try:
        jobs = (await _get("/server/history/list", limit=6, order="desc")).get("jobs", [])
        cola = await _get("/server/job_queue/status")
        consola = (await _get("/server/gcode_store", count=300)).get("gcode_store", [])
    except Exception as e:
        return f"No puedo hablar con la impresora ({MOONRAKER}): {e}"
    lineas = ["Últimos trabajos:"] + [
        f"- {time.strftime('%d/%m %H:%M', time.localtime(j['start_time']))} {j['filename']}: {j['status']}, "
        f"{_hhmm(j['total_duration'])}, {j['filament_used'] / 1000:.1f} m de filamento" for j in jobs]
    q = cola.get("queued_jobs", [])
    lineas.append(f"Cola: {len(q)} trabajos" + (": " + ", ".join(x["filename"] for x in q) if q else "") + ".")
    errores = [f"{time.strftime('%H:%M', time.localtime(x['time']))} {x['message']}" for x in consola
               if x["type"] == "response" and (x["message"].startswith("!!") or "rror" in x["message"])][-5:]
    lineas.append("Errores recientes en consola: " + ("; ".join(errores) if errores else "ninguno."))
    return "\n".join(lineas)


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

    tarea(_vigilante_tiempo())
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


# --- música (mpv + yt-dlp; control por el socket IPC de mpv) ---
MPV_SOCK = "/tmp/delta-mpv.sock"
_MPV = {"p": None}
ST["vol_musica"] = 60
ATENUAR = 0.3  # mientras Delta está despierto la música baja a este factor para oíros


def _mpv(cmd):
    """Orden al mpv en marcha; OSError si no hay música sonando."""
    with socket.socket(socket.AF_UNIX) as c:
        c.settimeout(2)
        c.connect(MPV_SOCK)
        c.sendall(json.dumps({"command": cmd, "request_id": 7}).encode() + b"\n")
        buf = b""
        while True:  # mpv intercala eventos: leer hasta la línea con nuestra respuesta
            trozo = c.recv(65536)
            if not trozo:
                raise OSError("mpv cerró el socket")
            buf += trozo
            for l in buf.split(b"\n"):
                if b'"request_id":7' in l:
                    return json.loads(l)


def _musica_vol():
    try:
        _mpv(["set_property", "volume", ST["vol_musica"] * (ATENUAR if ST["activo"] else 1)])
    except OSError:
        pass


async def poner_musica(busqueda):
    if _MPV["p"] and _MPV["p"].returncode is None:
        _MPV["p"].terminate()
    _MPV["p"] = await asyncio.create_subprocess_exec(
        "mpv", "--no-video", "--really-quiet", f"--input-ipc-server={MPV_SOCK}",
        f"--volume={ST['vol_musica'] * (ATENUAR if ST['activo'] else 1)}", f"ytdl://ytsearch10:{busqueda}",
        # sin la sesión de YouTube de Firefox, YouTube toma a yt-dlp por un bot (429) y no suena nada
        "--ytdl-raw-options=cookies-from-browser=firefox",
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):  # no decir «ya suena» sin comprobarlo
        await asyncio.sleep(1)
        if _MPV["p"].returncode is not None:
            break
        try:
            if (await asyncio.to_thread(_mpv, ["get_property", "time-pos"])).get("error") == "success":
                break
        except OSError:
            pass
    else:
        return "Error: la música no arranca tras 30 s (YouTube puede estar bloqueando)."
    if _MPV["p"].returncode is not None:
        return "Error: YouTube no deja reproducir; puede que la sesión de YouTube en Firefox haya caducado."
    return f"Sonando «{busqueda}» (comprobado): lista de 10 resultados de YouTube. Sonará bajita mientras hablamos y normal al dormirte."


async def controlar_musica(accion):
    cmds = {"pausa": ["set_property", "pause", True], "seguir": ["set_property", "pause", False],
            "siguiente": ["playlist-next"], "anterior": ["playlist-prev"], "que_suena": ["get_property", "media-title"]}
    try:
        if accion == "parar":
            _mpv(["quit"])
            return "Música parada."
        if accion in ("subir", "bajar"):
            ST["vol_musica"] = max(5, min(100, ST["vol_musica"] + (15 if accion == "subir" else -15)))
            _musica_vol()
            return f"Volumen de la música al {ST['vol_musica']}%."
        if accion not in cmds:
            return "Acción no válida."
        r = await asyncio.to_thread(_mpv, cmds[accion])
        return f"Suena: {r.get('data')}" if accion == "que_suena" else "Hecho." if r.get("error") == "success" else f"mpv: {r.get('error')}"
    except OSError:
        return "No hay música sonando."


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
AVERIAS_LOG = AQUI / "averias.log"   # lo revisa Claude Code


# Delta lo usaba como registro de averías («micrófono saturado» ×20): eso no es una capacidad nueva.
AVERIAS = re.compile(r"micr[oó]fono|saturad|ruido|eco\b|no (te |me )?(oigo|escucho|entiendo)|sin conexi[oó]n|desconectad|"
                     r"impresora (est[aá] )?(pausada|apagada|imprimiendo)|error|fall[oaó]|no funciona", re.I)


async def anotar_mejora(descripcion):
    d = descripcion.strip()
    if AVERIAS.search(d):
        # ponytail: una avería cada 10 min como mucho; si hacen falta distintas a la vez, deduplicar por texto
        if time.time() - (AVERIAS_LOG.stat().st_mtime if AVERIAS_LOG.exists() else 0) > 600:
            with open(AVERIAS_LOG, "a") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {d}\n")
        return ("Esto es una avería, no una capacidad nueva: queda en el registro de averías para que la revise el "
                "programador. No vuelvas a anotarla; cuéntaselo al usuario de palabra si hace falta.")
    if MEJORAS_LOG.exists() and d.lower() in MEJORAS_LOG.read_text().lower():
        return "Ya estaba anotado."
    with open(MEJORAS_LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {descripcion.strip()}\n")
    print(f"\n💡 [MEJORA SOLICITADA]: {descripcion.strip()}\n")
    lista = "; ".join(l.split("] ", 1)[-1] for l in MEJORAS_LOG.read_text().splitlines())
    return ("Anotado. Pendientes ahora: " + lista + ". No anotes variantes o reformulaciones de estas: "
            "solo ideas claramente distintas, y como mucho una por cada cosa que pida el usuario.")


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
    if nombre.lower() in ("panel", "interfaz", "deltaos", "panel de delta"):
        nombre = "Delta"  # la ventana del panel se titula así
    if accion == "listar":
        ids = (await _run(["kdotool", "search", "--name", ""]))[1].split()
        nombres = [(await _run(["kdotool", "getwindowname", i]))[1] for i in ids]
        return "\n".join(n for n in nombres if n) or "Sin ventanas."
    if accion in ("mover_pantalla", "otra_pantalla"):
        if nombre:
            ids = (await _run(["kdotool", "search", "--name", nombre]))[1].split()
            if not ids:
                return f"No encuentro ventana «{nombre}»."
            await _run(["kdotool", "windowactivate", ids[0]])
            await asyncio.sleep(0.1)
        await _run(["qdbus-qt6", "org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component.invokeShortcut", "Window to Next Screen"])
        return f"Ventana {f'«{nombre}» ' if nombre else ''}movida a la otra pantalla."
    ids = (await _run(["kdotool", "search", "--name", nombre]))[1].split()
    if not ids:
        return f"No encuentro ventana «{nombre}»."
    if accion == "ultrawide":  # a la pantalla más ancha, maximizada
        salida = (await _run(["kscreen-doctor", "-o"]))[1]
        geo = [tuple(map(int, re.findall(r"\d+", g))) for g in re.findall(r"Geometry: (\d+,\d+ \d+x\d+)", re.sub(r"\x1b\[[0-9;]*m", "", salida))]
        if not geo:
            return "No veo las pantallas."
        x, y, _, _ = max(geo, key=lambda g: g[2])
        await _run(["kdotool", "windowstate", "--remove", "MAXIMIZED", "--remove", "FULLSCREEN", ids[0]])
        await _run(["kdotool", "windowmove", ids[0], str(x + 50), str(y + 50)])
        await asyncio.sleep(0.2)
        accion = "maximizar"
    estado = {"maximizar": ["--add", "MAXIMIZED"], "pantalla_completa": ["--add", "FULLSCREEN"],
              "restaurar": ["--remove", "FULLSCREEN", "--remove", "MAXIMIZED"]}.get(accion)
    if estado:
        await _run(["kdotool", "windowactivate", ids[0]])
        return (await _run(["kdotool", "windowstate", *estado, ids[0]]))[1] or "Hecho."
    cmd = {"activar": "windowactivate", "cerrar": "windowclose", "minimizar": "windowminimize"}.get(accion)
    if not cmd:
        return "Acción no válida."
    if accion == "cerrar" and not await _confirmar(f"cerrar la ventana «{nombre}»", voz=True):
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
    _fn("ejecutar_shell", "Ejecuta un comando de shell, máx 60 s. Las consultas de solo lectura (ps, free, df, ls, cat, grep, journalctl, systemctl status… unidas con |, && o ;) se ejecutan sin preguntar; lo demás pide confirmación al usuario.",
        {"comando": _s("comando completo")}),
    _fn("preguntar_a_claude",
        "Lanza una tarea suelta de Claude Code SIN memoria (un solo disparo, pide confirmación). Para conversar o encadenar peticiones usa hablar_con_claude.",
        {"tarea": _s("instrucción completa y autocontenida")}),
    _fn("estado_impresora", "Estado de la impresora 3D (solo lectura): temperaturas, progreso, tiempo restante, altura/capa, velocidad, flujo, ventilador, filamento gastado y estado de Klipper."),
    _fn("historial_impresora", "Historial de impresiones recientes (resultado, duración, filamento), cola de trabajos y errores recientes de la consola de Klipper (solo lectura)."),
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
        {"accion": _s("listar | activar | minimizar | maximizar | pantalla_completa | restaurar | cerrar | mover_pantalla | ultrawide (la lleva a la pantalla ancha y la maximiza)"),
         "nombre": _s("parte del título de la ventana; tu panel/interfaz es «Delta». para ponerlo grande en la ultrawide usa accion=ultrawide")},
        req=["accion"]),
    _fn("anotar_mejora",
        "Cuando el USUARIO pida una función o capacidad NUEVA que aún no tienes, para que el programador la implemente. Una avería que persiste (micro, audio, impresora…) anótala UNA sola vez: va a un registro aparte; no repitas.",
        {"descripcion": _s("descripción clara de la función o acción solicitada")}),
    _fn("poner_musica", "Pone música buscándola en YouTube (canción, artista, estilo o lista). Sustituye a la que sonara.",
        {"busqueda": _s("qué poner, p.ej. «Los Planetas», «jazz para trabajar», «lofi»")}),
    _fn("controlar_musica", "Controla la música que pusiste con poner_musica.",
        {"accion": _s("pausa | seguir | siguiente | anterior | subir | bajar | parar | que_suena")}),
    _fn("dormir", "Vuelve al modo espera cuando el usuario se despide o dice que ya está."),
]

TOOLS = [types.Tool(google_search=types.GoogleSearch()),
         types.Tool(function_declarations=DECLARATIONS)]

def registrar(declaraciones, handlers):
    """Añade herramientas desde otros módulos y reconstruye TOOLS (que copia la lista al crearse)."""
    DECLARATIONS.extend(declaraciones)
    HANDLERS.update({f.__name__: f for f in handlers})
    TOOLS[1] = types.Tool(function_declarations=DECLARATIONS)


HANDLERS = {f.__name__: f for f in (
    abrir, ejecutar_herramienta_wormhole, verificar_diseno, ejecutar_shell, preguntar_a_claude,
    ver_trabajos, estado_impresora, historial_impresora, programar_aviso_impresora, estado_proyectos, recordar, olvidar, anotar_mejora,
    volumen, brillo, notificar, poner_musica, controlar_musica, portapapeles, ventanas, dormir)}


ETIQUETAS = {"estado_impresora": "Miro la impresora", "historial_impresora": "Leo el historial de la impresora",
             "poner_musica": "Pongo música", "controlar_musica": "Música", "mostrar": "Abro en pantalla",
             "buscar": "Busco en internet", "cambiar_vista": "Cambio de vista", "energia": "Energía del ordenador", "investigar": "Investigación profunda", "buscar_skills": "Busco skills", "instalar_skill": "Instalo skill",
             "usar_skill": "Leo la skill", "mirar_detalle": "Miro la pantalla en alta resolución",
             "hablar_con_claude": "Encargo a Claude Code", "ejecutar_shell": "Comando", "recordar": "Guardo en memoria",
             "consultar_clima": "Consulto el tiempo", "abrir": "Abro", "dormir": "A dormir"}
MAX_PASOS = 7

# Fusión (2026-10-19): 55 herramientas confundían al modelo; las de un mismo tema van en una con «accion».
# nombre → (descripción, {parámetro: descripción}, {accion: (herramienta real, {param real: param fusionado}, {param real: valor fijo})})
def _r(real, ren=None, fijo=None):
    return real, ren or {}, fijo or {}

_MUSICA = ("pausa", "seguir", "siguiente", "anterior", "subir", "bajar", "parar", "que_suena")
FUSIONES = {
    "impresora": ("Impresora 3D, SOLO LECTURA. estado: temperaturas, progreso, tiempo restante, capa, velocidad, flujo, "
                  "ventilador, filamento y Klipper. historial: impresiones recientes, cola y errores de Klipper. "
                  "avisar_antes: aviso cuando falten N minutos para que acabe la impresión.",
                  {"minutos_antes": "para avisar_antes: minutos antes del final (por defecto 5)"},
                  {"estado": _r("estado_impresora"), "historial": _r("historial_impresora"),
                   "avisar_antes": _r("programar_aviso_impresora")}),
    "avisos": ("Temporizadores, recordatorios y alarmas (sobreviven a reinicios). programar: «avísame en 20 minutos», "
               "«recuérdame a las 18:30 llamar a Juan», «despiértame a las 8» (tipo alarma: suena en bucle hasta "
               "accion=parar_alarma). ver: los pendientes y la hora actual. cancelar: los que contengan texto, o «todos».",
               {"texto": "programar: qué recordar («sacar la pizza»); cancelar: parte del texto o «todos»",
                "en_minutos": "programar: dentro de cuántos minutos, p.ej. 20 o 1.5",
                "a_las": "programar: hora HH:MM (la próxima vez que llegue) o AAAA-MM-DD HH:MM",
                "tipo": "programar: aviso (por defecto, suena una vez) | alarma (en bucle)",
                "repetir": "programar: vacío | diario"},
               {"programar": _r("programar_aviso"), "ver": _r("ver_avisos"),
                "cancelar": _r("cancelar_aviso", {"cual": "texto"}), "parar_alarma": _r("parar_alarma")}),
    "claude": ("Claude Code, el agente de código del repo WORMHOLE. hablar: UNA conversación persistente que recuerda lo "
               "anterior (vale «ahora hazlo más grueso»), trabaja en segundo plano y avisa; úsala para toda petición de "
               "código, CAD o archivos del repo. tarea_suelta: un disparo sin memoria (pide confirmación). "
               "estado: qué hace ahora. cancelar: interrumpe su tarea.",
               {"mensaje": "hablar/tarea_suelta: lo que quieres que haga, completo y claro"},
               {"hablar": _r("hablar_con_claude"), "tarea_suelta": _r("preguntar_a_claude", {"tarea": "mensaje"}),
                "estado": _r("estado_claude"), "cancelar": _r("cancelar_claude")}),
    "memoria": ("Memoria persistente (sobrevive a reinicios). recordar: guarda una nota. olvidar: borra las notas que "
                "contengan texto. anotar_mejora: cuando el USUARIO pida una función NUEVA que aún no tienes, para el "
                "programador; una avería que persiste (micro, audio, impresora…) anótala UNA sola vez, no repitas.",
                {"texto": "la nota, el fragmento a borrar o la mejora descrita con claridad"},
                {"recordar": _r("recordar", {"nota": "texto"}), "olvidar": _r("olvidar", {"fragmento": "texto"}),
                 "anotar_mejora": _r("anotar_mejora", {"descripcion": "texto"})}),
    "skills": ("Skills (capacidades con instrucciones). buscar: en las instaladas y en el catálogo skills.sh (en inglés "
               "da más resultados). instalar: descarga una del catálogo, pide permiso al usuario y devuelve sus "
               "instrucciones. usar: lee las instrucciones de una instalada para seguirlas. actualizar: todas desde su origen.",
               {"que": "buscar: tema; instalar: id owner/repo/skill tal como lo dio buscar; usar: nombre de la skill"},
               {"buscar": _r("buscar_skills", {"consulta": "que"}), "instalar": _r("instalar_skill", {"id_skill": "que"}),
                "usar": _r("usar_skill", {"nombre": "que"}), "actualizar": _r("sincronizar_skills")}),
    "musica": ("Música de YouTube. poner: busca y pone (canción, artista, estilo o lista; sustituye a la que sonara). "
               "El resto controla la que pusiste.",
               {"busqueda": "poner: qué poner, p.ej. «Los Planetas», «jazz para trabajar», «lofi»"},
               {"poner": _r("poner_musica"), **{a: _r("controlar_musica", fijo={"accion": a}) for a in _MUSICA}}),
    "vista": ("Tu interfaz. panel / mascota / invisible: panel completo, solo el animal flotando («modo mascota»), o "
              "ni animal ni panel y solo una tira de estado en una esquina («modo invisible», «quítate de en medio», «esconde la mascota», «quita el bicho del escritorio», «no quiero verte»). "
              "elegir_mascota: cual = mapache | gato, qué animal es la mascota («pon el gato», «quiero el mapache»). "
              "fondo: el del modo espera, cual = auto (rota; la impresión manda mientras imprime) | reloj | mascota | "
              "impresion | tiempo («pon el reloj de fondo», «salvapantallas»). pantalla_completa: cual = impresora (la "
              "pieza 3D en vivo con capas, tiempos, temperaturas, histórico…) | tiempo (Nothing Weather entero) | sistema "
              "(procesos por RAM y cuáles se pueden cerrar; enséñalo y dilo) | salir («ponme la impresora en grande», "
              "«¿qué está comiendo RAM?»).",
              {"cual": "fondo: auto | reloj | mascota | impresion | tiempo; pantalla_completa: impresora | tiempo | sistema | salir; "
                       "elegir_mascota: mapache | gato"},
              {"panel": _r("cambiar_vista", fijo={"modo": "panel"}), "mascota": _r("cambiar_vista", fijo={"modo": "mascota"}),
               "invisible": _r("cambiar_vista", fijo={"modo": "invisible"}),
               "elegir_mascota": _r("elegir_mascota", {"cual": "cual"}),
               "fondo": _r("fondo", {"escena": "cual"}), "pantalla_completa": _r("pantalla_completa", {"que": "cual"})}),
    "documentos": ("Secretario, en ~/Documentos/Delta/documentos. crear: redacta carta, instancia, reclamación, resumen, "
                   "acta, lista, apuntes, dossier, notas dictadas… («hazme un PDF», «redáctame», «toma nota de esto en un "
                   "archivo»); con buscar=sí busca antes en la web y cita fuentes; para investigar a fondo usa investigar y "
                   "luego convertir. convertir: un informe o documento ya hecho a pdf, docx u odt. enviar_al_movil: lo "
                   "manda al móvil por KDE Connect (los informes van en PDF).",
                   {"encargo": "crear: qué documento y para qué, con TODOS los datos; si dicta el texto, cópialo literal",
                    "nombre": "convertir/enviar_al_movil: parte del nombre del documento o informe",
                    "formato": "crear: pdf (por defecto) | docx | odt | txt | md; convertir: pdf | docx | odt",
                    "buscar": "crear: sí si hace falta buscar datos en internet",
                    "al_movil": "crear: sí si quiere que se lo mande al móvil al terminar"},
                   {"crear": _r("crear_documento"), "convertir": _r("convertir_documento"),
                    "enviar_al_movil": _r("enviar_al_movil")}),
    "taller": ("trabajos: los trabajos en segundo plano y su estado. proyectos: sin nombre lista los recientes; con nombre "
               "lee su ESTADO.md para decir dónde se dejó.",
               {"nombre": "proyectos: parte del nombre del proyecto, opcional"},
               {"trabajos": _r("ver_trabajos"), "proyectos": _r("estado_proyectos")}),
    "clima": ("consultar: el tiempo ahora y la previsión de hasta 3 días; sin lugar, donde está el usuario. Úsala siempre "
              "que pregunte por el tiempo, la temperatura, el viento o la lluvia. fijar_ubicacion: dónde está el usuario "
              "(«estoy en Chiclana»); no hay GPS, así que esto manda; lugar=auto la borra.",
              {"lugar": "ciudad o sitio; en consultar, vacío = donde está el usuario", "dias": "consultar: 1 a 3 (por defecto 1)"},
              {"consultar": _r("consultar_clima"), "fijar_ubicacion": _r("fijar_ubicacion")}),
    "movil": ("El móvil del usuario. notificaciones: lee las que tiene (WhatsApp, Telegram, correo, llamadas…). sonar: lo "
              "hace sonar a todo volumen para encontrarlo. Para contestar usa responder_notificacion o enviar_sms.",
              {}, {"notificaciones": _r("notificaciones_movil"), "sonar": _r("sonar_movil")}),
}


def fusionar():
    """Sustituye las herramientas de FUSIONES por la fusionada; llamar tras registrar todos los módulos."""
    reales = {r for _, _, ramas in FUSIONES.values() for r, _, _ in ramas.values()}
    DECLARATIONS[:] = [d for d in DECLARATIONS if d.name not in reales]
    for nombre, (desc, props, ramas) in FUSIONES.items():
        DECLARATIONS.append(_fn(nombre, desc, {"accion": _s(" | ".join(ramas)), **{k: _s(v) for k, v in props.items()}},
                                req=["accion"]))
        async def explica(*_, _n=nombre, _r=ramas, **__):
            return f"Error: {_n} necesita accion = {' | '.join(_r)}"
        HANDLERS[nombre] = explica
    TOOLS[1] = types.Tool(function_declarations=DECLARATIONS)


def _real(nombre, args):
    """(fusionada, args) → (herramienta real, sus args). Con accion inválida devuelve la fusionada, que explica el error."""
    if nombre not in FUSIONES or args.get("accion") not in FUSIONES[nombre][2]:
        return nombre, args
    real, ren, fijo = FUSIONES[nombre][2][args.pop("accion")]
    acepta = inspect.signature(HANDLERS[real]).parameters
    de = {f: r for r, f in ren.items()}
    args = {de.get(k, k): v for k, v in args.items()}
    args = {k: v for k, v in args.items() if k in acepta}
    return real, {**args, **{k: v for k, v in fijo.items() if k in acepta}}


def paso(texto, estado="en curso"):
    """Paso visible en el recuadro de estado del panel; devuelve el dict para marcarlo «hecho»/«falló»."""
    p = {"t": texto, "e": estado, "h": time.strftime("%H:%M:%S")}
    ST.setdefault("pasos", []).append(p)
    del ST["pasos"][:-MAX_PASOS]
    return p


def _paso(nombre, args):
    arg = next((str(v) for v in args.values() if v), "")
    return paso(ETIQUETAS.get(nombre, nombre.replace("_", " ").capitalize()) + (f" · {arg[:60]}" if arg else ""))


async def atender(session, tool_call):
    ST["ultima"] = time.monotonic()
    for fc in tool_call.function_calls:
        print(f"\n🔧 {fc.name}({dict(fc.args or {})})")
        nombre, args = _real(fc.name, dict(fc.args or {}))
        ST["herramienta"] = nombre
        paso = _paso(nombre, args)
        try:
            out = await HANDLERS[nombre](**args)
            paso["e"] = "falló" if str(out).startswith("Error") else "hecho"
        except Exception as e:
            out = f"Error: {e}"
            paso["e"] = "falló"
        finally:
            ST["herramienta"] = None
        try:
            await session.send_tool_response(function_responses=[
                types.FunctionResponse(id=fc.id, name=fc.name, response={"output": out})])
        except Exception as e:  # la sesión se reconectó mientras la herramienta trabajaba
            print(f"\n⚠️ Respuesta de {fc.name} perdida ({e}); resultado: {str(out)[:200]}")


if __name__ == "__main__":
    for c in ["ps aux --sort=-%mem | head -n 6", "free -h && df -h /", "journalctl -b -p err | tail -20",
              "systemctl status ollama", "sort x | uniq -c", "top -b -n1 | head"]:
        assert _solo_lectura(c), c
    for c in ["rm -rf /", "ps > x", "ls; rm x", "find . -delete", "cat $(ls)", "sudo ls", "systemctl stop x",
              "top", "sort -o x y", "uniq a b", "curl http://192.168.0.102:7125", "env rm x", "ls &", "echo `id`",
              # secretos (2026-10-19): todos pasaban sin preguntar
              "env", "printenv GEMINI_API_KEY", "echo $GEMINI_API_KEY", "cat ~/.bashrc", "cat /home/x/.bashrc",
              "grep -r KEY ~/.config", "grep -nr gemini ~", "cat movil_clave.txt", "cat movil_cl''ave.txt", "cat movil_*",
              "head movil_cl{a,}ve.txt", "find / -name id_ed25519", "cat /proc/self/environ", "ps auxe", "ps e",
              "tail ../.ssh/config", "rg --hidden gemini ~", "cat movil_vapid.pem", "ls ~/.gnupg"]:
        assert not _solo_lectura(c), c
    for c in ["ps -eo pid,cmd --sort=-%mem | head", "ls -la ./trabajos", "cat ../README.md", "grep -i error assistant.log",
              "journalctl -u ollama.service | tail", "ps aux | grep '[p]ython'", "find . -name '*.py'", "cut -d. -f1 x"]:
        assert _solo_lectura(c), c  # lo de siempre sigue sin preguntar
    os.environ["PRUEBA_API_KEY"] = "AIzaFalsaDePrueba1234"
    assert "AIza" not in _tapar("export PRUEBA_API_KEY=AIzaFalsaDePrueba1234")
    for c in ["kill $(ps -eo pid,ni,cmd | awk '$2 < 0 {print $1}')", "pkill wireplumber", "killall kwin_wayland",
              "kill -9 -1", "kill `pgrep x`"]:
        assert _mata_sesion(c), c
    for c in ["kill 12345", "pkill chromium", "killall mpv", "ps aux"]:
        assert not _mata_sesion(c), c
    print("ok")
