"""Gera um interior sintetico e exporta GLB + cameras.json.

Serve para validar o pipeline inteiro sem depender do modelo da arquiteta.
Imita de proposito o que o SketchUp entrega:
  - geometria simples, sem UV cuidado
  - materiais nomeados pelo contrato (PISO, BANCADA, MARCENARIA...)
  - um material sem mapeamento, para provar que o relatorio acusa
  - cameras exportadas a parte, como no SketchUp de verdade

    blender -b -P tools/make_test_scene.py -- projects/teste-interior/source
"""

import json
import math
import os
import sys

import bpy

# Ambiente: 4,20 x 5,60 m, pe-direito 2,70 m.
# Janela na parede X=0 (oeste), que pega o sol das 16h em cheio.
W, D, H = 4.20, 5.60, 2.70
WALL = 0.15
WIN = {"y0": 1.10, "y1": 4.50, "z0": 0.90, "z1": 2.30}


def mat(name, color, roughness=0.6):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = roughness
    return m


def box(name, x0, y0, z0, x1, y1, z1, material):
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.active_object
    obj.name = name
    obj.location = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    obj.scale = (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    return obj


# Dois vocabularios. "contrato" e a convencao que o pipeline propoe.
# "arquiteta" imita como uma arquiteta de verdade nomeia material no SketchUp,
# que e do que a gente precisa para testar o reconhecimento automatico.
NOMES = {
    "contrato": {
        "piso": "PISO", "parede": "PAREDE", "forro": "FORRO",
        "marcenaria": "MARCENARIA", "bancada": "BANCADA",
        "esquadria": "ESQUADRIA", "vidro": "VIDRO", "sofa": "SOFA",
    },
    "arquiteta": {
        "piso": "Piso Porcelanato Bianco 120x120",
        "parede": "Parede Branco Neve",
        "forro": "Forro Gesso Liso",
        "marcenaria": "MDF Freijó Duratex",
        "bancada": "Quartzito Taj Mahal Polido",
        "esquadria": "Alumínio Preto Fosco",
        "vidro": "Vidro Incolor 8mm",
        "sofa": "Tecido Linho Cru",
    },
}


def build(estilo="contrato"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    n = NOMES[estilo]

    piso = mat(n["piso"], (0.72, 0.70, 0.67), 0.3)
    parede = mat(n["parede"], (0.85, 0.84, 0.82), 0.7)
    forro = mat(n["forro"], (0.90, 0.90, 0.89), 0.8)
    marcenaria = mat(n["marcenaria"], (0.35, 0.22, 0.13), 0.4)
    bancada = mat(n["bancada"], (0.80, 0.78, 0.72), 0.2)
    esquadria = mat(n["esquadria"], (0.10, 0.10, 0.10), 0.4)
    vidro = mat(n["vidro"], (0.9, 0.95, 0.95), 0.05)
    sofa = mat(n["sofa"], (0.45, 0.42, 0.38), 0.85)
    luz = mat("LUZ_LED_3000K", (1.0, 0.85, 0.7), 0.5)
    # sem mapeamento no project.yaml de proposito: o relatorio tem que acusar
    orfao = mat("Material12", (0.6, 0.3, 0.3), 0.5)

    # casca do ambiente
    box("Piso", 0, 0, -WALL, W, D, 0, piso)
    box("Forro", 0, 0, H, W, D, H + WALL, forro)
    box("Parede_Leste", W, 0, 0, W + WALL, D, H, parede)
    box("Parede_Sul", 0, -WALL, 0, W, 0, H, parede)
    box("Parede_Norte", 0, D, 0, W, D + WALL, H, parede)

    # parede oeste em quatro pecas, deixando o vao da janela
    box("Parede_Oeste_a", -WALL, 0, 0, 0, WIN["y0"], H, parede)
    box("Parede_Oeste_b", -WALL, WIN["y1"], 0, 0, D, H, parede)
    box("Parede_Oeste_peitoril", -WALL, WIN["y0"], 0, 0, WIN["y1"], WIN["z0"], parede)
    box("Parede_Oeste_verga", -WALL, WIN["y0"], WIN["z1"], 0, WIN["y1"], H, parede)

    # esquadria e vidro (vidro como plano unico, igual ao SketchUp faz)
    f = 0.05
    box("Esq_inf", -0.08, WIN["y0"], WIN["z0"], -0.02, WIN["y1"], WIN["z0"] + f, esquadria)
    box("Esq_sup", -0.08, WIN["y0"], WIN["z1"] - f, -0.02, WIN["y1"], WIN["z1"], esquadria)
    box("Esq_lat_a", -0.08, WIN["y0"], WIN["z0"], -0.02, WIN["y0"] + f, WIN["z1"], esquadria)
    box("Esq_lat_b", -0.08, WIN["y1"] - f, WIN["z0"], -0.02, WIN["y1"], WIN["z1"], esquadria)
    box("Esq_central", -0.08, 2.78, WIN["z0"], -0.02, 2.82, WIN["z1"], esquadria)
    box("Vidro", -0.051, WIN["y0"] + f, WIN["z0"] + f, -0.05, WIN["y1"] - f, WIN["z1"] - f, vidro)

    # cozinha na parede sul
    box("Base_marcenaria", 0.20, 0.02, 0.10, 2.80, 0.62, 0.88, marcenaria)
    box("Rodape_cozinha", 0.20, 0.10, 0.0, 2.80, 0.62, 0.10, esquadria)
    box("Bancada", 0.15, 0.0, 0.88, 2.90, 0.66, 0.92, bancada)
    box("Aereo", 0.20, 0.02, 1.55, 2.40, 0.38, 2.30, marcenaria)
    box("Puxador_a", 0.22, 0.63, 0.70, 1.48, 0.65, 0.73, esquadria)
    box("Puxador_b", 1.55, 0.63, 0.70, 2.78, 0.65, 0.73, esquadria)

    # sanca de LED sob o armario aereo
    box("LED_sanca", 0.22, 0.06, 1.52, 2.38, 0.36, 1.55, luz)

    # estar
    box("Sofa_base", 2.55, 2.60, 0.10, 3.95, 4.90, 0.45, sofa)
    box("Sofa_encosto", 3.72, 2.60, 0.45, 3.95, 4.90, 0.90, sofa)
    box("Sofa_braco_a", 2.55, 2.60, 0.45, 3.95, 2.82, 0.75, sofa)
    box("Sofa_braco_b", 2.55, 4.68, 0.45, 3.95, 4.90, 0.75, sofa)
    box("Almofada", 3.55, 3.30, 0.45, 3.70, 3.95, 0.85, orfao)

    box("Mesa_centro_tampo", 1.55, 3.20, 0.38, 2.35, 4.30, 0.42, marcenaria)
    box("Mesa_centro_pe_a", 1.62, 3.28, 0.0, 1.74, 3.40, 0.38, esquadria)
    box("Mesa_centro_pe_b", 2.16, 4.10, 0.0, 2.28, 4.22, 0.38, esquadria)

    box("Painel_tv", 0.20, 4.95, 0.60, 1.90, 5.10, 2.10, marcenaria)

    return {
        "objetos": len(bpy.data.objects),
        "materiais": [m.name for m in bpy.data.materials],
    }


def cameras_json():
    """Formato identico ao que a extensao Ruby vai gerar do SketchUp."""
    return {
        "gerado_por": "tools/make_test_scene.py",
        "unidades": "metros",
        "cameras": [
            {
                "name": "Sala 01",
                "slug": "sala-01",
                "eye": [3.85, 5.25, 1.55],
                "target": [1.10, 1.30, 1.15],
                "up": [0.0, 0.0, 1.0],
                "fov_deg": 62.0,
                "fov_axis": "horizontal",
                "two_point": False,
            },
            {
                "name": "Cozinha 01",
                "slug": "cozinha-01",
                "eye": [3.60, 4.30, 1.60],
                "target": [1.30, 0.35, 1.05],
                "up": [0.0, 0.0, 1.0],
                "fov_deg": 65.0,
                "fov_axis": "horizontal",
                "two_point": False,
            },
            {
                "name": "Sala 02",
                "slug": "sala-02",
                "eye": [2.10, 5.30, 1.62],
                "target": [1.60, 0.60, 1.05],
                "up": [0.0, 0.0, 1.0],
                "fov_deg": 60.0,
                "fov_axis": "horizontal",
                "two_point": True,
            },
        ],
    }


def main():
    argv = sys.argv
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    out_dir = extra[0] if extra else "."
    estilo = extra[1] if len(extra) > 1 else "contrato"
    os.makedirs(out_dir, exist_ok=True)

    info = build(estilo)
    glb = os.path.join(out_dir, "modelo.glb")
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=False)

    cams = os.path.join(out_dir, "cameras.json")
    with open(cams, "w", encoding="utf-8") as f:
        json.dump(cameras_json(), f, ensure_ascii=False, indent=2)

    print(f"[cena-teste] {info['objetos']} objetos")
    print(f"[cena-teste] materiais: {', '.join(info['materiais'])}")
    print(f"[cena-teste] {glb}")
    print(f"[cena-teste] {cams}")


if __name__ == "__main__":
    main()
