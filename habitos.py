"""Calendario de hábitos: una rejilla hábitos × días del mes, local y privada.

Pedido el 25/10/2026 a partir de un calendario de hábitos de papel. Reglas, por las mismas razones que notas.py:

  - Solo SQLite, en `habitos.db`, aparte de memoria.db y notas.db, y gitignored (`habitos.db*`).
  - NO se inyecta en ningún contexto ni lo ve Claude Code: Delta solo lo lee cuando el usuario se lo pide.
  - El panel lo pinta en su visor (página `/habitos`), que escribe por POST en `/habitos/api/*`: esos endpoints
    tocan la base y nada más, nunca hacen hablar a Delta (para eso está el buzón 0700).

Cada casilla tiene tres estados: vacía (ni sí ni no), hecho, y no hecho con un motivo configurable y su color,
que es lo que deja ver de un vistazo POR QUÉ no pudo ser.
"""
import calendar
import json
import re
import sqlite3
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from aiohttp import web

AQUI = Path(__file__).parent
BD = AQUI / "habitos.db"
PAGINA = AQUI / "panel" / "habitos.html"

MAX_HABITOS = 20          # caben en la rejilla sin que el panel se vuelva ilegible
COLORES = ["#5B9BF6", "#4CC38A", "#E0A82E", "#D71921", "#A974E8", "#2EC4C4", "#F27A3D", "#8FA3B0"]
MOTIVOS_INICIALES = [("enfermo", "#D71921"), ("viaje", "#5B9BF6"), ("sin tiempo", "#E0A82E"),
                     ("pereza", "#A974E8"), ("olvido", "#8FA3B0"), ("descanso", "#4CC38A")]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS habitos(
  id INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL,
  color TEXT NOT NULL,
  orden INTEGER NOT NULL,
  creado REAL NOT NULL,
  archivado REAL                       -- NULL = activo; si no, fuera de la rejilla (las marcas se conservan)
);
CREATE TABLE IF NOT EXISTS motivos(
  id INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL,
  color TEXT NOT NULL,
  orden INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS marcas(
  habito INTEGER NOT NULL REFERENCES habitos(id) ON DELETE CASCADE,
  dia TEXT NOT NULL,                   -- AAAA-MM-DD
  hecho INTEGER NOT NULL,              -- 1 sí, 0 no
  motivo INTEGER REFERENCES motivos(id) ON DELETE SET NULL,
  puesto REAL NOT NULL,
  PRIMARY KEY(habito, dia)
);
CREATE INDEX IF NOT EXISTS marcas_dia ON marcas(dia);
"""

_con = None


def _bd():
    global _con
    if _con is None:
        _con = sqlite3.connect(BD)
        _con.row_factory = sqlite3.Row
        _con.execute("PRAGMA foreign_keys=ON")
        _con.executescript(ESQUEMA)
        if not _con.execute("SELECT 1 FROM motivos LIMIT 1").fetchone():
            _con.executemany("INSERT INTO motivos(nombre, color, orden) VALUES(?,?,?)",
                             [(n, c, i) for i, (n, c) in enumerate(MOTIVOS_INICIALES)])
        _con.commit()
    return _con


# ---------- utilidades ----------
def _sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def _color(s, por_defecto):
    s = (s or "").strip()
    return s if re.fullmatch(r"#[0-9a-fA-F]{6}", s) else por_defecto


def _dia(d=""):
    """Normaliza a AAAA-MM-DD. Acepta vacío/hoy, ayer, anteayer, mañana y un número de día del mes en curso."""
    d = _sin_tildes(d).strip()
    hoy = date.today()
    if d in ("", "hoy"):
        return hoy.isoformat()
    if d == "ayer":
        return (hoy - timedelta(days=1)).isoformat()
    if d in ("anteayer", "antes de ayer"):
        return (hoy - timedelta(days=2)).isoformat()
    if d == "manana":
        return (hoy + timedelta(days=1)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return d
    if re.fullmatch(r"\d{1,2}", d):  # «el 7» = el 7 de este mes
        n = int(d)
        ultimo = calendar.monthrange(hoy.year, hoy.month)[1]
        if 1 <= n <= ultimo:
            return date(hoy.year, hoy.month, n).isoformat()
    return hoy.isoformat()


def _mes(m=""):
    """Normaliza a (año, mes). Acepta AAAA-MM, un nombre de mes, «este mes», «el mes pasado» o vacío."""
    m = _sin_tildes(m).strip()
    hoy = date.today()
    if re.fullmatch(r"\d{4}-\d{1,2}", m):
        a, n = m.split("-")
        if 1 <= int(n) <= 12:
            return int(a), int(n)
    if m in ("pasado", "el mes pasado", "mes pasado", "anterior"):
        return (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    nombres = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
               "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    for i, n in enumerate(nombres, 1):
        if n in m:
            return hoy.year, i
    return hoy.year, hoy.month


def _buscar_habito(nombre):
    """El hábito cuyo nombre case con lo dicho (sin tildes, por partes); None si no hay o hay duda."""
    q = _sin_tildes(nombre).strip()
    if not q:
        return None
    filas = _bd().execute("SELECT * FROM habitos WHERE archivado IS NULL ORDER BY orden").fetchall()
    exactos = [f for f in filas if _sin_tildes(f["nombre"]) == q]
    if exactos:
        return exactos[0]
    parciales = [f for f in filas if q in _sin_tildes(f["nombre"]) or _sin_tildes(f["nombre"]) in q]
    return parciales[0] if len(parciales) == 1 else None


def _buscar_motivo(nombre):
    q = _sin_tildes(nombre).strip()
    if not q:
        return None
    filas = _bd().execute("SELECT * FROM motivos ORDER BY orden").fetchall()
    for f in filas:
        if _sin_tildes(f["nombre"]) == q:
            return f
    hay = [f for f in filas if q in _sin_tildes(f["nombre"]) or _sin_tildes(f["nombre"]) in q]
    return hay[0] if len(hay) == 1 else None


# ---------- lectura ----------
def datos_mes(anio, mes):
    """Todo lo que necesita la página: hábitos, motivos, marcas del mes y el resumen por hábito."""
    con = _bd()
    ultimo = calendar.monthrange(anio, mes)[1]
    ini, fin = f"{anio:04d}-{mes:02d}-01", f"{anio:04d}-{mes:02d}-{ultimo:02d}"
    habitos = [dict(h) for h in con.execute(
        "SELECT id, nombre, color, orden FROM habitos WHERE archivado IS NULL ORDER BY orden, id")]
    motivos = [dict(m) for m in con.execute("SELECT id, nombre, color FROM motivos ORDER BY orden, id")]
    marcas = {}
    for m in con.execute("SELECT habito, dia, hecho, motivo FROM marcas WHERE dia BETWEEN ? AND ?", (ini, fin)):
        marcas[f"{m['habito']}:{m['dia']}"] = {"hecho": m["hecho"], "motivo": m["motivo"]}
    hoy = date.today()
    # la racha se cuenta hacia atrás desde hoy; en un mes ya pasado, desde su último día (con la que lo cerró)
    corte = hoy if (anio, mes) == (hoy.year, hoy.month) else (date(anio, mes, ultimo) if (anio, mes) < (hoy.year, hoy.month) else None)
    for h in habitos:
        dias = [d for d in range(1, ultimo + 1) if f"{h['id']}:{anio:04d}-{mes:02d}-{d:02d}" in marcas]
        si = [d for d in dias if marcas[f"{h['id']}:{anio:04d}-{mes:02d}-{d:02d}"]["hecho"]]
        h["si"], h["no"] = len(si), len(dias) - len(si)
        h["racha"] = _racha(h["id"], corte) if corte else 0
    return {"anio": anio, "mes": mes, "dias": ultimo,
            "primer_dia": calendar.monthrange(anio, mes)[0],  # 0 = lunes
            "hoy": date.today().isoformat(), "habitos": habitos, "motivos": motivos, "marcas": marcas}


def _racha(habito_id, hasta=None):
    """Días seguidos hechos contando hacia atrás desde hoy (o desde `hasta`). Un día sin marcar la corta."""
    d = hasta or date.today()
    n = 0
    con = _bd()
    while n < 400:
        f = con.execute("SELECT hecho FROM marcas WHERE habito=? AND dia=?", (habito_id, d.isoformat())).fetchone()
        if not f or not f["hecho"]:
            break
        n += 1
        d -= timedelta(days=1)
    return n


def resumen(anio, mes, habito=None):
    """Texto corto para que Delta lo diga de viva voz."""
    d = datos_mes(anio, mes)
    nombres = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
               "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    cab = f"{nombres[mes - 1]} de {anio}"
    hs = [h for h in d["habitos"] if habito is None or h["id"] == habito["id"]]
    if not hs:
        return f"No hay ningún hábito en el calendario ({cab})."
    motivos = {m["id"]: m["nombre"] for m in d["motivos"]}
    lineas = []
    for h in hs:
        cuenta = {}
        for k, v in d["marcas"].items():
            if int(k.split(":")[0]) == h["id"] and not v["hecho"]:
                cuenta[motivos.get(v["motivo"], "sin motivo")] = cuenta.get(motivos.get(v["motivo"], "sin motivo"), 0) + 1
        porque = ", ".join(f"{n} {v}" for n, v in sorted(cuenta.items(), key=lambda x: -x[1]))
        linea = f"{h['nombre']}: {h['si']} sí y {h['no']} no"
        if h["racha"]:
            linea += f", racha de {h['racha']}"
        if porque:
            linea += f" (por {porque})"
        lineas.append(linea)
    return f"{cab} · " + "; ".join(lineas) + "."


# ---------- escritura ----------
def marcar(habito_id, dia, hecho, motivo_id=None):
    con = _bd()
    if hecho is None:  # quitar la marca: la casilla vuelve a estar vacía
        con.execute("DELETE FROM marcas WHERE habito=? AND dia=?", (habito_id, dia))
    else:
        con.execute("INSERT INTO marcas(habito, dia, hecho, motivo, puesto) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(habito, dia) DO UPDATE SET hecho=excluded.hecho, motivo=excluded.motivo, puesto=excluded.puesto",
                    (habito_id, dia, 1 if hecho else 0, motivo_id if not hecho else None, time.time()))
    con.commit()


def anadir_habito(nombre, color=""):
    nombre = (nombre or "").strip()[:40]
    con = _bd()
    if not nombre:
        raise ValueError("un hábito necesita nombre")
    ya = _buscar_habito(nombre)
    if ya and _sin_tildes(ya["nombre"]) == _sin_tildes(nombre):
        raise ValueError(f"«{nombre}» ya está en el calendario")
    n = con.execute("SELECT COUNT(*) c FROM habitos WHERE archivado IS NULL").fetchone()["c"]
    if n >= MAX_HABITOS:
        raise ValueError(f"ya hay {MAX_HABITOS} hábitos: quita alguno antes de añadir otro")
    cur = con.execute("INSERT INTO habitos(nombre, color, orden, creado) VALUES(?,?,?,?)",
                      (nombre, _color(color, COLORES[n % len(COLORES)]), n, time.time()))
    con.commit()
    return cur.lastrowid


def archivar_habito(habito_id):
    con = _bd()
    con.execute("UPDATE habitos SET archivado=? WHERE id=?", (time.time(), habito_id))
    con.commit()


def renombrar_habito(habito_id, nombre="", color=""):
    con = _bd()
    if nombre.strip():
        con.execute("UPDATE habitos SET nombre=? WHERE id=?", (nombre.strip()[:40], habito_id))
    if _color(color, ""):
        con.execute("UPDATE habitos SET color=? WHERE id=?", (_color(color, ""), habito_id))
    con.commit()


def mover_habito(habito_id, delta):
    """Sube (-1) o baja (+1) un hábito en la rejilla."""
    con = _bd()
    filas = con.execute("SELECT id FROM habitos WHERE archivado IS NULL ORDER BY orden, id").fetchall()
    ids = [f["id"] for f in filas]
    if habito_id not in ids:
        return
    i = ids.index(habito_id)
    j = max(0, min(len(ids) - 1, i + delta))
    ids.insert(j, ids.pop(i))
    for k, x in enumerate(ids):
        con.execute("UPDATE habitos SET orden=? WHERE id=?", (k, x))
    con.commit()


def anadir_motivo(nombre, color=""):
    nombre = (nombre or "").strip()[:30]
    if not nombre:
        raise ValueError("un motivo necesita nombre")
    con = _bd()
    n = con.execute("SELECT COUNT(*) c FROM motivos").fetchone()["c"]
    cur = con.execute("INSERT INTO motivos(nombre, color, orden) VALUES(?,?,?)",
                      (nombre, _color(color, COLORES[n % len(COLORES)]), n))
    con.commit()
    return cur.lastrowid


def cambiar_motivo(motivo_id, nombre="", color=""):
    con = _bd()
    if nombre.strip():
        con.execute("UPDATE motivos SET nombre=? WHERE id=?", (nombre.strip()[:30], motivo_id))
    if _color(color, ""):
        con.execute("UPDATE motivos SET color=? WHERE id=?", (_color(color, ""), motivo_id))
    con.commit()


def borrar_motivo(motivo_id):
    con = _bd()
    con.execute("DELETE FROM motivos WHERE id=?", (motivo_id,))  # las marcas se quedan como «no, sin motivo»
    con.commit()


# ---------- página y API del panel ----------
async def _pagina(request):
    return web.FileResponse(PAGINA, headers={"Cache-Control": "no-cache"})


async def _api_mes(request):
    a, m = _mes(request.query.get("m", ""))
    return web.json_response(datos_mes(a, m))


async def _api_marcar(request):
    d = await request.json()
    try:
        habito_id, dia = int(d["habito"]), _dia(str(d.get("dia", "")))
        hecho = d.get("hecho")
        motivo = d.get("motivo")
        marcar(habito_id, dia, None if hecho is None else bool(hecho), int(motivo) if motivo else None)
    except (KeyError, TypeError, ValueError) as e:
        raise web.HTTPBadRequest(text=str(e))
    a, m = int(dia[:4]), int(dia[5:7])
    return web.json_response(datos_mes(a, m))


async def _api_config(request):
    """Alta, baja y cambios de hábitos y motivos desde el modo edición de la página."""
    d = await request.json()
    accion = str(d.get("accion", ""))
    try:
        if accion == "habito_nuevo":
            anadir_habito(d.get("nombre", ""), d.get("color", ""))
        elif accion == "habito_cambiar":
            renombrar_habito(int(d["id"]), d.get("nombre", ""), d.get("color", ""))
        elif accion == "habito_quitar":
            archivar_habito(int(d["id"]))
        elif accion == "habito_mover":
            mover_habito(int(d["id"]), int(d.get("delta", 0)))
        elif accion == "motivo_nuevo":
            anadir_motivo(d.get("nombre", ""), d.get("color", ""))
        elif accion == "motivo_cambiar":
            cambiar_motivo(int(d["id"]), d.get("nombre", ""), d.get("color", ""))
        elif accion == "motivo_quitar":
            borrar_motivo(int(d["id"]))
        else:
            raise ValueError(f"acción desconocida: {accion}")
    except (KeyError, TypeError, ValueError) as e:
        return web.json_response({"error": str(e)}, status=400)
    a, m = _mes(str(d.get("mes", "")))
    return web.json_response(datos_mes(a, m))


# ---------- herramientas para Gemini ----------
async def habitos_ver(mes=""):
    """Abre el calendario en el panel."""
    import panel
    a, m = _mes(mes)
    panel.S["visor"] = {"url": f"/habitos?m={a:04d}-{m:02d}", "titulo": f"HÁBITOS · {a:04d}-{m:02d}", "id": time.time()}
    return f"Calendario de hábitos de {a:04d}-{m:02d} en el panel. {resumen(a, m)}"


async def habitos_marcar(habito="", hecho="si", motivo="", dia=""):
    h = _buscar_habito(habito)
    if not h:
        hay = ", ".join(x["nombre"] for x in _bd().execute(
            "SELECT nombre FROM habitos WHERE archivado IS NULL ORDER BY orden"))
        return (f"No tengo ningún hábito que se llame «{habito}». Los que hay: {hay or 'ninguno todavía'}. "
                "Si quiere añadirlo, usa habitos_configurar con accion=anadir.")
    d = _dia(dia)
    estado = _sin_tildes(str(hecho)).strip()
    if estado in ("quitar", "ninguno", "borrar", "nada", ""):
        marcar(h["id"], d, None)
        return f"Quitada la marca de «{h['nombre']}» del {d}."
    si = estado in ("si", "true", "1", "hecho", "hice", "cumplido")
    mot = _buscar_motivo(motivo) if (not si and motivo) else None
    if not si and motivo and not mot:
        try:
            mot = _bd().execute("SELECT * FROM motivos WHERE id=?", (anadir_motivo(motivo),)).fetchone()
        except ValueError:
            mot = None
    marcar(h["id"], d, si, mot["id"] if mot else None)
    _refrescar()
    if si:
        r = _racha(h["id"])
        return f"Marcado «{h['nombre']}» como hecho el {d}." + (f" Racha: {r} días seguidos." if r > 1 else "")
    return f"Marcado «{h['nombre']}» como NO hecho el {d}" + (f", motivo «{mot['nombre']}»." if mot else ", sin motivo.")


async def habitos_configurar(accion="", nombre="", nuevo="", color=""):
    accion = _sin_tildes(accion).strip()
    try:
        if accion in ("anadir", "nuevo", "crear"):
            anadir_habito(nombre, color)
            _refrescar()
            return f"Hábito «{nombre}» añadido al calendario."
        if accion in ("quitar", "borrar", "archivar"):
            h = _buscar_habito(nombre)
            if not h:
                return f"No encuentro el hábito «{nombre}»."
            archivar_habito(h["id"])
            _refrescar()
            return f"Hábito «{h['nombre']}» fuera de la rejilla (lo marcado se conserva)."
        if accion in ("renombrar", "cambiar", "color"):
            h = _buscar_habito(nombre)
            if not h:
                return f"No encuentro el hábito «{nombre}»."
            renombrar_habito(h["id"], nuevo, color)
            _refrescar()
            return f"Cambiado «{h['nombre']}»."
        if accion in ("motivo_anadir", "anadir_motivo", "motivo_nuevo"):
            anadir_motivo(nombre, color)
            _refrescar()
            return f"Motivo «{nombre}» añadido."
        if accion in ("motivo_quitar", "quitar_motivo", "borrar_motivo"):
            m = _buscar_motivo(nombre)
            if not m:
                return f"No encuentro el motivo «{nombre}»."
            borrar_motivo(m["id"])
            _refrescar()
            return f"Motivo «{m['nombre']}» borrado."
        if accion in ("listar", "lista", "ver"):
            hs = ", ".join(x["nombre"] for x in _bd().execute(
                "SELECT nombre FROM habitos WHERE archivado IS NULL ORDER BY orden")) or "ninguno"
            ms = ", ".join(x["nombre"] for x in _bd().execute("SELECT nombre FROM motivos ORDER BY orden")) or "ninguno"
            return f"Hábitos: {hs}. Motivos para cuando no se hace algo: {ms}."
    except ValueError as e:
        return f"No he podido: {e}."
    return "Error: accion debe ser anadir, quitar, renombrar, motivo_anadir, motivo_quitar o listar."


async def habitos_resumen(mes="", habito=""):
    a, m = _mes(mes)
    return resumen(a, m, _buscar_habito(habito) if habito else None)


def _refrescar():
    """Si el calendario está puesto en el visor, que la página recargue (cambia el id del visor)."""
    try:
        import panel
        v = panel.S.get("visor") or {}
        if str(v.get("url", "")).startswith("/habitos"):
            panel.S["visor"] = dict(v, id=time.time())
    except Exception:
        pass


def registrar():
    """Rutas en el panel y herramientas en acciones. Lo llama assistant al importar."""
    import acciones
    import panel
    panel.RUTAS.append(("/habitos", _pagina))
    panel.RUTAS.append(("/habitos/api/mes", _api_mes))
    panel.RUTAS_POST.append(("/habitos/api/marcar", _api_marcar))
    panel.RUTAS_POST.append(("/habitos/api/config", _api_config))
    acciones.registrar([
        acciones._fn("habitos_ver",
                     "Enseña en el panel el calendario de hábitos: una rejilla con un hábito por fila y un día por "
                     "columna, donde el usuario marca a golpe de clic si hizo cada cosa, y si no, por qué. Úsalo cuando "
                     "diga «enséñame mis hábitos», «abre el calendario de hábitos», «¿cómo llevo el mes?».",
                     {"mes": acciones._s("AAAA-MM, nombre del mes o «el mes pasado»; vacío = este mes")}, req=[]),
        acciones._fn("habitos_marcar",
                     "Marca en el calendario de hábitos si el usuario hizo o no una cosa un día. Úsalo cuando diga "
                     "«apunta que hoy hice ejercicio», «hoy no fui al gimnasio porque estaba malo», «ayer sí medité», "
                     "«quita la marca de…». Si no lo hizo y dice el motivo, pásalo en motivo (se pinta con su color "
                     "en el calendario para ver de un vistazo qué le frena).",
                     {"habito": acciones._s("nombre del hábito tal como lo tiene en el calendario"),
                      "hecho": acciones._s("si | no | quitar (quitar deja la casilla vacía)"),
                      "motivo": acciones._s("por qué no pudo ser (enfermo, viaje, sin tiempo, pereza…); solo si hecho=no"),
                      "dia": acciones._s("hoy | ayer | anteayer | AAAA-MM-DD | número de día de este mes; vacío = hoy")},
                     req=["habito", "hecho"]),
        acciones._fn("habitos_configurar",
                     "Cambia qué hay en el calendario de hábitos: añadir o quitar un hábito, renombrarlo, cambiarle el "
                     "color, o añadir y quitar motivos de los que explican por qué no se hizo algo. Úsalo cuando diga "
                     "«añade el hábito leer», «quita el de correr», «añade el motivo lluvia», «¿qué hábitos tengo?».",
                     {"accion": acciones._s("anadir | quitar | renombrar | motivo_anadir | motivo_quitar | listar"),
                      "nombre": acciones._s("nombre del hábito o del motivo sobre el que actuar"),
                      "nuevo": acciones._s("nombre nuevo, solo para renombrar"),
                      "color": acciones._s("color en #RRGGBB, opcional")}, req=["accion"]),
        acciones._fn("habitos_resumen",
                     "Cuenta cómo va el mes en el calendario de hábitos (cuántos sí, cuántos no, racha y por qué no pudo "
                     "ser), para decírselo de palabra sin abrir el panel.",
                     {"mes": acciones._s("AAAA-MM, nombre del mes o «el mes pasado»; vacío = este mes"),
                      "habito": acciones._s("un hábito concreto; vacío = todos")}, req=[]),
    ], (habitos_ver, habitos_marcar, habitos_configurar, habitos_resumen))


registrar()
