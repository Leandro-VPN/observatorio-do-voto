# 08 — Contrato de API, interface de pesquisa e relatórios

## 1. Propósito da API

A API FastAPI é uma fachada tipada sobre DuckDB/Parquet; não substitui nem tenta simular API de consulta transacional do TSE. O CKAN do TSE é **entrada de catálogo**; o backend próprio consulta arquivos locais padronizados. A arquitetura evita baixar um ZIP a cada filtro do usuário.

Todos os endpoints usam versão `/api/v1`, respostas JSON com metadados obrigatórios e paginação de registros detalhados. Valores ausentes são `null` acompanhados por `availability_status`, nunca `0` para simular ausência.

## 2. Envelope de resposta

```json
{
  "data": [],
  "meta": {
    "snapshot_id": "<published-snapshot>",
    "as_of": "2026-10-12",
    "scope": {"year": 2022, "round": 1, "office": "PRESIDENTE", "uf": "MA"},
    "source_coverage": {"status": "PARTIAL", "sections_observed": null, "sections_expected": null},
    "methodology_version": "1.0.0",
    "limitations": []
  },
  "pagination": {"cursor": null, "has_more": false}
}
```

Valores entre `<>` são placeholders, não dados reais. A API deve usar nomes em inglês canônicos nos contratos para reduzir deriva no código, mas toda a interface exibe pt-BR.

## 3. Endpoints propostos

### Catálogo, evolução e contexto

- `GET /api/v1/health` — prontidão/versões e estado do storage, sem dados sensíveis.
- `GET /api/v1/elections` — pleitos, tipos, situação e datas.
- `GET /api/v1/elections/{election_id}/rounds` — turnos aplicáveis/estado temporal.
- `GET /api/v1/offices?year=2026` — apenas quatro cargos elegíveis conforme pleito.
- `GET /api/v1/contests?year=&round=&office=&uf=&municipality=` — disputas reais, sem 2T inexistente.
- `GET /api/v1/catalog/datasets?family=&year=` — fonte descoberta, formatos.
- `GET /api/v1/catalog/resources?dataset_id=` — IDs reais e URLs oficiais.
- `GET /api/v1/catalog/coverage?year=&round=&uf=&family=` — cobertura, qualidade e ausências.
- `GET /api/v1/catalog/snapshots` — versões publicadas.

### Navegação geográfica

- `GET /api/v1/geography/states?year=&round=`
- `GET /api/v1/geography/municipalities?year=&round=&uf=`
- `GET /api/v1/geography/zones?year=&round=&uf=&municipality=`
- `GET /api/v1/geography/places?year=&round=&uf=&municipality=&zone=`
- `GET /api/v1/geography/sections?year=&round=&uf=&municipality=&zone=&place=`
- `GET /api/v1/geography/sections/{id}` — seção, vínculo histórico, local, cobertura e flags.

### Métricas e exploração

- `GET /api/v1/metrics/turnout?year=&round=&group_by=uf|municipality|zone|place|section&...`
- `GET /api/v1/metrics/votes?year=&round=&office=&candidate=&group_by=...`
- `GET /api/v1/metrics/times?year=&round=&uf=&group_by=&clock_policy=trusted_only`
- `GET /api/v1/metrics/habilitation?year=&round=&uf=&group_by=&denominator=classifiable|all_valid`
- `GET /api/v1/metrics/historical?metric=&years=2012,2016,2020,2024&group_by=...`
- `GET /api/v1/metrics/compare-sections?section_id=&reference=place|municipality|state`
- `GET /api/v1/metrics/reconciliation?year=&round=&uf=&issue_type=`
- `GET /api/v1/analytics/funnel?metric=&year=&round=&uf=&model_version=`
- `POST /api/v1/analytics/preview` — processar seleção de métricas somente no snapshot; limite por usuário e contexto.

### Casos, fontes e relatórios

- `GET /api/v1/findings?analysis_run_id=&status=&severity=&...`
- `GET /api/v1/findings/{id}` — evidência, explicações alternativas, revisão.
- `GET /api/v1/assets/{source_asset_id}/metadata` — proveniência, hash e URL, sem entregar raw sensível.
- `POST /api/v1/reports` — gera relatório em background **no próprio programa**; retorna `job_id` somente após enfileirar de verdade.
- `GET /api/v1/reports/{id}` — metadados e disponibilidade.
- `GET /api/v1/reports/{id}/download?format=csv|json|md|html|parquet`

### Administração (local/token autenticado)

- `POST /api/v1/admin/catalog/refresh`
- `POST /api/v1/admin/ingestions` — plano de aquisição controlado.
- `GET /api/v1/admin/jobs` — progresso/estado.
- `POST /api/v1/admin/reprocess` — reprocessar partição em novo run/snapshot.
- `POST /api/v1/admin/validate` — QA em recorte.
- `POST /api/v1/admin/publish` — publicação atômica após gates.

Endpoints de escrita não devem ficar acessíveis ao público sem autenticação, autorização e limitação por taxa.

## 4. Validação de filtros

`year` pertence à lista declarativa de oito eleições. `office` pertence ao conjunto fechado e é compatível com o ano. `round=2` requer disputas reais naquela geografia/cargo. UF validada incluindo `ZZ` especial. Município é código TSE **mais UF**. `group_by` enumerado e limites de granularidade impostos para evitar consulta de milhões de linhas não paginadas. Parâmetros de análise temporal exigem cobertura operacional e política de fuso. Qualquer filtro incompatível deve produzir resposta explicativa 422/404/`NOT_APPLICABLE`, nunca consulta vazia enganosa.

## 5. Páginas e componentes do painel

### 5.1 Visão Brasil

KPIs por seleção: aptos, presentes, ausentes, taxa de abstenção, número de seções cobertas/esperadas, votos nominais pelo cargo escolhido, abrangência geográfica, status do pleito. Pequeno bloco de `Origem: TSE; snapshot; atualização` e cartões de **cobertura**. Mapa estadual **somente** onde há geocódigos ou localizações válidas; se sem coordenadas, tabela/cartograma alternativo (não inventar coordenadas).

### 5.2 Filtros globais

`Eleição`, `Turno`, `Cargo`, `UF`, `Município`, `Zona`, `Local`, `Seção`, `Snapshot`; filtros avançados `Tipo de fonte`, `Cobertura mínima`, `Relógio validado`, `Mínimo aptos`, `Intervalo do dia`. `Turno` depende de `Cargo` e circunscrição. A escolha de prefeito remove cidades fora do pleito; a escolha de senador não apresenta T2.

### 5.3 Resultados por cargo

- Barras ordenadas, totais e porcentagens válidas; candidato/partido/chapa/situação.
- Comparação entre UFs/municípios respeitando circunscrição.
- **Senado 2018/2026:** nota visível '2 vagas, até duas escolhas por eleitor'; tooltip com denominador e regra específica; evitar percentuais que possam sugerir total de 100% dos eleitores por candidato.
- Data da extração e tipo de resultado (oficial/provisório/retificado).

### 5.4 Abstenção

- Taxa de abstenção ponderada; aptos/presentes/ausentes e distribuição de seções.
- Histograma, funil vs aptos, mapa e tabela.
- Filtros de extremos alto/baixo; não privilegiar uma direção.
- Seção selecionada vs outras da escola, município, UF e Brasil; preservar gráficos de todos os grupos.
- Série histórica com divergência de universo por pleito e links de seção explícitos.

### 5.5 Horários (quando há logs validados)

- KPI `seções com logs válidos`, `eventos computados`, `eventos depois do horário regular` e `relógio incerto`.
- Série horária local/BRT com fusos anotados.
- Comparação da seção com as outras da escola; intervalos, histograma de eventos, último voto, fim real se publicado e confiável.
- Visão de concentração após cutoff com n absoluto + percentual, denominador e exclusões por falta de relógio.
- Marcador separado `hora de recepção/totalização`, se existir: **não sobrepor sem legenda a voto computado**.

### 5.6 Habilitação

- Classes confirmadas e desconhecidas, números absolutos e %.
- Quando o registro é apenas indício, mostrar **indício**.
- Taxa de classificabilidade e cobertura.
- Distinção visual entre manual confirmado, biográfico, ausência de cadastro e confirmação biométrica.
- Tooltip obrigatório: 'Procedimento manual não equivale necessariamente a assinatura no caderno e não determina voto'.

### 5.7 História e comparação

Seleção livre de até oito pleitos. Para prefeito, comparação municipal; para presidente, nacional/UF; para governador/senador, UF. Mapa de mudanças de local/seção indica links fortes e fracos. 'Mesmo número de seção' não é prova de identidade histórica.

### 5.8 Cruzamentos e casos

Matriz de dispersão e filtros de múltiplos indicadores. Casos agrupados por tipo de problema, não 'pontuação de fraude'. Cada caso mostra explicações alternativas, qualidade das fontes, cobertura, evidência e revisão humana.

### 5.9 Fontes e Qualidade

Tabela por ano/turno/UF/família: dataset, recurso, status, bytes, hash, data, n registros, n seções, % cobertura, parser, avisos, última revisão. Ver itens que faltam, diferente de status `0`.

### 5.10 Metodologia

Página fixa com dicionário de métricas, fórmulas e diferenças entre comportamento atípico e irregularidade. Transparência de ajuste de múltiplos testes e fundamentos da hipótese. Ver decisão de exclusão e qual denominador foi escolhido.

## 6. Relatórios e documentação gerada

Todo relatório deve incluir:

1. título, pergunta, período e unidade;
2. versão e data de referência;
3. detalhamento da fonte e arquivo SHA-256;
4. percentagem de cobertura e mudanças de esquema;
5. filtros exatos, tamanho da amostra e exclusões;
6. fórmula de cada taxa e comparação;
7. tabelas e gráficos com legendas completas;
8. limitações e explicações alternativas;
9. conclusão compatível com a evidência: **observação estatística**;
10. comandos para reprodução e `report_manifest.json`.

Exports CSV devem incluir colunas `election_year, round, office, uf, municipality_tse, zone, place_code, section, metric_name, numerator, denominator, value, source_coverage_status, snapshot_id, method_version`, quando aplicáveis. Se for export de candidato, incluir identificador do candidato e legenda.

## 7. Performance de interface

- Cache por snapshot, filtros e versão do método (invalidar ao trocar snapshot).
- Queries DuckDB paginadas com `LIMIT` e cursor quando conveniente.
- Agregação em SQL e Parquet pushdown; não trazer 100 milhões de eventos para o Streamlit.
- Pré-materializar por UF/município nos painéis mais frequentes.
- Gráficos com muitos pontos devem amostrar só para visualização **com rótulo** e deixar tabela completa para download.
- Em caso de arquivo ausente, usar placeholders de indisponibilidade, não exceção genérica em branco.

## 8. UX de confiança

Cores não carregam inferência moral; intensidade de cor pode indicar magnitude, com legenda. Status de confiança é documental (`fonte íntegra, log validado, relógio confiável`), não 'chance de fraude'. Mostrar fonte original em link, método em detalhes e estado de revisão humana.

## 9. Padrão de resposta em caso de indisponibilidade

```
Não foi possível calcular a taxa de habilitação manual para 2016 neste recorte.
Motivo: não há logs operacionais classificados e validados para este pleito
na instalação atual. Resultados e abstenção continuam disponíveis.
Cobertura: 0 de N seções com logs validados, onde N foi verificado;
ou cobertura desconhecida se o universo ainda não foi estabelecido.
```

Se `N` não foi obtido, não interpolar o valor.
