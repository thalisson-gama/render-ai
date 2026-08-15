"""Bind de materiais: nome do material no modelo -> material PBR da biblioteca.

O contrato do sistema inteiro esta aqui. A arquiteta nomeia um material de
"BANCADA" no SketchUp; o project.yaml diz que BANCADA e `pedras/taj-mahal`;
este modulo reconstroi o shader. Nenhuma geometria e tocada.

Escala das texturas usa a POSICAO DE MUNDO (metros reais), entao um veio de
1,6 m tem 1,6 m na cena, independente de UV do SketchUp.
"""

import os
import re

import bpy

EMISSION_NAME = re.compile(r"^LUZ[_-]", re.IGNORECASE)
TEMP_IN_NAME = re.compile(r"(\d{4})\s*K", re.IGNORECASE)


def normalize(name):
    """`BANCADA.001` e `BANCADA` sao o mesmo material para nos."""
    return re.sub(r"\.\d{3}$", "", (name or "").strip()).upper()


# --------------------------------------------------------------------------
# blocos de no reutilizaveis
# --------------------------------------------------------------------------

def _fresh(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (280, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return nt, bsdf


def _world_coords(nt, scale_m, location=(-1000, 0), vertical_m=None, rotate_deg=0.0):
    """Coordenada de mundo em metros, dividida pelo tamanho do padrao.

    `scale_m` e a dimensao horizontal do ladrilho. `vertical_m`, quando
    informado, e a dimensao vertical. Ladrilho 43 x 5,3 cm precisa de escala
    diferente em X/Y e em Z; usar um numero so faz um ripado de 5 cm virar
    placa de 43 cm, que e erro grosseiro e passa despercebido em preview.
    """
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.location = location
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.location = (location[0] + 200, location[1])

    sx = max(float(scale_m), 1e-4)
    sz = max(float(vertical_m if vertical_m else scale_m), 1e-4)
    mapping.inputs["Scale"].default_value = (1.0 / sx, 1.0 / sx, 1.0 / sz)
    if rotate_deg:
        import math as _m

        mapping.inputs["Rotation"].default_value = (0.0, 0.0, _m.radians(rotate_deg))

    nt.links.new(geo.outputs["Position"], mapping.inputs["Vector"])
    return mapping.outputs["Vector"]


def _uv_coords(nt, location=(-1000, 0), scale=(1.0, 1.0), rotate_deg=0.0):
    """UV que veio do modelo. Preferivel quando a arquiteta ja texturizou.

    Ela posicionou e girou a textura no SketchUp; o UV carrega essa decisao.
    Projecao por posicao de mundo joga esse trabalho fora.
    """
    coord = nt.nodes.new("ShaderNodeTexCoord")
    coord.location = location
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.location = (location[0] + 200, location[1])
    mapping.inputs["Scale"].default_value = (scale[0], scale[1], 1.0)
    if rotate_deg:
        import math as _m

        mapping.inputs["Rotation"].default_value = (0.0, 0.0, _m.radians(rotate_deg))
    nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])
    return mapping.outputs["Vector"]


def _set(bsdf, socket, value):
    if socket in bsdf.inputs and value is not None:
        bsdf.inputs[socket].default_value = value


def _rgba(color, alpha=1.0):
    r, g, b = color
    return (float(r), float(g), float(b), float(alpha))


# --------------------------------------------------------------------------
# construtores por tipo
# --------------------------------------------------------------------------

def _build_plain(nt, bsdf, spec):
    _set(bsdf, "Base Color", _rgba(spec.get("base_color", [0.8, 0.8, 0.8])))
    _set(bsdf, "Roughness", spec.get("roughness", 0.5))
    _set(bsdf, "Metallic", spec.get("metallic", 0.0))


def _build_wood(nt, bsdf, spec):
    # `board_m` e a escala da peca (tabua). `grain_per_m` e quantas veias
    # cabem em um metro: madeira real tem de 40 a 80, ou seja veia de 1 a
    # 2,5 cm. Usar escala de metro aqui vira mancha marrom, nao madeira.
    board_m = float(spec.get("board_m", spec.get("scale_m", 1.0)))
    vec = _world_coords(nt, board_m)

    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.location = (-600, -260)
    noise.inputs["Scale"].default_value = 2.2
    noise.inputs["Detail"].default_value = 6.0
    nt.links.new(vec, noise.inputs["Vector"])

    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.location = (-380, 0)
    wave.wave_type = "BANDS"
    wave.bands_direction = spec.get("grain_direction", "X").upper()
    wave.wave_profile = "SIN"
    wave.inputs["Scale"].default_value = (
        float(spec.get("grain_per_m", 55.0)) * board_m
    )
    wave.inputs["Distortion"].default_value = spec.get("grain_distortion", 2.5)
    wave.inputs["Detail"].default_value = 3.0
    wave.inputs["Detail Scale"].default_value = 1.4
    wave.inputs["Detail Roughness"].default_value = 0.55
    nt.links.new(vec, wave.inputs["Vector"])

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-160, 0)
    contrast = float(spec.get("contrast", 0.35))
    ramp.color_ramp.elements[0].position = max(0.0, 0.5 - contrast)
    ramp.color_ramp.elements[1].position = min(1.0, 0.5 + contrast)
    ramp.color_ramp.elements[0].color = _rgba(spec.get("base_color", [0.32, 0.18, 0.10]))
    ramp.color_ramp.elements[1].color = _rgba(
        spec.get("secondary_color", spec.get("base_color", [0.20, 0.11, 0.06]))
    )
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    # variacao sutil de rugosidade: madeira nunca e uniforme
    rough = nt.nodes.new("ShaderNodeMapRange")
    rough.location = (-160, -260)
    base_r = float(spec.get("roughness", 0.38))
    rough.inputs["To Min"].default_value = max(0.02, base_r - 0.08)
    rough.inputs["To Max"].default_value = min(1.0, base_r + 0.08)
    nt.links.new(noise.outputs["Fac"], rough.inputs["Value"])
    nt.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (60, -420)
    bump.inputs["Strength"].default_value = float(spec.get("bump", 0.06))
    nt.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    _set(bsdf, "Coat Weight", spec.get("coat", 0.0))
    _set(bsdf, "Coat Roughness", spec.get("coat_roughness", 0.1))


def _build_stone(nt, bsdf, spec):
    scale_m = spec.get("scale_m", 1.6)
    vec = _world_coords(nt, scale_m)

    veins = nt.nodes.new("ShaderNodeTexNoise")
    veins.location = (-600, 0)
    veins.inputs["Scale"].default_value = 1.6
    veins.inputs["Detail"].default_value = 8.0
    veins.inputs["Roughness"].default_value = 0.62
    if "Distortion" in veins.inputs:
        veins.inputs["Distortion"].default_value = 2.4
    nt.links.new(vec, veins.inputs["Vector"])

    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-360, 0)
    contrast = float(spec.get("contrast", 0.16))
    ramp.color_ramp.elements[0].position = max(0.0, 0.5 - contrast)
    ramp.color_ramp.elements[1].position = min(1.0, 0.5 + contrast)
    ramp.color_ramp.elements[0].color = _rgba(spec.get("base_color", [0.86, 0.82, 0.74]))
    ramp.color_ramp.elements[1].color = _rgba(
        spec.get("vein_color", spec.get("secondary_color", [0.55, 0.48, 0.40]))
    )
    nt.links.new(veins.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    _set(bsdf, "Roughness", spec.get("roughness", 0.18))
    _set(bsdf, "Metallic", 0.0)
    _set(bsdf, "Coat Weight", spec.get("coat", 0.25))
    _set(bsdf, "Coat Roughness", spec.get("coat_roughness", 0.06))

    if spec.get("bump"):
        bump = nt.nodes.new("ShaderNodeBump")
        bump.location = (60, -420)
        bump.inputs["Strength"].default_value = float(spec["bump"])
        nt.links.new(veins.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_fabric(nt, bsdf, spec):
    scale_m = spec.get("scale_m", 0.02)
    vec = _world_coords(nt, scale_m)

    weave = nt.nodes.new("ShaderNodeTexNoise")
    weave.location = (-600, 0)
    weave.inputs["Scale"].default_value = 8.0
    weave.inputs["Detail"].default_value = 6.0
    nt.links.new(vec, weave.inputs["Vector"])

    _set(bsdf, "Base Color", _rgba(spec.get("base_color", [0.62, 0.56, 0.46])))
    _set(bsdf, "Roughness", spec.get("roughness", 0.85))
    _set(bsdf, "Sheen Weight", spec.get("sheen", 0.35))
    _set(bsdf, "Sheen Roughness", spec.get("sheen_roughness", 0.35))

    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (60, -420)
    bump.inputs["Strength"].default_value = float(spec.get("bump", 0.22))
    nt.links.new(weave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _build_metal(nt, bsdf, spec):
    _set(bsdf, "Base Color", _rgba(spec.get("base_color", [0.56, 0.57, 0.58])))
    _set(bsdf, "Metallic", spec.get("metallic", 1.0))
    _set(bsdf, "Roughness", spec.get("roughness", 0.28))

    if spec.get("brushed"):
        vec = _world_coords(nt, spec.get("scale_m", 0.4))
        wave = nt.nodes.new("ShaderNodeTexWave")
        wave.location = (-380, -260)
        wave.wave_type = "BANDS"
        wave.bands_direction = "Y"
        wave.inputs["Scale"].default_value = 40.0
        wave.inputs["Distortion"].default_value = 2.0
        nt.links.new(vec, wave.inputs["Vector"])
        rough = nt.nodes.new("ShaderNodeMapRange")
        rough.location = (-160, -260)
        base_r = float(spec.get("roughness", 0.28))
        rough.inputs["To Min"].default_value = max(0.02, base_r - 0.10)
        rough.inputs["To Max"].default_value = min(1.0, base_r + 0.10)
        nt.links.new(wave.outputs["Fac"], rough.inputs["Value"])
        nt.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])


def _build_glass(nt, bsdf, spec):
    _set(bsdf, "Base Color", _rgba(spec.get("base_color", [1.0, 1.0, 1.0])))
    _set(bsdf, "Roughness", spec.get("roughness", 0.02))
    _set(bsdf, "Metallic", 0.0)
    _set(bsdf, "IOR", spec.get("ior", 1.52))
    _set(bsdf, "Transmission Weight", spec.get("transmission", 1.0))
    # Vidro de esquadria costuma ser modelado como plano unico no SketchUp.
    # "Thin Wall" evita que o Cycles trate isso como um bloco solido de vidro.
    _set(bsdf, "Thin Wall", bool(spec.get("thin_wall", True)))

    if not spec.get("shadow_pass_through", True):
        return

    # Sol direto atravessando vidro refrativo e, tecnicamente, uma caustica.
    # O Cycles nao amostra caustica por padrao, entao o resultado e um
    # ambiente sem mancha de sol no piso: parece dia nublado dentro de casa.
    #
    # Solucao padrao de arch-viz: para RAIO DE SOMBRA o vidro vira Transparent,
    # deixando a luz passar reta. Para a camera e para reflexo continua vidro
    # de verdade. Sem isso, nenhuma cena com janela fica certa.
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (280, -220)
    path = nt.nodes.new("ShaderNodeLightPath")
    path.location = (60, 320)
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.location = (450, 0)

    nt.links.new(path.outputs["Is Shadow Ray"], mix.inputs["Fac"])
    nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    nt.links.new(transparent.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])


def _kelvin_node(nt, bsdf, temperature_k, wb_gain=None):
    """Cor da luminaria. Com balanco de branco, vira cor fixa ja corrigida.

    Sem isso, um banheiro iluminado so por LED de 4000K sai laranja: e o
    fisicamente correto e o fotograficamente errado.
    """
    if wb_gain:
        from .lighting import _apply_gain, _kelvin_to_rgb

        cor = _apply_gain(_kelvin_to_rgb(float(temperature_k)), wb_gain)
        bsdf.inputs["Emission Color"].default_value = (*cor, 1.0)
        return
    bb = nt.nodes.new("ShaderNodeBlackbody")
    bb.location = (60, 200)
    bb.inputs["Temperature"].default_value = float(temperature_k)
    nt.links.new(bb.outputs["Color"], bsdf.inputs["Emission Color"])


def _build_emission(nt, bsdf, spec):
    _set(bsdf, "Base Color", _rgba([0.05, 0.05, 0.05]))
    _set(bsdf, "Roughness", 0.5)
    _kelvin_node(nt, bsdf, spec.get("temperature_k", 3000), spec.get("_wb_gain"))
    _set(bsdf, "Emission Strength", spec.get("emission_strength", 12.0))


def _build_maps(nt, bsdf, spec, base_dir):
    """Material a partir de textura real.

    Aceita dois modos de coordenada:
      projection: uv   -> usa o UV do modelo (padrao quando ela texturizou)
      projection: box  -> projeta por posicao de mundo em escala fisica
    """
    tile = spec.get("tile_size_m") or [1.0, 1.0]
    if not isinstance(tile, (list, tuple)):
        tile = [tile, tile]
    modo = str(spec.get("projection", "uv")).lower()
    rot = float(spec.get("rotate_deg", 0.0))

    if modo == "box":
        vec = _world_coords(nt, tile[0], vertical_m=tile[1], rotate_deg=rot)
        proj = "BOX"
    else:
        uvs = spec.get("uv_scale") or [1.0, 1.0]
        vec = _uv_coords(nt, scale=(float(uvs[0]), float(uvs[1])), rotate_deg=rot)
        proj = "FLAT"

    maps = spec.get("maps", {})

    def load(rel, non_color, y=0):
        if not rel:
            return None
        path = rel if os.path.isabs(rel) else os.path.join(base_dir, rel)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"material '{spec.get('name', '?')}' declara o mapa '{rel}' "
                f"mas o arquivo nao existe em {path}"
            )
        node = nt.nodes.new("ShaderNodeTexImage")
        node.location = (-700, y)
        node.image = bpy.data.images.load(path, check_existing=True)
        node.projection = proj
        if proj == "BOX":
            node.projection_blend = float(spec.get("projection_blend", 0.25))
        node.extension = spec.get("extension", "REPEAT").upper()
        if non_color:
            node.image.colorspace_settings.name = "Non-Color"
        nt.links.new(vec, node.inputs["Vector"])
        return node

    base = load(maps.get("base_color", ""), non_color=False, y=200)
    if base:
        saturacao = float(spec.get("saturation", 1.0))
        brilho = float(spec.get("brightness", 1.0))
        saida = base.outputs["Color"]
        if saturacao != 1.0 or brilho != 1.0:
            hsv = nt.nodes.new("ShaderNodeHueSaturation")
            hsv.location = (-460, 200)
            hsv.inputs["Saturation"].default_value = saturacao
            hsv.inputs["Value"].default_value = brilho
            nt.links.new(saida, hsv.inputs["Color"])
            saida = hsv.outputs["Color"]
        nt.links.new(saida, bsdf.inputs["Base Color"])
    else:
        _set(bsdf, "Base Color", _rgba(spec.get("base_color", [0.8, 0.8, 0.8])))

    rough = load(maps.get("roughness", ""), non_color=True, y=-60)
    base_rough = float(spec.get("roughness", 0.5))
    if rough:
        nt.links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
    elif base and spec.get("roughness_from_base"):
        # Catalogo de fabricante vem so com difusa. Derivar uma variacao sutil
        # de rugosidade a partir da propria imagem quebra o aspecto de plastico
        # uniforme, sem inventar detalhe que nao existe.
        var = float(spec.get("roughness_variation", 0.08))
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.location = (-300, -60)
        mr.inputs["To Min"].default_value = max(0.01, base_rough - var)
        mr.inputs["To Max"].default_value = min(1.0, base_rough + var)
        nt.links.new(base.outputs["Color"], mr.inputs["Value"])
        nt.links.new(mr.outputs["Result"], bsdf.inputs["Roughness"])
    else:
        _set(bsdf, "Roughness", base_rough)

    nrm = load(maps.get("normal", ""), non_color=True, y=-320)
    if nrm:
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-300, -320)
        nmap.inputs["Strength"].default_value = float(spec.get("normal_strength", 1.0))
        nt.links.new(nrm.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    elif base and spec.get("bump_from_base"):
        bump = nt.nodes.new("ShaderNodeBump")
        bump.location = (-300, -320)
        bump.inputs["Strength"].default_value = float(spec["bump_from_base"])
        bump.inputs["Distance"].default_value = float(spec.get("bump_distance_m", 0.002))
        nt.links.new(base.outputs["Color"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    _set(bsdf, "Metallic", spec.get("metallic", 0.0))
    _set(bsdf, "IOR", spec.get("ior", 1.5))
    _set(bsdf, "Coat Weight", spec.get("coat", 0.0))
    _set(bsdf, "Coat Roughness", spec.get("coat_roughness", 0.05))


def _build_mirror(nt, bsdf, spec):
    """Espelho de verdade: metal quase perfeito, nao vidro transparente.

    Espelho comum tem a prata atras do vidro float, que e levemente esverdeado,
    entao a reflexao nunca e neutra. Quem faz espelho com transmissao acaba com
    ruido e com um vidro que deixa ver a parede atras.
    """
    _set(bsdf, "Base Color", _rgba(spec.get("base_color", [0.92, 0.95, 0.93])))
    _set(bsdf, "Metallic", 1.0)
    _set(bsdf, "Roughness", spec.get("roughness", 0.005))
    _set(bsdf, "Transmission Weight", 0.0)


BUILDERS = {
    "mirror": _build_mirror,
    "plain": _build_plain,
    "wood": _build_wood,
    "stone": _build_stone,
    "fabric": _build_fabric,
    "metal": _build_metal,
    "glass": _build_glass,
    "emission": _build_emission,
}


def build_material(mat, spec, base_dir=""):
    """Reescreve o shader de `mat` conforme a especificacao da biblioteca."""
    nt, bsdf = _fresh(mat)
    kind = (spec.get("kind") or "plain").lower()

    if kind == "maps":
        _build_maps(nt, bsdf, spec, base_dir)
    else:
        BUILDERS.get(kind, _build_plain)(nt, bsdf, spec)

    if kind == "glass":
        mat.use_backface_culling = False
    return mat


# --------------------------------------------------------------------------
# fallbacks para o que nao esta mapeado
# --------------------------------------------------------------------------

ROUGHNESS_HINTS = [
    (("vidro", "glass", "cristal"), None),
    (("espelho", "mirror"), 0.02),
    (("metal", "aco", "inox", "aluminio", "latao", "cromo"), 0.25),
    (("porcelanato", "ceramica", "marmore", "granito", "quartzo", "pedra"), 0.20),
    (("madeira", "wood", "mdf", "laminado", "freijo", "carvalho"), 0.40),
    (("tecido", "linho", "algodao", "veludo", "fabric"), 0.85),
    (("pintura", "parede", "gesso", "forro", "teto"), 0.65),
]


def guess_from_name(name):
    low = (name or "").lower()
    for keys, rough in ROUGHNESS_HINTS:
        if any(k in low for k in keys):
            if rough is None:
                return {"kind": "glass"}
            if rough == 0.25:
                return {"kind": "metal", "roughness": rough}
            return {"kind": "plain", "roughness": rough}
    return None


def preserve_existing(mat):
    """Mantem cor/textura que veio do modelo, so torna o shader plausivel.

    Usado quando o material nao esta mapeado. Melhor que cinza, pior que
    a biblioteca. Sempre reportado.
    """
    if not mat.use_nodes:
        return {"kind": "plain", "base_color": list(mat.diffuse_color[:3])}

    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return {"kind": "plain", "base_color": list(mat.diffuse_color[:3])}

    guess = guess_from_name(mat.name)
    if guess and guess.get("roughness") is not None:
        bsdf.inputs["Roughness"].default_value = guess["roughness"]
    elif guess and guess.get("kind") == "glass":
        _build_glass(nt, bsdf, {})
    else:
        # SketchUp exporta quase tudo com roughness 0.5 e specular alto,
        # o que da aquele plastico. 0.6 e um chute bem mais honesto.
        bsdf.inputs["Roughness"].default_value = 0.6
    return None


def texture_memory_report(max_px=None):
    """Mede (e opcionalmente limita) a memoria gasta com textura.

    O Cycles guarda imagem em ponto flutuante, entao 16 bytes por pixel, nao
    os 3 do JPEG. Um catalogo de 2000x2000 ocupa 64 MB na cena, nao 4 MB. Numa
    maquina de 8 GB de memoria unificada isso e o que estoura primeiro, antes
    de qualquer questao de velocidade.

    Reduzir a maior dimensao para 1024 px derruba a memoria em ~4x e e
    praticamente invisivel em revestimento visto de 2 m de distancia.
    """
    total_antes = total_depois = 0
    reduzidas = []

    for img in bpy.data.images:
        if img.size[0] == 0 or img.size[1] == 0:
            continue
        antes = img.size[0] * img.size[1] * 16
        total_antes += antes

        maior = max(img.size)
        if max_px and maior > max_px:
            fator = max_px / maior
            nx, ny = max(1, int(img.size[0] * fator)), max(1, int(img.size[1] * fator))
            try:
                img.scale(nx, ny)
                reduzidas.append({
                    "imagem": img.name,
                    "de": list(img.size[:2]) if img.size[0] else [nx, ny],
                    "para": [nx, ny],
                })
            except Exception:
                pass
        total_depois += img.size[0] * img.size[1] * 16

    return {
        "imagens": len([i for i in bpy.data.images if i.size[0]]),
        "memoria_antes_mb": round(total_antes / 1e6, 1),
        "memoria_depois_mb": round(total_depois / 1e6, 1),
        "limite_px": max_px,
        "reduzidas": len(reduzidas),
    }


def apply(material_specs, library_dir, artificial_lights=None, wb_gain=None):
    """Aplica a biblioteca a todos os materiais do arquivo.

    `material_specs`: {NOME_NORMALIZADO: {"slug":..., "spec":..., "dir":...}}
    Devolve relatorio com o que foi mapeado e o que caiu no fallback.
    """
    artificial_lights = artificial_lights or {}
    mapped, unmapped, emitters = [], [], []

    for mat in bpy.data.materials:
        if mat.name.startswith("Dot ") or mat.users == 0:
            continue
        key = normalize(mat.name)

        entry = material_specs.get(key)
        if entry:
            build_material(mat, entry["spec"], entry.get("dir", library_dir))
            mapped.append({"material": mat.name, "biblioteca": entry["slug"]})
            continue

        # luminarias por convencao de nome: LUZ_LED_3000K
        if EMISSION_NAME.match(mat.name):
            cfg = dict(artificial_lights.get(key, {}))
            m = TEMP_IN_NAME.search(mat.name)
            if m and "temperature_k" not in cfg:
                cfg["temperature_k"] = int(m.group(1))
            cfg.setdefault("temperature_k", 3000)
            cfg.setdefault("emission_strength", cfg.pop("power_w", 12.0))
            build_material(mat, {"kind": "emission", "_wb_gain": wb_gain, **cfg})
            emitters.append({"material": mat.name, "kelvin": cfg["temperature_k"]})
            continue

        preserve_existing(mat)
        unmapped.append(mat.name)

    return {
        "mapeados": mapped,
        "emissores": emitters,
        "sem_mapeamento": sorted(unmapped),
        "total_materiais": len(bpy.data.materials),
    }
