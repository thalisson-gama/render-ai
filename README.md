# render-ai

Render fotorrealista de interiores a partir de modelos do SketchUp, sem
alterar o projeto arquitetônico.

> Geometria é fixa. Aparência é editável.

---

## Instalação

```bash
# Blender (a única dependência pesada)
brew install --cask blender          # macOS
# Windows: https://www.blender.org/download/

# Python da CLI
pip3 install pyyaml
```

Se o Blender não estiver no lugar padrão, aponte a variável:

```bash
export BLENDER=/caminho/para/blender
```

---

## Uso

```bash
./render --project apartamento-joao --all
./render --project apartamento-joao --camera sala-01 --lighting tarde-16h
./render --project apartamento-joao --all --quality final
./render --project apartamento-joao --camera cozinha-01 --hour 16.5
./render --list-materials
./render --project apartamento-joao --list-cameras
```

---

## Projeto novo

```
projects/apartamento-joao/
    project.yaml            configuração: materiais, luz, câmeras
    source/                 somente leitura, vem do SketchUp
        modelo.glb
        cameras.json
        materials.json
    renders/                saída versionada
        sala-01/
            v001/  raw.png  config.snapshot.yaml
            v002/
            latest -> v002
        index.jsonl
```

Copie `projects/teste-interior/project.yaml` como ponto de partida.

No SketchUp, instale `sketchup/export_render.rb` e use
**Extensões > Exportar para Render**, apontando para a pasta `source/`.

---

## Presets

**Iluminação** (`config/lighting/`): `manha`, `meio-dia`, `tarde-16h`,
`por-do-sol`, `nublado`.

O sol é calculado de verdade a partir de cidade, data e hora, mais o ângulo
do norte do modelo. "16h" não é um chute estético, é a luz que entra naquela
janela naquele dia.

**Qualidade** (`config/quality/`):

| Preset    | Amostras | Escala | Teto     | Para quê                          |
|-----------|----------|--------|----------|-----------------------------------|
| `preview` | 96       | 50%    | 5 min    | iterar material, luz, enquadramento |
| `final`   | 1024     | 100%   | sem teto | apresentar ao cliente             |

---

## Cena de teste

Não precisa de modelo do SketchUp para validar o pipeline:

```bash
blender -b -P tools/make_test_scene.py -- projects/teste-interior/source
./render --project teste-interior --all
```

Gera um interior sintético com o contrato de nomes já aplicado, incluindo um
material sem mapeamento de propósito, para provar que o relatório acusa.

---

## Desempenho medido

MacBook Air M1, GPU de 7 núcleos, 8 GB, cena de teste, preview 960x540 a 96
amostras: **cerca de 23 s por imagem**.

A mesma cena antes da correção de vidro levava 241 s. Ver o item 3 dos fatos
técnicos no `CLAUDE.md`.

Para qualidade final em 1920x1080, esta máquina não é adequada. Use GPU
dedicada ou nuvem.

---

## Documentos

- `CLAUDE.md` — regras do repositório, arquitetura e fatos técnicos apurados
- `docs/padrao-sketchup.md` — o que entregar para a arquiteta
