"""Pruebas del modo estudiante (sin API): .venv/bin/python test_estudio.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import estudio_clase as ec

AQUI = Path(__file__).parent

# el tema sale del nombre que pone la academia
assert ec.tema_de("T1_DDHH_(1ºP_Curso…).mp3") == 1
assert ec.tema_de("T2_Igualdad_(Curso_PRO).mp3") == 2
assert ec.tema_de("Tema 14 - Interior.mp3") == 14
assert ec.tema_de("Clase_sin_numero.mp3") is None
# sin «T4» en el título: por el nombre del tema, para que todas las de Constitución vayan al mismo PDF
temas = [f.stem for f in sorted(ec.TEMARIO.glob("Tema [0-9][0-9] - *.pdf"))]
assert ec.tema_por_titulo("PRO_MILITARES_-_Constitución_Española_Parte_3_-_Paco_Arriola [123].mp4", temas) == 4
assert ec.tema_por_titulo("Derecho Penal - clase 2", temas) == 8
assert ec.tema_por_titulo("Derecho procesal penal", temas) == 9
assert ec.tema_por_titulo("Clase_sin_numero.mp3", temas) is None
assert ec.tema_de("PRO_MILITARES_-_T1_DDHH_Carta_de_las_NNUU [1236086480].mp4") == 1  # nombre que pone bajar()

# la página de la academia lleva el id de Vimeo y el título acaba en el profesor
assert ec.VIDEO_ACADEMIA.search("https://app.procivil.es/content/video/1236086480?title=PRO").group(1) == "1236086480"
assert ec.profe_de("PRO / MILITARES - T1 DDHH Carta de las NNUU - Parte 1 -  Paco Arriola") == "Paco Arriola"
assert ec.profe_de("T2 Igualdad - Parte 1") == "" and ec.profe_de("Sin guiones") == ""
assert ec.segundos("1:02:03") == 3723 and ec.segundos("[P2·0:05:28]") == 328

# una clase nueva se AÑADE al final; la repetida no se duplica y solo actualiza el profe
a, b, c = Path("/x/T1_a.mp3"), Path("/x/T1_b.mp3"), Path("/otra/ruta/T1_a.mp3")
r = ec.juntar([], [a, b], ["Jesús Rico"])
assert r == [{"audio": str(a), "profe": "Jesús Rico"}, {"audio": str(b), "profe": ""}], r
r2 = ec.juntar(r, [c], ["Paco"])  # mismo archivo movido de carpeta: es la misma clase
assert [x["audio"] for x in r2] == [str(a), str(b)] and r2[0]["profe"] == "Paco", r2
assert r[0]["profe"] == "Jesús Rico"  # no toca la lista de entrada
assert ec.juntar(r, [Path("/x/T1_c.mp3")], [])[-1]["audio"] == "/x/T1_c.mp3"


def corre(*args):
    return subprocess.run([sys.executable, str(AQUI / "estudio_clase.py"), *args], capture_output=True, text=True)


# entradas malas: se rechazan antes de gastar API y sin tocar nada
with tempfile.TemporaryDirectory() as d:
    corto = Path(d) / "T1_corte.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "10", str(corto)], check=True)
    os.utime(corto, (1, 1))  # como si la descarga hubiera acabado hace rato
    r = corre("--audio", str(corto))
    assert r.returncode and "no parece una clase" in r.stderr, r.stderr
    roto = Path(d) / "T1_roto.mp3"
    roto.write_bytes(b"esto no es audio")
    os.utime(roto, (1, 1))
    r = corre("--audio", str(roto))
    assert r.returncode and "descarga a medias" in r.stderr, r.stderr
    r = corre("--tema", "24", "--audio", str(corto))
    assert r.returncode and "invalid choice" in r.stderr, r.stderr
    r = corre("--audio", str(Path(d) / "no_existe.mp3"))
    assert r.returncode and "No existe" in r.stderr, r.stderr
    # el mismo vídeo bajado por otra vía (otro nombre, misma duración) reutiliza la clase; otra duración es otra clase
    otro, largo = Path(d) / "T1_otro_nombre.mp4", Path(d) / "T1_largo.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(corto), str(otro)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "20", str(largo)], check=True)
    clases = [{"audio": str(corto), "profe": ""}]
    assert ec.misma_clase(otro, clases) == corto and ec.misma_clase(largo, clases) == largo

# el PDF anterior solo se guarda en «Versiones anteriores» si tiene anotaciones que no son de Delta
import pymupdf
import estudio_pdf
with tempfile.TemporaryDirectory() as d:
    f = os.path.join(d, "x.pdf")
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((50, 50), "hola mundo")
    estudio_pdf.subrayar(pg, pg.search_for("hola"), "estudio")
    doc.save(f)
    assert not estudio_pdf.tocado_a_mano(f)
    doc = pymupdf.open(f)
    nota = doc[0].add_text_annot((80, 80), "mi nota")
    nota.set_info(title="jloslop")
    nota.update()
    doc.saveIncr()
    assert estudio_pdf.tocado_a_mano(f)

# el HUD saca etapa y % de la última línea «[NN%]» del log del trabajo, aunque luego vengan otras
import acciones
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "x.log"
    f.write_text("16:00:00 [12%] Transcribiendo…\n16:01:00 [23%] Transcribiendo: 1/4 tramos\n16:01:02   audio1/t00.ogg: 9 intervenciones\n\n")
    assert acciones.etapa(f) == {"pct": 23, "etapa": "Transcribiendo: 1/4 tramos"}
    f.write_text("hola\nTraceback x\n")
    assert acciones.etapa(f) == {"pct": None, "etapa": "Traceback x"}

# atender() hace await de cada herramienta: una síncrona da error aunque haga su trabajo
import inspect
import estudio
assert all(inspect.iscoroutinefunction(f) for f in acciones.HANDLERS.values()), \
    [n for n, f in acciones.HANDLERS.items() if not inspect.iscoroutinefunction(f)]

print("ok")
