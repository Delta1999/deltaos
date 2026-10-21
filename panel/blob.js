// Escena «blob» del salvapantallas: una gota blanca de barniz que respira y se deforma con la voz.
//
// Es la réplica del orbe que trajo el usuario (el «Magical Blob» de 14islands, 2026-10-21): una
// esfera de muchísimos triángulos a la que el shader de vértices le suma ruido de Perlin a lo largo
// de la normal; las normales se recalculan a mano con dos vecinos, que si no la luz se ve plana y
// deja de parecer plastilina. El material es un MeshPhysicalMaterial con barniz (clearcoat) sobre un
// entorno de degradado que se genera aquí mismo con un canvas: no hace falta ningún PNG.
//
// Lo que la hace de Delta, y no una demo:
//   · Delta habla   → la gota se deforma con SU nivel de voz y gira más deprisa.
//   · Delta escucha → se deforma con lo que entra por el micro, más suave (se ve que el micro vive).
//   · en reposo      → solo respira.
//
// Debajo NO va el rótulo «Delta.OS» ni la telemetría del orbe 1 (lo pidió el usuario el 2026-10-21:
// dos salvapantallas con el mismo pie son el mismo salvapantallas con otra piel). Van la hora, fina y
// muy espaciada como una inscripción, y la conversación en curso en burbujas. Las burbujas son HTML
// y no lienzo: así heredan las del panel y tienen scroll de verdad.
import * as THREE from '/three.module.js';

const SEG = 192;        // segmentos de la esfera: con menos se ve el polígono en la silueta
const ENTRA = 1.4;      // segundos que tarda en salir (crece y se deforma desde una bola lisa)

let r3 = null, t0 = 0, NV = 0, MV = 0, V = 0, giro = 0, fase = 0, ult = 0;
export const entrar = () => { t0 = performance.now() / 1000; giro = 0; fase = 0; ult = 0; NV = MV = V = 0; E = 0; };

// El ratón la empuja (pedido el 2026-10-21): donde apunta se le hace un hoyo, como si la gota se
// apartase del dedo, y todo el cuerpo se retira un poco. Viene en píxeles del lienzo; null = fuera.
let rx = null, ry = 0, E = 0;
const dirR = new THREE.Vector3(0, 0, 1);
export const raton = (x, y) => { rx = x; ry = y; };

const suave = v => v < 0 ? 0 : v > 1 ? 1 : v * v * (3 - 2 * v);

// ---- el ruido de Perlin periódico (Stefan Gustavson, dominio público) y la función de deformación.
// Va con prefijo d_ para no chocar con nada que traiga three.js en sus propios chunks.
const CABECERA = /* glsl */`
uniform float tiempo, frecuencia, distor, periodo, detalle, detalleFrec, empuje;
uniform vec3 raton;

vec3 d_mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 d_mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 d_permute(vec4 x) { return d_mod289(((x * 34.0) + 1.0) * x); }
vec4 d_taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
vec3 d_fade(vec3 t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }

float d_pnoise(vec3 P, vec3 rep) {
  vec3 Pi0 = mod(floor(P), rep);
  vec3 Pi1 = mod(Pi0 + vec3(1.0), rep);
  Pi0 = d_mod289(Pi0);
  Pi1 = d_mod289(Pi1);
  vec3 Pf0 = fract(P);
  vec3 Pf1 = Pf0 - vec3(1.0);
  vec4 ix = vec4(Pi0.x, Pi1.x, Pi0.x, Pi1.x);
  vec4 iy = vec4(Pi0.yy, Pi1.yy);
  vec4 iz0 = Pi0.zzzz;
  vec4 iz1 = Pi1.zzzz;
  vec4 ixy = d_permute(d_permute(ix) + iy);
  vec4 ixy0 = d_permute(ixy + iz0);
  vec4 ixy1 = d_permute(ixy + iz1);
  vec4 gx0 = ixy0 * (1.0 / 7.0);
  vec4 gy0 = fract(floor(gx0) * (1.0 / 7.0)) - 0.5;
  gx0 = fract(gx0);
  vec4 gz0 = vec4(0.5) - abs(gx0) - abs(gy0);
  vec4 sz0 = step(gz0, vec4(0.0));
  gx0 -= sz0 * (step(0.0, gx0) - 0.5);
  gy0 -= sz0 * (step(0.0, gy0) - 0.5);
  vec4 gx1 = ixy1 * (1.0 / 7.0);
  vec4 gy1 = fract(floor(gx1) * (1.0 / 7.0)) - 0.5;
  gx1 = fract(gx1);
  vec4 gz1 = vec4(0.5) - abs(gx1) - abs(gy1);
  vec4 sz1 = step(gz1, vec4(0.0));
  gx1 -= sz1 * (step(0.0, gx1) - 0.5);
  gy1 -= sz1 * (step(0.0, gy1) - 0.5);
  vec3 g000 = vec3(gx0.x, gy0.x, gz0.x);
  vec3 g100 = vec3(gx0.y, gy0.y, gz0.y);
  vec3 g010 = vec3(gx0.z, gy0.z, gz0.z);
  vec3 g110 = vec3(gx0.w, gy0.w, gz0.w);
  vec3 g001 = vec3(gx1.x, gy1.x, gz1.x);
  vec3 g101 = vec3(gx1.y, gy1.y, gz1.y);
  vec3 g011 = vec3(gx1.z, gy1.z, gz1.z);
  vec3 g111 = vec3(gx1.w, gy1.w, gz1.w);
  vec4 norm0 = d_taylorInvSqrt(vec4(dot(g000, g000), dot(g010, g010), dot(g100, g100), dot(g110, g110)));
  g000 *= norm0.x; g010 *= norm0.y; g100 *= norm0.z; g110 *= norm0.w;
  vec4 norm1 = d_taylorInvSqrt(vec4(dot(g001, g001), dot(g011, g011), dot(g101, g101), dot(g111, g111)));
  g001 *= norm1.x; g011 *= norm1.y; g101 *= norm1.z; g111 *= norm1.w;
  float n000 = dot(g000, Pf0);
  float n100 = dot(g100, vec3(Pf1.x, Pf0.yz));
  float n010 = dot(g010, vec3(Pf0.x, Pf1.y, Pf0.z));
  float n110 = dot(g110, vec3(Pf1.xy, Pf0.z));
  float n001 = dot(g001, vec3(Pf0.xy, Pf1.z));
  float n101 = dot(g101, vec3(Pf1.x, Pf0.y, Pf1.z));
  float n011 = dot(g011, vec3(Pf0.x, Pf1.yz));
  float n111 = dot(g111, Pf1);
  vec3 fade_xyz = d_fade(Pf0);
  vec4 n_z = mix(vec4(n000, n100, n010, n110), vec4(n001, n101, n011, n111), fade_xyz.z);
  vec2 n_yz = mix(n_z.xy, n_z.zw, fade_xyz.y);
  return 2.2 * mix(n_yz.x, n_yz.y, fade_xyz.x);
}

vec3 d_orthogonal(vec3 v) {
  return normalize(abs(v.x) > abs(v.z) ? vec3(-v.y, v.x, 0.0) : vec3(0.0, -v.z, v.y));
}

// cuánto se mueve cada punto a lo largo de su normal: la masa (ruido lento y grande) más el
// relieve de la superficie (ruido pequeño y más rápido), que es lo que la hace parecer cera
float f(vec3 punto) {
  float masa = d_pnoise(punto / frecuencia + mod(tiempo, periodo), vec3(periodo)) * distor;
  float piel = d_pnoise(punto * detalleFrec + mod(tiempo * 1.6, periodo), vec3(periodo)) * detalle;
  // el hoyo del ratón: una campana alrededor de la dirección a la que apunta (a = 1 - cos del ángulo)
  float a = 1.0 - dot(normalize(punto), raton);
  return masa + piel - empuje * .3 * exp(-a / .14);
}
`;

// el desplazamiento y la corrección de normales (dos vecinos y producto cruzado), tal cual el original
const DESPLAZA = /* glsl */`
  vec3 displacedPosition = position + normalize(normal) * f(position);
  float offset = .5 / 512.;
  vec3 tangente = d_orthogonal(normal);
  vec3 bitangente = normalize(cross(normal, tangente));
  vec3 vecino1 = position + tangente * offset;
  vec3 vecino2 = position + bitangente * offset;
  vec3 dVecino1 = vecino1 + normal * f(vecino1);
  vec3 dVecino2 = vecino2 + normal * f(vecino2);
  vec3 displacedNormal = normalize(cross(dVecino1 - displacedPosition, dVecino2 - displacedPosition));
  // según cómo caigan los dos vecinos el producto cruzado sale hacia dentro y la gota se ve negra:
  if (dot(displacedNormal, normal) < 0.0) displacedNormal = -displacedNormal;
`;

// El entorno: un degradado vertical (arriba claro, abajo casi negro) hecho con un canvas y pasado
// por PMREM. Es lo que le da el reflejo suave del barniz sin cargar ningún HDRI.
function entorno(ren) {
  const cv = document.createElement('canvas');
  cv.width = 16; cv.height = 256;
  const x = cv.getContext('2d'), g = x.createLinearGradient(0, 0, 0, 256);
  g.addColorStop(0, '#ffffff'); g.addColorStop(.42, '#b4b4b4'); g.addColorStop(.62, '#2a2a2a'); g.addColorStop(1, '#050505');
  x.fillStyle = g; x.fillRect(0, 0, 16, 256);
  const tex = new THREE.CanvasTexture(cv);
  tex.mapping = THREE.EquirectangularReflectionMapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  const pmrem = new THREE.PMREMGenerator(ren);
  const env = pmrem.fromEquirectangular(tex).texture;
  pmrem.dispose(); tex.dispose();
  return env;
}

function montar(cv) {
  const ren = new THREE.WebGLRenderer({canvas: cv, antialias: true, alpha: true, powerPreference: 'high-performance'});
  ren.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
  ren.setClearColor(0x000000, 0);
  ren.toneMapping = THREE.ACESFilmicToneMapping;
  ren.toneMappingExposure = 1.05;

  const escena = new THREE.Scene();
  escena.environment = entorno(ren);

  const u = {
    tiempo: {value: 0}, frecuencia: {value: 1.35}, distor: {value: .3},
    periodo: {value: 4}, detalle: {value: .035}, detalleFrec: {value: 3.4},
    empuje: {value: 0}, raton: {value: dirR},
  };
  const mat = new THREE.MeshPhysicalMaterial({
    color: 0xffffff, roughness: .14, metalness: 0, clearcoat: 1, clearcoatRoughness: .12,
    envMapIntensity: 1.15, sheen: .2, sheenColor: new THREE.Color(0xffd9d4),
  });
  mat.onBeforeCompile = sh => {
    Object.assign(sh.uniforms, u);
    sh.vertexShader = CABECERA + sh.vertexShader;
    // beginnormal_vertex va ANTES que begin_vertex: ahí se calcula todo y se cambia la normal
    sh.vertexShader = sh.vertexShader
      .replace('#include <beginnormal_vertex>', DESPLAZA + '\n  vec3 objectNormal = displacedNormal;')
      .replace('#include <begin_vertex>', '  vec3 transformed = displacedPosition;');
  };

  const malla = new THREE.Mesh(new THREE.SphereGeometry(1, SEG, SEG), mat);
  escena.add(malla);

  // luz: una clave blanca que marca el volumen y un contraluz rojo, el acento del panel
  escena.add(new THREE.HemisphereLight(0xffffff, 0x0a0a0a, .55));
  const clave = new THREE.DirectionalLight(0xffffff, 2.2); clave.position.set(-1.6, 2.2, 2.4); escena.add(clave);
  const contra = new THREE.DirectionalLight(0xff2d1f, 1.1); contra.position.set(1.8, -.6, -1.8); escena.add(contra);

  const cam = new THREE.PerspectiveCamera(30, 1, .1, 50);
  cam.position.set(0, 0, 6.6);
  return {ren, escena, cam, malla, u};
}

export function pintar(cv, d) {
  const w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return;
  if (!r3) r3 = montar(cv);
  const {ren, escena, cam, malla, u} = r3;
  if (cv.width !== Math.round(w * ren.getPixelRatio()) || cv.height !== Math.round(h * ren.getPixelRatio())) {
    ren.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix();
  }

  const ms = performance.now(), t = ms / 1000 - t0;
  const est = d.estado || 'dormido', hablando = est === 'hablando';
  const nac = suave(t / ENTRA);
  const dt = ult ? Math.min(.1, (ms - ult) / 1000) : 0; ult = ms;

  // La voz se sigue con constantes de tiempo, no con un factor por fotograma: el nivel llega a
  // saltos cada 0,4 s por el WebSocket y aquí interesa que la gota lo *acompañe*. Sube deprisa
  // (se nota al empezar a hablar) y baja despacio (no da tirones en cada sílaba), y después se
  // vuelve a suavizar otra vez: eso es lo «gradual». El orbe 1 puede ir más nervioso porque es
  // alambre; esta gota, al ser una superficie sólida, delata cualquier salto.
  const sigue = (v, obj, sube, baja) => v + (obj - v) * (1 - Math.exp(-dt / (obj > v ? sube : baja)));
  NV = sigue(NV, d.nivel || 0, .13, .80);
  MV = sigue(MV, (d.mic || {}).nivel || 0, .18, 1.0);
  const bruto = hablando ? NV : est === 'escuchando' ? MV * .7 : 0;
  V = sigue(V, bruto, .28, .65);

  // la fase del ruido se acumula (como el giro): así la voz cambia la VELOCIDAD del hervor y no
  // da un salto en el ruido, que es lo que pasaba al multiplicar la voz por el tiempo absoluto.
  fase += dt * (.42 + V * .30);
  giro += dt * (.12 + (hablando ? .34 : est === 'trabajando' ? .25 : 0) + V * .5);
  malla.rotation.set(Math.sin(t * .11) * .22, giro, Math.sin(t * .07) * .12);
  malla.scale.setScalar(.8 * (.6 + .4 * nac) * (1 + V * .04));   // con voz se hincha un poco
  malla.position.set(0, .46, 0);   // arriba del centro: debajo van la hora y la conversación
  empujar(cam, malla, w, h, sigue);

  u.tiempo.value = fase;
  u.distor.value = (.20 + .05 * Math.sin(t * .55) + V * .26) * nac;   // respira siempre; con voz, se hincha
  u.detalle.value = (.02 + V * .045) * nac;                          // y le sale grano en la piel
  u.empuje.value = E * nac;
  ren.render(escena, cam);

  hora();
  conversacion(d, nac);
}

// El rayo del ratón contra la gota sin deformar. Si la toca, el hoyo va donde la toca; si pasa
// cerca, va hacia el lado del ratón y con menos fuerza. La dirección y la fuerza se suavizan, que
// si no el hoyo salta de un sitio a otro al mover el ratón deprisa.
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), cen = new THREE.Vector3(), pc = new THREE.Vector3();
function empujar(cam, malla, w, h, sigue) {
  let obj = 0;
  if (rx !== null) {
    ndc.set(rx / w * 2 - 1, 1 - ry / h * 2);
    ray.setFromCamera(ndc, cam);
    const R = malla.scale.x * 1.05, o = ray.ray.origin, d = ray.ray.direction;
    malla.getWorldPosition(cen);
    pc.copy(o).addScaledVector(d, cen.clone().sub(o).dot(d));       // punto del rayo más cerca del centro
    const dist = pc.distanceTo(cen);
    if (dist < R) pc.copy(o).addScaledVector(d, cen.clone().sub(o).dot(d) - Math.sqrt(R * R - dist * dist));
    else pc.sub(cen).setLength(R).add(cen);
    obj = dist < R ? 1 : 1 - suave((dist - R) / (R * .7));
    if (obj > 0) dirR.lerp(malla.worldToLocal(pc.clone()).normalize(), .25).normalize();
  }
  E = sigue(E, obj, .12, .5);
  // el cuerpo se aparta del ratón: hacia el lado contrario, en el plano de la pantalla
  if (E > 0) {
    const lado = malla.localToWorld(dirR.clone()).sub(cen);
    malla.position.x -= lado.x * E * .07; malla.position.y -= lado.y * E * .07;
  }
}

// ---- la hora: «1 9 : 4 2», sin segundos. Los dos puntos laten solos (CSS), que es el único
// movimiento que se permite aquí: lo demás lo pone la gota.
let ultMin = -1;
function hora() {
  const n = new Date(), m = n.getHours() * 60 + n.getMinutes();
  if (m === ultMin) return;
  ultMin = m;
  const e = document.getElementById('fb-hora');
  e.innerHTML = String(n.getHours()).padStart(2, '0') + '<i>:</i>' + String(n.getMinutes()).padStart(2, '0');
}

// ---- la conversación, en las mismas burbujas del panel.
// Se apaga sola a los 20 s de la última frase, que si no acabas con un salvapantallas lleno de texto
// viejo; mientras estés leyendo más arriba con la rueda no se apaga, y una frase nueva la devuelve.
const APAGA = 20e3;
let firma = '', ultCambio = 0, ultRueda = 0, atado = false;
const esc = v => String(v ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

function conversacion(d, nac) {
  const c = document.getElementById('fb-chat');
  if (!atado) {   // la rueda sobre las burbujas es para leerlas, no para quitar el salvapantallas
    atado = true;
    c.addEventListener('wheel', e => { e.stopPropagation(); ultRueda = performance.now(); }, {passive: true});
  }
  const fr = (d.frases || []).slice(-14);
  const nueva = fr.map(f => f.rol + f.t).join('\u0000');
  if (nueva !== firma) {
    const abajo = c.scrollHeight - c.scrollTop - c.clientHeight < 40;
    firma = nueva; ultCambio = performance.now();
    c.innerHTML = fr.map(f => {
      const tu = f.rol === 'tú';
      return `<div class="msg ${tu ? 'tu' : 'delta'}"><small>${tu ? 'TÚ' : 'DELTA'}${f.h ? ' · ' + f.h : ''}</small>` +
        `<div class="bub">${esc(f.t)}</div></div>`;
    }).join('');
    if (abajo) c.scrollTop = c.scrollHeight;
  }
  // leyendo = subido a releer: entonces no se apaga aunque pasen los 20 s
  const leyendo = c.scrollHeight - c.scrollTop - c.clientHeight > 40;
  const vivo = performance.now() - Math.max(ultCambio, ultRueda) < APAGA;
  c.classList.toggle('apagado', nac < 1 || !fr.length || !(vivo || leyendo));
}
