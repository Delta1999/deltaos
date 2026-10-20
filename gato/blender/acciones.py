"""Animaciones del gato para Blender (las monta montar.py): ACCIONES = {nombre: (f(t) → pose, segundos, en bucle)}.
Mismos nombres que mascota3d/poses.py, porque mascota.py elige por nombre.

Para que no se mueva como un robot: nada de senos sueltos en todos los huesos, sino
  - posturas clave con entradas y salidas suaves y ratos quieto (tramo), como las pone un animador;
  - lo que cuelga va con retraso: la cabeza tras el cuerpo, la cola en onda de la base a la punta, las orejas al final;
  - respiración, tics de oreja y cambios de peso sueltos, con un bucle largo para que no se note la repetición;
  - patas con IK: se plantan en el suelo (bajo el hombro o la cadera, calculados aquí con el cuerpo ya posado)
    y al andar se quedan quietas en el apoyo mientras el cuerpo avanza.

Pose = {hueso: {"r": (rx, ry, rz) grados, "t": (dx, dy, dz) unidades base, "s": …}} como en mascota3d/rig.py: giran
sobre la cabeza del hueso en los ejes del padre; z arriba, el gato mira a -Y (rx + baja el morro, rz + gira hacia la
derecha de la pantalla vista de frente, ry + lo inclina). Los ik_* son sueltos: su "t" es dónde va la muñeca, el
corvejón o la almohadilla, menos su sitio en reposo.
"""
from math import atan2, cos, degrees, exp, pi, radians, sin

import numpy as np

from esqueleto import CABEZA, PADRE

E, FPS = 1.3, 24
V = 70 / 5 / E / sin(radians(70))  # base/s que avanza la mascota (VEL / CELDA, visto de perfil a 70°)
ACCIONES = {}
K = {"i": -1, "d": 1}
TARSO = 2.14                        # corvejón → almohadilla trasera
ANG_TARSO = degrees(atan2(0.4, 2.1))  # en reposo el corvejón cae casi encima de la almohadilla


def accion(dur, ciclo=True):
    def reg(f):
        ACCIONES[f.__name__] = (f, dur, ciclo)
        return f
    return reg


# ---- curvas ----
def lim(x):
    return min(max(x, 0.0), 1.0)


def ease(x):
    """0 → 1 con salida y llegada lentas."""
    return 0.5 - 0.5 * cos(pi * lim(x))


def tramo(t, claves):
    """Valor en t entre posturas clave [(t, v), …] (v número o tupla), suavizado y quieto antes y después."""
    if t <= claves[0][0]:
        return np.asarray(claves[0][1], float)
    for (t0, a), (t1, b) in zip(claves, claves[1:]):
        if t <= t1:
            a, b = np.asarray(a, float), np.asarray(b, float)
            return a + (b - a) * ease((t - t0) / (t1 - t0))
    return np.asarray(claves[-1][1], float)


def golpe(t, t0, dur):
    """Ida y vuelta rápida (un tic): 0 → 1 → 0 entre t0 y t0 + dur, con la vuelta más lenta que la ida."""
    x = (t - t0) / dur
    return 0.0 if not 0 < x < 1 else sin(pi * x ** 0.6)


def ola(t, periodo, fase=0.0):
    return sin(2 * pi * (t / periodo - fase))


def respira(t, periodo=2.2, fuerza=1.0):
    """Pecho que sube y baja (inspira más deprisa de lo que espira)."""
    x = (t / periodo) % 1
    k = ease(x / 0.4) if x < 0.4 else 1 - ease((x - 0.4) / 0.6)
    return {"lomo": {"r": (-0.8 * k * fuerza, 0, 0)}, "pecho": {"r": (-1.2 * k * fuerza, 0, 0)},
            "cuello": {"r": (1.6 * k * fuerza, 0, 0)}, "raiz": {"t": (0, 0, 0.06 * k * fuerza)}}


# ---- poses ----
def suma(*partes):
    """Junta poses sumando giros y desplazamientos (y multiplicando escalas) del mismo hueso."""
    out = {}
    for p in partes:
        for h, q in p.items():
            d = out.setdefault(h, {})
            for c, v in q.items():
                v = np.asarray(v, float)
                d[c] = d[c] * v if c == "s" and c in d else d[c] + v if c in d else v
    return out


def rot(rx, ry, rz):
    a, b, c = np.radians((rx, ry, rz))
    X = np.array([[1, 0, 0], [0, cos(a), -sin(a)], [0, sin(a), cos(a)]])
    Y = np.array([[cos(b), 0, sin(b)], [0, 1, 0], [-sin(b), 0, cos(b)]])
    Z = np.array([[cos(c), -sin(c), 0], [sin(c), cos(c), 0], [0, 0, 1]])
    return Z @ Y @ X


def punto(pose, hueso, p):
    """Dónde cae en el mundo el punto p (en reposo) que lleva el hueso, con la pose puesta."""
    cadena, h = [], hueso
    while h:
        cadena.append(h)
        h = PADRE[h]
    M = np.eye(4)
    for h in reversed(cadena):
        q, c = pose.get(h, {}), CABEZA[h]
        L = np.eye(4)
        L[:3, :3] = rot(*q.get("r", (0, 0, 0))) * np.asarray(q.get("s", (1, 1, 1)))
        L[:3, 3] = c - L[:3, :3] @ c + np.asarray(q.get("t", (0, 0, 0)))
        M = M @ L
    return M[:3, :3] @ p + M[:3, 3]


def cuerpo(sube=0.0, avanza=0.0, lado=0.0, cabecea=0.0, ladea=0.0, gira=0.0, arquea=0.0, curva=0.0):
    """Tronco: cabecea + = levanta el pecho (gira sobre las caderas, repartido por la columna); arquea + = lomo de
    gato enfadado; curva = la columna en C hacia un lado (+ derecha de la pantalla); gira = todo el cuerpo."""
    return {"raiz": {"r": (-cabecea * 0.6, ladea, gira), "t": (lado, -avanza, sube)},
            "lomo": {"r": (-cabecea * 0.25 - arquea, 0, curva * 0.35)},
            "pecho": {"r": (-cabecea * 0.15 + arquea * 0.6, 0, curva * 0.35)},
            "hombro_i": {"r": (cabecea * 1.1, 0, 0)}, "hombro_d": {"r": (cabecea * 1.1, 0, 0)},  # omóplatos de pie
            "cuello": {"r": (cabecea * 0.5 + arquea * 0.4, 0, curva * 0.3)}}  # la cabeza no se va con el pecho


def cabeza(mira=0.0, gira=0.0, ladea=0.0, estira=0.0):
    """mira + = levanta el morro; gira + = hacia la derecha de la pantalla; ladea + = inclina hacia su izquierda.
    El cuello se lleva un tercio; estira = cuello adelante (+) o encogido (−)."""
    return {"cuello": {"r": (-mira * 0.35 - estira, 0, gira * 0.35)},
            "cabeza": {"r": (-mira * 0.65 + estira, ladea, gira * 0.65)}}


def orejas(atras=0.0, fuera=0.0, gira=0.0, i=0.0, d=0.0):
    """atras + = gachas hacia atrás (− hacia delante, atento); fuera = abiertas a los lados (de avión si va con
    atras); gira = vuelven la concha hacia la derecha de la pantalla; i, d = tic de cada una."""
    return {f"oreja_{s}": {"r": (-atras - 25 * tic, (fuera + 20 * tic) * K[s], gira)} for s, tic in (("i", i), ("d", d))}


def cola(t, alza=0.0, curva=0.0, meneo=0.0, periodo=3.0, punta=0.0, enrosca=0.0):
    """alza: la base (− cae hacia atrás, + sobre el lomo); curva: se dobla hacia un lado (+ derecha de la pantalla),
    repartido por toda la cola; meneo: onda que va de la base a la punta, más ancha en la punta; punta: golpe de las
    dos últimas vértebras; enrosca: la punta hacia arriba (+) o abajo (−)."""
    p = {}
    for k in range(6):
        onda = meneo * (0.35 + 0.15 * k) * ola(t, periodo, k * 0.09)
        p[f"cola{k + 1}"] = {"r": (alza * (1.0 if k == 0 else 0.0) + enrosca * k / 15,
                                   curva / 5 * (k > 0) + onda + punta * (k >= 4), 0)}
    return p


def mano(pose, s, dy=0.0, alza=0.0, dx=0.0, dobla=0.0, en=None, rel=None, alcanza=None):
    """Muñeca delantera: por defecto en el suelo bajo su hombro (dy + = hacia atrás, alza = la levanta); en = sitio
    del mundo; rel = desde el hombro; alcanza = (rel, k): de su sitio en el suelo (k = 0) a rel (k = 1).
    dobla + = la almohadilla mira atrás (pata recogida)."""
    J = punto(pose, f"hombro_{s}", CABEZA[f"brazo_{s}"])
    if en is None:
        en = J + rel if rel is not None else J + (dx * K[s], -0.4 + dy, 0) - (0, 0, J[2] - 1.4 - alza)
    if alcanza:
        en = en + (J + np.asarray(alcanza[0]) - en) * alcanza[1]
    return {f"ik_mano_{s}": {"t": tuple(np.asarray(en) - CABEZA[f"ik_mano_{s}"]), "r": (dobla, 0, 0)}}


def pie(pose, s, dy=0.0, alza=0.0, dx=0.0, ang=ANG_TARSO, punta=0.0, en=None, rel=None, alcanza=None):
    """Almohadilla trasera: por defecto en el suelo bajo su cadera (dy + = atrás); en / rel como en mano. ang: el
    corvejón respecto a la almohadilla (≈11° de pie, 90° = tumbado en el suelo detrás de ella, − delante); punta +
    = dedos hacia abajo."""
    H = punto(pose, f"muslo_{s}", CABEZA[f"muslo_{s}"])
    if en is None:
        en = H + rel if rel is not None else np.array([H[0] + (dx - 0.4) * K[s], H[1] + 1.8 + dy, 1.3 + alza])
    en = np.asarray(en, float)
    if alcanza:
        en = en + (H + np.asarray(alcanza[0]) - en) * alcanza[1]
    a = radians(ang)
    talon = en + (0.1 * K[s], TARSO * sin(a), TARSO * cos(a))
    return {f"ik_pie_{s}": {"t": tuple(en - CABEZA[f"ik_pie_{s}"]), "r": (punta, 0, 0)},
            f"ik_talon_{s}": {"t": tuple(talon - CABEZA[f"ik_talon_{s}"])}}


def patas(pose, i=None, d=None, ti=None, td=None):
    """Añade a la pose las cuatro patas (dicts de argumentos de mano / pie; None = apoyada en su sitio)."""
    return suma(pose, mano(pose, "i", **(i or {})), mano(pose, "d", **(d or {})),
                pie(pose, "i", **(ti or {})), pie(pose, "d", **(td or {})))


# ---- sentado: la base de casi todo lo que hace quieto ----
SENTADO = dict(cabecea=30, sube=-6.0, avanza=0.3)
PIE_SENTADO = dict(dy=-2.6, ang=88, alza=-0.2)   # corvejón en el suelo y la almohadilla delante


def sienta(erguido=0.0, **extra):
    """Sentado; erguido + = saca pecho: lo dobla la parte alta de la columna, así los hombros apenas suben y las manos
    siguen llegando al suelo."""
    p = cuerpo(**dict(SENTADO, **extra))
    return suma(p, {"pecho": {"r": (-erguido * 0.8, 0, 0)}, "lomo": {"r": (-erguido * 0.2, 0, 0)},
                    "cuello": {"r": (erguido * 0.6, 0, 0)}, "cabeza": {"r": (erguido * 0.4, 0, 0)},
                    "hombro_i": {"r": (erguido, 0, 0)}, "hombro_d": {"r": (erguido, 0, 0)}})


def sentado_patas(pose, i=None, d=None, ti=None, td=None):
    return patas(pose, i, d, dict(PIE_SENTADO, **(ti or {})), dict(PIE_SENTADO, **(td or {})))


def cola_sentado(t, meneo=0.0, punta=0.0, periodo=4.0):
    """Cae por detrás hasta el suelo y rodea las patas por un lado."""
    return cola(t, alza=-95, curva=-130, meneo=meneo, periodo=periodo, punta=punta, enrosca=-20)


# ---- en bucle ----
@accion(9.0)
def reposo(t):
    """Sentado tranquilo: mira por ahí con pausas, respira, mueve una oreja, cambia el peso y mueve la punta de la cola."""
    gira = tramo(t, [(0, 0), (1.0, 0), (1.6, 28), (3.4, 28), (3.9, -4), (5.2, -4), (6.0, -32), (7.6, -32), (8.4, 0)])
    mira = tramo(t, [(0, 0), (1.0, 0), (1.6, 6), (3.4, 6), (3.9, -3), (5.2, -3), (6.0, 3), (7.6, 3), (8.4, 0)])
    peso = tramo(t, [(0, 0), (4.0, 0), (4.8, 2.5), (7.8, 2.5), (8.8, 0)])
    p = suma(sienta(ladea=peso), respira(t, 2.25), cabeza(float(mira), float(gira), -gira * 0.15),
             orejas(-4, 4, gira * 0.3, i=golpe(t, 5.4, 0.22), d=golpe(t, 2.3, 0.2) + golpe(t, 2.6, 0.18)),
             cola_sentado(t, punta=14 * golpe(t, 3.0, 0.5) - 10 * golpe(t, 7.0, 0.6)))
    return sentado_patas(p)


@accion(2.0)
def anda(t):
    """Paso de gato (secuencia lateral: trasera izquierda, delantera izquierda, trasera derecha, delantera derecha),
    apoyo del 62%: en el apoyo la pata se queda clavada y se desliza hacia atrás a la velocidad del cuerpo. Las
    manos pisan un poco por detrás del hombro: la pata delantera no da más de sí."""
    T, B = 1.0, 0.62
    A = V * B * T / 2
    f = t / T
    p = suma(cuerpo(sube=-0.6 + 0.22 * cos(4 * pi * (f - 0.1)), ladea=-1.2 * sin(2 * pi * f), gira=2.0 * sin(2 * pi * (f - 0.1)),
                    lado=0.12 * sin(2 * pi * f), curva=-3.0 * sin(2 * pi * (f - 0.15))),
             cabeza(-6 + 1.2 * cos(4 * pi * (f - 0.25)), -2.0 * sin(2 * pi * (f - 0.2)), 0, estira=3),
             orejas(-3, 4, i=golpe(t, 1.4, 0.2) * 0.5),
             cola(t, alza=-10, curva=0, meneo=7, periodo=2 * T, enrosca=8))
    args = {}
    for lado, fase, delante in (("i", 0.25, True), ("d", 0.75, True), ("i", 0.0, False), ("d", 0.5, False)):
        x = (f - fase) % 1
        if x < B:  # apoyo: de delante (−A) a detrás (+A); al final despega el talón
            u = x / B
            dy, alza, despega = -A + 2 * A * u, 0.0, ease((u - 0.75) / 0.25)
            q = (dict(dy=dy + 0.8, alza=0.5 * despega, dobla=35 * despega) if delante else
                 dict(dy=dy, alza=0.3 * despega, punta=30 * despega, ang=ANG_TARSO - 12 * despega))
        else:      # vuelo: adelante con la pata recogida, la estira justo antes de posarla
            u = (x - B) / (1 - B)
            dy, alza = A - 2 * A * ease(u), sin(pi * u ** 0.8)
            q = (dict(dy=dy + 0.8, alza=1.6 * alza, dobla=75 * sin(pi * min(u * 1.3, 1)) + 35 * (1 - ease(u * 3))) if delante else
                 dict(dy=dy, alza=1.3 * alza, punta=30 * (1 - ease(u * 2.5)), ang=ANG_TARSO - 12 * (1 - ease(u * 3)) - 35 * sin(pi * u)))
        if delante:  # el omóplato acompaña a la pata
            p = suma(p, {f"hombro_{lado}": {"r": (12 * dy / A, 0, 0)}})
        if delante:  # respecto al suelo, no al hombro (que va y viene con el omóplato)
            q["en"] = CABEZA[f"ik_mano_{lado}"] + (0, q.pop("dy"), q.pop("alza"))
        else:
            q["en"] = CABEZA[f"ik_pie_{lado}"] + (0, q.pop("dy"), q.pop("alza"))
        args[("" if delante else "t") + lado] = q
    return patas(p, **args)


@accion(11.0)
def sentado(t):
    """Encima de una ventana: sentado mirando abajo, con la cola colgando por el borde y meneando la punta."""
    gira = tramo(t, [(0, -10), (2.0, -10), (3.0, 22), (6.0, 22), (7.2, -10)])
    mira = tramo(t, [(0, -14), (2.0, -14), (3.0, -6), (6.0, -6), (7.2, -14)])
    p = suma(sienta(), respira(t, 2.75), cabeza(float(mira), float(gira), 4),
             orejas(-2, 3, gira * 0.4, d=golpe(t, 4.4, 0.2), i=golpe(t, 9.3, 0.2)),
             cola(t, alza=-110, curva=10, meneo=6, periodo=5.5, punta=10 * golpe(t, 8.0, 0.5), enrosca=-6))
    return sentado_patas(p)


@accion(6.0)
def escucha(t):
    """Atento a ti: erguido, orejas de punta hacia delante y la cabeza ladeada, que cambia de lado."""
    ladea = tramo(t, [(0, 12), (2.6, 12), (3.1, -10), (5.6, -10), (6.0, 12)])
    p = suma(sienta(erguido=6), respira(t, 2.0), cabeza(8, 0, float(ladea)), orejas(-14, -4, i=golpe(t, 1.5, 0.18)),
             cola_sentado(t, punta=8 * golpe(t, 4.2, 0.5)))
    return sentado_patas(p)


@accion(6.0)
def alto(t):
    return escucha(t)


@accion(4.0)
def habla(t):
    """Te cuenta algo: cabecea al ritmo, gira un poco y gesticula con una pata."""
    gesto = tramo(t, [(0, 0), (1.2, 0), (1.5, 1), (2.3, 1), (2.7, 0)])
    p = suma(sienta(erguido=3), respira(t, 2.0), cabeza(4 + 3 * abs(sin(2 * pi * t)), 8 * ola(t, 4.0), 5 * ola(t, 4.0, 0.2)),
             orejas(-6, 3 + 4 * ola(t, 2.0)), cola_sentado(t, meneo=4))
    return sentado_patas(p, d=dict(alza=2.6 * float(gesto), dy=-2.0 * float(gesto), dobla=50 * float(gesto)))


@accion(2.0)
def trabaja(t):
    """Juega con el cometa: zarpazo con una pata y luego con la otra (recoge, golpe rápido, vuelve despacio) y la
    cabeza sigue la bola."""
    def zarpa(t0):
        x = t - t0
        return (0.0 if x < 0 else -0.25 * ease(x / 0.25) if x < 0.25 else
                -0.25 + 1.25 * ease((x - 0.25) / 0.12) if x < 0.37 else 1 - ease((x - 0.45) / 0.45) if x < 0.9 else 0.0)
    a, b = zarpa(0.0), zarpa(1.0)
    p = suma(sienta(erguido=8), cabeza(14 + 8 * ola(t, 2.0, 0.25), 25 * ola(t, 2.0), 6 * ola(t, 2.0)),
             orejas(-12, -2), cola_sentado(t, meneo=10, punta=12 * ola(t, 0.5), periodo=2.0))
    return sentado_patas(p, d=dict(dy=4 * min(a, 0), alcanza=((1.2, -6.0, 1.5), max(a, 0)), dobla=60 * max(a, 0)),
                         i=dict(dy=4 * min(b, 0), alcanza=((-1.2, -6.0, 1.5), max(b, 0)), dobla=60 * max(b, 0)))


@accion(1.6)
def permiso(t):
    """Te pide algo: muy erguido, toca el aire con una pata dos veces y ladea la cabeza."""
    toque = golpe(t, 0.1, 0.35) + golpe(t, 0.55, 0.35)
    p = suma(sienta(erguido=10), cabeza(12, 0, 14), orejas(-12, -3), cola_sentado(t, meneo=6, punta=10 * ola(t, 0.8), periodo=1.6))
    return sentado_patas(p, d=dict(rel=(0.4, -4.0 - 1.0 * toque, -4.5 + 2.0 * toque), dobla=70))


@accion(2.0)
def agobio(t):
    """El ordenador va ahogado: agazapado, orejas de avión, la cola pegada y tiritando."""
    tirita = 0.1 * ola(t, 1 / 6)
    p = suma(sienta(erguido=-14, sube=-6.6, lado=tirita), cabeza(-14, 0, 0, estira=-6), orejas(25, 45),
             cola(t, alza=-100, curva=-170, enrosca=-25), {"raiz": {"r": (0, 0, 1.2 * ola(t, 1 / 5))}})
    return sentado_patas(p)


@accion(6.0)
def calor(t):
    """Hace calor: tumbado y aplastado, las traseras estiradas hacia atrás, jadeando."""
    jadeo = sin(2 * pi * 3 * t)
    p = suma(cuerpo(sube=-6.7, cabecea=-2), {"pecho": {"r": (-1.0 * jadeo, 0, 0)}, "lomo": {"r": (-0.6 * jadeo, 0, 0)}},
             cabeza(-6, 12 * ola(t, 6.0), 10), orejas(15, 35), cola(t, alza=-118, curva=40, meneo=3, periodo=6.0, enrosca=-12))
    return patas(p, i=dict(dy=-4.5, alza=-0.3, dobla=-10), d=dict(dy=-4.0, alza=-0.3, dobla=-10),
                 ti=dict(dy=6.0, ang=150, punta=-60, alza=-0.1), td=dict(dy=6.0, ang=150, punta=-60, alza=-0.1))


@accion(8.0)
def duerme(t):
    """Hecho una rosquilla: tumbado, la columna en C, la cabeza apoyada mirando a la cola, que le rodea; respira
    despacio y alguna vez mueve una oreja."""
    p = suma(cuerpo(sube=-6.8, curva=-55, gira=18), respira(t, 4.0, 2.2), cabeza(-22, -55, -24, estira=-4),
             orejas(10, 20, i=golpe(t, 5.0, 0.25)), cola(t, alza=-112, curva=-210, enrosca=-12, punta=6 * golpe(t, 2.0, 0.8)))
    return patas(p, i=dict(dy=-2.5, alza=-0.4, dobla=-20, dx=0.6), d=dict(dy=-1.0, alza=-0.4, dobla=20, dx=-1.4),
                 ti=dict(dy=-3.2, ang=92, alza=-0.3), td=dict(dy=-3.0, ang=92, alza=-0.3, dx=1.0))


@accion(1.0)
def cae(t):
    """Cayendo: patas abiertas y estiradas hacia el suelo, cola de timón, orejas atrás."""
    m = 0.8 * ola(t, 1.0)
    p = suma(cuerpo(sube=2.0, cabecea=-4), cabeza(-12, 0, 3 * ola(t, 1.0)), orejas(25, 20),
             cola(t, alza=8, meneo=16, periodo=1.0, enrosca=10))
    return patas(p, i=dict(rel=(-1.6, -1.6 + m, -7.6)), d=dict(rel=(1.6, -1.6 - m, -7.6)),
                 ti=dict(rel=(-1.2, 3.0 - m, -9.0), ang=-10), td=dict(rel=(1.2, 3.0 + m, -9.0), ang=-10))


@accion(2.0)
def arrastre(t):
    """Cogido por el pescuezo: cuelga casi vertical, manos sueltas que se balancean con retraso, traseras encogidas
    hacia la barriga (nada de «de pie») y la cola metida entre ellas."""
    b = ola(t, 2.0)
    p = suma(cuerpo(cabecea=80, sube=-3.5, avanza=-6, ladea=4 * b), cabeza(-40, 6 * ola(t, 2.0, 0.15), 0), orejas(18, 25),
             cola(t, alza=-120, curva=-40 + 10 * ola(t, 2.0, 0.3), enrosca=8))
    return patas(p, i=dict(rel=(-0.5, -1.5 + 1.2 * ola(t, 2.0, 0.12), -8.4), dobla=25),
                 d=dict(rel=(0.5, -1.5 + 1.2 * ola(t, 2.0, 0.2), -8.4), dobla=25),
                 ti=dict(rel=(-1.0, -3.2 + 0.5 * ola(t, 2.0, 0.25), -6.4), ang=50, punta=20),
                 td=dict(rel=(1.0, -3.2 + 0.5 * ola(t, 2.0, 0.3), -6.4), ang=50, punta=20))


@accion(4.0)
def come(t):
    """Se asea: se lame la pata (lametones cortos) y se la pasa por la cara, y vuelta a empezar."""
    sube = tramo(t, [(0, 0), (0.4, 1), (3.4, 1), (3.9, 0)])
    frota = tramo(t, [(0, 0), (2.2, 0), (2.5, 1), (2.9, 0.2), (3.2, 1), (3.5, 0)])
    lame = abs(sin(2 * pi * 2.2 * t)) * (0.5 < t < 2.1)
    p = suma(sienta(erguido=4), cabeza(-30 * float(sube) - 6 * lame + 10 * float(frota), 18 * float(sube), 20 * float(frota)),
             orejas(-2 + 10 * float(frota), 6), cola_sentado(t, meneo=3))
    frota = float(frota)
    return sentado_patas(p, d=dict(alcanza=((-1.6 - 0.8 * frota, -4.5 - 1.0 * frota, -6.5 + 3.0 * frota), float(sube)),
                                   dobla=80 * float(sube)))


@accion(0.5)
def salto_sube(t):
    """Subiendo: estirado, delanteras arriba buscando el borde, traseras empujando hacia atrás, cola de timón."""
    p = suma(cuerpo(cabecea=35, sube=3), cabeza(-25, 0, 0, estira=4), orejas(-8, 0), cola(t, alza=-40, meneo=5, periodo=0.5))
    return patas(p, i=dict(rel=(-0.4, -4.5, -5.0), dobla=40), d=dict(rel=(0.4, -5.0, -4.6), dobla=40),
                 ti=dict(rel=(-0.4, 7.5, -6.5), ang=60, punta=40), td=dict(rel=(0.4, 7.0, -7.0), ang=60, punta=40))


@accion(0.5)
def salto_cae(t):
    """Bajando: delanteras estiradas hacia el suelo para frenar, traseras recogidas, cola arriba."""
    p = suma(cuerpo(cabecea=-18, sube=2), cabeza(14, 0, 0), orejas(10, 15), cola(t, alza=25, meneo=8, periodo=0.5, enrosca=10))
    return patas(p, i=dict(rel=(-0.6, -2.5, -8.8)), d=dict(rel=(0.6, -2.0, -8.8)),
                 ti=dict(rel=(-0.5, -1.0, -6.0), ang=40), td=dict(rel=(0.5, -1.0, -6.0), ang=40))


# ---- de una vez ----
@accion(0.35, ciclo=False)
def aterriza(t):
    """Amortigua: el cuerpo baja y sube, la cabeza llega un poco después y la cola rebota."""
    k = golpe(t, 0.0, 0.3)
    k2 = golpe(t, 0.06, 0.29)
    p = suma(cuerpo(sube=-2.2 * k, cabecea=-4 * k), cabeza(-10 * k2), orejas(10 * k2, 18 * k2), cola(t, alza=-10 - 20 * k2, enrosca=8))
    return patas(p)


@accion(0.7, ciclo=False)
def aplastado(t):
    """¡Plof!: se aplasta con las patas abiertas y rebota hasta ponerse de pie."""
    k = exp(-(t - 0.06) * 5) * cos((t - 0.06) * 17) if t > 0.06 else ease(t / 0.06)
    a = max(k, 0)
    p = suma(cuerpo(sube=-6.2 * k if k > 0 else -0.8 * k), cabeza(-8 * k), orejas(30 * a, 30 * a), cola(t, alza=-50 * a, curva=40 * a, enrosca=5))
    return patas(p, i=dict(dx=3.5 * a, dy=-2 * a), d=dict(dx=3.5 * a, dy=-2 * a), ti=dict(dx=3.0 * a, dy=1.5 * a, ang=11 + 70 * a),
                 td=dict(dx=3.0 * a, dy=1.5 * a, ang=11 + 70 * a))


def de_sentado(t, dur, entra=0.5, sale=0.6):
    """0 sentado → 1 la postura del ocio → 0 sentado otra vez al final."""
    return ease(t / entra) * (1 - ease((t - (dur - sale)) / sale))


@accion(2.5, ciclo=False)
def estira(t):
    """El estiramiento de gato: se levanta, adelanta las manos, pecho al suelo y trasero arriba, y vuelve a sentarse."""
    k = de_sentado(t, 2.5, 0.6, 0.7)
    tiembla = 0.4 * sin(2 * pi * 5 * t) * (0.8 < t < 1.7)
    c = {x: SENTADO[x] * (1 - k) for x in SENTADO}
    p = suma(cuerpo(cabecea=c["cabecea"] - 22 * k, sube=c["sube"] - 1.0 * k + 0.1 * tiembla, avanza=c["avanza"]),
             cabeza(-10 + 34 * k, 0, 0, estira=4 * k), orejas(-4 + 22 * k, 6 * k), cola(t, alza=-95 + 115 * k, curva=-130 * (1 - k), enrosca=12 * k))
    pierna = dict(dy=-2.6 * (1 - k), ang=88 * (1 - k) + ANG_TARSO * k, alza=-0.2)
    return patas(p, i=dict(dy=-6.0 * k, alza=-0.3 * k), d=dict(dy=-6.5 * k, alza=-0.3 * k), ti=pierna, td=pierna)


@accion(2.0, ciclo=False)
def bosteza(t):
    """Bostezo: levanta la cabeza, orejas atrás, se queda un momento y sacude la cabeza al acabar."""
    k = tramo(t, [(0, 0), (0.5, 1), (1.2, 1), (1.6, 0)])
    sacude = sin(2 * pi * 6 * t) * golpe(t, 1.45, 0.35)
    p = suma(sienta(erguido=4 * float(k)), cabeza(30 * float(k), 0, 14 * sacude), orejas(20 * float(k), 18 * float(k)),
             cola_sentado(t, punta=8 * float(k)))
    return sentado_patas(p)


@accion(2.5, ciclo=False)
def rasca(t):
    """Se rasca detrás de la oreja con la pata de atrás: ladea la cabeza hacia la pata y patalea deprisa."""
    k = de_sentado(t, 2.5, 0.45, 0.5)
    pata = sin(2 * pi * 7 * t) * (0.5 < t < 1.9)
    p = suma(sienta(ladea=-8 * k), cabeza(-10 * k, 30 * k, -28 * k), orejas(8 * k, 10 * k, d=0.6 * abs(pata) * k),
             cola_sentado(t, punta=10 * k))
    return sentado_patas(p, td=dict(alcanza=((2.6, -8.5 - 0.9 * pata, 3.0 + 1.0 * pata), k), ang=88 - 40 * k, punta=30 * k))


@accion(2.0, ciclo=False)
def saluda(t):
    """Levanta la pata y la mueve (la almohadilla hacia ti), y la vuelve a posar."""
    k = de_sentado(t, 2.0, 0.4, 0.45)
    agita = sin(2 * pi * 2.5 * t) * (0.4 < t < 1.55)
    p = suma(sienta(erguido=4 * k, ladea=-3 * k), cabeza(8 * k, 6 * k, 10 * k), orejas(-8 * k, 0), cola_sentado(t, meneo=6))
    return sentado_patas(p, d=dict(alcanza=((0.6 + 0.9 * agita, -3.5, 4.9), k), dobla=(-20 + 25 * agita) * k))


@accion(3.0, ciclo=False)
def curioso(t):
    """Ha visto algo: se agazapa, mira fijo, menea el trasero y hace un amago de salto, y se vuelve a sentar."""
    k = de_sentado(t, 3.0, 0.5, 0.6)
    meneo = sin(2 * pi * 3 * t) * tramo(t, [(0, 0), (0.9, 0), (1.1, 1), (1.9, 1), (2.0, 0)])
    salto = golpe(t, 2.0, 0.35)
    c = {x: SENTADO[x] * (1 - k) for x in SENTADO}
    p = suma(cuerpo(cabecea=c["cabecea"] - 6 * k, sube=c["sube"] - 3.0 * k + 2.5 * salto, avanza=c["avanza"] + 2.5 * salto,
                    gira=2.5 * float(meneo), lado=0.4 * float(meneo)),
             cabeza(4 * k, 0, 0, estira=8 * k), orejas(-16 * k, -4 * k),
             cola(t, alza=-95 * (1 - k) - 30 * k, curva=-130 * (1 - k), punta=18 * k * ola(t, 0.6), enrosca=-10))
    pierna = dict(dy=-2.6 * (1 - k) + 0.5 * k, ang=88 * (1 - k) + 45 * k, alza=-0.2 + 1.2 * salto)
    return patas(p, i=dict(dy=-2.0 * k, alza=1.5 * salto), d=dict(dy=-1.0 * k, alza=1.5 * salto), ti=pierna, td=pierna)


if __name__ == "__main__":  # comprobaciones rápidas fuera de Blender
    for n, (f, dur, ciclo) in ACCIONES.items():
        a, b = f(0.0), f(dur)
        if ciclo:  # el bucle cierra: el último fotograma es el primero
            err = max(float(np.abs(np.asarray(a[h][c]) - np.asarray(b[h][c])).max()) for h in a for c in a[h])
            assert err < 0.05, (n, err)
    print(len(ACCIONES), "acciones ok")
