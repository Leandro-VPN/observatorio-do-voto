# AUDITA-BR — especificação consolidada de execução

**ALTERAÇÃO DO USUÁRIO EM 14/10/2026 — maior precedência:** limitar coleta, persistência analítica e consultas ao Norte (AC, AP, AM, PA, RO, RR, TO) e Nordeste (AL, BA, CE, MA, PB, PE, PI, RN, SE), somente presidente e prefeito. Preferir API oficial quando oferecer os dados necessários. Na ausência de consulta histórica por linha nos recursos CKAN, ler os membros ZIP em fluxo e persistir apenas linhas/colunas necessárias em Parquet comprimido. Não conservar ZIPs/CSVs amplos. Distinguir explicitamente hash da captura projetada de hash do original. Preservar URL, catálogo, identidade HTTP disponível, CRC, ordinal dos registros e versão da projeção. Validar capturas contra fatos antes de substituir dados amplos do piloto. Manter um banco físico consolidado com os oito pleitos, preservando capturas e manifests; marcar versões físicas removidas e informar que diffs dessas versões exigem backup. Linhas aritmeticamente inconsistentes ficam em quarentena identificada, sem ajuste presumido, com exclusões explícitas nos totais. Não ampliar logs além das três amostras já adquiridas sem necessidade analítica concreta. Esta alteração substitui exigências anteriores de cobertura nacional, conservação de fontes amplas e retenção ilimitada de bancos.

**ALTERAÇÃO DO USUÁRIO EM 13/10/2026 — precedência sobre o pacote original:** restringir toda a aplicação a PRESIDENTE (2014, 2018, 2022, 2026) e PREFEITO (2012, 2016, 2020, 2024). Governador e senador ficam excluídos, assim como deputados e vereadores. Usar apenas o membro BR para resultados presidenciais; não baixar ZIPs estaduais de votação em eleições gerais. Nos municipais, selecionar UF e filtrar prefeito antes da persistência. Regras e telas de Senado deixam de integrar a entrega. Preservar a metodologia, os logs sem vínculo de candidato e a rastreabilidade. Reduzir armazenamento/processamento por cache de partições e remoção apenas de cópias temporárias redundantes. Os requisitos abaixo são históricos quando conflitarem com esta alteração.

Inventário em 13/10/2026: o prompt mestre da raiz e o de AUDITA_BR são cópias byte a byte (SHA-256 b436a56631b7a05c9a6ce3a47930bb74fd9bf9cba38bad0df719f94fc8aabbe4). O ZIP repete o pacote. Não foi encontrado um segundo prompt distinto. DOCUMENTACAO_COMPLETA.md reúne os mesmos documentos individuais. Os originais ficam preservados.

Esta consolidação incorpora os requisitos do pacote AUDITA_BR e a simplicidade operacional descrita no README do projeto https://github.com/ralbuque/esteleicao: iniciar localmente, descer da UF à seção, comparar pares, inspecionar horários e exportar resultados. A implementação é independente; o código externo não é incorporado sem licença verificável.

## Missão e precedência

Construir e executar CLI, ingestão reproduzível, API FastAPI e painel Streamlit. Aplicam-se integralmente AUDITA_BR/PROMPT_MESTRE_CRIACAO.md e os documentos 01–11. Em conflitos prevalecem fonte observada, segurança, privacidade, grão e denominadores corretos. Interface simples não reduz o controle de qualidade.

## Contrato de entrega

- Oito pleitos: 2012/2016/2020/2024 prefeito; 2014/2018/2022/2026 presidente.
- Segundo turno só entra onde houver registros ordinários observados e após a data oficial.
- Comparecimento único por seção/pleito/turno, separado dos fatos de candidatos. Taxas calculadas pelas somas.
- Descoberta CKAN com IDs reais antes de qualquer download; recursos/fatos/execuções distinguem descoberto, baixado, validado e publicado.
- Raw imutável, SHA-256, parâmetros, schema e parser versionados; publicação atômica e preservação de snapshots anteriores.
- Processamento limitado por partição e memória; HTTPS, Range validado, retomada com identidade da versão, limites de arquivo e proteção contra arquivos maliciosos.
- Logs nunca ligam candidato a evento; habilitação manual exige conclusão inequívoca. Indeterminação é publicada. Fuso legal não é correção do relógio.
- Métricas temporais só são elegíveis com regra e relógio confiáveis; transmissão e fechamento não são votos.
- Abstenção alta e baixa são tratadas simetricamente; baselines excluem a seção observada, scores heurísticos não recebem p-values fictícios.
- Ausência permanece null com motivo; 2026/T2 permanece FUTURE até 25/10/2026. Dados simulados em armazenamento separado e rotulado.
- Relatórios fixam snapshot, filtros, fontes e fórmulas. Interface informa cobertura e limitações em cada página.

## Ordem e prova de execução

Fundação/testes → catálogo oficial → download/perfil → apuração e votos em uma UF → expansão municipal/histórica → geografia → logs → análises → painel/API/relatórios → expansão progressiva/benchmark. Não declarar coleta nacional ou parser oficial validado quando há apenas fixtures. O relatório de execução deve distinguir implementação, validação com dados reais e lacunas externas.
