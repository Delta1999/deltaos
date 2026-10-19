"""Compone el PDF anotado: página ensanchada con margen, subrayados reales (editables en Okular),
notas manuscritas en el margen, reglas mnemotécnicas, esquemas dibujados a mano y resumen de la clase."""
import html
import json
import random
import re
import subprocess
import tempfile
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf

AQUI = Path(__file__).parent / "estudio"
FUENTES = AQUI / "fuentes"
MARGEN = 215  # pt añadidos a la derecha de cada página

# subrayado (relleno) y tinta (texto de la nota) por tipo
FONDO = {"estudio": (1, .93, .3), "pregunta_fija": (1, .5, .5), "ojo": (1, .62, .86), "dato": (1, .78, .38),
         "explicacion": (.62, .84, 1), "anadido": (.55, .74, 1), "mnemo": (.58, .93, .58)}
TINTA = {"pregunta_fija": (.78, .08, .1), "ojo": (.72, .08, .42), "dato": (.08, .2, .58),
         "explicacion": (.08, .2, .58), "anadido": (.02, .36, .72), "mnemo": (.04, .45, .18)}
ETIQUETA = {"pregunta_fija": "* PREGUNTA FIJA *", "ojo": "¡OJO!", "anadido": "+ DICHO EN CLASE"}
SIN_GLIFO = {"→": "->", "←": "<-", "↔": "<->", "⇒": "=>", "★": "*", "✓": "ok", "✗": "x", "≠": "=/="}

_mano = pymupdf.Font(fontfile=str(FUENTES / "Caveat.ttf"))
_rotulo = pymupdf.Font(fontfile=str(FUENTES / "Kalam-Bold.ttf"))


def _limpia(t):
    for a, b in SIN_GLIFO.items():
        t = t.replace(a, b)
    return t.strip()


# ── Buscar el fragmento en la página (tolerante a guiones, saltos y tildes) ──

def _norm(w):
    w = unicodedata.normalize("NFKD", w.lower())
    return re.sub(r"[^a-z0-9ñ]", "", "".join(c for c in w if not unicodedata.combining(c)))


def buscar(palabras, frag):
    """palabras = page.get_text('words'). Devuelve los rectángulos (uno por línea) del fragmento o []."""
    toks = []  # «re- comendación» copiado del PDF también va junto
    for x in frag.split():
        if toks and toks[-1].endswith("-"):
            toks[-1] += x
        else:
            toks.append(x)
    toks = [t for t in map(_norm, toks) if t]
    seq, idx = [], []  # palabra normalizada y sus índices; «Euro-» + «peo» se juntan en una
    for i, w in enumerate(palabras):
        t = _norm(w[4])
        if not t:
            continue
        if idx and palabras[idx[-1][-1]][4].endswith("-"):
            seq[-1] += t
            idx[-1].append(i)
        else:
            seq.append(t)
            idx.append([i])
    if not toks or not seq:
        return []
    m = SequenceMatcher(None, seq, toks, autojunk=False)
    b = max(m.get_matching_blocks(), key=lambda x: x.size)
    if b.size < max(2, round(len(toks) * .6)) and not (len(toks) == 1 and b.size == 1):
        return []
    ini = max(b.a - b.b, 0)  # el fragmento entero alrededor del trozo que casa
    lineas = {}
    for i in (j for grupo in idx[ini:ini + len(toks)] for j in grupo):
        x0, y0, x1, y1, _, bl, ln, _ = palabras[i]
        lineas.setdefault((bl, ln), pymupdf.Rect(x0, y0, x1, y1)).include_rect(pymupdf.Rect(x0, y0, x1, y1))
    return list(lineas.values())


def situar(W, p, frags):
    """Página (0-based) donde casan más fragmentos: la que dice el modelo, las vecinas y por último todo el tema.
    El modelo se equivoca a menudo de página (cuenta la impresa, o la de otro lote)."""
    cerca = sorted(range(len(W)), key=lambda i: (abs(i - p), i))
    for paginas in (cerca[:1], cerca[1:41], cerca[41:]):
        cuenta = {i: sum(bool(buscar(W[i], f)) for f in frags) for i in paginas}
        mejor = max(cuenta, key=cuenta.get, default=None)
        if mejor is not None and cuenta[mejor]:
            return mejor
    return None


def subrayar(page, rects, tipo, info=""):
    a = page.add_highlight_annot(quads=[r.quad for r in rects])
    a.set_colors(stroke=FONDO[tipo])
    a.set_info(content=info, title="Delta")  # firma: lo que no lleve «Delta» lo anotó el usuario (ver tocado_a_mano)
    a.update()


# ── Notas del margen ─────────────────────────────────────────────────────────

def _envolver(texto, font, size, ancho):
    lineas, cur = [], ""
    for w in texto.split():
        prueba = f"{cur} {w}".strip()
        if font.text_length(prueba, size) <= ancho or not cur:
            cur = prueba
        else:
            lineas.append(cur)
            cur = w
    return lineas + ([cur] if cur else [])


def _bloque(nota, size, ancho):
    """Líneas (font, size, texto, color) de una nota y su alto."""
    out = []
    if nota.get("etiqueta"):
        out.append((_rotulo, size * .62, nota["etiqueta"], nota["tinta"]))
    out += [(_mano, size, l, nota["tinta"]) for l in _envolver(nota["texto"], _mano, size, ancho)]
    if nota.get("cita"):
        out += [(_mano, size * .86, l, (.45, .1, .12)) for l in _envolver(nota["cita"], _mano, size * .86, ancho)]
    return out, sum(s * 1.08 for _, s, _, _ in out) + (8 if nota.get("caja") else 0)


def _colocar(notas, alto, size, ancho):
    """Ordena por altura del ancla y empuja hacia abajo (y hacia arriba al final) para que no se pisen."""
    blq = [(_bloque(n, size, ancho)) for n in notas]
    ys, cur = [], 22
    for n, (_, h) in zip(notas, blq):
        y = max(n["y"] - 4, cur)
        ys.append(y)
        cur = y + h + 9
    tope = alto - 26
    for i in range(len(ys) - 1, -1, -1):
        ys[i] = min(ys[i], tope - blq[i][1])
        tope = ys[i] - 9
    return ys, blq, ys and ys[0] >= 14


def _trazo_mano(page, rect, color, semilla):
    """Recuadro a mano: dos pasadas con temblor."""
    rnd = random.Random(semilla)
    for _ in range(2):
        j = lambda: rnd.uniform(-1.6, 1.6)
        pts = [(rect.x0 + j(), rect.y0 + j()), (rect.x1 + j(), rect.y0 + j()), (rect.x1 + j(), rect.y1 + j()),
               (rect.x0 + j(), rect.y1 + j()), (rect.x0 + j(), rect.y0 + j())]
        page.draw_polyline(pts, color=color, width=.9, stroke_opacity=.85)


def margen(page, notas, ancho_orig):
    if not notas:
        return
    notas.sort(key=lambda n: n["y"])
    x0, ancho = ancho_orig + 16, MARGEN - 30
    for size in (14, 12.5, 11, 9.5, 8.5):
        ys, blq, cabe = _colocar(notas, page.rect.height, size, ancho - 10)
        if cabe:
            break
    for n, y, (lineas, h) in zip(notas, ys, blq):
        if n.get("caja"):
            _trazo_mano(page, pymupdf.Rect(x0 - 5, y - 3, x0 + ancho - 2, y + h - 3), n["tinta"], int(y))
            y += 3
        # línea guía desde el borde de la página original hasta la nota
        ya = n["y"] + 4
        p = page.new_shape()
        p.draw_bezier((ancho_orig - 6, ya), (ancho_orig + 6, ya), (x0 - 12, y + 6), (x0 - 4, y + 6))
        p.draw_circle((ancho_orig - 6, ya), 1.6)
        p.finish(color=n["tinta"], fill=None, width=.6, stroke_opacity=.7)
        p.commit()
        yy = y
        for font, s, txt, color in lineas:
            yy += s
            page.insert_text((x0, yy - s * .18), txt, fontsize=s, fontname="mano" if font is _mano else "rotulo",
                             fontfile=str(FUENTES / ("Caveat.ttf" if font is _mano else "Kalam-Bold.ttf")), color=color)
            yy += s * .08


# ── Esquemas y resumen: HTML a mano (rough.js) → PDF con Chromium ─────────────

PLANTILLA = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{font-family:Kalam;src:url('fuentes/Kalam-Regular.ttf')}@font-face{font-family:KalamB;src:url('fuentes/Kalam-Bold.ttf')}
@font-face{font-family:Caveat;src:url('fuentes/Caveat.ttf')}
@page{size:__W__pt __H__pt;margin:0}*{box-sizing:border-box}html,body{margin:0}
.hoja{width:__W__pt;height:__H__pt;position:relative;overflow:hidden;page-break-after:always;padding:46pt 40pt 36pt 64pt;
 background:#fffdf6 linear-gradient(#d6e4f5 1px,transparent 1px) 0 0/100% 18pt;font-family:Kalam,cursive;color:#1b2a5c}
.hoja:before{content:"";position:absolute;left:46pt;top:0;bottom:0;border-left:1.5px solid #e9a0a0}
h1{font-family:KalamB;font-size:26pt;margin:0 0 6pt;display:inline-block;position:relative}
h1 span{position:relative;z-index:1}.sub{font-family:Caveat;font-size:17pt;color:#555;margin:0 0 10pt}
.lienzo{position:absolute;left:64pt;right:30pt;top:105pt;bottom:70pt}.arbol{position:absolute;left:0;top:0;transform-origin:0 0}
.arbol.v>.r{flex-direction:column}.arbol.v>.r>.hijos{flex-direction:row;align-items:flex-start;margin:34pt 0 0;gap:22pt}
.arbol.v>.r>.hijos>.r{flex-direction:column;align-items:flex-start}.arbol.v>.r>.hijos>.r>.hijos{margin:10pt 0 0 26pt}
.r{display:flex;align-items:center}.hijos{display:flex;flex-direction:column;gap:7pt;margin-left:38pt}
.n{padding:4pt 9pt;font-size:13pt;line-height:1.15;max-width:200pt;position:relative;z-index:1}
.t-titulo{font-family:KalamB;font-size:18pt;max-width:150pt}.t-rama{font-family:KalamB}.t-dato{font-size:12.5pt}
.t-ojo{font-size:12.5pt;color:#c0142a}.t-ojo:before{content:"¡ojo! ";font-family:KalamB}
svg.capa{position:absolute;left:0;top:0;overflow:visible;z-index:0}
.pie{position:absolute;left:64pt;right:40pt;bottom:22pt;font-family:Caveat;font-size:21pt;line-height:1.1;color:#7a1020}
.texto{font-size:13.5pt;line-height:1.35}.texto h2{font-family:KalamB;font-size:17pt;margin:12pt 0 4pt}
.texto li{margin:2pt 0}.pag{font-family:Caveat;color:#888;font-size:13pt}
.caja{border:2px solid #2e8b57;border-radius:10pt 4pt 12pt 5pt;padding:4pt 9pt;margin:5pt 0;transform:rotate(-.4deg)}
.caja b{font-family:KalamB;color:#2e7d4f}
</style><script src="rough.js"></script></head><body>__CUERPO__<script>
const PLUMAS=['#1d4fa3','#c0392b','#1e8449','#7d3c98','#d35400','#0e6e7d'];
document.fonts.ready.then(()=>{document.querySelectorAll('.lienzo').forEach(lz=>{
 const a=lz.querySelector('.arbol'),esc=()=>Math.min(1.9,lz.clientWidth/a.scrollWidth,lz.clientHeight/a.scrollHeight);
 // árbol ancho y bajo = media hoja vacía: probar raíz arriba con las ramas en columnas y quedarse con lo que salga más grande
 const kh=esc();a.classList.add('v');if(esc()<=kh)a.classList.remove('v');const k=esc();
 const raiz=a.querySelector(':scope>.r');
 a.style.transform=`scale(${k})`;a.style.top=Math.max(0,(lz.clientHeight-a.scrollHeight*k)/2)+'px';const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.classList.add('capa');
 svg.setAttribute('width',a.scrollWidth);svg.setAttribute('height',a.scrollHeight);a.prepend(svg);const rc=rough.svg(svg);
 const R=e=>{const b=e.getBoundingClientRect(),o=a.getBoundingClientRect();return{x:(b.left-o.left)/k,y:(b.top-o.top)/k,w:b.width/k,h:b.height/k}};
 a.querySelectorAll('.n').forEach(n=>{const r=R(n),c=n.dataset.pluma,t=n.dataset.tipo;n.style.color=t==='ojo'?'#c0142a':c;
  if(t==='titulo')svg.append(rc.rectangle(r.x,r.y,r.w,r.h,{stroke:c,strokeWidth:2.2,fill:'#ffe066',fillStyle:'hachure',hachureGap:5,roughness:1.6}));
  else if(t==='rama')svg.append(rc.rectangle(r.x,r.y,r.w,r.h,{stroke:c,strokeWidth:1.4,roughness:1.3}));
  else if(t==='ojo')svg.append(rc.ellipse(r.x+r.w/2,r.y+r.h/2,r.w+16,r.h+12,{stroke:'#c0142a',strokeWidth:1.3,roughness:1.8}));
  else svg.append(rc.line(r.x+6,r.y+r.h-3,r.x+r.w-6,r.y+r.h-3,{stroke:'#f4d03f',strokeWidth:7,roughness:1.2}));
  const p=n.parentElement.parentElement.closest('.r');if(!p)return;const q=R(p.querySelector(':scope>.n'));
  const v=a.classList.contains('v');
  if(v&&p===raiz){const x1=q.x+q.w/2,y1=q.y+q.h+2,x2=r.x+r.w/2,y2=r.y-3,m=(y1+y2)/2;  // raíz → columna
   svg.append(rc.path(`M${x1} ${y1} C${x1} ${m},${x2} ${m},${x2} ${y2}`,{stroke:c,strokeWidth:1.2,roughness:.9}));
   svg.append(rc.linearPath([[x2-4,y2-6],[x2,y2],[x2+4,y2-6]],{stroke:c,strokeWidth:1.2}));return}
  if(v&&p.parentElement.parentElement===raiz){const x1=q.x+12,y1=q.y+q.h+2,x2=r.x-3,y2=r.y+r.h/2;  // rama → hijos debajo
   svg.append(rc.linearPath([[x1,y1],[x1,y2],[x2,y2]],{stroke:c,strokeWidth:1.2,roughness:.8}));
   svg.append(rc.linearPath([[x2-6,y2-4],[x2,y2],[x2-6,y2+4]],{stroke:c,strokeWidth:1.2}));return}
  const x1=q.x+q.w+2,y1=q.y+q.h/2,x2=r.x-3,y2=r.y+r.h/2,m=(x1+x2)/2;
  svg.append(rc.path(`M${x1} ${y1} C${m} ${y1},${m} ${y2},${x2} ${y2}`,{stroke:c,strokeWidth:1.2,roughness:.9}));
  svg.append(rc.linearPath([[x2-6,y2-4],[x2,y2],[x2-6,y2+4]],{stroke:c,strokeWidth:1.2}))});});
 document.querySelectorAll('h1').forEach(h=>{const s=document.createElementNS('http://www.w3.org/2000/svg','svg');
  s.setAttribute('style','position:absolute;left:-6pt;top:0;overflow:visible');s.setAttribute('width',h.offsetWidth+12);s.setAttribute('height',h.offsetHeight);
  s.append(rough.svg(s).rectangle(0,h.offsetHeight*.45,h.offsetWidth+12,h.offsetHeight*.45,{fill:'#ffe066',fillStyle:'solid',stroke:'none',roughness:2}));h.prepend(s)});
 document.title='ok';});
</script></body></html>"""


def _arbol(nodos):
    hijos = {}
    for n in nodos:
        hijos.setdefault(n.get("padre") or "", []).append(n)
    raices = hijos.get("", []) or nodos[:1]
    plumas = ["#1d4fa3", "#c0392b", "#1e8449", "#7d3c98", "#d35400", "#0e6e7d"]

    def rama(n, pluma, nivel, vistos):
        if n["id"] in vistos:
            return ""
        vistos.add(n["id"])
        sub = "".join(rama(h, plumas[i % len(plumas)] if nivel == 0 else pluma, nivel + 1, vistos)
                      for i, h in enumerate(hijos.get(n["id"], [])))
        return (f'<div class="r"><div class="n t-{n["tipo"]}" data-tipo="{n["tipo"]}" data-pluma="{pluma}">'
                f'{html.escape(re.sub(r"^(\W*ojo\b\W*)+", "", n["texto"], flags=re.I) if n["tipo"] == "ojo" else n["texto"])}</div>' + (f'<div class="hijos">{sub}</div>' if sub else "") + "</div>")
    return "".join(rama(r, "#1b2a5c", 0, set()) for r in raices)


def _chromium(cuerpo, ancho, alto, destino):
    with tempfile.TemporaryDirectory() as tmp:
        f = AQUI / f".tmp_{destino.stem}.html"  # junto a fuentes/ y rough.js
        f.write_text(PLANTILLA.replace("__W__", str(ancho)).replace("__H__", str(alto)).replace("__CUERPO__", cuerpo))
        try:
            subprocess.run(["chromium-browser", "--headless=new", f"--user-data-dir={tmp}", "--no-pdf-header-footer",
                            "--virtual-time-budget=8000", "--allow-file-access-from-files",
                            f"--print-to-pdf={destino}", f.as_uri()], capture_output=True, timeout=120, check=True)
        finally:
            f.unlink(missing_ok=True)
    return pymupdf.open(destino)


def esquema_pdf(e, ancho, alto, destino):
    cuerpo = (f'<div class="hoja"><h1><span>{html.escape(e["titulo"])}</span></h1>'
              f'<div class="lienzo"><div class="arbol">{_arbol(e["nodos"])}</div></div>'
              f'<div class="pie">{html.escape(e.get("pie", ""))}</div></div>')
    return _chromium(cuerpo, ancho, alto, destino)


def _min(n):
    return n.get("minuto", "").strip("[] ")


def resumen_pdf(an, sueltas, ancho, alto, destino):
    esc = html.escape
    fijas = [n for n in an["notas"] if n["tipo"] == "pregunta_fija"]
    anad = [n for n in an["notas"] if n["tipo"] == "anadido"]
    li = lambda n: f'<li>{esc(n["nota"])} <span class="pag">pág. {n["pagina"]} · {esc(_min(n))}</span></li>'
    mn = "".join(f'<div class="caja"><b>{esc(m["regla"])}</b> — {esc(m["significa"])} <span class="pag">'
                 f'{"truco del profe" if m["origen"] == "profesor" else "regla sugerida"} · pág. {m["pagina"]}</span></div>'
                 for m in an["mnemotecnias"])
    cuerpo = (f'<div class="hoja" style="height:auto;min-height:{alto}pt"><h1><span>Clase de {esc(an.get("profesor") or "la academia")}</span></h1>'
              f'<p class="sub">Lo que hay que saberse de esta clase</p><div class="texto">{"".join(f"<p>{esc(x)}</p>" for x in (an["resumen"] if isinstance(an["resumen"], list) else [an["resumen"]]))}'
              f'<h2>Preguntas fijas ({len(fijas)})</h2><ul>{"".join(map(li, fijas))}</ul>'
              f'<h2>Reglas para memorizar</h2>{mn}'
              + (f'<h2>Dicho en clase y no está en el tema</h2><ul>{"".join(map(li, anad))}</ul>' if anad else "")
              + (f'<h2>Más notas del profe</h2><ul>{"".join(map(li, sueltas))}</ul>' if sueltas else "")
              + "</div></div>")
    return _chromium(cuerpo, ancho, alto, destino)


def tocado_a_mano(pdf):
    """¿Tiene anotaciones que no puso Delta (hechas en Okular)? Entonces no se puede pisar sin guardar copia."""
    with pymupdf.open(pdf) as d:
        return any(a.info.get("title") != "Delta" for pg in d for a in pg.annots())


# ── Composición ──────────────────────────────────────────────────────────────

def componer(tema_pdf, an, sub, destino, trabajo):
    src = pymupdf.open(tema_pdf)
    W, H = src[0].rect.width, src[0].rect.height
    out = pymupdf.open()
    W_src = [pg.get_text("words") for pg in src]
    por_pag = {}

    def poner(clave, item, pagina, frags):
        q = situar(W_src, pagina - 1, frags) if frags else None
        d = por_pag.setdefault(pagina - 1 if q is None else q, {"notas": [], "mnemo": [], "sub": []})
        if item not in d[clave]:  # los lotes del subrayado a veces repiten fragmentos
            d[clave].append(item)

    for n in an["notas"]:
        poner("notas", n, n["pagina"], n["subrayar"])
    for m in an["mnemotecnias"]:
        poner("mnemo", m, m["pagina"], [m["subrayar"]])
    for s in sub:
        for f in s["fragmentos"]:
            poner("sub", f, s["pagina"], [f])
    esquemas = {}
    for i, e in enumerate(an["esquemas"]):
        esquemas.setdefault(e["despues_de_pagina"] - 1, []).append((i, e))

    tot = {"frag": 0, "ok": 0, "notas": 0, "sueltas": []}
    toc, mapa = [], {}
    for p in range(len(src)):
        pg = out.new_page(width=W + MARGEN, height=H)
        pg.show_pdf_page(pymupdf.Rect(0, 0, W, H), src, p)
        mapa[p] = len(out)
        d = por_pag.get(p)
        if d:
            palabras = W_src[p]
            for f in d["sub"]:
                tot["frag"] += 1
                if r := buscar(palabras, f):
                    tot["ok"] += 1
                    subrayar(pg, r, "estudio")
            notas = []
            r_mnemo = [buscar(palabras, m["subrayar"]) for m in d["mnemo"]]
            pisado = [x for r in r_mnemo for x in r]
            for n in d["notas"]:
                rects = []
                for f in n["subrayar"]:
                    tot["frag"] += 1
                    if r := buscar(palabras, f):
                        tot["ok"] += 1
                        rects += r
                        subrayar(pg, r, n["tipo"], f'{n.get("profe") or "Profe"} ({_min(n)}): {n["cita"]}')
                if not rects:
                    tot["sueltas"].append(n)
                    continue
                tot["notas"] += 1
                if n["tipo"] in ("dato", "explicacion") and any(r.intersects(x) for r in rects for x in pisado):
                    continue  # el recuadro de la mnemotecnia ya lo dice: la nota de margen sería el mismo truco dos veces
                cita = f'{n.get("profe") or "Profe"} ({_min(n)}): «{n["cita"][:110]}»' if n["tipo"] in ("pregunta_fija", "ojo") and n["cita"] else ""
                notas.append({"y": min(r.y0 for r in rects), "texto": _limpia(n["nota"]), "tinta": TINTA[n["tipo"]],
                              "etiqueta": ETIQUETA.get(n["tipo"]), "cita": _limpia(cita)})
            for m, r in zip(d["mnemo"], r_mnemo):
                tot["frag"] += 1
                if r:
                    tot["ok"] += 1
                    subrayar(pg, r, "mnemo", m["significa"])
                notas.append({"y": min((x.y0 for x in r), default=H * .7), "caja": True, "tinta": TINTA["mnemo"],
                              "etiqueta": "TRUCO DEL PROFE" if m["origen"] == "profesor" else "PARA ACORDARME",
                              "texto": _limpia(f'{m["regla"]} = {m["significa"]}')})
            margen(pg, notas, W)
        for i, e in esquemas.get(p, []):
            tmp = trabajo / f"esquema{i:02d}.pdf"
            out.insert_pdf(esquema_pdf(e, W + MARGEN, H, tmp))
            toc.append([1, f'Esquema: {e["titulo"]}', len(out)])
    res = resumen_pdf(an, [n for n in tot["sueltas"] if n["tipo"] != "anadido"], W + MARGEN, H, trabajo / "resumen.pdf")
    out.insert_pdf(res, start_at=1)
    n_res = len(res)
    toc = [[1, "Resumen de la clase", 2]] + [[l, t, pg + (n_res if pg > 1 else 0)] for l, t, pg in toc]
    toc += [[l, t, mapa.get(pg - 1, 0) + (n_res if mapa.get(pg - 1, 0) > 1 else 0)] for l, t, pg in src.get_toc()]
    out.set_toc(sorted(toc, key=lambda x: x[2]))
    out.save(destino, garbage=3, deflate=True)
    cob = tot["ok"] / max(tot["frag"], 1)
    return (f"PDF: {len(out)} págs ({len(an['esquemas'])} esquemas, resumen de {n_res}); subrayados anclados "
            f"{tot['ok']}/{tot['frag']} ({cob:.0%}); notas en margen {tot['notas']}, al resumen {len(tot['sueltas'])}")


if __name__ == "__main__":  # prueba rápida de buscar()
    p = [(0, 0, 10, 10, "El", 0, 0, 0), (11, 0, 30, 10, "Tribunal", 0, 0, 1), (31, 0, 50, 10, "Euro-", 0, 0, 2),
         (0, 12, 20, 22, "peo", 0, 1, 0), (21, 12, 40, 22, "tiene", 0, 1, 1), (41, 12, 60, 22, "sede", 0, 1, 2)]
    r = buscar(p, "Tribunal Europeo tiene sede")
    assert len(r) == 2 and (r[0].x0, r[0].x1, r[1].x1) == (11, 50, 60), r
    assert buscar(p, "nada que ver aquí") == []
    print("ok", json.dumps([tuple(x) for x in r]))
