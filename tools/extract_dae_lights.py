#!/usr/bin/env python3
"""Extrai do DAE a posicao das luminarias que a arquiteta colocou no modelo.

Por que isso existe:

A arquiteta indica a iluminacao no SketchUp com componentes (aqui,
`V-Ray_IES_Light_4000K` e `V-Ray_Mesh_Light_4000K`). Essa informacao e
preciosa: e o projeto luminotecnico dela, e nao se adivinha.

Dois problemas no caminho:
  1. O Blender 5.x nao importa Collada, entao o DAE passa pelo assimp, que
     DESTROI os nomes dos objetos (viram `$ColladaAutoName$_N`).
  2. Mesmo com nome, componente de luz do V-Ray e geometria, nao e luz.

A solucao e ler o XML do DAE direto, achar as instancias dos componentes de
luz e gravar a posicao de cada uma em metros. Depois o pipeline cria luz de
verdade do Cycles nessas posicoes, que amostra muito melhor que geometria
emissiva.

    python3 tools/extract_dae_lights.py modelo.dae lights.json
"""

import json
import re
import sys
import xml.etree.ElementTree as ET

NS = {"c": "http://www.collada.org/2005/11/COLLADASchema"}

# Nome do componente -> como tratar no render
PADROES = [
    (re.compile(r"ies", re.I), "spot"),
    (re.compile(r"mesh.?light", re.I), "area"),
    (re.compile(r"(spot|foco)", re.I), "spot"),
    (re.compile(r"(luz|light|lumin|led)", re.I), "point"),
]

KELVIN = re.compile(r"(\d{3,5})\s*K", re.I)


def identity():
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def matmul(a, b):
    out = [0.0] * 16
    for i in range(4):
        for j in range(4):
            out[i * 4 + j] = sum(a[i * 4 + k] * b[k * 4 + j] for k in range(4))
    return out


def parse_matrix(node):
    """Matriz local do node: produto de <matrix>/<translate>/<rotate>/<scale>."""
    m = identity()
    for child in node:
        tag = child.tag.split("}")[-1]
        if tag == "matrix":
            vals = [float(v) for v in child.text.split()]
            if len(vals) == 16:
                m = matmul(m, vals)
        elif tag == "translate":
            x, y, z = (float(v) for v in child.text.split())
            t = identity()
            t[3], t[7], t[11] = x, y, z
            m = matmul(m, t)
        elif tag == "scale":
            x, y, z = (float(v) for v in child.text.split())
            s = identity()
            s[0], s[5], s[10] = x, y, z
            m = matmul(m, s)
    return m


def classify(name):
    for padrao, tipo in PADROES:
        if padrao.search(name):
            return tipo
    return None


def extract(dae_path):
    tree = ET.parse(dae_path)
    root = tree.getroot()

    # fator de unidade declarado no proprio arquivo
    unit = root.find(".//c:asset/c:unit", NS)
    escala = float(unit.get("meter", 1.0)) if unit is not None else 1.0

    biblioteca = {}
    for lib in root.findall(".//c:library_nodes", NS):
        for node in lib.findall("c:node", NS):
            biblioteca[node.get("id")] = node

    encontradas = []
    vistos = set()

    def visitar(node, mundo, heranca, profundidade=0):
        if profundidade > 24:
            return
        nome = node.get("name") or node.get("id") or ""
        local = matmul(mundo, parse_matrix(node))
        rotulo = heranca or (nome if classify(nome) else None)

        if rotulo and (node.find("c:instance_geometry", NS) is not None):
            chave = (rotulo, round(local[3], 4), round(local[7], 4), round(local[11], 4))
            if chave not in vistos:
                vistos.add(chave)
                k = KELVIN.search(rotulo)
                encontradas.append({
                    "componente": rotulo,
                    "tipo": classify(rotulo),
                    "posicao_m": [
                        round(local[3] * escala, 4),
                        round(local[7] * escala, 4),
                        round(local[11] * escala, 4),
                    ],
                    # 3a coluna da matriz e o eixo Z local do componente
                    "eixo_z": [round(local[2], 5), round(local[6], 5), round(local[10], 5)],
                    "temperature_k": int(k.group(1)) if k else None,
                })

        for filho in node.findall("c:node", NS):
            visitar(filho, local, rotulo, profundidade + 1)

        for inst in node.findall("c:instance_node", NS):
            url = (inst.get("url") or "").lstrip("#")
            alvo = biblioteca.get(url)
            if alvo is not None:
                nome_alvo = alvo.get("name") or ""
                visitar(alvo, local, rotulo or (nome_alvo if classify(nome_alvo) else None),
                        profundidade + 1)

    for cena in root.findall(".//c:library_visual_scenes/c:visual_scene", NS):
        for node in cena.findall("c:node", NS):
            visitar(node, identity(), None)

    return {"escala_do_arquivo": escala, "luminarias": encontradas}


def main():
    if len(sys.argv) < 3:
        raise SystemExit("uso: extract_dae_lights.py <modelo.dae> <lights.json>")

    dados = extract(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    luzes = dados["luminarias"]
    print(f"\n  {len(luzes)} luminarias encontradas no modelo\n")

    por_tipo = {}
    for l in luzes:
        por_tipo.setdefault((l["componente"], l["tipo"], l["temperature_k"]), []).append(l)
    for (comp, tipo, k), itens in sorted(por_tipo.items(), key=lambda kv: -len(kv[1])):
        print(f"    {len(itens):>3}x  {comp[:44]:<46} tipo={tipo:<6} {k or '?'}K")

    if luzes:
        zs = [l["posicao_m"][2] for l in luzes]
        print(f"\n    altura das luminarias: {min(zs):.2f} m a {max(zs):.2f} m")
    print()


if __name__ == "__main__":
    main()
