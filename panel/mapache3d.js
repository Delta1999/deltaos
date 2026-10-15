// Mapache 3D de puntos del salvapantallas: el mismo modelo que mascota.py (modelo(), girar(), pata(), brazo() portados
// tal cual), pero aquí se pasea por la pantalla, sigue al ratón y, si le pasas el ratón por encima 4 veces en 6 s,
// se pone juguetón un rato: brinca, da volteretas, agita las manos y saca la lengua.
const GRIS = {'#': 26, '+': 138, 'o': 242}, EJE = 15, GIRO_LADO = 20, ANDAR = 70, VGIRO = 240, ZANCADA = 2, ALZA = 2;
const OJOS = new Set(['12,9', '12,10', '13,9', '13,10', '12,19', '12,20', '13,19', '13,20']);  // fila,columna
const FORMAS = {cabeza: [[14.5, 13, 0], [15, 10, 9]], cuerpo: [[14.5, 30.5, 0], [11.5, 8.5, 8]], cola: [[33, 30, -9], [7, 8, 4]],
  pata_i: [[9.5, 40.5, 0], [3.5, 2.5, 3]], pata_d: [[21, 40.5, 0], [3.5, 2.5, 3]]};
const ESPALDA = {cabeza: '+', cuerpo: '+', pata_i: '#', pata_d: '#', cola: null};
const LATERAL = ['cabeza', 'cuerpo', 'cola'], MOVIL = new Set(['cola', 'ojo', 'pata', 'oreja']);
const HOMBROS = [[7, 25, 4], [22, 25, 4]], PIVOTE_OREJA = [[5, 7.5], [24, 7.5]], PIVOTE_COLA = [33, 26];
const LENGUA = '214,96,104', ROJO = '255,45,31';
const PASES = 4, VENTANA_PASES = 6, JUEGA = 9, SIGUE = 8;  // pases del ratón para jugar, en cuántos s; s jugando; s siguiéndolo
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);

let MAP = null, MODELO = [], REPOSO = [], PALMAS = [];
fetch('/mapache.txt').then(r => r.text()).then(t => { MAP = t.trimEnd().split('\n'); construir(); });

function parte(f, c) {
  if (OJOS.has(f + ',' + c)) return 'ojo';
  if (f >= 23 && c >= 27) return 'cola';
  if (f >= 39) return 'pata';
  if (f <= 7 && (c <= 9 || c >= 20)) return 'oreja';
  if (f >= 18 && f <= 21) return 'hocico';
  return f >= 23 ? 'barriga' : 'cuerpo';
}
const forma = (f, c, pt) => pt === 'cola' || pt === 'oreja' ? pt : pt === 'pata' ? (c < EJE ? 'pata_i' : 'pata_d') : f <= 22 ? 'cabeza' : 'cuerpo';

function superficie(fo, c, f, lado = 1) {
  const [[cx, cy, cz], [rx, ry, rz]] = FORMAS[fo], u = (c - cx) / rx, v = (f - cy) / ry;
  const h = Math.sqrt(Math.max(.04, 1 - u * u - v * v)), nx = u / rx, ny = v / ry, nz = lado * h / rz, m = Math.hypot(nx, ny, nz);
  const hocico = fo === 'cabeza' && lado > 0 ? 3.5 * Math.max(0, 1 - ((c - 14.5) / 5) ** 2 - ((f - 19) / 3) ** 2) : 0;
  return [cz + lado * rz * h + hocico, nx / m, nz / m, h];
}

function colorLado(fo, x, f) {
  const c = Math.round(x), ch = MAP[f][c] || '.';
  if (fo === 'cola') return ch !== '.' && forma(f, c, parte(f, c)) === fo ? ch : '+';
  return fo === 'cabeza' && ch === '#' && f >= 10 && f <= 15 ? '#' : '+';
}

// [x, y, z, nx, nz, ch, parte, forma, borde, malla], igual que modelo() de mascota.py
function construir() {
  const manos = [[8, 13], [17, 22]].map(([a, b]) => {
    const m = [];
    for (let f = 28; f < 32; f++) for (let c = a; c < b; c++) if (MAP[f][c] === '#') m.push([c, f]);
    return m;
  });
  const esMano = new Set(manos.flat().map(([c, f]) => c + ',' + f)), filas = {};
  MAP.forEach((fila, f) => [...fila].forEach((ch0, c) => {
    if (ch0 === '.') return;
    const ch = esMano.has(c + ',' + f) ? (c >= 10 && c <= 19 ? 'o' : '+') : ch0, pt = parte(f, c), fo = forma(f, c, pt);
    if (fo === 'oreja') {  // lámina fina: de perfil se ve de canto
      MODELO.push([c, f, 2.6, 0, 1, ch, pt, fo, false, 'frente'], [c, f, 1.4, 0, -1, '#', pt, fo, false, 'frente']);
      return;
    }
    (filas[fo] = filas[fo] || new Set()).add(f);
    for (const lado of [1, -1]) {
      const [z, nx, nz, h] = superficie(fo, c, f, lado), delante = lado > 0;
      MODELO.push([c, f, z, nx, nz, delante || !ESPALDA[fo] ? ch : ESPALDA[fo],
        delante || pt === 'cola' || pt === 'pata' ? pt : 'espalda', fo,
        delante && ch === '#' && h < .5 && (fo === 'cabeza' || fo === 'cuerpo'),
        Math.abs(nx) > Math.abs(nz) && LATERAL.includes(fo) ? 'canto' : 'frente']);
    }
  }));
  for (const fo of LATERAL) {  // rejilla de costado: rellena los flancos al girarse
    const [[cx, cy, cz], [rx, ry, rz]] = FORMAS[fo];
    for (const f of [...filas[fo]].sort((a, b) => a - b)) {
      const v = (f - cy) / ry;
      for (let k = -Math.trunc(rz); k <= Math.trunc(rz); k++) {
        const w = k / rz, r = 1 - w * w - v * v;
        if (r <= 0) continue;
        for (const lado of [-1, 1]) {
          const nx = lado * Math.sqrt(r) / rx, ny = v / ry, nz = w / rz, m = Math.hypot(nx, ny, nz);
          if (Math.abs(nx) <= Math.abs(nz)) continue;
          const x = cx + lado * rx * Math.sqrt(r);
          MODELO.push([x, f, cz + k, nx / m, nz / m, colorLado(fo, x - lado * 2, f), fo === 'cola' ? 'cola' : 'espalda', fo, false, 'lado']);
        }
      }
    }
  }
  const centros = manos.map(m => [m.reduce((s, p) => s + p[0], 0) / m.length, m.reduce((s, p) => s + p[1], 0) / m.length]);
  PALMAS = manos.map((m, i) => m.map(([c, f]) => [c - centros[i][0], f - centros[i][1]]));
  REPOSO = centros.map(([cx, cy]) => [cx, cy, superficie('cuerpo', cx, cy)[0] + .4]);
  M.manos = REPOSO.map(r => r.slice());
}

const mallaVisible = (malla, yaw) => malla === 'frente' || (malla === 'lado') === (Math.abs(yaw) >= GIRO_LADO);
const girar = (x, z, nx, nz, cs, sn) => [(x - EJE) * cs + z * sn + EJE, -(x - EJE) * sn + z * cs, -nx * sn + nz * cs];
const luz = nz => .55 + .45 * Math.max(nz, 0);
const colaX = yaw => -34 * Math.min(Math.max(yaw, 0), ANDAR) / ANDAR;
function tapado(X, y, cs, sn) {
  for (const fo of ['cabeza', 'cuerpo']) {
    const [[cx, cy, cz], [rx, ry, rz]] = FORMAS[fo], v = (y - cy) / ry;
    if (v * v < 1 && Math.abs(X - ((cx - EJE) * cs + cz * sn + EJE)) < Math.hypot(rx * cs, rz * sn) * Math.sqrt(1 - v * v) - .5) return true;
  }
  return false;
}
function sinAmontonar(ps) {  // de atrás adelante, sin los que caen casi encima de otro más cercano
  const vistos = new Set(), quedan = [];
  for (const q of ps.sort((a, b) => b[0] - a[0])) {
    const k = Math.round(q[1] / .8) + ',' + Math.round(q[2]);
    if (!vistos.has(k)) { vistos.add(k); quedan.push(q); }
  }
  return quedan.reverse();
}
function brazo(hombro, mano, i) {
  const [x, y, z] = mano, pts = PALMAS[i].map(([dc, df]) => [x + dc, y + df, z, 0, 0, '#']);
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  if (dist(mano, REPOSO[i]) < 2) return pts;
  const codo = hombro.map((a, j) => (a + mano[j]) / 2);
  codo[0] += (i ? 1 : -1) * Math.max(0, .35 * (dist(hombro, mano) - 6));
  for (const [a, b] of [[hombro, codo], [codo, mano]]) {
    const n = Math.max(1, Math.round(dist(a, b) / .8));
    for (let k = 0; k < n; k++) {
      const [px, py, pz] = [0, 1, 2].map(j => a[j] + (b[j] - a[j]) * k / n);
      pts.push([px - .8, py, pz - .2, 0, 0, '#'], [px, py, pz - .1, 0, 0, '+'], [px + .8, py, pz - .2, 0, 0, '#']);
    }
  }
  return pts;
}

// ---- comportamiento ----
const M = {px: null, alt: 0, vy: 0, vx: 0, vgiro: 0, yaw: 0, dir: 1, modo: 'quieto', paso: 0, ritmo: 0, meta: null, sig: 0, mira: 0,
  orejas: [[0, 0], [0, 0]], manos: null, tic: [0, 0], parp: 0, raton: null, tRaton: -1e9, pases: [], dentro: false, juega: 0,
  caja: null, ult: 0, ultPinta: 0};

export function raton(x, y, t) {
  M.raton = [x, y]; M.tRaton = t;
  const [x0, y0, x1, y1] = M.caja || [0, 0, -1, -1], dentro = x >= x0 && x <= x1 && y >= y0 && y <= y1;
  if (dentro && !M.dentro) {
    M.pases = M.pases.filter(p => t - p < VENTANA_PASES).concat(t);
    if (M.pases.length >= PASES) { M.juega = t + JUEGA; M.pases = []; M.sig = t; }
  }
  M.dentro = dentro;
}

function mover(t, dt, W, C) {
  const G = 440 * C, juega = t < M.juega, sigue = M.raton && t - M.tRaton < SIGUE;
  let girando = false;
  if (M.alt > 0) {  // en el aire
    M.vy += G * dt; M.alt = Math.max(0, M.alt - M.vy * dt); M.px += M.vx * dt;
    if (M.vgiro) { M.yaw += M.vgiro * dt; girando = true; }
    if (!M.alt) { M.vy = M.vx = 0; if (M.vgiro) { M.yaw = ((M.yaw % 360) + 540) % 360 - 180; M.vgiro = 0; } M.sig = t + .25 + Math.random() * .5; }
  } else if (juega && t > M.sig) {  // brinco, y a veces voltereta entera en el aire
    const h = (4 + Math.random() * 7) * C, aire = 2 * Math.sqrt(2 * h / G);
    M.dir = Math.random() < .5 ? -1 : 1; M.vy = -Math.sqrt(2 * G * h); M.alt = .01;
    M.vx = M.dir * (3 + Math.random() * 12) * C; M.vgiro = Math.random() < .45 ? M.dir * 360 / aire : 0;
    M.modo = 'cae';
  } else {
    let meta = null, vel = 14 * C;
    if (!juega && sigue && !M.dentro) {
      const dx = M.raton[0] - M.px;
      if (Math.abs(dx) > (M.modo === 'anda' ? C : 6 * C)) meta = M.raton[0];
      if (Math.abs(dx) > W / 3) vel *= 1.8;  // lejos: trota
    } else if (!juega && !sigue) {
      if (M.meta == null && t > M.sig) M.meta = (.1 + .8 * Math.random()) * W;
      meta = M.meta;
    }
    if (meta == null) M.modo = 'quieto';
    else {
      M.modo = 'anda'; M.dir = meta >= M.px ? 1 : -1;
      const d = Math.abs(meta - M.px);
      if (Math.abs(M.yaw - ANDAR * M.dir) < .5) {  // primero se da la vuelta
        const s = Math.min(d, vel * dt);
        M.px += M.dir * s; M.paso += s / (8 * C) * 2 * Math.PI;
      }
      if (d <= vel * dt) { M.modo = 'quieto'; M.meta = null; M.sig = t + 4 + Math.random() * 10; }
    }
  }
  if (!girando) {
    if (M.modo === 'quieto' && !sigue && Math.random() < dt / 7) M.mira = [-45, -20, 0, 0, 20, 45][Math.random() * 6 | 0];
    const obj = M.modo === 'anda' ? ANDAR * M.dir : M.modo === 'cae' ? M.yaw : juega || M.dentro ? 0
      : sigue ? clamp((M.raton[0] - M.px) / (W / 2) * 60, -50, 50) : M.mira;  // mira hacia el ratón
    M.yaw += clamp(obj - M.yaw, -VGIRO * dt, VGIRO * dt);
  }
  if (!M.alt && M.modo === 'cae') M.modo = 'quieto';
  M.ritmo += clamp((M.modo === 'anda' && Math.abs(M.yaw - ANDAR * M.dir) < .5) - M.ritmo, -6 * dt, 6 * dt);
  M.px = clamp(M.px, 18 * C, W - 24 * C);
}

function pata(f, c, z) {  // cada pata avanza alzada y vuelve apoyada, a contrapaso de la otra; en el aire se encoge
  const w = (f - 38) / 4, lado = c < EJE ? -1 : 1;
  if (M.modo === 'cae') return [c + lado * .8 * w, f + (M.vy > 0 ? .7 : -1) * w, z];
  const fase = M.paso + (lado < 0 ? 0 : Math.PI);
  return [c, f - ALZA * Math.max(Math.sin(fase), 0) * w * M.ritmo, z - ZANCADA * Math.cos(fase) * w * M.ritmo];
}

function gestos(t, dt, est, voz) {  // orejas y manos camino de su postura; devuelve brazos y boca
  const k = Math.min(1, dt * 9), juega = t < M.juega;
  const ore = juega ? null : M.dentro || est === 'escuchando' ? [-10, 1.2] : est === 'hablando' ? [3 + 10 * voz, .3 * voz] : [0, 0];
  if (ore && !ore[0] && Math.random() < dt / 4) M.tic = [t + .25, Math.random() * 2 | 0];
  const metas = [0, 1].map(i => ore ? [ore[0] + 18 * (t < M.tic[0] && M.tic[1] === i), ore[1]]
    : [18 + 22 * Math.sin(t * 16 + i * Math.PI), .5]);  // jugando: aletean
  M.orejas = M.orejas.map((o, i) => o.map((a, j) => a + (metas[i][j] - a) * k));
  let manos;
  if (juega) { const s = Math.sin(t * 10) * 1.5; manos = [[1.5, 21 + s, 6], [27.5, 21 - s, 6]]; }  // manos arriba, agitándolas
  else if (M.dentro) manos = [REPOSO[0], [27.5, 17 + Math.sin(t * 9) * 1.6, 6]];  // saluda
  else {
    const sw = 1.5 * Math.cos(M.paso) * M.ritmo;  // braceo al andar
    manos = [[REPOSO[0][0], REPOSO[0][1], REPOSO[0][2] + sw], [REPOSO[1][0], REPOSO[1][1], REPOSO[1][2] - sw]];
  }
  M.manos = M.manos.map((m, i) => m.map((a, j) => a + (manos[i][j] - a) * k));
  const pts = [0, 1].flatMap(i => brazo(HOMBROS[i], M.manos[i], i).map(q => [...q, GRIS[q[5]], null]));
  const n = juega ? 2 : est === 'hablando' ? Math.round(Math.min(voz, 1) * 2) : 0;
  const boca = n ? [...Array(3 + 2 * (n > 1)).keys()].map(i => [14 - (n > 1) + i, 20, '#'])
      .concat(n > 1 ? [[14, 21, '#'], [15, 21, LENGUA], [16, 21, '#']] : [])
    : M.dentro || M.ritmo > .3 ? [[14, 20, '#'], [15, 20, LENGUA], [16, 20, '#']] : [];  // contento
  for (const [c, f, q] of boca) {
    const [z, nx, nz] = superficie('cabeza', c, f), ch = q.length === 1 ? q : 'o';
    pts.push([c, f, z + .2, nx, nz, ch, GRIS[ch], ch === q ? null : q]);
  }
  return pts;
}

export function pintar(t, cv) {
  if (!MAP || t - M.ultPinta < 1 / 30) return;  // 30 fps bastan
  M.ultPinta = t;
  const k = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  if (cv.width !== Math.round(W * k) || cv.height !== Math.round(H * k)) { cv.width = Math.round(W * k); cv.height = Math.round(H * k); }
  const C = Math.min(W, H) * .3 / 43, R = C * .42, suelo = H - 4 * C;
  if (M.px == null) M.px = W / 2;
  const dt = Math.min(t - M.ult, .1); M.ult = t;
  mover(t, dt, W, C);
  const S0 = typeof S !== 'undefined' ? S : {}, est = S0.estado || 'dormido', voz = typeof NV !== 'undefined' ? NV : 0;
  const juega = t < M.juega;
  if (t > M.parp + .15 && Math.random() < .012) M.parp = t;
  const cerrados = t - M.parp < .15, resp = Math.sin(t * 2 * Math.PI / 3.5);
  const cola = (juega ? 26 : M.modo === 'anda' ? 12 : est === 'hablando' ? 8 + 16 * voz : 7) * Math.PI / 180 *
    Math.sin(t * (juega ? 14 : M.modo === 'anda' ? 6 : est === 'hablando' ? 9 : 3));
  const yaw = Math.round(M.yaw / 5) * 5, cs = Math.cos(yaw * Math.PI / 180), sn = Math.sin(yaw * Math.PI / 180);
  const bote = -Math.abs(Math.sin(M.paso)) * .6 * C * M.ritmo;
  const ox = M.px - EJE * C, oy = suelo - 42 * C - M.alt + bote + resp * .24 * C;
  M.caja = [M.px - 17 * C, oy, M.px + 22 * C, oy + 43 * C];
  const brillo = Math.round(8 * (est === 'hablando' ? .75 + .25 * voz : .9 + .1 * resp)), vista = [];
  for (const [x0, y0, z0, nx0, nz0, ch0, pt, , borde, malla] of MODELO) {  // cuerpo
    if (MOVIL.has(pt) || !mallaVisible(malla, yaw)) continue;
    const [X, Z, NZ] = girar(x0, z0, nx0, nz0, cs, sn);
    if (NZ < -.1) continue;
    const ch = borde && NZ > .45 ? '+' : ch0, g = ch === 'o' && (pt === 'hocico' || pt === 'barriga') ? GRIS[ch] * brillo / 8 : GRIS[ch];
    vista.push([Z, X, y0, ch, null, Math.round(g * luz(NZ))]);
  }
  const [pcf, pcc] = PIVOTE_COLA, cx = colaX(yaw), pts = gestos(t, dt, est, voz);
  for (let [x, y, z, nx, nz, ch, pt, , , malla] of MODELO) {  // lo que se mueve
    if (!MOVIL.has(pt) || !mallaVisible(malla, yaw)) continue;
    let g = GRIS[ch], col = null;
    if (pt === 'pata') [x, y, z] = pata(y, x, z);
    else if (pt === 'cola') {
      const dx = x - pcc, dy = y - pcf;
      [x, y] = [pcc + cx + dx * Math.cos(cola) - dy * Math.sin(cola), pcf + dx * Math.sin(cola) + dy * Math.cos(cola)];
    } else if (pt === 'oreja') {  // gira sobre su base y se alza
      const i = +(x >= EJE), [bx, by] = PIVOTE_OREJA[i], [a0, alza] = M.orejas[i], a = (i ? a0 : -a0) * Math.PI / 180, dx = x - bx, dy = y - by;
      [x, y, nx, nz] = [bx + dx * Math.cos(a) - dy * Math.sin(a), by + dx * Math.sin(a) + dy * Math.cos(a) - alza, 0, 0];
    } else if (cerrados) g = 26;
    else if (est === 'escuchando') col = ROJO;
    pts.push([x, y, z, nx, nz, ch, g, col]);
  }
  for (const [x, y, z, nx, nz, ch, g, col] of pts) {
    const [X, Z, NZ] = girar(x, z, nx, nz, cs, sn);
    if (NZ < -.1 || (Z < 0 && tapado(X, y, cs, sn))) continue;
    vista.push([Z, X, y, ch, col, Math.round(g * (nx || nz ? luz(NZ) : .9))]);
  }
  const g2 = cv.getContext('2d');
  g2.setTransform(k, 0, 0, k, 0, 0); g2.clearRect(0, 0, W, H);
  if (M.alt) {  // sombra en el suelo mientras brinca
    g2.fillStyle = `rgba(255,255,255,${.12 * Math.max(0, 1 - M.alt / (12 * C))})`;
    g2.beginPath(); g2.ellipse(M.px, suelo + 1.5 * C, 9 * C, 1.4 * C, 0, 0, 7); g2.fill();
  }
  for (const [, X, y, ch, col, g] of sinAmontonar(vista)) {
    const px = ox + X * C, py = oy + y * C;
    if (!col && ch === '#' && g < 60) {  // aro: si no, lo oscuro se pierde en el negro
      g2.fillStyle = 'rgb(78,78,78)'; g2.beginPath(); g2.arc(px, py, R, 0, 7); g2.fill();
    }
    g2.fillStyle = `rgb(${col || g + ',' + g + ',' + g})`;
    g2.beginPath(); g2.arc(px, py, !col && ch === '#' && g < 60 ? R * .72 : R, 0, 7); g2.fill();
  }
}
