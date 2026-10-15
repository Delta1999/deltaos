"""Repertorio de animaciones del mapache: cada una es t (s) → pose para rig.Mapache.pintar.

ANIM[nombre] = (función, duración); duración None = en bucle. Ángulos en grados, alturas en filas del sprite.
Huesos: raiz, cabeza, oreja_i/d, brazo_i/d, pata_i/d, cola1..4 (_i = x < 0, izquierda en pantalla de frente).
Los brazos son cortos (chibi): «arriba» llega a la altura de la cara, no por encima de las orejas.
"""
from math import cos, exp, pi, sin

ANIM = {}


def anim(dur=None):
    def reg(f):
        ANIM[f.__name__] = (f, dur)
        return f
    return reg


def junta(*partes):
    pose = {}
    for p in partes:
        for h, q in p.items():
            pose.setdefault(h, {}).update(q)
    return pose


def sg(lado):
    return 1 if lado == "d" else -1


def brazo(lado, alza=0, abre=0, gira=0):
    """alza: hacia delante y arriba (0 = colgando sobre la barriga); abre: hacia fuera; gira: muñeca."""
    return {f"brazo_{lado}": {"r": (-alza, -abre * sg(lado), gira * sg(lado))}}


def brazos(alza=0, abre=0, gira=0, alterna=0):
    return junta(brazo("d", alza + alterna, abre, gira), brazo("i", alza - alterna, abre, gira))


def pata(lado, adelante=0, abre=0):
    return {f"pata_{lado}": {"r": (-adelante, -abre * sg(lado), 0)}}


def patas(adelante=0, abre=0, alterna=0):
    return junta(pata("d", adelante + alterna, abre), pata("i", adelante - alterna, abre))


def orejas(fuera=0, atras=0, tic_d=0, tic_i=0):
    """fuera: se abren a los lados; atras: gachas (negativo = de punta, alerta)."""
    return {f"oreja_{s}": {"r": (-atras, (fuera + tic) * sg(s), 0)} for s, tic in (("d", tic_d), ("i", tic_i))}


def cabeza(asiente=0, ladea=0, gira=0):
    """asiente: mira abajo; ladea: inclina hacia la derecha de la pantalla; gira: mira hacia la derecha."""
    return {"cabeza": {"r": (asiente, ladea, gira)}}


def cola(t, onda=8, frec=1.2, curva=0, enrosca=0):
    """onda: meneo a los lados que recorre la cola; curva: hacia delante (+) o atrás (-); enrosca: hacia un lado."""
    return {f"cola{k}": {"r": (curva / 4, 0, enrosca / 4 + onda * sin(t * frec * 2 * pi - k * 0.7))} for k in range(1, 5)}


def cuerpo(alto=1.0, sube=0, inclina=0, ladea=0, gira=0, x=0, y=0):
    """alto < 1 = aplastado, > 1 = estirado (conserva volumen y los pies en el suelo); inclina: hacia delante."""
    a = 1 / alto ** 0.5
    return {"raiz": {"s": (a, a, alto), "t": (x, y, 6.0 * (alto - 1) + sube), "r": (inclina, ladea, gira)}}


def env(t, dur):
    """0 → 1 → 0 a lo largo de la duración."""
    return sin(pi * min(max(t / dur, 0), 1))


# ---- en bucle ----
@anim()
def reposo(t):
    tic = 18 * ((t % 4.3) < 0.18)
    return junta(cuerpo(1 + 0.012 * sin(t * 2.2)), cabeza(2 * sin(t * 1.1)), orejas(tic_d=tic), cola(t, 6))


@anim()
def anda(t):
    f = t * 1.6 * 2 * pi
    return junta(cuerpo(sube=0.8 * abs(cos(f)), ladea=3 * sin(f)), patas(alterna=28 * sin(f)),
                 brazos(alterna=-18 * sin(f), abre=8), cabeza(-2, -2 * sin(f)), orejas(4), cola(t, 10, 1.6))


@anim()
def corre(t):
    f = t * 2.8 * 2 * pi
    return junta(cuerpo(sube=1.6 * abs(cos(f)), inclina=14), patas(alterna=45 * sin(f)),
                 brazos(20, 10, alterna=-40 * sin(f)), cabeza(-10), orejas(10, 25), cola(t, 6, 2.8, curva=-20))


@anim()
def sentado(t):
    return junta(cuerpo(sube=-1.2), patas(80, 6, alterna=14 * sin(t * 2.4)), brazos(10, -8),
                 cabeza(4, 0, 15 * sin(t * 0.5)), orejas(6), cola(t, 5, 0.7))


@anim()
def escucha(t):
    return junta(cuerpo(inclina=4), cabeza(-4, 12 + 2 * sin(t * 1.5)), orejas(-10, -15), brazo("d", 150, 35),
                 brazo("i", 5), cola(t, 4, 0.8))


@anim()
def habla(t):
    return junta(cuerpo(1 + 0.02 * sin(t * 6)), brazo("d", 40 + 30 * sin(t * 5), 20), brazo("i", 40 + 30 * sin(t * 5 + 2), 20),
                 cabeza(4 * sin(t * 6), 4 * sin(t * 2)), orejas(6 * sin(t * 3)), cola(t, 8))


@anim()
def trabaja(t):
    return junta(cuerpo(inclina=6), brazos(55, -10, alterna=6 * sin(t * 16)), cabeza(12, 2 * sin(t * 0.7)),
                 orejas(0, 5), cola(t, 3))


@anim()
def permiso(t):
    return junta(cuerpo(sube=0.6 * abs(sin(t * 8))), brazos(165, 25, alterna=12 * sin(t * 8)), cabeza(-6),
                 orejas(-5, -10), cola(t, 12, 2))


@anim()
def agobio(t):
    return junta(cuerpo(0.97, gira=3 * sin(t * 40), x=0.3 * sin(t * 37)), brazos(150, -15), cabeza(6),
                 orejas(35, 20), cola(t, 2, 3, curva=20))


@anim()
def calor(t):
    return junta(cuerpo(0.96), brazo("d", 120 + 15 * sin(t * 10), 10, 20 * sin(t * 10)), brazo("i", 5),
                 cabeza(-6, 6), orejas(25, 5), cola(t, 3, 0.6))


@anim()
def duerme(t):
    return junta(cuerpo(0.94 + 0.025 * sin(t * 1.3), sube=-1.2, inclina=6), patas(80, 8), brazos(25, -18),
                 cabeza(12 + 2 * sin(t * 1.3), 14), orejas(28, 18), cola(t, 0, curva=30, enrosca=-160))


@anim()
def tumbado(t):
    """Tumbado como una esfinge (en la barra de título de una ventana): barriga abajo y la cara hacia ti."""
    return junta({"raiz": {"r": (80, 0, 0), "t": (0, 6, 3), "s": (1, 1, 1 + 0.025 * sin(t * 1.3))}},
                 cabeza(-75 + 2 * sin(t * 1.3), 10), orejas(20, 10), brazos(-10, 5), patas(-60), cola(t, 3, 0.4, curva=-20))


@anim()
def cae(t):
    return junta(cuerpo(inclina=-10), brazos(150, 50, alterna=20 * sin(t * 18)), patas(alterna=30 * sin(t * 14)),
                 cabeza(-8), orejas(30, -20), cola(t, 15, 3, curva=-40))


@anim()
def arrastre(t):
    """Colgando de la mano del ratón: se balancea con brazos y patas sueltos."""
    return junta(cuerpo(1.06, ladea=6 * sin(t * 2)), brazos(-10, 10), patas(alterna=15 * sin(t * 3)),
                 cabeza(6, -4 * sin(t * 2)), orejas(15, 10), cola(t, 4, 1, curva=15))


@anim()
def celebra(t):
    h = abs(sin(t * pi * 2))
    return junta(cuerpo(1 + 0.08 * (h - 0.5), sube=5 * h), brazos(160, 30 + 15 * sin(t * 12)), patas(alterna=-10 * h),
                 cabeza(-6, 8 * sin(t * 4)), orejas(0, -15), cola(t, 25, 3))


@anim()
def baila(t):
    f = t * 4
    return junta(cuerpo(ladea=8 * sin(f), gira=12 * sin(t * 2), sube=0.8 * abs(sin(f))),
                 brazo("d", 90 + 60 * sin(f), 40), brazo("i", 90 - 60 * sin(f), 40), cabeza(0, -10 * sin(f)),
                 patas(alterna=15 * sin(f)), orejas(8 * sin(f)), cola(t, 20, 1.3))


@anim()
def saluda(t):
    return junta(brazo("d", 150, 40 + 25 * sin(t * 9)), brazo("i", 5), cabeza(-4, 8), orejas(-4, -8), cola(t, 12, 1.6))


@anim()
def rasca(t):
    return junta(brazo("d", 140, 10 + 8 * sin(t * 20)), cabeza(4, -14), orejas(0, 0, tic_d=10), cola(t, 4))


@anim()
def curioso(t):
    """Algo en la pantalla le llama la atención: se asoma y ladea la cabeza."""
    return junta(cuerpo(inclina=12), cabeza(6, 15 * sin(t * 1.2)), orejas(-5, -15), brazos(20, -10), cola(t, 10, 0.8))


@anim()
def alto(t):
    """Patrulla: «¡alto!» con la mano por delante y la porra en alto."""
    return junta(cuerpo(inclina=-6), brazo("d", 90, 10), brazo("i", 130, 15), cabeza(-4), orejas(-4, -10), cola(t, 4))


@anim()
def come(t):
    sorbo = env(t % 3, 1.0)
    return junta(brazo("d", 105 + 15 * sorbo, -35), brazo("i", 30, -20), cabeza(-6 * sorbo), orejas(4), cola(t, 5))


@anim()
def senala(t):
    return junta(brazo("d", 95, 55 + 3 * sin(t * 3)), brazo("i", 5), cabeza(-2, 5, 25), orejas(-4, -8), cola(t, 6))


@anim()
def tiembla(t):
    return junta(cuerpo(0.97, x=0.3 * sin(t * 45)), brazos(35, -20), cabeza(4), orejas(10, 15), cola(t, 0, curva=25, enrosca=-90))


@anim()
def mira(t, gira=0, asiente=0):
    """Sigue algo con la cabeza (el ratón): mascota.py le pasa hacia dónde."""
    return junta(cuerpo(1 + 0.012 * sin(t * 2.2)), cabeza(asiente, gira * 0.15, gira), orejas(-3, -6), cola(t, 6))


# ---- de una vez ----
@anim(0.25)
def salto_prepara(t):
    k = min(t / 0.25, 1)
    return junta(cuerpo(1 - 0.18 * k, inclina=10 * k), brazos(-30 * k), orejas(0, 10 * k), cola(t, 4))


@anim()
def salto_sube(t):
    return junta(cuerpo(1.12), brazos(150, 20), patas(-25), orejas(0, 20), cola(t, 4, 2, curva=-25))


@anim()
def salto_cae(t):
    return junta(brazos(110, 60, alterna=10 * sin(t * 14)), patas(25, 10), orejas(25, -10), cola(t, 6, 2, curva=25))


@anim(0.35)
def aterriza(t):
    k = env(t, 0.35)
    return junta(cuerpo(1 - 0.22 * k), brazos(0, 30 * k), orejas(30 * k), cola(t, 4))


@anim(0.7)
def aplastado(t):
    """Golpe fuerte contra el suelo: se aplasta y rebota como gelatina."""
    return junta(cuerpo(1 - 0.35 * exp(-t * 6) * cos(t * 20)), brazos(0, 40 * exp(-t * 5)), orejas(35 * exp(-t * 4)), cola(t, 6, 2))


@anim(0.8)
def sorpresa(t):
    k = env(t, 0.8)
    return junta(cuerpo(1 + 0.1 * k, sube=3 * env(t, 0.4), y=1.5 * k), brazos(120 * k, 50 * k), orejas(0, -20 * k),
                 cabeza(-8 * k), cola(t, 6, 2, curva=-30 * k))


@anim(2.5)
def estira(t):
    k = env(t, 2.5)
    return junta(cuerpo(1 + 0.08 * k), brazos(170 * k, 15 * k), cabeza(-15 * k), orejas(0, 20 * k), cola(t, 4))


@anim(2.0)
def bosteza(t):
    k = env(t, 2.0)
    return junta(cuerpo(1 + 0.04 * k, inclina=-6 * k), brazos(60 * k, 30 * k), cabeza(-20 * k), orejas(15 * k, 10 * k), cola(t, 3))
