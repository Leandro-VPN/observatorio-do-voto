# Observatório do Voto / AUDITA-BR

Código de coleta, processamento e análise reproduzível de dados públicos do TSE (boletins de urna, logs de urna, correspondências de urnas e perfil do eleitorado), com métodos, testes estatísticos e priorização de observação eleitoral. Sinalização não é acusação. Site: https://leandro-vpn.github.io/observatorio-do-voto/ . Dados em GitHub Releases.

## Mapa do repositório: três escopos

| Escopo | O que é | Onde | Como rodar |
|---|---|---|---|
| **1. Varredura de fiscalização (atual)** | 11 UFs (BA, SP, MG, RJ, PR, RS, PE, CE, PA, SC, MA); presidente 2022 T1/T2 e 2026 T1; prefeito 2024 T1/T2. Indicadores por seção, comparação com as vizinhas do mesmo prédio, prioridade de observação por local, mapa de fiscalização, documentos e site. | `scripts/make_fiscalizacao_study.py`, `make_varredura_locais.py`, `make_mapa_fiscalizacao_2026t2.py`, `make_documentos_metodo.py`, `build_site.py`, `publish_release.py`, `restore_edicao.py`; saídas em `relatorios/fiscalizacao/` e `site/` | ambiente `.venv-report` (`requirements-report.lock`); ver "Varredura" e "Site" abaixo |
| **2. Pesquisa presidente/governador (2014–2026)** | Estudos exploratórios por estado e por partido, persistência, multiano, votos após 17h, fechamento e trocas de urna; piloto BA/2022/T2 com [plano a priori](research/PLANO_ANALISE_A_PRIORI.md). | `scripts/make_bahia_reports.py`, `make_late_votes_study.py`, `make_persistence_study.py`, `make_multiyear_study.py`, `make_closing_swaps_study.py`, …; dados em `research/`, saídas em `relatorios/<UF>`, `relatorios/governador` etc. | `.venv-report`; aquisição com `uf_pipeline.py`, `mun_logs_pipeline.py`, `bu_capture_all.py`, `ceft_capture.py`, `profile_capture.py` (ambiente `.venv`, `PYTHONPATH=src`) |
| **3. Base regional AUDITA-BR 0.2.0 (anterior)** | Aplicação local (CLI, API FastAPI, painel Streamlit) para presidente e prefeito nos 16 estados do Norte e Nordeste, com snapshots DuckDB e proveniência. As restrições de API, retenção e quarentena descritas em "Base regional anterior" pertencem a este escopo. | `src/auditabr/`, `tests/`, `storage-regional/` | ambiente `.venv` (`requirements.lock`); `python -m auditabr serve` |

Aquisição (escopo 2 e insumos do 1): HTTP Range nos ZIPs do Portal de Dados Abertos do TSE, hash SHA-256 e recibo por captura; os dados brutos (`research/`, `relatorios/`, `storage*`) ficam fora do git por tamanho. Para reconstruir o site sem refazer a coleta: `python scripts/restore_edicao.py --tag dados-AAAA-MM-DD [--parquet]` e depois `python scripts/build_site.py`. Testes: `pytest tests` (escopo 3, `.venv`) e `pytest tests_report` (varredura e site, `.venv-report`); o workflow do GitHub Actions roda ambos antes de publicar o site. Não há LICENSE escolhida: o titular decide a licença do código e os termos dos dados antes de convidar reutilização.

## Pesquisa presidente e governador

O pedido mais recente está em `research/`: quatro eleições presidenciais (2014/2018/2022, ambos os turnos; 2026, primeiro turno), comparação por partido e piloto BA/2022/T2. O [plano fixado](research/PLANO_ANALISE_A_PRIORI.md) prevalece para essa pesquisa. O processamento operacional e seus limites estão separados da base regional anterior.

O painel inclui **Piloto BA/2022/T2**, também acessível em http://127.0.0.1:8501/?study=pilot. A consolidação produz `research/piloto-ba-2022-t2/analysis/RELATORIO.md`, tabelas territoriais e manifesto. Resultados exploratórios de horários registrados e sequências manuais não equivalem aos indicadores confirmatórios ajustados.

### Varredura por local de votação (fiscalização)

`scripts/make_varredura_locais.py` consolida, por local de votação, as seções com votação tardia e/ou habilitação manual excessiva, compara cada uma às demais seções do mesmo local sem o comportamento com um teste de diferença acima do limiar (≥5 p.p. e |z| ≥ 2, com taxa-base medida nas seções comuns, por nível de comparação: o resultado principal é o do mesmo prédio com ≥3 pares; sem par no prédio, a comparação ao município é reportada em separado), cruza prefeito × presidente nas mesmas seções e atribui uma pontuação transparente de prioridade de observação (0–100; não é probabilidade de irregularidade), com pontos operacionais e de resultado separados. Saída em `relatorios/fiscalizacao/varredura/`: `VARREDURA_LOCAIS.xlsx` (aba `leia_me` com a metodologia), `LOCAIS_<UF>.xlsx`, `prioridade_locais_2026_T2.csv`, `comparacao_por_nivel.csv`, `pres_x_pref_pareado.csv` e `VARREDURA_LOCAIS_RISCO.pdf`. Depende dos `secoes_indicadores_*.parquet` gerados por `make_fiscalizacao_study.py` e roda no `.venv-report`. Cobertura: 11 estados (BA, SP, MG, RJ, PR, RS, PE, CE, PA, SC, MA). `make_mapa_fiscalizacao_2026t2.py` gera o mapa de fiscalização por estado e `make_documentos_metodo.py` os três documentos (método e dados, gráficos, resumo simples), com registro das alterações feitas após o parecer externo de 24/10/2026. Sinalização não é acusação.

### Site estático (Observatório do Voto)

`site/` é um site estático pronto para GitHub Pages. `scripts/build_site.py` o reconstrói a partir dos resultados atuais: números do painel, galeria dos 12 gráficos com legendas (`relatorios/fiscalizacao/documentos/figuras/legendas.json`), PDFs, pacotes de dados em `site/dados/` (CSVs, zips e os `secoes_indicadores_*.parquet` se `incluir_parquet` estiver ativo em `site/site_config.json`) e dicionário de campos. Os textos ficam em `site/templates/`; `site/index.html` e `site/app.js` são gerados. Para testar: `python -m http.server 8766 --directory site`. Publicação: o workflow `.github/workflows/pages.yml` publica a pasta `site/` na raiz de https://leandro-vpn.github.io/observatorio-do-voto/ a cada push em `main` (GitHub Actions). O `index.html` da raiz do repositório só serve de redirecionamento caso o Pages volte a publicar a partir da branch; a fonte recomendada nas configurações do Pages é "GitHub Actions". Pacotes grandes (parquet por eleição, zips de varredura, planilhas e mapa) e o pacote editorial (tudo o que o `build_site.py` lê) ficam fora do git, em `site/pacotes/`, e são publicados como GitHub Release imutável por `scripts/publish_release.py`: a tag vem do manifesto da edição (`relatorios/fiscalizacao/varredura/edicao.json`, escrito pela varredura com data, SHA do código produtor, parâmetros e hashes das entradas); se a tag já existir, cria a próxima revisão (`-r2`, …) em vez de substituir; a release nasce como rascunho, os ativos são conferidos por SHA-256 e um `manifesto-release.json` é anexado antes da publicação. O token fica em `api.env.txt` (ignorado pelo git). Sequência de uma nova edição: cadeia de análise → `build_site.py` → `publish_release.py` → `build_site.py` → commit e push; `restore_edicao.py --tag …` recria as entradas a partir da release.

## Base regional anterior

Aplicação local para pesquisar **presidente e prefeito nos 16 estados do Norte e Nordeste**, em oito pleitos, usando dados oficiais do TSE com fontes, hashes, snapshots e cobertura explícita.

- Presidente: 2014, 2018, 2022, 2026.
- Prefeito: 2012, 2016, 2020, 2024.
- Norte: AC, AP, AM, PA, RO, RR e TO. Nordeste: AL, BA, CE, MA, PB, PE, PI, RN e SE.
- Turnos onde ocorreram. Em 14/10/2026, o segundo turno de 2026 permanece `FUTURE`.

O escopo foi reduzido por solicitação do usuário. Os documentos originais em `AUDITA_BR/` foram preservados como referência histórica; em divergências prevalece `PROMPT_MESTRE_UNIFICADO.md` com as alterações para dois cargos e duas regiões. UFs e cargos externos ao escopo são recusados na ingestão e nas consultas.

## Abrir no Windows

Nesta instalação, execute `iniciar.ps1` no PowerShell ou:

```powershell
cd D:\votos
.\.venv\Scripts\python.exe -m auditabr serve
```

Painel: http://127.0.0.1:8501 · API/OpenAPI: http://127.0.0.1:8000/docs . Os serviços ficam restritos ao computador local. Ctrl+C encerra ambos.

O serviço iniciado em segundo plano nesta entrega pode ser encerrado com `./parar.ps1`. O script confere se o PID pertence ao Python deste projeto antes de encerrar seus processos.

## Instalar em outra máquina

Python 3.12+. Dependências exatas estão em `requirements.lock`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m auditabr init
```

Os scripts de pesquisa em `scripts/make_*.py` (PDF, XLSX, figuras) usam um segundo ambiente, `.venv-report`, criado a partir de `requirements-report.lock`:

```powershell
python -m venv .venv-report
.\.venv-report\Scripts\python.exe -m pip install -r requirements-report.lock
```

Linux: substitua `.\.venv\Scripts\python.exe` por `.venv/bin/python`. Use `python3 -m venv .venv`. A versão publicada foi testada no Windows/Python 3.12; outras plataformas requerem executar a suíte localmente.

## Coletar e reproduzir

```powershell
.\.venv\Scripts\python.exe -m auditabr discover --all-years
.\.venv\Scripts\python.exe -m auditabr collect-regions
.\.venv\Scripts\python.exe -m auditabr collect --year 2022 --uf MA
.\.venv\Scripts\python.exe -m auditabr collect --year 2024 --uf AC
.\.venv\Scripts\python.exe -m auditabr validate
.\.venv\Scripts\python.exe -m auditabr report --year 2022 --round 1 --uf MA
```

`collect-regions` processa os 16 estados, com publicação por ano. `--years 2022,2024` seleciona anos; sem esse parâmetro, processa os oito pleitos. `collect` limita a uma UF e aceita `--round 1`. Execuções repetidas reutilizam capturas verificadas; `--refresh` consulta o catálogo e adquire novamente as fontes.

Nas eleições gerais, a fonte é o membro presidencial BR. Nos municipais, é o membro da UF. O leitor usa HTTP Range e descompressão em fluxo, filtra UF/cargo/data e projeta as colunas necessárias antes de gravar Parquet comprimido. **Não salva ZIPs completos ou CSVs nacionais.** O formato ZIP exige transferir e percorrer o membro comprimido, inclusive registros descartados; não equivale a uma API que filtre linhas no servidor.

A API CKAN é usada para descobrir recursos, licenças e versões. Nenhum dos 224 recursos de apuração/votação consultados habilitava DataStore; a tentativa de `datastore_search` retornou recurso inexistente (evidência em `storage/manifests/api-records-check.json`). Isso não exclui outras APIs do TSE, mas impede substituir essa série histórica por consultas de linhas nos recursos encontrados. Não há coleta recorrente ou tarefa agendada.

## Consultas, versões e exportações

```powershell
.\.venv\Scripts\python.exe -m auditabr query --year 2022 --uf MA --group-by municipality
.\.venv\Scripts\python.exe -m auditabr resources --year 2024 --kind votes
.\.venv\Scripts\python.exe -m auditabr profile --resource ID_CKAN
.\.venv\Scripts\python.exe -m auditabr fetch --resource ID_CKAN --member NOME_REAL_DO_MEMBRO.csv
.\.venv\Scripts\python.exe -m auditabr fetch --resource ID_CKAN --input CAMINHO_DO_ARQUIVO
.\.venv\Scripts\python.exe -m auditabr ingest --receipt RECIBO_JSON --year 2024 --round 1 --uf AC --kind votes
.\.venv\Scripts\python.exe -m auditabr report --year 2022 --uf MA --snapshot ID_DO_SNAPSHOT
.\.venv\Scripts\python.exe -m auditabr diff SNAPSHOT_ANTERIOR SNAPSHOT_ATUAL
```

Os IDs e nomes reais são obtidos por `resources` e `profile`. Os comandos avançados `fetch` e `ingest` continuam disponíveis para importação manual; para economizar disco, use `collect`/`collect-regions`. Recibos ficam em `storage-regional/manifests/assets/`. Importação manual conserva a origem declarada pelo operador; o hash comprova integridade local, não assinatura/autenticidade eleitoral.

Relatórios em `storage-regional/reports/` contêm CSV, JSON, Parquet, Markdown, HTML e manifesto de hashes. O snapshot é fixado para que uma atualização posterior não altere o relatório. A exportação do painel cobre apuração/abstenção; resultados de candidatos são consultáveis pela API.

## Painel e metodologia

As páginas são Visão geral, Geografia, Resultados, Abstenção, Horários, Habilitação, Histórico, Cruzamentos, Casos, Fontes e qualidade, Metodologia. Filtros dependem de eleição/turno/UF/município/zona/local/seção. Códigos municipais são do TSE, não do IBGE. Quando não há coordenadas verificadas, a navegação é tabular.

Comparecimento = uma linha por seção/turno. A base é presidencial nos pleitos gerais e prefeito nos municipais. Abstenção agregada = `SUM(ausentes)/SUM(aptos)`. Votos por candidatura têm fato próprio; não multiplicam eleitores por joins.

O score de abstenção é **exploratório**: compara pares leave-one-out, recua à UF quando faltam pares municipais e incorpora heterogeneidade por momentos. Exibe efeito, limites exploratórios e cobertura. Não fornece p-values derivados automaticamente, causalidade ou probabilidade de irregularidade. A função FDR exige p-values previamente validados.

Histórico é agregado municipal/estadual com ressalvas de composição. Seção ou local sem vínculo documental retorna `NOT_COMPARABLE`. Não há geocodificação ou correspondência histórica inventada.

## Logs operacionais

O leitor reconhece os contêineres observados em amostras oficiais: 7z/2022 e ZIP/2024/2026 com `logd.dat`. Confere geografia, dia e sequência e preserva origem por hash/linha. Não associa evento a candidato ou identidade. Linhas de outros dias não viram votos; dois eventos no mesmo segundo não são colapsados.

```powershell
.\.venv\Scripts\python.exe -m auditabr ingest-log --receipt RECIBO_JSON --year 2022 --round 1 --uf AC --municipality 01392 --zone 0009 --section 0463
```

Por padrão, relógio e taxonomia ficam pendentes de validação documental. Nessa situação, os horários civis originais e contagens observadas podem ser inspecionados, mas **taxas de biometria/manual/atividade tardia permanecem nulas**. Mera solicitação manual não é confirmação; identificação biográfica não prova ausência de biometria. Fragmentos diferentes de uma mesma seção exigem reconciliação antes de serem combinados. Não há validação de assinatura digital de BU/RDV nesta versão.

## API local

Principais endpoints: `/api/v1/health`, `/elections`, `/offices`, `/contests`, `/catalog/resources`, `/catalog/coverage`, `/catalog/snapshots`, `/geography/*`, `/metrics/turnout`, `/metrics/votes`, `/metrics/times`, `/metrics/habilitation`, `/metrics/historical`, `/metrics/reconciliation`, `/analytics/funnel`, `/findings`, `/assets/{id}/metadata`, `/reports`.

Operações administrativas e criação de relatórios via API exigem `AUDITABR_ADMIN_TOKEN` e cabeçalho `Authorization: Bearer ...`. Não existe token padrão. Ingestão e publicação são feitas por CLI. O refresh do catálogo usa uma tarefa local e registra o estado em disco. A API limita/pagina listas; não aceita SQL ou caminhos de raw externos.

## Armazenamento e economia

`auditabr.json` seleciona `storage-regional` por padrão. A variável `AUDITABR_STORAGE` ou a opção global `--storage` permite outra pasta. Dentro dela: `raw` preserva capturas compactas; `captures` registra seleção e transporte; `silver` guarda Parquet normalizado; `gold` contém bancos imutáveis; `manifests` fixa proveniência; `quarantine` registra falhas. A UI lê somente snapshots publicados.

Capturas `SCOPED_PROJECTED_RECORDS` preservam os valores selecionados e o ordinal do registro CSV original. Seu SHA-256 é da captura Parquet, **não do ZIP/CSV original**. A origem inclui URL, recurso CKAN, licença, CRC do membro e identidade HTTP quando disponível. A versão de projeção e os parâmetros permitem reproduzir os fatos a partir das capturas. Arquivos amplos do piloto foram substituídos por esses recortes após reconciliação independente; seus recibos e relatórios continuam disponíveis.

Linhas com `aptos != presentes + ausentes` são preservadas na captura e registradas em quarentena; somente essas linhas ficam fora dos totais de comparecimento. A partição recebe `VALIDATED_WITH_EXCLUSIONS`, com aviso na interface. Não há correção presumida dos valores; votos de candidatos continuam independentes.

Downloads seletivos usam HTTP Range/If-Range validado e CRC do membro. O hash do membro não equivale ao hash de todo o ZIP remoto. Para obter arquivo integral, use `fetch` sem `--member`, com limite explícito de MB. Downloads integrais retomam `.part`; extração seletiva interrompida reinicia aquele membro. Este limite operacional é intencional e documentado.

Para reduzir duplicação física, a entrega mantém um banco consolidado com todos os oito pleitos. `auditabr retain-snapshots --keep 1` mostra uma simulação; acrescente `--apply` para remover bancos antigos após conferir seus hashes. Capturas, metadados e relatórios permanecem. Versões removidas ficam marcadas `PRUNED_PHYSICAL`; consultas/diffs exigem uma versão física ainda retida ou restaurada de backup. Essa limpeza não remove anos do banco atual e não roda automaticamente após futuras coletas.

Backup: `auditabr backup CAMINHO_NOVO_FORA_DO_STORAGE`. Não modifica a origem. Restore: copie o backup para uma pasta nova e execute `auditabr --storage PASTA validate` antes de servir. Proteja o diretório raw local; ele não é exposto por endpoint.

## Verificação

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m mypy src\auditabr
.\.venv\Scripts\python.exe scripts/validate_regional.py
```

Os testes unitários usam dados sintéticos isolados e não dependem de rede. `validate_regional.py` confere independentemente todas as capturas reais contra o banco, integridade e cobertura. A execução e cobertura reais são descritas em `docs/RELATORIO_EXECUCAO.md`. Consulte `docs/DECISOES_E_CORRECOES.md` para decisões de fonte, esquema e escopo.

## Fontes e atribuição

Fonte eleitoral: Tribunal Superior Eleitoral, https://dadosabertos.tse.jus.br/ . Licenças são capturadas por dataset no manifesto. Inspiração de interface e operação: https://github.com/ralbuque/esteleicao . Implementação independente; nenhuma licença foi presumida para o código externo. O código próprio não recebeu uma licença de redistribuição sem decisão do titular.
