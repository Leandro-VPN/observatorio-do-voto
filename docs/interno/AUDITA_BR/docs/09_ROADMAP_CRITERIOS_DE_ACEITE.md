# 09 — Plano de execução, backlog e critérios de aceite

## Regra de implementação

**Entregas pequenas, verificáveis e reprodutíveis.** Não tentar construir painel completo sobre parsers não validados. O desenvolvedor deve implementar verticalmente: um estado/turno/pleito com fonte oficial, validação, API e página mínima, e só depois expandir. A ordem das etapas é condição de aceite; não confundir documentação com código pronto.

## Fase 0 — Fundação e contrato

**Entregáveis:** monorepo Python, `pyproject.toml`, ambiente reprodutível, configuração, gerador de `election_id`, enums, logger estruturado, CLI `auditabr --help`, suite pytest, esquema DuckDB com migração e amostras sintéticas.

**Aceite:** testes de restrição de cargo/turno/senador, lista de pleitos, CI local e criação de banco vazio rodam em máquina limpa. Nenhuma rede necessária para `pytest`.

## Fase 1 — Catálogo oficial e plano de downloads

**Entregáveis:** cliente CKAN paginado, `package_search/package_show`, filtros por ano/família, armazenamento versionado de metadados, manifesto de recursos, profiler para arquivo pequeno e tela/lista de fontes.

**Aceite:** descobrir resultado 2012 e dataset de arquivos 2022/2024/2026 usando **IDs reais**; exportar manifesto sem baixar ZIP grande; erro de rede não causa sucesso falso. Guardar data/URLs e apresentar status de cobertura real.

## Fase 2 — Download robusto e bronze

**Entregáveis:** downloader com cancelamento/retry/backoff/retomada/sha256, verificador de ZIP64, streaming e fallback. Suporte a arquivo existente `--input`. Estados de jobs e quarentena.

**Aceite:** teste controlado de falha de Range/ETag/ZIP; não perde bytes, não gera fonte falsa, reprocessamento idempotente. Medição de tamanho e disco antes de download.

## Fase 3 — Resultados e abstenção (núcleo prioritário)

**Entregáveis:** parsers por layout, extração de votos somente quatro cargos, `section_turnout`, `candidate_vote`, `contest_vote_summary`, comparações nacionais. Inicialmente 2022 e 2024 em uma ou duas UFs; depois estender aos oito pleitos.

**Aceite:** resultados por cargo comparados com relatórios TSE da mesma extração; taxas por estado/município corretas; sem duplicar comparecimento; 2018 e 2026 reconhecem 2 vagas no Senado; ausência de 2º turno respeitada.

## Fase 4 — Geografia por local de votação

**Entregáveis:** mapas de códigos TSE/IBGE, local de votação, agregações, `ZZ`, histórico das seções e UI drill-down.

**Aceite:** ir de Brasil à seção sem colisões; dados sem local/sem endereço aparecem como 'não disponível'; relações históricas aproximadas são rotuladas. Testar em município com seções agregadas.

## Fase 5 — Logs operacionais (2022 e 2026 primeiro)

**Entregáveis:** parsers independentes por formato e ano; máquina de estados; identificação de múltiplos dispositivos; timestamps e regras de fuso; métricas tardias, biometria/manual, cobertura; QA log vs comparecimento.

**Aceite:** amostra real de dois formatos passa em testes; classificação tem proporção de unknown explícita; não atribui voto a candidato; qualquer log com relógio suspeito não integra ranking principal sem ressalva. 2024 pode entrar na sequência após perfil de formato.

## Fase 6 — Estatística e análise cruzada

**Entregáveis:** métricas de abstenção, overdispersion, leave-one-out, funis, séries históricas, FDR para modelos válidos, análises de sensibilidade, fichas de achados e cobertura.

**Aceite:** propriedade matemática validada, dados sintéticos com sinais conhecidos detectados e controles negativos não geram excesso injustificado; nenhum score é denominado probabilidade de fraude.

## Fase 7 — Painel e relatórios

**Entregáveis:** Streamlit responsivo com telas e gráficos do documento 08, filtros encadeados, links de evidência, documentação de método, exports. FastAPI com endpoints contratados e OpenAPI.

**Aceite:** 10 casos de uso do PRD concluídos conforme disponibilidade; respostas de indisponibilidade visíveis; export contém snapshot/hash/método; testes de UX e desempenho.

## Fase 8 — Expansão nacional e retroativa

**Entregáveis:** 27 UFs + exterior quando aplicável, oito eleições, dois turnos onde existem, todos os quatro cargos aplicáveis, métricas de cobertura por família, backup/snapshot, benchmarks.

**Aceite:** inventário completo e relatório de **cobertura observada**, não objetivo fictício de 100% em famílias inexistentes; nenhuma falha de UF invalida o restante. Performance medida em escala progressiva.

## Fase 9 — Operação e publicação eventual

**Entregáveis:** comando local de startup, backup, atualização, reprocessamento; autenticação administrativa se expor remotamente; página de proveniência pública e licença própria.

**Aceite:** usuário consegue instalar, carregar um município/UF, consultar, exportar e reproduzir as principais métricas sem intervenção do desenvolvedor. Fontes e hashes auditáveis.

## Ordem de prioridade de dados

1. `election_round/contest` + resultado por seção + comparecimento/abstenção.
2. Metadados de candidatos apenas dos quatro cargos.
3. Local de votação, geografia, histórico de seção.
4. BU publicado para reconciliação.
5. Logs operacionais 2022 e 2026, depois 2024 (dependente de layout); outros pleitos apenas se evidência existir.
6. Correspondências, logs de preparação e demais fontes auxiliares.

Os anos 2012/2014/2016/2018/2020 não devem ficar bloqueados aguardando logs possivelmente indisponíveis. Valor histórico do módulo de resultados já existe independentemente.

## Backlog priorizado (P0/P1/P2)

**P0 — Inadiável:** fontes rastreáveis, snapshot, resultados e abstenção, quatro cargos, Senado duas vagas, chaves por turno, denominadores corretos, status de cobertura, comparações descritivas, CLI e testes.

**P1 — Alto valor:** locais, cruzamento BU, logs 2022/2026, fuso validado, habilitações classificáveis, múltiplos equipamentos, análise pareada por escola, relatórios exportáveis.

**P2 — Pesquisa avançada:** modelagem beta-binomial, FDR rigoroso, links históricos complexos, variáveis explicativas, geocodificação revisada, reprodução independente, API pública endurecida, documentação metodológica acadêmica.

## Critérios de aceite globais (Definition of Done)

- Documentação técnica e do usuário atualizada com o código.
- Testes automatizados correspondentes ao módulo implementado.
- Nenhum dado inferido silenciosamente.
- Status de cobertura e exceções disponíveis em consulta.
- Indicador com numerador, denominador, método e fonte.
- Entradas de TSE imutáveis e hasheadas.
- Pipeline idempotente e capaz de reprocessar.
- Sem código copiado de repositório externo em situação de licença não resolvida.
- Cada milestone mostra **comandos executados, resultados e itens ainda pendentes**.
- Ambiente local reproduzível com instruções para Windows e Linux.

## Demonstração mínima da primeira versão

Executar, por exemplo, `auditabr discover --year 2022`, `auditabr profile --...`, `auditabr ingest results --year 2022 --uf MA --round 1`, `auditabr validate --year 2022 --uf MA`, `auditabr publish`, `auditabr serve` e abrir a tela MA → Município → Zona → Local → Seção. Os comandos são especificações desejadas, ainda não implementados; o desenvolvedor pode ajustar a sintaxe e documentar a escolha.

## Critérios para implementação de recursos futuros

Novas fontes ou métricas só entram com: definição de grão; original verificável; semântica de colunas; tratamentos de não aplicável/desconhecido; risco de privacidade; teste reproduzível; documentação; espaço em disco estimado. Melhor uma cobertura parcial declarada do que uma métrica nacional enganosa.
