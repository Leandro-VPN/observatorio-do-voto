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
