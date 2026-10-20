"""Saca de origen_cat.blend la malla de la gata en reposo (vértices, normales, triángulos con UV) a malla_uv.npz,
para pintar su pelaje con pelaje.py.   blender -b gato/gata/origen_cat.blend -P gato/gata/exportar_malla.py"""
from pathlib import Path

import bpy
import numpy as np

AQUI = Path(__file__).resolve().parent
cat, ao = bpy.data.objects["Cat"], bpy.data.objects["Armature"]
ao.data.pose_position = "REST"
for m in cat.modifiers:
    if m.type == "PARTICLE_SYSTEM":
        m.show_viewport = False
bpy.context.view_layer.update()
me = cat.data
me.calc_loop_triangles()
v = np.array([cat.matrix_world @ x.co for x in me.vertices], np.float32)
n = np.array([(cat.matrix_world.to_3x3() @ x.normal).normalized() for x in me.vertices], np.float32)
uv = me.uv_layers.active.data
tri = np.array([t.vertices[:] for t in me.loop_triangles], np.int32)
tuv = np.array([[uv[l].uv[:] for l in t.loops] for t in me.loop_triangles], np.float32)
huesos = {b.name: tuple(ao.matrix_world @ b.head_local) for b in ao.data.bones}
np.savez_compressed(AQUI / "malla_uv.npz", v=v, n=n, tri=tri, tuv=tuv, hn=np.array(list(huesos)),
                    hp=np.array(list(huesos.values()), np.float32), uvnombre=me.uv_layers.active.name)
print("MALLA", len(v), "vértices", len(tri), "triángulos", "uv", me.uv_layers.active.name, v.min(0), v.max(0))
for o in bpy.data.objects:
    print("MW", o.name, tuple(round(x, 3) for x in o.matrix_world.to_translation()), tuple(round(x, 3) for x in o.matrix_world.to_scale()))
