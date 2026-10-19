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

print("ok")
