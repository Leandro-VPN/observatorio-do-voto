# 01 — Documento de Produto e Escopo (PRD)

## 1. Visão

Construir uma aplicação Python de investigação quantitativa de eleições brasileiras que permita acompanhar o caminho da evidência da visão nacional até o registro operacional de cada seção, abrangendo 2012, 2014, 2016, 2018, 2020, 2022, 2024 e 2026. O projeto é **descritivo, comparativo e investigativo**, sem conclusões pré-fixadas.

### Perguntas que a aplicação deve responder

1. Qual foi a abstenção de determinada seção, zona, município, UF ou eleição? Qual o denominador e a fonte exata?
2. Como essa abstenção mudou entre eleições, respeitando alterações no cadastro, locais e seções?
3. Quais locais concentraram votação computada após o horário regulamentar — **somente nos anos com logs compatíveis**?
4. A atividade tardia ocorreu em todas as seções de um local, sugerindo filas ou questões estruturais, ou em uma seção isolada?
5. Qual a proporção de eventos associados a habilitação biométrica, manual/alternativa, sem cadastro e indeterminada, por ano e por seção?
6. Como comparar manualmente os registros operacionais com comparecimento, BU e totalização sem confundir suas unidades?
7. Qual o número de votos, válidos, brancos, nulos e votos por candidato/partido **apenas** para presidente, governador, senador e prefeito?
8. Quais mudanças de turno, regras de disputa, vagas ao Senado, limites geográficos e indisponibilidade de fontes comprometem a comparação?
9. Quais achados possuem evidência suficientemente robusta para revisão humana e quais são apenas problemas de qualidade dos dados?
10. O resultado de qualquer gráfico pode ser reproduzido com um comando, a URL do TSE, o arquivo e sua impressão digital?

## 2. Usuários e perfis

- **Pesquisador:** filtros profundos, SQL de consulta, método exposto e intervalos de confiança.
- **Analista de dados:** cobertura, ingestões, catálogos, versão de parser, inspeção de erros e exportações.
- **Público/leitor:** métricas simples, linguagem acessível, comparações e alertas não conclusivos.
- **Administrador local:** definir localização do storage, limites de disco, jobs, republicação de snapshots.

A execução inicial é **local, single-user**, em Windows/Linux, sem autenticação obrigatória em `localhost`. Uma futura publicação em servidor exigirá autenticação administrativa, limitação de acesso e controles de privacidade apropriados.

## 3. Requisitos funcionais

IDs `RF-*` devem constar dos testes e relatórios de entrega.

### 3.1 Fontes e descoberta
- **RF-001** Inventariar catálogos oficiais TSE via CKAN (`package_search`, `package_show`) por ano, cargo indiretamente por recurso, nome e tipo.
- **RF-002** Registrar ID real de dataset, recurso, URL descoberta, formato, tamanho, data de alteração, extração e licença quando informada.
- **RF-003** Descarregar apenas recursos necessários, preservando raw byte a byte e hash SHA-256.
- **RF-004** Permitir download seletivo por ano/turno/UF e retomada segura; validar HTTP Range e ZIP64 antes de leituras parciais.
- **RF-005** Preservar versões de arquivos quando o TSE substituir conteúdo mantendo o mesmo nome.
- **RF-006** Usar estados `DISCOVERED`, `QUEUED`, `DOWNLOADING`, `VERIFIED`, `PARSED`, `VALIDATED`, `QUARANTINED`, `FAILED`, `UNAVAILABLE`.
- **RF-007** Registrar indisponibilidade de fonte de maneira explícita, com data, justificativa e possível próxima revisão.

### 3.2 Modelo eleitoral e apuração
- **RF-010** Importar apenas os cargos PRESIDENTE, GOVERNADOR, SENADOR e PREFEITO para o fato de votos por candidato.
- **RF-011** Normalizar código de cargo exclusivamente após validação do layout do ano; não adivinhar códigos só pelo número.
- **RF-012** Suportar eleições gerais e municipais e atribuir cargo elegível a cada pleito.
- **RF-013** Não gerar segundo turno para senador; gerar segundo turno apenas se existir na respectiva disputa regional.
- **RF-014** Armazenar candidatos com id eleitoral **por eleição**, partido/coligação, situação e votos; separar contabilização original e reprocessamento judicial posterior quando aplicável.
- **RF-015** Distinguir comparecimento por eleitor/seção de quantidade de seleções/votos por cargo. Eleitor do Senado em pleito de duas vagas tem até dois votos para a disputa; **não** comparar soma de votos nominais do Senado ao comparecimento como se cada eleitor tivesse apenas um voto.
- **RF-016** Exibir comparecimento, abstenção, aptos, seções agregadas, transferências temporárias e justificativas conforme a definição e a disponibilidade da fonte.
- **RF-017** Preservar os valores por candidato, brancos/nulos e outras classes do layout, incluindo categorias cuja contabilização dependa da situação da candidatura.
- **RF-018** Separar coluna `scope_status` por cobertura (`COMPLETE`, `PARTIAL`, `MISSING`, `NOT_APPLICABLE`, `PROVISIONAL`, `SUPERSEDED`).

### 3.3 Geografia e história
- **RF-020** Navegação BR > UF > Município > Zona > Local > Seção com retorno a qualquer nível.
- **RF-021** Representar zona e seção como identificadores que precisam do município, pleito e turno para identificar a unidade operacional.
- **RF-022** Não supor permanência de número ou endereço de seção entre eleições; construir correspondências documentadas de baixa/média/alta confiança.
- **RF-023** Preservar `ZZ`/exterior como domínio próprio, quando disponível, sem atribuir automaticamente a uma UF comum.
- **RF-024** Tratar DF, territórios especiais, locais sem coordenadas, urnas de contingência e seções agregadas sem exclusão silenciosa.
- **RF-025** Agregar por escola/local apenas se código de local validado no pleito; correspondência por nome e endereço é aproximação.

### 3.4 Logs operacionais
- **RF-030** Usar parsers por versão, tipo e ano; ler `logd.dat` em contêineres publicados, sem pressupor formato universal.
- **RF-031** Extrair sequência cronológica de eventos com id do arquivo e posição de linha, tipo de evento e timestamp com proveniência.
- **RF-032** Diferenciar hora de abertura, início da votação, computação do voto, fim da votação, emissão BU, envio, recebimento e totalização.
- **RF-033** Exibir horário local original e referência temporal padronizada, anotando versão de `tzdata`, regra histórica de votação e problemas do relógio.
- **RF-034** Identificar urnas substituídas e múltiplos arquivos por seção; reconstruir linha do tempo sem duplicar votos.
- **RF-035** Habilitação: biométrica comprovada, alternativa/manual confirmada, indício de ausência de cadastro, não classificável, conflitante.
- **RF-036** Não afirmar assinatura física do mesário a partir de evento de intervenção digital; somente fonte inequívoca autoriza essa contagem.
- **RF-037** Exibir filtros antes/depois de 17h somente quando `limite_legal_em_instante` estiver corretamente resolvido para a eleição, UF e localidade.
- **RF-038** Trabalhar independentemente quando logs não existirem (comparativo de apuração e abstenção continua utilizável).

### 3.5 Análises e relatórios
- **RF-040** Calcular taxas ponderadas (por totais) e mostrar média simples de seções separadamente e claramente rotulada.
- **RF-041** Comparar seção com pares do mesmo local e município via leave-one-out, observando tamanho de amostra.
- **RF-042** Oferecer estatísticas descritivas, funil de controle e modelos de excesso de dispersão; manter limiares versionados e configuráveis.
- **RF-043** Tratar correção para comparações múltiplas e cobertura de logs ao construir rankings nacionais.
- **RF-044** Separar `ALERTA DE QUALIDADE` de `ACHADO ESTATÍSTICO` e `CASO EM REVISÃO`; nenhum é prova de ilícito.
- **RF-045** Emitir relatório com denominadores, comparador, método, versão, cobertura, ressalvas e fontes.
- **RF-046** Exportar CSV, JSON, Parquet e um relatório HTML/Markdown; PDF opcional em etapa futura.
- **RF-047** Exibir valores pequenos e intervalos de incerteza; taxa extrema com n=3 não recebe prioridade automática.
- **RF-048** Permitir comparar cargos apenas quanto à **distribuição dos votos de cada cargo**, não transferir eventos temporais individuais a um candidato.
- **RF-049** Salvar investigação como configuração reproduzível (JSON/YAML + versão de snapshot), não como julgamento.

### 3.6 Operação
- **RF-050** CLI, API local e UI capazes de operar com dados de um único município, UF ou Brasil.
- **RF-051** Manifesto de execução e comandos de reprodução por relatório.
- **RF-052** Telemetria local de duração, bytes, falhas, itens descobertos/baixados/validados, sem enviar dados privados.
- **RF-053** Download interrompido continua após reinício, sem marcar parcial como completo.
- **RF-054** UI sempre distingue `sem dados` de `zero`, `não comparável`, `provisório` e `não se aplica`.

## 4. Requisitos não funcionais

- **RNF-01 Auditabilidade:** qualquer número remonta a versão de arquivo oficial, hash e regra de transformação.
- **RNF-02 Reprodutibilidade:** código, dependências e dados congelados produzem resultados equivalentes.
- **RNF-03 Local-first:** não exigir API comercial, cloud ou banco remoto.
- **RNF-04 Escalabilidade:** particionamento por pleito/turno/UF; evitar carregar todos os eventos em RAM.
- **RNF-05 Segurança:** não executar conteúdo de arquivos baixados; proteção contra ZIP bombs/path traversal; conexões HTTPS.
- **RNF-06 Privacidade:** remover/mascarar eventuais dados identificáveis dos logs antes da persistência analítica e jamais correlacionar voto a identidade.
- **RNF-07 Neutralidade:** explicar diferenças de cobertura, hipóteses alternativas e contexto operacional em cada alerta.
- **RNF-08 Acessibilidade:** interface em pt-BR, tabelas navegáveis e gráficos com alternativas tabulares.
- **RNF-09 Performance:** metas definidas por benchmark e hardware real, com degradação graciosa sob pouca RAM.
- **RNF-10 Extensibilidade:** novo pleito requer catálogo + mapeamentos + parser testado, não refatoração de toda aplicação.

## 5. Excluído do escopo

- Deputados federais, estaduais, distritais; vereadores; suplentes e vices como resultados independentes.
- Inferência de escolha individual, associação voto/hora/pessoa, vigilância individual de mesários/eleitores.
- Reconhecimento facial, cruzamento com bases pessoais ou identificação de eleitores.
- Declaração automática de fraude, causalidade de alterações nos votos ou autoria de irregularidade.
- Captura por tela de portal em substituição à API sem uma justificativa técnica documentada.
- Scraping indiscriminado de documentos privados, cadastros eleitorais pessoais ou dados não publicados.
- Predição de resultado futuro a partir de anomalias sem pesquisa metodológica separada.

## 6. Casos de uso prioritários

- **UC-01:** selecionar 2022/t1/MA/Açailândia, listar zonas, escolas e seções, comparar taxas com MA e Brasil.
- **UC-02:** selecionar eleições 2014–2026 para cargo presidente e visualizar porcentagens por candidato/UF, com status de apuração.
- **UC-03:** selecionar um local de votação em 2026/t1 e comparar horários das seções da escola com logs válidos, cobertura e relógio.
- **UC-04:** visualizar 2018/t1/SENADOR, contemplando duas vagas e denominadores corretos.
- **UC-05:** abrir 2016/t2 de município sem segundo turno e receber `NOT_APPLICABLE` sem criar linhas zeradas.
- **UC-06:** abrir seção sem log e ver resultados, abstenção e mensagem 'Sem dados operacionais publicados/validados'.
- **UC-07:** exportar um achado contendo raw hashes, algoritmo e contra-hipóteses.
- **UC-08:** detectar substituição de urna e conciliar vários fragmentos do log.
- **UC-09:** reprocessar um recurso corrigido pelo TSE sem perder o snapshot anterior.
- **UC-10:** comparar 2012–2024 para prefeito por município, sinalizando fusões e modificações de seções.

## 7. Conceitos de tela

Resumo Brasil; Explorar geografia; Candidatos/cargos; Abstenção; Histórico de pleitos; Horários; Habilitação; Análises combinadas; Casos de revisão; Qualidade/Cobertura; Fontes/Proveniência; Administração de coleta. Detalhamento em `08_API_E_PAINEL.md`.

## 8. Ética de apresentação

Nunca rotular uma seção ou escola como 'fraudulenta'. Texto padrão: **'A diferença indicada é estatística e pode refletir composição do eleitorado, infraestrutura, filas, erro de registro ou cobertura incompleta. Requer verificação independente.'** Dados operacionais não substituem procedimento de auditoria oficial nem demonstram, isoladamente, ilícito.
