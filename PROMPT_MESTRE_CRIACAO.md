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
