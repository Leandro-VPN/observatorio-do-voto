# Execução regional — 14/10/2026

O AUDITA-BR 0.2.0 foi executado para presidente e prefeito nos 16 estados do Norte e Nordeste. O relatório anterior está preservado em RELATORIO_PILOTO_2026-10-13.md.

Painel: http://127.0.0.1:8501/ . API: http://127.0.0.1:8000/docs . Acesso somente local. iniciar.ps1 inicia ambos; parar.ps1 encerra o serviço desta entrega. Não há coleta recorrente.

## Cobertura

Norte: AC, AP, AM, PA, RO, RR, TO. Nordeste: AL, BA, CE, MA, PB, PE, PI, RN, SE.

Presidente: 2014, 2018, 2022 nos dois turnos e 2026 no primeiro. Prefeito: 2012, 2016, 2020, 2024, incluindo os segundos turnos encontrados nas fontes ordinárias. 2026/T2 permanece FUTURE até 25/10/2026.

Snapshot: **12668d1e1721dd5f0ac65c8b**, publicado em 14/10/2026 às 10:54:56 UTC. Contém **1.893.520 registros de seção/pleito/turno** e **11.233.771 registros de votação por seção/candidatura/classe**. Não são contagens de seções físicas únicas, candidatos únicos ou votos totais. Não há fatos de UFs/cargos externos ao escopo.

Foram concluídas 136 leituras de fonte, gerando 256 capturas compactas (16 UFs × 8 anos × 2 famílias). Não faltam partições de primeiro turno. A correspondência com as extrações adquiridas foi verificada; integralidade frente a um universo eleitoral externo não foi validada, condição explicitada na interface.

## API e aquisição compacta

A API CKAN localiza recursos, licenças e versões. Nenhum dos 224 recursos de apuração/votação consultados tinha DataStore ativo; a consulta direta por linha retornou recurso inexistente. Evidência: storage/manifests/api-records-check.json. Isso não significa inexistência de outras APIs do TSE.

O coletor lê membros ZIP por HTTP Range e descompressão em fluxo; filtra UF, cargo, eleição ordinária e colunas necessárias antes de salvar Parquet comprimido. Uma passagem pelo membro presidencial BR produz os 16 recortes. Nos municipais, usa-se o membro da UF. Fontes verificadas do piloto foram reaproveitadas para evitar tráfego repetido.

Não ficam ZIPs completos ou CSVs nacionais no armazenamento regional. Ainda é necessário transferir o membro comprimido: o filtro ocorre localmente. Capturas SCOPED_PROJECTED_RECORDS têm hash próprio, diferente do original remoto; preservam origem, parâmetros, versão da projeção, ordinal do registro CSV, CRC e identidade HTTP disponível. Campos descartados exigem nova aquisição; os fatos selecionados podem ser reprocessados pelas capturas.

## Verificação

- **53 testes passaram**; Ruff passou; mypy validou 19 módulos. Um aviso de depreciação do adaptador HTTP dos testes não causou falha.
- **256 comparações independentes sem diferenças**, entre capturas Parquet e banco: contagens, aptos, presentes, ausentes e votos por UF/ano/turno. A segunda implementação usa SQL separado do parser.
- Todas as fontes referenciadas e o banco passaram pela conferência SHA-256. Comparecimento publicado satisfaz aptos = presentes + ausentes.
- API real respondeu aos agregados regionais de 2022/2024, votos de prefeito no Acre e turno futuro vazio; SP foi recusado com HTTP 422.
- Benchmark de uma chamada local com cache aquecido: agregado regional 2022 em aproximadamente 0,18 segundo; não é teste de carga concorrente.
- Dependências fixadas permanecem as auditadas no piloto, cuja consulta não encontrou vulnerabilidades conhecidas. Evidência datada: storage/manifests/dependency-audit.json.

Evidências: storage-regional/manifests/regional-validation.json e http-validation.json. Pacote: dist/auditabr-0.2.0-py3-none-any.whl.

## Exclusões e limites

**11 registros de comparecimento** tinham aptos diferentes de presentes + ausentes: SE/2014 (quatro nos dois turnos), AC/2016 (um), AL/2016 (um), MA/2016 (dois), PA/2016 (um), AM/2022 (dois, um por turno). Permanecem nas capturas e na quarentena. Somente essas linhas foram excluídas dos totais; partições recebem VALIDATED_WITH_EXCLUSIONS. Nenhum valor foi corrigido por hipótese; votos são independentes.

Foram preservadas apenas as três amostras de logs já adquiridas no Acre: 2022 (60 eventos), 2024 (62), 2026 (69), coincidentes com o comparecimento de cada seção. Isso não valida relógio, taxonomia, integralidade ou representatividade. Relógio UNKNOWN e taxonomia UNVERIFIED mantêm taxas de biometria/manual/atividade tardia nulas.

O score de abstenção é exploratório, sem p-value fictício ou inferência de irregularidade. Permanecem fora da implementação concluída: enriquecimento completo de partidos/coligações/situação, mapas TSE–IBGE validados, vínculos históricos documentais de seções, reconciliação de múltiplos dispositivos, assinaturas/importação binária de BU/RDV e inferência estatística calibrada. A carga regional de apuração/votação está concluída; não se declara conclusão de todas as extensões originais.

## Armazenamento

Fontes compactas com três logs: **271.092.998 bytes**. Derivados Parquet: **134.545.466 bytes**. Banco consolidado: **1.511.272.448 bytes**, contendo todos os oito pleitos. Bytes lógicos; excluem ambiente Python, código, metadados e relatórios.

A retenção conserva um banco atual; versões físicas retiradas recebem PRUNED_PHYSICAL. Arquivos amplos gerados pelo piloto são retirados somente após comprovação de substituição por capturas reconciliadas e cópias idênticas dos logs. Prompts originais, recibos, catálogos e relatórios permanecem. Evidência efetiva da limpeza: storage-regional/manifests/retention-12668d1e1721dd5f0ac65c8b.json, pilot-retirement.json e storage-final.json.

Retenção não remove anos do banco atual. Diffs de versões físicas removidas exigem backup. Não há limpeza automática após novas coletas. Comando: auditabr retain-snapshots --keep 1 --apply; omita --apply para simular.

## Relatórios

Quatro relatórios regionais por município, com snapshot fixado, cinco formatos e manifesto de hashes:

- 2022/T1: storage-regional/reports/73c17e20d6963aa5df903a95/.
- 2022/T2: storage-regional/reports/0ea2c0e8288864e6c3d29a1d/.
- 2024/T1: storage-regional/reports/fedd63efe0d39bdb3cbf97f2/.
- 2024/T2: storage-regional/reports/91b8f2a51ed8a8f37c845a91/.

Exportação cobre apuração/abstenção; votos são consultáveis pela API e painel. README.md contém operação, atualização seletiva e backup. PROMPT_MESTRE_UNIFICADO.md consolida as restrições solicitadas. Os dois prompts originais encontrados eram idênticos; a inspiração de esteleicao foi conceitual, sem incorporar código externo.


Medição final após limpeza: 21.480.771.846 bytes liberados; armazenamento regional completo 1.944.674.848 bytes. Banco atual e todas as fontes referenciadas permanecem acessíveis. Interface inspecionada no navegador em presidente/2022 e prefeito/2024; imagem em painel-regional.png.
