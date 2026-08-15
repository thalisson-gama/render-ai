"""Levantamento dos materiais que EXISTEM no modelo, com area real em metros.

Existe porque a arquiteta ja aplica material durante a modelagem, com os nomes
dela. Impor uma convencao nova seria pedir retrabalho a quem ja tem um jeito
que funciona. Entao o pipeline descobre a convencao dela e se adapta.

A area em metros quadrados e o dado que mais importa aqui: ela responde
"quais 6 materiais ocupam 80% da imagem", que e onde vale gastar textura PBR
de verdade. Material com 0,3 m2 nao merece mapa 4K.
"""

import bpy


def _polygon_world_area(obj, polygon, verts):
    """Area em metros quadrados, ja com a transformacao do objeto aplicada."""
    mw = obj.matrix_world
    pts = [mw @ verts[i].co for i in polygon.vertices]
    if len(pts) < 3:
        return 0.0
    total = 0.0
    origin = pts[0]
    for i in range(1, len(pts) - 1):
        total += (pts[i] - origin).cross(pts[i + 1] - origin).length * 0.5
    return total


def _has_image_texture(mat):
    if not mat.use_nodes or mat.node_tree is None:
        return False
    return any(n.type == "TEX_IMAGE" and n.image for n in mat.node_tree.nodes)


def _base_color(mat):
    if mat.use_nodes and mat.node_tree:
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                c = n.inputs["Base Color"].default_value
                return [round(c[0], 3), round(c[1], 3), round(c[2], 3)]
    c = mat.diffuse_color
    return [round(c[0], 3), round(c[1], 3), round(c[2], 3)]


def _looks_auto_generated(name):
    """`Material12`, `Color A03`, `Cor 0255`: nome que o SketchUp inventou."""
    low = name.strip().lower()
    for prefix in ("material", "color", "cor ", "colour", "default"):
        if low.startswith(prefix):
            rest = low[len(prefix):].strip(" _-")
            if rest == "" or rest.replace(" ", "").replace("_", "").isalnum() and any(
                ch.isdigit() for ch in rest
            ):
                return True
    return False


def survey(meshes):
    """Devolve a lista de materiais do modelo, ordenada por area."""
    stats = {}
    sem_material = {"objetos": 0, "area_m2": 0.0}

    for obj in meshes:
        mesh = obj.data
        verts = mesh.vertices
        slots = [s.material for s in obj.material_slots]

        if not slots:
            sem_material["objetos"] += 1
            for poly in mesh.polygons:
                sem_material["area_m2"] += _polygon_world_area(obj, poly, verts)
            continue

        for poly in mesh.polygons:
            idx = poly.material_index
            mat = slots[idx] if idx < len(slots) else None
            if mat is None:
                sem_material["area_m2"] += _polygon_world_area(obj, poly, verts)
                continue
            entry = stats.setdefault(
                mat.name,
                {
                    "nome": mat.name,
                    "area_m2": 0.0,
                    "faces": 0,
                    "objetos": set(),
                    "tem_textura": _has_image_texture(mat),
                    "cor": _base_color(mat),
                    "nome_automatico": _looks_auto_generated(mat.name),
                },
            )
            entry["area_m2"] += _polygon_world_area(obj, poly, verts)
            entry["faces"] += 1
            entry["objetos"].add(obj.name)

    total = sum(e["area_m2"] for e in stats.values()) or 1.0
    saida = []
    for e in sorted(stats.values(), key=lambda d: -d["area_m2"]):
        saida.append({
            "nome": e["nome"],
            "area_m2": round(e["area_m2"], 2),
            "percentual": round(100.0 * e["area_m2"] / total, 1),
            "faces": e["faces"],
            "objetos": len(e["objetos"]),
            "tem_textura": e["tem_textura"],
            "cor": e["cor"],
            "nome_automatico": e["nome_automatico"],
        })

    return {
        "materiais": saida,
        "area_total_m2": round(total, 2),
        "faces_sem_material": round(sem_material["area_m2"], 2),
        "objetos_sem_material": sem_material["objetos"],
    }
