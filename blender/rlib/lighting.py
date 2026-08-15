"""Iluminacao: ceu fisico, sol datado por cidade/data/hora, e luz artificial.

Duas decisoes que valem explicacao:

1. O sol vem de uma LAMPADA SUN explicita, e o disco solar do ceu fica
   desligado. Ceu com disco solar ilumina interior por amostragem do
   ambiente, o que converge muito devagar e enche a cena de ruido. Lampada
   sun e amostrada diretamente. Mesma luz, uma fracao do tempo.

2. `sun_rotation` do no de ceu foi medido empiricamente no Blender 5.2:
   rotacao 0 poe o sol em +Y, rotacao 90 em +X. Ou seja, e a bussola com
   +Y = Norte e giro horario. Bate com o modulo solar sem conversao.
"""

import math

import bpy

from . import solar


def _clear_world(scene):
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    out.location = (400, 0)
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.location = (200, 0)
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    return nt, bg


def _remove_existing_suns():
    for obj in list(bpy.data.objects):
        if obj.type == "LIGHT" and obj.name.startswith("SOL_"):
            bpy.data.objects.remove(obj, do_unlink=True)


def setup(scene, preset, location, north_angle_deg=0.0, date=None):
    """Monta o rig de iluminacao. Devolve relatorio."""
    report = {"preset": preset.get("name", "?")}

    wb_k = preset.get("white_balance_k")
    wb_gain = white_balance_gain(float(wb_k)) if wb_k else None
    if wb_gain:
        report["balanco_de_branco"] = {
            "kelvin": float(wb_k),
            "ganho_rgb": [round(v, 4) for v in wb_gain],
        }

    sky_cfg = preset.get("sky", {}) or {}
    sun_cfg = preset.get("sun", {}) or {}
    hdri_cfg = preset.get("hdri", {}) or {}

    nt, bg = _clear_world(scene)
    bg.inputs["Strength"].default_value = float(sky_cfg.get("strength", 1.0))

    # --- posicao solar ---------------------------------------------------
    sun_info = None
    if sun_cfg.get("enabled", True):
        sun_info = solar.resolve(
            lat=location["lat"],
            lon=location["lon"],
            tz_offset=location.get("tz_offset", -3),
            date_str=date or location.get("date", "2026-03-21"),
            hour=float(sun_cfg.get("hour", 12.0)),
            north_angle_deg=north_angle_deg,
        )
        report["sol"] = {
            "hora": sun_cfg.get("hour"),
            "data": date or location.get("date"),
            "elevacao_deg": round(sun_info["elevation_deg"], 2),
            "azimute_deg": round(sun_info["azimuth_deg"], 2),
            "acima_do_horizonte": sun_info["above_horizon"],
        }
        if not sun_info["above_horizon"]:
            report.setdefault("avisos", []).append(
                f"o sol esta abaixo do horizonte as {sun_cfg.get('hour')}h "
                f"nesta data e latitude. A cena vai ficar noturna."
            )

    # --- ceu --------------------------------------------------------------
    if hdri_cfg.get("path"):
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.location = (-100, 0)
        env.image = bpy.data.images.load(hdri_cfg["path"], check_existing=True)
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.location = (-320, 0)
        mapping.inputs["Rotation"].default_value = (
            0.0,
            0.0,
            math.radians(float(hdri_cfg.get("rotation_deg", 0.0))),
        )
        coord = nt.nodes.new("ShaderNodeTexCoord")
        coord.location = (-520, 0)
        nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        report["ceu"] = f"HDRI {hdri_cfg['path']}"

    elif sky_cfg.get("enabled", True):
        sky = nt.nodes.new("ShaderNodeTexSky")
        sky.location = (-100, 0)
        sky.sky_type = "MULTIPLE_SCATTERING"
        sky.sun_disc = bool(sky_cfg.get("sun_disc", False))
        sky.sun_intensity = float(sky_cfg.get("sun_intensity", 1.0))
        sky.sun_size = math.radians(float(sky_cfg.get("sun_size_deg", 0.545)))
        sky.altitude = float(sky_cfg.get("altitude_m", 0.0))
        sky.air_density = float(sky_cfg.get("air_density", 1.0))
        sky.aerosol_density = float(sky_cfg.get("aerosol_density", 1.0))
        sky.ozone_density = float(sky_cfg.get("ozone_density", 1.0))
        if sun_info:
            sky.sun_elevation = math.radians(max(sun_info["elevation_deg"], -5.0))
            sky.sun_rotation = math.radians(
                sun_info["azimuth_deg"] - north_angle_deg
            )
        else:
            sky.sun_elevation = math.radians(float(sky_cfg.get("elevation_deg", 20.0)))
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
        report["ceu"] = "fisico (multiple scattering)"

    else:
        bg.inputs["Color"].default_value = tuple(
            sky_cfg.get("color", [0.02, 0.03, 0.05])
        ) + (1.0,)
        report["ceu"] = "cor solida"

    # --- lampada sol ------------------------------------------------------
    _remove_existing_suns()
    if sun_info and sun_info["above_horizon"]:
        data = bpy.data.lights.new("SOL_data", "SUN")
        data.energy = float(sun_cfg.get("energy", 3.0))
        data.angle = math.radians(float(sun_cfg.get("angle_deg", 0.545)))
        if sun_cfg.get("temperature_k"):
            cor = _kelvin_to_rgb(float(sun_cfg["temperature_k"]))
            data.color = _apply_gain(cor, wb_gain) if wb_gain else cor
        obj = bpy.data.objects.new("SOL_" + preset.get("name", "sol"), data)
        scene.collection.objects.link(obj)

        from mathutils import Vector

        direction = Vector(sun_info["direction"])
        obj.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
        report["lampada_sol"] = {
            "energia": data.energy,
            "angulo_deg": round(math.degrees(data.angle), 3),
        }

    # --- exposicao e color management ------------------------------------
    scene.view_settings.exposure = float(preset.get("exposure", 0.0))
    vt = preset.get("view_transform", "AgX")
    try:
        scene.view_settings.view_transform = vt
    except TypeError:
        scene.view_settings.view_transform = "AgX"
        report.setdefault("avisos", []).append(
            f"view transform '{vt}' nao existe nesta build, usando AgX"
        )
    if preset.get("look"):
        try:
            scene.view_settings.look = preset["look"]
        except TypeError:
            pass

    report["exposicao"] = scene.view_settings.exposure
    report["view_transform"] = scene.view_settings.view_transform
    return report


def _folga_lateral(pos):
    """Menor distancia ate geometria nas 4 direcoes horizontais."""
    from mathutils import Vector

    dg = bpy.context.evaluated_depsgraph_get()
    cena = bpy.context.scene
    menor = 1e9
    for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)):
        acertou, local, _, _, _, _ = cena.ray_cast(dg, Vector(pos), Vector(d))
        if acertou:
            menor = min(menor, (local - Vector(pos)).length)
    return menor


def _escapar_do_corpo(pos, meia_largura, passo=0.02, maximo=0.30):
    """Desce a luz ate ela sair de dentro do corpo da luminaria.

    Componente de luminaria do V-Ray e do Enscape e uma caixa (spot embutido,
    plafon, perfil). A origem do componente fica DENTRO dessa caixa. Uma luz
    de area de 10 cm dentro de uma caixa de 5 cm tem quase toda a superficie
    emissora bloqueada pela propria luminaria, e a cena renderiza escura sem
    apresentar erro nenhum: o pior tipo de defeito.

    Aqui a fonte desce em passos ate ter folga lateral maior que o seu proprio
    raio, ou seja, ate estar livre para iluminar.
    """
    from mathutils import Vector

    atual = list(pos)
    for _ in range(int(maximo / passo)):
        if _folga_lateral(atual) > meia_largura:
            return atual, True
        atual[2] -= passo
    return atual, False


def place_fixtures(scene, luminarias, config, wb_gain=None):
    """Cria luzes reais do Cycles nas posicoes que a arquiteta marcou.

    Os componentes de luminaria do V-Ray sao geometria, nao luz. Renderizar
    geometria emissiva funciona, mas amostra mal: o Cycles nao consegue mirar
    raios de sombra numa malha arbitraria do jeito que mira numa lampada.
    Convertendo para luz de verdade, a mesma cena converge com uma fracao das
    amostras e sem os pontos brancos de ruido.

    A posicao vem do modelo dela. A potencia vem do project.yaml, porque isso
    e decisao de projeto e nao se adivinha.
    """
    config = config or {}
    criadas, por_tipo, presas = [], {}, []

    for i, lum in enumerate(luminarias):
        comp = lum.get("componente", "luz")
        cfg = dict(config.get(comp) or config.get("padrao") or {})
        if cfg.get("enabled") is False:
            continue

        tipo = (cfg.get("type") or lum.get("tipo") or "point").upper()
        tipo = {"AREA": "AREA", "SPOT": "SPOT", "POINT": "POINT"}.get(tipo, "POINT")

        data = bpy.data.lights.new(f"LUM_{i:02d}", tipo)
        data.energy = float(cfg.get("power_w", 25.0))

        kelvin = cfg.get("temperature_k") or lum.get("temperature_k") or 4000
        cor = _kelvin_to_rgb(float(kelvin))
        data.color = _apply_gain(cor, wb_gain) if wb_gain else cor

        if tipo == "AREA":
            data.shape = cfg.get("shape", "SQUARE")
            data.size = float(cfg.get("size_m", 0.12))
        elif tipo == "SPOT":
            data.spot_size = math.radians(float(cfg.get("angle_deg", 70.0)))
            data.spot_blend = float(cfg.get("blend", 0.35))
            data.shadow_soft_size = float(cfg.get("radius_m", 0.03))
        else:
            data.shadow_soft_size = float(cfg.get("radius_m", 0.03))

        obj = bpy.data.objects.new(f"LUM_{i:02d}_{comp[:20]}", data)
        scene.collection.objects.link(obj)

        # O componente de luminaria costuma ter origem no PLANO DO FORRO, e as
        # vezes 1 cm acima dele. Luz do lado de fora do forro nao ilumina nada
        # e a cena sai preta sem nenhum erro aparente. O deslocamento traz a
        # fonte para dentro do ambiente.
        pos = list(lum["posicao_m"])
        pos[2] += float(cfg.get("offset_z_m", -0.02))

        meia = float(cfg.get("size_m", 0.12)) / 2.0 if tipo == "AREA" else 0.01
        if cfg.get("escape_do_corpo", True):
            pos, livre = _escapar_do_corpo(pos, meia + 0.005)
            if not livre:
                presas.append(obj.name)
        obj.location = pos

        # Lampada do Blender ja emite no -Z local, ou seja, rotacao zero
        # aponta PARA BAIXO. Aplicar 180 graus aqui joga a luz no forro, e o
        # sintoma e cena escura que nao melhora quando se aumenta a potencia.
        eixo = lum.get("eixo_z") or [0, 0, 1]
        if cfg.get("aim_down", True) or abs(eixo[2]) > 0.99:
            obj.rotation_euler = (0.0, 0.0, 0.0)
        else:
            from mathutils import Vector

            obj.rotation_euler = Vector(eixo).to_track_quat("-Z", "Y").to_euler()

        criadas.append(obj.name)
        por_tipo[f"{comp} ({tipo.lower()})"] = por_tipo.get(f"{comp} ({tipo.lower()})", 0) + 1

    resultado = {
        "total": len(criadas),
        "por_componente": por_tipo,
        "origem": "componentes do modelo do SketchUp",
    }
    if presas:
        resultado["presas_no_corpo"] = len(presas)
    return resultado


def white_balance_gain(kelvin):
    """Ganho RGB que neutraliza uma fonte de `kelvin`, preservando luminancia.

    Aplicado na COR DAS FONTES, nao em pos-producao. E equivalente quando a
    cena e iluminada por aquela temperatura, e nao depende da API do
    compositor, que muda de versao para versao do Blender. Uma lampada de
    2700K numa cena balanceada em 4000K continua mais quente que as outras,
    que e exatamente o comportamento correto.
    """
    r, g, b = _kelvin_to_rgb(kelvin)
    r, g, b = max(r, 1e-4), max(g, 1e-4), max(b, 1e-4)
    gain = [1.0 / r, 1.0 / g, 1.0 / b]
    lum = 0.2126 * gain[0] + 0.7152 * gain[1] + 0.0722 * gain[2]
    return [v / lum for v in gain]


def _apply_gain(cor, gain):
    return tuple(min(1.0, c * g) for c, g in zip(cor[:3], gain))


def apply_white_balance_compositor(scene, kelvin, alvo_k=6500.0, tint=0.0):
    """Neutraliza a dominante da fonte de luz, como uma camera faria.

    Ambiente iluminado so por LED de 4000K e fisicamente alaranjado, e o render
    sai alaranjado se ninguem corrigir. Nenhum fotografo de arquitetura entrega
    assim: ele balanceia o branco para a fonte. Sem esta etapa, todo render de
    banheiro e de cozinha com luz artificial fica com cara de foto de
    imobiliaria tirada com lampada incandescente.

    O Blender 5.x trocou o compositor de `scene.node_tree` para um node group
    em `scene.compositing_node_group`, e o antigo MixRGB deixou de existir. Aqui
    usamos o ColorBalance em modo Whitepoint, que e a ferramenta certa: informa
    a temperatura da fonte e a temperatura alvo.
    """
    ng = bpy.data.node_groups.new("render-ai compositor", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="INPUT", socket_type="NodeSocketColor")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")

    entrada = ng.nodes.new("NodeGroupInput")
    entrada.location = (-300, 0)
    saida = ng.nodes.new("NodeGroupOutput")
    saida.location = (400, 0)

    cb = ng.nodes.new("CompositorNodeColorBalance")
    cb.location = (0, 0)

    aplicado = False
    try:
        cb.inputs["Type"].default_value = "Whitepoint"
        temps = [i for i in cb.inputs if i.name == "Temperature"]
        tints = [i for i in cb.inputs if i.name == "Tint"]
        if len(temps) >= 2:
            temps[0].default_value = float(kelvin)     # de onde a luz vem
            temps[1].default_value = float(alvo_k)     # para onde queremos
            aplicado = True
        if len(tints) >= 2 and tint:
            tints[0].default_value = float(tint)
    except (TypeError, KeyError, IndexError):
        aplicado = False

    if not aplicado:
        # se a API mudar de novo, nao vale derrubar o render por causa de cor
        ng.nodes.remove(cb)
        ng.links.new(entrada.outputs[0], saida.inputs[0])
        scene.compositing_node_group = ng
        return {"kelvin": kelvin, "aplicado": False,
                "motivo": "ColorBalance em modo Whitepoint indisponivel nesta build"}

    ng.links.new(entrada.outputs[0], cb.inputs["Image"])
    ng.links.new(cb.outputs[0], saida.inputs[0])
    scene.compositing_node_group = ng

    return {"kelvin": kelvin, "alvo_k": alvo_k, "aplicado": True}


def _kelvin_to_rgb(kelvin):
    """Aproximacao de Tanner Helland, suficiente para cor de lampada."""
    t = max(1000.0, min(40000.0, kelvin)) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307

    def norm(v):
        return max(0.0, min(1.0, v / 255.0)) ** 2.2

    return (norm(r), norm(g), norm(b))
