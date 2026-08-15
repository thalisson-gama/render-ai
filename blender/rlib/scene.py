"""Importacao do modelo, diagnostico e validacao de escala.

REGRA ZERO: nada aqui altera geometria por conta propria. Qualquer operacao
que mexa em malha e opt-in explicito no project.yaml. O padrao e diagnosticar
e reportar, nunca "consertar" em silencio.
"""

import os

import bpy

PLAUSIBLE_MIN_M = 0.8      # menor dimensao aceitavel para um ambiente
PLAUSIBLE_MAX_M = 300.0    # maior dimensao aceitavel para um projeto de interiores

# Fatores classicos de erro de unidade em export de CAD.
UNIT_SUSPECTS = {
    "modelo em milimetros": 0.001,
    "modelo em centimetros": 0.01,
    "modelo em polegadas": 0.0254,
    "modelo em pes": 0.3048,
    "modelo em metros lido como milimetros": 1000.0,
}


def wipe():
    """Cena limpa. Remove tudo, inclusive dados orfaos do arquivo padrao."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    if not os.path.exists(path):
        raise FileNotFoundError(f"modelo nao encontrado: {path}")

    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext in (".usd", ".usdc", ".usda", ".usdz"):
        bpy.ops.wm.usd_import(filepath=path)
    elif ext == ".dae":
        bpy.ops.wm.collada_import(filepath=path)
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        raise ValueError(f"formato nao suportado: {ext}")

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(
            "importacao terminou sem nenhuma malha. O arquivo pode estar vazio "
            "ou corrompido. Abra no Blender manualmente para conferir."
        )
    return meshes


def world_bbox(objects):
    """Bounding box em coordenadas de mundo."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for obj in objects:
        for corner in obj.bound_box:
            p = obj.matrix_world @ type(obj.location)(corner)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
    return lo, hi, [hi[i] - lo[i] for i in range(3)]


def validate_scale(meshes, expected_ceiling_m=None, tolerance_m=0.25):
    """Confere se o modelo chegou em metros. Erro de unidade e silencioso e caro.

    Devolve (ok, relatorio). Nunca corrige sozinho: sugere o fator e para.
    """
    lo, hi, dims = world_bbox(meshes)
    largest = max(dims)
    report = {
        "bbox_min": [round(v, 4) for v in lo],
        "bbox_max": [round(v, 4) for v in hi],
        "dimensoes_m": [round(v, 3) for v in dims],
        "maior_dimensao_m": round(largest, 3),
        "altura_z_m": round(dims[2], 3),
        "problemas": [],
        "sugestoes": [],
    }

    plausible = PLAUSIBLE_MIN_M <= largest <= PLAUSIBLE_MAX_M
    if not plausible:
        report["problemas"].append(
            f"maior dimensao do modelo e {largest:.3f} m, fora da faixa "
            f"plausivel ({PLAUSIBLE_MIN_M} a {PLAUSIBLE_MAX_M} m)"
        )
        for label, factor in UNIT_SUSPECTS.items():
            if PLAUSIBLE_MIN_M <= largest * factor <= PLAUSIBLE_MAX_M:
                report["sugestoes"].append(
                    f"suspeita: {label}. Multiplicar por {factor} daria "
                    f"{largest * factor:.2f} m. Corrija na EXPORTACAO, nao aqui."
                )

    if expected_ceiling_m:
        delta = abs(dims[2] - expected_ceiling_m)
        report["pe_direito_esperado_m"] = expected_ceiling_m
        if delta > tolerance_m:
            report["problemas"].append(
                f"altura total do modelo e {dims[2]:.3f} m, esperado "
                f"~{expected_ceiling_m} m (tolerancia {tolerance_m} m). "
                "Confira se ha laje, cobertura ou objeto solto fora do ambiente."
            )

    report["ok"] = plausible and not any(
        "maior dimensao" in p for p in report["problemas"]
    )
    return report["ok"], report


def diagnose(meshes):
    """Diagnostico de saude do modelo. So reporta, nao mexe."""
    tris = 0
    heavy = []
    loose_scale = []
    for obj in meshes:
        n = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        tris += n
        if n > 150_000:
            heavy.append({"objeto": obj.name, "triangulos": n})
        s = obj.scale
        if any(abs(v - 1.0) > 1e-3 for v in s):
            loose_scale.append(obj.name)

    return {
        "objetos": len(meshes),
        "triangulos": tris,
        "materiais": len(bpy.data.materials),
        "imagens": len(bpy.data.images),
        "objetos_pesados": sorted(heavy, key=lambda d: -d["triangulos"])[:10],
        "objetos_com_escala_nao_aplicada": loose_scale[:10],
    }


def apply_optional_cleanup(meshes, options):
    """Operacoes que TOCAM geometria. Todas desligadas por padrao.

    So rodam se o project.yaml pedir explicitamente. Cada uma volta no relatorio.
    """
    done = []
    if not options:
        return done

    if options.get("merge_by_distance"):
        threshold = float(options.get("merge_threshold_m", 0.0001))
        bpy.ops.object.select_all(action="DESELECT")
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=threshold)
        bpy.ops.object.mode_set(mode="OBJECT")
        done.append(f"merge_by_distance (limiar {threshold} m)")

    if options.get("recalculate_normals"):
        bpy.ops.object.select_all(action="DESELECT")
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        done.append("recalculate_normals (para fora)")

    return done
