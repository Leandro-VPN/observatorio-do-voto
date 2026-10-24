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
