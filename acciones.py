"""Herramientas (function calling) que Gemini puede invocar + estado compartido."""
import asyncio
import json
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


async def _confirmar(texto: str, voz=False) -> bool:
    """Pregunta al usuario por teclado [s/N] o botón del panel. voz=True deja contestar también
    con responder_permiso, pero solo si el usuario habla después de la pregunta (ver ST["t_tu"])."""
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
    tarea(_trabajo(nombre, argv, cwd, timeout))
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


# Consultas que el usuario autorizó sin preguntar (2026-10-15): solo programas que leen.
# Nada de red (curl/wget podrían mandar órdenes a la impresora), ni nada que lance otros comandos.
LECTURA = {"ps", "pgrep", "top", "free", "df", "du", "uptime", "uname", "lscpu", "lsblk", "lsusb", "lspci", "lsmod",
           "sensors", "nproc", "whoami", "id", "date", "cal", "hostname", "ip", "ss", "cat", "head", "tail", "wc", "ls",
           "stat", "file", "grep", "rg", "find", "which", "whereis", "echo", "sort", "uniq", "cut", "tr", "column",
           "journalctl", "systemctl", "pactl", "rpm", "flatpak", "vmstat", "iostat", "zramctl", "swapon", "last", "w",
           "who", "env", "printenv", "basename", "dirname", "realpath", "readlink", "md5sum", "sha256sum", "nvidia-smi"}
PROHIBIDO = {"find": ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"),
             "sort": ("-o", "--output", "--compress"), "rg": ("--pre",), "file": ("-C", "--compile"), "journalctl": ("--vacuum", "--rotate", "--flush", "--sync", "--setup-keys"),
             "swapon": ("",), "env": ("",)}  # sin argumentos: con ellos env ejecuta programas y swapon activa swap
SUBORDEN = {"systemctl": {"status", "list-units", "list-timers", "list-unit-files", "is-active", "is-enabled", "show"},
            "pactl": {"list", "info", "get-default-sink", "get-default-source", "get-sink-volume", "get-sink-mute"},
            "rpm": {"-q", "-qa", "-qi", "-ql", "-qf"}, "flatpak": {"list", "info"}}


def _solo_lectura(comando):
    """True si todo el comando son programas de LECTURA unidos por tuberías, && o ;, sin redirecciones ni subcomandos."""
    if re.search(r"[<>`\n]|\$\(", comando):
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
    return f"[código {code}]\n{out}"


async def preguntar_a_claude(tarea):
    if not await _confirmar(f"delegar en Claude Code: {tarea}"):
        return "El usuario denegó la tarea."
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


def paso(texto, estado="en curso"):
    """Paso visible en el recuadro de estado del panel; devuelve el dict para marcarlo «hecho»/«falló»."""
    p = {"t": texto, "e": estado, "h": time.strftime("%H:%M:%S")}
    ST.setdefault("pasos", []).append(p)
    del ST["pasos"][:-MAX_PASOS]
    return p


def _paso(fc):
    arg = next((str(v) for v in (fc.args or {}).values() if v), "")
    return paso(ETIQUETAS.get(fc.name, fc.name.replace("_", " ").capitalize()) + (f" · {arg[:60]}" if arg else ""))


async def atender(session, tool_call):
    ST["ultima"] = time.monotonic()
    for fc in tool_call.function_calls:
        print(f"\n🔧 {fc.name}({dict(fc.args or {})})")
        ST["herramienta"] = fc.name
        paso = _paso(fc)
        try:
            out = await HANDLERS[fc.name](**(fc.args or {}))
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
              "top", "sort -o x y", "uniq a b", "curl http://192.168.0.102:7125", "env rm x", "ls &", "echo `id`"]:
        assert not _solo_lectura(c), c
    for c in ["kill $(ps -eo pid,ni,cmd | awk '$2 < 0 {print $1}')", "pkill wireplumber", "killall kwin_wayland",
              "kill -9 -1", "kill `pgrep x`"]:
        assert _mata_sesion(c), c
    for c in ["kill 12345", "pkill chromium", "killall mpv", "ps aux"]:
        assert not _mata_sesion(c), c
    print("ok")
