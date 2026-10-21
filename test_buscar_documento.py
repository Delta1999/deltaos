"""Encontrar un documento por su título aunque el fichero lo lleve recortado y con guiones
(.venv/bin/python test_buscar_documento.py)"""
import os
import tempfile
from pathlib import Path

import deltaos
import secretario

tmp = Path(tempfile.mkdtemp())
deltaos.INFORMES, secretario.DOCS = tmp / "inf", tmp / "docs"
for d in (deltaos.INFORMES, secretario.DOCS):
    d.mkdir()
pdf = secretario.DOCS / "20261021-0108-resumen-provisional-skills-de-análisis-financiero.pdf"
otro = secretario.DOCS / "20261020-2210-carta-de-reclamación-a-la-compañía-del-gas.pdf"
for f in (pdf, otro):
    f.write_bytes(b"%PDF")
os.utime(otro, (2e9, 2e9))  # el más nuevo no tiene que ganar si no se parece

# Lo que pidió Delta el 21/10 a la 01:09 y falló: el título entero, con dos puntos y más largo que el fichero.
assert secretario._buscar("Resumen provisional: Skills de análisis financiero y agenda predictiva") == pdf
assert secretario._buscar(pdf.name) == pdf
assert secretario._buscar("analisis financiero") == pdf  # sin tildes
assert secretario._buscar("la carta del gas") == otro
assert secretario._buscar("informe de la tostadora") is None
assert secretario._buscar("de la") is None, "las palabras de relleno solas no bastan"
print("OK: los documentos se encuentran por su título, no solo por el nombre exacto del fichero")
