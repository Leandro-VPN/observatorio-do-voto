# 05 — Especificação crítica: logs de urna, horários, fuso e identificação

> Este documento possui **prioridade de segurança analítica**. Uma implementação que contar eventos sem validar o relógio, o dia, a sequência da habilitação, substituições e cobertura pode produzir resultados muito convincentes, mas errados.

## 1. Cinco horários que não são a mesma coisa

| Conceito | Definição | Fonte pretendida | Interpretação válida |
|---|---|---|---|
| `scheduled_cutoff` | Instante de encerramento do **período regular** de votação aplicável à localidade/ano | Regra TSE + ato local se necessário | Marco legal/operacional, não fechamento efetivo |
| `last_vote_computed` | Último evento confirmado de conclusão de voto da urna/seção | log operacional | Atividade efetiva; não inclui candidato escolhido |
| `actual_closure_event` | Evento inequívoco de encerramento da votação pela urna | log validado | Encerramento registrado, se disponível |
| `bu_generated_at` | Geração/fechamento do boletim de urna | BU/log | Procedimento posterior à votação; não é voto |
| `received_or_totalized_at` | Recepção/totalização pela infraestrutura da Justiça Eleitoral | sistemas de transmissão/totalização, quando disponíveis | **Não** é horário de voto nem prova de atividade em urna |

O gráfico principal deve chamar a série de **eventos de voto computado após o fim do horário regular**; jamais de 'votos após fechamento da urna' se o evento de fechamento real ainda não ocorreu. Voto validamente computado depois do horário de encerramento geral pode decorrer de eleitor em fila, contingência ou outra circunstância operacional legal.

Se o usuário solicitar 'após horário de fechamento' oferecer duas consultas diferentes: `after_scheduled_cutoff` e `after_actual_closure`. A segunda é uma **checagem de integridade de ordenação de log**, não indicador geral de votação tardia. Uma seção com eventos posteriores a `actual_closure_event` deve ser reavaliada para múltiplos dispositivos, timestamps corrompidos, eventos retrospectivos e interpretação de mensagens antes de ser sinalizada.

## 2. Evidência do projeto `esteleicao`

A referência observada usa `logd.dat` dentro de `-log.jez` em 2026 (ZIP) e `.logjez` em 2022 (7z), com linhas tabuladas de data-hora, nível, ID do equipamento, aplicação, mensagem, hash. Mensagens textuais observadas no código da referência:

```
O voto do eleitor foi computado
Aguardando digitação do título
Aguardando digitação do identificador do eleitor
Tipo de habilitação do eleitor [biométrica]
O eleitor não possui biometria
Ano de nascimento digitado é igual ao do cadastro
Solicitação de dado pessoal do eleitor para habilitação manual
```

A aplicação deve **testar correspondência exata ou regras versionadas** contra amostras oficiais para cada eleição antes de assumir os significados. Traduzir mensagens iguais como equivalentes em anos diferentes é perigoso.

> Atenção especial: a mensagem 'Ano de nascimento digitado é igual ao do cadastro' por si só **não comprova ausência de biometria cadastrada**; pode ser evidência de um procedimento biográfico, dependendo do estado do fluxo. O projeto de referência a usa sob condições heurísticas. Nesta especificação, a classe `SEM_CADASTRO_CONFIRMADO` requer evento inequívoco, enquanto sinais ambíguos pertencem a `INDICIO_SEM_CADASTRO` / `BIOGRAFICO_NAO_CONCLUSIVO` com confiança menor.

## 3. Protocolos de parsing

### 3.1 Identificação do contêiner

1. Determinar tipo de arquivo por *magic bytes* (`PK..` para ZIP, assinatura 7z, etc.), não apenas pela extensão.
2. Validar ZIP e limites de descompressão; bloquear paths relativos ascendentes, paths absolutos, symlinks e membros duplicados suspeitos.
3. Procurar `logd.dat` ou equivalentes **reconhecidos por versão**; se não houver, retornar `UNSUPPORTED_FORMAT`, preservando a entrada e listando membros detectados.
4. Identificar codificação pela documentação/layout e perfil do arquivo; preferir heurística não destrutiva e registrar exceções de caracteres.
5. Fazer parser de linha tolerante a campos extras, mas rigoroso com data/hora e tipagem. Linha rejeitada → `rejected_events` com índice e razão.
6. Não usar somente dia com mais eventos para escolher o dia oficial. O dia deve vir de `election_round.election_date` e a seção/UF conhecida. Seleções alternativas são **sinal de qualidade**, não fallback silencioso.
7. Identificar `GAP`/cabeçalho para validar seção, município e zona, conferindo com nomes do arquivo e cadastro oficial, sem confiar cegamente em um único local de identificação.

### 3.2 Fragmentação, substituições e duplicatas

Um local pode ter equipamento substituído, arquivos múltiplos ou arquivos reenviados. Construir `operational_log_group(section_instance_id, device_id_hash, round_id)` com intervalos e status de origem. Concatenar eventos por timestamp **e por sequência do log**, quando existir. Evitar duplicar eventos iguais retransmitidos e **não** deduplicar automaticamente dois votos registrados no mesmo segundo, pois podem ser pessoas diferentes (ou relógio com precisão baixa). Deduplicação só com identidade de arquivo/linha, chaves operacionais inequívocas e regras documentadas.

Analisar transições: `device A ended`, `device B started`, gap, sobreposição; se cronologia ou sequência forem ambíguas, marcar `MULTI_DEVICE_UNRESOLVED`.

### 3.3 Máquina de estados de habilitação

Classes de saída propostas:

```
BIO_CONFIRMED
ALT_MANUAL_CONFIRMED
NO_BIOMETRIC_ENROLLMENT_CONFIRMED
BIOGRAPHIC_ALTERNATIVE_CONFIRMED
HABILITATION_OTHER_CONFIRMED
HABILITATION_UNCLASSIFIED
HABILITATION_CONFLICT
```

Estados transitórios por dispositivo/seção:

- `IDLE` — urna aguardando próximo eleitor;
- `HABILITATION_STARTED` — iniciou tentativa de identificar eleitor (sem armazenar título);
- `BIO_ATTEMPTED` — evento explícito de tentativa;
- `BIO_ACCEPTED` — evento inequívoco de validação biométrica;
- `ALT_REQUESTED` — procedimento alternativo solicitado;
- `ALT_APPROVED` — liberado após etapas requeridas;
- `NO_ENROLLMENT` — informação explícita de não existência de biometria, com semântica validada;
- `READY_TO_VOTE` — habilitado;
- `VOTE_COMPUTED` — evento de conclusão do voto;
- `CANCELLED_OR_TIMEOUT` — ciclo abortado/expirado;
- `UNRESOLVED` — estados incompletos/conflitantes.

Regras:

1. Ao iniciar novo atendimento, abrir `session_seq` **local à seção/dispositivo**, sem identificador de pessoa.
2. Associar eventos de habilitação ao evento de conclusão **somente** se pertencerem ao mesmo ciclo e dispositivo, sem eventos contraditórios de reinício, cancelamento ou substituição.
3. `BIO_CONFIRMED` exige aceitação inequívoca; menção a biometria não basta.
4. `ALT_MANUAL_CONFIRMED` exige solicitação **e** confirmação de habilitação manual (ou sequência que tenha sido validada com especificação oficial); mera solicitação não prova conclusão.
5. `NO_BIOMETRIC_ENROLLMENT_CONFIRMED` exige evento explícito sem ambiguidade; se apenas ocorreu identificação biográfica, classificar como biográfico confirmado ou evidência fraca de cadastro, conforme a versão.
6. Em fluxo misto ou com mensagens incompletas: `UNCLASSIFIED`/`CONFLICT`. Não forçar classe para chegar artificialmente a 100%.
7. Guardar `reason_code`, `observed_message_ids`, versão taxonômica e confiabilidade.
8. Se a quantidade de ciclos com voto não conciliar, exibir diferenças sem inferir identidade/voto.

### 3.4 Classificação robusta de timestamp

Para cada evento:

```text
raw_timestamp_text
local_civil_datetime
zone_id / time_offset_as_observed
corrected_utc_datetime
corrected_brt_datetime
rule_version
clock_quality_class
clock_adjustment_provenance
raw_line_number
```

Não sobrescrever a hora original depois da correção. Separar `clock_offset_estimate` (anomalia do relógio da máquina) de `civil_timezone_offset` (fuso legal). Não misturar horário de emissão do BU (pode ter fuso/campo próprio) com horário dos logs sem validação.

## 4. Regra histórica de fuso e horário eleitoral

- Para o pleito de 2026, o TSE estabelece votação 8h–17h no horário de Brasília. Para 2022, o sistema de referência trabalha com a mesma política; confirmar com instrução oficial de 2022 e lista de exceções.
- Antes de 2022, a aplicação **não pode** assumir 17:00 de Brasília para todas as localidades. Obter regra e horário legal do ano (p.ex. local vs BRT) em `time_rules.yaml` com link da norma e status de verificação.
- Usar `zoneinfo` e IANA timezone por município quando disponível; UFs podem ter mais de um fuso. Tratar Fernando de Noronha, oeste do Amazonas, zonas fronteiriças e eventuais horários de verão históricos.
- Horário de referência para comparar eventos: `cutoff_instant_utc`, criado a partir da regra da localidade, não `datetime.replace(hour=17)` após normalização incorreta.
- Se mapa de fuso ou relógio não confiável, excluir a seção dos rankings de 'após horário regular', mas contar no resumo de cobertura como excluída.

### 4.1 Auditoria do relógio do equipamento

O relógio local pode estar adiantado/atrasado; a referência `esteleicao` reporta casos com curvas deslocadas. Um pipeline sério deve marcar:

- divergência entre hora de início de operações e janela prevista;
- saltos/retrocesso de timestamps na mesma sequência de arquivo;
- agrupamentos deslocados vs várias urnas do mesmo local;
- diferença sistemática de hora/offset em relação ao município;
- grande discrepância entre 'hora média' de seção e comparadores;
- inconsistência entre horário operacional e timestamp de BU **quando são comparáveis**.

Estimar `clock_quality=TRUSTED | SUSPECTED_OFFSET | CLOCK_JUMP | UNKNOWN`; **nunca corrigir silenciosamente** com a moda de horários de outros equipamentos. Estimativa de offset deve ser um campo separado com intervalo de incerteza e validação cruzada. Se houver correção, mostrar resultados **originais e corrigidos** e o impacto no número de eventos após 17h. Em rankings públicos, só `TRUSTED` ou correção validada.

## 5. Sequência de invariantes dos logs

- Um evento de voto computado **não pode ser automaticamente associado a cargo ou candidato**. É um evento de conclusão de um eleitor na urna, que pode ter votado em vários cargos.
- Contar somente eventos do dia e turno corretos, excluindo testes/carga e reinicializações administrativas.
- Número de eventos deve ser >= 0, nunca obter contagem negativa.
- Todo evento classificado tem `source_asset_id` e `raw_line_number` ou posição equivalente.
- `n_bio + n_alt_manual + n_no_enroll + n_biographic + n_other + n_unclassified + n_conflict = n_votos_classificaveis_ou_tentados` de acordo com o grão definido (um evento final por voto), sem eventos duplicados.
- `after_cutoff_events <= valid_timed_vote_events`.
- `last_vote >= first_vote` na cronologia **validada**; caso contrário erro/relógio.
- Se `n_events ≠ voters_present`, criar alerta de **consistência**, não de fraude.
- Se não houver evento de fechamento real, mostrar `Fechamento real: não identificado`, mesmo que haja último voto e geração de BU.
- Se um evento aparece depois de evento de fechamento real: controlar se foi em outro equipamento ou houve problema de hora e documentar a reconciliação.

## 6. Métricas operacionais derivadas

| Indicador | Descrição | Denominador | Observação |
|---|---|---|---|
| eventos `after_regular_cutoff` | voto computado após o horário regular da localidade | eventos com hora e relógio validado | Pode ser legal pela existência de fila |
| fração tardia | `after_regular_cutoff / valid_timed_vote_events` | idem | Mostrar numerador e n sempre |
| último evento de voto | `MAX(timestamp)` | — | Não é fechamento formal |
| fechamento efetivo | último evento **inequívoco** de fim da votação | — | Pode não existir na versão do log |
| ociosidade antes do corte | maior hiato sem conclusão de voto, em janela configurável | intervalo de horas | Não prova ausência de eleitores/fluxo de autenticação |
| hora mediana | mediana de instantes computados | eventos validados | Comparar locais/histórico com controle de fuso |
| velocidade de conclusão | tempo entre votos consecutivos | instantes de voto | Intervalos curtos não comprovam irregularidade |
| habilitação biométrica | ciclos com evidência de sucesso biométrico | ciclos com classificação operacional | Não misturar com cadastro |
| habilitação manual confirmada | ciclos com aprovação inequívoca de alternativa/manual | ciclos classificáveis | Não confundir com assinatura física |
| indício de não cadastro | evidência sobre ausência de biometria no cadastro | ciclos pertinentes | Rotular 'indício' se não inequívoco |
| cobertura de classificação | ciclos classificados sem conflito / eventos computados | eventos computados | Não deve ser forçada a 100% |

**Mudança de denominador:** taxa de habilitação manual entre pessoas com biometria cadastrada requer evidência **individual agregada** de `elegível à biometria` por evento, sem identificação pessoal. Se não for possível reconstruir o subconjunto, a métrica deve ser `manual/eventos com habilitação classificada`, com rótulo diferente; **não** afirmar que representa 'manual dentre biometrizados cadastrados'.

## 7. 'Assinatura de mesário' — contrato de comunicação

A palavra 'assinatura' pode se referir a uma assinatura em caderno de votação, ato do mesário ou intervenção biométrica. **Não são intercambiáveis**. Só mostrar contagem de `ASSINATURA_FISICA_CONFIRMADA` caso exista fonte pública agregada e inequívoca, com definição de população e metodologia. Eventos `Solicitação de dado pessoal para habilitação manual` não comprovam assinatura física, sucesso ou autoria individual. A UI deve usar preferencialmente `habilitação alternativa/manual confirmada` e oferecer tooltip: 'Não indica assinatura física do caderno, nem identifica o mesário'.

## 8. Testes obrigatórios de logs

T01 evento de voto sem biometria anterior → `UNCLASSIFIED`, não manual. T02 aceitação biométrica inequívoca → `BIO_CONFIRMED`. T03 solicitação manual sem conclusão → não contar manual confirmado. T04 cancelamento antes de voto → zero computados. T05 mudança de equipamento e sequência correta → sem dupla contagem. T06 duas linhas de voto no mesmo segundo → preservar ambas se são eventos distintos. T07 log de treinamento anterior → excluir do dia oficial. T08 relógio saltando 90 min → bloqueio de taxa tardia. T09 UF com dois fusos → resolver por município. T10 eleição anterior à unificação → regra histórica própria. T11 sem eleição 2T em município → no events aplicáveis. T12 timestamp após fechamento formal → alerta de consistência, não conclusão automática. T13 rótulo 'sem cadastro' por frase biográfica ambígua → não classificar como confirmado. T14 hash raw presente, mas linha ilegível → rejeitada com razão. T15 ZIP malicioso → quarentena.

## 9. Proteção de dados e sigilo

Mesmo arquivo público pode conter texto com informações identificáveis ou sensíveis; o parser deve **permitir leitura operacional sem persistir identificadores pessoais desnecessários**. Armazenar `device_id_hash` se útil para distinguir equipamentos e `session_seq` local efêmero. Não persistir CPF, título, nome de eleitor, dado biométrico, nem logs brutos em servidor público. Não reconstruir sequência entre eleitor individual e escolha/candidato. Os dados raw podem ficar em diretório local restrito ao operador, sujeitos a política de retenção.

RDV é uma fonte de escrutínio e reconciliação do registro digital de votos, **não** uma chave para determinar pessoa/hora/candidato. Sem necessidade demonstrável, não decodificar/transformar RDV no MVP.

## 10. Grupos de evidência e casos de revisão

Para cada achado temporal registrar: `section_instance`, intervalo/cutoff, timezone/regra, `clock_quality`, n total válido, n tardio, comparadores mesma escola, eventos de abertura/encerramento, estado de substituição, compatibilidade log-oficial, proporção de eventos indeterminados, hash e limites. A triagem humana deve considerar fila, condições de acesso, contingência e relógio antes de qualquer interpretação.
