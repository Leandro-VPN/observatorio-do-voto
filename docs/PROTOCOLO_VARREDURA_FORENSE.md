# Protocolo da varredura forense — versão 1.0

Travado em 05/11/2026 antes da execução das checagens. Alterações posteriores exigem nova versão, com justificativa, e ficam registradas na seção 9. Sinalização não é acusação: tudo o que este protocolo produz é descritivo e não indica irregularidade por si só.

## 1. Objetivo

Percorrer todas as camadas abaixo procurando qualquer coisa problemática, inconsistente, incompatível ou inexplicada (estatística, de processo, de dados ou de formato) nos pleitos já cobertos pelo repositório, sem descartar nada por parecer improvável, e levar cada achado a um dossiê investigado até o fim. O objetivo é entender como a eleição presidencial de 2026 se comportou em relação às anteriores, ou contestar o fenômeno se o dado sustentar.

## 2. Escopo

- Presidente 2014, 2018, 2022 e 2026 (1º e 2º turnos), governador onde houver BU por seção em disco, prefeito 2024 (1º e 2º turnos) e os municipais 2012/2016/2020 onde houver BU em disco.
- Unidade: seção (urna) por pleito e turno. Chave: UF, município (código TSE), zona, seção; por urna, o nome do pacote (stem) e o SHA-256 do log.
- Universo de referência de cada teste: o pleito/turno/cargo do próprio teste. Seções do exterior (ZZ), especiais e com menos de 50 aptos entram nos inventários e nas reconciliações, mas ficam fora das referências estatísticas e são reportadas à parte.

## 3. Camadas

C1 aquisição e formato; C2 consistência interna da urna (BU × RDV × log, assinaturas); C3 cronologia e processo da seção; C4 totalização; C5 padrões estatísticos entre seções; C6 estabilidade e regimes entre eleições; C7 espelhamento e duplicidade; C8 clusters (espaciais, técnicos, de processo). O mapa do que o repositório já cobria por camada antes desta varredura está em `mapa/RESUMO_MAPA.md` e nos `mapa/mapa_C*.json`; a varredura estende e não refaz.

## 4. Ordem e custo

1. Checagens leves (consultas aos parquet/CSV já existentes) de prioridade 1 e 2 de todas as camadas, em paralelo, cada uma gravando CSVs próprios e registrando seus achados.
2. Passadas únicas e retomáveis sobre os arquivos de urna, em série e com prioridade baixa (uma de cada vez, nunca em paralelo com outra passada pesada): (a) logs — linha do tempo, cabeçalho técnico, taxonomia de habilitação, intervalos, monotonicidade, erros, hash de cada logd.dat; (b) BUs binários — invariantes estruturais, identificação de urna e carga, todos os cargos. Primeiro 2026 2º turno, depois 2022 2º turno, depois os 1ºs turnos e 2024.
3. Checagens que dependem das passadas.
4. Dossiês, verificação adversarial, registro de achados, relatório, lista de dados externos.

## 5. Controles obrigatórios

- Todo teste estatístico feito em 2026 é feito, com a mesma especificação, em 2022 e, quando os dados permitirem, em 2014, 2018 e 2024. Um resultado de 2026 só é lido ao lado do seu controle.
- Testes de detecção recebem cópias plantadas (manipulação conhecida sobre uma base real) para medir poder; o que a bateria não detecta nas plantadas não pode ser declarado ausente no real.
- Comparações de resultado são simétricas: todos os candidatos, margens e brancos/nulos, nunca só o vencedor ou só um lado.
- Comparações de seção usam as vizinhas do mesmo prédio (mesmo local de votação, ≥ 3 pares); sem par, o nível de comparação cai para município e isso é reportado (NOT_COMPARABLE quando não há vínculo documental).

## 6. Regras de decisão

- Multiplicidade: dentro de cada família de testes (camada × pleito × medida), Benjamini–Hochberg a 5%; onde houver nulo por permutação, o limite é o p95 do máximo sob permutação. Seções isoladas só são listadas com |z| ≥ 4 (ou p < 1e-6 em testes multivariados).
- Status de cada achado, atribuído só depois dos itens 1–5 do dossiê: EXPLICADO (causa documentada nos dados), ARTEFATO (parser, formato, fuso, quarentena, vínculo), PLAUSÍVEL-EXPLICÁVEL (hipótese compatível, não comprovada), INEXPLICADO (controles e hipóteses não explicam), NÃO TESTÁVEL COM ESTES DADOS (falta dado externo nomeado).
- Materialidade: todo achado traz votos possivelmente envolvidos (mínimo e máximo) e a margem do nível relevante; a prioridade de aprofundamento segue materialidade e falha de reconciliação (C2 e C4 antes de C5 e C6).
- Nada é corrigido por suposição: linhas que falham invariantes vão para quarentena identificada, com o valor original preservado.
- Exploratório × confirmatório: tudo nesta varredura é exploratório, salvo os indicadores A/B/C/D do plano a priori (`research/PLANO_ANALISE_A_PRIORI.md`), que seguem aquele plano.

## 7. Convenções

Recibo SHA-256 (`<arquivo>.json`) ao lado de cada parquet derivado com entradas e hashes; quarentena em `research/varredura_forense/quarentena/`; status de comparabilidade por seção; manifesto `edicao.json` com SHA do código, parâmetros, hashes das entradas e deste protocolo; erratas como entrada datada em `docs/DECISOES_E_CORRECOES.md` e na seção "Registro de alterações" do relatório; CSVs com `;` e vírgula decimal; rodapé "descritivo — não indica irregularidade por si só"; termos: "diferença acima do limiar", "comportamento", "prioridade de observação".

## 8. Entregas

`registro_de_achados.parquet/.csv` (id, camada, pleito, cargo, UF, escopo, tipo, efeito, materialidade mín/máx, margem, status, exploratório, fonte, dossiê, errata, data, prioridade); um dossiê por achado em `dossies/`; `RELATORIO_VARREDURA.pdf` (o que foi checado, passou, falhou, não foi testável); código em `scripts/varredura_forense*.py` com testes em `tests_report/`; `dados_externos_necessarios.csv`.

## 9. Registro de alterações

- 05/11/2026 — v1.0, travado antes de qualquer checagem desta varredura.
