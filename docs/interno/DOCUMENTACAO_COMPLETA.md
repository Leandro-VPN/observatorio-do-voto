# AUDITA-BR — DOCUMENTAÇÃO COMPLETA EM ARQUIVO ÚNICO
Edição 1.0.0. Data documental: 2026-10-12. Este arquivo consolida README, prompt-mestre e os 11 documentos numerados, seguido dos contratos de configuração e SQL.
**Para a experiência mais fiel e a implementação, prefira o ZIP, que preserva arquivos individuais e scripts.**


---

# ARQUIVO: `README.md`

# AUDITA-BR — Plataforma de Inteligência, Rastreabilidade e Auditoria Estatística Eleitoral

**Especificação técnica para implementação por IA de programação.** Versão 1.0.0 | Referência temporal: **12 de outubro de 2026** | Idioma: pt-BR.

> **Missão:** construir um observatório **reproduzível, apartidário e auditável** das eleições brasileiras, com recorte de resultados restrito a **presidente, governador, senador e prefeito**, cobrindo oito pleitos (2012–2026), analisando resultados, abstenção, locais de votação, logs e procedimentos de habilitação **conforme a disponibilidade e a confiabilidade dos dados originais**.

## Comece por aqui

1. Leia `docs/01_PRODUTO_ESCOPO.md` e `docs/02_FONTES_OFICIAIS_E_COBERTURA.md`.
2. Leia `docs/03_ARQUITETURA_TECNICA.md`, `docs/04_MODELO_DE_DADOS.md` e `db/schema.sql`.
3. Leia `docs/05_LOGS_HORARIOS_BIOMETRIA.md` e `docs/06_METODOLOGIA_ESTATISTICA.md` **antes** de implementar detecção de anomalias.
4. Leia `docs/07_VALIDACAO_TESTES_SEGURANCA.md`, `docs/08_API_E_PAINEL.md` e `docs/09_ROADMAP_CRITERIOS_DE_ACEITE.md`.
5. Use `PROMPT_MESTRE_CRIACAO.md` como a primeira instrução para a IA programadora, anexando este pacote inteiro.
6. `docs/10_REFERENCIA_ESTELEICAO.md` registra o que foi estudado no repositório de inspiração e o que **não** deve ser copiado sem validação.
7. `docs/11_GLOSSARIO_E_DECISOES.md` define termos, situações ambíguas e decisões arquiteturais.

## Escopo por eleição

| Pleito | Natureza | Cargos a exibir | Turnos possíveis |
|---|---|---|---|
| 2012 | Municipal | Prefeito | 1º e, onde houve, 2º |
| 2014 | Geral | Presidente, governador, senador | 1º; 2º só presidente/governador quando aplicável |
| 2016 | Municipal | Prefeito | 1º e, onde houve, 2º |
| 2018 | Geral | Presidente, governador, senador | 1º; 2º só presidente/governador quando aplicável |
| 2020 | Municipal | Prefeito | 1º e, onde houve, 2º |
| 2022 | Geral | Presidente, governador, senador | 1º; 2º só presidente/governador quando aplicável |
| 2024 | Municipal | Prefeito | 1º e, onde houve, 2º |
| 2026 | Geral | Presidente, governador, senador | 1º disponível; 2º previsto para 25/10/2026, ainda futuro no corte documental |

**Regras mandatórias:**
- NÃO importar votos de deputados, vereadores, vice-cargos ou suplentes como resultados analíticos; vice/suplentes podem aparecer **apenas como metadados de chapa**, se necessário.
- NÃO assumir que todas as fontes, logs ou timestamps existem em todos os pleitos.
- NÃO inferir em quem uma pessoa votou a partir do horário de voto. Logs são **operacionais**, não um vínculo com a escolha individual.
- NÃO converter automaticamente eventos de habilitação manual em 'assinaturas de mesário' ou 'fraude'.
- NÃO tratar transmissão tardia de BU como voto tardio.
- NÃO interpretar sinal estatístico como irregularidade comprovada.
- Dados ausentes devem gerar **NÃO DISPONÍVEL / NÃO APLICÁVEL / INDETERMINADO**, nunca zero fictício.
- O recorte dos cargos **não** impede usar arquivos globais de comparecimento para a consistência do pleito, desde que sem importar votos de outros cargos.

## Pacote

| Artefato | Finalidade |
|---|---|
| `PROMPT_MESTRE_CRIACAO.md` | Prompt executável para IA de desenvolvimento, com condições de aceite |
| `docs/01_PRODUTO_ESCOPO.md` | Visão de produto, requisitos e casos de uso |
| `docs/02_FONTES_OFICIAIS_E_COBERTURA.md` | Inventário verificado, fontes pretendidas e descoberta via API CKAN |
| `docs/03_ARQUITETURA_TECNICA.md` | Camadas, fluxos, reprocessamento, CLI e desenho de módulos |
| `docs/04_MODELO_DE_DADOS.md` | Dimensões, fatos, grãos, versões, chaves e dicionário |
| `docs/05_LOGS_HORARIOS_BIOMETRIA.md` | Parsers, máquina de estados, tempo civil, fuso, evidência |
| `docs/06_METODOLOGIA_ESTATISTICA.md` | Indicadores, denominadores, modelos, vieses e protocolos |
| `docs/07_VALIDACAO_TESTES_SEGURANCA.md` | QA, testes de integração, privacidade e reprodução |
| `docs/08_API_E_PAINEL.md` | Endpoints, telas, filtros, exports e performance |
| `docs/09_ROADMAP_CRITERIOS_DE_ACEITE.md` | Plano de entregas, prioridades e gates de qualidade |
| `docs/10_REFERENCIA_ESTELEICAO.md` | Mapeamento de código de referência, ideias e restrições |
| `docs/11_GLOSSARIO_E_DECISOES.md` | Termos, ADRs e perguntas em aberto |
| `config/pleitos.yaml` | Matriz declarativa de eleições/cargos/turnos |
| `config/fontes_seed.yaml` | Fontes oficiais e status inicial de evidência |
| `db/schema.sql` | DDL inicial do banco analítico (DuckDB) |
| `scripts/inventariar_ckan.py` | Script utilizável de **descoberta**, sem downloads em massa |
| `tests/cenarios_aceite.md` | Especificações de fixtures e resultados esperados |

## Não concluído neste pacote

Isto é a **documentação de arquitetura**, não a aplicação pronta nem uma coleta executada. O arquivo `scripts/inventariar_ckan.py` é um auxiliar funcional de inventário de metadados, que requer rede no computador onde for executado. URLs/formatos finais de todos os anos devem ser confirmados via catálogo oficial no desenvolvimento.

## Fontes de referência

- Portal TSE: https://dadosabertos.tse.jus.br/
- API CKAN: https://dadosabertos.tse.jus.br/api/3/action/package_search
- Documentação técnica da urna 2022: https://www.tse.jus.br/eleicoes/eleicoes-2022/documentacao-tecnica-do-software-da-urna-eletronica
- TSE 2026, arquivos transmitidos: https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao
- Projeto de inspiração, não dependência: https://github.com/ralbuque/esteleicao


---

# ARQUIVO: `PROMPT_MESTRE_CRIACAO.md`

# PROMPT-MESTRE — CONSTRUIR AUDITA-BR

> Copie esta mensagem integralmente para a IA programadora e **anexe a pasta de documentação deste pacote**. Se a ferramenta aceitar projeto/repositório, disponibilize todos os arquivos. Este prompt é uma especificação de tarefa de implementação; a IA deve **escrever código, executar testes e entregar resultados verificáveis**, não só propor uma arquitetura textual.

---

## PAPEL E RESPONSABILIDADE

Atue como arquiteto sênior de software Python, engenheiro de dados especialista em processamento de arquivos grandes e auditor de consistência estatística. Construa do zero o projeto **AUDITA-BR — Plataforma de Inteligência, Rastreabilidade e Auditoria Estatística Eleitoral**. Sua responsabilidade é implementar um sistema local-first, escalável por UF/pleito, transparente, apartidário, quantitativamente correto, seguro para uso em pesquisa pública e reproduzível até o arquivo original do TSE.

**Não entregue mockups como produto final. Não preencha números reais com dados sintéticos. Não invente recursos do TSE. Não chame anomalia estatística de fraude. Não relacione voto de candidato ao horário/identidade de eleitor.**

## DOCUMENTOS DE ENTRADA E PRECEDÊNCIA

Leia e utilize, por inteiro, nesta ordem:

1. `README.md` — missão e escopo imutável.
2. `docs/01_PRODUTO_ESCOPO.md` — todos os requisitos `RF-*` e `RNF-*`.
3. `docs/02_FONTES_OFICIAIS_E_COBERTURA.md` — catálogo, semântica e limitações verificadas.
4. `docs/03_ARQUITETURA_TECNICA.md` — módulos, fluxos, dados imutáveis e stack.
5. `docs/04_MODELO_DE_DADOS.md` + `db/schema.sql` — grãos, chaves e contratos SQL.
6. `docs/05_LOGS_HORARIOS_BIOMETRIA.md` — máquina de estados e proteção contra interpretação incorreta.
7. `docs/06_METODOLOGIA_ESTATISTICA.md` — taxas, sobredispersão, tamanho amostral, correção e vieses.
8. `docs/07_VALIDACAO_TESTES_SEGURANCA.md` + `tests/cenarios_aceite.md` — qualidade e testes adversariais.
9. `docs/08_API_E_PAINEL.md` — contratos JSON, filtros e UI.
10. `docs/09_ROADMAP_CRITERIOS_DE_ACEITE.md` — ordem de implementação.
11. `docs/10_REFERENCIA_ESTELEICAO.md` — ideias do GitHub e cuidados com licença e heurísticas.
12. `docs/11_GLOSSARIO_E_DECISOES.md` e `config/*.yaml` — terminologia e regras de escopo.

Em caso de conflito, dar prioridade aos **invariantes de segurança, escopo, fonte oficial, privacidade e correção quantitativa**. Se notar inconsistência entre documento e fonte oficial, registrar em `docs/DECISOES_E_CORRECOES.md` com evidência e corrigir a implementação, sem inventar.

## ESCOPO OBRIGATÓRIO

Usar **oito pleitos**:
- Gerais: **2014, 2018, 2022, 2026** — Presidente, Governador e Senador.
- Municipais: **2012, 2016, 2020, 2024** — Prefeito.

**Não implementar resultados eleitorais de vereadores, deputados federais, estaduais ou distritais**, nem análises de vice/suplente como cargos próprios. Vices e suplentes podem aparecer somente em contexto de identificação de chapa, caso a fonte oficial exija.

Suportar turnos onde realmente houve. Senador não possui segundo turno. Eleições para o Senado em **2014/2022 têm uma vaga por UF e 2018/2026 duas vagas**; isso altera denominadores, agregações e reconciliações. Eleitor vota em vários cargos na eleição geral, mas comparecimento é contado **uma vez por eleitor**, não uma vez por cargo. Nunca somar comparecimento repetido após join com cada candidato.

**Corte da documentação: 12/10/2026.** Em 2026, 1º turno em 04/10/2026 e 2º turno previsto para 25/10/2026, onde aplicável. Se o sistema for executado posteriormente, a disponibilidade deve refletir o **TSE consultado na data da execução**, mas o pacote não pode inventar conteúdo futuro no marco documental; salvar `as_of` e status da publicação. O segundo turno de 2026 não pode aparecer como processado antes de existir.

A navegação deve funcionar em **BR → UF → Município → Zona → Local de votação → Seção**, incluindo eleições históricas, mudanças de locais/identificadores, exterior (ZZ) quando aplicável e seções agregadas.

## O QUE VOCÊ DEVE CONSTRUIR (CÓDIGO REAL)

**Tecnologias preferenciais:** Python 3.12+, Polars/PyArrow, DuckDB, Parquet, FastAPI + Pydantic, Streamlit + Plotly, Typer, Pytest/Hypothesis, `zoneinfo` e `tzdata`. Use versions fixadas em lockfile e documente mudanças técnicas indispensáveis.

Implemente:

### A. Catálogo oficial

Cliente para API CKAN do TSE, endpoints `package_search`, `package_show`, paginação, metadados de dataset/recurso, formatos, datas, licenças e IDs reais; `discover` e `profile` independentes de downloads grandes. A API CKAN é usada para **descobrir arquivos**, não se presume que fornece o resultado eleitoral detalhado em requisições linha a linha. Nunca fabricar URL/CDN por interpolação de ano se o recurso não foi verificado na origem. Os links de catálogo verificados estão nos documentos.

### B. Download gerenciado

Downloader seguro, resumível por bytes, com hash SHA-256, ETag, If-Range, validação HTTP 206/Content-Range, ZIP64, retries limitados e backoff, limite de conexões, medidor de espaço/bytes, recuperação de interrupção, `.part` e promoção atômica. Download seletivo de membros ZIP **somente se validado e seguro**; fallback integral. Importação manual de arquivo já baixado por `--input`. Não descompactar zip de origem sem limites.

### C. Data lake imutável + banco

Camadas raw/bronze/silver/gold: raw preservado, headers e metadados, fatos normalizados em Parquet particionado por pleito/turno/UF, marts DuckDB, ids e manifests, snapshots e diff de atualização. Implementar DDL/migrações e chaves, usando `db/schema.sql` como base revisável. A UI só lê snapshot que passou pelos gates de publicação. Ausência de fonte vira status verificável, **não zero**.

### D. Resultados eleitorais

Parser de CSV/TXT de resultados e votação por seção, com detecção de layout, charset e colunas. Fato `section_turnout` único por seção; fatos por candidato/contesta com filtros **apenas** para quatro cargos. Incorporar candidato/partido/situação no contexto do pleito e versionar retificações. Tratar branco/nulo e situação jurídica segundo documentação do layout, não supor regras simplistas. Comparar taxas agregadas por somas de contagens, não médias simples de porcentagens. Não associar tempo a candidato.

### E. Geografia e histórico

Códigos TSE/IBGE diferentes; `UF + código TSE` como identidade municipal eleitoral. Zona/seção dependem de eleição/turno/município. Local de votação por código do ano. Montar `historical_section_link` de confiança explícita e relações 1:N/N:1. Para ausência de vínculo histórico confiável, agregar no nível município/UF ou mostrar 'não comparável'. Geocodificação externa só com fonte e confiança; não inventar coordenadas.

### F. Logs operacionais (parte crítica)

Implementar parsers por formato/versão de logs, inicialmente 2022/2026 e 2024 quando as amostras confirmarem layout. A referência GitHub documenta `logd.dat`, `.logjez` 7z e `-log.jez` ZIP em alguns anos; confirmar magic bytes e mensagens a partir dos arquivos oficiais. Usar máquina de estados de eventos, filtrar dia/turno corretos, múltiplas urnas e substituições, conferir `voto computado` vs comparecimento. Separar: último voto, horário regular, encerramento efetivo, geração BU e recepção/totalização. Não atribuir candidato a evento.

**Biometria:** dividir evidência em biometria confirmada, alternativa/manual confirmada, ausência de cadastro comprovada, alternativa biográfica, indeterminada e conflitante. O evento de solicitação de dado pessoal não é prova de habilitação manual concluída; ano de nascimento compatível não comprova ausência de biometria cadastrada. NÃO chamar um procedimento de log de 'assinatura do mesário' sem fonte que realmente conte assinaturas físicas. Guardar confiança e taxa não classificada.

**Horário:** calcular tempo de corte por localidade, turno e regra histórica; não aplicar automaticamente 17h BRT em 2012–2020. Para 2026, TSE estabelece 8h–17h BRT. Fuso civil e desvio de relógio são coisas distintas. Salvar original e normalizado, sem correção silenciosa. Se relógio suspeito, bloquear ranking temporal principal ou marcar explicitamente como não confiável. Votar após 17h pode ser legítimo quando há fila; NÃO rotular isso de fraude.

### G. Reconciliação

Conferir aptos/presentes/ausentes, contagens oficiais e BU quando compatíveis, soma de candidato segundo cargo, logs vs comparecimento, cobertura por UF, logs ausentes e retificações. Relatório de divergência deve apontar primeiro causa técnica ou ausência de dados. Para senador com duas vagas, jamais impor a igualdade falsa `nominais do Senado = comparecimento`.

### H. Análise estatística

Taxas ponderadas, distribuição por seção, funil por tamanho, comparação leave-one-out por local/município/UF, sobredispersão (com validação de premissas), percentis, efeitos absolutos, intervalos preditivos, séries históricas compatibilizadas, análise de cobertura, controle de múltiplos testes quando houver p-values válidos. Sinais de abstenção alta/baixa, atividade tardia, habilitação alternativa e inconsistência devem ser **variáveis distintas**. Não inventar `probabilidade_de_fraude`, não tratar múltiplos desvios correlacionados como provas independentes.

### I. API e painel

FastAPI `/api/v1` e páginas Streamlit conforme documento 08: Visão Geral, Geografia, Resultados, Abstenção, Horários, Habilitação, Histórico, Cruzamentos, Casos, Fontes/Qualidade, Metodologia. Filtros dependentes e estado de cobertura em todas as páginas. A visualização por cargo mostra apenas Presidente/Governador/Senador/Prefeito aplicáveis; o Senado com duas vagas tem legenda e denominador próprios. Export CSV/JSON/Parquet e relatório Markdown/HTML com manifesto. Painel jamais oculta ausência ou insuficiência de dados.

### J. Qualidade, privacidade e documentação

Testes unitários, propriedade, integração, esquema e regressão; fixture sintética segregada. Segurança de ZIP e URL, minimização de dados pessoais, sem correlação eleitor/candidato/hora. Documentar CLI, instalação Windows/Linux, fontes oficiais, método e backup. Desenvolver código independente da referência GitHub até checar licença; registrar atribuições e decisões.

## INSTRUÇÕES DE DESENVOLVIMENTO: ORDEM OBRIGATÓRIA

**Não comece pelo dashboard.** Faça exatamente o processo em fases, com resultados executados entre elas:

1. Crie estrutura de projeto e configure Python, lockfile, lint, tipos, testes e CLI.
2. Implemente domínio de pleitos/cargos/vagas, regras de primeiro/segundo turnos e migrações DuckDB. Escreva testes para Senado, cargos excluídos e 2026/t2.
3. Implemente descoberta CKAN e catalogue fontes reais, produzindo manifesto reproduzível. Informe quais recursos foram de fato encontrados, com IDs e links; não informe arquivos como processados se só os viu no catálogo.
4. Implemente downloader e testes de integridade/recuperação; só então realize download de amostra pequena, respeitando tamanho/disco.
5. Implemente resultados/abstenção com **uma UF e um pleito** (sugestão: MA/2022/t1) e confronte com fonte TSE; exponha CLI e API para esse recorte.
6. Amplie para o pleito geral e um municipal (p.ex. 2024), somente depois de passar reconciliação, chaves e grãos. Incorpore Senado com uma e duas vagas nos testes.
7. Implemente geografia/local de votação, com cobertura e casos sem local.
8. Implemente leitura de logs no formato realmente encontrado, com máquina de estados, cronologia, fuso e classificação conservadora, além dos testes de relógio e múltiplas urnas.
9. Implemente análise estatística, baselines, qualidade e casos revisáveis; nunca usar dados inválidos para pontuar.
10. Implemente painel completo, relatórios, manuais e integração.
11. Expanda progressivamente para oito pleitos/UFs/turnos, registrando cobertura real. Logs antigos inexistentes não bloqueiam módulo de resultados.
12. Verifique desempenho, correção, segurança, licenças e conclusão de todas as histórias de usuário.

**Se executar em ambiente sem internet**, não alegue ter coletado dados; implemente cliente e testes com mocks/fixtures, deixe `DISCOVERED_NOT_FETCHED` e documente instruções para execução real. **Se a máquina não comportar o volume**, ative modo parcial por estado sem falsificar abrangência nacional. **Se houver divergência numérica**, corrija ou bloqueie a métrica antes de fazer ajustes estéticos.

## REQUISITOS DE ENGENHARIA DETALHADOS

- Criar `source_registry` versionado e função de `content_hash`.
- Garantir idempotência em ETL por hash+versão de parser+parâmetros.
- Evitar joins que duplicam comparecimento por cargo ou candidato.
- Salvar *raw* e schema fingerprint, com diffs se TSE alterar arquivos.
- Separar proveniência de dataset, recurso e bytes descarregados.
- Guardar identificadores de município, zona e seção como strings com zeros preservados.
- Usar tipos inteiros 64 bits para contagem; floating point apenas taxas.
- Documentar todo denominador e granulação de cada métrica.
- Retornar NA/UNKNOWN/NÃO APLICÁVEL onde apropriado, em vez de zeros.
- Ter testes para relógio, horário de verão, fusos especiais e timestamp em UTC/local.
- Diferenciar `clock_offset` de `timezone_offset`.
- Suportar `ZZ`, DF, seção agregada e urna substituída.
- Não presumir que os arquivos de 2024 são os mesmos contêineres de 2022/2026.
- `2026/t2` até sua ocorrência tem status `FUTURE`, não dados preenchidos.
- Garantir link da seção com fonte e status de cobertura.
- Tratar em painéis a diferença entre `último voto`, `fim real` e `transmissão`.
- Projetar jobs retomáveis com logs de exceção por UF e arquivo.
- Apresentar métricas de cobertura e indicadores de confiança DOCUMENTAL.
- Separar análise descritiva, heurística e inferência calibrada.
- Não produzir gráficos nacionais de logs quando a cobertura for insuficiente sem aviso.
- Não afirmar causalidade ou intenção de eleitores/candidatos.
- Evitar leitura de arquivo gigante com `pandas.read_csv` em memória inteira.
- Não sugerir percentual de eleitores por candidato em eleição do Senado com duas vagas usando denominador incorreto.
- Segregar fontes sintéticas de resultados reais em paths, entidades e UI.
- Usar nomes e rótulos pt-BR na UI e documentação técnica clara nos contratos.

## CONTRATOS INEGOCIÁVEIS DE ACEITE

1. Apenas quatro cargos aparecem no resultado, com contexto correto de turno e distrito.
2. 2018/2026 senador com duas vagas, 2014/2022 com uma.
3. Sem duplicação de aptos/comparecimento em joins.
4. Fonte original rastreável por URL, ID e hash, incluindo versão.
5. Falta de log/biometria → **indisponível**, não 0.
6. Biometria e manual só recebem categoria de confirmação sob evidência validada.
7. Linha de evento de voto jamais vira voto em determinado candidato.
8. Local e seções não são comparados historicamente só pelo número.
9. 2026 2º turno futuro no snapshot documental, sem dado fictício.
10. Ingestão retoma e valida downloads; corrompido vai à quarentena.
11. Relógio suspeito tratado como problema de qualidade e não inflação de alertas.
12. Taxa agregada calculada `SUM(numerador)/SUM(denominador)`.
13. Métodos estatísticos documentam modelo, comparador, cobertura, tamanho de efeito e limitações.
14. Testes do documento 07 e fixtures cobrem os casos críticos.
15. `README` ensina a instalação e a reprodução de uma análise.
16. API de consulta e Streamlit funcionam **sem logs** (modo resultados-only).
17. Fonte sintética nunca se mistura com dado oficial.
18. Não reutilizar código de terceiros com licença não verificada sem autorização e atribuição correta.

## FORMATO DE ENTREGA A CADA FASE

Ao terminar cada etapa, devolva de forma **objetiva e verificável**:

- Arquivos criados/alterados.
- Comandos executados e testes que passaram/falharam.
- Saída observada, não resultado suposto.
- Total de recursos encontrados/arquivos processados e cobertura real, se houver.
- Divergências quantitativas localizadas e decisão adotada.
- Lacunas da fonte oficial e como aparecem no sistema.
- Decisões arquiteturais relevantes no `docs/DECISOES_E_CORRECOES.md`.
- Próximo incremento de desenvolvimento **sem alterar unilateralmente o escopo**.

Se faltarem fontes atuais ou se houver incerteza técnica, faça a melhor implementação segura possível com sinalização de limitação, e não invente dados para 'fechar' a interface.

## CRITÉRIO FINAL DE CONCLUSÃO

O projeto só está completo quando permite selecionar os oito pleitos, visualizar exclusivamente os quatro cargos autorizados, explorar hierarquia até seção, consultar resultados e abstenção, examinar dados operacionais nos períodos/fontes em que existem e são validáveis, comparar historicamente com metodologia correta, emitir relatórios auditáveis, continuar downloads e reprocessamentos sem perda, e explicar em cada tela os limites dos dados.

A aplicação deve poder afirmar: **'Este número foi calculado a partir destes arquivos oficiais, nesta versão, com esta fórmula; estas são as seções cobertas, estas são as ausentes, estas são as limitações e estas são as explicações alternativas.'**

**Comece a implementação pela Fase 0, já produzindo código e testes.**


---

# ARQUIVO: `docs/01_PRODUTO_ESCOPO.md`

# 01 — Documento de Produto e Escopo (PRD)

## 1. Visão

Construir uma aplicação Python de investigação quantitativa de eleições brasileiras que permita acompanhar o caminho da evidência da visão nacional até o registro operacional de cada seção, abrangendo 2012, 2014, 2016, 2018, 2020, 2022, 2024 e 2026. O projeto é **descritivo, comparativo e investigativo**, sem conclusões pré-fixadas.

### Perguntas que a aplicação deve responder

1. Qual foi a abstenção de determinada seção, zona, município, UF ou eleição? Qual o denominador e a fonte exata?
2. Como essa abstenção mudou entre eleições, respeitando alterações no cadastro, locais e seções?
3. Quais locais concentraram votação computada após o horário regulamentar — **somente nos anos com logs compatíveis**?
4. A atividade tardia ocorreu em todas as seções de um local, sugerindo filas ou questões estruturais, ou em uma seção isolada?
5. Qual a proporção de eventos associados a habilitação biométrica, manual/alternativa, sem cadastro e indeterminada, por ano e por seção?
6. Como comparar manualmente os registros operacionais com comparecimento, BU e totalização sem confundir suas unidades?
7. Qual o número de votos, válidos, brancos, nulos e votos por candidato/partido **apenas** para presidente, governador, senador e prefeito?
8. Quais mudanças de turno, regras de disputa, vagas ao Senado, limites geográficos e indisponibilidade de fontes comprometem a comparação?
9. Quais achados possuem evidência suficientemente robusta para revisão humana e quais são apenas problemas de qualidade dos dados?
10. O resultado de qualquer gráfico pode ser reproduzido com um comando, a URL do TSE, o arquivo e sua impressão digital?

## 2. Usuários e perfis

- **Pesquisador:** filtros profundos, SQL de consulta, método exposto e intervalos de confiança.
- **Analista de dados:** cobertura, ingestões, catálogos, versão de parser, inspeção de erros e exportações.
- **Público/leitor:** métricas simples, linguagem acessível, comparações e alertas não conclusivos.
- **Administrador local:** definir localização do storage, limites de disco, jobs, republicação de snapshots.

A execução inicial é **local, single-user**, em Windows/Linux, sem autenticação obrigatória em `localhost`. Uma futura publicação em servidor exigirá autenticação administrativa, limitação de acesso e controles de privacidade apropriados.

## 3. Requisitos funcionais

IDs `RF-*` devem constar dos testes e relatórios de entrega.

### 3.1 Fontes e descoberta
- **RF-001** Inventariar catálogos oficiais TSE via CKAN (`package_search`, `package_show`) por ano, cargo indiretamente por recurso, nome e tipo.
- **RF-002** Registrar ID real de dataset, recurso, URL descoberta, formato, tamanho, data de alteração, extração e licença quando informada.
- **RF-003** Descarregar apenas recursos necessários, preservando raw byte a byte e hash SHA-256.
- **RF-004** Permitir download seletivo por ano/turno/UF e retomada segura; validar HTTP Range e ZIP64 antes de leituras parciais.
- **RF-005** Preservar versões de arquivos quando o TSE substituir conteúdo mantendo o mesmo nome.
- **RF-006** Usar estados `DISCOVERED`, `QUEUED`, `DOWNLOADING`, `VERIFIED`, `PARSED`, `VALIDATED`, `QUARANTINED`, `FAILED`, `UNAVAILABLE`.
- **RF-007** Registrar indisponibilidade de fonte de maneira explícita, com data, justificativa e possível próxima revisão.

### 3.2 Modelo eleitoral e apuração
- **RF-010** Importar apenas os cargos PRESIDENTE, GOVERNADOR, SENADOR e PREFEITO para o fato de votos por candidato.
- **RF-011** Normalizar código de cargo exclusivamente após validação do layout do ano; não adivinhar códigos só pelo número.
- **RF-012** Suportar eleições gerais e municipais e atribuir cargo elegível a cada pleito.
- **RF-013** Não gerar segundo turno para senador; gerar segundo turno apenas se existir na respectiva disputa regional.
- **RF-014** Armazenar candidatos com id eleitoral **por eleição**, partido/coligação, situação e votos; separar contabilização original e reprocessamento judicial posterior quando aplicável.
- **RF-015** Distinguir comparecimento por eleitor/seção de quantidade de seleções/votos por cargo. Eleitor do Senado em pleito de duas vagas tem até dois votos para a disputa; **não** comparar soma de votos nominais do Senado ao comparecimento como se cada eleitor tivesse apenas um voto.
- **RF-016** Exibir comparecimento, abstenção, aptos, seções agregadas, transferências temporárias e justificativas conforme a definição e a disponibilidade da fonte.
- **RF-017** Preservar os valores por candidato, brancos/nulos e outras classes do layout, incluindo categorias cuja contabilização dependa da situação da candidatura.
- **RF-018** Separar coluna `scope_status` por cobertura (`COMPLETE`, `PARTIAL`, `MISSING`, `NOT_APPLICABLE`, `PROVISIONAL`, `SUPERSEDED`).

### 3.3 Geografia e história
- **RF-020** Navegação BR > UF > Município > Zona > Local > Seção com retorno a qualquer nível.
- **RF-021** Representar zona e seção como identificadores que precisam do município, pleito e turno para identificar a unidade operacional.
- **RF-022** Não supor permanência de número ou endereço de seção entre eleições; construir correspondências documentadas de baixa/média/alta confiança.
- **RF-023** Preservar `ZZ`/exterior como domínio próprio, quando disponível, sem atribuir automaticamente a uma UF comum.
- **RF-024** Tratar DF, territórios especiais, locais sem coordenadas, urnas de contingência e seções agregadas sem exclusão silenciosa.
- **RF-025** Agregar por escola/local apenas se código de local validado no pleito; correspondência por nome e endereço é aproximação.

### 3.4 Logs operacionais
- **RF-030** Usar parsers por versão, tipo e ano; ler `logd.dat` em contêineres publicados, sem pressupor formato universal.
- **RF-031** Extrair sequência cronológica de eventos com id do arquivo e posição de linha, tipo de evento e timestamp com proveniência.
- **RF-032** Diferenciar hora de abertura, início da votação, computação do voto, fim da votação, emissão BU, envio, recebimento e totalização.
- **RF-033** Exibir horário local original e referência temporal padronizada, anotando versão de `tzdata`, regra histórica de votação e problemas do relógio.
- **RF-034** Identificar urnas substituídas e múltiplos arquivos por seção; reconstruir linha do tempo sem duplicar votos.
- **RF-035** Habilitação: biométrica comprovada, alternativa/manual confirmada, indício de ausência de cadastro, não classificável, conflitante.
- **RF-036** Não afirmar assinatura física do mesário a partir de evento de intervenção digital; somente fonte inequívoca autoriza essa contagem.
- **RF-037** Exibir filtros antes/depois de 17h somente quando `limite_legal_em_instante` estiver corretamente resolvido para a eleição, UF e localidade.
- **RF-038** Trabalhar independentemente quando logs não existirem (comparativo de apuração e abstenção continua utilizável).

### 3.5 Análises e relatórios
- **RF-040** Calcular taxas ponderadas (por totais) e mostrar média simples de seções separadamente e claramente rotulada.
- **RF-041** Comparar seção com pares do mesmo local e município via leave-one-out, observando tamanho de amostra.
- **RF-042** Oferecer estatísticas descritivas, funil de controle e modelos de excesso de dispersão; manter limiares versionados e configuráveis.
- **RF-043** Tratar correção para comparações múltiplas e cobertura de logs ao construir rankings nacionais.
- **RF-044** Separar `ALERTA DE QUALIDADE` de `ACHADO ESTATÍSTICO` e `CASO EM REVISÃO`; nenhum é prova de ilícito.
- **RF-045** Emitir relatório com denominadores, comparador, método, versão, cobertura, ressalvas e fontes.
- **RF-046** Exportar CSV, JSON, Parquet e um relatório HTML/Markdown; PDF opcional em etapa futura.
- **RF-047** Exibir valores pequenos e intervalos de incerteza; taxa extrema com n=3 não recebe prioridade automática.
- **RF-048** Permitir comparar cargos apenas quanto à **distribuição dos votos de cada cargo**, não transferir eventos temporais individuais a um candidato.
- **RF-049** Salvar investigação como configuração reproduzível (JSON/YAML + versão de snapshot), não como julgamento.

### 3.6 Operação
- **RF-050** CLI, API local e UI capazes de operar com dados de um único município, UF ou Brasil.
- **RF-051** Manifesto de execução e comandos de reprodução por relatório.
- **RF-052** Telemetria local de duração, bytes, falhas, itens descobertos/baixados/validados, sem enviar dados privados.
- **RF-053** Download interrompido continua após reinício, sem marcar parcial como completo.
- **RF-054** UI sempre distingue `sem dados` de `zero`, `não comparável`, `provisório` e `não se aplica`.

## 4. Requisitos não funcionais

- **RNF-01 Auditabilidade:** qualquer número remonta a versão de arquivo oficial, hash e regra de transformação.
- **RNF-02 Reprodutibilidade:** código, dependências e dados congelados produzem resultados equivalentes.
- **RNF-03 Local-first:** não exigir API comercial, cloud ou banco remoto.
- **RNF-04 Escalabilidade:** particionamento por pleito/turno/UF; evitar carregar todos os eventos em RAM.
- **RNF-05 Segurança:** não executar conteúdo de arquivos baixados; proteção contra ZIP bombs/path traversal; conexões HTTPS.
- **RNF-06 Privacidade:** remover/mascarar eventuais dados identificáveis dos logs antes da persistência analítica e jamais correlacionar voto a identidade.
- **RNF-07 Neutralidade:** explicar diferenças de cobertura, hipóteses alternativas e contexto operacional em cada alerta.
- **RNF-08 Acessibilidade:** interface em pt-BR, tabelas navegáveis e gráficos com alternativas tabulares.
- **RNF-09 Performance:** metas definidas por benchmark e hardware real, com degradação graciosa sob pouca RAM.
- **RNF-10 Extensibilidade:** novo pleito requer catálogo + mapeamentos + parser testado, não refatoração de toda aplicação.

## 5. Excluído do escopo

- Deputados federais, estaduais, distritais; vereadores; suplentes e vices como resultados independentes.
- Inferência de escolha individual, associação voto/hora/pessoa, vigilância individual de mesários/eleitores.
- Reconhecimento facial, cruzamento com bases pessoais ou identificação de eleitores.
- Declaração automática de fraude, causalidade de alterações nos votos ou autoria de irregularidade.
- Captura por tela de portal em substituição à API sem uma justificativa técnica documentada.
- Scraping indiscriminado de documentos privados, cadastros eleitorais pessoais ou dados não publicados.
- Predição de resultado futuro a partir de anomalias sem pesquisa metodológica separada.

## 6. Casos de uso prioritários

- **UC-01:** selecionar 2022/t1/MA/Açailândia, listar zonas, escolas e seções, comparar taxas com MA e Brasil.
- **UC-02:** selecionar eleições 2014–2026 para cargo presidente e visualizar porcentagens por candidato/UF, com status de apuração.
- **UC-03:** selecionar um local de votação em 2026/t1 e comparar horários das seções da escola com logs válidos, cobertura e relógio.
- **UC-04:** visualizar 2018/t1/SENADOR, contemplando duas vagas e denominadores corretos.
- **UC-05:** abrir 2016/t2 de município sem segundo turno e receber `NOT_APPLICABLE` sem criar linhas zeradas.
- **UC-06:** abrir seção sem log e ver resultados, abstenção e mensagem 'Sem dados operacionais publicados/validados'.
- **UC-07:** exportar um achado contendo raw hashes, algoritmo e contra-hipóteses.
- **UC-08:** detectar substituição de urna e conciliar vários fragmentos do log.
- **UC-09:** reprocessar um recurso corrigido pelo TSE sem perder o snapshot anterior.
- **UC-10:** comparar 2012–2024 para prefeito por município, sinalizando fusões e modificações de seções.

## 7. Conceitos de tela

Resumo Brasil; Explorar geografia; Candidatos/cargos; Abstenção; Histórico de pleitos; Horários; Habilitação; Análises combinadas; Casos de revisão; Qualidade/Cobertura; Fontes/Proveniência; Administração de coleta. Detalhamento em `08_API_E_PAINEL.md`.

## 8. Ética de apresentação

Nunca rotular uma seção ou escola como 'fraudulenta'. Texto padrão: **'A diferença indicada é estatística e pode refletir composição do eleitorado, infraestrutura, filas, erro de registro ou cobertura incompleta. Requer verificação independente.'** Dados operacionais não substituem procedimento de auditoria oficial nem demonstram, isoladamente, ilícito.


---

# ARQUIVO: `docs/02_FONTES_OFICIAIS_E_COBERTURA.md`

# 02 — Inventário de fontes oficiais, disponibilidade e estratégia de aquisição

**Corte de verificação: 2026-10-12.** Os endereços abaixo são páginas de **catálogo**, não promessas de que todos os arquivos de todo ano já foram descarregados, inspecionados ou possuem layouts equivalentes. O pipeline deve descobrir os recursos atuais na API e guardar seus identificadores.

## 1. Autoridade dos dados

Hierarquia de fontes:
1. TSE — arquivos originais publicados (CSV/TXT/ZIP/BU/log/RDV), seus hashes, especificações e metadados do catálogo.
2. TSE — materiais técnicos e resoluções de cada ano, inclusive fusos, horários e procedimentos.
3. TSE — relatórios e agregados oficiais para conferência.
4. TRE/atos locais publicados, caso necessários para excepcionalidades e horários.
5. Repositórios de terceiros como **referência técnica**, jamais autoridade final sobre resultados.
6. Dados simulados apenas para testes, com sinalização ostensiva.

Não misturar arquivos de diferentes `extraction_as_of` no mesmo relatório sem registrar a diferença. Dados de resultado podem sofrer retificações; preservar versões e selecionar explicitamente um snapshot.

## 2. Conjuntos oficiais confirmados em páginas do TSE

| Código | Família | Anos/publicações confirmadas nesta pesquisa | Conteúdo/uso | Estado |
|---|---|---|---|---|
| F01 | Resultados por seção / detalhe de apuração | 2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026 | Aptos, comparecimento, abstenção e votos por seção conforme leiaute | Páginas de resultados verificadas nos oito pleitos; layouts por conferir |
| F02 | Votação por seção | 2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026 | Candidatos e quantidades por cargo/seção | Páginas verificadas; conteúdo por conferir |
| F03 | Boletim de Urna publicado | 2012, 2016, 2026; demais via CKAN | Reconciliação independente de agregados | Páginas verificadas |
| F04 | Arquivos transmitidos para totalização, incluindo logs | 2022, 2024, 2026 | Arquivos compactados por UF/turno contendo tipos publicados para cada ano | Páginas verificadas |
| F05 | Comparecimento e Abstenção | 2012 e 2022, 2024; outras a inventariar | Dados oficiais complementares à apuração | Páginas verificadas |
| F06 | Eleitorado / locais de votação / seções agregadas | 2022 e 2024; outras a inventariar | Mapeamento geográfico, locais e histórico | Páginas verificadas |
| F07 | Candidatos | 2026; outras a inventariar | Candidatos, números, legendas, chapas e situações | Página verificada |
| F08 | Correspondências esperadas/efetivadas | 2012, 2016, 2026; outras a inventariar | Reconciliação operacional quando semântica conhecida | Páginas verificadas |
| F09 | Documentação técnica de urna | 2022 | Formatos BU/RDV/assinaturas/logs e scripts oficiais | Página verificada |
| F10 | Calendário e regras de votação | 2026 | Datas/turnos, horário de votação, regras de procedimento | Página verificada |

**Não afirmar** que F04 existe publicamente com logs cronológicos equivalentes em 2012/2014/2016/2018/2020. A ausência no inventário inicial não prova inexistência absoluta: tratar como `NOT_DISCOVERED`, depois `UNAVAILABLE` somente após procedimento de pesquisa documentado.

### URLs oficiais verificadas

- TSE catálogo: https://dadosabertos.tse.jus.br/
- 2012 resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2012
- 2014 resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2014
- 2016 resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2016
- 2018 resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2018
- 2020 resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2020
- 2012 boletins: https://dadosabertos.tse.jus.br/dataset/resultados-2012-boletim-de-urna
- 2016 boletins: https://dadosabertos.tse.jus.br/dataset/resultados-2016-boletim-de-urna
- 2022 resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2022
- 2024 resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2024
- 2022 arquivos: https://dadosabertos.tse.jus.br/dataset/resultados-2022-arquivos-transmitidos-para-totalizacao
- 2022 comparecimento: https://dadosabertos.tse.jus.br/dataset/comparecimento-e-abstencao-2022
- 2022 eleitorado: https://dadosabertos.tse.jus.br/dataset/eleitorado-2022
- 2024 arquivos: https://dadosabertos.tse.jus.br/dataset/resultados-2024-arquivos-transmitidos-para-totalizacao
- 2024 eleitorado: https://dadosabertos.tse.jus.br/dataset/eleitorado-2024
- 2026 resultados: https://dadosabertos.tse.jus.br/dataset/resultados-2026
- 2026 boletins: https://dadosabertos.tse.jus.br/dataset/resultados-2026-boletim-de-urna
- 2026 arquivos: https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao
- 2026 candidatos: https://dadosabertos.tse.jus.br/dataset/candidatos-2026
- Documentação técnica da urna 2022: https://www.tse.jus.br/eleicoes/eleicoes-2022/documentacao-tecnica-do-software-da-urna-eletronica
- Calendário e 2026: https://www.tse.jus.br/eleicoes/cde-2026
- Resolução TSE 23.751/2026: https://www.tse.jus.br/legislacao/compilada/res/2026/resolucao-no-23-751-de-26-de-fevereiro-de-2026

**Nota editorial:** links de páginas do catálogo podem redirecionar ou ser reestruturados; a descoberta definitiva deve partir do inventário CKAN. Não fabricar URLs para anos adicionais por interpolação.

## 3. Cobertura por tipo de análise — princípio de projeto

| Análise | 2012 | 2014 | 2016 | 2018 | 2020 | 2022 | 2024 | 2026 |
|---|---|---|---|---|---|---|---|---|
| Resultado de cargos elegíveis por seção | Inventariar e importar | Inventariar e importar | Inventariar e importar | Inventariar e importar | Inventariar e importar | Inventariar e importar | Inventariar e importar | Inventariar e importar 1T; 2T futuro |
| Abstenção por seção | Verificar no layout | Verificar | Verificar | Verificar | Verificar | Verificar | Verificar | Verificar |
| Nome/código de local | Verificar | Verificar | Verificar | Verificar | Verificar | Verificar | Verificar | Verificar |
| Logs com voto por horário | **Não confirmado** | **Não confirmado** | **Não confirmado** | **Não confirmado** | **Não confirmado** | Arquivos de log publicados | Arquivos de log publicados | Arquivos de log publicados 1T |
| Eventos de biometria/alternativa | **Não confirmado** | **Não confirmado** | **Não confirmado** | **Não confirmado** | **Não confirmado** | Investigar semântica | Investigar semântica | Investigar semântica |
| BU publicado em texto/CSV | Catálogo verificado | Inventariar | Catálogo verificado | Inventariar | Inventariar | Inventariar | Inventariar | Catálogo verificado |

Esta tabela descreve a **estratégia de implantação**, não resultado de auditoria de cada arquivo. Nos relatórios finais deve existir `coverage_report` calculado, com contagem de arquivos, seções e eventos efetivamente processados.

## 4. Descoberta oficial via API CKAN

Endpoints base:

- `GET https://dadosabertos.tse.jus.br/api/3/action/package_search?q=...&rows=...&start=...`
- `GET https://dadosabertos.tse.jus.br/api/3/action/package_show?id=<dataset_slug_or_id>`
- `GET https://dadosabertos.tse.jus.br/api/3/action/resource_show?id=<resource_id>` quando habilitado.

Processo determinístico:
1. Fazer `package_search` por padrões `resultados-YYYY`, `boletim`, `comparecimento`, `eleitorado`, `candidatos`.
2. Paginar até `count`, sem supor que uma busca por ano só devolve aquele pleito.
3. Classificar o título do recurso por família **apenas como pré-triagem**, nunca como certeza sobre formato interno.
4. Persistir IDs CKAN, nome, descrição, formato, URL, tamanho se disponível, licenciamento, `metadata_modified` e data da captura.
5. Baixar apenas amostra ou cabeçalho para perfil de esquema; registrar encoding, delimitador, colunas, arquivos dentro de ZIP.
6. Validar `NR_TURNO`, `ANO_ELEICAO`, UFs, cargos e layout observados dentro dos arquivos.
7. Marcar `SUPPORTED`/`UNSUPPORTED`/`PARTIAL` por ano/turno/família e criar um ticket de parser se necessário.
8. Realizar coleta total somente quando esquema e escopo estiverem documentados.

O script `scripts/inventariar_ckan.py` deste pacote executa a descoberta, com exportação de JSON. É propositalmente conservador: não dispara downloads grandes.

## 5. Famílias de dados e finalidade

### 5.1 `detalhe_votacao_secao` / apuração por seção

Campos exemplificados no projeto de referência para **um layout de 2026** (verificar na amostra real): `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_CARGO`, `QT_APTOS`, `QT_COMPARECIMENTO`, `QT_ABSTENCOES`, `NR_LOCAL_VOTACAO`, `NM_LOCAL_VOTACAO`.

Transformação: `(election_id, turno, uf, município, zona, seção)` → fato de comparecimento, **uma vez por unidade**, sem somar novamente linhas repetidas de outros cargos. O recorte principal de cargo é validado por dicionário de época.

### 5.2 Votação por seção

Importar somente registros dos quatro cargos. Para votos por candidato, incluir identificador do candidato no pleito, número, legenda e estado da contabilização. **Não presumir que o código de cargo `1` corresponde a presidente em todos os anos sem checagem**. Mapear brancos/nulos conforme layout efetivo.

### 5.3 BU eletrônico / textual

Usar para reconciliação de somas por seção e cargo, e guardar referência ao conteúdo assinado/hash publicado. BU não informa quem votou em quem nem permite associar horário a uma escolha. Implementar parser binário apenas usando especificação oficial e testes; CSV e TXT devem ter caminhos separados.

### 5.4 Logs de urna

O TSE publica conjuntos 2022 (`.bu`, `.imgbu`, `.logjez`, `.rdv`, `.vscmr`), 2024 (`bu`, `imgbu`, `log`, `rdv`, `vota`) e 2026 (`bu`, `log`, `rdv`, `vota`) segundo as descrições de cada página. **A enumeração varia** — detectar os membros reais do ZIP e extensão/MIME por conteúdo. O dataset 2026 indica inclusão somente de arquivos na situação **'Totalizado'**; isto exige comparação com universo de seções esperado para não enviesar cobertura.

No repositório de referência foram observados contêineres `.logjez` com 7z para 2022 e `-log.jez` com ZIP para 2026, ambos com `logd.dat`; são **hipóteses de formato testáveis**, não garantia de todas as UFs/turnos. Ver `05_LOGS_HORARIOS_BIOMETRIA.md`.

### 5.5 Eleitorado / locais

`Eleitorado por local de votação`, `Perfil do eleitorado por seção`, `Seções agregadas` e informações complementares existem em determinados anos. Usar para localizar as escolas, validar o universo de seções e explicar diferenças cadastrais. Contagens do eleitorado publicadas antes da eleição podem não ser equivalentes aos aptos finais de uma seção.

### 5.6 Comparecimento / abstenção

Pode servir como segunda conferência, mas **validar o grão**: há bases com níveis distintos de agregação e até desagregações demográficas. Nunca somar cortes de perfil ao total se representam a mesma população.

### 5.7 Candidatos e situação

Aplicar recorte de cargo antes de gerar tabelas de fatos. O cadastro de candidatos pode registrar modificações, substituições e resultados judicializados. Guardar instantâneo e classe original; não sobrescrever versões.

### 5.8 Correspondências / logs de preparação / metadados

Fontes opcionais para consistência, detecção de arquivo ausente, correspondência de urna e preparação. **Logs do GEDAÍ (preparação da urna) não equivalem a logs de votação no dia do pleito.** Não usar como se fossem.

## 6. Catálogo de disponibilidade (`dataset_coverage`)

Para cada combinação `(ano, turno, UF, família, versão recurso)`:

- status de descoberta/publicação e status de processamento separados;
- número de recursos encontrados, arquivos esperados e observados, total de linhas, seções cobertas;
- total de aptos e comparecimento nos dois universos, se conciliáveis;
- codificação, delimitador, assinatura do esquema, versão do parser;
- `raw_sha256`, `source_updated_at`, `retrieved_at`, `processed_at`;
- campos disponíveis, campos ausentes, proporção não classificável;
- validade do período, motivo de exceções, número de erros e dados descartados;
- `coverage_ratio_sections`, `coverage_ratio_attendance`, `coverage_ratio_events` somente quando denominadores são justificáveis.

### Invariantes de cobertura

- Recurso CKAN anunciado mas link falhando: `DISCOVERED` + download `FAILED`, não `MISSING` na origem.
- Ano que ainda não ocorreu: `NOT_APPLICABLE`/`FUTURE`, não `ERROR`.
- 2026/t2 em 12/10/2026: `FUTURE`, sem gerar dados falsos.
- Município sem segundo turno: `NOT_APPLICABLE`, ainda que exista pacote genérico de 2º turno para a UF.
- Sem log validado: nulos em indicadores temporais e biométricos; o denominador da amostra temporal é zero e **não** o total nacional de eleitores.

## 7. Download resiliente e segurança de fonte

- Fazer `HEAD` ou pequena requisição `GET` com `Range` para detectar `Accept-Ranges`, `Content-Range`, ETag, `Content-Length` e resposta 206.
- **Não** interpretar `Accept-Ranges` anunciado como suporte garantido: validar `206` e conteúdo devolvido.
- Implementar retomada por blocos com metadata `If-Range` (quando há ETag/Last-Modified confiáveis). Se fonte mudou, invalidar parciais.
- ZIP64: diretório central e campos de 64 bits; confirmar offsets/compressão; se não houver leitura seletiva segura, baixar arquivo inteiro.
- Nunca decomprimir sem limites de tamanho/membros/razão de expansão; zip-slip e symlinks devem ser bloqueados.
- Taxa de conexões configurável (padrão conservador 2–4, limite configurado); retry com backoff exponencial/jitter e códigos transitórios; respeitar servidor público.
- Download em `.part` e promoção atômica para arquivo final somente após verificação.
- Guardar o ZIP/TXT original ou referência imutável; não confiar em URL como identificador de conteúdo.
- SHA-256 local demonstra integridade do arquivo baixado/snapshot; **não prova assinatura/autenticidade eleitoral** por si só. Comparar a hashes/assinaturas oficiais apenas conforme especificação.

## 8. Datas e fusos

- 2026: primeiro turno ocorreu em **04/10/2026**; segundo turno quando aplicável está previsto para **25/10/2026**. Regra oficial 2026: 08:00–17:00 horário de Brasília no país, ressalvadas disposições específicas.
- **Não** retroprojetar regras de 2026 a 2012–2020. Horários, fusos locais e eventuais horários de verão devem ser interpretados por ano, localidade e legislação histórica.
- O ano 2020 teve calendário eleitoral excepcional; não assumir datas usuais de outubro. Datas vêm de `pleitos.yaml` validado.

## 9. Fluxo de atualização de fonte

Ingestão inicial → validação → snapshot publicado. Toda atualização posterior cria novo snapshot, executa diff por `(pleito/turno/UF/família)` e guarda relatório: campos adicionados/removidos, seções que mudaram, totais anteriores/novos, motivação/retificação, status de consistência e data.

## 10. Licenciamento

Alguns conjuntos exibem **Creative Commons Atribuição**, outros podem exibir `Nenhuma Licença Fornecida` na página do portal. Não presumir licença única para tudo: capturar licenciamento recurso a recurso. O código do repositório `ralbuque/esteleicao` não mostrou licença explícita na raiz verificada; usar seus conceitos, não copiar trechos extensos de implementação sem autorização/licença apropriada.


---

# ARQUIVO: `docs/03_ARQUITETURA_TECNICA.md`

# 03 — Arquitetura técnica, módulos e fluxo operacional

## 1. Estratégia arquitetural

A arquitetura deve ser **modular, reprocessável, local-first, independente de serviços pagos, orientada a dados versionados**. Preferir *modular monolith*: um repositório Python com fronteiras claras, CLI própria, API REST interna e aplicação Streamlit. Microsserviços, filas distribuídas, Kubernetes e Spark não são necessários na primeira versão; seriam complexidade sem benefício proporcional.

### Esquema lógico

```text
TSE CKAN  ────────────────────────────────────────────────┐
TSE CSV/TXT/ZIP/BU/LOG/RDV ──────────────────────────────┤
Metadados/atos de eleição ───────────────────────────────┘
                 │ (descoberta, seleção, inventário)
                 ▼
         [RESOURCE REGISTRY / CATALOG]
                 │
                 ▼
 [DOWNLOADER] → raw imutável + sha256 + download receipt
                 │
                 ▼
         [PROFILERS] (arquivo/layout/encoding)
                 │
       ┌─────────┼──────────────┬──────────────┐
       ▼         ▼              ▼              ▼
   [CSV]       [BU]          [LOGS]          [LOCAIS]
       │         │              │              │
       └─────────┴──────────────┴──────────────┘
                 ▼
         [NORMALIZERS / QUALITY GATES]
                 ▼
        SILVER PARQUET PARTICIONADO
                 ▼
         [RECONCILIATION ENGINE]
                 ▼
          GOLD DUCKDB + VIEWS
                 │
         ┌───────┼────────────┐
         ▼       ▼            ▼
     [Metrics] [Cases]   [Coverage + Audit]
         └───────┼────────────┘
                 ▼
          [FastAPI LOCAL]
                 ▼
   [STREAMLIT UI / EXPORT / REPORTS]
```

**Regra:** nenhuma camada altera o raw. A camada derivada sempre aponta para `raw_asset_id` e versão do processo.

## 2. Stack escolhida

| Componente | Escolha | Motivação |
|---|---|---|
| Linguagem | Python 3.12+ estável | Leitores, tooling e excelente ecossistema |
| HTTP | `httpx` ou `requests` + `tenacity` | Retry, streaming e timeouts |
| Manipulação colunar | `polars` + `pyarrow` | Memória e performance em CSV grandes |
| Banco analítico | `duckdb` | SQL local, parquet pushdown |
| Arquivos | Parquet particionado por ano/turno/UF/família | Compressão, predicate pushdown |
| API | FastAPI + Pydantic v2 | Validação de filtros e contratos |
| UI | Streamlit + Plotly | Desenvolvimento local e inspeção interativa |
| Configuração | YAML + `pydantic-settings` | Pleitos, fontes, portas, memória, thresholds |
| CLI | Typer + Rich | `catalog`, `ingest`, `validate`, `report` |
| Logs comprimidos | `zipfile`, `py7zr`, utilitários separados | Variantes observadas |
| Validação | Pandera / validação SQL + testes customizados | Checagens de esquema e invariantes |
| Testes | Pytest, Hypothesis, snapshots sintéticos | Dados adversariais e testes por contrato |
| Qualidade | Ruff, mypy, pre-commit | Governança de código |
| Empacotamento | `pyproject.toml` + lock (`uv` ou Poetry) | Reprodutibilidade |
| Deploy futuro | Docker/serviço Windows opcional | Não bloquear instalação local |

Deve haver uma política de upgrades e versões fixadas; não codificar bibliotecas só pelo nome sem documentar versão. Parâmetros de compressão/concorrência precisam ser configuráveis.

## 3. Organização recomendada do repositório implementado

```text
src/auditabr/
  __init__.py
  cli.py                    # Typer
  config.py                 # settings + validação de pleitos
  domains/
    elections.py            # eleição/turno/cargo/vagas/UF
    geography.py            # identificação seção e correspondência histórica
    provenance.py           # ids, sha256, lineage
    coverage.py             # categorias de disponibilidade
    audit_cases.py          # workflow de casos sem conclusões automáticas
  catalog/
    ckan_client.py          # busca paginada, package_show, resource_show
    discover.py             # normalização metadados
    registry.py             # banco de recursos
    schema_profiler.py      # valida charset/delimitador/colunas
  acquisition/
    downloader.py           # HTTP resumível e seguro
    partial_zip.py          # ZIP64 e leitura seletiva VALIDADA
    manifest.py             # arquivo, etag, hash, data
    quarantine.py           # integridade e corruptos
  parsers/
    base.py                 # ParserContract
    csv_tse.py              # TSE CSV/TXT, por layouts
    bu_text.py              # BU TXT/CSV
    bu_binary.py            # somente se validado por documentação
    logs_2022.py            # 7z/formatos observados
    logs_2024.py            # a testar com amostra
    logs_2026.py            # ZIP/formatos observados
    log_state_machine.py    # eventos e habilitação
    candidate.py            # cadastro restrito ao cargo
    geo_local.py            # local, agregação e revisão cadastral
  pipelines/
    bronze.py               # inventário raw
    silver.py               # contratos canônicos
    gold.py                 # marts por grão
    reconcile.py            # oficiais vs logs/BU
    snapshots.py            # idempotência e versionamento
  analytics/
    turnout.py              # comparecimento/abstenção
    offices.py              # votos e regras por cargo
    timings.py              # horários, fuso e relógio
    habilitation.py         # biometria/manual/unknown
    baselines.py            # comparadores históricos
    outliers.py             # estatística + FDR
    coverage_bias.py        # viés de seleção por fonte faltante
    cases.py                # achados, triagem
  storage/
    parquet_store.py
    duckdb_store.py
    schema_migrations.py
  api/
    app.py
    routes_catalog.py
    routes_elections.py
    routes_geography.py
    routes_metrics.py
    routes_audit.py
    routes_reports.py
    schemas.py
  ui/
    main.py
    pages/
      01_visao_geral.py
      02_geografia.py
      03_resultados_cargos.py
      04_abstencao.py
      05_horarios.py
      06_habilitacao.py
      07_historico.py
      08_cruzamentos.py
      09_casos.py
      10_fontes_qualidade.py
      11_metodologia.py
  reporting/
    renderer.py
    templates/
  utils/
    timezone.py
    io.py
    hashing.py
    ids.py
config/
  pleitos.yaml
  fontes.yaml
  office_codes_by_layout.yaml   # descobrir via amostras; não inventar mapeamento
  event_taxonomy.yaml
  time_rules.yaml
  thresholds.yaml
  local_settings.example.yaml
storage/
  raw/              # imutável, fora do Git
  bronze/           # inventário + headers
  silver/           # parquets normalizados
  gold/             # DuckDB e agregados
  reports/          # relatórios imutáveis
  cache/            # descartável
  quarantine/       # erros e evidências
  manifests/        # versões, hashes, data lineage
  fixtures/         # material sintético de teste
migrations/
tests/
  unit/
  integration/
  contract/
  property/
  regression/
  fixtures/
docs/
pyproject.toml
uv.lock
README.md
LICENSE                 # licença PRÓPRIA a escolher
```

## 4. Fluxo de execução

### 4.1 Fase catálogo (`discover`)
Entrada: anos/categorias. Saída: manifesto de datasets e recursos, **nenhum ZIP gigante** baixado. Resolve recursos pelos IDs CKAN, classifica metadados, anota `proposed_family` e salva snapshot de catálogo.

### 4.2 Fase profiling (`profile`)
Amostra pequenos intervalos de recursos; identifica CSV com `;`, charset `latin-1` ou `utf-8`, colunas; para ZIP lista entradas **sem descompactar integralmente**. Confirma `supported_parser_version` por recurso, e permite bloqueio humano em arquivos inesperados.

### 4.3 Fase aquisição (`fetch`)
Seleciona recursos aprovados, estima espaço em disco, controla concorrência e restaura downloads interrompidos. Captura resposta HTTP (ETag, Last-Modified, size) e hash final. Transferência seletiva de ZIP só quando semântica `Range` + offsets for verificada; se falhar, download completo. As partes e índice não substituem arquivo original se integridade global for requerida.

### 4.4 Fase bronze (`inspect`)
Leitura mínima de metadados; hash, arquivos internos, cabeçalho, status de assinatura se houver verificador implementado, data de publicação, esquema detectado, recursos duplicados e versões antigas. Arquivos corrompidos → quarentena.

### 4.5 Fase silver (`parse`)
Parsers produzem tabelas canônicas, com linhas inválidas em armazenamento de exceções (não descartar silenciosamente). Cada parser expõe `parser_id`, `source_compatibility`, `recognized`, `unrecognized`, `event_taxonomy_version` e `parse_warnings`.

### 4.6 Fase gold (`materialize`)
Gera dimensões, fatos sem duplicidade, agregados e índices. SQL incremental por partições. Correções de código criam nova `transformation_run` e invalidam somente seus descendentes, não o raw.

### 4.7 Validação (`validate`)
Executa invariantes, checagem de cobertura, joins, reconciliação com BU, duplicatas, relógio e relatórios de QA. Dados inválidos não vão para `published_snapshot`.

### 4.8 Publicação (`publish`)
Gera snapshot atômico, com hash do catálogo, versões dos parsers e relatório. A UI lê **somente snapshot publicado**. Permitir consultar versões anteriores.

## 5. IDs, hash e idempotência

- `election_id`: chave estável `BR-{ANO}-{TIPO}`.
- `contest_id`: eleição + turno + cargo + distrito da disputa (presidência BR; governador/senador UF; prefeito município).
- `section_instance_id`: pleito + turno + UF/ZZ + código de município + zona + seção + eventual qualificador de agregação. São unidades **por turno**, não um ID histórico permanente.
- `source_asset_id`: hash SHA-256 do conteúdo ou UUID referenciando hash; registrar diferenças de conteúdo/URL.
- `pipeline_run_id`: UUID ou hash de manifest de entrada + versionamento da transformação, data, parâmetros.
- `snapshot_id`: versão publicada e imutável.
- `event_id`: seção + hash raw + posição (line/byte) + parser; não numerar apenas por hora, pois eventos podem ocorrer no mesmo segundo.

Invariantes: mesmos arquivos + parâmetros + versão de parser produzem linhas e hashes semânticos equivalentes; reexecutar não insere duplicatas. Se o mesmo recurso do TSE tiver conteúdo atualizado, cria-se nova versão de asset e comparação de diferenças.

## 6. Orquestração local

Não iniciar com Celery/Redis. Usar executor de jobs local, com `jobs` no DuckDB ou um pequeno SQLite operacional (se concorrência de gravação exigir). Processar uma UF/turno por job; limitar memória e IO. Work queue na camada de CLI e painel pode mostrar progresso de arquivos, mas tarefas de longa execução devem rodar **na aplicação local** — não em serviço oculto do assistente conversacional.

Estados: `PENDING -> FETCHING -> FETCHED -> PARSING -> PARSED -> VALIDATING -> READY -> PUBLISHED`, com transições alternativas `FAILED`, `QUARANTINED`, `RETRYABLE`, `CANCELLED`. Um job falho não invalida o restante do país; qualidade se mantém por partição.

## 7. Interfaces dos parsers (contrato)

```python
from dataclasses import dataclass
from typing import Protocol, Iterator, BinaryIO

@dataclass(frozen=True)
class ParseContext:
    election_id: str
    round: int
    uf: str
    asset_id: str
    detected_schema_id: str
    parser_version: str

@dataclass(frozen=True)
class ParsedBatch:
    table_name: str
    rows: object                 # DataFrame/Arrow RecordBatch
    rejected_rows: object
    observations: dict

class Parser(Protocol):
    def probe(self, header: bytes, metadata: dict) -> float: ...
    def parse(self, stream: BinaryIO, context: ParseContext) -> Iterator[ParsedBatch]: ...
```

O parser de logs deve usar API própria para fluxo de eventos e não forçar o carregamento de todo log em RAM. O `probe` nunca decide ano/eleição apenas por extensão.

## 8. Estratégia de volume e hardware

Planejar instalação com SSD e armazenamento limitado. Não fixar estimativas nacionais de GB sem observar os tamanhos publicados no catálogo. Alguns ZIP estaduais podem ocupar vários GB; por isso é obrigatório:

- perfilar um estado menor antes;
- mostrar espaço livre, compressão estimada e custo por bloco;
- limitar downloads simultâneos e CPU;
- priorizar resultados/abstenção nacionais, depois logs por UF;
- permitir apagar cache sem apagar raw validado e relatórios;
- processar um arquivo grande em stream/batches, sem abrir tudo com pandas;
- colunarizar eventos e histogramas por seção; manter os detalhes cronológicos como partição consultável por demanda.

Referência de performance: benchmark em 1 UF pequena e MA com tempos medidos para download, parse, joins e consultas. Metas realistas são estabelecidas **após** observar tamanho, rede e máquina, não inventadas.

## 9. Estratégia de deploy

1. **MVP local:** CLI + Streamlit/localhost em PC Windows/Linux.
2. **Modo compartilhado:** FastAPI com token para operações administrativas, Streamlit read-only e firewall.
3. **Produção pública opcional:** proxy HTTPS, CORS limitado, autenticação para exportações pesadas, rate limiting, proteção contra scans, observabilidade e backups; nunca publicar pastas raw contendo material não avaliado quanto à privacidade.

## 10. Modos de execução

- **`metadata-only`:** funciona apenas com o catálogo; não altera banco eleitoral.
- **`results-only`:** funciona sem logs; temporal e habilitação ficam indisponíveis.
- **`ops-only`:** pré-processa logs para um pleito/UF, mas marca cruzamento com resultados como pendente.
- **`reconciliation`:** utiliza ambas as fontes e confere equivalência.
- **`offline`:** permite repetir análises sem internet sobre snapshot fixado.
- **`demo`:** dados sintéticos claramente rotulados, não misturáveis com dados oficiais.

## 11. Tratamento de erros

Definir classes `CatalogError`, `SourceUnavailable`, `TransportError`, `IntegrityError`, `UnsupportedFormat`, `SchemaMismatch`, `ClockAnomaly`, `CoverageMismatch`, `DuplicateRecord`, `ConflictingElectionID`. Cada erro é localizado por `source_asset_id`, partição, parser e etapa. Log deve registrar causa, retry recomendado e se exige intervenção.

Não converter todo erro para `except Exception: pass` nem preencher NaN/zero para fazer painel funcionar. Qualquer intervenção automática deve registrar transformação reversível.


---

# ARQUIVO: `docs/04_MODELO_DE_DADOS.md`

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


---

# ARQUIVO: `docs/05_LOGS_HORARIOS_BIOMETRIA.md`

# 05 — Especificação crítica: logs de urna, horários, fuso e identificação

> Este documento possui **prioridade de segurança analítica**. Uma implementação que contar eventos sem validar o relógio, o dia, a sequência da habilitação, substituições e cobertura pode produzir resultados muito convincentes, mas errados.

## 1. Cinco horários que não são a mesma coisa

| Conceito | Definição | Fonte pretendida | Interpretação válida |
|---|---|---|---|
| `scheduled_cutoff` | Instante de encerramento do **período regular** de votação aplicável à localidade/ano | Regra TSE + ato local se necessário | Marco legal/operacional, não fechamento efetivo |
| `last_vote_computed` | Último evento confirmado de conclusão de voto da urna/seção | log operacional | Atividade efetiva; não inclui candidato escolhido |
| `actual_closure_event` | Evento inequívoco de encerramento da votação pela urna | log validado | Encerramento registrado, se disponível |
| `bu_generated_at` | Geração/fechamento do boletim de urna | BU/log | Procedimento posterior à votação; não é voto |
| `received_or_totalized_at` | Recepção/totalização pela infraestrutura da Justiça Eleitoral | sistemas de transmissão/totalização, quando disponíveis | **Não** é horário de voto nem prova de atividade em urna |

O gráfico principal deve chamar a série de **eventos de voto computado após o fim do horário regular**; jamais de 'votos após fechamento da urna' se o evento de fechamento real ainda não ocorreu. Voto validamente computado depois do horário de encerramento geral pode decorrer de eleitor em fila, contingência ou outra circunstância operacional legal.

Se o usuário solicitar 'após horário de fechamento' oferecer duas consultas diferentes: `after_scheduled_cutoff` e `after_actual_closure`. A segunda é uma **checagem de integridade de ordenação de log**, não indicador geral de votação tardia. Uma seção com eventos posteriores a `actual_closure_event` deve ser reavaliada para múltiplos dispositivos, timestamps corrompidos, eventos retrospectivos e interpretação de mensagens antes de ser sinalizada.

## 2. Evidência do projeto `esteleicao`

A referência observada usa `logd.dat` dentro de `-log.jez` em 2026 (ZIP) e `.logjez` em 2022 (7z), com linhas tabuladas de data-hora, nível, ID do equipamento, aplicação, mensagem, hash. Mensagens textuais observadas no código da referência:

```
O voto do eleitor foi computado
Aguardando digitação do título
Aguardando digitação do identificador do eleitor
Tipo de habilitação do eleitor [biométrica]
O eleitor não possui biometria
Ano de nascimento digitado é igual ao do cadastro
Solicitação de dado pessoal do eleitor para habilitação manual
```

A aplicação deve **testar correspondência exata ou regras versionadas** contra amostras oficiais para cada eleição antes de assumir os significados. Traduzir mensagens iguais como equivalentes em anos diferentes é perigoso.

> Atenção especial: a mensagem 'Ano de nascimento digitado é igual ao do cadastro' por si só **não comprova ausência de biometria cadastrada**; pode ser evidência de um procedimento biográfico, dependendo do estado do fluxo. O projeto de referência a usa sob condições heurísticas. Nesta especificação, a classe `SEM_CADASTRO_CONFIRMADO` requer evento inequívoco, enquanto sinais ambíguos pertencem a `INDICIO_SEM_CADASTRO` / `BIOGRAFICO_NAO_CONCLUSIVO` com confiança menor.

## 3. Protocolos de parsing

### 3.1 Identificação do contêiner

1. Determinar tipo de arquivo por *magic bytes* (`PK..` para ZIP, assinatura 7z, etc.), não apenas pela extensão.
2. Validar ZIP e limites de descompressão; bloquear paths relativos ascendentes, paths absolutos, symlinks e membros duplicados suspeitos.
3. Procurar `logd.dat` ou equivalentes **reconhecidos por versão**; se não houver, retornar `UNSUPPORTED_FORMAT`, preservando a entrada e listando membros detectados.
4. Identificar codificação pela documentação/layout e perfil do arquivo; preferir heurística não destrutiva e registrar exceções de caracteres.
5. Fazer parser de linha tolerante a campos extras, mas rigoroso com data/hora e tipagem. Linha rejeitada → `rejected_events` com índice e razão.
6. Não usar somente dia com mais eventos para escolher o dia oficial. O dia deve vir de `election_round.election_date` e a seção/UF conhecida. Seleções alternativas são **sinal de qualidade**, não fallback silencioso.
7. Identificar `GAP`/cabeçalho para validar seção, município e zona, conferindo com nomes do arquivo e cadastro oficial, sem confiar cegamente em um único local de identificação.

### 3.2 Fragmentação, substituições e duplicatas

Um local pode ter equipamento substituído, arquivos múltiplos ou arquivos reenviados. Construir `operational_log_group(section_instance_id, device_id_hash, round_id)` com intervalos e status de origem. Concatenar eventos por timestamp **e por sequência do log**, quando existir. Evitar duplicar eventos iguais retransmitidos e **não** deduplicar automaticamente dois votos registrados no mesmo segundo, pois podem ser pessoas diferentes (ou relógio com precisão baixa). Deduplicação só com identidade de arquivo/linha, chaves operacionais inequívocas e regras documentadas.

Analisar transições: `device A ended`, `device B started`, gap, sobreposição; se cronologia ou sequência forem ambíguas, marcar `MULTI_DEVICE_UNRESOLVED`.

### 3.3 Máquina de estados de habilitação

Classes de saída propostas:

```
BIO_CONFIRMED
ALT_MANUAL_CONFIRMED
NO_BIOMETRIC_ENROLLMENT_CONFIRMED
BIOGRAPHIC_ALTERNATIVE_CONFIRMED
HABILITATION_OTHER_CONFIRMED
HABILITATION_UNCLASSIFIED
HABILITATION_CONFLICT
```

Estados transitórios por dispositivo/seção:

- `IDLE` — urna aguardando próximo eleitor;
- `HABILITATION_STARTED` — iniciou tentativa de identificar eleitor (sem armazenar título);
- `BIO_ATTEMPTED` — evento explícito de tentativa;
- `BIO_ACCEPTED` — evento inequívoco de validação biométrica;
- `ALT_REQUESTED` — procedimento alternativo solicitado;
- `ALT_APPROVED` — liberado após etapas requeridas;
- `NO_ENROLLMENT` — informação explícita de não existência de biometria, com semântica validada;
- `READY_TO_VOTE` — habilitado;
- `VOTE_COMPUTED` — evento de conclusão do voto;
- `CANCELLED_OR_TIMEOUT` — ciclo abortado/expirado;
- `UNRESOLVED` — estados incompletos/conflitantes.

Regras:

1. Ao iniciar novo atendimento, abrir `session_seq` **local à seção/dispositivo**, sem identificador de pessoa.
2. Associar eventos de habilitação ao evento de conclusão **somente** se pertencerem ao mesmo ciclo e dispositivo, sem eventos contraditórios de reinício, cancelamento ou substituição.
3. `BIO_CONFIRMED` exige aceitação inequívoca; menção a biometria não basta.
4. `ALT_MANUAL_CONFIRMED` exige solicitação **e** confirmação de habilitação manual (ou sequência que tenha sido validada com especificação oficial); mera solicitação não prova conclusão.
5. `NO_BIOMETRIC_ENROLLMENT_CONFIRMED` exige evento explícito sem ambiguidade; se apenas ocorreu identificação biográfica, classificar como biográfico confirmado ou evidência fraca de cadastro, conforme a versão.
6. Em fluxo misto ou com mensagens incompletas: `UNCLASSIFIED`/`CONFLICT`. Não forçar classe para chegar artificialmente a 100%.
7. Guardar `reason_code`, `observed_message_ids`, versão taxonômica e confiabilidade.
8. Se a quantidade de ciclos com voto não conciliar, exibir diferenças sem inferir identidade/voto.

### 3.4 Classificação robusta de timestamp

Para cada evento:

```text
raw_timestamp_text
local_civil_datetime
zone_id / time_offset_as_observed
corrected_utc_datetime
corrected_brt_datetime
rule_version
clock_quality_class
clock_adjustment_provenance
raw_line_number
```

Não sobrescrever a hora original depois da correção. Separar `clock_offset_estimate` (anomalia do relógio da máquina) de `civil_timezone_offset` (fuso legal). Não misturar horário de emissão do BU (pode ter fuso/campo próprio) com horário dos logs sem validação.

## 4. Regra histórica de fuso e horário eleitoral

- Para o pleito de 2026, o TSE estabelece votação 8h–17h no horário de Brasília. Para 2022, o sistema de referência trabalha com a mesma política; confirmar com instrução oficial de 2022 e lista de exceções.
- Antes de 2022, a aplicação **não pode** assumir 17:00 de Brasília para todas as localidades. Obter regra e horário legal do ano (p.ex. local vs BRT) em `time_rules.yaml` com link da norma e status de verificação.
- Usar `zoneinfo` e IANA timezone por município quando disponível; UFs podem ter mais de um fuso. Tratar Fernando de Noronha, oeste do Amazonas, zonas fronteiriças e eventuais horários de verão históricos.
- Horário de referência para comparar eventos: `cutoff_instant_utc`, criado a partir da regra da localidade, não `datetime.replace(hour=17)` após normalização incorreta.
- Se mapa de fuso ou relógio não confiável, excluir a seção dos rankings de 'após horário regular', mas contar no resumo de cobertura como excluída.

### 4.1 Auditoria do relógio do equipamento

O relógio local pode estar adiantado/atrasado; a referência `esteleicao` reporta casos com curvas deslocadas. Um pipeline sério deve marcar:

- divergência entre hora de início de operações e janela prevista;
- saltos/retrocesso de timestamps na mesma sequência de arquivo;
- agrupamentos deslocados vs várias urnas do mesmo local;
- diferença sistemática de hora/offset em relação ao município;
- grande discrepância entre 'hora média' de seção e comparadores;
- inconsistência entre horário operacional e timestamp de BU **quando são comparáveis**.

Estimar `clock_quality=TRUSTED | SUSPECTED_OFFSET | CLOCK_JUMP | UNKNOWN`; **nunca corrigir silenciosamente** com a moda de horários de outros equipamentos. Estimativa de offset deve ser um campo separado com intervalo de incerteza e validação cruzada. Se houver correção, mostrar resultados **originais e corrigidos** e o impacto no número de eventos após 17h. Em rankings públicos, só `TRUSTED` ou correção validada.

## 5. Sequência de invariantes dos logs

- Um evento de voto computado **não pode ser automaticamente associado a cargo ou candidato**. É um evento de conclusão de um eleitor na urna, que pode ter votado em vários cargos.
- Contar somente eventos do dia e turno corretos, excluindo testes/carga e reinicializações administrativas.
- Número de eventos deve ser >= 0, nunca obter contagem negativa.
- Todo evento classificado tem `source_asset_id` e `raw_line_number` ou posição equivalente.
- `n_bio + n_alt_manual + n_no_enroll + n_biographic + n_other + n_unclassified + n_conflict = n_votos_classificaveis_ou_tentados` de acordo com o grão definido (um evento final por voto), sem eventos duplicados.
- `after_cutoff_events <= valid_timed_vote_events`.
- `last_vote >= first_vote` na cronologia **validada**; caso contrário erro/relógio.
- Se `n_events ≠ voters_present`, criar alerta de **consistência**, não de fraude.
- Se não houver evento de fechamento real, mostrar `Fechamento real: não identificado`, mesmo que haja último voto e geração de BU.
- Se um evento aparece depois de evento de fechamento real: controlar se foi em outro equipamento ou houve problema de hora e documentar a reconciliação.

## 6. Métricas operacionais derivadas

| Indicador | Descrição | Denominador | Observação |
|---|---|---|---|
| eventos `after_regular_cutoff` | voto computado após o horário regular da localidade | eventos com hora e relógio validado | Pode ser legal pela existência de fila |
| fração tardia | `after_regular_cutoff / valid_timed_vote_events` | idem | Mostrar numerador e n sempre |
| último evento de voto | `MAX(timestamp)` | — | Não é fechamento formal |
| fechamento efetivo | último evento **inequívoco** de fim da votação | — | Pode não existir na versão do log |
| ociosidade antes do corte | maior hiato sem conclusão de voto, em janela configurável | intervalo de horas | Não prova ausência de eleitores/fluxo de autenticação |
| hora mediana | mediana de instantes computados | eventos validados | Comparar locais/histórico com controle de fuso |
| velocidade de conclusão | tempo entre votos consecutivos | instantes de voto | Intervalos curtos não comprovam irregularidade |
| habilitação biométrica | ciclos com evidência de sucesso biométrico | ciclos com classificação operacional | Não misturar com cadastro |
| habilitação manual confirmada | ciclos com aprovação inequívoca de alternativa/manual | ciclos classificáveis | Não confundir com assinatura física |
| indício de não cadastro | evidência sobre ausência de biometria no cadastro | ciclos pertinentes | Rotular 'indício' se não inequívoco |
| cobertura de classificação | ciclos classificados sem conflito / eventos computados | eventos computados | Não deve ser forçada a 100% |

**Mudança de denominador:** taxa de habilitação manual entre pessoas com biometria cadastrada requer evidência **individual agregada** de `elegível à biometria` por evento, sem identificação pessoal. Se não for possível reconstruir o subconjunto, a métrica deve ser `manual/eventos com habilitação classificada`, com rótulo diferente; **não** afirmar que representa 'manual dentre biometrizados cadastrados'.

## 7. 'Assinatura de mesário' — contrato de comunicação

A palavra 'assinatura' pode se referir a uma assinatura em caderno de votação, ato do mesário ou intervenção biométrica. **Não são intercambiáveis**. Só mostrar contagem de `ASSINATURA_FISICA_CONFIRMADA` caso exista fonte pública agregada e inequívoca, com definição de população e metodologia. Eventos `Solicitação de dado pessoal para habilitação manual` não comprovam assinatura física, sucesso ou autoria individual. A UI deve usar preferencialmente `habilitação alternativa/manual confirmada` e oferecer tooltip: 'Não indica assinatura física do caderno, nem identifica o mesário'.

## 8. Testes obrigatórios de logs

T01 evento de voto sem biometria anterior → `UNCLASSIFIED`, não manual. T02 aceitação biométrica inequívoca → `BIO_CONFIRMED`. T03 solicitação manual sem conclusão → não contar manual confirmado. T04 cancelamento antes de voto → zero computados. T05 mudança de equipamento e sequência correta → sem dupla contagem. T06 duas linhas de voto no mesmo segundo → preservar ambas se são eventos distintos. T07 log de treinamento anterior → excluir do dia oficial. T08 relógio saltando 90 min → bloqueio de taxa tardia. T09 UF com dois fusos → resolver por município. T10 eleição anterior à unificação → regra histórica própria. T11 sem eleição 2T em município → no events aplicáveis. T12 timestamp após fechamento formal → alerta de consistência, não conclusão automática. T13 rótulo 'sem cadastro' por frase biográfica ambígua → não classificar como confirmado. T14 hash raw presente, mas linha ilegível → rejeitada com razão. T15 ZIP malicioso → quarentena.

## 9. Proteção de dados e sigilo

Mesmo arquivo público pode conter texto com informações identificáveis ou sensíveis; o parser deve **permitir leitura operacional sem persistir identificadores pessoais desnecessários**. Armazenar `device_id_hash` se útil para distinguir equipamentos e `session_seq` local efêmero. Não persistir CPF, título, nome de eleitor, dado biométrico, nem logs brutos em servidor público. Não reconstruir sequência entre eleitor individual e escolha/candidato. Os dados raw podem ficar em diretório local restrito ao operador, sujeitos a política de retenção.

RDV é uma fonte de escrutínio e reconciliação do registro digital de votos, **não** uma chave para determinar pessoa/hora/candidato. Sem necessidade demonstrável, não decodificar/transformar RDV no MVP.

## 10. Grupos de evidência e casos de revisão

Para cada achado temporal registrar: `section_instance`, intervalo/cutoff, timezone/regra, `clock_quality`, n total válido, n tardio, comparadores mesma escola, eventos de abertura/encerramento, estado de substituição, compatibilidade log-oficial, proporção de eventos indeterminados, hash e limites. A triagem humana deve considerar fila, condições de acesso, contingência e relógio antes de qualquer interpretação.


---

# ARQUIVO: `docs/06_METODOLOGIA_ESTATISTICA.md`

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


---

# ARQUIVO: `docs/07_VALIDACAO_TESTES_SEGURANCA.md`

# 07 — Qualidade, testes, segurança, governança e reprodutibilidade

## 1. Filosofia de QA

Qualquer número exibido precisa responder: **de qual arquivo saiu, a que seção pertence, que parser o interpretou, quais filtros foram aplicados, quais dados faltaram e quais checagens passaram?**

Gate de publicação em camadas:
- **Q0:** origem identificada e arquivo íntegro.
- **Q1:** esquema e tipos aderentes.
- **Q2:** chaves e geografia válidas.
- **Q3:** reconciliação eleitoral dos fatos permitida, com ressalvas categorizadas.
- **Q4:** logs com relógio e interpretação consistentes.
- **Q5:** métricas/relatórios com filtros, cobertura e métodos transparentes.

Não bloquear a publicação do **resultado oficial de uma seção** por causa de ausência de log; publicar resultado e marcar módulo operacional como indisponível.

## 2. Testes de integridade de fonte

1. SHA-256 calculado após finalizar download é estável em repetição sem alteração de origem.
2. Arquivo parcial não recebe status `VERIFIED`.
3. Conteúdo alterado na mesma URL gera novo `source_asset_id` e diff.
4. HTTP Range 200 em vez de 206 provoca fallback correto.
5. Content-Range, ETag e Content-Length inconsistentes invalidam retomada.
6. ZIP64 com entradas e offsets grandes é processado sem estourar inteiros.
7. ZIP/7z corrompido é posto em quarentena e não gera saída completa.
8. ZIP bomb, path traversal, nomes duplicados inesperados e symlink são bloqueados.
9. CSV com `;`, CRLF, aspas e `latin-1` é lido sem truncamento silencioso.
10. Parser captura arquivo com layout alterado em vez de deslocar colunas.
11. URLs e recursos CKAN devem apontar a domínios esperados conforme política configurada.
12. Logs de acesso não armazenam tokens/secrets.

## 3. Contratos de domínio eleitoral

13. Só existem quatro cargos no fato candidato.
14. A seleção de municipal só permite prefeito; geral permite os três cargos elegíveis.
15. Sem senador no segundo turno; validação falha caso algoritmo tente inserir.
16. Senado 2014/2022 contém 1 vaga por UF; 2018/2026 contém 2 vagas.
17. `section_turnout` tem 1 registro por seção/snapshot, mesmo com várias disputas.
18. Somar candidaturas não multiplica aptos/comparecimento.
19. Seção com número igual, mas em outro município/pleito, não faz join indevido.
20. Município TSE e IBGE não são tratados como códigos intercambiáveis.
21. Exterior e DF são suportados sem imputação de UF convencional para `ZZ`.
22. Município sem segundo turno retorna `NOT_APPLICABLE`.
23. Resultado 2026 segundo turno em 2026-10-12 retorna `FUTURE`.
24. Dados com candidatos substituídos/retificados mantêm snapshot e versão.
25. Município com seção agregada não duplica comparecimento.

## 4. Reconciliação quantitativa

26. `aptos=presentes+ausentes` quando o layout oficial autoriza esse invariante; exceções são documentadas.
27. Taxa de abstenção de 80 ausentes/400 aptos = 20%; agregado 80/400+20/100 = 100/500=20%, não média de 20% e 20% por coincidência apenas.
28. Taxa agregada de seções de tamanhos diferentes difere de média simples quando apropriado; demonstrar no teste.
29. Todo campo de contagem é não negativo e inteiro.
30. Resumo por candidato/cargo concilia com total de classe de voto previsto no BU, quando compatível.
31. Um eleitor em disputa do Senado com 2 vagas pode gerar **duas escolhas**, sem duplicar comparecimento.
32. Nenhum algoritmo divide automaticamente votos do Senado de 2018/2026 por comparecimento e chama isso de 'percentual de eleitores que votou no candidato' sem definição e regra específica.
33. Taxas por seção e município não se alteram em `join` com candidato.
34. Retificação de fonte gera diff e não sobrescreve original.
35. Duas fontes que discordam geram `reconciliation_issue`, não escolha arbitrária da mais conveniente.
36. Discrepância entre log e comparecimento não vira categoria de fraude.
37. Cobertura de logs em 10% do Brasil não pode produzir gráfico intitulado 'Brasil inteiro'.
38. Dado inexistente não retorna 0.

## 5. Testes temporais

39. Com evento UTC e fuso local equivalente, classificação após cutoff é igual.
40. Evento exatamente no cutoff tem comportamento definido pelo operador estrito `>`.
41. 2012 não herda regra horária de 2026.
42. Município com fuso distinto da capital da UF é resolvido por regra própria.
43. Histórico de horário de verão é considerado conforme data e localidade.
44. Relógio 60 minutos adiantado produz `CLOCK_SUSPECT` antes de ranking temporal.
45. Último voto não é interpretado como evento formal de fechamento.
46. BU transmitido às 22h não gera voto após horário regular se log encerrou às 17h.
47. Eventos de testes pré-pleito são excluídos.
48. Voto em nova urna após substituição não é duplicado nem perdido.
49. Vários eventos no mesmo segundo podem ser contados se são eventos distintos.
50. Timestamp de uma seção com data errada gera quarentena temporal.

## 6. Testes de habilitação

51. Solicitação manual não é confirmação manual.
52. Evento biográfico não prova ausência de biometria cadastrada sem regra suportada.
53. Ciclo com evento cancelado não é voto computado.
54. Ciclo com falta de eventos vai para `UNCLASSIFIED`.
55. Classes confirmadas não excedem número de ciclos de voto validados.
56. Nenhum campo publicado revela identidade de eleitor ou mesário.
57. A legenda 'assinatura do mesário' não aparece para um contador de habilitação manual.
58. Entre dois turnos, regra de taxonomia diferente bloqueia série homogênea sem ressalva.
59. Nível de evidência e taxa de desconhecidos aparecem em tela e exportação.

## 7. Estatística e prevenção de conclusões falsas

60. Grupo com poucos comparadores não recebe score pseudo-estável.
61. Modelo que usa leave-one-out não inclui a própria seção no baseline.
62. Variância ajustada fica definida para proporções 0/1 sem dividir por zero.
63. Hipóteses em massa reportam número de testes e FDR se p-values válidos.
64. Rankings excluem ou sinalizam relógios problemáticos e fonte incompleta.
65. Nenhuma função retorna `fraud_probability`.
66. Ficha de caso traz causas alternativas predefinidas e qualidade documental.
67. Métrica de taxa mostra numerador e denominador.
68. Taxa nacional recalculada a partir de contagens, não média de estados.
69. Comparação histórica de seção com vínculo de baixa confiança é rotulada.
70. Falta de log não é interpretada como ausência de evento tardio ou manual.

## 8. Testes de produto e UX

71. Filtros Brasil/UF/município/zona/local/seção são dependentes e coerentes.
72. Mudança de pleito limpa/discrimina filtros incompatíveis.
73. Dados provisórios e futuros são rotulados adequadamente.
74. Exportação acompanha `snapshot_id`, filtros, versão estatística e fontes.
75. Cada gráfico possui modo tabular equivalente e descrição de método.
76. O modo `demo` nunca aparece como dado oficial.
77. URL pública de raw é excluída se contiver parâmetro privado; URLs oficiais normais são permitidas.
78. API recusa cargo fora dos quatro permitidos.
79. API pagina listas grandes e aplica limite de rows.
80. Reabrir relatório salvo fixa a mesma versão de dados, não atualiza silenciosamente.

## 9. Estratégia de teste em níveis

- **Unitário:** parsing por linha, funções de taxa, hora, chaves, estados de classe, matching histórico.
- **Contrato:** schemas reais em amostras pequenas do TSE de cada ano/turno/UF/sistema.
- **Integração:** CKAN mockado, download Range mockado, ZIP pequeno, pipeline e DDL reais.
- **Propriedade:** entradas aleatórias e limites (zero, negativo, duplicado, texto truncado, duas vagas) usando Hypothesis.
- **Regressão:** snapshots aprovados de resultados calculados com dados oficiais de amostra; hash semântico dos relatórios.
- **Cross-validation:** somas por candidatos e seções contra relatórios oficiais; múltiplos parsers quando possível.
- **Sistema:** executar em máquina de RAM restrita com dataset de tamanho realista, medindo peak RSS, bytes, velocidade e tempo de query.

## 10. Política de confidencialidade, retenção e LGPD

O projeto não cria cadastro de eleitores nem processa características individuais para análise. Pode haver campos pessoais em dados públicos; dados sensíveis ou identificáveis devem ser **minimizados**. Aplicar:

- diretórios raw locais com ACL e sem sincronização pública por padrão;
- UI exibe dados agregados de seção/cargo, nunca sequências ligadas a pessoa;
- perfis públicos têm read-only; administração de coleta não exposta;
- não coletar IPs/usuários sem necessidade, e se fizer, documentar retenção;
- mascarar possíveis CPF, título e nomes indevidos em erros/logs;
- relatório inclui proveniência sem anexar conteúdo bruto com dados pessoais;
- não publicar dados de alto risco de reidentificação em combinação de microeventos (evitar timeline granular por evento na UI pública sem revisão de privacidade);
- política de backup/expurgo documentada; raw pode ser retido para reprodutibilidade em storage controlado;
- não armazenar credenciais em YAML versionado.

## 11. Segurança e supply chain

- Dependências fixadas e com relatório de vulnerabilidades.
- Conexões HTTPS, DNS normal, timeout, retry limitado, proibir redirecionamento para hosts não autorizados em downloader.
- Não passar membros ZIP como paths sem sanitização.
- Limites para descompressão total, razão de compressão e número de entradas.
- SQL parametrizado, validação de filtros e paginação.
- Sem execução de scripts de origem TSE/GitHub durante ETL.
- Bibliografia e URL expostas de maneira segura; download de scripts de terceiros sujeito a revisão.
- Licença do projeto próprio definida; atribuição de fontes respeitada.

## 12. Manifesto de reprodução

Todo relatório contém, no mínimo:

```json
{
  "report_id": "example-only",
  "snapshot_id": "snapshot-2026-10-12-sample",
  "as_of": "2026-10-12",
  "parameters": {"year": 2026, "round": 1, "uf": "MA"},
  "source_assets": [{"ckan_resource_id": "<real-id>", "sha256": "<real-hash>"}],
  "parser_versions": {"logs_2026": "<semantic-version>"},
  "analysis_version": "<semantic-version>",
  "coverage": {"sections_expected": null, "sections_valid": null},
  "clock_policy": "<version>",
  "created_utc": "<ISO-8601>"
}
```

Este objeto é **exemplo de contrato**, não um relatório real. Cada campo `<real-...>` deve ser preenchido somente após processamento real.

## 13. Critérios de falha impeditiva

Publicação do snapshot deve falhar se houver: tabelas de votos contendo cargo excluído; colisão de chave seção/turno; ausência de hash em arquivo usado; ingestão duplicada com contagens somadas; regras de Senado/turno violadas; fonte alegada como oficial sem catalogação; classificação temporal em massa sem política de fuso; parser aceitando layout desconhecido sem alerta; divulgação de identidade individual; relatórios 'Brasil' sem cobertura explícita; valores inventados para 2026/t2 antes do evento.


---

# ARQUIVO: `docs/08_API_E_PAINEL.md`

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


---

# ARQUIVO: `docs/09_ROADMAP_CRITERIOS_DE_ACEITE.md`

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


---

# ARQUIVO: `docs/10_REFERENCIA_ESTELEICAO.md`

# 10 — Auditoria de referência: `ralbuque/esteleicao`

**Repositório observado:** https://github.com/ralbuque/esteleicao (branch principal, inspecionado em 12/10/2026). Esta documentação usa o projeto como **referência de ideias e arquitetura**. Não pressupõe reuso do código nem verificação independente de seus resultados numéricos. A listagem principal inspecionada não exibiu arquivo de licença explícito. Investigar licenciamento antes de reutilizar implementação protegida.

## 1. Inventário dos arquivos observados

| Arquivo original | Função informada/documentada | Uso planejado no AUDITA-BR | Revisão crítica |
|---|---|---|---|
| `README.md` | Orienta execução e critérios de anomalia de 2026 | Inspiração para UX/CLI e declaração de métricas | Enfoque em 3 sinais específico de 2026, não histórico |
| `CLAUDE.md` | Contexto, decisões e método do sistema de referência | Inspiração para manter decisões persistentes no repositório | Afirmações empíricas não são verificação independente |
| `baixar_dados.py` | Obtém detalhe da apuração por seção e Parquet | Pipeline de resultados com schema versionado | Generalizar oito anos e quatro cargos |
| `baixar_logs.py` | Coleta arquivos de logs por UF, ano/turno, processa por seção | Planejamento de coleta seletiva e local-first | Não hardcodar layout/URL nem depender de uma única taxonomia |
| `download_tse.py` | HTTP Range ZIP remoto, retomada, retries, fallback | Download robusto com manifesto/segurança | Validar ETag/Range/ZIP64 e respeito ao CDN |
| `logs_urna.py` | Parser `logd.dat`, eventos horários, classificações | Especificação de máquina de estados por versão | Reavaliar classe biográfica e inferências de habilitação |
| `analise.py` | Z simples, binomial, ajustado, dispersão robusta, horários, comparações | Baselines e modelos transparentes | Validar pressupostos, FDR, missingness, impacto de relógio |
| `painel.py` | Streamlit com filtros, horários, habilitação e cruzamentos | Inspiração UX: drill-down e gráficos | Separar qualidade, disponibilidade, análise e interpretação |
| `gerar_dados_teste.py` | Fixtures sintéticas com anomalias plantadas | Gerador de fixtures e controles negativos | Não treinar parâmetros só com anomalias 'fáceis' |
| `deploy/*` | Empacotamento e publicação Windows/Caddy | Possível modelo de deploy opcional | Não fazer publicação pública sem segurança/privacidade |
| `requirements.txt` | Dependências | Verificar compatibilidade antes de selecionar versões próprias | Priorizar lock e tipos |

## 2. Insumos e dados usados no projeto de referência

No `CLAUDE.md` foi documentado para 2026:

```
https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/detalhe_votacao_secao_2026.zip
```

O documento menciona CSV com `;`, `latin-1`, e colunas `NR_TURNO`, `SG_UF`, `CD_MUNICIPIO`, `NM_MUNICIPIO`, `NR_ZONA`, `NR_SECAO`, `CD_CARGO`, `QT_APTOS`, `QT_COMPARECIMENTO`, `QT_ABSTENCOES`, `NR_LOCAL_VOTACAO`, `NM_LOCAL_VOTACAO`. Essas são **referências de layout**, que devem ser comparadas com os arquivos realmente observados antes de serem elevadas a contrato oficial.

Para logs, foi observado padrão de CDN em 2026 com ZIP por UF/turno e itens que incluem BU, log e RDV. O repositório de referência mostra uma URL padronizada, mas o conjunto oficial de 2026 descreve arquivos `bu log rdv vota`, e o de 2022 outros sufixos. **Não fixar por interpolação o mesmo filename para todos os anos.** Descobrir via CKAN, guardar IDs e usar padrões de URL apenas como fallback auditado.

## 3. Algoritmos observados e tratamento recomendado

### 3.1 Recuperação seletiva dos logs dentro do ZIP

O repositório descreve leitura do diretório central ZIP e requisições HTTP Range para baixar somente as entradas desejadas, com conexões paralelas, novas tentativas e fallback completo. É ótima ideia para economizar disco e rede. Implementação nova deve usar biblioteca/rotina testada, validar Range, ZIP64, ETag, CRC/compressão e tratar integridade/segurança. Uma extração seletiva não verifica necessariamente a integridade global do arquivo principal; registrar que é `PARTIAL_FETCH`.

### 3.2 Identificação de votação concluída

Referência usa evento `O voto do eleitor foi computado`, filtrando app `VOTA` e dia do pleito. No AUDITA-BR, controlar `election_date` oficial, distinguir testes e tratar substituição de dispositivo. Não fazer inferência de candidato por instante.

### 3.3 Habilitação

A referência diferencia biométrica, sem cadastro e manual com padrões de mensagens. Nosso ganho metodológico é modelar estados de tentativa, sucesso, cancelamento e indeterminação. Em particular, `Ano de nascimento digitado é igual ao do cadastro` **não basta isoladamente** para concluir que não havia biometria cadastrada. Registrar o código/condição observada e o nível de confiança.

### 3.4 Ajuste de fuso

A referência harmoniza horário de urna com a abertura esperada e a moda do município. É uma heurística útil, mas pode corrigir indevidamente uma urna com relógio adiantado. Nossa abordagem preserva o horário bruto, separa fuso civil de erro de relógio e aplica correções somente com evidência controlada, deixando exclusões visíveis.

### 3.5 Desvios de abstenção

Referência calcula:

```
z_simples = (taxa - média) / dp
z_binomial = (ausentes - aptos * p) / sqrt(aptos * p * (1-p))
z_ajustado = (taxa - p) / sqrt(p * (1-p) / aptos + tau2)
```

A versão ajustada incorpora variabilidade entre seções e `p` de grupos leave-one-out. Muito melhor do que z bruto, mas exige validação estatística para inferências nacionais; `tau2` robusto heurístico não fornece automaticamente distribuição nula exata. O AUDITA-BR separa estatística descritiva, score de triagem, modelo probabilístico validado, controle de múltiplos testes e tamanho do efeito.

### 3.6 Alertas combinados

Referência prioriza abstenção baixa, votação tardia e liberação manual; usa thresholds de 15%/10 eventos e 30 minutos de contraste com outras seções da mesma escola. Usar esses valores como **exemplos de filtros ajustáveis e cenários de validação**, não como padrão científico ou legal. Nosso produto deve comparar **abstenção baixa ou alta**, avaliar qualidade antes de score e testar explicações alternativas.

### 3.7 Qualidade de relógio

O próprio documento de referência relata anomalias de relógio com votação deslocada, que alteraram a taxa de 'após 17h'. Isso motiva manter métricas original/corrigida e não tornar fuso inferido de dados tão confiável quanto horário oficialmente normalizado.

## 4. Limitações a superar

1. Foco original em 2026, enquanto o projeto novo tem oito pleitos e quatro cargos.
2. Ausência de matriz explícita de cobertura por ano/UF/tipo impede inferência sobre históricos completos.
3. Semântica da biometria entre versões necessita contrato e testes negativos.
4. Logs parciais ou somente arquivos totalizados podem enviesar ranking nacional.
5. BUs, comparecimento e escolha por cargo necessitam reconciliação independente; os votos em senador com duas vagas exigem regra específica.
6. Labels como 'sem digital' devem distinguir cadastro, leitura, fluxo biográfico e intervenção manual.
7. Regras históricas de horário devem ser documentadas por ano e localidade.
8. Dataset atualizado no portal precisa reprocessamento e versionamento de snapshot.
9. Falta de licença explícita no checkout não autoriza copiar integralmente código; manter implementação original.
10. Declarações numéricas do repositório são hipóteses para reprodução, **não números garantidos** no nosso relatório.

## 5. Fontes para revisão manual pelo desenvolvedor

- Repo: https://github.com/ralbuque/esteleicao
- README: https://github.com/ralbuque/esteleicao/blob/main/README.md
- CLAUDE: https://github.com/ralbuque/esteleicao/blob/main/CLAUDE.md
- Download: https://github.com/ralbuque/esteleicao/blob/main/download_tse.py
- Logs coletor: https://github.com/ralbuque/esteleicao/blob/main/baixar_logs.py
- Parser: https://github.com/ralbuque/esteleicao/blob/main/logs_urna.py
- Estatística: https://github.com/ralbuque/esteleicao/blob/main/analise.py
- Painel: https://github.com/ralbuque/esteleicao/blob/main/painel.py

### Instrução à IA desenvolvedora

Estude esses arquivos como referências públicas para entendimento do problema, **mas implemente por conta própria a solução com os contratos do pacote**, sem copiar trechos protegidos. Caso a licença seja verificada como permissiva e haja interesse em portar módulo, registre origem, licença, diferenças, testes e manutenção separadamente; nunca incorporar silenciosamente.


---

# ARQUIVO: `docs/11_GLOSSARIO_E_DECISOES.md`

# 11 — Glossário, decisões de arquitetura e questões a validar

## A. Glossário técnico

- **Pleito:** eleição de determinado ano/tipo.
- **Turno:** rodada de votação; não confundir com extração/publicação do arquivo.
- **Disputa (`contest`):** cargo + circunscrição + turno.
- **Circunscrição:** Brasil para presidente; UF/DF para governador/senador; município para prefeito.
- **Seção eleitoral:** unidade que registra comparecimento e votos; deve estar vinculada a turno e localidade.
- **Zona eleitoral:** organização territorial da Justiça Eleitoral; não necessariamente município único.
- **Local de votação:** escola/prédio ou local administrativo; código/nome podem mudar.
- **BU:** Boletim de Urna; totais de votos e dados da votação por urna/seção no contexto adequado.
- **RDV:** Registro Digital do Voto, não identidade do eleitor nem vínculo com tempo individual.
- **Log:** sequência de eventos dos aplicativos da urna.
- **Evento de voto computado:** registro operacional de conclusão da participação na urna, sem indicar escolha individual.
- **Aptos:** eleitores habilitados naquela unidade segundo referência operacional da eleição.
- **Abstenção:** faltas no pleito; calcular no grão compatível.
- **Biometria cadastrada:** existência de dados biométricos no cadastro; **não** igual a biometria usada com sucesso no dia.
- **Biometria confirmada:** sucesso de autenticação biométrica no evento.
- **Habilitação alternativa/manual:** outro procedimento de habilitação conforme versão do sistema; não equivale a assinatura física.
- **Hora regular de encerramento:** fim da janela ordinária de votação, que não necessariamente coincide com último eleitor nem com fechamento efetivo.
- **Fechamento efetivo:** evento operacional de encerramento formal, se provado.
- **Recepção/totalização:** fases posteriores que não indicam o momento em que o eleitor votou.
- **Clock skew:** desvio entre o relógio do equipamento e horário civil real.
- **Fuso:** offset geográfico/legal em um instante; distinto do erro de relógio.
- **Snapshot:** conjunto imutável de dados derivados com versão de fontes/transformações.
- **Coverage:** porcentagem de universo relevante que foi realmente observado/validado.
- **Missingness:** modo como as ausências de dados ocorrem e podem enviesar estimativas.
- **Leave-one-out:** comparação com pares excluindo a seção examinada.
- **FDR:** taxa esperada de falsas descobertas entre hipóteses declaradas significativas; exige p-values válidos.
- **MAD:** median absolute deviation, estimador robusto de dispersão.
- **Proveniência:** rastro do valor desde arquivo e linha até resultado transformado.

## B. Architecture Decision Records (ADRs)

### ADR-001 — Python + DuckDB + Parquet, não PostgreSQL como requisito inicial

**Decisão:** computação local colunar. **Razão:** escalabilidade em notebooks/desktop, consultas grandes por UF e independência de serviço. **Consequência:** organizar concorrência de escrita e snapshots, usar migrador e transação de publicação. PostgreSQL continua opcional em implantação multiusuário.

### ADR-002 — Monólito modular + FastAPI + Streamlit

**Decisão:** simplicidade operacional, fronteiras lógicas e API explicitamente separada do UI. **Consequência:** alguns endpoints podem ser adaptadores locais no MVP, mas os contratos devem existir e ser testados.

### ADR-003 — Bronze/Silver/Gold com raw imutável

**Decisão:** cada dado reprocessável e auditável. **Consequência:** custo maior de disco em troca de integridade. Permitir limpar cache, não raw sem política explícita.

### ADR-004 — Só quatro cargos como fato de voto

**Decisão:** Presidente, Governador, Senador, Prefeito. **Consequência:** importadores devem filtrar deputados/vereadores e não importar seus candidatos, embora arquivos globais possam aparecer em reconciliação de comparecimento. Senado considera quantidade de vagas por pleito.

### ADR-005 — Seção é temporal, não permanente

**Decisão:** `section_instance` por turno; vínculos históricos são relacionamentos de confiança variável. **Consequência:** comparativos históricos automatizados no nível de seção podem estar restritos; município e UF são bases mais confiáveis.

### ADR-006 — Falta de log não vira zero

**Decisão:** disponibilidade explícita. **Consequência:** histórico de resultados 2012–2026 pode estar completo em um painel enquanto histórico temporal só inclui 2022/2024/2026 ou subconjunto verificado.

### ADR-007 — Distinguir horário legal, operacional e transmissão

**Decisão:** campos e gráficos separados; sem inferir voto irregular por atraso. **Consequência:** UI mais complexa, mas mais fiel.

### ADR-008 — Classes conservadoras de biometria

**Decisão:** classificar como confirmado só com sequência inequívoca. **Consequência:** mais `UNKNOWN`, porém menor risco de interpretações falsas.

### ADR-009 — Qualidade antes da detecção de anomalias

**Decisão:** findings estatísticos dependem de gates, cobertura e relógio. **Consequência:** menos falsos positivos espúrios e mais trabalho em validação.

### ADR-010 — Reprodutibilidade dos resultados

**Decisão:** versionar fonte, parser, análise, parâmetros e relatório. **Consequência:** banco de manifests e histórico de snapshots obrigatório.

### ADR-011 — Código da referência não é dependência

**Decisão:** aproveitar ideias técnicas do `esteleicao` e implementar a própria solução, salvaguardando licenciamento e evolução. **Consequência:** código inicial mais trabalhoso, documentação e manutenção controladas.

### ADR-012 — Dados reais e sintéticos segregados

**Decisão:** `demo` sempre particionado e rotulado, sem agregação cruzada possível. **Consequência:** testes e tutoriais podem usar fixtures sem contaminar painéis reais.

## C. Questões que só inspeção de dados reais poderá resolver

1. Quais colunas e seus significados variam entre 2012–2026? Quais esquemas/charset realmente aparecem em cada arquivo?
2. Em quais pleitos existem logs cronológicos públicos suficientemente detalhados? Para quais UFs/turnos?
3. Qual o significado exato dos eventos biométricos e manuais em 2022, 2024 e 2026?
4. Qual evento marca **encerramento real** em cada versão, se existir? Qual o fuso do timestamp?
5. Como diferenciar log de uma urna substituída de duplicata de transmissão?
6. Quais arquivos publicados foram retificados, e com quais `source_updated_at`?
7. Há relatórios públicos de horário de transmissão/recepção por seção? Se sim, qual o grão e a cobertura?
8. Em 2012–2020, há metadados confiáveis de horário de encerramento no BU ou outras fontes? Se não, declarar lacuna.
9. Quais relações entre TSE local de votação e nome/endereço podem ser verificadas historicamente?
10. Existem fontes de assinatura física **agregadas e públicas**? Se não, excluir esse indicador.
11. Como se representam seções agregadas, voto em trânsito, locais extraordinários, exterior e justificativas em cada pleito?
12. Qual a versão de leiaute das fontes de candidatos, brancos/nulos e situações judiciais?
13. Como os resultados são versionados nas fontes 2026 até consolidação do pleito?
14. O TSE publica SHA-256/SHA-512, assinaturas ou hashes específicos por tipo/ano? Implementar verificadores somente após documentação.
15. Quais regras históricas de horário e horário de verão se aplicam às localidades anteriores a 2022?

Essas perguntas são requisitos de *spikes técnicos* que devem produzir relatórios de verificação, **não** impedimentos para construir resultados e abstenção.

## D. Padrão de incerteza para o produto

Toda métrica de difícil confirmação tem uma das categorias:

- `CONFIRMED_BY_OFFICIAL_SOURCE`
- `CONFIRMED_BY_REPRODUCIBLE_PARSER`
- `ESTIMATED_WITH_VALIDATION`
- `HEURISTIC_EXPLORATORY`
- `UNVERIFIED`
- `UNAVAILABLE`
- `NOT_APPLICABLE`

Essas etiquetas referem-se à **qualidade e à origem do dado**, não a confiança em acusações de fraude. `HEURISTIC_EXPLORATORY` nunca se transforma em valor confirmado pela simples repetição da análise.


---

# ARQUIVO: `INSTRUCOES_DE_ENVIO.md`

# Como enviar este projeto para uma IA programadora

## Rota recomendada (ferramenta com arquivos/projeto)

1. Anexe o arquivo ZIP `AUDITA_BR_PACOTE_ARQUITETURA_v1.zip` ou extraia a pasta do pacote em um repositório de trabalho.
2. Abra `PROMPT_MESTRE_CRIACAO.md`, copie todo o conteúdo e envie como primeira mensagem à ferramenta de desenvolvimento.
3. Instrua-a a ler e obedecer a todos os arquivos antes de implementar, **em especial** 02, 04, 05, 06, 07 e `db/schema.sql`.
4. Peça desenvolvimento **fase por fase**, começando pela Fase 0/1, com código real e testes.
5. Exija sempre que separe o que foi implementado/testado do que ainda depende de baixar arquivos oficiais do TSE.

## Rota alternativa (ferramenta aceita apenas texto)

Anexe/cole `DOCUMENTACAO_COMPLETA.md` se couber no limite de contexto, ou compartilhe `PROMPT_MESTRE_CRIACAO.md` primeiro e em seguida os documentos numerados como contexto. Em ferramenta com limite curto de contexto, solicite fasear a leitura; evite remover as regras de fuso, biometria, Senado e confiabilidade.

## O que conferir na primeira entrega

O desenvolvedor deve devolver uma estrutura de diretórios, contrato de eleicões/cargos, schema DuckDB executado, cliente CKAN real, testes automatizados com resultados e estado exato das fontes acessadas. O painel completo não deve ser a primeira entrega.

## Como usar o auxiliar incluído

```bash
python scripts/inventariar_ckan.py --year 2022 --out catalogo_2022.json
python scripts/inventariar_ckan.py --query 'resultados 2026' --out catalogo_resultados_2026.json
python -m unittest discover -s tests -p 'test_*.py' -v
```

Os comandos do inventário exigem acesso à internet no computador em que forem executados. O arquivo fornecido serve somente para **inventariar metadados**, não para fazer o download dos dados eleitorais nem implementar o sistema inteiro.

## Regras finais

- Compartilhar a arquitetura não equivale a autorização para copiar código de outro repositório sem licença verificada.
- Não divulgar dados oficiais como coletados antes de baixar e validar os arquivos.
- Não retirar ressalvas metodológicas para tornar indicadores 'mais fortes'.
- A especificação foi preparada no marco temporal de 12/10/2026; a IA deve verificar disponibilidade e regras no momento de codificar e registrar atualizações.


---

# ARQUIVO: `config/pleitos.yaml`

```yaml
# Escopo declarativo de eleições. A existência de um 2T não implica que todas as localidades o tenham.
# 2026/t2 ainda é evento futuro na data de referência desta documentação (2026-10-12).
as_of: '2026-10-12'
allowed_offices: [PRESIDENTE, GOVERNADOR, SENADOR, PREFEITO]
excluded_offices: [DEPUTADO_FEDERAL, DEPUTADO_ESTADUAL, DEPUTADO_DISTRITAL, VEREADOR]
municipal:
  2012: {offices: [PREFEITO], rounds_possible: [1, 2], phase: final, senate_seats: 0}
  2016: {offices: [PREFEITO], rounds_possible: [1, 2], phase: final, senate_seats: 0}
  2020: {offices: [PREFEITO], rounds_possible: [1, 2], phase: final, senate_seats: 0}
  2024: {offices: [PREFEITO], rounds_possible: [1, 2], phase: final, senate_seats: 0}
general:
  2014: {offices: [PRESIDENTE, GOVERNADOR, SENADOR], rounds_possible: [1, 2], senate_rounds: [1], phase: final, senate_seats: 1}
  2018: {offices: [PRESIDENTE, GOVERNADOR, SENADOR], rounds_possible: [1, 2], senate_rounds: [1], phase: final, senate_seats: 2}
  2022: {offices: [PRESIDENTE, GOVERNADOR, SENADOR], rounds_possible: [1, 2], senate_rounds: [1], phase: final, senate_seats: 1}
  2026: {offices: [PRESIDENTE, GOVERNADOR, SENADOR], rounds_possible: [1, 2], senate_rounds: [1], phase: first_round_available_second_future, senate_seats: 2}
# A data e regra de cada turno devem vir do cadastro validado; não gerar 2T automaticamente.
# Códigos CD_CARGO do TSE são mapeados por esquema/ano em arquivo próprio validado com dados amostrais.

```


---

# ARQUIVO: `config/fontes_seed.yaml`

```yaml
# Seeds de URLs CATALOGAIS VERIFICADAS; URLs de download efetivas devem ser descobertas pela API CKAN.
as_of: '2026-10-12'
ckan_api: https://dadosabertos.tse.jus.br/api/3/action
sources:
  - {family: result_section, year: 2012, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2012'}
  - {family: result_section, year: 2014, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2014'}
  - {family: result_section, year: 2016, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2016'}
  - {family: result_section, year: 2018, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2018'}
  - {family: result_section, year: 2020, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2020'}
  - {family: result_section, year: 2022, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2022'}
  - {family: result_section, year: 2024, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2024'}
  - {family: result_section, year: 2026, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2026'}
  - {family: bu, year: 2012, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2012-boletim-de-urna'}
  - {family: bu, year: 2016, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2016-boletim-de-urna'}
  - {family: bu, year: 2026, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2026-boletim-de-urna'}
  - {family: transmitted_archives, year: 2022, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2022-arquivos-transmitidos-para-totalizacao'}
  - {family: transmitted_archives, year: 2024, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2024-arquivos-transmitidos-para-totalizacao'}
  - {family: transmitted_archives, year: 2026, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao'}
  - {family: turnout, year: 2022, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/comparecimento-e-abstencao-2022'}
  - {family: electoral_roll, year: 2022, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/eleitorado-2022'}
  - {family: electoral_roll, year: 2024, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/eleitorado-2024'}
  - {family: candidates, year: 2026, status: catalog_page_verified, url: 'https://dadosabertos.tse.jus.br/dataset/candidatos-2026'}

```


---

# ARQUIVO: `db/schema.sql`

```sql
-- AUDITA-BR | DDL inicial canônico para DuckDB.
-- Versão de especificação 1.0.0 | Um migrador deve gerir versões de esquema.
-- DuckDB para consultas analíticas; parquet para fatos grandes de eventos.

CREATE TABLE IF NOT EXISTS schema_migration (
  version VARCHAR PRIMARY KEY, applied_at TIMESTAMP NOT NULL,
  migration_sha256 VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS election (
  election_id VARCHAR PRIMARY KEY,
  election_year INTEGER NOT NULL,
  election_kind VARCHAR NOT NULL,                -- GERAL | MUNICIPAL
  reference_as_of DATE NOT NULL,
  publication_status VARCHAR NOT NULL,
  created_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS election_round (
  round_id VARCHAR PRIMARY KEY,
  election_id VARCHAR NOT NULL,
  round_number INTEGER NOT NULL,
  election_date DATE,
  scheduled_open_brt TIMESTAMP,
  scheduled_cutoff_brt TIMESTAMP,
  timing_rule_id VARCHAR,
  publication_status VARCHAR NOT NULL,
  UNIQUE(election_id, round_number)
);
CREATE TABLE IF NOT EXISTS office (
  office_code VARCHAR PRIMARY KEY,               -- PRESIDENTE, GOVERNADOR, SENADOR, PREFEITO
  office_name VARCHAR NOT NULL,
  seat_count_rule VARCHAR,
  runoff_allowed BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS contest (
  contest_id VARCHAR PRIMARY KEY,
  round_id VARCHAR NOT NULL,
  office_code VARCHAR NOT NULL,
  district_scope VARCHAR NOT NULL,               -- BR, UF, MUNICIPIO
  district_code VARCHAR NOT NULL,
  senate_seats INTEGER,
  status VARCHAR NOT NULL,
  UNIQUE(round_id, office_code, district_scope, district_code)
);
CREATE TABLE IF NOT EXISTS locality (
  locality_id VARCHAR PRIMARY KEY,
  election_id VARCHAR NOT NULL,
  uf VARCHAR NOT NULL,
  tse_municipality_code VARCHAR,
  municipality_name VARCHAR,
  ibge_municipality_code VARCHAR,
  is_foreign BOOLEAN DEFAULT FALSE,
  code_map_status VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS polling_place (
  polling_place_id VARCHAR PRIMARY KEY,
  round_id VARCHAR NOT NULL,
  locality_id VARCHAR NOT NULL,
  electoral_zone VARCHAR NOT NULL,
  place_code VARCHAR,
  place_name VARCHAR,
  address_normalized VARCHAR,
  latitude DOUBLE,
  longitude DOUBLE,
  geocode_source VARCHAR,
  location_confidence DOUBLE,
  is_provisional BOOLEAN DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS section_instance (
  section_instance_id VARCHAR PRIMARY KEY,
  round_id VARCHAR NOT NULL,
  locality_id VARCHAR NOT NULL,
  uf VARCHAR NOT NULL,
  municipality_tse VARCHAR,
  electoral_zone VARCHAR NOT NULL,
  electoral_section VARCHAR NOT NULL,
  polling_place_id VARCHAR,
  section_aggregation_status VARCHAR,
  section_type VARCHAR,
  source_asset_id VARCHAR,
  UNIQUE(round_id, uf, municipality_tse, electoral_zone, electoral_section)
);
CREATE TABLE IF NOT EXISTS historical_section_link (
  link_id VARCHAR PRIMARY KEY,
  section_instance_a VARCHAR NOT NULL,
  section_instance_b VARCHAR NOT NULL,
  linkage_method VARCHAR NOT NULL,
  confidence VARCHAR NOT NULL,                  -- HIGH, MEDIUM, LOW
  evidence JSON,
  reviewed_by VARCHAR,
  reviewed_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS candidate (
  candidate_instance_id VARCHAR PRIMARY KEY,
  election_id VARCHAR NOT NULL,
  office_code VARCHAR NOT NULL,
  tse_candidate_code VARCHAR,
  ballot_number VARCHAR,
  ballot_name VARCHAR,
  full_name VARCHAR,
  party_acronym VARCHAR,
  ticket_id VARCHAR,
  original_status VARCHAR,
  status_snapshot_id VARCHAR,
  source_asset_id VARCHAR
);
CREATE TABLE IF NOT EXISTS source_dataset (
  source_dataset_id VARCHAR PRIMARY KEY,
  ckan_package_id VARCHAR,
  ckan_slug VARCHAR,
  title VARCHAR,
  source_page_url VARCHAR NOT NULL,
  license_label VARCHAR,
  source_updated_at TIMESTAMP,
  catalog_retrieved_at TIMESTAMP NOT NULL,
  metadata_json JSON
);
CREATE TABLE IF NOT EXISTS source_resource (
  source_resource_id VARCHAR PRIMARY KEY,
  source_dataset_id VARCHAR NOT NULL,
  ckan_resource_id VARCHAR,
  resource_url VARCHAR NOT NULL,
  resource_name VARCHAR,
  reported_format VARCHAR,
  observed_format VARCHAR,
  expected_size BIGINT,
  last_modified VARCHAR,
  etag VARCHAR,
  resource_metadata JSON
);
CREATE TABLE IF NOT EXISTS source_asset (
  source_asset_id VARCHAR PRIMARY KEY,
  source_resource_id VARCHAR NOT NULL,
  raw_sha256 VARCHAR NOT NULL,
  raw_size_bytes BIGINT NOT NULL,
  storage_uri VARCHAR NOT NULL,
  downloaded_at TIMESTAMP NOT NULL,
  source_http_metadata JSON,
  archive_members_manifest_uri VARCHAR,
  verification_status VARCHAR NOT NULL,
  retained BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE(source_resource_id, raw_sha256)
);
CREATE TABLE IF NOT EXISTS pipeline_run (
  pipeline_run_id VARCHAR PRIMARY KEY,
  run_type VARCHAR NOT NULL,
  code_commit VARCHAR,
  parser_version VARCHAR,
  taxonomy_version VARCHAR,
  config_sha256 VARCHAR,
  input_manifest_sha256 VARCHAR,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  status VARCHAR NOT NULL,
  warnings JSON
);
CREATE TABLE IF NOT EXISTS lineage (
  lineage_id VARCHAR PRIMARY KEY,
  pipeline_run_id VARCHAR NOT NULL,
  source_asset_id VARCHAR NOT NULL,
  derived_table VARCHAR NOT NULL,
  partition_uri VARCHAR,
  derived_sha256 VARCHAR,
  row_count BIGINT,
  rejected_count BIGINT
);
CREATE TABLE IF NOT EXISTS dataset_coverage (
  coverage_id VARCHAR PRIMARY KEY,
  round_id VARCHAR NOT NULL,
  uf VARCHAR NOT NULL,
  source_family VARCHAR NOT NULL,
  snapshot_id VARCHAR,
  discovery_status VARCHAR NOT NULL,
  processing_status VARCHAR NOT NULL,
  expected_sections BIGINT,
  parsed_sections BIGINT,
  eligible_voters_in_scope BIGINT,
  event_classified_count BIGINT,
  event_unknown_count BIGINT,
  completeness_ratio DOUBLE,
  limitations JSON,
  source_asset_ids JSON,
  updated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS section_turnout (
  section_instance_id VARCHAR NOT NULL,
  snapshot_id VARCHAR NOT NULL,
  voters_eligible BIGINT,
  voters_present BIGINT,
  voters_absent BIGINT,
  is_provisional BOOLEAN NOT NULL DEFAULT FALSE,
  source_asset_id VARCHAR NOT NULL,
  validation_status VARCHAR NOT NULL,
  PRIMARY KEY(section_instance_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS candidate_vote (
  section_instance_id VARCHAR NOT NULL,
  contest_id VARCHAR NOT NULL,
  candidate_instance_id VARCHAR NOT NULL,
  snapshot_id VARCHAR NOT NULL,
  vote_count BIGINT NOT NULL,
  vote_status VARCHAR NOT NULL,
  source_asset_id VARCHAR NOT NULL,
  PRIMARY KEY(section_instance_id, contest_id, candidate_instance_id, snapshot_id, vote_status)
);
CREATE TABLE IF NOT EXISTS contest_vote_summary (
  section_instance_id VARCHAR NOT NULL,
  contest_id VARCHAR NOT NULL,
  snapshot_id VARCHAR NOT NULL,
  vote_nominal_total BIGINT,
  vote_blank BIGINT,
  vote_null BIGINT,
  vote_other_count BIGINT,
  ballot_slots_per_voter INTEGER NOT NULL,
  reconciliation_status VARCHAR NOT NULL,
  source_asset_id VARCHAR NOT NULL,
  PRIMARY KEY(section_instance_id, contest_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS operational_log (
  operational_log_id VARCHAR PRIMARY KEY,
  section_instance_id VARCHAR,
  round_id VARCHAR NOT NULL,
  source_asset_id VARCHAR NOT NULL,
  source_member_name VARCHAR NOT NULL,
  parser_id VARCHAR NOT NULL,
  parser_version VARCHAR NOT NULL,
  raw_event_count BIGINT,
  classified_event_count BIGINT,
  invalid_event_count BIGINT,
  urn_device_count INTEGER,
  clock_confidence VARCHAR,
  parse_status VARCHAR NOT NULL,
  warnings JSON
);
-- Para eventos de alta cardinalidade, a tabela abaixo é a interface *lógica*.
-- Persistir fisicamente em Parquet particionado por ano/turno/UF/tipo quando volumoso.
CREATE TABLE IF NOT EXISTS operational_event_example_schema (
  event_id VARCHAR,
  operational_log_id VARCHAR,
  section_instance_id VARCHAR,
  device_id_hash VARCHAR,
  raw_line_number BIGINT,
  local_civil_ts TIMESTAMP,
  timezone_id VARCHAR,
  normalized_ts_utc TIMESTAMP,
  normalized_ts_brt TIMESTAMP,
  event_kind VARCHAR,
  event_subtype VARCHAR,
  parser_confidence VARCHAR,
  clock_quality VARCHAR,
  is_election_day BOOLEAN,
  linkage_group_id VARCHAR,
  source_asset_id VARCHAR
);
CREATE TABLE IF NOT EXISTS operational_section_metrics (
  section_instance_id VARCHAR NOT NULL,
  snapshot_id VARCHAR NOT NULL,
  event_votes_count BIGINT,
  earliest_vote_local TIMESTAMP,
  last_vote_local TIMESTAMP,
  nominal_end_local TIMESTAMP,
  closure_event_local TIMESTAMP,
  issued_bu_local TIMESTAMP,
  after_cutoff_events BIGINT,
  after_cutoff_share DOUBLE,
  biometric_confirmed BIGINT,
  manual_confirmed BIGINT,
  no_enrollment_evidence BIGINT,
  other_confirmed BIGINT,
  unknown_habilitation BIGINT,
  multi_device BOOLEAN,
  clock_confidence VARCHAR,
  event_match_status VARCHAR,
  classification_coverage DOUBLE,
  operational_log_ids JSON,
  PRIMARY KEY(section_instance_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS quality_issue (
  issue_id VARCHAR PRIMARY KEY,
  snapshot_id VARCHAR,
  source_asset_id VARCHAR,
  section_instance_id VARCHAR,
  issue_category VARCHAR NOT NULL,
  issue_code VARCHAR NOT NULL,
  severity VARCHAR NOT NULL,
  raw_value VARCHAR,
  expected_value VARCHAR,
  evidence JSON,
  resolution_status VARCHAR NOT NULL,
  created_at TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_run (
  analysis_run_id VARCHAR PRIMARY KEY,
  snapshot_id VARCHAR NOT NULL,
  analysis_code VARCHAR NOT NULL,
  analysis_version VARCHAR NOT NULL,
  filters JSON NOT NULL,
  baselines JSON,
  thresholds JSON,
  coverage_constraints JSON,
  multiple_testing_method VARCHAR,
  created_at TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_finding (
  finding_id VARCHAR PRIMARY KEY,
  analysis_run_id VARCHAR NOT NULL,
  section_instance_id VARCHAR,
  aggregation_scope VARCHAR,
  finding_type VARCHAR NOT NULL,
  evidence_strength VARCHAR NOT NULL,
  review_status VARCHAR NOT NULL,
  measured_value DOUBLE,
  expected_value DOUBLE,
  effect_size DOUBLE,
  p_value DOUBLE,
  adjusted_q_value DOUBLE,
  sample_size BIGINT,
  coverage_pct DOUBLE,
  alternative_explanations JSON,
  notes VARCHAR,
  source_asset_ids JSON,
  created_at TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS report_manifest (
  report_id VARCHAR PRIMARY KEY,
  snapshot_id VARCHAR NOT NULL,
  analysis_run_id VARCHAR,
  report_uri VARCHAR NOT NULL,
  report_sha256 VARCHAR NOT NULL,
  produced_at TIMESTAMP NOT NULL,
  source_asset_ids JSON,
  filters JSON NOT NULL,
  code_version VARCHAR,
  bibliography JSON
);
CREATE TABLE IF NOT EXISTS published_snapshot (
  snapshot_id VARCHAR PRIMARY KEY,
  published_at TIMESTAMP NOT NULL,
  as_of_date DATE NOT NULL,
  source_manifest_sha256 VARCHAR NOT NULL,
  transformation_version VARCHAR NOT NULL,
  quality_summary JSON,
  status VARCHAR NOT NULL
);

INSERT INTO office VALUES
  ('PRESIDENTE','Presidente da República','1',TRUE),
  ('GOVERNADOR','Governador de Estado/DF','1',TRUE),
  ('SENADOR','Senador','depends_on_year:1_or_2',FALSE),
  ('PREFEITO','Prefeito','1',TRUE)
ON CONFLICT DO NOTHING;

```


---

# ARQUIVO: `tests/cenarios_aceite.md`

# Cenários de aceite para o desenvolvedor (fixtures sintéticas, não dados TSE)

Todos os valores desta página são **exemplos inventados para testar o código**.

## 1. Não duplicar comparecimento por cargo

Seção X/t1/2022, aptos 400, presentes 300, ausentes 100; disputa presidente e governador com múltiplos candidatos.

**Esperado:** `section_turnout` 1 linha, aptos 400, presentes 300, ausentes 100; soma pós-join com candidato não pode virar 800 aptos ou 600 presentes. Taxa = 25%.

## 2. Média simples não é taxa agregada

Seção A 10 aptos, 5 ausentes; Seção B 100 aptos, 10 ausentes.

**Esperado:** média simples = (0,50+0,10)/2 = 30%; taxa agregada = 15/110 = 13,63636%. Ambas só aparecem com rótulos próprios.

## 3. Senado duas vagas

2018/t1 UF fictícia, 100 eleitores presentes, 2 vagas. Total de 150 votos nominais registrados para candidatos; comparecimento 100.

**Esperado:** nenhuma exceção `150 != 100` baseada nessa falsa equivalência. Não informar que '150 eleitores votaram'. Senado 2018 deve ter `senate_seats = 2`; 2022 = 1.

## 4. Turno inexistente

Município Y/2024 com 1º turno, sem 2º turno. **Esperado:** `/contests?office=PREFEITO&round=2&municipality=Y` retorna `NOT_APPLICABLE`, sem linhas fabricadas.

## 5. Fonte ausente não significa zero

Seção Z/2016 tem resultados mas não tem log disponível/validado. **Esperado:** abstenção calculada; `after_cutoff_events=null`, `manual_confirmed=null`, `operational_status=UNAVAILABLE`, sem sinalização temporal.

## 6. Voto exatamente no cutoff

TSE define horário regular até 17h; eventos 16:59:59, 17:00:00, 17:00:01; regra `>`.

**Esperado:** 1 evento após cutoff, 3 válidos, taxa 33,333%. Em regra diferente, registrar explicitamente.

## 7. Transmissão tardia não é voto tardio

Último voto 16:50, fechamento 17:01, BU gerado 17:05, recebido 20:13.

**Esperado:** zero eventos após cutoff; recepção exibida em campo independente.

## 8. Votação após 17h com fila

Eventos de voto computado às 17:13 e 17:29; sem outro contexto. **Esperado:** 2 eventos após cutoff, anotação 'pode ser compatível com fila; não comprova irregularidade', sem score de fraude.

## 9. Relógio adiantado

Equipamento apresenta abertura prevista às 8h, eventos sempre deslocados +60 minutos e referência independente de offset validado.

**Esperado:** `CLOCK_SUSPECT` se não validado; não integrar ranking principal de atividade tardia; opções de visões original/corrigida só quando correção suportada.

## 10. Biometria ambígua

Ciclo com apenas `Ano de nascimento digitado é igual ao do cadastro` e conclusão do voto.

**Esperado:** NUNCA `NO_BIOMETRIC_ENROLLMENT_CONFIRMED` sem outro evento ou documentação que torne a semântica inequívoca.

## 11. Pedido manual não prova execução

Ciclo: solicitação de habilitação manual, reinício, voto computado com classe indefinida.

**Esperado:** não contar 1 manual confirmado; devolver desconhecido/conflitante conforme taxonomia e `reason_code`.

## 12. Duas urnas na seção

Dispositivo A registra 120 eventos distintos, dispositivo B registra 90 eventos distintos após substituição. Um ZIP retransmitido copia todos 120 de A.

**Esperado:** 210 eventos únicos e reconciliação com comparecimento 210, se arquivos forem válidos; não 330.

## 13. Duas pessoas no mesmo segundo

Dois eventos diferentes com mesmo timestamp em arquivos válidos, identidades de linha diferentes. **Esperado:** não colapsar por segundo sem evidência de duplicação.

## 14. Histórico seção mudou

Seção 100 em município A em 2016 e seção 100 em município B em 2020, mesma UF.

**Esperado:** nenhuma associação automática. Códigos iguais não significam mesmas pessoas, escola ou local.

## 15. Apoio eleitoral não implica identidade

Seção registra 50 eventos depois das 17h e maioria dos votos totais para candidato K. **Esperado:** UI **não** afirma que os 50 eventos foram votos para K ou que foram produzidos por eleitor de grupo específico.

## 16. Dados provisórios

No corte de 12/10/2026, solicitar 2026/t2. **Esperado:** `FUTURE`, não '0 voto' nem total definitivo.

## 17. Fuso e regra por pleito

Dois locais em fusos diferentes com votações encerrando no mesmo instante oficial BRT. **Esperado:** comparação de instantes coerente e horas locais diferentes exibidas; 2012 usa regra do ano, não regra 2026.

## 18. Cobertura parcial

100 seções esperadas, somente 27 com logs validados; destas 4 têm eventos após o cutoff.

**Esperado:** informar '4 de 27 seções com logs válidos', cobertura 27/100; não '4% das seções do estado'.

## 19. Download interrompido

Servidor mudou ETag após baixar 3 de 5 blocos. **Esperado:** invalidar `.part` antes de retomar, nunca juntar blocos de versões distintas.

## 20. Fonte adulterada/corrompida

Arquivo recebido diverge de checksum oficial conhecido ou está truncado. **Esperado:** `QUARANTINED`, sem gerar fatos publicáveis.
