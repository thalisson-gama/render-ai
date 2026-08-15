# Instalar no PC (Windows)

Testado para o cenário real: notebook com Windows 11, i7-11800H, 8 GB de RAM,
GTX 1650 (4 GB) e SketchUp Pro 2022 instalado.

A vantagem dessa máquina não é velocidade bruta (a GPU é só 20 a 40% mais
rápida que o M1). É que **o SketchUp está aqui**, a NVIDIA destrava o **OptiX**,
e o CUDA abre a porta para a etapa de IA mais adiante.

---

## 1. O que instalar

**Blender 5.2 LTS** em [blender.org/download](https://www.blender.org/download/),
ou pelo terminal:

```powershell
winget install BlenderFoundation.Blender
```

**Python 3** (se ainda não tiver) e a única dependência da CLI:

```powershell
winget install Python.Python.3.12
pip install pyyaml
```

**Assimp**, o conversor de Collada (ver o porquê no passo 4):

```powershell
winget install Assimp.Assimp
```

Confira se os três aparecem:

```powershell
blender --version
python --version
assimp version
```

Se o `blender` não for reconhecido no terminal, tudo bem: a CLI procura o
executável nos caminhos padrão do Windows sozinha. Se ainda assim não achar:

```powershell
setx BLENDER "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
```

---

## 2. Baixar o projeto

```powershell
cd $HOME\Documents
git clone https://github.com/<usuario>/render-ai.git
cd render-ai
```

Teste que está tudo no lugar:

```powershell
.\render.bat --list-materials
```

Deve listar a biblioteca (quartzito Splendido, Eliane Oris Corda, Murano Ostra,
Louro Freijó, espelho, cromado e o resto).

---

## 3. Confirmar que a GPU está sendo usada

```powershell
.\render.bat --project teste-interior --camera sala-01
```

Na saída tem que aparecer:

```
[render-ai] dispositivo: OPTIX (NVIDIA GeForce GTX 1650)
```

Se aparecer `CPU`, o driver da NVIDIA está desatualizado. Atualize e repita.

**Sobre a GTX 1650:** é Turing sem núcleos RT, então o OptiX entra pelo
denoiser, não por aceleração de traçado. Continua sendo melhor que CUDA.

---

## 4. O modelo: dois caminhos

O Blender 5.x **removeu o importador de Collada**. Então o `.dae` do SketchUp
não entra direto. Há dois caminhos.

### Caminho A: DAE (validado, é o que já usamos)

No SketchUp: **Arquivo > Exportar > Modelo 3D > COLLADA (.dae)**, botão
**Opções**, com:

| Opção | |
|---|---|
| Exportar faces com dois lados | marcado |
| Exportar arestas | desmarcado |
| Triangular todas as faces | marcado |
| Exportar geometria oculta | desmarcado |
| Preservar hierarquias de componentes | marcado |
| Exportar mapas de textura | marcado |

A CLI converte o `.dae` para `.glb` sozinha na primeira vez, usando o assimp,
e reaproveita depois.

**Limitação conhecida:** o assimp perde os nomes dos objetos (viram
`$ColladaAutoName$`). Por isso as luminárias são extraídas do XML do DAE
direto, com `tools/extract_dae_lights.py`.

### Caminho B: FBX (mais simples, falta validar)

O SketchUp 2022 também exporta FBX, e o Blender **importa FBX nativamente**,
sem assimp.

Se o FBX do SketchUp preservar os nomes dos objetos (bem provável, já que não
passa pelo assimp), esse caminho fica melhor: encontro as luminárias pelo nome
e não preciso do DAE.

Vale testar. Exporte FBX, aponte `source.model` para o `.fbx` no
`project.yaml`, rode `--diagnose` e veja se os nomes vieram.

---

## 5. Preparar um projeto

```
projects/<Nome do Projeto>/
    project.yaml
    source/
        modelo.dae         (ou modelo.fbx)
        <pasta de texturas do DAE>
        cameras.json
        lights.json
```

O `cameras.json` sai do trecho no **Janela > Console Ruby** (ver
`sketchup/export_render.rb`, ou o bloco avulso).

O `lights.json`, das luminárias do modelo:

```powershell
python tools\extract_dae_lights.py "projects\<Projeto>\source\modelo.dae" "projects\<Projeto>\source\lights.json"
```

Antes de renderizar, sempre:

```powershell
.\render.bat --project "<Projeto>" --all --diagnose
.\render.bat --project "<Projeto>" --all --survey
```

O primeiro diz se o modelo está apto (escala, peso, câmeras). O segundo lista
os materiais por área e propõe o mapeamento pronto para colar.

---

## 6. Cuidado com os 8 GB

O Cycles guarda textura em ponto flutuante: **16 bytes por pixel**, não os 3 do
JPEG. Um catálogo de 2000x2000 ocupa 64 MB na cena, não 4 MB.

No banheiro de teste foram **814 MB de textura reduzidos para 196 MB** pelo
teto de `texture_max_px`. Sem isso, 8 GB de RAM com 4 GB de VRAM não fecha.

| Preset | Teto de textura | Para quê |
|---|---|---|
| `preview` | 1024 px | iterar |
| `entrega` | 2048 px | apresentar |
| `final` | sem teto | só com folga de memória |

Se estourar a memória, nesta ordem: baixe `texture_max_px`, esconda componentes
pesados (pessoas, plantas do 3D Warehouse), e por último use `--device cpu`,
que é mais lento mas lida melhor com falta de VRAM.

---

## 7. Medir esta máquina

```powershell
blender -b -P tools\benchmark.py -- projects\teste-interior
```

Grava `tools/benchmark-windows-amd64.json`. Referência já medida no MacBook
Air M1 (GPU de 7 núcleos), cena de teste:

| Ajuste | Tempo |
|---|---|
| preview 960x540, 96 amostras | ~36 s |
| entrega 1920x1080, 300 amostras | ~7 min |
