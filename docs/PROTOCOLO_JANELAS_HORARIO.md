# Protocolo travado — gatilho por janela de horário, por volume e em forma de cluster (2º turno 2026)

> Cópia versionada de `relatorios/verificacoes/janelas_horario/PROTOCOLO.md` (a pasta `relatorios/` não entra no repositório). O commit que adiciona este arquivo é a âncora citada na versão 1.0. Scripts: `scripts/janelas_horario.py`, `scripts/make_janelas_report.py`.

**Versão 1.1 — 03/11/2026, 15h, ainda antes de qualquer varredura dos logs de 2022** (ajuste de parâmetro sobre a 1.0, de 14h).
Mudança da 1.1: (a) o leitor de logs identifica cada log pela sua primeira linha, não pelo 3º campo (que em 2022 não é o
número de série e é igual para todas as urnas), e entre cópias do mesmo log fica a que tem mais votos no dia; antes, o log
do 1º turno aninhado no pacote vencia o do 2º (315 seções de 2026 e cerca de 5 mil de 2022 ficavam com zero votos) e, em
2022, a urna de contingência apagava a original (cerca de 2,7 mil seções com meio dia de log); (b) **uma seção só entra
na varredura se o log do dia conta os mesmos eleitores do BU (diferença ≤ 5)**. Motivo: achado na conferência de Campos
dos Goytacazes (5 seções com zero votos no log do dia), antes de o 2022 ser varrido.

**Versão 1.0 — travada em 03/11/2026, 14h, antes de qualquer varredura dos logs de 2022.**
Âncora: o commit que adicionar este arquivo ao repositório. Qualquer mudança posterior em grade, filtros,
controles, limites, cenários plantados ou regra de decisão exige nova versão aqui (1.1 para ajuste de parâmetro,
2.0 para mudança na lógica de decisão) e **não vale retroativamente** para resultados já produzidos sob a versão
anterior. Os resultados de 2026 já tinham sido vistos quando esta versão foi escrita; o que o protocolo fixa é a
leitura do controle (2022) e de tudo o que vier depois. A seção 9 registra o que foi mudado antes do travamento
e por quê.

## 1. Pergunta

Se um programa trocasse votos só entre uma hora e outra (p.ex. 14h–15h), só a partir do N-ésimo voto, ou só num
subconjunto de seções (sorteado ou territorial), isso apareceria nos dados publicados (BU, RDV, log de urna)?
O teste não procura "fraude": procura uma associação entre a exposição de cada seção a uma regra hipotética e o
quanto a seção se afasta das vizinhas do mesmo prédio. Sinalização não é acusação.

## 2. Dados e preparação (fixos)

- Seções do modelo do local (`research/anomalias_2t/secoes_<ano>.parquet`, resíduo `res_pp` do M1) com BU
  (`research/padroes_2t/base_<ano>.parquet`).
- Log de urna: contagem de "O voto do eleitor foi computado" por faixa de 15 min, 5h00–21h00, hora local da urna,
  no dia da eleição (25/10/2026; 30/10/2022). Lidos **todos** os `logd.dat` do pacote da seção (urna de
  contingência e urnas anteriores aninhadas), deduplicados por número de série, filtrados pela seção declarada
  na carga. Seção entra com ≥ 20 votos no log; prédio entra com ≥ 3 seções.
- Exposição a uma janela [s, t): fração dos votos da seção computados dentro dela. Exposição a regra por volume:
  função do BU (`(comp − N)+/comp`, `(comp − p·aptos)+/comp`, `min(k, comp)/comp`).

## 3. Grade e validade (fixas)

- Todas as janelas início–fim da grade de 15 min (2.080). Janela **válida**: pelo menos 1% das seções com voto
  dentro dela e pelo menos 1% com voto fora dela. Só janelas válidas entram nos máximos e nos limites.
- Grupo (UF, zona, município) válido numa janela: ≥ 30 prédios e, dentro do grupo, pelo menos 10% das seções
  (mínimo 30) com voto dentro da janela e outras tantas com voto fora.

## 4. Estatísticas (fixas)

Tudo dentro do prédio (centrado por prédio), com controles descontados (Frisch–Waugh) e erro-padrão robusto
agrupado por prédio.

| Nome | O que mede | Controles |
|---|---|---|
| reta (deslocamento) | coeficiente do resíduo na exposição | log n, fração de habilitação manual, variação do comparecimento |
| reta (inversão) | idem, exposição × sinal de quem liderava na seção no 1º turno | os mesmos + sinal, sinal×comparecimento, sinal×comparecimento² |
| dispersão | coeficiente do quadrado do resíduo de Pearson (escala binomial) na exposição | os mesmos da reta do tipo |
| curvatura | Wald dos contrastes de decil de exposição dado o termo linear (decis empatados fundidos), como t equivalente | os mesmos |
| agrupamento | a reta refeita dentro de cada UF, zona e município válidos | os mesmos (coeficientes nacionais) |
| chegada | índice de dispersão D das contagens de 15 min em torno da curva do prédio; resíduo × log D | os da reta |
| volume | reta e inversão nas exposições por volume | os da reta + comparecimento, comparecimento², comparecimento³, log aptos |

## 5. Nulo e limites (fixos)

- **Bonferroni** (analítico): `|t| > Φ⁻¹(1 − 0,05 / m)`, m = 2 tipos × janelas válidas (reta, dispersão,
  curvatura); m = 2 × janelas válidas × grupos válidos (agrupamento, por nível).
- **Permutação dentro do prédio** (principal): o vetor de horários de cada seção é embaralhado entre as seções do
  mesmo prédio (preserva prédio, tamanho, 1º turno, BU e controles; quebra só o vínculo horário ↔ resíduo).
  NPERM = 60. Em cada permutação registra-se o máximo de |t| sobre todas as janelas válidas, por tipo, para a
  reta, a dispersão e cada nível de agrupamento. **Limite = percentil 95 desses máximos.** A curvatura não entra
  na permutação (custo) e fica só com Bonferroni.
- Os dois limites são informados; quando divergem, vale o de permutação.

## 6. Régua de calibração (fixa)

Cópias de 2026 com regras plantadas, antes de olhar 2022: "2 para 1" (metade dos votos do adversário na janela
vira voto do PT) e inversão (os votos da janela trocam de lado), nas janelas 14h–15h, 10h–12h, 16h–17h, 8h–8h30 e
12h–12h15; no país, em 20% das seções sorteadas e só em MG. Em forma de cluster, nas janelas 14h–15h e 16h–17h:
país, 20% e 5% das seções sorteadas, 30 zonas sorteadas, só seções com exposição acima do 70º percentil. Por
volume: a partir do voto 200 e 300, a partir de 60% dos aptos, só os últimos 30 votos; país e 20% das seções.
Semente 0. Um cenário "escapou" quando a estatística na janela/regra plantada fica abaixo do limite.

## 7. Regra de decisão (hierárquica, fixa)

Para cada família (reta, dispersão, curvatura, agrupamento por nível, volume) e tipo:

1. **Nada a sinalizar** se o máximo de 2026 fica abaixo do limite por permutação (ou de Bonferroni, nas famílias
   sem permutação).
2. Se passa do limite, comparar com 2022 medido do mesmo jeito:
   - **Padrão de comportamento** (resultado negativo, documentado): 2022 passa do limite na mesma região da grade
     (janelas com exposição correlacionada ≥ 0,98 com a de 2026) e com o mesmo sinal. Quem vota tarde ou cedo não
     é o mesmo público, e isso não é regra de programa.
   - **Destoante, a investigar**: 2026 passa, e em 2022 a mesma região não passa, ou passa com sinal contrário.
     O passo seguinte é o cenário plantado mais parecido (tamanho do efeito, fração de seções) e a leitura dos
     logs e RDVs das seções/zonas apontadas; nunca a conclusão.
   - **Indeterminado**: ambos passam em regiões diferentes da grade. Fica registrado como tal.
3. Em qualquer caso o relatório mostra os três números lado a lado: 2026, 2022 e as cópias plantadas.
4. Nenhum resultado desta varredura, sozinho, afirma irregularidade. O texto do relatório mantém "descritivo —
   não indica irregularidade por si só".

## 8. O que o protocolo não decide

Regra proporcional e idêntica em todas as seções, sem momento (não cria diferença entre vizinhas); regra em
poucas dezenas de urnas escolhidas; regra "a cada k-ésimo voto" (o RDV é ordenado e o log não tem candidato);
relógio da urna errado (a janela desloca junto). Esses limites estão no relatório.

## 9. Histórico antes do travamento (mudanças feitas depois de ver dados de 2026)

| Data | Mudança | Motivo |
|---|---|---|
| 03/11 manhã | controles suaves de comparecimento nas regras por volume | a exposição por volume é função do comparecimento, e o comparecimento relativo ao prédio se relaciona com o resíduo (nos dois anos, sinais opostos) |
| 03/11 manhã | controles de sinal (quem liderava no 1º turno) no teste de inversão | sem eles o resíduo M1 dá |t| ≈ 80 por construção, nos dois anos |
| 03/11 11h | grade começa às 5h | urnas do AC em 2022 marcam votos às 6h no relógio local |
| 03/11 11h | filtro de janela válida (1% dentro, 1% fora) | a primeira varredura deu |t| = 79 numa janela com uma única seção exposta (voto depois das 19h45) |
| 03/11 13h | validade de grupo (10% / 30 seções de cada lado) | a varredura por zona deu |t| > 200 em janelas que cobrem o dia inteiro, com a variação concentrada em meia dúzia de seções |
| 03/11 13h | decis empatados fundidos na curvatura | matriz singular em janelas com muitas seções de exposição zero |
| 03/11 14h | nulo por permutação dentro do prédio (NPERM 60) e esta regra de decisão | Bonferroni sobre milhões de testes correlacionados é grosseiro; a regra de decisão precisava existir antes do controle |

Nenhuma dessas mudanças foi feita olhando o 2022: a varredura de 2022 nos logs não existia até este travamento.

Como repetir: `scripts/janelas_horario.py coleta <ano> | janelas <ano> | clusters <ano> | permutacao <ano> | plantadas |
clusters_plantadas | volume` e `scripts/make_janelas_report.py`.
