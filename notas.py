"""Notas: el cajón desastre del usuario, LOCAL y sin conectar a nada («apunta en notas que…»).

No es la memoria (memoria.py): la memoria son datos sobre el usuario que Delta debe tener siempre presentes y se
inyectan al despertar; esto es lo que el usuario echa al cajón para mirarlo él cuando quiera. De ahí las reglas:

  - Solo SQLite, en `notas.db`, aparte de memoria.db y gitignored (`notas.db*`: también -wal, -shm y -journal).
  - NO se inyecta en ningún contexto (ni memoria.contexto() ni panel.contexto()) y NO la ve Claude Code (ni
    hablar_con_claude, ni mejorar_delta, ni preguntar_a_claude) ni el puente MCP: Delta solo las lee cuando el
    usuario se las pide, con nota_listar / nota_buscar.
  - El panel (que también sale en la tele) recibe SOLO `resumen()`: cuántas hay y cuándo se apuntó la última.
  - Se guarda el texto TAL CUAL: sin resumir, sin corregir, sin quitar duplicados.
  - Borrar es BLANDO: la nota queda 30 días con `borrada_en` por si el usuario se arrepiente, y luego se purga.

El buscador y las palabras vacías son los de memoria.py: «nino» encuentra «niño».
"""
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

from memoria import _consulta   # solo la consulta FTS5; memoria.py no abre su base hasta que se la usa

AQUI = Path(__file__).parent
BD = AQUI / "notas.db"

PURGA_DIAS = 30               # cuánto se conserva una nota borrada
BUSCA_N = 8                   # resultados por búsqueda
LISTA_N = 5                   # notas por defecto al listar

ESQUEMA = """
CREATE TABLE IF NOT EXISTS notas(
  id INTEGER PRIMARY KEY,
  texto TEXT NOT NULL,
  etiqueta TEXT,                       -- una palabra, opcional
  creada REAL NOT NULL,
  borrada_en REAL                      -- NULL = viva; si no, borrada (blando) hasta la purga
);
CREATE VIRTUAL TABLE IF NOT EXISTS notas_fts USING fts5(
  texto, etiqueta, content='notas', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS notas_ai AFTER INSERT ON notas BEGIN
  INSERT INTO notas_fts(rowid, texto, etiqueta) VALUES (new.id, new.texto, new.etiqueta); END;
CREATE TRIGGER IF NOT EXISTS notas_ad AFTER DELETE ON notas BEGIN
  INSERT INTO notas_fts(notas_fts, rowid, texto, etiqueta) VALUES('delete', old.id, old.texto, old.etiqueta); END;
CREATE TRIGGER IF NOT EXISTS notas_au AFTER UPDATE OF texto, etiqueta ON notas BEGIN
  INSERT INTO notas_fts(notas_fts, rowid, texto, etiqueta) VALUES('delete', old.id, old.texto, old.etiqueta);
  INSERT INTO notas_fts(rowid, texto, etiqueta) VALUES (new.id, new.texto, new.etiqueta); END;
"""

_con = None
_res = None                   # {"n", "ultima"}: se recalcula al escribir, no por fotograma del panel


def db():
    """Una conexión para todo el proceso (las acciones corren en el bucle de asyncio, alguna desde to_thread)."""
    global _con
    if _con is None:
        _con = sqlite3.connect(BD, check_same_thread=False)
        _con.row_factory = sqlite3.Row
        _con.executescript(ESQUEMA)
        _con.commit()
        purgar()
    return _con


def _plano(s):
    """Minúsculas y sin acentos: para casar lo dictado («ultima») con lo escrito («última»)."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if not unicodedata.combining(c)).strip()


def _refrescar():
    global _res
    f = db().execute("SELECT count(*) AS n, max(creada) AS ultima FROM notas WHERE borrada_en IS NULL").fetchone()
    _res = {"n": f["n"], "ultima": f["ultima"]}


def resumen():
    """Lo ÚNICO que sale de este módulo hacia el panel: cuántas notas y cuándo se apuntó la última (epoch, o None)."""
    try:
        if _res is None:
            _refrescar()
        return dict(_res)
    except Exception:
        return {"n": 0, "ultima": None}


def purgar():
    """Borra de verdad las notas borradas hace más de PURGA_DIAS. Devuelve cuántas."""
    c = db()
    n = c.execute("DELETE FROM notas WHERE borrada_en IS NOT NULL AND borrada_en < ?",
                  (time.time() - PURGA_DIAS * 86400,)).rowcount
    c.commit()
    return n


# ---------- escribir ----------
def guardar(texto, etiqueta=None):
    texto = (texto or "").strip()
    if not texto:
        return "Error: la nota está vacía."
    palabras = re.findall(r"\w+", (etiqueta or "").lower())
    etiqueta = palabras[0] if palabras else None
    c = db()
    c.execute("INSERT INTO notas(texto, etiqueta, creada) VALUES (?, ?, ?)", (texto, etiqueta, time.time()))
    c.commit()
    purgar()
    _refrescar()
    return "Anotado. Responde solo «Anotado», sin repetir la nota."


def borrar(fragmento=None):
    """Borrado blando. Sin fragmento (o «la última») borra la más reciente; con fragmento, la más reciente que
    lo contenga. Dice cuál ha sido y, si había más que coinciden, cuántas quedan sin tocar."""
    frag = _plano(fragmento)
    if frag in ("", "ultima", "la ultima", "ultima nota", "la ultima nota", "esa", "esa nota", "esta", "la anterior"):
        frag = ""
    vivas = db().execute("SELECT id, texto FROM notas WHERE borrada_en IS NULL ORDER BY creada DESC, id DESC").fetchall()
    coinciden = [f for f in vivas if frag in _plano(f["texto"])]
    if not coinciden:
        return "No tengo ninguna nota con eso." if frag else "No hay ninguna nota."
    f = coinciden[0]
    db().execute("UPDATE notas SET borrada_en = ? WHERE id = ?", (time.time(), f["id"]))
    db().commit()
    _refrescar()
    resto = len(coinciden) - 1 if frag else 0      # «la última» no es una búsqueda: no hay «otras que coinciden»
    return (f"Borrada: «{f['texto']}»." + (f" Hay otras {resto} que también coinciden; no las he tocado." if resto else "")
            + f" Se conserva {PURGA_DIAS} días por si hay que recuperarla.")


# ---------- leer ----------
def _desde_hasta(cuando):
    """«hoy» | «ayer» | «semana» (7 días) | «mes» (30 días) → (desde, hasta) en epoch; None = sin límite."""
    ahora = time.time()
    hoy = time.mktime(time.localtime(ahora)[:3] + (0, 0, 0, 0, 0, -1))
    c = _plano(cuando)
    if c == "hoy":
        return hoy, None
    if c == "ayer":
        return hoy - 86400, hoy
    if c in ("semana", "esta semana", "la semana"):
        return ahora - 7 * 86400, None
    if c in ("mes", "este mes", "el mes"):
        return ahora - 30 * 86400, None
    return None, None


def listar(cuando=None, n=LISTA_N):
    try:
        n = max(1, min(int(n), 50))
    except (TypeError, ValueError):
        n = LISTA_N
    desde, hasta = _desde_hasta(cuando)
    filas = db().execute(
        "SELECT texto, etiqueta, creada FROM notas WHERE borrada_en IS NULL AND creada >= ? AND creada < ? "
        "ORDER BY creada DESC, id DESC LIMIT ?", (desde or 0, hasta or 9e18, n)).fetchall()
    return [dict(f) for f in filas]


def buscar(consulta, n=BUSCA_N):
    q = _consulta(consulta)
    if not q:
        return []
    filas = db().execute(
        "SELECT n.texto, n.etiqueta, n.creada FROM notas_fts f JOIN notas n ON n.id = f.rowid "
        "WHERE notas_fts MATCH ? AND n.borrada_en IS NULL ORDER BY bm25(notas_fts) LIMIT ?", (q, n)).fetchall()
    return [dict(f) for f in filas]


def cuando_fue(t):
    """«hoy 14:05», «ayer 09:30», «23/10 18:00»."""
    l, hoy, ayer = time.localtime(t), time.localtime(), time.localtime(time.time() - 86400)
    dia = (l.tm_year, l.tm_yday)
    if dia == (hoy.tm_year, hoy.tm_yday):
        pre = "hoy"
    elif dia == (ayer.tm_year, ayer.tm_yday):
        pre = "ayer"
    else:
        pre = time.strftime("%d/%m", l)
    return f"{pre} {time.strftime('%H:%M', l)}"


def formato(filas):
    return "\n".join(f"- {cuando_fue(f['creada'])} · {f['texto']}" + (f" [{f['etiqueta']}]" if f["etiqueta"] else "")
                     for f in filas)
