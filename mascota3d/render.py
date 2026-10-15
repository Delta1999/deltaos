"""Renderiza la vuelta del mapache (malla de modelo.py) con Blender headless, en dos pasadas por vista.

    blender -b --python mascota3d/render.py -- <mapache.ply> <carpeta> [n_vistas]

tono_XX.png: el pelaje plano (sin luz). luz_XX.png: blanco con luz de estudio, sombras y cavidades.
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ply, salida, *resto = sys.argv[sys.argv.index("--") + 1:]
VISTAS = int(resto[0]) if resto else 12
salida = Path(salida)
salida.mkdir(parents=True, exist_ok=True)
CENTRO, ESCALA, PX = Vector((3.0, 0, 23.0)), 60, 384  # encuadre fijo: 60 filas en 384 px

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.ply_import(filepath=ply)
ob = bpy.context.object
bpy.ops.object.shade_smooth()

sc = bpy.context.scene
try:
    sc.render.engine = "BLENDER_WORKBENCH"
except TypeError as e:
    raise SystemExit(f"Sin Workbench: {e}")
sc.render.film_transparent = True
sc.render.resolution_x = sc.render.resolution_y = PX
sc.render.image_settings.color_mode = "RGBA"
sh = sc.display.shading
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type, cam.data.ortho_scale, cam.data.clip_end = "ORTHO", ESCALA, 1000
tipos = [i.identifier for i in sh.bl_rna.properties["color_type"].enum_items]

for i in range(VISTAS):
    a = 2 * math.pi * i / VISTAS  # 0 = de frente
    d = Vector((math.sin(a), -math.cos(a), 0.12)).normalized()
    cam.location = CENTRO + d * 200
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sh.light, sh.color_type = "FLAT", "VERTEX" if "VERTEX" in tipos else "ATTRIBUTE"
    sh.show_shadows = sh.show_cavity = False
    sc.render.filepath = str(salida / f"tono_{i:02d}.png")
    bpy.ops.render.render(write_still=True)
    sh.light, sh.color_type, sh.single_color = "STUDIO", "SINGLE", (1, 1, 1)
    sh.show_shadows = sh.show_cavity = True
    sc.render.filepath = str(salida / f"luz_{i:02d}.png")
    bpy.ops.render.render(write_still=True)
