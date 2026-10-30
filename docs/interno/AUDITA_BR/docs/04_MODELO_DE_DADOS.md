# 04 — Modelo dimensional, esquema lógico e dicionário de métricas

`db/schema.sql` é o ponto de partida de DDL. Não tratar DDL inicial como prova de compatibilidade final: a implementação deve criar migrações, executar teste em DuckDB de versão fixada e reconciliar estruturas físicas de parquet com as views.

## 1. Grãos das tabelas — regra mais importante do projeto

| Tabela/fato | Um registro representa | Chave de negócio |
|---|---|---|
| `election` | Um pleito (ano, tipo) | ano + tipo |
| `election_round` | Um turno nacional de um pleito | pleito + número turno |
| `contest` | Uma disputa de cargo por circunscrição | turno + cargo + distrito |
| `section_instance` | Uma seção **no turno do pleito** | turno + UF + mun/TSE + zona + seção |
| `polling_place` | Um local eleitoral no contexto do turno | turno + município + zona + local |
| `section_turnout` | Aptos/presentes/ausentes da seção | seção + snapshot |
| `candidate_vote` | Votos de um candidato/cargo/seção | seção + disputa + candidato + status + snapshot |
| `contest_vote_summary` | Consolidação da cédula do cargo por seção | seção + disputa + snapshot |
| `operational_event` | Um evento operacional identificado no log | asset + membro + linha/evento + dispositivo |
| `operational_section_metrics` | Indicadores dos logs por seção | seção + snapshot |
| `historical_section_link` | Uma relação não necessariamente 1:1 entre seções de eleições distintas | instância A + B + metodologia |
| `dataset_coverage` | Disponibilidade de família de fonte no recorte | turno + UF + família + snapshot |
| `audit_finding` | Um resultado de uma análise com parâmetros fixados | análise + seção/agrupamento + tipo |

**Falha proibida:** duplicar `voters_present` ao juntar cada linha de candidato, somando comparecimento várias vezes. Somar `section_turnout` apenas em conjunto de **chaves distintas por seção**. O mesmo vale para fatos por cargo em eleições com várias disputas.

## 2. Dimensões e entidades

### 2.1 Pleitos

Tipos: municipal (2012, 2016, 2020, 2024) e geral (2014, 2018, 2022, 2026). `election_round` representa o calendário, mas a aplicabilidade de um turno por local/cargo só é verificada em `contest`. `contest` nunca cria SENADOR/turno 2. `status`: `SCHEDULED`, `IN_PROGRESS`, `PROVISIONAL`, `OFFICIAL`, `SUPERSEDED`, `NOT_APPLICABLE`.

### 2.2 Cargos e regras de vaga

`office_code` enum fechado: `PRESIDENTE`, `GOVERNADOR`, `SENADOR`, `PREFEITO`.

- Presidente: distrito BR; votos por candidato por seção, inclusive seções no exterior quando observadas; 1 vaga; possível 2T.
- Governador: distrito UF/DF; 1 vaga; possível 2T segundo resultado regional.
- Senador: distrito UF/DF; **1 vaga em 2014 e 2022, 2 vagas em 2018 e 2026**; **somente 1T**. Os registros representam **votos ao cargo**, não eleitores individuais; candidatos ao Senado podem receber votos de um mesmo eleitor no pleito de duas vagas. O conceito de quantidade de votos por eleitor/vagas deve ser validado no layout e na regra eleitoral.
- Prefeito: distrito municipal; 1 vaga; 2T apenas para municípios que se enquadram e onde realmente ocorreu disputa.

Observação: no Senado, **nem todos os eleitores necessariamente utilizam as duas escolhas**; não se presume que total de votos válidos equivale exatamente a `comparecimento × 2`. O teto técnico das escolhas possíveis é uma propriedade do cargo/ano, mas brancos/nulos por vaga e outros estados de voto requerem especificação própria.

### 2.3 Geografia

Chaves TSE `CD_MUNICIPIO` podem diferir de códigos IBGE. Não usar `codigo_mun` isoladamente em todo o país sem UF. `NR_ZONA`, `NR_SECAO`, `NR_LOCAL_VOTACAO` são texto numérico normalizado com padding quando necessário, mas preservar o campo original. Exterior (`ZZ`) deve ter regras próprias. A mesma escola pode ter vários códigos, se mudar de endereço/nome, ou um código pode ser reciclado; manter unidade temporal por eleição/turno.

### 2.4 Candidatos

Candidato identificado por eleição/cargo/código do TSE; não por nome completo (homônimos e grafias). `candidate_instance_id` varia quando a entidade cadastral foi substituída; partido e chapa são atributos versionados. Dados pessoais não necessários à pesquisa (CPF/endereço pessoal) não devem entrar na base analítica, ainda que disponíveis na fonte.

### 2.5 Fonte e proveniência

`source_dataset` = dataset catálogo; `source_resource` = item público; `source_asset` = bytes observados; `lineage` = derivação. `source_asset_id` é obrigatório em toda métrica base. Dataset/versionamento e pipeline/versionamento não são o mesmo: arquivo atualizado mas parser fixo vs parser atualizado com arquivo fixo.

## 3. Dicionário de métricas oficiais

| Nome canônico | Unidade | Fórmula/regra | Quando é nulo |
|---|---|---|---|
| `voters_eligible` | eleitores | QT_APTOS no grão da seção/turno ou equivalente validado | Fonte sem aptos |
| `voters_present` | eleitores | comparecimento oficial | Ausência de campo |
| `voters_absent` | eleitores | abstenção oficial | Ausência de campo |
| `abstention_rate` | 0..1 | ausentes / aptos | aptos <= 0, desconhecidos ou inconsistentes |
| `turnout_rate` | 0..1 | presentes / aptos | idem |
| `nominal_votes` | votos por cargo | soma de votos nominais elegíveis no cargo | ausência do cargo/turno |
| `blank_votes` | votos por cargo | definição específica do layout | desconhecida |
| `null_votes` | votos por cargo | definição específica do layout | desconhecida |
| `candidate_share_valid` | 0..1 | votos elegíveis do candidato / votos válidos segundo regra | base válida ausente |
| `candidate_share_nominal` | 0..1 | votos do candidato / total nominal do cargo | total nominal zero |
| `section_log_vote_events` | eventos | número de eventos comprovados 'voto computado' | log sem validação |
| `after_cutoff_events` | eventos | eventos comprovados depois do corte legal normalizado | timestamp/relógio não confiável |
| `after_cutoff_rate` | 0..1 | eventos tardios / eventos válidos com horário classificável | sem eventos válidos |
| `manual_confirmed` | eventos | habilitações manual/alternativas **confirmadas** por regra de log | método indisponível |
| `biometric_confirmed` | eventos | biometria efetivamente confirmada por sequência | método indisponível |
| `no_enrollment_evidence` | eventos | indício específico de ausência de biometria cadastrada, conforme log | evidência insuficiente |
| `unclassified_habilitation` | eventos | evento de voto sem prova de classe de habilitação | nunca converter em manual |
| `operational_coverage` | 0..1 | seções com log válido / seções esperadas | denominador não determinado |
| `log_vs_turnout_delta` | eleitores/eventos | eventos voto computado - comparecimento oficial | sem junção válida |

Importante: `after_cutoff_events` é **atividade da urna**, não 'votos em candidato após 17h' e não necessariamente votos ilícitos. As taxas de habilitação só se tornam comparáveis entre eleições quando a taxonomia e cobertura do log forem equivalentes ou ajustadas.

## 4. Abstenção: medidas diferentes

- **Agregada/ponderada:** `SUM(absent)/SUM(eligible)` — taxa real do conjunto.
- **Média de seção (não ponderada):** `AVG(absent/eligible)` — perfil da seção média, não a taxa agregada.
- **Diferença em pontos percentuais:** `(p_ano_b - p_ano_a) * 100`, com nota sobre mudança de eleitorado e composição.
- **Diferença relativa:** `(p_b - p_a)/p_a`, quando `p_a > 0`.
- **Histórico com geometria variável:** quando houve divisão/agregação/mudança de local, exibir comparação ao nível mais estável (município/UF) ou mostrar a incerteza de links de seção.

## 5. Reconciliação e exemplos

**Comparecimento:** para uma seção comum, `aptos = presentes + ausentes` deve ser verificado; caso não bata, gerar `quality_issue`. Entretanto, casos especiais (seções agregadas, voto em trânsito, exterior e categorias de arquivo) exigem confirmação de semântica antes de classificar discrepância como erro.

**Candidatos:** para cargo de uma escolha, soma de votos nominais/brancos/nulos e categorias oficiais deveria conciliar com total de escolhas no cargo; **jamais igualar cegamente** ao comparecimento sem olhar as regras do cargo. Para senador com duas vagas, analisar **dois slots possíveis** por eleitor, sem duplicar comparecimento.

**Logs:** comparar `section_log_vote_events` a `voters_present` apenas quando o evento representa exatamente um eleitor que concluiu a votação, com logs completos, eleição/dia corretos, seções e urnas substituídas concatenadas. Divergências podem decorrer de erro de parser, eventos ausentes, substituição, contingência, datas, capturas parciais; investigar antes de qualquer conclusão.

## 6. Tipos de ausência e semântica de `NULL`

- `NOT_APPLICABLE`: não existe segundo turno, cargo não disputado, fonte não pertinente.
- `NOT_PUBLISHED`: recurso não publicado até a data do inventário.
- `NOT_DISCOVERED`: tentativa de descoberta sem localização confiável.
- `DOWNLOAD_FAILED`: fonte existe, mas acesso/download falhou.
- `PARSER_UNSUPPORTED`: formato obtido não suportado.
- `INVALID`: valor processado falhou consistência.
- `CLOCK_UNCERTAIN`: evento existe, mas comparação temporal é inadequada.
- `UNKNOWN`: classe ou valor indeterminado com fonte presente.
- `PROVISIONAL`: dados ainda sujeitos a atualização/correção.

`0` é um resultado válido e se diferencia de todas as classes acima. Não mostrar 0% biometria se não foi possível classificar nenhuma habilitação.

## 7. Contratos físicos no data lake

Partições do tipo:

```text
storage/silver/turnout/ano=2022/turno=1/uf=MA/part-00001.parquet
storage/silver/votes/ano=2022/turno=1/cargo=PRESIDENTE/uf=MA/part-00001.parquet
storage/silver/log_events/ano=2026/turno=1/uf=MA/tipo=VOTE_COMPUTED/part-00001.parquet
storage/silver/log_habilitation/ano=2026/turno=1/uf=MA/part-00001.parquet
storage/gold/metrics/ano=2026/turno=1/uf=MA/part-00001.parquet
```

Configurar Arrow schemas fixos. Não usar `float` em contagens. Identificadores como zona, seção, município, candidato e título de dataset são strings normalizadas para preservar zeros significativos; datas ISO com timezone explícito quando forem instantes, e timestamp **sem timezone** apenas quando deliberadamente representarem 'hora civil local original'.

## 8. SQL de análise ilustrativo

```sql
-- Taxa agregada por UF: uma linha por seção, não um join multiplicativo com candidatos.
SELECT s.uf,
       SUM(t.voters_eligible) AS aptos,
       SUM(t.voters_present) AS comparecimento,
       SUM(t.voters_absent) AS abstencoes,
       SUM(t.voters_absent) * 1.0 / NULLIF(SUM(t.voters_eligible), 0) AS taxa_abstencao
FROM section_turnout t
JOIN section_instance s USING (section_instance_id)
WHERE s.round_id = 'BR-2022-GERAL-T1'
  AND t.snapshot_id = :snapshot_id
  AND t.validation_status = 'VALID'
GROUP BY s.uf;
```

O identificador de `round_id` do exemplo é ilustrativo; a implementação só pode utilizá-lo se o gerador canônico de IDs efetivamente produzi-lo.

## 9. Identificação de seções históricas

Nunca montar uma chave única histórica com `UF + zona + seção` somente. Usar link multigrafo, dirigido pelo tempo, com `linkage_method`:

- `OFFICIAL_RENUMBERING`: documento oficial une duas instâncias;
- `SAME_VERIFIED_TSE_LOCATION_CODE`: estabilidade explícita dentro do município e escopo;
- `SAME_ADDRESS_CONFIRMED`: comparação de endereço normalizado com validação;
- `FUZZY_NAME_ADDRESS`: correspondência aproximada marcada `LOW/MEDIUM`;
- `NO_LINK`: não comparável.

Permitir transições 1→N, N→1, N↔M, e divisões de seção. Agregações históricas de comparecimento devem ser explicitamente ponderadas. Nenhum link aproximado autoriza afirmar 'a mesma seção' sem ressalva.
