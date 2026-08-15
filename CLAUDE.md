# render-ai

Pipeline de render fotorrealista de interiores a partir de modelos já feitos
no SketchUp. Automatiza render, materiais, iluminação e pós. Não automatiza,
e não pode automatizar, decisão de projeto.

---

## REGRA ZERO

> **Geometria é fixa. Aparência é editável.**

Nenhum script deste repositório pode criar, mover, escalar, deformar ou
deletar malha por conta própria. Se uma tarefa parecer exigir isso, **pare e
pergunte**. Não improvise, não "ajeite", não conserte em silêncio.

**Pode ser alterado:** material, textura, rugosidade, reflexo, iluminação,
exposição, pós-produção, resolução, amostras, presets.

**Não pode ser alterado:** paredes, medidas, portas, janelas, marcenaria,
móveis, bancadas, rebaixos, forros, posição e enquadramento de câmera,
proporção, layout.

As únicas operações que tocam geometria vivem em `apply_optional_cleanup`
(`blender/rlib/scene.py`), estão **desligadas por padrão**, só rodam se o
`project.yaml` pedir explicitamente, e sempre aparecem no relatório.

---

## Arquitetura

```
project.yaml + presets + biblioteca
        ↓  cli/render.py  (Python de fora: pyyaml, resolve tudo)
     job.json  (resolvido, sem ambiguidade)
        ↓  blender/run_render.py  (dentro do Blender: só bpy + stdlib)
renders/<camera>/vNNN/{raw.png, config.snapshot.yaml, passes/}
```

Separação deliberada: **toda decisão** acontece fora do Blender e é testável
sem abrir o Blender. O lado Blender é executor puro. Nunca mova lógica de
configuração para dentro de `blender/`.

---

## Fluxo de trabalho

Todo pedido de aparência é **um patch no `project.yaml`**, nunca código novo.

- "bancada em Taj Mahal" → muda uma linha em `materials:`
- "renderize às 16h" → `--lighting tarde-16h` ou `--hour 16`
- "mais claro" → `exposure` no preset, ou `--samples` se for ruído

Se o pedido não couber no schema do `project.yaml`, **não é mudança de
projeto, é mudança de pipeline**. Avise e trate como desenvolvimento, com
revisão, fora do fluxo de produção.

Ao editar `project.yaml` a pedido do usuário, só toque em `lighting`,
`materials`, `render`, `cameras.include` e `cameras.overrides`. Os campos
`source`, `north_angle_deg`, `location` e `units_check` descrevem a realidade
física do projeto e não se mudam para "ficar mais bonito".

---

## Comandos

```bash
./render --project <nome> --all
./render --project <nome> --camera sala-01 --lighting tarde-16h
./render --project <nome> --all --quality final
./render --project <nome> --camera cozinha-01 --hour 16.5 --date 2026-06-21
./render --project <nome> --list-cameras
./render --list-materials
./render --project <nome> --all --dry-run     # mostra o job, não renderiza

# gerar a cena sintética de teste
blender -b -P tools/make_test_scene.py -- projects/teste-interior/source
```

---

## Materiais: a convenção é descoberta, não imposta

O nome do material no modelo é a chave que liga o projeto à biblioteca PBR.
Mas a arquiteta **já aplica material enquanto modela**, com o vocabulário
dela. Impor uma convenção nova seria pedir retrabalho a quem já tem um jeito
que funciona.

Então o fluxo é o inverso: `./render --project X --survey` lê os nomes reais
do modelo, ordena por **área em metros quadrados** e propõe o mapeamento.
Humano confere e cola no `project.yaml`.

```
"Piso Porcelanato Bianco 120x120" -> pisos/porcelanato-acetinado-claro
"MDF Freijó Duratex"              -> madeiras/freijo
"Quartzito Taj Mahal Polido"      -> pedras/taj-mahal
```

O reconhecimento vem do campo `aliases:` de cada `material.yaml`. **Ao criar
material novo na biblioteca, sempre preencha `aliases`**, senão ele nunca vai
ser sugerido.

A área é o dado que decide onde gastar textura PBR de verdade: no teste, 4
materiais cobriam 86% da superfície. Material com 0,3 m² não merece mapa 4K.

Materiais com prefixo `LUZ_` viram emissores e não passam pela biblioteca; a
temperatura sai do próprio nome (`_3000K`). Sufixo `.001` é ignorado.

Ver `docs/padrao-sketchup.md`, que é o documento entregue à arquiteta.

---

## Relatórios obrigatórios

Todo render reporta, e essas informações nunca podem ser suprimidas:

- materiais **sem mapeamento** na biblioteca (caíram no fallback)
- validação de escala (dimensões medidas do modelo)
- posição solar calculada (elevação, azimute, se está acima do horizonte)
- dispositivo, amostras, tempo
- qualquer operação de geometria que tenha rodado

**Degradação silenciosa é bug.** Se algo não foi aplicado como pedido, isso
aparece no terminal e no `report-*.json`.

---

## Saída e versões

Renders **nunca** são sobrescritos. Cada execução cria `vNNN` novo, por
câmera. Junto vai `config.snapshot.yaml`, que é o estado resolvido que gerou
aquela imagem: é o que permite "pegue a v002 e mude só a luz indireta".

O `raw.png` é o render puro do Cycles e é preservado sempre, mesmo quando
houver etapa de IA (que ainda não existe).

---

## Fatos técnicos apurados nesta base

Foram medidos nesta máquina, não presumidos. Não reverter sem re-medir.

1. **Blender 5.2 removeu o céu Nishita.** Usar `MULTIPLE_SCATTERING`.
2. **`sun_rotation` do nó de céu é a bússola:** 0 põe o sol em +Y, 90 em +X.
   Ou seja, +Y = Norte e giro horário. Bate com `rlib/solar.py` sem conversão.
3. **Vidro precisa de `shadow_pass_through`.** Sol direto atravessando vidro
   refrativo é cáustica. O Cycles **amostra** cáustica (verificado:
   `caustics_reflective` e `caustics_refractive` vêm `True` por padrão), mas
   converge lentíssimo. Sem o truque de virar Transparent no raio de sombra,
   o interior fica sem mancha de sol **e o render fica 10x mais lento**
   (241s → 23s medidos na mesma cena).
4. **Sol e céu físico precisam ser calibrados juntos.** A convenção de
   "energia 3 a 5" vem de HDRI normalizado e deixa o sol invisível contra o
   céu `MULTIPLE_SCATTERING`. Os presets usam de 10 a 24, medidos.
5. **Denoiser OptiX só existe em NVIDIA.** No Mac só há OpenImageDenoise, e
   `engine.configure_quality` já trata isso.
6. **`sample_clamp_indirect` vem em 10.0 por padrão e o pipeline nunca escreve
   esse campo.** Isso corta o rebote indireto forte. Enquanto estiver em 10,
   subir a energia do sol rende menos do que deveria e a cena fica achatada.
   Sol, clamp e `exposure` têm que ser mexidos no MESMO passo: cada um sozinho
   parece regressão.
7. **Portais de janela existem** em 5.2 (`light.cycles.is_portal`), ao
   contrário do que se lê por aí sobre o Cycles X.

---

## Limitações conhecidas

- Blender **não** abre `.skp` de forma confiável. A fonte é sempre
  `modelo.glb` + `cameras.json` exportados do SketchUp Pro.
- Câmeras **não** vêm em nenhum formato de troca. Vêm do `export_render.rb`.
- MacBook Air M1 8 GB é máquina de preview. Qualidade final é para GPU
  dedicada ou nuvem.
- Não há etapa de IA ainda. Quando houver, será opcional, por flag, com teto
  de denoise e o `raw.png` sempre preservado.
- Materiais da biblioteca são procedurais. O schema já aceita `kind: maps`
  com texturas PBR, mas ainda não há mapas no repositório.
