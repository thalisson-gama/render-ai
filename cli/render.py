#!/usr/bin/env python3
"""CLI do render-ai. Resolve a configuracao e entrega um job pronto ao Blender.

Toda a inteligencia de configuracao mora aqui, fora do Blender: ler YAML,
mesclar presets, achar materiais na biblioteca, decidir o numero da versao,
validar o que foi pedido. O Blender recebe um job.json sem ambiguidade.

    ./render --project apartamento-joao --all
    ./render --project apartamento-joao --camera sala-01 --lighting tarde-16h
    ./render --project apartamento-joao --all --quality final --hour 16.5
"""

import argparse
import copy
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BLENDER_CANDIDATES = [
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/local/bin/blender",
    "/usr/bin/blender",
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
]


# ---------------------------------------------------------------- utilidades

def die(msg):
    print(f"\n  erro: {msg}\n", file=sys.stderr)
    sys.exit(1)


def load_yaml(path):
    if not os.path.exists(path):
        die(f"arquivo nao encontrado: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def find_blender():
    """Acha o Blender em qualquer maquina, sem exigir configuracao.

    A ordem importa: variavel de ambiente ganha de tudo, depois PATH, depois
    os lugares padrao. No Windows a versao entra no caminho da pasta, entao a
    busca e por padrao e nao por caminho fixo, senao quebra a cada atualizacao.
    """
    env = os.environ.get("BLENDER")
    if env and os.path.exists(env):
        return env

    which = shutil.which("blender")
    if which:
        return which

    padroes = [
        # macOS
        "/Applications/Blender.app/Contents/MacOS/Blender",
        "/Applications/Blender*/Blender.app/Contents/MacOS/Blender",
        # Windows
        r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        r"C:\Program Files (x86)\Blender Foundation\Blender*\blender.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender Foundation\Blender*\blender.exe"),
        os.path.expandvars(
            r"%ProgramFiles%\WindowsApps\BlenderFoundation.Blender*\blender.exe"
        ),
        # Linux
        "/usr/local/bin/blender",
        "/usr/bin/blender",
        "/snap/bin/blender",
    ]

    achados = []
    for p in padroes:
        achados.extend(sorted(glob.glob(p)))
    if achados:
        return achados[-1]  # a versao mais nova pelo nome da pasta

    die(
        "Blender nao encontrado.\n"
        "  macOS:   brew install --cask blender\n"
        "  Windows: baixe em blender.org (ou winget install BlenderFoundation.Blender)\n"
        "  Ou aponte a variavel de ambiente BLENDER para o executavel."
    )


# ------------------------------------------------------------- biblioteca

def resolve_material(slug, library_dir):
    """Aceita 'pedras/taj-mahal' ou so 'taj-mahal'."""
    if "/" in slug:
        mat_dir = os.path.join(library_dir, slug)
    else:
        matches = [
            p.parent
            for p in Path(library_dir).rglob("material.yaml")
            if p.parent.name == slug
        ]
        if not matches:
            return None, None
        if len(matches) > 1:
            die(
                f"material '{slug}' existe em mais de um lugar da biblioteca: "
                + ", ".join(str(m.relative_to(library_dir)) for m in matches)
            )
        mat_dir = str(matches[0])

    spec_path = os.path.join(mat_dir, "material.yaml")
    if not os.path.exists(spec_path):
        return None, None
    return load_yaml(spec_path), mat_dir


def list_library(library_dir):
    out = []
    for p in sorted(Path(library_dir).rglob("material.yaml")):
        spec = load_yaml(str(p))
        rel = p.parent.relative_to(library_dir)
        out.append((str(rel), spec.get("label", p.parent.name), spec.get("kind", "?")))
    return out


def garantir_formato_legivel(path):
    """O Blender 5.x REMOVEU o importador de Collada. DAE precisa virar GLB.

    A arquiteta exporta DAE porque o SketchUp 2022 nao tem glTF. Em vez de
    exigir que ela mude o processo, o pipeline converte sozinho, uma vez, e
    reaproveita o resultado. Precisa do assimp instalado.

    Alternativa sem assimp: exportar FBX do SketchUp, que o Blender importa
    nativamente. Ver docs/setup-windows.md.
    """
    if not path.lower().endswith(".dae"):
        return path

    glb = path[:-4] + ".glb"
    if os.path.exists(glb) and os.path.getmtime(glb) >= os.path.getmtime(path):
        return glb

    exe = shutil.which("assimp")
    if not exe:
        die(
            "este projeto usa .dae, e o Blender 5.x nao importa Collada.\n"
            "  Instale o conversor:  macOS: brew install assimp\n"
            "                        Windows: winget install Assimp.Assimp\n"
            "  Ou exporte FBX do SketchUp (o Blender le nativamente) e aponte\n"
            "  source.model para o .fbx no project.yaml."
        )

    print(f"  convertendo {os.path.basename(path)} -> {os.path.basename(glb)} (assimp)")
    r = subprocess.run([exe, "export", path, glb], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(glb):
        die(f"falha ao converter o DAE:\n{r.stderr[-800:]}")
    return glb


# -------------------------------------------------------------- versoes

def next_version(camera_dir):
    if not os.path.isdir(camera_dir):
        return "v001"
    existing = [
        int(d[1:])
        for d in os.listdir(camera_dir)
        if len(d) == 4 and d.startswith("v") and d[1:].isdigit()
    ]
    return f"v{(max(existing) + 1) if existing else 1:03d}"


def update_latest(camera_dir, version):
    link = os.path.join(camera_dir, "latest")
    try:
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(version, link)
    except OSError:
        pass  # Windows sem permissao de symlink: nao e critico


# --------------------------------------------------------------- principal

def build_job(args):
    project_dir = ROOT / "projects" / args.project
    if not project_dir.is_dir():
        available = sorted(p.name for p in (ROOT / "projects").iterdir() if p.is_dir())
        die(
            f"projeto '{args.project}' nao existe. "
            f"Disponiveis: {', '.join(available) or 'nenhum'}"
        )

    project = load_yaml(str(project_dir / "project.yaml"))
    defaults = load_yaml(str(ROOT / "config" / "defaults.yaml"))

    # --- qualidade ------------------------------------------------------
    quality_name = args.quality or project.get("render", {}).get("quality", "preview")
    quality = load_yaml(str(ROOT / "config" / "quality" / f"{quality_name}.yaml"))

    # --- iluminacao -----------------------------------------------------
    lighting_name = args.lighting or project.get("lighting", {}).get("preset")
    if not lighting_name:
        die("nenhum preset de iluminacao definido (use --lighting ou project.yaml)")
    lighting_path = ROOT / "config" / "lighting" / f"{lighting_name}.yaml"
    if not lighting_path.exists():
        available = sorted(
            p.stem for p in (ROOT / "config" / "lighting").glob("*.yaml")
        )
        die(
            f"preset de iluminacao '{lighting_name}' nao existe. "
            f"Disponiveis: {', '.join(available)}"
        )
    lighting = load_yaml(str(lighting_path))
    lighting["name"] = lighting_name
    lighting = deep_merge(lighting, project.get("lighting", {}).get("overrides", {}))
    if args.hour is not None:
        lighting.setdefault("sun", {})["enabled"] = True
        lighting["sun"]["hour"] = args.hour
    if args.date:
        lighting["date"] = args.date

    # --- render ---------------------------------------------------------
    render_cfg = deep_merge(defaults.get("render", {}), project.get("render", {}))
    if args.resolution:
        w, h = args.resolution.lower().split("x")
        render_cfg["resolution"] = [int(w), int(h)]
    if args.device:
        render_cfg["device"] = args.device
    if args.samples:
        quality["samples"] = args.samples
    if args.time_limit:
        quality["time_limit_s"] = args.time_limit
    if quality.get("resolution_scale"):
        s = float(quality["resolution_scale"])
        render_cfg["resolution"] = [
            int(render_cfg["resolution"][0] * s),
            int(render_cfg["resolution"][1] * s),
        ]

    # --- materiais ------------------------------------------------------
    library_dir = str(ROOT / "materials")
    resolved_materials, missing = {}, []
    for skp_name, valor in (project.get("materials") or {}).items():
        # Aceita duas formas:
        #   BANCADA: pedras/quartzito-splendido
        #   BANCADA: {use: pedras/quartzito-splendido, rotate_deg: 90}
        # A segunda ajusta o material da biblioteca so neste projeto, sem
        # duplicar arquivo. Mesmo revestimento assentado deitado ou em pe.
        if isinstance(valor, dict):
            slug = valor.get("use")
            ajustes = {k: v for k, v in valor.items() if k != "use"}
        else:
            slug, ajustes = valor, {}

        spec, mat_dir = resolve_material(slug, library_dir)
        if spec is None:
            missing.append((skp_name, slug))
            continue
        if ajustes:
            spec = deep_merge(spec, ajustes)
        resolved_materials[skp_name.strip().upper()] = {
            "slug": slug,
            "spec": spec,
            "dir": mat_dir,
        }
    if missing:
        die(
            "materiais citados no project.yaml que nao existem na biblioteca:\n    "
            + "\n    ".join(f"{n} -> {s}" for n, s in missing)
            + "\n\n  Rode `./render --list-materials` para ver o que existe."
        )

    artificial = {
        k.strip().upper(): v
        for k, v in ((project.get("lighting") or {}).get("artificial") or {}).items()
    }

    # --- cameras --------------------------------------------------------
    source = project.get("source", {})
    model_path = str(project_dir / source.get("model", "source/modelo.glb"))
    model_path = garantir_formato_legivel(model_path)
    cameras_path = str(project_dir / source.get("cameras", "source/cameras.json"))

    lights_path = str(project_dir / source.get("lights", "source/lights.json"))
    luminarias = []
    if os.path.exists(lights_path):
        with open(lights_path, encoding="utf-8") as f:
            luminarias = json.load(f).get("luminarias", [])

    if not os.path.exists(cameras_path):
        die(
            f"cameras.json nao encontrado em {cameras_path}.\n"
            "  Exporte do SketchUp com sketchup/export_render.rb."
        )
    with open(cameras_path, encoding="utf-8") as f:
        all_cameras = json.load(f).get("cameras", [])

    def slug_of(c):
        return c.get("slug") or c["name"].lower().replace(" ", "-")

    wanted = None
    if args.camera:
        wanted = {c.strip().lower() for c in args.camera.split(",")}
    elif not args.all:
        include = (project.get("cameras") or {}).get("include")
        if include:
            wanted = {c.lower() for c in include}

    selected = []
    for cam in all_cameras:
        s = slug_of(cam)
        if wanted is not None and s.lower() not in wanted and cam["name"].lower() not in wanted:
            continue
        cam["slug"] = s
        ov = dict(((project.get("cameras") or {}).get("overrides") or {}).get(s, {}))
        caixa = (project.get("cameras") or {}).get("room_bbox")
        if caixa and "room_bbox" not in ov:
            ov["room_bbox"] = caixa
        cam["overrides"] = ov
        selected.append(cam)

    if not selected:
        names = ", ".join(slug_of(c) for c in all_cameras)
        die(f"nenhuma camera selecionada. Disponiveis: {names}")

    # --- versoes ---------------------------------------------------------
    renders_dir = str(project_dir / "renders")
    for cam in selected:
        cam_dir = os.path.join(renders_dir, cam["slug"])
        cam["version"] = next_version(cam_dir)

    loc = deep_merge(defaults.get("location", {}), project.get("project", {}).get("location", {}))

    job = {
        "project_name": project.get("project", {}).get("name", args.project),
        "source": {"model": model_path, "cameras": cameras_path},
        "location": loc,
        "north_angle_deg": float(project.get("project", {}).get("north_angle_deg", 0.0)),
        "units_check": project.get("project", {}).get("units_check", {}),
        "cleanup": project.get("cleanup", {}),
        "render": render_cfg,
        "quality": quality,
        "lighting": lighting,
        "materials": resolved_materials,
        "artificial_lights": artificial,
        "luminarias": luminarias,
        "fixtures": (project.get("lighting") or {}).get("fixtures") or {},
        "library_dir": library_dir,
        "cameras": selected,
        "output": {"dir": renders_dir, "version": selected[0]["version"]},
        "force": args.force,
    }
    return job, project, project_dir


ACENTOS = str.maketrans("áàãâäéèêëíìîïóòõôöúùûüç", "aaaaaeeeeiiiiooooouuuuc")


def _tokens(name):
    return set(name.lower().translate(ACENTOS).replace("_", " ").replace("-", " ").split())


def suggest_material(nome_dela, library_index):
    """Casa o nome de material da arquiteta com um material da biblioteca.

    Ela ja aplica material na modelagem, com o vocabulario dela. Em vez de
    exigir que renomeie tudo, o pipeline tenta reconhecer. O palpite sempre
    volta com nivel de confianca, e humano confirma antes de virar config.
    """
    toks = _tokens(nome_dela)
    if not toks:
        return None, 0.0

    melhor, melhor_score = None, 0.0
    for slug, apelidos in library_index.items():
        score = 0.0
        for a in apelidos:
            a_norm = a.lower().translate(ACENTOS)
            if a_norm in toks:
                score += 2.0 + len(a_norm) / 20.0      # palavra inteira bate forte
            elif any(a_norm in t and len(a_norm) >= 4 for t in toks):
                score += 1.0                            # bate como pedaco
        if score > melhor_score:
            melhor, melhor_score = slug, score

    if melhor_score >= 2.0:
        return melhor, melhor_score
    return None, melhor_score


def build_library_index(library_dir):
    idx = {}
    for p in sorted(Path(library_dir).rglob("material.yaml")):
        spec = load_yaml(str(p))
        slug = str(p.parent.relative_to(library_dir))
        apelidos = list(spec.get("aliases") or [])
        apelidos += [spec.get("name", ""), p.parent.name]
        idx[slug] = [a for a in apelidos if a]
    return idx


def print_survey(report, job, library_dir):
    lev = report.get("etapas", {}).get("levantamento", {})
    mats = lev.get("materiais", [])
    idx = build_library_index(library_dir)
    bar = "  " + "=" * 78

    print(bar)
    print(f"  MATERIAIS DO MODELO: {job['project_name']}")
    print(f"  {len(mats)} materiais, {lev.get('area_total_m2', 0):,.0f} m2 de superficie")
    print(bar)
    print(f"\n  {'area m2':>9} {'%':>6}  {'material no SketchUp':<34} {'sugestao':<30} conf")
    print("  " + "-" * 78)

    sugestoes, sem_palpite = [], []
    for m in mats:
        # LUZ_* nao vem da biblioteca: vira emissor pelo proprio nome
        if m["nome"].upper().startswith(("LUZ_", "LUZ-")):
            print(
                f"  {m['area_m2']:>9,.1f} {m['percentual']:>5.1f}% L "
                f"{m['nome'][:33]:<34} {'(emissor automatico)':<30} ok"
            )
            continue

        slug, score = suggest_material(m["nome"], idx)
        conf = "alta" if score >= 3.0 else ("media" if score >= 2.0 else "-")
        marca = "T" if m["tem_textura"] else " "
        if m["nome_automatico"]:
            marca = "!"
        print(
            f"  {m['area_m2']:>9,.1f} {m['percentual']:>5.1f}% {marca} "
            f"{m['nome'][:33]:<34} {(slug or '???')[:29]:<30} {conf}"
        )
        (sugestoes if slug else sem_palpite).append((m, slug))

    print("  " + "-" * 78)
    print("  T = ja tem textura no modelo   L = luminaria   ! = nome automatico do SketchUp\n")

    # quais materiais realmente merecem textura PBR de verdade
    corte, soma = [], 0.0
    for m in mats:
        corte.append(m)
        soma += m["percentual"]
        if soma >= 80.0:
            break
    print(f"  ONDE VALE GASTAR TEXTURA PBR DE VERDADE")
    print(f"    {len(corte)} materiais cobrem {soma:.0f}% da superficie do projeto:")
    for m in corte:
        print(f"      {m['percentual']:>5.1f}%  {m['nome']}")
    if len(mats) > len(corte):
        print(f"    os outros {len(mats) - len(corte)} podem ficar procedurais sem prejuizo.")

    if lev.get("objetos_sem_material"):
        print(
            f"\n  ATENCAO: {lev['objetos_sem_material']} objetos sem material nenhum "
            f"({lev['faces_sem_material']:,.1f} m2). Vao renderizar cinza."
        )

    print("\n" + bar)
    print("  RASCUNHO PARA O project.yaml (confira antes de colar)")
    print(bar + "\n")
    print("materials:")
    for m, slug in sugestoes:
        print(f'  "{m["nome"]}": {slug:<40} # {m["percentual"]:.1f}% da area')
    if sem_palpite:
        print("\n  # sem palpite, escolha na mao (./render --list-materials):")
        for m, _ in sem_palpite:
            print(f'  # "{m["nome"]}": ???                      # {m["percentual"]:.1f}% da area')
    print()


def print_diagnosis(report, job):
    """Laudo do modelo antes de gastar um segundo de GPU.

    Responde a unica pergunta que importa no primeiro contato com um .skp:
    esse modelo esta apto a virar render, ou o trabalho e outro?
    """
    et = report.get("etapas", {})
    diag = et.get("diagnostico", {})
    esc = et.get("escala", {})
    mat = et.get("materiais", {})
    bar = "  " + "=" * 64

    print(bar)
    print(f"  DIAGNOSTICO DO MODELO: {job['project_name']}")
    print(bar)

    print("\n  GEOMETRIA")
    print(f"    objetos            {diag.get('objetos', 0):,}")
    print(f"    triangulos         {diag.get('triangulos', 0):,}")
    tri = diag.get("triangulos", 0)
    if tri > 8_000_000:
        print("      ! muito pesado. Risco alto de estourar memoria em 8 GB.")
    elif tri > 2_000_000:
        print("      ! pesado. Vai renderizar, mas devagar em maquina modesta.")
    for h in diag.get("objetos_pesados", [])[:5]:
        print(f"      objeto pesado: {h['objeto']} ({h['triangulos']:,} triangulos)")

    print("\n  ESCALA")
    d = esc.get("dimensoes_m", [0, 0, 0])
    print(f"    dimensoes          {d[0]} x {d[1]} x {d[2]} m")
    print(f"    altura total       {esc.get('altura_z_m')} m")
    print(f"    veredito           {'OK' if esc.get('ok') else 'PROBLEMA'}")
    for pr in esc.get("problemas", []):
        print(f"      ! {pr}")
    for s in esc.get("sugestoes", []):
        print(f"      -> {s}")

    print("\n  MATERIAIS")
    print(f"    total no modelo    {mat.get('total_materiais', 0)}")
    print(f"    mapeados           {len(mat.get('mapeados', []))}")
    print(f"    luminarias (LUZ_)  {len(mat.get('emissores', []))}")
    sem = mat.get("sem_mapeamento", [])
    print(f"    SEM mapeamento     {len(sem)}")
    for n in sem[:20]:
        print(f"      - {n}")
    if len(sem) > 20:
        print(f"      ... e mais {len(sem) - 20}")

    cams = et.get("cameras_disponiveis", [])
    print(f"\n  CAMERAS ({len(cams)})")
    for c in cams:
        marca = "  [dois pontos]" if c.get("dois_pontos") else ""
        print(f"    {c.get('slug', '?'):<26} {c.get('nome', '?')}{marca}")

    print("\n  VEREDITO")
    if not esc.get("ok"):
        print("    BLOQUEADO. Corrija a escala na exportacao antes de qualquer render.")
    elif len(sem) > len(mat.get("mapeados", [])):
        print("    ATENCAO. A maior parte dos materiais nao tem mapeamento.")
        print("    O render vai rodar, mas com acabamento generico.")
        print("    Renomeie no SketchUp ou amplie o materials: do project.yaml.")
    else:
        print("    APTO. Pode renderizar.")
    print(bar + "\n")


def main():
    p = argparse.ArgumentParser(
        prog="render",
        description="Renderiza projetos de interiores sem alterar a geometria.",
    )
    p.add_argument("--project", "-p", help="nome da pasta em projects/")
    p.add_argument("--camera", "-c", help="slug da camera, ou varios separados por virgula")
    p.add_argument("--all", "-a", action="store_true", help="renderiza todas as cameras")
    p.add_argument("--lighting", "-l", help="preset de iluminacao")
    p.add_argument("--quality", "-q", help="preset de qualidade (preview, final)")
    p.add_argument("--hour", type=float, help="hora do dia, sobrescreve o preset")
    p.add_argument("--date", help="data YYYY-MM-DD para a posicao do sol")
    p.add_argument("--resolution", help="por exemplo 1920x1080")
    p.add_argument("--samples", type=int)
    p.add_argument("--time-limit", type=int, help="teto de segundos por imagem")
    p.add_argument("--device", choices=["auto", "cpu", "gpu"])
    p.add_argument("--force", action="store_true", help="ignora falha de validacao de escala")
    p.add_argument("--dry-run", action="store_true", help="mostra o job e nao renderiza")
    p.add_argument(
        "--diagnose",
        action="store_true",
        help="importa o modelo, mede escala, lista materiais e cameras, e NAO renderiza",
    )
    p.add_argument(
        "--survey",
        action="store_true",
        help="lista os materiais do modelo por area e sugere o mapeamento do project.yaml",
    )
    p.add_argument("--list-materials", action="store_true")
    p.add_argument("--list-cameras", action="store_true")
    args = p.parse_args()

    if args.list_materials:
        print("\n  biblioteca de materiais:\n")
        for rel, label, kind in list_library(str(ROOT / "materials")):
            print(f"    {rel:<42} {label:<28} [{kind}]")
        print()
        return

    if not args.project:
        p.error("--project e obrigatorio")

    job, project, project_dir = build_job(args)

    if args.list_cameras:
        print(f"\n  cameras de {args.project}:\n")
        for c in job["cameras"]:
            print(f"    {c['slug']:<24} {c['name']:<28} proxima versao {c['version']}")
        print()
        return

    run_dir = project_dir / ".run"
    run_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job_path = run_dir / f"job-{stamp}.json"
    job["report_path"] = str(run_dir / f"report-{stamp}.json")
    job["diagnose_only"] = args.diagnose
    job["survey_only"] = args.survey
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)

    print(f"\n  projeto     {job['project_name']}")
    print(f"  modelo      {os.path.basename(job['source']['model'])}")
    print(f"  iluminacao  {job['lighting']['name']}")
    print(f"  qualidade   {args.quality or project.get('render', {}).get('quality', 'preview')}"
          f"  ({job['quality'].get('samples')} amostras)")
    print(f"  resolucao   {job['render']['resolution'][0]}x{job['render']['resolution'][1]}")
    print(f"  cameras     {', '.join(c['slug'] + ' ' + c['version'] for c in job['cameras'])}")
    print()

    if args.dry_run:
        print(f"  dry-run, job escrito em {job_path}\n")
        return

    blender = find_blender()
    cmd = [blender, "-b", "-P", str(ROOT / "blender" / "run_render.py"), "--", str(job_path)]
    t0 = time.time()
    proc = subprocess.run(cmd)
    elapsed = time.time() - t0

    report_path = job["report_path"]
    if not os.path.exists(report_path):
        die(f"o Blender terminou sem relatorio (codigo {proc.returncode}).")

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    if args.survey:
        print_survey(report, job, job["library_dir"])
        sys.exit(0 if report.get("sucesso") else 1)

    if args.diagnose:
        print_diagnosis(report, job)
        sys.exit(0 if report.get("sucesso") else 1)

    # snapshot da configuracao junto de cada imagem, para reproduzir depois
    for r in report.get("renders", []):
        version_dir = Path(r["arquivo"]).parent
        snap = {
            k: job[k]
            for k in ("lighting", "quality", "render", "materials", "north_angle_deg", "location")
        }
        snap["camera"] = next(
            (c for c in job["cameras"] if c["slug"] == r["slug"]), None
        )
        snap["gerado_em"] = datetime.now().isoformat(timespec="seconds")
        with open(version_dir / "config.snapshot.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump(snap, f, allow_unicode=True, sort_keys=False)
        update_latest(str(version_dir.parent), version_dir.name)

    index = project_dir / "renders" / "index.jsonl"
    index.parent.mkdir(exist_ok=True)
    with open(index, "a", encoding="utf-8") as f:
        for r in report.get("renders", []):
            f.write(json.dumps({
                "quando": datetime.now().isoformat(timespec="seconds"),
                "camera": r["slug"],
                "versao": Path(r["arquivo"]).parent.name,
                "iluminacao": job["lighting"]["name"],
                "amostras": job["quality"].get("samples"),
                "segundos": r["segundos"],
                "arquivo": r["arquivo"],
            }, ensure_ascii=False) + "\n")

    print("\n  " + "-" * 62)
    for r in report.get("renders", []):
        rel = os.path.relpath(r["arquivo"], ROOT)
        print(f"  {r['slug']:<20} {r['segundos']:>7.1f}s   {rel}")
    for a in report.get("avisos", []):
        print(f"  aviso: {a}")
    for e in report.get("erros", []):
        print(f"  ERRO:  {e}")
    print(f"  {'-' * 62}")
    print(f"  total {elapsed:.1f}s   relatorio: {os.path.relpath(report_path, ROOT)}\n")

    sys.exit(0 if report.get("sucesso") else 1)


if __name__ == "__main__":
    main()
