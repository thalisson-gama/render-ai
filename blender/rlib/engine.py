"""Configuracao do Cycles: dispositivo, amostragem, passes e saida.

A selecao de dispositivo e deliberadamente portatil. O MVP e validado num
Mac M1 (Metal) mas vai rodar num PC com NVIDIA (OptiX). O mesmo codigo tem
que achar o melhor backend disponivel sem ninguem editar config.
"""

import os

import bpy

# Ordem de preferencia. OptiX ganha de CUDA na mesma placa NVIDIA porque
# usa os nucleos RT e habilita o denoiser por hardware.
BACKENDS = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")


def configure_device(scene, preference="auto"):
    """Escolhe e liga o melhor dispositivo disponivel. Devolve relatorio."""
    report = {"solicitado": preference}

    if preference == "cpu":
        scene.cycles.device = "CPU"
        report["usando"] = "CPU"
        report["dispositivos"] = ["CPU"]
        return report

    prefs = bpy.context.preferences.addons["cycles"].preferences
    chosen, active = None, []

    for backend in BACKENDS:
        try:
            prefs.compute_device_type = backend
        except (TypeError, AttributeError):
            continue
        try:
            prefs.refresh_devices()
        except Exception:
            pass
        available = [d for d in prefs.devices if d.type == backend]
        if available:
            chosen = backend
            for d in prefs.devices:
                d.use = d.type == backend
            active = [d.name for d in available]
            break

    if chosen:
        scene.cycles.device = "GPU"
        report["usando"] = chosen
        report["dispositivos"] = active
    else:
        scene.cycles.device = "CPU"
        report["usando"] = "CPU"
        report["dispositivos"] = ["CPU"]
        report["aviso"] = "nenhuma GPU compativel encontrada, caiu para CPU"

    return report


def configure_quality(scene, quality, device_report):
    """Amostragem, ruido, quiques de luz e limite de tempo."""
    c = scene.cycles
    scene.render.engine = "CYCLES"

    c.samples = int(quality.get("samples", 256))
    c.use_adaptive_sampling = bool(quality.get("adaptive", True))
    c.adaptive_threshold = float(quality.get("adaptive_threshold", 0.01))
    c.time_limit = float(quality.get("time_limit_s", 0))

    # O Cycles vem com sample_clamp_indirect = 10.0 de fabrica. Isso corta o
    # topo das amostras indiretas, o que serve para matar firefly em cena com
    # caustica, e destroi o rebote em interior iluminado so por luminaria: o
    # piso estoura, a luz que ele devolveria para a parede e decapitada, e a
    # parede fica preta. O sintoma e cruel porque aumentar a potencia da luz
    # NAO melhora nada, ja que o teto e absoluto.
    c.sample_clamp_indirect = float(quality.get("clamp_indirect", 0.0))
    c.sample_clamp_direct = float(quality.get("clamp_direct", 0.0))

    c.use_denoising = bool(quality.get("denoise", True))
    if c.use_denoising:
        for candidate in ("OPTIX", "OPENIMAGEDENOISE"):
            if candidate == "OPTIX" and device_report.get("usando") != "OPTIX":
                continue
            try:
                c.denoiser = candidate
                break
            except TypeError:
                continue

    # Interior vive de luz indireta. Cortar quique difuso e o jeito mais
    # rapido de matar o realismo, entao esse valor sobe, nao desce.
    c.max_bounces = int(quality.get("max_bounces", 12))
    c.diffuse_bounces = int(quality.get("diffuse_bounces", 4))
    c.glossy_bounces = int(quality.get("glossy_bounces", 4))
    c.transmission_bounces = int(quality.get("transmission_bounces", 12))
    c.transparent_max_bounces = int(quality.get("transparent_bounces", 8))

    if quality.get("fast_gi"):
        c.use_fast_gi = True
        c.ao_bounces_render = int(quality.get("fast_gi_bounces", 2))

    # 8 GB de RAM nao perdoa cache entre frames.
    scene.render.use_persistent_data = bool(quality.get("persistent_data", False))

    return {
        "amostras": c.samples,
        "adaptativo": c.use_adaptive_sampling,
        "denoise": c.use_denoising,
        "denoiser": c.denoiser if c.use_denoising else None,
        "limite_tempo_s": c.time_limit or None,
        "quiques": {
            "max": c.max_bounces,
            "difuso": c.diffuse_bounces,
            "glossy": c.glossy_bounces,
            "transmissao": c.transmission_bounces,
        },
        "fast_gi": bool(quality.get("fast_gi")),
        "clamp_indirect": c.sample_clamp_indirect,
    }


def configure_output(scene, resolution, file_format="PNG", color_depth="16"):
    scene.render.resolution_x = int(resolution[0])
    scene.render.resolution_y = int(resolution[1])
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False

    img = scene.render.image_settings
    img.file_format = file_format
    if file_format == "PNG":
        img.color_mode = "RGB"
        img.color_depth = color_depth
        img.compression = 15


def enable_passes(scene, want_passes):
    """Liga depth, normal e cryptomatte. Sao a materia-prima da etapa de IA."""
    vl = scene.view_layers[0]
    if not want_passes:
        return {"ativo": False}

    vl.use_pass_z = True
    vl.use_pass_normal = True
    vl.use_pass_cryptomatte_object = True
    vl.use_pass_cryptomatte_material = True
    vl.pass_cryptomatte_depth = 6
    return {
        "ativo": True,
        "passes": ["depth", "normal", "cryptomatte_object", "cryptomatte_material"],
    }


def setup_pass_output(scene, passes_dir):
    """Compositor gravando os passes em EXR junto com o beauty em PNG.

    Se a API do compositor mudar entre versoes, o render principal continua.
    Passe e um extra, nunca pode derrubar a entrega.
    """
    try:
        # Blender 5.x: o compositor virou node group em compositing_node_group.
        # A API antiga (scene.node_tree) nao existe mais.
        nt = getattr(scene, "compositing_node_group", None)
        if nt is None:
            return {"ok": False, "erro": "compositor indisponivel nesta build"}
        for n in list(nt.nodes):
            nt.nodes.remove(n)

        rl = nt.nodes.new("CompositorNodeRLayers")
        rl.location = (0, 0)
        comp = nt.nodes.new("CompositorNodeComposite")
        comp.location = (600, 200)
        nt.links.new(rl.outputs["Image"], comp.inputs["Image"])

        os.makedirs(passes_dir, exist_ok=True)
        fout = nt.nodes.new("CompositorNodeOutputFile")
        fout.location = (600, -200)
        fout.base_path = passes_dir
        fout.format.file_format = "OPEN_EXR"
        fout.format.color_depth = "32"

        fout.file_slots.clear()
        wired = []
        for socket, label in (
            ("Depth", "depth"),
            ("Normal", "normal"),
            ("CryptoObject00", "crypto_object"),
            ("CryptoMaterial00", "crypto_material"),
        ):
            if socket in rl.outputs:
                fout.file_slots.new(label)
                nt.links.new(rl.outputs[socket], fout.inputs[label])
                wired.append(label)
        return {"ok": True, "gravando": wired}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def render_to(scene, camera_obj, filepath):
    scene.camera = camera_obj
    scene.render.filepath = filepath
    bpy.ops.render.render(write_still=True)
    return filepath
