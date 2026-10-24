# Decisões verificadas durante a implementação

## 2026-10-14 — Norte/Nordeste, captura compacta e retenção

A solicitação mais recente limita o projeto aos 16 estados das duas regiões e a presidente/prefeito. `auditabr.json` seleciona `storage-regional`. Os fatos e as consultas rejeitam UFs externas. A política desta seção substitui as decisões anteriores sobre raw amplo e retenção ilimitada.

A API CKAN foi consultada para descoberta. Os 224 recursos de apuração/votação selecionados nos oito pleitos não tinham DataStore ativo; uma consulta direta por recurso confirmou indisponibilidade de registros nessa API. A evidência está em `storage/manifests/api-records-check.json`. Não se presume inexistência de outras APIs de divulgação do TSE nem equivalência destas com a série histórica por seção.

O coletor lê os membros oficiais com HTTP Range e descompressão em fluxo. Retém somente UF, cargo, eleição ordinária e colunas necessárias, em Parquet comprimido. Nas fontes presidenciais BR, uma única passagem gera os 16 recortes. Fontes locais já verificadas foram reaproveitadas para evitar transferências repetidas. Ler um ZIP remoto ainda transfere o membro comprimido; o filtro não é executado no servidor TSE.

Cada captura informa `SCOPED_PROJECTED_RECORDS`, hash próprio, parâmetros, versão da projeção, recurso CKAN, URL, metadados de transporte e ordinal do registro CSV. O hash da captura não é apresentado como hash do ZIP original. Capturas permitem reprocessamento dos fatos dentro do escopo; campos descartados exigem nova aquisição da fonte.

Inconsistências `aptos != presentes + ausentes` ficam preservadas na captura e em quarentena. A carga regional exclui apenas a linha inconsistente, publica as demais e informa `VALIDATED_WITH_EXCLUSIONS`; a ingestão manual estrita continua recusando a partição. Nenhum número é corrigido por hipótese.

A publicação é agrupada por ano para reduzir cópias do banco. Uma execução idêntica é reconhecida antes de copiar o banco. A retenção explícita conserva o banco atual com todos os oito pleitos e remove somente versões físicas antigas verificadas, mantendo capturas, manifests e relatórios. Versões removidas recebem `PRUNED_PHYSICAL`; diffs precisam dos bancos retidos/restaurados. Os arquivos amplos gerados pelo piloto só podem ser retirados após comprovação de substituição por capturas reconciliadas. Os prompts originais são preservados.

## 2026-10-13 — Fontes da especificação

Os dois prompts mestres disponíveis são idênticos por SHA-256. O ZIP contém o mesmo pacote extraído; DOCUMENTACAO_COMPLETA concatena os documentos. Não havia um segundo prompt mais simples distinto. A consolidação preserva a especificação e incorpora a navegação/CLI simples do README de https://github.com/ralbuque/esteleicao. Nenhum código desse repositório foi copiado.

## 2026-10-13 — Alteração explícita de escopo pelo usuário

Somente PRESIDENTE e PREFEITO. A instrução posterior do usuário prevalece sobre o pacote original, que incluía governador/senador. A coleta em andamento foi interrompida. O domínio, parser, filtros, API, telas e seleção de arquivos foram restringidos. Governador, senador, deputados e vereadores não integram novos fatos analíticos.

- Gerais: usar membro de apuração BR e recurso de votação BR, filtrando UF/turno. Não adquirir votação estadual desses pleitos.
- Municipais: usar arquivos da UF e reter somente prefeito nos derivados. O arquivo oficial pode também conter vereadores; raw preserva os bytes originais, derivados descartam esses cargos.
- Apuração geral passa a usar exclusivamente a base presidencial, sem misturar comparecimento estadual.
- A migração 002 remove fatos dos cargos excluídos da nova versão publicada. Snapshots antigos ficam como histórico técnico, não são opções normais do painel.

## Arquivos presidenciais separados

O catálogo oficial resultados-2022 informa que arquivos por UF têm cargos estaduais e o BR contém presidente, inclusive exterior: https://dadosabertos.tse.jus.br/dataset/resultados-2022 . A seleção de fontes deriva dos IDs/URLs CKAN efetivamente retornados, não de URLs fabricadas.

## Comparecimento por população eleitoral

Em 189 seções MA/2022/T1 houve diferença entre contagens presidenciais e estaduais. Exemplo observado: MA/09377/zona0019/seção0128: estadual aptos356/presentes304; presidencial aptos366/presentes314, ambos ausentes52. A coleta conjunta foi bloqueada antes de publicar contagens conflitantes. Voto em trânsito fora da UF de origem pode ser apenas presidencial (exemplo de regra oficial: https://sintse.tse.jus.br/documentos/2022/Jul/22/diario-da-justica-eletronico-tres-destaques/resolucao-no-370-2022-dispoe-sobre-a-instalacao-de-mesas-receptoras-de-justificativas-mrj-das-agrega ). Essa é uma possível explicação, não uma atribuição causal comprovada às 189 seções. A restrição solicitada a presidente resolve a ambiguidade do denominador: usa-se somente a disputa presidencial nos gerais.

## Esquema e snapshots

O DDL do pacote era um rascunho. `resources/reference_schema.sql` preserva-o; `runtime.sql` define um esquema físico menor com fatos desnormalizados e contagens int64. Cada snapshot é um arquivo DuckDB independente, somente leitura; a publicação troca um pequeno manifesto atomicamente. Isso evita concorrência entre leituras Streamlit/API e ingestão no Windows. Migrações têm checksums.

## Logs e prudência verificável

Amostras reais AC: 2022 é 7z, 2024/2026 são ZIP, com logd.dat. O leitor confere cabeçalho geográfico e conta eventos do dia do pleito. Taxonomia/relógio permanecem UNVERIFIED/UNKNOWN até haver validação documental. A falta dessa validação bloqueia as taxas de biometria/manual/atividade tardia; não transforma ausência em zero. Não se publicam identificadores pessoais.

## Métodos

O escore de abstenção usa momentos de pares leave-one-out com sobredispersão não negativa e limites exploratórios. Não é modelo inferencial calibrado. FDR existe apenas como função explícita para p-values previamente validados. Histórico automático é territorial; seção/local sem vínculo documental retorna NOT_COMPARABLE.
