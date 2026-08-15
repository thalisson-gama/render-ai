"""Executor dentro do Blender. Nao chame direto, use `./render`.

    blender -b -P blender/run_render.py -- /caminho/job.json

Recebe um job.json ja resolvido pela CLI de fora e devolve um relatorio.
Nao le YAML, nao decide versao, nao inventa parametro. So executa.
"""

import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from rlib import cameras, engine, lighting, materials, scene as scene_mod, survey  # noqa: E402


def log(msg):
    print(f"[render-ai] {msg}", flush=True)


def main():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("uso: blender -b -P run_render.py -- job.json")
    job_path = argv[argv.index("--") + 1]

    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)

    report = {"job": job_path, "etapas": {}, "renders": [], "avisos": [], "erros": []}
    started = time.time()

    # ---------------------------------------------------------------- cena
    scene_mod.wipe()
    sc = bpy.context.scene

    log(f"importando {job['source']['model']}")
    meshes = scene_mod.import_model(job["source"]["model"])
    report["etapas"]["diagnostico"] = scene_mod.diagnose(meshes)
    log(
        f"  {report['etapas']['diagnostico']['objetos']} objetos, "
        f"{report['etapas']['diagnostico']['triangulos']:,} triangulos, "
        f"{report['etapas']['diagnostico']['materiais']} materiais"
    )

    # ------------------------------------------------------------- escala
    units = job.get("units_check") or {}
    ok, scale_report = scene_mod.validate_scale(
        meshes,
        expected_ceiling_m=units.get("expected_ceiling_m"),
        tolerance_m=units.get("tolerance", 0.25),
    )
    report["etapas"]["escala"] = scale_report
    dims = scale_report["dimensoes_m"]
    log(f"  dimensoes do modelo: {dims[0]} x {dims[1]} x {dims[2]} m")
    for p in scale_report["problemas"]:
        log(f"  PROBLEMA DE ESCALA: {p}")
        report["avisos"].append(p)
    for s in scale_report["sugestoes"]:
        log(f"  -> {s}")

    if not ok and not job.get("force"):
        report["erros"].append(
            "escala do modelo implausivel. Render abortado. Corrija a exportacao "
            "ou rode de novo com --force se souber o que esta fazendo."
        )
        finish(report, job, started, failed=True)
        return

    cleanup = scene_mod.apply_optional_cleanup(meshes, job.get("cleanup"))
    if cleanup:
        report["etapas"]["limpeza_geometria"] = cleanup
        for c in cleanup:
            log(f"  GEOMETRIA ALTERADA (pedido no project.yaml): {c}")

    if job.get("survey_only"):
        # Levantamento antes de qualquer bind: queremos os nomes ORIGINAIS
        # que ela usou, não os nossos.
        log("levantando materiais do modelo (nenhum render sera feito)")
        report["etapas"]["levantamento"] = survey.survey(meshes)
        report["etapas"]["cameras_disponiveis"] = [
            {"nome": c["name"], "slug": c.get("slug"), "dois_pontos": c.get("two_point", False)}
            for c in job.get("cameras", [])
        ]
        finish(report, job, started, failed=False)
        return

    # -------------------------------------------------------- iluminacao
    log(f"iluminacao: preset {job['lighting'].get('name')}")
    light_report = lighting.setup(
        sc,
        job["lighting"],
        job["location"],
        north_angle_deg=job.get("north_angle_deg", 0.0),
        date=job["lighting"].get("date"),
    )
    report["etapas"]["iluminacao"] = light_report
    for a in light_report.get("avisos", []):
        log(f"  AVISO: {a}")
        report["avisos"].append(a)
    if job.get("luminarias"):
        fix = lighting.place_fixtures(
            sc, job["luminarias"], job.get("fixtures"),
            wb_gain=(light_report.get("balanco_de_branco") or {}).get("ganho_rgb"),
        )
        light_report["luminarias"] = fix
        log(f"  {fix['total']} luminarias criadas a partir do modelo:")
        for k, v in fix["por_componente"].items():
            log(f"      {v}x {k}")

    if "sol" in light_report:
        s = light_report["sol"]
        log(
            f"  sol as {s['hora']}h: elevacao {s['elevacao_deg']}deg, "
            f"azimute {s['azimute_deg']}deg"
        )


    # --------------------------------------------------------- materiais
    log("aplicando materiais")
    mat_report = materials.apply(
        job.get("materials", {}),
        job.get("library_dir", ""),
        job.get("artificial_lights", {}),
        wb_gain=(light_report.get("balanco_de_branco") or {}).get("ganho_rgb"),
    )
    report["etapas"]["materiais"] = mat_report
    log(f"  {len(mat_report['mapeados'])} mapeados da biblioteca")
    if mat_report["emissores"]:
        log(f"  {len(mat_report['emissores'])} luminarias detectadas por nome")
    if mat_report["sem_mapeamento"]:
        aviso = (
            f"{len(mat_report['sem_mapeamento'])} materiais sem mapeamento na "
            f"biblioteca: {', '.join(mat_report['sem_mapeamento'][:8])}"
            + (" ..." if len(mat_report["sem_mapeamento"]) > 8 else "")
        )
        log(f"  ATENCAO: {aviso}")
        report["avisos"].append(aviso)

    if job.get("diagnose_only"):
        log("modo diagnostico: nenhum render sera feito")
        report["etapas"]["cameras_disponiveis"] = [
            {"nome": c["name"], "slug": c.get("slug"), "dois_pontos": c.get("two_point", False)}
            for c in job.get("cameras", [])
        ]
        finish(report, job, started, failed=False)
        return

    tex = materials.texture_memory_report(job["quality"].get("texture_max_px"))
    report["etapas"]["texturas"] = tex
    if tex["imagens"]:
        msg = f"  texturas: {tex['imagens']} imagens, {tex['memoria_antes_mb']:.0f} MB na cena"
        if tex["reduzidas"]:
            msg += (
                f" -> {tex['memoria_depois_mb']:.0f} MB "
                f"({tex['reduzidas']} reduzidas para {tex['limite_px']}px)"
            )
        log(msg)
        if tex["memoria_depois_mb"] > 2500:
            aviso = (
                f"textura ocupando {tex['memoria_depois_mb']:.0f} MB. Em maquina de "
                f"8 GB isso e risco de estouro. Considere texture_max_px menor."
            )
            log(f"  ATENCAO: {aviso}")
            report["avisos"].append(aviso)

    # ------------------------------------------------------------- engine
    quality = job["quality"]
    dev = engine.configure_device(sc, job["render"].get("device", "auto"))
    log(f"dispositivo: {dev['usando']} ({', '.join(dev['dispositivos'])})")
    q = engine.configure_quality(sc, quality, dev)
    engine.configure_output(sc, job["render"]["resolution"])
    passes = engine.enable_passes(sc, quality.get("passes", False))
    report["etapas"]["engine"] = {"dispositivo": dev, "qualidade": q, "passes": passes}
    log(
        f"  {q['amostras']} amostras, denoise={q['denoise']}, "
        f"limite {q['limite_tempo_s'] or 'sem limite'}s"
    )

    # ------------------------------------------------------------ cameras
    out_dir = job["output"]["dir"]

    for spec in job["cameras"]:
        slug = spec.get("slug") or cameras.slugify(spec["name"])
        # a versao e por camera: sala-01/v007 e cozinha-01/v002 convivem
        version = spec.get("version") or job["output"]["version"]
        cam_dir = os.path.join(out_dir, slug, version)
        os.makedirs(cam_dir, exist_ok=True)

        if passes.get("ativo"):
            engine.setup_pass_output(sc, os.path.join(cam_dir, "passes"))

        try:
            cam_obj, cam_info = cameras.build(
                spec, job["render"]["resolution"], spec.get("overrides")
            )
        except Exception as exc:
            msg = f"camera '{spec.get('name')}' falhou: {exc}"
            log(f"  ERRO: {msg}")
            report["erros"].append(msg)
            continue

        target = os.path.join(cam_dir, "raw.png")
        log(
            f"renderizando {slug} ({cam_info['lente_mm']}mm, "
            f"fov {cam_info['fov_deg']}deg {cam_info['fov_axis']})"
        )
        t0 = time.time()
        engine.render_to(sc, cam_obj, target)
        elapsed = time.time() - t0

        entry = {
            "camera": spec["name"],
            "slug": slug,
            "arquivo": target,
            "segundos": round(elapsed, 1),
            **cam_info,
        }
        report["renders"].append(entry)
        log(f"  pronto em {elapsed:.1f}s -> {target}")

        bpy.data.objects.remove(cam_obj, do_unlink=True)

    finish(report, job, started, failed=bool(report["erros"]) and not report["renders"])


def finish(report, job, started, failed=False):
    report["segundos_total"] = round(time.time() - started, 1)
    report["sucesso"] = not failed
    path = job.get("report_path")
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    log(f"relatorio: {path}")
    if failed:
        for e in report["erros"]:
            log(f"FALHOU: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
