# Padrão de modelagem para render automático

Documento para a arquiteta. São poucas regras, e cada uma existe porque sem
ela o render sai errado de um jeito difícil de perceber.

Você continua modelando do seu jeito. O que muda é **como você nomeia as
coisas** e **como você exporta**.

---

## 1. Continue nomeando do seu jeito

**Você não precisa adotar convenção nenhuma.** Se você já aplica material
enquanto modela, com os seus nomes, está ótimo. O sistema lê os nomes que você
usou e reconhece sozinho.

Testado: "Piso Porcelanato Bianco 120x120", "MDF Freijó Duratex", "Quartzito
Taj Mahal Polido" e "Alumínio Preto Fosco" foram todos reconhecidos
automaticamente, com acento e espaço, sem ninguém configurar nada.

A única coisa que importa é o nome **descrever o acabamento**. Duas regras:

**Diga o material no nome.** "Bancada" sozinho é ambíguo. "Bancada Quartzito
Taj Mahal" se reconhece sozinho. Quanto mais específico, melhor, e nome longo
não atrapalha.

**Um material por acabamento.** Se sala e banheiro têm pisos diferentes,
precisam ser dois materiais no SketchUp, com nomes diferentes. Se os dois
estiverem pintados com o mesmo material, não existe forma de dar acabamentos
diferentes depois sem você reexportar. Essa é a única decisão que é cara de
desfazer.

**O que não funciona:** `Material12`, `Color A03`, `Cor 0255`, os nomes que o
SketchUp inventa sozinho. Esses não descrevem nada, então não têm como ser
reconhecidos. Aparecem no relatório e renderizam com acabamento genérico.

Não é preciso renomear tudo de uma vez. O relatório mostra a lista ordenada
por **área em metros quadrados**, então dá para renomear só os que ocupam mais
imagem. No teste, 4 materiais cobriam 86% da superfície do projeto.

---

## 2. Luminárias

Material com prefixo `LUZ_` vira fonte de luz no render. A temperatura de cor
sai do próprio nome.

- `LUZ_LED_3000K` → luz quente (sanca, embutido residencial)
- `LUZ_LED_4000K` → luz neutra (área de serviço, cozinha técnica)
- `LUZ_SPOT_2700K` → luz bem quente (ambiente de estar à noite)

Aplique esse material na face que de fato emite luz: a fita de LED dentro da
sanca, o difusor da luminária, a face inferior do plafon. Não aplique no corpo
inteiro da luminária.

---

## 3. Crie as Cenas

Cada **Cena** do SketchUp (Janela > Cenas) vira uma câmera no render, com o
nome que você deu. "Sala 01" vira `sala-01`.

Enquadre exatamente como quer ver. O render respeita a câmera ao pé da letra:
posição, altura, abertura e perspectiva de dois pontos.

Altura de olho recomendada para interiores: entre 1,50 m e 1,65 m. Câmera
muito alta dá aspecto de maquete.

---

## 4. Cuidados de modelagem que afetam o render

Nenhum deles é exigência nova de trabalho. São armadilhas conhecidas.

**Vidro precisa de face única, não de bloco.** Se você modelar o vidro com
espessura de verdade, o render fica mais lento sem ganho visual. Uma face só
é o ideal.

**Confira as faces invertidas.** No SketchUp, face azul-acinzentada é o verso.
Se o verso estiver para dentro do ambiente, a iluminação erra. Clique com o
botão direito > Inverter faces. (Vista > Estilos de face > Monocromático
mostra isso na hora.)

**Cuidado com componente do 3D Warehouse.** Muitos vêm com centenas de
milhares de polígonos e materiais lixo. Uma cadeira não precisa de 800 mil
faces. O relatório do render avisa quais objetos estão pesados.

**Modele em metros.** Confira em Janela > Informações do modelo > Unidades.
O render mede o modelo na importação e recusa rodar se a escala estiver
implausível, porque escala errada estraga luz, profundidade e textura de um
jeito que não é óbvio na imagem.

**Feche o ambiente.** Parede, piso e forro fechados. Ambiente com fresta
vaza luz e aparece um brilho estranho que ninguém sabe de onde vem.

---

## 5. Exportar

Menu **Extensões > Exportar para Render**, e escolha a pasta `source/` do
projeto.

Isso gera três arquivos:

- `modelo.glb` — a geometria
- `cameras.json` — todas as suas Cenas como câmeras
- `materials.json` — a lista de materiais, para conferência

Se aparecer o aviso de "materiais com nome automático", vale voltar e
renomear antes de pedir o render. É a diferença entre um render com
acabamento e um render cinza.

---

## 6. O que o render faz e o que não faz

**Faz:** material, textura, reflexo, iluminação natural e artificial, sombra,
exposição, pós-produção.

**Não faz, e não vai fazer sem você pedir:** mexer em parede, medida, porta,
janela, marcenaria, móvel, bancada, forro, layout ou câmera.

O projeto que você modelou é o projeto que sai na imagem. Se algo apareceu
diferente do que você desenhou, isso é um bug do pipeline e precisa ser
reportado, não um "ajuste" que a ferramenta fez.

**O que o render também não faz: decoração.** Almofada, tapete, cortina,
planta, livro na mesa, objeto de bancada. Render bonito é metade motor e
metade styling. Se o modelo for volumetria de estudo, a imagem vai ser
volumetria de estudo bem iluminada.
