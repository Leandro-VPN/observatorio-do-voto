# Cenários de aceite para o desenvolvedor (fixtures sintéticas, não dados TSE)

Todos os valores desta página são **exemplos inventados para testar o código**.

## 1. Não duplicar comparecimento por cargo

Seção X/t1/2022, aptos 400, presentes 300, ausentes 100; disputa presidente e governador com múltiplos candidatos.

**Esperado:** `section_turnout` 1 linha, aptos 400, presentes 300, ausentes 100; soma pós-join com candidato não pode virar 800 aptos ou 600 presentes. Taxa = 25%.

## 2. Média simples não é taxa agregada

Seção A 10 aptos, 5 ausentes; Seção B 100 aptos, 10 ausentes.

**Esperado:** média simples = (0,50+0,10)/2 = 30%; taxa agregada = 15/110 = 13,63636%. Ambas só aparecem com rótulos próprios.

## 3. Senado duas vagas

2018/t1 UF fictícia, 100 eleitores presentes, 2 vagas. Total de 150 votos nominais registrados para candidatos; comparecimento 100.

**Esperado:** nenhuma exceção `150 != 100` baseada nessa falsa equivalência. Não informar que '150 eleitores votaram'. Senado 2018 deve ter `senate_seats = 2`; 2022 = 1.

## 4. Turno inexistente

Município Y/2024 com 1º turno, sem 2º turno. **Esperado:** `/contests?office=PREFEITO&round=2&municipality=Y` retorna `NOT_APPLICABLE`, sem linhas fabricadas.

## 5. Fonte ausente não significa zero

Seção Z/2016 tem resultados mas não tem log disponível/validado. **Esperado:** abstenção calculada; `after_cutoff_events=null`, `manual_confirmed=null`, `operational_status=UNAVAILABLE`, sem sinalização temporal.

## 6. Voto exatamente no cutoff

TSE define horário regular até 17h; eventos 16:59:59, 17:00:00, 17:00:01; regra `>`.

**Esperado:** 1 evento após cutoff, 3 válidos, taxa 33,333%. Em regra diferente, registrar explicitamente.

## 7. Transmissão tardia não é voto tardio

Último voto 16:50, fechamento 17:01, BU gerado 17:05, recebido 20:13.

**Esperado:** zero eventos após cutoff; recepção exibida em campo independente.

## 8. Votação após 17h com fila

Eventos de voto computado às 17:13 e 17:29; sem outro contexto. **Esperado:** 2 eventos após cutoff, anotação 'pode ser compatível com fila; não comprova irregularidade', sem score de fraude.

## 9. Relógio adiantado

Equipamento apresenta abertura prevista às 8h, eventos sempre deslocados +60 minutos e referência independente de offset validado.

**Esperado:** `CLOCK_SUSPECT` se não validado; não integrar ranking principal de atividade tardia; opções de visões original/corrigida só quando correção suportada.

## 10. Biometria ambígua

Ciclo com apenas `Ano de nascimento digitado é igual ao do cadastro` e conclusão do voto.

**Esperado:** NUNCA `NO_BIOMETRIC_ENROLLMENT_CONFIRMED` sem outro evento ou documentação que torne a semântica inequívoca.

## 11. Pedido manual não prova execução

Ciclo: solicitação de habilitação manual, reinício, voto computado com classe indefinida.

**Esperado:** não contar 1 manual confirmado; devolver desconhecido/conflitante conforme taxonomia e `reason_code`.

## 12. Duas urnas na seção

Dispositivo A registra 120 eventos distintos, dispositivo B registra 90 eventos distintos após substituição. Um ZIP retransmitido copia todos 120 de A.

**Esperado:** 210 eventos únicos e reconciliação com comparecimento 210, se arquivos forem válidos; não 330.

## 13. Duas pessoas no mesmo segundo

Dois eventos diferentes com mesmo timestamp em arquivos válidos, identidades de linha diferentes. **Esperado:** não colapsar por segundo sem evidência de duplicação.

## 14. Histórico seção mudou

Seção 100 em município A em 2016 e seção 100 em município B em 2020, mesma UF.

**Esperado:** nenhuma associação automática. Códigos iguais não significam mesmas pessoas, escola ou local.

## 15. Apoio eleitoral não implica identidade

Seção registra 50 eventos depois das 17h e maioria dos votos totais para candidato K. **Esperado:** UI **não** afirma que os 50 eventos foram votos para K ou que foram produzidos por eleitor de grupo específico.

## 16. Dados provisórios

No corte de 12/10/2026, solicitar 2026/t2. **Esperado:** `FUTURE`, não '0 voto' nem total definitivo.

## 17. Fuso e regra por pleito

Dois locais em fusos diferentes com votações encerrando no mesmo instante oficial BRT. **Esperado:** comparação de instantes coerente e horas locais diferentes exibidas; 2012 usa regra do ano, não regra 2026.

## 18. Cobertura parcial

100 seções esperadas, somente 27 com logs validados; destas 4 têm eventos após o cutoff.

**Esperado:** informar '4 de 27 seções com logs válidos', cobertura 27/100; não '4% das seções do estado'.

## 19. Download interrompido

Servidor mudou ETag após baixar 3 de 5 blocos. **Esperado:** invalidar `.part` antes de retomar, nunca juntar blocos de versões distintas.

## 20. Fonte adulterada/corrompida

Arquivo recebido diverge de checksum oficial conhecido ou está truncado. **Esperado:** `QUARANTINED`, sem gerar fatos publicáveis.
