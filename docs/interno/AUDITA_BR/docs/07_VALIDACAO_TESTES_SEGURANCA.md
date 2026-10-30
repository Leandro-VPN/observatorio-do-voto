# 07 — Qualidade, testes, segurança, governança e reprodutibilidade

## 1. Filosofia de QA

Qualquer número exibido precisa responder: **de qual arquivo saiu, a que seção pertence, que parser o interpretou, quais filtros foram aplicados, quais dados faltaram e quais checagens passaram?**

Gate de publicação em camadas:
- **Q0:** origem identificada e arquivo íntegro.
- **Q1:** esquema e tipos aderentes.
- **Q2:** chaves e geografia válidas.
- **Q3:** reconciliação eleitoral dos fatos permitida, com ressalvas categorizadas.
- **Q4:** logs com relógio e interpretação consistentes.
- **Q5:** métricas/relatórios com filtros, cobertura e métodos transparentes.

Não bloquear a publicação do **resultado oficial de uma seção** por causa de ausência de log; publicar resultado e marcar módulo operacional como indisponível.

## 2. Testes de integridade de fonte

1. SHA-256 calculado após finalizar download é estável em repetição sem alteração de origem.
2. Arquivo parcial não recebe status `VERIFIED`.
3. Conteúdo alterado na mesma URL gera novo `source_asset_id` e diff.
4. HTTP Range 200 em vez de 206 provoca fallback correto.
5. Content-Range, ETag e Content-Length inconsistentes invalidam retomada.
6. ZIP64 com entradas e offsets grandes é processado sem estourar inteiros.
7. ZIP/7z corrompido é posto em quarentena e não gera saída completa.
8. ZIP bomb, path traversal, nomes duplicados inesperados e symlink são bloqueados.
9. CSV com `;`, CRLF, aspas e `latin-1` é lido sem truncamento silencioso.
10. Parser captura arquivo com layout alterado em vez de deslocar colunas.
11. URLs e recursos CKAN devem apontar a domínios esperados conforme política configurada.
12. Logs de acesso não armazenam tokens/secrets.

## 3. Contratos de domínio eleitoral

13. Só existem quatro cargos no fato candidato.
14. A seleção de municipal só permite prefeito; geral permite os três cargos elegíveis.
15. Sem senador no segundo turno; validação falha caso algoritmo tente inserir.
16. Senado 2014/2022 contém 1 vaga por UF; 2018/2026 contém 2 vagas.
17. `section_turnout` tem 1 registro por seção/snapshot, mesmo com várias disputas.
18. Somar candidaturas não multiplica aptos/comparecimento.
19. Seção com número igual, mas em outro município/pleito, não faz join indevido.
20. Município TSE e IBGE não são tratados como códigos intercambiáveis.
21. Exterior e DF são suportados sem imputação de UF convencional para `ZZ`.
22. Município sem segundo turno retorna `NOT_APPLICABLE`.
23. Resultado 2026 segundo turno em 2026-10-12 retorna `FUTURE`.
24. Dados com candidatos substituídos/retificados mantêm snapshot e versão.
25. Município com seção agregada não duplica comparecimento.

## 4. Reconciliação quantitativa

26. `aptos=presentes+ausentes` quando o layout oficial autoriza esse invariante; exceções são documentadas.
27. Taxa de abstenção de 80 ausentes/400 aptos = 20%; agregado 80/400+20/100 = 100/500=20%, não média de 20% e 20% por coincidência apenas.
28. Taxa agregada de seções de tamanhos diferentes difere de média simples quando apropriado; demonstrar no teste.
29. Todo campo de contagem é não negativo e inteiro.
30. Resumo por candidato/cargo concilia com total de classe de voto previsto no BU, quando compatível.
31. Um eleitor em disputa do Senado com 2 vagas pode gerar **duas escolhas**, sem duplicar comparecimento.
32. Nenhum algoritmo divide automaticamente votos do Senado de 2018/2026 por comparecimento e chama isso de 'percentual de eleitores que votou no candidato' sem definição e regra específica.
33. Taxas por seção e município não se alteram em `join` com candidato.
34. Retificação de fonte gera diff e não sobrescreve original.
35. Duas fontes que discordam geram `reconciliation_issue`, não escolha arbitrária da mais conveniente.
36. Discrepância entre log e comparecimento não vira categoria de fraude.
37. Cobertura de logs em 10% do Brasil não pode produzir gráfico intitulado 'Brasil inteiro'.
38. Dado inexistente não retorna 0.

## 5. Testes temporais

39. Com evento UTC e fuso local equivalente, classificação após cutoff é igual.
40. Evento exatamente no cutoff tem comportamento definido pelo operador estrito `>`.
41. 2012 não herda regra horária de 2026.
42. Município com fuso distinto da capital da UF é resolvido por regra própria.
43. Histórico de horário de verão é considerado conforme data e localidade.
44. Relógio 60 minutos adiantado produz `CLOCK_SUSPECT` antes de ranking temporal.
45. Último voto não é interpretado como evento formal de fechamento.
46. BU transmitido às 22h não gera voto após horário regular se log encerrou às 17h.
47. Eventos de testes pré-pleito são excluídos.
48. Voto em nova urna após substituição não é duplicado nem perdido.
49. Vários eventos no mesmo segundo podem ser contados se são eventos distintos.
50. Timestamp de uma seção com data errada gera quarentena temporal.

## 6. Testes de habilitação

51. Solicitação manual não é confirmação manual.
52. Evento biográfico não prova ausência de biometria cadastrada sem regra suportada.
53. Ciclo com evento cancelado não é voto computado.
54. Ciclo com falta de eventos vai para `UNCLASSIFIED`.
55. Classes confirmadas não excedem número de ciclos de voto validados.
56. Nenhum campo publicado revela identidade de eleitor ou mesário.
57. A legenda 'assinatura do mesário' não aparece para um contador de habilitação manual.
58. Entre dois turnos, regra de taxonomia diferente bloqueia série homogênea sem ressalva.
59. Nível de evidência e taxa de desconhecidos aparecem em tela e exportação.

## 7. Estatística e prevenção de conclusões falsas

60. Grupo com poucos comparadores não recebe score pseudo-estável.
61. Modelo que usa leave-one-out não inclui a própria seção no baseline.
62. Variância ajustada fica definida para proporções 0/1 sem dividir por zero.
63. Hipóteses em massa reportam número de testes e FDR se p-values válidos.
64. Rankings excluem ou sinalizam relógios problemáticos e fonte incompleta.
65. Nenhuma função retorna `fraud_probability`.
66. Ficha de caso traz causas alternativas predefinidas e qualidade documental.
67. Métrica de taxa mostra numerador e denominador.
68. Taxa nacional recalculada a partir de contagens, não média de estados.
69. Comparação histórica de seção com vínculo de baixa confiança é rotulada.
70. Falta de log não é interpretada como ausência de evento tardio ou manual.

## 8. Testes de produto e UX

71. Filtros Brasil/UF/município/zona/local/seção são dependentes e coerentes.
72. Mudança de pleito limpa/discrimina filtros incompatíveis.
73. Dados provisórios e futuros são rotulados adequadamente.
74. Exportação acompanha `snapshot_id`, filtros, versão estatística e fontes.
75. Cada gráfico possui modo tabular equivalente e descrição de método.
76. O modo `demo` nunca aparece como dado oficial.
77. URL pública de raw é excluída se contiver parâmetro privado; URLs oficiais normais são permitidas.
78. API recusa cargo fora dos quatro permitidos.
79. API pagina listas grandes e aplica limite de rows.
80. Reabrir relatório salvo fixa a mesma versão de dados, não atualiza silenciosamente.

## 9. Estratégia de teste em níveis

- **Unitário:** parsing por linha, funções de taxa, hora, chaves, estados de classe, matching histórico.
- **Contrato:** schemas reais em amostras pequenas do TSE de cada ano/turno/UF/sistema.
- **Integração:** CKAN mockado, download Range mockado, ZIP pequeno, pipeline e DDL reais.
- **Propriedade:** entradas aleatórias e limites (zero, negativo, duplicado, texto truncado, duas vagas) usando Hypothesis.
- **Regressão:** snapshots aprovados de resultados calculados com dados oficiais de amostra; hash semântico dos relatórios.
- **Cross-validation:** somas por candidatos e seções contra relatórios oficiais; múltiplos parsers quando possível.
- **Sistema:** executar em máquina de RAM restrita com dataset de tamanho realista, medindo peak RSS, bytes, velocidade e tempo de query.

## 10. Política de confidencialidade, retenção e LGPD

O projeto não cria cadastro de eleitores nem processa características individuais para análise. Pode haver campos pessoais em dados públicos; dados sensíveis ou identificáveis devem ser **minimizados**. Aplicar:

- diretórios raw locais com ACL e sem sincronização pública por padrão;
- UI exibe dados agregados de seção/cargo, nunca sequências ligadas a pessoa;
- perfis públicos têm read-only; administração de coleta não exposta;
- não coletar IPs/usuários sem necessidade, e se fizer, documentar retenção;
- mascarar possíveis CPF, título e nomes indevidos em erros/logs;
- relatório inclui proveniência sem anexar conteúdo bruto com dados pessoais;
- não publicar dados de alto risco de reidentificação em combinação de microeventos (evitar timeline granular por evento na UI pública sem revisão de privacidade);
- política de backup/expurgo documentada; raw pode ser retido para reprodutibilidade em storage controlado;
- não armazenar credenciais em YAML versionado.

## 11. Segurança e supply chain

- Dependências fixadas e com relatório de vulnerabilidades.
- Conexões HTTPS, DNS normal, timeout, retry limitado, proibir redirecionamento para hosts não autorizados em downloader.
- Não passar membros ZIP como paths sem sanitização.
- Limites para descompressão total, razão de compressão e número de entradas.
- SQL parametrizado, validação de filtros e paginação.
- Sem execução de scripts de origem TSE/GitHub durante ETL.
- Bibliografia e URL expostas de maneira segura; download de scripts de terceiros sujeito a revisão.
- Licença do projeto próprio definida; atribuição de fontes respeitada.

## 12. Manifesto de reprodução

Todo relatório contém, no mínimo:

```json
{
  "report_id": "example-only",
  "snapshot_id": "snapshot-2026-10-12-sample",
  "as_of": "2026-10-12",
  "parameters": {"year": 2026, "round": 1, "uf": "MA"},
  "source_assets": [{"ckan_resource_id": "<real-id>", "sha256": "<real-hash>"}],
  "parser_versions": {"logs_2026": "<semantic-version>"},
  "analysis_version": "<semantic-version>",
  "coverage": {"sections_expected": null, "sections_valid": null},
  "clock_policy": "<version>",
  "created_utc": "<ISO-8601>"
}
```

Este objeto é **exemplo de contrato**, não um relatório real. Cada campo `<real-...>` deve ser preenchido somente após processamento real.

## 13. Critérios de falha impeditiva

Publicação do snapshot deve falhar se houver: tabelas de votos contendo cargo excluído; colisão de chave seção/turno; ausência de hash em arquivo usado; ingestão duplicada com contagens somadas; regras de Senado/turno violadas; fonte alegada como oficial sem catalogação; classificação temporal em massa sem política de fuso; parser aceitando layout desconhecido sem alerta; divulgação de identidade individual; relatórios 'Brasil' sem cobertura explícita; valores inventados para 2026/t2 antes do evento.
