"""Memoria real: SQLite + FTS5, en vez de un .md que se leía entero cada vez.

Hasta hoy la memoria era `memoria.md` y se metía COMPLETA en el contexto en cada despertar
(assistant.py). Con dos notas eso da igual; con trescientas te comes el contexto en recordar
que un martes de marzo dijiste que te gusta el PETG. Y no había forma de buscar nada: `olvidar`
recorría líneas con un `in`.

Lo que cambia:

  - Cada nota es una fila con su fecha, y FTS5 la indexa. Buscar «qué dije de la boquilla» es
    una consulta, no leerse la libreta entera.
  - Al despertar ya NO se inyecta todo: van las últimas y las que más se consultan. El resto
    está a una búsqueda de distancia, y Delta tiene la acción para hacerla.
  - El tokenizador va sin acentos a propósito (`remove_diacritics 2`): esto se alimenta de voz
    dictada, y «niño» transcrito como «nino» tiene que encontrar la nota igual.

`memoria.md` no se borra: queda como copia legible y de ahí se importa la primera vez.
"""
import re
import sqlite3
import time
from pathlib import Path

AQUI = Path(__file__).parent
BD = AQUI / "memoria.db"
MD = AQUI / "memoria.md"      # la libreta de antes: se importa una vez y se deja como copia

CONTEXTO_N = 12               # notas que se inyectan al despertar (antes: todas)
BUSCA_N = 8                   # resultados por búsqueda

ESQUEMA = """
CREATE TABLE IF NOT EXISTS notas(
  id INTEGER PRIMARY KEY,
  texto TEXT NOT NULL,
  creada REAL NOT NULL,
  veces INTEGER NOT NULL DEFAULT 0,   -- cuántas veces ha salido en una búsqueda
  ultima REAL                          -- cuándo salió por última vez
);
CREATE VIRTUAL TABLE IF NOT EXISTS notas_fts USING fts5(
  texto, content='notas', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
-- Los disparadores mantienen el índice al día: si se escribe en notas sin pasar por aquí,
-- la búsqueda seguiría encontrándolo.
CREATE TRIGGER IF NOT EXISTS notas_ai AFTER INSERT ON notas BEGIN
  INSERT INTO notas_fts(rowid, texto) VALUES (new.id, new.texto); END;
CREATE TRIGGER IF NOT EXISTS notas_ad AFTER DELETE ON notas BEGIN
  INSERT INTO notas_fts(notas_fts, rowid, texto) VALUES('delete', old.id, old.texto); END;
CREATE TRIGGER IF NOT EXISTS notas_au AFTER UPDATE OF texto ON notas BEGIN
  INSERT INTO notas_fts(notas_fts, rowid, texto) VALUES('delete', old.id, old.texto);
  INSERT INTO notas_fts(rowid, texto) VALUES (new.id, new.texto); END;
"""

_con = None


def db():
    """Una conexión para todo el proceso. check_same_thread=False porque las acciones corren en
    el bucle de asyncio y alguna llega desde un hilo de to_thread."""
    global _con
    if _con is None:
        _con = sqlite3.connect(BD, check_same_thread=False)
        _con.row_factory = sqlite3.Row
        _con.executescript(ESQUEMA)
        _con.commit()
        _importar_md()
    return _con


def _importar_md():
    """La libreta vieja, una sola vez. Si ya hay notas no se toca: no vaya a resucitar algo
    que el usuario mandó olvidar."""
    if _con.execute("SELECT 1 FROM notas LIMIT 1").fetchone() or not MD.exists():
        return
    ahora = time.time()
    lineas = [l.strip().lstrip("-").strip() for l in MD.read_text().splitlines()]
    filas = [(l, ahora) for l in lineas if l]
    if filas:
        _con.executemany("INSERT INTO notas(texto, creada) VALUES (?, ?)", filas)
        _con.commit()
        print(f"🧠 memoria: importadas {len(filas)} notas de memoria.md")


# Palabras que no distinguen nada. Sin esto, «¿qué dije DE LA boquilla?» casa con cualquier nota
# que lleve un «de», devuelve ruido y —peor— le sube el contador a notas que nadie buscaba, así que
# acaban colándose en el contexto del despertar por la puerta de atrás.
VACIAS = {
    "a", "al", "algo", "ante", "antes", "con", "como", "cual", "cuando", "de", "del", "dije", "dijo",
    "donde", "el", "ella", "ellos", "en", "era", "es", "esa", "ese", "eso", "esta", "este", "esto",
    "fue", "ha", "hay", "la", "las", "le", "lo", "los", "me", "mi", "mucho", "muy", "no", "nos", "o",
    "para", "pero", "por", "que", "qué", "se", "si", "sin", "sobre", "son", "su", "sus", "te", "tiene",
    "todo", "tu", "un", "una", "uno", "unos", "y", "ya", "yo",
}


def _consulta(texto):
    """Texto suelto → consulta FTS5. FTS5 tiene lenguaje propio (AND, OR, NEAR, *, comillas) y una
    frase dictada lo rompe en cuanto lleva un apóstrofo o un guion: se parte en palabras y se cita
    cada una. OR en vez de AND porque bm25 ya ordena y es mejor traer de más que nada —pero fuera
    las palabras vacías, que si no «de» trae media libreta."""
    palabras = [p for p in re.findall(r"\w+", texto or "", re.UNICODE)
                if len(p) > 2 and p.lower() not in VACIAS]
    return " OR ".join(f'"{p}"' for p in palabras) or None


# ---------- escribir ----------
def guardar(texto):
    texto = " ".join((texto or "").split())
    if not texto:
        return "Error: la nota está vacía."
    c = db()
    ya = c.execute("SELECT id FROM notas WHERE lower(texto) = lower(?)", (texto,)).fetchone()
    if ya:  # dicho dos veces no son dos notas; se refresca la fecha y punto
        c.execute("UPDATE notas SET creada = ? WHERE id = ?", (time.time(), ya["id"]))
        c.commit()
        return "Ya lo tenía apuntado."
    c.execute("INSERT INTO notas(texto, creada) VALUES (?, ?)", (texto, time.time()))
    c.commit()
    return "Anotado."


def olvidar(fragmento):
    frag = (fragmento or "").strip()
    if not frag:
        return "Error: di qué hay que olvidar."
    c = db()
    n = c.execute("DELETE FROM notas WHERE lower(texto) LIKE lower(?)", (f"%{frag}%",)).rowcount
    c.commit()
    return f"Borradas {n} notas." if n else "No tenía nada apuntado con eso."


# ---------- leer ----------
def buscar(consulta, n=BUSCA_N):
    q = _consulta(consulta)
    if not q:
        return []
    c = db()
    filas = c.execute(
        "SELECT n.id, n.texto, n.creada FROM notas_fts f JOIN notas n ON n.id = f.rowid "
        "WHERE notas_fts MATCH ? ORDER BY bm25(notas_fts) LIMIT ?", (q, n)).fetchall()
    if filas:  # lo consultado sube: es lo que acaba yendo en el contexto del despertar
        c.executemany("UPDATE notas SET veces = veces + 1, ultima = ? WHERE id = ?",
                      [(time.time(), f["id"]) for f in filas])
        c.commit()
    return [dict(f) for f in filas]


def contexto(n=CONTEXTO_N):
    """Lo que se inyecta al despertar. Las más recientes y las más consultadas, no todas: esa
    era justo la avería que esto viene a arreglar."""
    c = db()
    filas = c.execute(
        "SELECT texto, orden FROM ("
        "  SELECT texto, creada AS orden FROM (SELECT texto, creada FROM notas ORDER BY creada DESC LIMIT ?)"
        "  UNION"
        "  SELECT texto, creada AS orden FROM (SELECT texto, creada FROM notas WHERE veces > 0"
        "                                      ORDER BY veces DESC, ultima DESC LIMIT ?)"
        ") ORDER BY orden DESC", (n, max(1, n // 3))).fetchall()
    return "\n".join(f"- {f['texto']}" for f in filas)


def cuantas():
    return db().execute("SELECT count(*) AS n FROM notas").fetchone()["n"]
