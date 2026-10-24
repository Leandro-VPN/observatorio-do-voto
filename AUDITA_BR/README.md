# AUDITA-BR — Plataforma de Inteligência, Rastreabilidade e Auditoria Estatística Eleitoral

**Especificação técnica para implementação por IA de programação.** Versão 1.0.0 | Referência temporal: **12 de outubro de 2026** | Idioma: pt-BR.

> **Missão:** construir um observatório **reproduzível, apartidário e auditável** das eleições brasileiras, com recorte de resultados restrito a **presidente, governador, senador e prefeito**, cobrindo oito pleitos (2012–2026), analisando resultados, abstenção, locais de votação, logs e procedimentos de habilitação **conforme a disponibilidade e a confiabilidade dos dados originais**.

## Comece por aqui

1. Leia `docs/01_PRODUTO_ESCOPO.md` e `docs/02_FONTES_OFICIAIS_E_COBERTURA.md`.
2. Leia `docs/03_ARQUITETURA_TECNICA.md`, `docs/04_MODELO_DE_DADOS.md` e `db/schema.sql`.
3. Leia `docs/05_LOGS_HORARIOS_BIOMETRIA.md` e `docs/06_METODOLOGIA_ESTATISTICA.md` **antes** de implementar detecção de anomalias.
4. Leia `docs/07_VALIDACAO_TESTES_SEGURANCA.md`, `docs/08_API_E_PAINEL.md` e `docs/09_ROADMAP_CRITERIOS_DE_ACEITE.md`.
5. Use `PROMPT_MESTRE_CRIACAO.md` como a primeira instrução para a IA programadora, anexando este pacote inteiro.
6. `docs/10_REFERENCIA_ESTELEICAO.md` registra o que foi estudado no repositório de inspiração e o que **não** deve ser copiado sem validação.
7. `docs/11_GLOSSARIO_E_DECISOES.md` define termos, situações ambíguas e decisões arquiteturais.

## Escopo por eleição

| Pleito | Natureza | Cargos a exibir | Turnos possíveis |
|---|---|---|---|
| 2012 | Municipal | Prefeito | 1º e, onde houve, 2º |
| 2014 | Geral | Presidente, governador, senador | 1º; 2º só presidente/governador quando aplicável |
| 2016 | Municipal | Prefeito | 1º e, onde houve, 2º |
| 2018 | Geral | Presidente, governador, senador | 1º; 2º só presidente/governador quando aplicável |
| 2020 | Municipal | Prefeito | 1º e, onde houve, 2º |
| 2022 | Geral | Presidente, governador, senador | 1º; 2º só presidente/governador quando aplicável |
| 2024 | Municipal | Prefeito | 1º e, onde houve, 2º |
| 2026 | Geral | Presidente, governador, senador | 1º disponível; 2º previsto para 25/10/2026, ainda futuro no corte documental |

**Regras mandatórias:**
- NÃO importar votos de deputados, vereadores, vice-cargos ou suplentes como resultados analíticos; vice/suplentes podem aparecer **apenas como metadados de chapa**, se necessário.
- NÃO assumir que todas as fontes, logs ou timestamps existem em todos os pleitos.
- NÃO inferir em quem uma pessoa votou a partir do horário de voto. Logs são **operacionais**, não um vínculo com a escolha individual.
- NÃO converter automaticamente eventos de habilitação manual em 'assinaturas de mesário' ou 'fraude'.
- NÃO tratar transmissão tardia de BU como voto tardio.
- NÃO interpretar sinal estatístico como irregularidade comprovada.
- Dados ausentes devem gerar **NÃO DISPONÍVEL / NÃO APLICÁVEL / INDETERMINADO**, nunca zero fictício.
- O recorte dos cargos **não** impede usar arquivos globais de comparecimento para a consistência do pleito, desde que sem importar votos de outros cargos.

## Pacote

| Artefato | Finalidade |
|---|---|
| `PROMPT_MESTRE_CRIACAO.md` | Prompt executável para IA de desenvolvimento, com condições de aceite |
| `docs/01_PRODUTO_ESCOPO.md` | Visão de produto, requisitos e casos de uso |
| `docs/02_FONTES_OFICIAIS_E_COBERTURA.md` | Inventário verificado, fontes pretendidas e descoberta via API CKAN |
| `docs/03_ARQUITETURA_TECNICA.md` | Camadas, fluxos, reprocessamento, CLI e desenho de módulos |
| `docs/04_MODELO_DE_DADOS.md` | Dimensões, fatos, grãos, versões, chaves e dicionário |
| `docs/05_LOGS_HORARIOS_BIOMETRIA.md` | Parsers, máquina de estados, tempo civil, fuso, evidência |
| `docs/06_METODOLOGIA_ESTATISTICA.md` | Indicadores, denominadores, modelos, vieses e protocolos |
| `docs/07_VALIDACAO_TESTES_SEGURANCA.md` | QA, testes de integração, privacidade e reprodução |
| `docs/08_API_E_PAINEL.md` | Endpoints, telas, filtros, exports e performance |
| `docs/09_ROADMAP_CRITERIOS_DE_ACEITE.md` | Plano de entregas, prioridades e gates de qualidade |
| `docs/10_REFERENCIA_ESTELEICAO.md` | Mapeamento de código de referência, ideias e restrições |
| `docs/11_GLOSSARIO_E_DECISOES.md` | Termos, ADRs e perguntas em aberto |
| `config/pleitos.yaml` | Matriz declarativa de eleições/cargos/turnos |
| `config/fontes_seed.yaml` | Fontes oficiais e status inicial de evidência |
| `db/schema.sql` | DDL inicial do banco analítico (DuckDB) |
| `scripts/inventariar_ckan.py` | Script utilizável de **descoberta**, sem downloads em massa |
| `tests/cenarios_aceite.md` | Especificações de fixtures e resultados esperados |

## Não concluído neste pacote

Isto é a **documentação de arquitetura**, não a aplicação pronta nem uma coleta executada. O arquivo `scripts/inventariar_ckan.py` é um auxiliar funcional de inventário de metadados, que requer rede no computador onde for executado. URLs/formatos finais de todos os anos devem ser confirmados via catálogo oficial no desenvolvimento.

## Fontes de referência

- Portal TSE: https://dadosabertos.tse.jus.br/
- API CKAN: https://dadosabertos.tse.jus.br/api/3/action/package_search
- Documentação técnica da urna 2022: https://www.tse.jus.br/eleicoes/eleicoes-2022/documentacao-tecnica-do-software-da-urna-eletronica
- TSE 2026, arquivos transmitidos: https://dadosabertos.tse.jus.br/dataset/resultados-2026-arquivos-transmitidos-para-totalizacao
- Projeto de inspiração, não dependência: https://github.com/ralbuque/esteleicao
