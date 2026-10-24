# Execução local — 13/10/2026

O AUDITA-BR está implementado e executado localmente para **presidente e prefeito**, com carga inicial seletiva. A entrega não corresponde à carga nacional integral nem à conclusão de todas as extensões previstas no pacote original.

## Entrega disponível

- Painel Streamlit: http://127.0.0.1:8501 . API e contrato OpenAPI: http://127.0.0.1:8000/docs . Acesso restrito ao próprio computador.
- CLI de catálogo, download seletivo/integral, importação, ingestão, validação, consulta, relatório, comparação de versões, backup e inicialização.
- Dados separados por seção/turno e cargo/candidatura; taxas ponderadas, fontes e hashes; publicação atômica em snapshots DuckDB; derivados Parquet.
- Onze páginas, filtros geográficos, sinais exploratórios de abstenção, histórico territorial, inspeção de logs, investigações e exportação em cinco formatos.
- Prompt consolidado em `PROMPT_MESTRE_UNIFICADO.md`; guia operacional em `README.md`; pacote instalável em `dist/auditabr-0.1.0-py3-none-any.whl`.

## Cobertura observada

Snapshot de referência: **55b5134464c11f4c7f3de819**, publicado às 21:00:54 UTC de 13/10/2026. Os oito pleitos foram catalogados e tiveram dados reais processados.

- Catálogo: 104 registros de datasets nas consultas por ano e 5.097 registros de recursos. Descoberta não significa download.
- Presidente: Acre/2014, 2018 e 2022 nos dois turnos; Acre/2026 no primeiro turno; Maranhão/2022 nos dois turnos.
- Prefeito: Acre/2012 e 2020 nos turnos encontrados; Acre/2024 no primeiro turno; votos de prefeito de Acre/2016 no primeiro turno. Comparecimento de Acre/2016 foi bloqueado por inconsistência da fonte.
- Total publicado: **53.157 registros de seção/pleito/turno** e **297.724 linhas de votação por seção/candidatura/classe**. Essas contagens não representam seções físicas únicas ao longo dos anos, candidatos únicos ou votos totais.
- Acre/2016/T2 e Acre/2024/T2: nenhum registro ordinário nos arquivos adquiridos, marcado `NOT_APPLICABLE`. 2026/T2: `FUTURE`, sem ingestão.
- Logs: três seções do Acre, uma de 2022, uma de 2024 e uma de 2026. São amostras deliberadamente pequenas, sem representatividade estatística.

Os arquivos presidenciais BR foram preservados integralmente como fontes adquiridas; somente as UFs selecionadas foram materializadas nos fatos. Nos arquivos municipais, outros cargos presentes no raw foram filtrados antes da persistência analítica. Nenhum cargo excluído aparece nos fatos de votação do snapshot de referência.

## Verificações executadas

- **49 testes passaram**, incluindo os testes fornecidos no pacote, propriedades matemáticas, download/retomada, identidade HTTP, arquivos inseguros, publicação, idempotência, filtros, logs e as onze páginas via Streamlit AppTest.
- Ruff passou e mypy validou os 17 módulos sem erros. Há um aviso de depreciação do adaptador HTTP de testes da Starlette, sem falha de teste.
- Auditoria das dependências fixadas não encontrou vulnerabilidades conhecidas na consulta executada. Resultado em `storage/manifests/dependency-audit.json`.
- Integridade: **19 hashes verificados**, correspondentes ao banco e às 18 fontes referenciadas no snapshot. Todas as linhas publicadas de comparecimento satisfazem aptos = presentes + ausentes.
- Uma segunda implementação, usando o leitor CSV do Arrow, reproduziu as contagens de seções, aptos, presentes e ausentes de MA/2022 e AC/2024 em ambos os turnos. Evidência em `storage/manifests/independent-reconciliation.json`. O teste compara agregações da mesma extração, sem pressupor equivalência com versões posteriores do TSE.
- As três amostras de logs registraram 60, 62 e 69 eventos de conclusão, respectivamente; cada contagem coincide com o comparecimento da seção correspondente. Essa coincidência não valida relógio, taxonomia ou integralidade de toda a família de logs.
- API verificada por HTTP real; interface inspecionada no navegador, inclusive a mudança de presidente/2022 para prefeito/2024.
- Benchmark local, uma chamada com cache de sistema aquecido: agregado MA/2022 em aproximadamente 0,12 s; cálculo exploratório MA/2022 e retorno da primeira página em aproximadamente 0,36 s. Não é teste de carga nacional ou concorrência.

## Quarentena e limites relevantes

A fonte de comparecimento AC/2016 contém a seção município 01392, zona 0009, seção 0170 com **46 aptos, 0 presentes e 0 ausentes**. A partição foi recusada; não foi aplicado ajuste presumido. Os votos de prefeito desse ano permanecem consultáveis independentemente. Raw e motivo estão preservados, e a tentativa aparece em Fontes e qualidade.

As métricas de biometria, procedimento manual e votos após o limite continuam **nulas** nas amostras reais: taxonomia `UNVERIFIED` e relógio `UNKNOWN`. A implementação oferece leitura e testes conservadores, mas não se declara homologação oficial dos formatos ou das classificações.

Ainda não estão concluídos: carga nacional integral; metadados completos de partido/coligação/situação de candidaturas; correspondência TSE–IBGE e mapas com coordenadas validadas; ligações históricas documentais de seções; reconciliação automática de múltiplos dispositivos/fragmentos; validação de assinaturas e importação binária de BU/RDV; inferência estatística calibrada e FDR sobre dados reais. Campos sem fonte permanecem ausentes. O score atual é exploratório e não demonstra irregularidade.

O segundo prompt supostamente mais simples não foi encontrado como arquivo distinto: os prompts da raiz e de `AUDITA_BR` são idênticos por hash, e o ZIP repete o pacote. A consolidação usa esses materiais e a inspiração de operação/interface de https://github.com/ralbuque/esteleicao, sem incorporar código externo.

## Armazenamento e operação

Na medição após a carga: raw aproximadamente 7,16 GB; snapshots publicados e temporários históricos aproximadamente 3,78 GB; derivados Parquet aproximadamente 10,6 MB. O banco de referência tem aproximadamente 81,5 MB. Valores são bytes lógicos, não espaço físico alocado. Versões anteriores e originais foram preservados para reprodução.

Duas limpezas verificadas recuperaram aproximadamente **7,16 GB** de cópias temporárias redundantes (2,68 GB + 4,48 GB). O cache restante medido tinha cerca de 37 KB. Novas aquisições evitam manter uma segunda cópia após verificar o raw.

Não há coleta recorrente ou automação oculta. A expansão é explícita por `auditabr collect --year ANO --uf UF`, reaproveitando fontes existentes. `iniciar.ps1` inicia os serviços; `parar.ps1` encerra o serviço desta entrega em segundo plano. Consulte o README para backup e instalação reproduzível.

## Relatórios e evidências

Quatro relatórios foram gerados com snapshot fixado e hashes dos arquivos exportados:

- MA/2022/T1: `storage/reports/539f9d6bed7f4a3707b01ccb/`.
- MA/2022/T2: `storage/reports/47a2a5a8019a4213a62309e1/`.
- AC/2024/T1: `storage/reports/1c34aa1500534c2b402e4cec/`.
- AC/2024/T2: `storage/reports/15c6db0e20d16b1757f3487e/`, relatório de indisponibilidade/ausência de disputa no arquivo, sem resultados inventados.

Cada pasta contém CSV, JSON, Parquet, Markdown, HTML e manifesto. Contagens detalhadas, benchmark, fontes verificadas e observações de coleta estão em `storage/manifests/execution-evidence.json`. O histórico da carga está em `storage/bootstrap-focused.log`.
