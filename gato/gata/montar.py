"""Monta gata.blend desde origen_cat.blend (Jonas Dichelle, CC-BY 3.0): pelaje carey (pelaje.png, de pelaje.py) en la
piel y en el pelo, pelo más largo y esponjoso, sin el suelo ni el HDRI viejos, luces de estudio y cámara ortográfica
«Cam» para los sprites, en Cycles.   blender -b gato/gata/origen_cat.blend -P gato/gata/montar.py
"""
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

AQUI = Path(__file__).resolve().parent
sc = bpy.context.scene
cat = bpy.data.objects["Cat"]

# pelaje: la imagen «Untitled» la usan la piel y el pelo (el pelo coge el color de la piel bajo su raíz)
img = bpy.data.images.load(str(AQUI / "pelaje.png"))
for mat in bpy.data.materials:
    if mat.use_nodes:
        for nd in mat.node_tree.nodes:
            if nd.type == "TEX_IMAGE" and nd.image and nd.image.name.startswith("Untitled"):
                nd.image = img
                print("PELAJE en", mat.name, nd.name)

# las puntas del pelo iban a un gris claro fijo (la gata original era casi blanca): que sean su mismo color, algo más
# claro, y el brillo especular más flojo, que lavaba el gris pardo
nt = bpy.data.materials["hair"].node_tree
hs = next(nd for nd in nt.nodes if nd.type == "HUE_SAT")
tex = next(nd for nd in nt.nodes if nd.type == "TEX_IMAGE")
nt.links.new(tex.outputs["Color"], hs.inputs["Color"])
hs.inputs["Saturation"].default_value, hs.inputs["Value"].default_value = 1.0, 1.15
brillo = next(nd for nd in nt.nodes if nd.type == "BSDF_HAIR" and nd.component == "Reflection")
brillo.inputs["Color"].default_value = (0.3, 0.28, 0.26, 1)

# pelo: algo más largo y esponjoso que el original, sin simulación (los sprites salen igual en cada render)
for ps in cat.particle_systems:
    st = ps.settings
    if st.type == "HAIR" and ps.settings.count > 0:
        ps.use_hair_dynamics = False  # el pelo viene peinado (is_edited): hair_length no hace nada, lo corto eran
        st.child_length = 1.0         # los hijos, al 35 % de su guía; a la guía entera, pelo largo como la de referencia
        st.child_radius = 0.3         # hijos más abiertos alrededor de su guía: más volumen
        arma = next(m for m in cat.modifiers if m.type == "ARMATURE")
        arma.show_viewport = False                     # raíces en reposo (sin la pose de la acción)
        ev = cat.evaluated_get(bpy.context.evaluated_depsgraph_get())
        epm = next(m for m in ev.modifiers if m.type == "PARTICLE_SYSTEM" and m.particle_system.name == ps.name)
        raiz = [ep.hair_keys[0].co_object(ev, epm, ep).copy() for ep in epm.particle_system.particles]
        arma.show_viewport = True
        for p, ro in zip(ps.particles, raiz):  # las guías, ×1.5 desde la raíz: pelo semilargo, como la gata de verdad;
            cuello = min(max((ro.y + 3.75) / 0.35, 0), 1) * min(max((-1.6 - ro.y) / 0.4, 0), 1) * (ro.z > 1.2)
            estira = 1.5 + 0.8 * cuello                 # y ×2.3 en el cuello y la nuca: la gola y la melena de la foto
            r = p.hair_keys[0].co_local.copy()
            hacia_dentro = (p.hair_keys[-1].co_local - r).normalized().z < -0.3  # z del espacio del pelo ≈ normal
            for q in p.hair_keys[1:]:
                o = (q.co_local - r) * estira
                if hacia_dentro:  # 16 guías peinadas hacia dentro de la cabeza: sus hijos se enterraban (calva en la sien)
                    o.z = -o.z
                q.co_local = r + o
        st.roughness_1, st.roughness_1_size = 0.1, 1.0   # rizo suave de cada pelo
        st.roughness_endpoint = 0.04
        st.clump_factor = 0.15                              # mechones
        print("PELO", ps.name, st.count, "guías estiradas ×1.5, hijos a largo completo")

# cara de la foto de la gata, no de rata: cabeza más grande y ancha, hocico corto, ojos grandes y abiertos con la pupila
# redonda, y pelo corto en la cara (el largo le colgaba del hocico como una barba). Head y las dos orejas giran sobre el
# mismo punto (la nuca): escalados a la vez, la cabeza crece entera, ojos incluidos; ninguna acción anima su escala,
# así que vale para todas.
pb = bpy.data.objects["Armature"].pose.bones
for nombre, esc in (("Head", (1.55, 1.35, 1.35)), ("Ear_connector", (1.35,) * 3), ("Ear_connector.001", (1.35,) * 3),
                    ("Nose", (1.1, 0.65, 1.0)), ("Mouth", (1.1, 0.7, 1.0))):
    pb[nombre].scale = esc
mw = cat.matrix_world
V = np.array([mw @ v.co for v in cat.data.vertices])
for sx in (1, -1):  # párpados abiertos: lo que rodea cada ojo se aparta de él (más en vertical), en el plano de la cara
    c = np.array((0.375 * sx, -4.11, 3.06))
    d = V - c
    d[:, 1] = 0
    r = np.maximum(np.linalg.norm(d, axis=1), 1e-6)
    f = np.clip(1 - (r - 0.1) / 0.45, 0, 1) * (r > 0.08) * (np.abs(V[:, 1] - c[1]) < 0.45)
    V = V + d / r[:, None] * np.array((0.6, 0, 1.0)) * (0.1 * f)[:, None]
# de perfil (foto con el contorno) la nariz y la barbilla quedan bastante más abajo de los ojos: la cara por debajo de
# ellos, ×1.5 hacia abajo (se apaga hacia el cuello)
frente = np.clip((-3.3 - V[:, 1]) / 0.4, 0, 1)
bajo = V[:, 2] < 3.06
V[bajo, 2] = 3.06 - (3.06 - V[bajo, 2]) * (1 + 0.5 * frente[bajo])
parpados = cat.shape_key_add(name="parpados", from_mix=False)  # como forma: la malla ya tiene «Basis» y mover v.co
for k, q in zip(parpados.data, V):                              # no llegaba al render
    k.co = mw.inverted() @ Vector(q)
parpados.value = 1.0
largo = cat.vertex_groups.new(name="largo")  # largo del pelo: 1 en el cuerpo, 0.35 en la cara
for i, q in enumerate(V):
    largo.add([i], float(1 - 0.65 * min(max((-3.4 - q[1]) / 0.6, 0), 1)), "REPLACE")
cat.particle_systems[0].vertex_group_length = "largo"
ojo = bpy.data.images.load(str(AQUI / "ojo.png"))
for nombre in ("Sphere", "Sphere.001"):
    o = bpy.data.objects[nombre]
    o.scale = (0.17 * 1.45,) * 3
nt = bpy.data.objects["Sphere"].active_material.node_tree  # (los dos ojos comparten material)
tx = next(nd for nd in nt.nodes if nd.type == "TEX_IMAGE")
tx.image = ojo
nt.links.new(tx.outputs["Color"], next(nd for nd in nt.nodes if nd.type == "GROUP").inputs["Color"])  # sin sus curvas (volvían rosa el iris)

# fuera la escena vieja
for nombre in ("Plane", "Camera", "Empty"):
    if nombre in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[nombre])
w = sc.world
w.use_nodes = True
nt = w.node_tree
nt.nodes.clear()
bg = nt.nodes.new("ShaderNodeBackground")
bg.inputs[0].default_value = (0.55, 0.57, 0.62, 1)
bg.inputs[1].default_value = 0.2
nt.links.new(bg.outputs[0], nt.nodes.new("ShaderNodeOutputWorld").inputs[0])


def luz(nombre, tam, energia, pos, color=(1, 1, 1)):
    l = bpy.data.lights.new(nombre, "AREA")
    l.size, l.energy, l.color = tam, energia, color
    o = bpy.data.objects.new(nombre, l)
    sc.collection.objects.link(o)
    o.location = pos
    o.rotation_euler = (-o.location).to_track_quat("-Z", "Y").to_euler()  # apunta al gato (centro ≈ origen)
    return o


luz("Clave", 8, 2500, (-9, -12, 12), (1.0, 0.96, 0.9))   # arriba a la izquierda, por delante
luz("Relleno", 10, 700, (12, -8, 3), (0.85, 0.9, 1.0))
luz("Contra", 6, 1800, (2, 14, 10))                       # contraluz: ilumina el borde del pelo

cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type, cam.data.ortho_scale = "ORTHO", 15  # andar y correr van en el sitio: cabe todo en 15

sc.render.engine = "CYCLES"
sc.cycles.device, sc.cycles.samples, sc.cycles.use_denoising = "CPU", 40, True
sc.render.film_transparent = True
sc.render.image_settings.media_type = "IMAGE"
sc.render.image_settings.file_format, sc.render.image_settings.color_mode = "PNG", "RGBA"
sc.render.resolution_x = sc.render.resolution_y = 400
sc.render.resolution_percentage = 100
sc.view_settings.view_transform = "Standard"  # el Blender de Fedora no carga su config OCIO: no hay AgX ni Filmic
bpy.ops.wm.save_as_mainfile(filepath=str(AQUI / "gata.blend"), compress=True)
print("GUARDADO gata.blend")
