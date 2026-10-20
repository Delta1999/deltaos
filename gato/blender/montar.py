"""Monta el gato en Blender: malla de gato/malla.npz (modelo.py), esqueleto de gato con IK en las patas, pesos
automáticos (difusión de calor) y las animaciones de acciones.py como acciones con curvas Bézier. Guarda gato/gato.blend
(se puede abrir y retocar a mano) y lo hornea con hornear.py a gato/gato.npz + gato/animaciones.npz.

    blender -b --factory-startup -P gato/blender/montar.py     # rehace gato.blend desde cero (pisa los retoques) y hornea
    blender -b gato/gato.blend -P gato/blender/hornear.py       # solo hornea, p. ej. tras retocar el .blend a mano

Convención de las poses (la de mascota3d/rig.py): por hueso {"r": (rx, ry, rz) grados, "t": (dx, dy, dz), "s": …},
giro Z·Y·X en los ejes del mundo alrededor de la cabeza del hueso, dentro del padre; z arriba y el gato mira a -Y.
Los objetivos IK (ik_*) son huesos sueltos: su "t" es cuánto se mueve su cabeza en el mundo.
"""
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

AQUI = Path(__file__).resolve().parent
GATO = AQUI.parent
sys.path.insert(0, str(AQUI))
import acciones  # noqa: E402
import esqueleto as esq  # noqa: E402
import hornear  # noqa: E402

E = acciones.E      # unidades base de modelo.py → celdas
FPS = acciones.FPS
PASO = 2            # una clave cada 2 fotogramas: Bézier entre medias

HUESOS = esq.HUESOS


def limpiar():
    for c in (bpy.data.objects, bpy.data.meshes, bpy.data.armatures, bpy.data.actions, bpy.data.materials):
        for x in list(c):
            c.remove(x)


def malla():
    d = np.load(GATO / "malla.npz")
    me = bpy.data.meshes.new("Gato")
    me.from_pydata(d["v"].tolist(), [], d["f"].tolist())
    me.shade_smooth()
    col = me.color_attributes.new("pelaje", "BYTE_COLOR", "POINT")
    col.data.foreach_set("color_srgb", np.c_[d["g"] / 255, np.ones(len(d["g"]))].ravel())
    mat = bpy.data.materials.new("Pelaje")  # para verlo con sus colores en Blender
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    attr = mat.node_tree.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "pelaje"
    mat.node_tree.links.new(attr.outputs[0], bsdf.inputs[0])
    me.materials.append(mat)
    ob = bpy.data.objects.new("Gato", me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def esqueleto():
    arm = bpy.data.armatures.new("Esqueleto")
    ao = bpy.data.objects.new("Esqueleto", arm)
    bpy.context.scene.collection.objects.link(ao)
    bpy.context.view_layer.objects.active = ao
    bpy.ops.object.mode_set(mode="EDIT")
    for n, padre, a, b, deforma in HUESOS:
        eb = arm.edit_bones.new(n)
        eb.head, eb.tail, eb.roll, eb.use_deform = Vector(a) * E, Vector(b) * E, 0, deforma
        if padre:
            eb.parent = arm.edit_bones[padre]
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.display_type = "STICK"
    ao.show_in_front = True
    for pb in ao.pose.bones:
        pb.rotation_mode = "XYZ"
    return ao


def restricciones(ao):
    pb = ao.pose.bones
    for s in "id":
        ik = [pb[f"antebrazo_{s}"].constraints.new("IK"), pb[f"canilla_{s}"].constraints.new("IK")]
        for c, objetivo, polo in zip(ik, (f"ik_mano_{s}", f"ik_talon_{s}"), (f"polo_codo_{s}", f"polo_rodilla_{s}")):
            c.target, c.subtarget, c.chain_count = ao, objetivo, 2
            c.pole_target, c.pole_subtarget = ao, polo
        c = pb[f"tarso_{s}"].constraints.new("DAMPED_TRACK")  # el metatarso apunta al pie
        c.target, c.subtarget = ao, f"ik_pie_{s}"
        for h in ("mano", "pie"):  # la mano y el pie copian el giro de su control (apoyados planos en el suelo)
            c = pb[f"{h}_{s}"].constraints.new("COPY_ROTATION")
            c.target, c.subtarget = ao, f"ik_{h}_{s}"
    afinar_polos(ao, [c for p in pb for c in p.constraints if c.type == "IK"])


def afinar_polos(ao, iks):
    """El ángulo de polo con el que, en reposo, la IK no mueve la pata (depende del giro de cada hueso)."""
    for c in iks:
        dueño = next(p for p in ao.pose.bones if c in p.constraints.values())
        errores = []
        for ang in range(-180, 180, 5):
            c.pole_angle = np.radians(ang)
            bpy.context.view_layer.update()
            errores.append((sum((h.tail - h.bone.tail_local).length for h in (dueño, dueño.parent)), ang))
        err, ang = min(errores)
        c.pole_angle = np.radians(ang)
        print(f"polo {dueño.name}: {ang}° (se mueve {err:.3f})")


def pesar(ob, ao):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    ao.select_set(True)
    bpy.context.view_layer.objects.active = ao
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    sin = sum(1 for v in ob.data.vertices if not v.groups)
    print("vértices sin peso:", sin)
    assert sin < 20, "los pesos automáticos han fallado"


def base(ao, nombre, d):
    """Pose en la convención de rig.py → (loc, euler, escala) del hueso en Blender."""
    rest = ao.data.bones[nombre].matrix_local
    p = rest.to_translation()
    R = Euler(np.radians(d.get("r", (0, 0, 0))), "XYZ").to_matrix() @ Matrix.Diagonal(d.get("s", (1, 1, 1)))
    L = Matrix.Translation(p + Vector(d.get("t", (0, 0, 0))) * E) @ R.to_4x4() @ Matrix.Translation(-p)
    return (rest.inverted() @ L @ rest).decompose()


def animar(ao, nombre, f, dur, ciclo):
    act = bpy.data.actions.new(nombre)
    act.use_fake_user = True
    ao.animation_data_create()
    ao.animation_data.action = act
    n = round(dur * FPS)
    act.use_frame_range, act.frame_start, act.frame_end, act.use_cyclic = True, 0, n, ciclo
    huesos = [h[0] for h in HUESOS if not h[0].startswith("polo")]
    previo = {}
    for fr in sorted(set(range(0, n + 1, PASO)) | {n}):
        pose = f(fr / FPS)
        for h in huesos:
            pb = ao.pose.bones[h]
            loc, q, esc = base(ao, h, pose.get(h, {}))
            pb.location, pb.scale = loc, esc
            pb.rotation_euler = q.to_euler("XYZ", previo.get(h, Euler()))  # sin saltos de 360°
            previo[h] = pb.rotation_euler.copy()
            for canal in ("location", "rotation_euler", "scale"):
                pb.keyframe_insert(canal, frame=fr, group=h)
    return act


if __name__ == "__main__":
    limpiar()
    sc = bpy.context.scene
    sc.render.fps, sc.frame_start = FPS, 0
    ob, ao = malla(), esqueleto()  # noqa: F811
    restricciones(ao)
    pesar(ob, ao)
    for nombre, (f, dur, ciclo) in acciones.ACCIONES.items():
        animar(ao, nombre, f, dur, ciclo)
    ao.animation_data.action = bpy.data.actions.get("reposo")
    bpy.ops.wm.save_as_mainfile(filepath=str(GATO / "gato.blend"))
    hornear.hornear(ao)
