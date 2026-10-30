# 06 — Metodologia estatística, detecção exploratória e limites inferenciais

## 1. Objetivo analítico

Detectar **desvios mensuráveis** nos resultados, abstenção e eventos operacionais, com máxima resistência a vieses de tamanho da seção, região, composição demográfica, troca de local, diferenças de sistema, ausência de fonte e variação aleatória. Não existe 'índice científico de fraude' inferível destes dados. O resultado é uma lista **priorizada para revisão documental**, não condenação, suspeita pessoal ou inferência de causa.

**Metodologia deve ser transparente, versionada, configurável e testada com dados simulados e negativos**, inclusive se resultados não mostrarem qualquer anomalia.

## 2. Pré-condições (gates)

Nenhum cálculo avança sem:

1. `source_validated = TRUE` ou restrição transparente a descritivos.
2. `office_scope` correto; disputa de prefeito não existe em eleição geral.
3. Chave completa seção/pleito/turno; ausência de duplicidade.
4. Denominador explícito e >= limite mínimo pré-definido.
5. Cobertura mínima e `coverage_missingness` exibida; sem zero em recursos faltantes.
6. `clock_confidence = TRUSTED/VALIDATED_CORRECTED` para métricas tardias.
7. Comparador regional/histórico apropriado; tamanho amostral e seleção verificados.
8. Regras/categorias do ano comparáveis ou análise estratificada por versão.

## 3. Análise de abstenção

Para seção i com `n_i = aptos`, `a_i = ausentes`, `p_i = a_i/n_i`. Taxa de agregação de um conjunto S:

\[
 p_S = \frac{\sum_{i\in S} a_i}{\sum_{i\in S} n_i}.
\]

A média simples `AVG(p_i)` mede o perfil da seção típica, não do conjunto de eleitores, e não pode ser exibida como taxa geral.

### 3.1 Base comparadora leave-one-out

Para município g, preferir:

\[
 \hat p_{-i,g}=\frac{\sum_{j\in g,j\ne i}a_j}{\sum_{j\in g,j\ne i}n_j}.
\]

Se não houver tamanho/quantidade suficiente, recuar para UF (também excluindo a seção) e documentar o fallback. Para locais pequenos, considerar comparações hierárquicas robustas ou não emitir score.

### 3.2 Z binomial simplificado

\[
 z_{bin,i}=\frac{a_i-n_i\hat p_{-i,g}}{\sqrt{n_i\hat p_{-i,g}(1-\hat p_{-i,g})}}.
\]

Não usar como único padrão, porque presume independência e homogeneidade entre seções, frequentemente falsas. Em população enorme, pequenas diferenças podem ser significativas mas operacionalmente irrelevantes.

### 3.3 Z de taxa com sobredispersão

Uma opção exploratória inspirada pelo repositório de referência é:

\[
 z_{adj,i} = \frac{p_i-\hat p_{-i,g}}{\sqrt{\hat p_{-i,g}(1-\hat p_{-i,g})/n_i + \tau_g^2}}.
\]

`tau²` estima heterogeneidade real residual; não é 'ruído de fraude'. A referência calcula robustamente com mediana/MAD e ajusta em nível UF. Na implementação, validar estimativa em simulação, usar shrinkage quando houver poucos grupos, evitar coeficientes que tornem score arbitrariamente alto ou baixo; documentar se for método heurístico, e não 'modelo de efeitos aleatórios exato'.

Alternativa preferida para validação aprofundada: modelo beta-binomial (ou hierárquico) com sobredispersão, estimado em coortes comparáveis por município/UF, verificando pressupostos. Exibir efeito absoluto (pontos percentuais), intervalo preditivo e percentil empírico, não só z.

### 3.4 Faixas e funil

Para n eleitores, `p` base e heterogeneidade `tau²`, usar limites exploratórios:

\[
 p \pm k\sqrt{\frac{p(1-p)}{n}+\tau^2}.
\]

`k=2` e `k=3` são configurações de visualização, **não** critérios jurídicos. Em modelos estimados, preferir intervalo de predição calibrado. Exibir escala n e legenda da dispersão, e especificar se a linha representa intervalo binomial, overdispersion ou empírico.

## 4. Tempo de votação e atividade após janela regular

Denominador é o número de eventos com `VOTE_COMPUTED` e tempo **validado**, não votos nominais de presidente ou prefeito. Definir:

\[
 p_{tardio,i} =\frac{n_{\mathrm{evento>corte},i}}{n_{\mathrm{evento\ válido},i}}.
\]

Respeitar exatidão de segundos. Um evento exatamente às 17:00:00 é **no limite**, não 'após', salvo regra explícita diferente. Exibir comparação estrita `>` e janela `17:00:01...` conforme precisão do log. O corte deve ser calculado no fuso/ano/localidade corretos. Construir histogramas de hora em UTC para cálculo, mas apresentação pode ser BRT e/ou local com rótulos claros.

Medidas auxiliares: quantis de instante de voto, último evento, mediana, concentração de eventos, intervalos entre eventos, hiato 16h–17h, impacto de deslocamento de relógio, distância de outras seções do mesmo local, indicador de fila coletiva inferido com **cautela**.

**Importante:** log contém eventos de conclusão de participação na urna; não permite dizer que os votos tardios beneficiaram uma candidatura. Qualquer correlação entre votos de uma seção e horários de votação é **ecológica**, jamais individual.

## 5. Biometria e habilitação alternativa

Categorias mutuamente exclusivas por ciclo concluído, conforme `05_LOGS_HORARIOS_BIOMETRIA.md`.

- `p_bio_confirmed = n_bio / n_classificavel`.
- `p_manual_confirmed = n_manual / n_classificavel`.
- `p_bio_overall = n_bio / n_eventos_voto` também pode ser mostrado, mas com rótulo distinto e não comparável à anterior.
- `unknown_rate = n_unclassified / n_eventos_voto` é sempre visível.

Não incluir no denominador os eventos que não são participação concluída; não confundir falta de cadastro e falha de leitor. Se algum ano documentar apenas **tentativa manual** e outro **manual concluída**, estas séries **não** serão comparadas diretamente.

## 6. Regras de agregação e comparações

### Hierarquia territorial

BR → UF → município → zona → local → seção. Toda métrica agregada recalculada **a partir dos numeradores e denominadores**, nunca somando percentuais, salvo medida explicitamente definida como média ponderada. Em agrupamento de logs, denominador deve ser só o conjunto com log válido, exibindo `seções cobertas/esperadas`, `comparecimento coberto/esperado`, e `população excluída por relógio`.

### Comparação entre anos

- Impedir comparação indevida de porcentagens com denominadores incompatíveis.
- Para abstenção, comparar taxa oficial por eleitorado elegível; controlar proporção de jovens, alterações do cadastro e crescimento demográfico se os dados existirem e forem adequados.
- Para voto, apresentar % de votos válidos e votos absolutos; mudanças na oferta de candidatos e turnos devem estar explícitas.
- Para Senado, separar eleições de **uma** e **duas** vagas. Um ranking de 'candidato mais votado' deve usar votos por candidato/denominador apropriado ao pleito. Em 2018 e 2026 cada eleitor podia escolher até dois candidatos; não comparar a proporção bruta do total de votos para senador de 2018 com 2022 como se as disputas tivessem uma única vaga.
- Municípios/seções podem mudar de geografia, local, número e tamanho. Comparações de seção requerem `historical_section_link` com confiança declarada.
- Distribuições de tempo antes de 2022 requerem normalização conforme horário/regulamento daquela eleição.

## 7. Detecção multivariada (apenas exploratória)

Sinais potenciais:

- abstenção baixa **ou alta** em relação a comparadores;
- diferença de horário de conclusão em relação às outras seções da mesma escola;
- elevada fração de habilitações alternativas confirmadas, com elevada cobertura de classificação;
- divergência material entre logs e comparecimento ou BU;
- deslocamento cronológico do relógio ou substituição de urna;
- mudança abrupta vs histórico, quando o vínculo da seção for confiável;
- inconsistência específica do processamento (campo fora de faixa, duplicata, cargo incorreto).

Separar em duas classes:

1. `DATA_QUALITY`: relógio, arquivo incompleto, divergência de schema, falta de fonte, duplicata, associação de seção contraditória. Não misturar com suspeita eleitoral.
2. `STATISTICAL_REVIEW`: comportamento atípico **após** passar nos gates de integridade.

Uma seção pode ter métricas altas por uma causa comum (fila, população atendida, localização remota); sinais correlacionados não são provas independentes. **Não somar z-scores como se as variáveis fossem independentes.** Se criar score combinado, especificar correlação, calibração, prevalência, explicações alternativas, e permitir exibir os componentes.

### Exemplo de elegibilidade de alerta configurável

```
min_eligible_voters = 50
min_valid_log_vote_events = 30
min_group_comparator_sections = 5
clock_quality_allow = [TRUSTED, VALIDATED_CORRECTED]
min_manual_confirmed_events = 5
min_late_events = 10
min_operational_classification_coverage = 0.90
min_operational_section_coverage_for_aggregate = 0.80
```

**Os valores são defaults propostos para teste**, não parâmetros científicos validados nem limites legais. Ajustar após avaliação em dados sintéticos, robustez, revisão de fonte e sensitivity analysis; tornar todos visíveis na UI.

## 8. Múltiplas comparações e achados excepcionais

Com centenas de milhares de seções, um limiar p < 0,01 produz muitos 'significativos' por acaso. Exigir:

- família de hipóteses pré-especificada e identificada;
- reporte de `n_tests` e correção de taxa de descobertas falsas (Benjamini-Hochberg) quando p-values forem válidos;
- intervalo de confiança/predição e tamanho de efeito;
- processo de escolha dos testes documentado (evitar p-hacking);
- validação fora da amostra ou replicação histórica quando cabível;
- zero inferências de autoria, manipulação ou causalidade apenas pelo p-value;
- método de escore heurístico identificado como heurístico, **sem p-value inventado**.

Se score z deriva de modelo robusto heurístico sem distribuição nula estabelecida, não convertê-lo em 'probabilidade de fraude' nem em p-value.

## 9. Missingness e viés de seleção

O sistema deve construir análises de cobertura antes de qualquer ranking:

- Se logs existem só para parte das UFs, não afirmar 'X% das seções brasileiras' sem qualificar cobertura.
- Se dataset só traz arquivos em situação `Totalizado`, o universo efetivo pode ser diferente do universo de seções esperadas; comparar.
- Uma proporção calculada apenas entre logs encontrados pode ser enviesada se logs faltantes estiverem correlacionados com zonas remotas, horários tardios, falhas técnicas ou eleitorado.
- Exibir panorama `UF/ano/turno -> esperado, processado, elegível, excluído, falha`.
- Não transformar ausência de log em 'urna sem votos após 17h' nem ausência de evento biométrico em 'todos manuais'.

## 10. Evidência e contraditório operacional

Antes de criar caso de revisão pública, apresentar ficha de explicações alternativas:

- fila e voto de quem já estava aguardando;
- falha de leitor biométrico;
- ausência de biometria cadastrada;
- substituição de urna/contingência;
- relógio e regra de fuso;
- agregação/cadastro da seção;
- baixa cobertura ou uso de arquivo incompleto;
- retificação de resultados;
- padrão semelhante nas outras seções do local e na região.

Cada caso inclui `evidence_strength=LOW | MODERATE | HIGH` **relativo à qualidade documental da métrica, não probabilidade de irregularidade**. Revisão humana pode classificar `EXPLAINED`, `UNRESOLVED`, `DATA_ERROR`, `REQUIRES_OFFICIAL_CLARIFICATION`, nunca `FRAUD_CONFIRMED` automaticamente.

## 11. Resultados eleitorais e tentação de inferir causalidade

Apoio a candidato e habilitação manual podem ter correlação por região, idade, renda, infraestrutura, escolaridade ou urbanização. Se houver comparação exploratória, sempre:

1. utilizar agregados por seção, não ligação pessoa-a-pessoa;
2. ajustar por confundidores **medidos** e explicar os não medidos;
3. usar métodos de robustez e controles negativos;
4. reportar apenas associação ecológica, sem imputar voto individual ou mecanismo causal;
5. proibir linguagem 'os eleitores habilitados manualmente votaram em X'.

## 12. Entregáveis analíticos obrigatórios

- Dashboard de abstenção por UF/município/zona/local/seção com taxas ponderadas.
- Distribuições por tamanho de seção e funil de controle.
- Séries 2012–2026 com comparabilidade explícita.
- Relatório de duas-vagas x uma-vaga para senador.
- Panel de eventos horários com cobertura/relógio/cutoff.
- Panel de habilitação com `confirmado`, `indício` e `desconhecido` separados.
- Relatório de discrepâncias log vs comparecimento e BU.
- Lista de casos revisáveis com origem, explicações alternativas e status.
- Documento automático de limitações por pleito/UF/fonte.

## 13. Modelo de ficha de achado

```
Identificador: RUN-... / FIND-...
Pleito/Turno/Seção: ...
Pergunta: ...
Métrica: ... (numerador = N, denominador = D, taxa = ...)
Comparador: local/município/UF/histórico (n = ..., período ...)
Diferença absoluta e relativa: ...
Modelo/versionamento: ...
Intervalo de confiança ou incerteza: ...
Cobertura de fonte: ...; classificação desconhecida: ...
Status de fuso/relógio: ...
Consistência BU x resultados x log: ...
Fontes: URL CKAN, recurso, SHA-256, parser, linha/evento
Possíveis explicações alternativas: ...
Conclusão permitida: diferença estatística / qualidade de dados / sem evidência suficiente
Revisão humana: pendente / explicada / sem resolução
```
