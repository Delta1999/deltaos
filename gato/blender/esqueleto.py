"""Esqueleto del gato, en unidades base de gato/modelo.py (z arriba, mirando a -Y): lo montan montar.py en Blender y
acciones.py para saber dónde caen hombros y caderas al posar el cuerpo."""
import numpy as np

# (nombre, padre, cabeza, cola, deforma) en unidades base; el gato de pie mirando a -Y
HUESOS = [("raiz", None, (0, 10.5, 12.5), (0, 5.0, 13.2), True),
          ("lomo", "raiz", (0, 5.0, 13.2), (0, -1.0, 13.8), True),
          ("pecho", "lomo", (0, -1.0, 13.8), (0, -7.0, 14.5), True),
          ("cuello", "pecho", (0, -7.0, 14.5), (0, -10.5, 18.5), True),
          ("cabeza", "cuello", (0, -10.5, 18.5), (0, -16.5, 21.5), True)]
for s, k in (("i", -1), ("d", 1)):
    HUESOS += [(f"oreja_{s}", "cabeza", (k * 3.5, -12.6, 25.4), (k * 4.6, -12.4, 29.8), True),
               (f"hombro_{s}", "pecho", (k * 2.6, -4.5, 15.0), (k * 3.4, -7.0, 10.5), True),
               (f"brazo_{s}", f"hombro_{s}", (k * 3.4, -7.0, 10.5), (k * 3.4, -6.4, 5.8), True),
               (f"antebrazo_{s}", f"brazo_{s}", (k * 3.4, -6.4, 5.8), (k * 3.4, -7.4, 1.4), True),
               (f"mano_{s}", f"antebrazo_{s}", (k * 3.4, -7.4, 1.4), (k * 3.4, -9.6, 1.0), True),
               (f"muslo_{s}", "raiz", (k * 4.0, 8.8, 11.0), (k * 4.0, 6.6, 6.2), True),
               (f"canilla_{s}", f"muslo_{s}", (k * 4.0, 6.6, 6.2), (k * 3.7, 11.0, 3.4), True),
               (f"tarso_{s}", f"canilla_{s}", (k * 3.7, 11.0, 3.4), (k * 3.6, 10.6, 1.3), True),
               (f"pie_{s}", f"tarso_{s}", (k * 3.6, 10.6, 1.3), (k * 3.6, 8.2, 0.9), True),
               # controles: muñeca, corvejón y pie (sueltos, en el mundo) y polos de codo y rodilla
               (f"ik_mano_{s}", None, (k * 3.4, -7.4, 1.4), (k * 3.4, -9.6, 1.0), False),
               (f"ik_talon_{s}", None, (k * 3.7, 11.0, 3.4), (k * 3.7, 11.0, 5.4), False),
               (f"ik_pie_{s}", None, (k * 3.6, 10.6, 1.3), (k * 3.6, 8.2, 0.9), False),
               (f"polo_codo_{s}", "pecho", (k * 3.4, 4.0, 5.8), (k * 3.4, 4.0, 7.8), False),
               (f"polo_rodilla_{s}", "raiz", (k * 4.0, -4.0, 6.2), (k * 4.0, -4.0, 8.2), False)]
COLA = np.array([(0, 13.0, 15.5), (0, 15.6, 19.5), (0, 16.4, 25.0), (0, 15.8, 30.5), (0, 14.0, 35.0)])
_l = np.r_[0, np.cumsum(np.linalg.norm(np.diff(COLA, axis=0), axis=1))]
_p = np.array([np.interp(np.linspace(0, _l[-1], 7), _l, COLA[:, j]) for j in range(3)]).T  # 6 vértebras iguales
HUESOS += [(f"cola{k + 1}", "raiz" if k == 0 else f"cola{k}", tuple(_p[k]), tuple(_p[k + 1]), True) for k in range(6)]
PADRE = {h[0]: h[1] for h in HUESOS}
CABEZA = {h[0]: np.array(h[2], float) for h in HUESOS}
COLA_H = {h[0]: np.array(h[3], float) for h in HUESOS}
