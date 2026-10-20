"""Hornea el gato de gato.blend para rig.py: malla + pesos + esqueleto → gato/gato.npz, y cada acción, ya con la IK
resuelta, fotograma a fotograma → gato/animaciones.npz (lo lee gato/poses.py).

    blender -b gato/gato.blend -P gato/blender/hornear.py    # tras retocar el .blend a mano

Cada fotograma va en la convención de rig.py, por hueso que deforma: r (rx, ry, rz) grados con giro Z·Y·X, t y s, sobre
la cabeza del hueso en reposo y dentro del padre; así mascota.py puede fundir unas poses con otras como con el mapache.
"""
from pathlib import Path

import bpy
import numpy as np

GATO = Path(__file__).resolve().parent.parent
ANCLAS = {"ojo_i": "cabeza", "ojo_d": "cabeza", "boca": "cabeza", "nariz": "cabeza", "coronilla": "cabeza",
          "oreja_i": "oreja_i", "oreja_d": "oreja_d", "mano_i": "mano_i", "mano_d": "mano_d", "pecho": "pecho",
          "cola": "cola6"}
K = 6  # pesos por vértice (con 4 se pierde la cabeza bajo la barbilla)


def deforman(ao):
    """Huesos que deforman, padres antes que hijos."""
    lista = []

    def baja(b):
        if b.use_deform:
            lista.append(b.name)
        for h in b.children:
            baja(h)
    for b in ao.data.bones:
        if b.parent is None:
            baja(b)
    return lista


def pesos(ob, huesos):
    grupo = {g.index: huesos.index(g.name) for g in ob.vertex_groups if g.name in huesos}
    n = len(ob.data.vertices)
    wi, w = np.zeros((n, K), np.int16), np.zeros((n, K), np.float32)
    for v in ob.data.vertices:
        gs = sorted(((g.weight, grupo[g.group]) for g in v.groups if g.group in grupo and g.weight > 0), reverse=True)[:K]
        if not gs:
            gs = [(1.0, 0)]
        tot = sum(p for p, _ in gs)
        for k, (p, i) in enumerate(gs):
            wi[v.index, k], w[v.index, k] = i, p / tot
    return wi, w


def a_pose(D, padres, pivotes):
    """Matrices de deformación del mundo (B×4×4) → (B×9) r, t, s locales a la manera de rig.py."""
    out = np.zeros((len(D), 9), np.float32)
    for i, p in enumerate(padres):
        L = D[i] if p < 0 else np.linalg.inv(D[p]) @ D[i]
        A = L[:3, :3]
        s = np.linalg.norm(A, axis=0)
        R = A / s
        out[i, 0] = np.degrees(np.arctan2(R[2, 1], R[2, 2]))
        out[i, 1] = np.degrees(-np.arcsin(np.clip(R[2, 0], -1, 1)))
        out[i, 2] = np.degrees(np.arctan2(R[1, 0], R[0, 0]))
        out[i, 3:6] = L[:3, 3] - (pivotes[i] - A @ pivotes[i])
        out[i, 6:] = s
    return out


def hornear(ao, anclas=ANCLAS):
    ob = next(o for o in bpy.data.objects if o.type == "MESH" and o.find_armature() == ao)
    huesos = deforman(ao)
    bones = ao.data.bones
    padres = np.array([huesos.index(bones[h].parent.name) if bones[h].parent else -1 for h in huesos])
    pivotes = np.array([bones[h].head_local for h in huesos], np.float64)
    reposo_inv = [np.linalg.inv(np.array(bones[h].matrix_local)) for h in huesos]
    wi, w = pesos(ob, huesos)
    d = dict(np.load(GATO / "malla.npz"))
    assert len(d["v"]) == len(ob.data.vertices)
    np.savez_compressed(GATO / "gato.npz", v=d["v"], f=d["f"], n=d["n"], g=d["g"], ao=d["ao"], wi=wi, w=w,
                        huesos=np.array(huesos), padres=padres, pivotes=pivotes.astype(np.float32),
                        anclas=d["anclas"], ancla_hueso=np.array([huesos.index(anclas[a]) for a in d["anclas"]]),
                        ancla_p=d["ancla_p"], centro=np.array([0.0, 26.0]))
    sc = bpy.context.scene
    fps = sc.render.fps
    out, meta = {}, []
    for act in sorted(bpy.data.actions, key=lambda a: a.name):
        ao.animation_data.action = act
        if ao.animation_data.action_slot is None and act.slots:
            ao.animation_data.action_slot = act.slots[0]
        n = int(act.frame_end)
        cuadros, falla = [], (0.0, "", 0)
        for fr in range(n + 1):
            sc.frame_set(fr)
            pb = ao.pose.bones
            D = [np.array(pb[h].matrix) @ reposo_inv[i] for i, h in enumerate(huesos)]
            cuadros.append(a_pose(D, padres, pivotes))
            falla = max([falla] + [((pb[a].tail - pb[b].head).length, a, fr) for s in "id"
                                   for a, b in ((f"antebrazo_{s}", f"ik_mano_{s}"), (f"canilla_{s}", f"ik_talon_{s}"))])
        if falla[0] > 0.3:  # la pata no llega a su objetivo: se ve flotar o resbalar
            print(f"  ⚠ {act.name}: {falla[1]} se queda a {falla[0] / 1.3:.1f} del objetivo IK en el fotograma {falla[2]}")
        c = np.array(cuadros)
        c[:, :, :3] = np.degrees(np.unwrap(np.radians(c[:, :, :3]), axis=0))  # sin saltos de 360° entre fotogramas
        out[act.name] = c
        meta.append((act.name, n / fps, act.use_cyclic))
        print(f"horneada {act.name}: {n + 1} fotogramas, {'en bucle' if act.use_cyclic else 'de una vez'}")
    np.savez_compressed(GATO / "animaciones.npz", **out, _nombres=np.array([m[0] for m in meta]),
                        _dur=np.array([m[1] for m in meta]), _ciclo=np.array([m[2] for m in meta]),
                        _fps=np.array(fps), _huesos=np.array(huesos))
    sc.frame_set(0)
    print("hornear: listo,", len(huesos), "huesos,", len(out), "acciones")


if __name__ == "__main__":
    hornear(bpy.data.objects["Esqueleto"])
