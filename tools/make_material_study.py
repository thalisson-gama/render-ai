"""Estudo de material: um banheiro generico para julgar acabamento.

NAO E O PROJETO DO CLIENTE. A geometria aqui e inventada e serve so de
suporte para avaliar como os materiais reais se comportam sob luz. O banheiro
de verdade so entra quando a geometria for exportada do SketchUp.

Ambiente: 1,80 x 2,60 m, pe-direito 2,55 m. Bancada e painel em quartzito,
paredes laterais em revestimento ripado, piso em porcelanato, espelho sobre a
bancada e iluminacao artificial em 4000K, que foi o que a arquiteta indicou.

    blender -b -P tools/make_material_study.py -- projects/estudo-material/source
"""

import json
import os
import sys

import bpy

W, D, H = 1.80, 2.60, 2.55
WALL = 0.10


def mat(name, color=(0.8, 0.8, 0.8), roughness=0.6):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = roughness
    return m


def box(name, x0, y0, z0, x1, y1, z1, material):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.active_object
    o.name = name
    o.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    o.scale = (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(material)
    return o


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)

    piso = mat("PISO", (0.72, 0.70, 0.66), 0.25)
    ripado = mat("REVESTIMENTO", (0.80, 0.78, 0.74), 0.10)
    pedra = mat("PEDRA", (0.70, 0.62, 0.55), 0.12)
    forro = mat("FORRO", (0.92, 0.92, 0.91), 0.75)
    marcenaria = mat("MARCENARIA", (0.34, 0.21, 0.12), 0.40)
    metal = mat("METAL", (0.55, 0.56, 0.57), 0.20)
    louca = mat("LOUCA", (0.93, 0.93, 0.92), 0.15)
    espelho = mat("ESPELHO", (0.9, 0.9, 0.9), 0.02)
    vidro = mat("VIDRO", (0.92, 0.95, 0.94), 0.02)
    luz = mat("LUZ_LED_4000K", (1.0, 0.96, 0.9), 0.5)

    # casca
    box("Piso", 0, 0, -WALL, W, D, 0, piso)
    box("Forro", 0, 0, H, W, D, H + WALL, forro)
    box("Parede_Bancada", 0, -WALL, 0, W, 0, H, pedra)          # painel de pedra
    box("Parede_Esq", -WALL, 0, 0, 0, D, H, ripado)
    box("Parede_Dir", W, 0, 0, W + WALL, D, H, ripado)
    box("Parede_Fundo", 0, D, 0, W, D + WALL, H, ripado)

    # bancada em quartzito, com saia (espessura aparente de 4 cm)
    box("Bancada", 0.12, 0.0, 0.86, 1.68, 0.52, 0.90, pedra)
    box("Bancada_saia", 0.12, 0.50, 0.82, 1.68, 0.52, 0.86, pedra)

    # marcenaria suspensa
    box("Gabinete", 0.20, 0.03, 0.32, 1.60, 0.50, 0.86, marcenaria)
    box("Puxador", 0.28, 0.505, 0.74, 1.52, 0.525, 0.775, metal)

    # cuba de apoio e torneira de parede
    box("Cuba", 0.68, 0.10, 0.90, 1.12, 0.40, 0.99, louca)
    box("Cuba_interna", 0.71, 0.13, 0.905, 1.09, 0.37, 0.985, louca)
    box("Torneira_corpo", 0.875, 0.0, 1.16, 0.905, 0.04, 1.20, metal)
    box("Torneira_bica", 0.875, 0.04, 1.16, 0.905, 0.20, 1.19, metal)

    # espelho sobre a bancada, com moldura fina
    box("Espelho", 0.24, 0.008, 1.06, 1.56, 0.016, 2.12, espelho)
    box("Moldura_a", 0.225, 0.004, 1.045, 0.24, 0.018, 2.135, metal)
    box("Moldura_b", 1.56, 0.004, 1.045, 1.575, 0.018, 2.135, metal)
    box("Moldura_c", 0.225, 0.004, 1.045, 1.575, 0.018, 1.06, metal)
    box("Moldura_d", 0.225, 0.004, 2.12, 1.575, 0.018, 2.135, metal)

    # sanca de LED acima do espelho, principal fonte de luz
    box("LED_espelho", 0.26, 0.03, 2.17, 1.54, 0.13, 2.20, luz)
    box("Sanca", 0.20, 0.0, 2.20, 1.60, 0.16, 2.34, forro)

    # dois embutidos no forro
    for i, x in enumerate((0.60, 1.20)):
        box(f"Spot_{i}", x - 0.05, 1.55, H - 0.012, x + 0.05, 1.65, H, luz)
        box(f"Spot_aro_{i}", x - 0.065, 1.535, H - 0.02, x + 0.065, 1.665, H, metal)

    # box do chuveiro ao fundo, com vidro
    box("Soleira", 0, 1.90, 0.0, W, 1.94, 0.03, pedra)
    box("Vidro_box", 0.90, 1.915, 0.03, 0.905, 1.925, 2.05, vidro)
    box("Perfil_box", 0.895, 1.905, 0.03, 0.915, 1.935, 2.06, metal)
    box("Chuveiro_haste", 0.40, 2.55, 2.05, 0.44, 2.60, 2.09, metal)
    box("Chuveiro_prato", 0.28, 2.28, 2.02, 0.56, 2.56, 2.05, metal)

    # meia parede em pedra atras do vaso, como ela especificou
    box("Meia_parede", 1.42, 1.10, 0.0, W, 1.22, 1.10, pedra)
    box("Vaso_caixa", 1.44, 1.22, 0.0, 1.78, 1.60, 0.42, louca)
    box("Vaso_assento", 1.46, 1.24, 0.42, 1.76, 1.58, 0.45, louca)

    return {"objetos": len(bpy.data.objects), "materiais": [m.name for m in bpy.data.materials]}


def cameras_json():
    return {
        "gerado_por": "tools/make_material_study.py",
        "unidades": "metros",
        "cameras": [
            {
                "name": "Bancada 01", "slug": "bancada-01",
                "eye": [1.42, 2.32, 1.55], "target": [0.62, 0.30, 1.20],
                "up": [0.0, 0.0, 1.0],
                "fov_deg": 58.0, "fov_axis": "horizontal", "two_point": True,
            },
            {
                "name": "Geral 01", "slug": "geral-01",
                "eye": [0.30, 2.42, 1.62], "target": [1.30, 0.35, 1.15],
                "up": [0.0, 0.0, 1.0],
                "fov_deg": 64.0, "fov_axis": "horizontal", "two_point": True,
            },
        ],
    }


def main():
    argv = sys.argv
    out = argv[argv.index("--") + 1] if "--" in argv else "."
    os.makedirs(out, exist_ok=True)
    info = build()
    glb = os.path.join(out, "modelo.glb")
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=False)
    with open(os.path.join(out, "cameras.json"), "w", encoding="utf-8") as f:
        json.dump(cameras_json(), f, ensure_ascii=False, indent=2)
    print(f"[estudo] {info['objetos']} objetos")
    print(f"[estudo] materiais: {', '.join(info['materiais'])}")


if __name__ == "__main__":
    main()
