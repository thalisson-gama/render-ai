#!/usr/bin/env python3
"""Extrai texturas e escalas fisicas de dentro de um .skp, sem abrir o SketchUp.

Desde a versao 2021 o .skp e um contêiner ZIP. A geometria fica em `model.dat`,
que e binario proprietario e continua ilegivel. Mas as TEXTURAS e os
`material.xml` estao em claro, e o XML guarda o dado mais valioso que existe
para realismo: o tamanho fisico real do ladrilho.

    <mat:texture xScale="16.909448818897637" yScale="2.106299212598425">

Isso e polegada. 16,909 x 0,0254 = 0,4295 m e 2,106 x 0,0254 = 0,0535 m, ou
seja um revestimento de 43 x 5,3 cm, exatamente o que o nome do produto diz.

Textura fora de escala e a maior causa isolada de render com cara de
videogame, e aqui ela vem de graca, medida, direto do arquivo da arquiteta.

    python3 tools/extract_skp.py "projeto.skp" projects/meu-projeto/source
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

INCH_TO_M = 0.0254
NS = {"mat": "http://sketchup.google.com/schemas/sketchup/1.0/material"}

# Palavras no nome que dizem o acabamento. Serve para o pipeline saber que
# "BR" (brilhante) reflete e "AC" (acetinado) nao.
ACABAMENTO = [
    (("polido", "polida", "-pl-", " pl ", "brilhante", "-br-", "lux"), 0.06),
    (("acetinado", "-ac-", "satin", "seda"), 0.22),
    (("natural", "-na-", "mate", "matte", "fosco", "fosca"), 0.55),
    (("externo", "antiderrapante", "rustico"), 0.75),
]


def texture_roughness_hint(name):
    low = " " + name.lower().replace("_", " ") + " "
    for chaves, rough in ACABAMENTO:
        if any(k in low for k in chaves):
            return rough
    return None


def safe_dirname(name):
    s = re.sub(r"[^0-9a-zA-Z._,\- ]+", "_", name).strip().strip(".")
    return s or "material"


def parse_material_xml(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None

    mat = root.find("mat:material", NS)
    if mat is None:
        return None

    info = {
        "nome": mat.get("name"),
        "cor": [
            int(mat.get("colorRed", 255)) / 255.0,
            int(mat.get("colorGreen", 255)) / 255.0,
            int(mat.get("colorBlue", 255)) / 255.0,
        ],
        "tem_textura": mat.get("hasTexture") == "1",
        "textura": None,
        "tile_m": None,
        "origem": None,
    }

    tex = mat.find("mat:texture", NS)
    if tex is not None:
        xs = float(tex.get("xScale", 0) or 0)
        ys = float(tex.get("yScale", 0) or 0)
        if xs > 0 and ys > 0:
            info["tile_m"] = [round(xs * INCH_TO_M, 5), round(ys * INCH_TO_M, 5)]
        info["origem"] = tex.get("textureFilename")
        img = tex.find("mat:images/mat:image", NS)
        if img is not None:
            info["textura"] = os.path.basename(img.get("path", ""))

    return info


def extract(skp_path, out_dir):
    if not zipfile.is_zipfile(skp_path):
        raise SystemExit(
            "Este .skp nao e um contêiner ZIP (SketchUp anterior a 2021). "
            "Nesse caso so da para extrair exportando pelo proprio SketchUp."
        )

    tex_dir = os.path.join(out_dir, "textures")
    os.makedirs(tex_dir, exist_ok=True)

    z = zipfile.ZipFile(skp_path)
    materiais, extraidas = [], 0

    por_material = {}
    for n in z.namelist():
        m = re.match(r"materials/([^/]+)/(.+)$", n)
        if m:
            por_material.setdefault(m.group(1), []).append((m.group(2), n))

    for pasta, arquivos in sorted(por_material.items()):
        info = None
        for base, full in arquivos:
            if base == "material.xml":
                info = parse_material_xml(z.read(full))
        if info is None:
            continue

        for base, full in arquivos:
            if base.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tga")):
                destino_nome = f"{safe_dirname(pasta)}__{base}"
                destino = os.path.join(tex_dir, destino_nome)
                with open(destino, "wb") as f:
                    f.write(z.read(full))
                info["arquivo"] = os.path.join("textures", destino_nome)
                extraidas += 1
                break

        info["roughness_sugerida"] = texture_roughness_hint(info["nome"] or pasta)
        materiais.append(info)

    # cenas: prova visual de que camera existe, util antes mesmo do export
    cenas = []
    for n in z.namelist():
        m = re.match(r"scene_thumbnails/(.+)\.png$", n)
        if m:
            destino = os.path.join(out_dir, "cenas_sketchup", m.group(1) + ".png")
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "wb") as f:
                f.write(z.read(n))
            cenas.append(m.group(1))

    manifesto = {
        "arquivo_skp": os.path.basename(skp_path),
        "versao_sketchup": _versao(z),
        "materiais": sorted(materiais, key=lambda d: (d["nome"] or "").lower()),
        "cenas_no_arquivo": sorted(cenas),
        "com_textura": sum(1 for m in materiais if m.get("arquivo")),
        "com_escala_fisica": sum(1 for m in materiais if m.get("tile_m")),
    }

    saida = os.path.join(out_dir, "skp_materials.json")
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(manifesto, f, ensure_ascii=False, indent=2)

    return manifesto, saida, extraidas


def _versao(z):
    try:
        head = z.read("meta/meta.dat").decode("latin1")
        m = re.search(r"(\d{2}\.\d\.\d{3})", head)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def main():
    if len(sys.argv) < 3:
        raise SystemExit("uso: extract_skp.py <arquivo.skp> <pasta_source>")
    skp, out = sys.argv[1], sys.argv[2]
    manifesto, saida, n = extract(skp, out)

    print(f"\n  SketchUp {manifesto['versao_sketchup']}")
    print(f"  {len(manifesto['materiais'])} materiais, {n} texturas extraidas")
    print(f"  {manifesto['com_escala_fisica']} com escala fisica conhecida")
    print(f"  cenas no arquivo: {', '.join(manifesto['cenas_no_arquivo']) or 'nenhuma'}")
    print(f"\n  manifesto: {saida}\n")

    com_escala = [m for m in manifesto["materiais"] if m.get("tile_m") and m.get("arquivo")]
    com_escala.sort(key=lambda d: -(d["tile_m"][0] * d["tile_m"][1]))
    print(f"  {'material':<46} {'tamanho real do ladrilho':<26} rugosidade")
    print("  " + "-" * 84)
    for m in com_escala[:25]:
        tx, ty = m["tile_m"]
        r = m.get("roughness_sugerida")
        print(
            f"  {(m['nome'] or '?')[:45]:<46} "
            f"{tx * 100:>7.1f} x {ty * 100:<6.1f} cm        "
            f"{('%.2f' % r) if r is not None else '-'}"
        )
    if len(com_escala) > 25:
        print(f"  ... mais {len(com_escala) - 25}")
    print()


if __name__ == "__main__":
    main()
