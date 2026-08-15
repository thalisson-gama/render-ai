"""Mede a curva real de tempo x qualidade nesta maquina.

Existe porque "essa maquina aguenta?" e uma pergunta que so se responde
medindo. Roda a MESMA camera em varios ajustes e imprime a tabela.

    blender -b -P tools/benchmark.py -- projects/teste-interior

Grava tools/benchmark-<maquina>.json para comparar depois com o PC dela.
"""

import json
import os
import platform
import sys
import time

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "blender"))

from rlib import cameras, engine, lighting, materials, scene as scene_mod  # noqa: E402

# (rotulo, largura, altura, amostras, limiar adaptativo, fast_gi, passes)
PONTOS = [
    ("preview       960x540   96am", 960, 540, 96, 0.03, True, False),
    ("medio        1280x720  200am", 1280, 720, 200, 0.02, False, False),
    ("entrega      1920x1080 300am", 1920, 1080, 300, 0.015, False, False),
    ("entrega+     1920x1080 600am", 1920, 1080, 600, 0.010, False, False),
    ("final        1920x1080 1024am", 1920, 1080, 1024, 0.008, False, False),
    ("final+passes 1920x1080 1024am", 1920, 1080, 1024, 0.008, False, True),
]


def main():
    argv = sys.argv
    proj = argv[argv.index("--") + 1] if "--" in argv else "projects/teste-interior"

    with open(os.path.join(proj, "source", "cameras.json"), encoding="utf-8") as f:
        cams = json.load(f)["cameras"]
    modelo = os.path.join(proj, "source", "modelo.glb")

    scene_mod.wipe()
    sc = bpy.context.scene
    meshes = scene_mod.import_model(modelo)
    tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)

    materials.apply({}, "", {})
    preset = {
        "name": "bench",
        "sun": {"enabled": True, "hour": 16.0, "energy": 18.0, "angle_deg": 0.6},
        "sky": {"enabled": True, "strength": 1.0, "sun_disc": False},
        "exposure": 0.0,
        "view_transform": "AgX",
    }
    lighting.setup(sc, preset, {"lat": -19.92, "lon": -43.94, "tz_offset": -3}, 0.0, "2026-03-21")
    dev = engine.configure_device(sc, "auto")

    print("BENCH_START")
    print(f"BENCH_INFO maquina={platform.machine()} dispositivo={dev['usando']} "
          f"({', '.join(dev['dispositivos'])}) triangulos={tris}")

    resultados = []
    for rotulo, w, h, am, limiar, fgi, passes in PONTOS:
        engine.configure_quality(sc, {
            "samples": am, "adaptive": True, "adaptive_threshold": limiar,
            "denoise": True, "fast_gi": fgi, "fast_gi_bounces": 2,
            "max_bounces": 8 if fgi else 16,
            "diffuse_bounces": 3 if fgi else 6,
            "glossy_bounces": 3 if fgi else 6,
            "transmission_bounces": 8 if fgi else 16,
            "transparent_bounces": 8,
        }, dev)
        engine.configure_output(sc, [w, h])
        engine.enable_passes(sc, passes)

        cam, _ = cameras.build(cams[0], [w, h])
        t0 = time.time()
        engine.render_to(sc, cam, f"/tmp/bench_{w}x{h}_{am}{'_p' if passes else ''}.png")
        dt = time.time() - t0
        bpy.data.objects.remove(cam, do_unlink=True)

        resultados.append({"ajuste": rotulo, "largura": w, "altura": h,
                           "amostras": am, "passes": passes, "segundos": round(dt, 1)})
        print(f"BENCH_ROW {rotulo} | {dt:8.1f}s | {dt/60:6.1f} min")

    saida = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"benchmark-{platform.system().lower()}-{platform.machine()}.json",
    )
    with open(saida, "w", encoding="utf-8") as f:
        json.dump({
            "maquina": platform.platform(),
            "processador": platform.processor() or platform.machine(),
            "dispositivo": dev,
            "triangulos_cena": tris,
            "blender": bpy.app.version_string,
            "resultados": resultados,
        }, f, ensure_ascii=False, indent=2)
    print(f"BENCH_SAVED {saida}")
    print("BENCH_OK")


if __name__ == "__main__":
    main()
