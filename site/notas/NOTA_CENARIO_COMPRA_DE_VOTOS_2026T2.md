# Nota: o cenário mais perigoso — compra de votos com a janela até as 19h, o que deixaria nos dados e qual é o teto

Gerada em 25/10/2026 20:07 por `scripts/make_nota_cenario_compra.py`, com os indicadores por seção do 1º turno de 2026 em 11 estados (seções elegíveis com log completo) e a varredura por local. Lado A = PT, lado B = PL. Esta nota raciocina sobre hipóteses: os dados não observam compra de votos, dinheiro, transporte nem intenção; observam horários, habilitações, encerramento e votos por seção. Nenhuma seção ou local aqui é acusado de nada. Complementa a [nota sobre a extensão até as 19h](NOTA_HORARIO_19H_2026T2.html).

## 1. Como uma operação de compra de votos usaria duas horas a mais

Compra de votos, nas formas que a Justiça Eleitoral documenta em cassações, não é um eleitor isolado: é logística. Dinheiro ou bens trocados por comparecimento, transporte organizado, cabos eleitorais que levam o eleitor até a seção e conferem que ele foi, e pressão sobre quem depende de alguém (emprego, benefício, terra). O gargalo dessa operação é o **tempo de levar gente até a urna**. A extensão até as 19h ataca exatamente esse gargalo:

- **Duas horas a mais de transporte** depois do horário em que a maioria já votou, quando as filas são curtas e cada veículo descarrega eleitores que votam em minutos.
- **Cobertura legal**: votar às 18h30 passa a ser normal em qualquer seção. O sinal que o projeto usava para destacar seções (votos depois das 17h) deixa de distinguir fila remanescente de mobilização tardia.
- **Fim de dia**: mesários cansados, menos fiscais presentes; é quando a habilitação manual (eleitor liberado sem biometria) tende a ser menos conferida.
- **Decisão no meio do dia**: a operação que já tinha estrutura montada (transporte, listas) ganha duas horas; o eleitor comum que não soube da extensão, não. A vantagem é assimétrica por construção.

## 2. O que isso deixaria nos dados (assinaturas que o projeto consegue medir)

| Assinatura | O que se mede | Onde | Como separar de mobilização legítima |
|---|---|---|---|
| Pico concentrado de votos entre 17h e 19h em poucos locais, não difuso | votos por hora por seção frente à distribuição do estado | logs do 2º turno (`uf_pipeline.py`) | legítimo tende a ser difuso e proporcional ao eleitorado; operação é concentrada em prédios específicos e recorrentes |
| Ritmo de fila cheia até perto do fechamento | mediana do intervalo entre votos após 17h (no 1º turno, 93 s, ~39 votos/hora por seção) | logs | fila orquestrada mantém intervalos curtos e regulares até o fim; fila espontânea rareia |
| Habilitação manual acima do esperado na janela extra | votos de sequência manual após 19h frente ao esperado por biometria, idade e escolaridade | logs + perfil | liberação manual não é prova de nada; a assinatura é excesso frente às vizinhas, repetido |
| Resultado da seção destoando das vizinhas do mesmo prédio, na direção de um lado só | diferença acima do limiar (≥5 p.p. e z≥2) e direção, nível local | varredura (`make_varredura_locais.py`) | composição explica muito; o que importa é o salto **dentro do prédio** e a recorrência |
| Salto de comparecimento frente ao 1º turno na mesma seção, acima das vizinhas | comparecimento T2 − T1 por seção, contra os pares | boletins de urna (hoje à noite) | legítimo sobe junto com as vizinhas; operação sobe em seções específicas |
| Encerramento muito depois das 19h, sem troca de urna | horário de encerramento no BU | boletins (hoje) | permitido para quem estava na fila às 19h; o sinal é a concentração |
| Recorrência: as mesmas seções em 2022, 2024 e 2026 | histórico por seção | varredura | prédio grande ou bairro explica parte; a direção repetida para o mesmo lado, não |

Nenhuma assinatura isolada prova compra de votos. A combinação que exige explicação é: **concentração + ritmo cheio até o fim + manual acima do esperado + resultado destoando do prédio para o mesmo lado + recorrência**. É exatamente o que a pontuação de prioridade da varredura soma, e é por isso que o mapa de fiscalização aponta para esses prédios.

## 3. O tamanho do problema, com os números do 1º turno de 2026

Seções com comportamento (votação tardia ou manual acima do P99 do estado) no 1º turno de 2026, agrupadas pela prioridade do local na varredura:

| Prioridade do local | Locais | Seções com comportamento | Votos após 17h | Manuais após 17h | Diferenças acima do limiar (A / B) | Excesso de votos A | Excesso de votos B | Votos válidos das seções |
|---|---|---|---|---|---|---|---|---|
| alta | 450 | 2.964 | 154.507 | 8.766 | 478 (398 / 80) | 16.989 | 2.698 | 842.724 |
| média | 2.352 | 10.995 | 546.133 | 29.741 | 387 (320 / 67) | 14.035 | 2.081 | 3.109.374 |
| baixa | 14.454 | 22.116 | 921.771 | 52.127 | 704 (575 / 129) | 23.826 | 3.557 | 5.750.131 |

Nos 450 locais de prioridade alta, os votos após 17h foram 18,3% dos votos válidos dessas seções (contra 2,9% no conjunto dos 11 estados). O "excesso" do lado A (votos acima do que a seção teria se votasse como as vizinhas do prédio) somou 16.989 votos nos locais de prioridade alta e 54.849 em todos; o excesso do lado B, 8.337. São ordens de grandeza do desvio, não contagem de votos comprados: parte disso é composição, acaso e fila real.

**Núcleo mais sensível**: 979 seções com comportamento em 2 ou mais eleições e diferença acima do limiar a favor de A em alguma presidencial; 881 delas tiveram comportamento também no 1º turno de 2026, com 234.366 votos válidos, 47.716 votos após 17h, lado A em 74,2% contra 61,3% nas vizinhas, e excesso A de 29.810 votos. 350 estão em locais de prioridade alta e 281 em média. Esse núcleo é onde uma operação já existente teria mais a ganhar com duas horas extras, e onde um fiscal tem mais o que ver.

## 4. O teto: quantos votos cabem em duas horas

Uma seção com fila cheia computa cerca de 39 votos por hora (mediana do intervalo entre votos após 17h no 1º turno, nas seções com 20 ou mais votos tardios; as 10% mais rápidas chegam a 45). Duas horas extras cabem, portanto, no máximo ~77 votos por seção, e isso só se a fila for mantida cheia do início ao fim.

| Hipótese de alcance da operação | Seções | Capacidade máxima em 2 h | Votos líquidos para A se os novos votos seguirem o padrão dos tardios do 1º turno | Se seguirem o padrão do núcleo recorrente |
|---|---|---|---|---|
| todas as seções dos locais de prioridade alta | 4.012 | 310.606 | 57.367 | 150.432 |
| todas as seções a checar do mapa (locais alta e média) | 14.107 | 1.092.155 | 201.713 | 528.950 |
| só o núcleo recorrente com direção A | 881 | 68.206 | 12.597 | 33.034 |

Os dois padrões: votos após 17h no 1º turno foram 59,2% para A; o núcleo recorrente, 74,2% para A. Para comparação, a margem do 1º turno nos 11 estados foi de 1.885.018 votos (B à frente), e o reservatório de abstenção é de 25.853.372 eleitores (21,1% dos aptos).

Leitura: mesmo no teto físico, uma operação restrita aos locais que já têm sinal não vira uma margem desse tamanho. O que ela pode fazer é decidir uma disputa nacional apertada (centenas de milhares de votos), ou disputas locais, e fazê-lo com cobertura legal. O teto só sobe se a operação se espalhar por prédios que hoje não têm sinal nenhum, e aí ela deixa o rastro difuso que a comparação com as vizinhas captura. O cenário mais perigoso, portanto, não é o da virada aritmética: é o de uma disputa decidida por poucos votos em que as duas horas extras, concentradas onde já havia estrutura, fazem a diferença sem deixar prova individual.

**Os dois lados.** A tabela de teto usa a direção A porque é a dominante nos desvios medidos (1.293 seções acima do limiar a favor de A contra 276 a favor de B no 1º turno de 2026). O mecanismo não tem lado: uma operação a favor de B usaria as mesmas duas horas, os mesmos veículos e deixaria as mesmas assinaturas. As seções com desvio para B estão no mesmo mapa e recebem o mesmo checklist.

## 5. Por que este é o cenário mais perigoso para a fiscalização, e não só para o resultado

- O sinal "votou depois das 17h" perde valor de uma vez: qualquer explicação de fila passa a ser aceita. O projeto precisa mudar a referência para 19h e tratar a janela 17h–19h como objeto próprio.
- A decisão no meio do dia produz aplicação desigual (seções que fecharam às 17h ao lado de seções que ficaram abertas), o que gera ruído legítimo e dificulta separar operação de confusão.
- A observação presencial é o único instrumento que distingue veículo fretado de ônibus urbano, cabo eleitoral de parente, dinheiro de nada. Por isso o checklist do mapa pede o horário em que a seção soube da extensão, fila às 17h e às 19h, manuais observadas e encerramento real.

## 6. Protocolo para as próximas 72 horas

1. **Hoje à noite, com os boletins** (`bu_capture_all.py` e `analyze_office.py` para 2026 T2): por seção, horário de encerramento, habilitados manualmente (campo do BU) e comparecimento; comparar com o 1º turno na mesma seção e com as vizinhas. Lista 1: seções com salto de comparecimento frente ao T1 acima das vizinhas e encerramento depois das 19h.
2. **Cruzar a lista 1 com a varredura**: seções que já estavam no mapa (prioridade alta ou média, recorrentes, direção A) sobem para o topo; seções novas, sem histórico, ficam numa lista separada para olhar com cautela.
3. **Quando saírem os logs** (dias a semanas): votos por hora entre 17h e 19h e depois das 19h; ritmo; manuais na janela; refazer a varredura com referência 19h e publicar como edição nova, sem substituir a atual.
4. **Encaminhamento**: o que a varredura produz é uma lista de prédios e seções com padrão a explicar. Quem pode pedir explicação é o Ministério Público Eleitoral e os partidos; o material certo para isso é a lista com os números e os relatos de fiscais com horário, nunca a afirmação de que houve compra.

**O que esta nota não diz**: que houve ou haverá compra de votos; que a extensão foi feita para isso; quem comprou ou vendeu. **O que ela diz**: onde uma operação desse tipo teria mais a ganhar, quanto no máximo poderia render e como ela apareceria nos dados.

## Números de referência

- Seções elegíveis com log completo, 2026 T1, 11 UFs: 383.080
- Votos após 17h, 2026 T1: 2.712.591
- Parcela de A nos votos após 17h: 59,2%
- Intervalo mediano entre votos após 17h (s): 93
- Votos por hora por seção (mediana / P10 do intervalo): 39 / 45
- Seções nos locais de prioridade alta: 4.012
- Seções a checar no mapa: 14.107
- Núcleo recorrente com direção A e comportamento em 2026 T1: 881
- Margem B − A no 1º turno, 11 UFs: 1.885.018
- Ausentes no 1º turno, 11 UFs: 25.853.372