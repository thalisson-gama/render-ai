"""Camera: reconstroi no Blender exatamente o enquadramento do SketchUp.

Tres detalhes que quebram em silencio se forem ignorados:

1. O SketchUp mede o campo de visao no eixo VERTICAL ou no HORIZONTAL
   dependendo do formato da janela (`Camera#fov_is_height?`). Assumir sempre
   um dos dois deixa algumas cenas com enquadramento errado e outras certas,
   que e o pior tipo de bug.

2. Perspectiva de dois pontos (verticais retas) nao e uma camera comum. E
   camera nivelada com deslocamento de sensor. Sem isso, todo render sai com
   as paredes tombando, exatamente o que a arquiteta evita no SketchUp.

3. Camera do Blender olha para -Z com +Y para cima. A matriz precisa ser
   montada nessa ordem.
"""

import math

import bpy
from mathutils import Matrix, Vector

SENSOR_WIDTH_MM = 36.0
SENSOR_HEIGHT_MM = 24.0


def _look_at_matrix(eye, target, up):
    eye = Vector(eye)
    target = Vector(target)
    up = Vector(up)

    forward = target - eye
    if forward.length < 1e-9:
        raise ValueError("camera com eye igual a target")
    forward.normalize()

    right = forward.cross(up)
    if right.length < 1e-6:
        # olhando reto para cima ou para baixo: escolhe um "direita" qualquer
        right = forward.cross(Vector((0.0, 1.0, 0.0)))
        if right.length < 1e-6:
            right = forward.cross(Vector((1.0, 0.0, 0.0)))
    right.normalize()
    true_up = right.cross(forward)

    return Matrix((
        (right.x, true_up.x, -forward.x, eye.x),
        (right.y, true_up.y, -forward.y, eye.y),
        (right.z, true_up.z, -forward.z, eye.z),
        (0.0, 0.0, 0.0, 1.0),
    ))


def build(spec, resolution, overrides=None):
    """Cria e devolve o objeto camera para uma entrada do cameras.json."""
    overrides = overrides or {}
    name = spec.get("name", "camera")

    data = bpy.data.cameras.new(f"CAM_{name}")
    data.sensor_width = SENSOR_WIDTH_MM
    data.sensor_height = SENSOR_HEIGHT_MM
    data.clip_start = float(overrides.get("clip_start", 0.02))
    data.clip_end = float(overrides.get("clip_end", 500.0))

    fov_deg = float(overrides.get("fov_deg", spec.get("fov_deg", 55.0)))
    axis = (overrides.get("fov_axis") or spec.get("fov_axis") or "vertical").lower()
    half = math.radians(fov_deg) / 2.0

    if axis.startswith("vert"):
        data.sensor_fit = "VERTICAL"
        data.lens = (SENSOR_HEIGHT_MM / 2.0) / math.tan(half)
    else:
        data.sensor_fit = "HORIZONTAL"
        data.lens = (SENSOR_WIDTH_MM / 2.0) / math.tan(half)

    obj = bpy.data.objects.new(f"CAM_{name}", data)
    bpy.context.scene.collection.objects.link(obj)

    clip_report = None
    caixa = overrides.get("room_bbox")
    if caixa:
        clip, clip_report = clip_ate_o_ambiente(spec["eye"], spec["target"], caixa)
    elif overrides.get("auto_clip", spec.get("auto_clip", True)):
        clip, clip_report = auto_clip_start(
            spec["eye"], spec["target"],
            parede_max_m=float(overrides.get("parede_max_m", 0.45)),
        )
    else:
        clip = None
    if clip and clip > data.clip_start:
        data.clip_start = clip

    eye = spec["eye"]
    target = spec["target"]
    up = spec.get("up", [0.0, 0.0, 1.0])

    two_point = bool(overrides.get("two_point", spec.get("two_point", False)))
    if two_point:
        obj.matrix_world, shift = _two_point(eye, target, data)
        data.shift_y = shift
    else:
        obj.matrix_world = _look_at_matrix(eye, target, up)

    dof = overrides.get("dof") or spec.get("dof")
    if dof and dof.get("enabled"):
        data.dof.use_dof = True
        data.dof.focus_distance = float(dof.get("focus_distance_m", 3.0))
        data.dof.aperture_fstop = float(dof.get("fstop", 4.0))

    return obj, {
        "nome": name,
        "clip_start_m": round(data.clip_start, 3),
        "recorte": clip_report,
        "fov_deg": fov_deg,
        "fov_axis": axis,
        "lente_mm": round(data.lens, 2),
        "dois_pontos": two_point,
        "shift_y": round(data.shift_y, 4),
        "dof": bool(data.dof.use_dof),
    }


def _two_point(eye, target, data):
    """Nivela a camera e compensa com deslocamento de sensor.

    O conteudo enquadrado continua o mesmo, mas as verticais ficam retas.
    """
    eye_v = Vector(eye)
    target_v = Vector(target)
    forward = (target_v - eye_v)

    horizontal = Vector((forward.x, forward.y, 0.0))
    if horizontal.length < 1e-6:
        # camera apontando reto para cima ou baixo: dois pontos nao faz sentido
        return _look_at_matrix(eye, target, (0, 0, 1)), 0.0

    pitch = math.atan2(forward.z, horizontal.length)
    leveled_target = eye_v + horizontal

    matrix = _look_at_matrix(eye_v, leveled_target, Vector((0.0, 0.0, 1.0)))

    # deslocamento em fracao da largura do sensor (convencao do Blender)
    shift = (data.lens * math.tan(pitch)) / SENSOR_WIDTH_MM
    return matrix, shift


def clip_ate_o_ambiente(eye, target, caixa, margem_m=0.03):
    """Recorta a camera ate ela entrar no ambiente que interessa.

    O arquivo da arquiteta traz a suite inteira, mas as Cenas enquadram so o
    banheiro. No SketchUp isso funciona porque cada Cena esconde as paredes da
    frente; esse estado nao existe em nenhum formato de exportacao.

    Em vez de adivinhar quantas paredes atravessar, o projeto declara a caixa
    do ambiente e a camera passa a enxergar a partir da entrada nessa caixa.
    E o equivalente exato de um plano de seccao, e nao toca em geometria.
    """
    from mathutils import Vector

    eye_v = Vector(eye)
    direcao = (Vector(target) - eye_v).normalized()
    (x0, y0, z0), (x1, y1, z1) = caixa

    t_entra, t_sai = 0.0, float("inf")
    for i, (lo, hi) in enumerate(((x0, x1), (y0, y1), (z0, z1))):
        d = direcao[i]
        if abs(d) < 1e-9:
            if not (lo <= eye_v[i] <= hi):
                return None, {"motivo": "o raio nao cruza a caixa do ambiente"}
            continue
        ta, tb = (lo - eye_v[i]) / d, (hi - eye_v[i]) / d
        if ta > tb:
            ta, tb = tb, ta
        t_entra, t_sai = max(t_entra, ta), min(t_sai, tb)

    if t_entra >= t_sai:
        return None, {"motivo": "o raio nao cruza a caixa do ambiente"}
    if t_entra <= 0.0:
        return None, {"motivo": "camera ja esta dentro do ambiente"}

    return t_entra + margem_m, {
        "entra_no_ambiente_m": round(t_entra, 3),
        "clip_start_m": round(t_entra + margem_m, 3),
    }


def auto_clip_start(eye, target, parede_max_m=0.45, margem_m=0.02, limite=12):
    """Descobre a que distancia comecar a enxergar, atravessando a parede proxima.

    A arquiteta posiciona a camera FORA do ambiente e o SketchUp esconde a
    parede da frente por cena. Esse estado nao existe em nenhum formato de
    exportacao, entao a camera importada acorda dentro do vizinho e o render
    sai preto.

    A saida correta e recorte de camera, que e exatamente o que uma seccao faz
    e nao altera um vertice sequer. Aqui o raio e lancado da camera e
    atravessa camadas enquanto o vao entre elas for menor que `parede_max_m`,
    ou seja, enquanto ainda estiver dentro da espessura de uma parede. Quando
    aparece um vao maior, chegamos no ambiente.

    Devolve (clip_start, relatorio). clip_start None significa que a camera ja
    esta livre e nao precisa recorte.
    """
    from mathutils import Vector

    eye_v = Vector(eye)
    direcao = (Vector(target) - eye_v).normalized()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    cena = bpy.context.scene

    camadas = []
    distancia = 0.0
    for _ in range(limite):
        origem = eye_v + direcao * (distancia + 1e-4)
        acertou, local, _, _, _, _ = cena.ray_cast(depsgraph, origem, direcao)
        if not acertou:
            break
        d = (local - eye_v).length
        if camadas and (d - camadas[-1]) > parede_max_m:
            break  # vao grande: saimos da parede e entramos no ambiente
        camadas.append(d)
        distancia = d

    if not camadas:
        return None, {"camadas": [], "motivo": "nada na frente da camera"}

    clip = camadas[-1] + margem_m
    return clip, {
        "camadas_atravessadas": [round(c, 3) for c in camadas],
        "clip_start_m": round(clip, 3),
    }


def slugify(name):
    out = []
    for ch in (name or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " _-/":
            out.append("-")
        elif ch in "áàãâä":
            out.append("a")
        elif ch in "éèêë":
            out.append("e")
        elif ch in "íìîï":
            out.append("i")
        elif ch in "óòõôö":
            out.append("o")
        elif ch in "úùûü":
            out.append("u")
        elif ch == "ç":
            out.append("c")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "camera"
