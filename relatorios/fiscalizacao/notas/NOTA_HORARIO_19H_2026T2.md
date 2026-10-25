# Nota: extensão da votação até as 19h no 2º turno de 2026 — o que os dados do projeto permitem dizer

Gerada em 25/10/2026 19:42 por `scripts/make_nota_horario_19h.py`, a partir dos indicadores por seção de 11 estados (BA, SP, MG, RJ, PR, RS, PE, CE, PA, SC, MA), seções elegíveis (≥50 aptos) com log completo. Lado A = PT, lado B = PL. Sinalização não é acusação; nada aqui identifica o voto de ninguém.

## 1. O fato

Em 25/10/2026, dia do 2º turno, o ministro Cristiano Zanin (STF) determinou, em liminar, que a votação fosse estendida até as 19h (horário de Brasília) em todas as seções do país, a pedido da campanha de Lula, que alegou falhas no transporte público; a campanha de Flávio Bolsonaro havia pedido prorrogação em municípios de SP, PR e SC por chuvas. O TSE acatou e suspendeu a divulgação parcial enquanto a votação estivesse aberta. Fontes ao final (reportagens do próprio dia; não localizei desdobramentos posteriores).

**O que muda para a pesquisa**: votar depois das 17h deixa de ser exceção (fila remanescente) e passa a ser a regra por duas horas. Os indicadores do projeto que usam as 17h como referência (votos após 17h, último voto após 19h, encerramento mais de 60 min após 17h, habilitações manuais após 17h) precisam ser recalibrados para o 2º turno de 2026: a referência passa a ser as 19h. Como os limiares são relativos (P99 por estado), a varredura continua funcionando; o que muda é o significado do sinal.

## 2. O que já sabemos sobre votação tardia

| Eleição | Seções | Comparecimento | Votos após 17h | % do comparecimento | Seções com voto após 17h | Último voto ≥18h | Último voto ≥19h | Encerramento >60 min | Manuais após 17h |
|---|---|---|---|---|---|---|---|---|---|
| Pres. 2022 T1 | 361.347 | 95.565.764 | 3.161.934 | 3,31% | 45,1% | 30.832 | 7.510 | 35.923 | 278.487 |
| Pres. 2022 T2 | 362.594 | 96.538.013 | 29.364 | 0,03% | 7,1% | 3 | 0 | 69 | 2.747 |
| Pref. 2024 T1 | 373.721 | 95.623.241 | 107.419 | 0,11% | 12,6% | 363 | 62 | 433 | 9.508 |
| Pref. 2024 T2 | 77.045 | 18.956.141 | 9.351 | 0,05% | 10,6% | 0 | 0 | 3 | 622 |
| Pres. 2026 T1 | 383.080 | 96.786.456 | 2.712.591 | 2,80% | 42,6% | 28.106 | 5.561 | 32.028 | 143.291 |

Leitura: no 1º turno presidencial, votar depois das 17h é comum (2,8% dos votos de 2026 T1; 43% das seções tiveram pelo menos um). No **2º turno de 2022**, o mais comparável ao de hoje, foram só 29.364 votos após 17h (0,030%): a mediana do último voto foi 9 min **antes** das 17h e o P99 do encerramento, 11 min depois. Segundos turnos têm cédula de um cargo só e filas muito menores. A extensão de hoje não responde a uma demanda de fila como a do 1º turno; ela abre duas horas novas de votação.

### 2.1 Onde a votação tardia se concentra (2026 T1)

| UF | Seções | % de votos após 17h | % de seções com voto após 17h | Último voto ≥18h | Último voto ≥19h | Lado A % nos votos tardios (se votassem como suas seções) |
|---|---|---|---|---|---|---|
| BA | 35.266 | 7,39% | 70,3% | 8.045 | 2.061 | 68,8% |
| SP | 103.190 | 0,41% | 27,0% | 196 | 9 | 42,4% |
| MG | 51.869 | 2,04% | 38,8% | 2.116 | 245 | 49,1% |
| RJ | 37.482 | 2,38% | 50,4% | 1.704 | 130 | 40,2% |
| PR | 26.949 | 0,64% | 23,4% | 191 | 10 | 36,9% |
| RS | 27.402 | 0,49% | 17,6% | 114 | 4 | 38,4% |
| PE | 21.316 | 7,46% | 74,3% | 5.170 | 1.030 | 66,8% |
| CE | 23.647 | 6,12% | 65,3% | 4.039 | 727 | 65,0% |
| PA | 20.734 | 5,73% | 67,1% | 3.389 | 696 | 54,2% |
| SC | 17.231 | 0,87% | 25,9% | 152 | 5 | 26,5% |
| MA | 17.994 | 5,89% | 60,0% | 2.990 | 644 | 65,5% |

A votação tardia é um fenômeno do Nordeste e do Pará (5,7% a 7,5% dos votos após 17h em PE, BA, CE, MA e PA) e é rara no Sul e em SP (abaixo de 0,9%). Os estados onde a extensão tende a produzir mais votos novos são, portanto, os mesmos onde o lado A já é majoritário.

### 2.2 Seções com mais votos tardios votam diferente? (2026 T1)

| Faixa de votos após 17h na seção | Seções | Votos após 17h | Lado A % (ponderado) | Resíduo frente ao próprio prédio (p.p.) | Biometria cadastrada % | 60+ anos % | Baixa escolaridade % | Comparecimento % |
|---|---|---|---|---|---|---|---|---|
| 0 | 219.821 | 0 | 39,9% | -0,04 | 72,1 | 23,8 | 32,2 | 78,6% |
| 0–2% | 72.690 | 133.473 | 44,5% | -0,10 | 70,6 | 20,2 | 32,3 | 78,5% |
| 2–5% | 26.226 | 245.035 | 50,1% | -0,06 | 74,7 | 19,3 | 38,2 | 79,6% |
| 5–10% | 27.962 | 579.543 | 53,8% | 0,07 | 76,6 | 19,2 | 40,9 | 79,9% |
| 10–20% | 27.769 | 1.130.580 | 59,6% | 0,32 | 79,4 | 19,6 | 46,3 | 79,9% |
| >20% | 8.612 | 623.960 | 68,3% | 0,54 | 81,5 | 21,5 | 56,0 | 79,4% |

Duas leituras ao mesmo tempo. (1) **Composição**: quanto mais votos tardios, maior o % do PT na seção (de 40% sem tardios a 68% nas seções com mais de 20% de votos após 17h), porque fila acontece onde o eleitorado é menos escolarizado e mais nordestino, perfis que já votam mais no PT. (2) **Dentro do prédio**: o resíduo frente às seções vizinhas é pequeno (até +0,5 p.p.): a seção com fila vota quase como as vizinhas sem fila. Ou seja, o voto tardio reflete sobretudo *quem* enfrenta fila, não uma mudança de comportamento dentro do mesmo prédio.

### 2.3 Quanto os votos tardios pesam frente à margem (2026 T1, 11 estados)

- Votos válidos: A 41.443.962, B 43.328.980; margem B−A = 1.885.018. Votos após 17h: 2.712.591 = 144% da margem, em valor absoluto: os tardios são numerosos o bastante para mudar uma margem desse tamanho **se** votassem em bloco, o que os dados não mostram.
- Se cada voto tardio seguisse a proporção da própria seção, A teria 1.606.794 dos 2.712.591 (59,2%) e B 1.105.797: saldo líquido de 500.996 votos para A, ou 26,6% da margem.
- Por hora do último voto: seções cujo último voto saiu entre 18h e 19h têm lado A em 61,2%; depois das 19h, 70,0%; nas que fecharam até as 17h, 39,9%.

## 3. O que pode acontecer hoje (cenários, com o que os dados sustentam)

**Cenário 1 — pouca gente usa as duas horas extras.** É o cenário-base para um 2º turno: em 2022 T2 quase ninguém votou depois das 17h (0,03%). Quem queria votar já estava na fila. Efeito no resultado: desprezível. Efeito nos dados: os logs mostrarão último voto perto das 17h na maioria das seções, com cauda maior do que em 2022 pela permissão.

**Cenário 2 — a extensão vira mobilização extra onde a fila é rotina (NE e PA).** As duas horas a mais convertem eleitores que desistiriam, concentradas nos estados e seções com perfil de fila. Pelo padrão do 1º turno, cada 1 milhão de votos adicionais com esse perfil renderia cerca de 184.693 votos líquidos para A (proporção 59/41). Para virar a margem do 1º turno nos 11 estados (1.885.018) seriam necessários cerca de 10,2 milhões de votos novos com esse perfil, o que não é plausível; numa disputa nacional apertada (margem de algumas centenas de milhares), 1 a 2 milhões de votos novos com esse perfil seriam decisivos. Este é o cenário que importa monitorar, e ele é **perfeitamente legal**: votar às 18h30 com a urna aberta por decisão judicial não é irregularidade.

**Cenário 3 — aplicação desigual.** A decisão saiu durante a votação. Seções que já tinham encerrado ou cujos mesários não foram avisados fecham às 17h; outras ficam abertas até as 19h; em algumas a notícia atrai eleitores, em outras não. Isso cria diferenças de encerramento entre seções do **mesmo prédio**, exatamente o tipo de comparação que o projeto faz. É aqui que a varredura tem mais a dizer depois da eleição.

**Cenário 4 — risco operacional nas duas horas extras.** Mais tempo de urna aberta com mesários cansados e luz artificial: mais habilitações manuais, mais contingências, mais trocas de urna, encerramentos ainda mais tarde. No 1º turno de 2026 já houve 143.291 votos com habilitação manual depois das 17h; com a janela legal até as 19h esse número tende a crescer, e a comparação relevante passa a ser **manuais após 19h** e, dentro da janela, a razão manual/votos frente às seções vizinhas.

**O que os dados não permitem dizer**: em quem votaram os eleitores tardios; se a extensão foi pedida por cálculo eleitoral; se houve manipulação. O que permitem: medir, seção a seção, quantos votaram depois das 17h e das 19h, como essas seções votaram frente às vizinhas, e onde a aplicação foi desigual.

## 4. O que fazer hoje e nos próximos dias

1. **Hoje, nos locais do mapa de fiscalização**: anotar, além do que já está no checklist, a hora em que a seção soube da extensão, se continuou aberta até as 19h, se houve fila às 17h e às 19h, quantas habilitações manuais depois das 17h, e a hora real do encerramento. Prédios de prioridade alta continuam sendo os melhores pontos de observação: são os que têm fila e habilitação manual recorrentes.
2. **Esta noite / amanhã, com os boletins de urna** (bweb, publicados em horas): o BU traz o horário de encerramento e o número de habilitados manualmente por seção. Dá para medir, por estado e por prédio, quem fechou às 17h e quem às 19h, e comparar o resultado de seções que ficaram abertas com as vizinhas que fecharam (mesmo método da varredura, nível local). O script `analyze_office.py` já faz a parte do BU.
3. **Quando o TSE publicar os logs do 2º turno** (dias a semanas): rodar a cadeia com as referências recalibradas para 19h (votos após 19h, último voto após 21h, encerramento >60 min após 19h, manuais após 19h) e, separadamente, a janela 17h–19h como objeto próprio: quantos votos, em que estados, em que prédios, com que direção frente às vizinhas. Publicar como edição nova, sem substituir a atual.
4. **Não mudar a pontuação dos locais no dia**; registrar a recalibração dos limiares como alteração de parâmetro no documento técnico.

## 5. Números de referência para hoje

- 2026 T1, 11 estados: 2.712.591 votos após 17h (2,8% do comparecimento); 5.561 seções com último voto depois das 19h; P99 do último voto a 133 min das 17h; P99 do encerramento a 137 min.
- 2022 T2: 29.364 votos após 17h; P99 do último voto a 3 min das 17h; P99 do encerramento a 11 min. Qualquer coisa muito acima disso hoje é efeito da decisão.
- Cobertura: 11 estados, cerca de 62% do eleitorado nacional; os números não são o Brasil inteiro.

Fontes da decisão: https://forbes.com.br/geral/2026/10/stf-estende-votacao-do-segundo-turno-ate-as-19h-em-todas-as-secoes/ · https://www.poder360.com.br/poder-eleicoes-2026/zanin-prorroga-votacao-do-2o-turno-ate-19h/ · https://www.cnnbrasil.com.br/eleicoes/zanin-prorroga-eleicao-ate-as-19h-deste-domingo-em-todo-o-pais/ · https://exame.com/brasil/tse-aprova-a-extensao-do-horario-de-votacao-do-2o-turno-para-as-19h/ · https://www12.senado.leg.br/tv/programas/noticias-1/2026/10/eleicoes-2026-zanin-prorroga-horario-das-eleicoes-do-segundo-turno-1
