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
