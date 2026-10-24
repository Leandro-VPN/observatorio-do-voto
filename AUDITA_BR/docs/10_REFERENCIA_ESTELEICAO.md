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
