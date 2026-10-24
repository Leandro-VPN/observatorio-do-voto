# Plano de análise eleitoral — versão 1

## Natureza do registro

Este plano fixa as decisões antes dos novos testes de associação. Não constitui pré-registro externo nem independente de todos os dados: os totais por candidato e a reconciliação log–BU da Bahia/2022/T2 já foram examinados. Esse piloto é exploratório. Resultados anteriores não serão usados para escolher limiares, partidos, localidades ou hipóteses favoráveis. A assinatura SHA-256 e a data UTC ficam em `plano-v1-registro.json`; alterações posteriores exigem outra versão, justificativa e análise de sensibilidade.

## Universo e perguntas

Presidente e governador, separados por disputa; prioridade à comparação presidencial pedida pelo usuário. Anos 2014, 2018 e 2022: ambos os turnos; 2026: somente primeiro turno. Governador sem segundo turno será registrado como não aplicável. Os dez maiores eleitorados serão determinados pelo total oficial de eleitores de cada ano, antes de examinar os indicadores; a composição não será presumida constante. Referências nacionais exigem cobertura nacional, não apenas os dez estados ou Norte/Nordeste.

H0: após os controles obrigatórios, a proporção de votos válidos de cada partido não difere entre unidades sinalizadas e unidades comparáveis. H1: há diferença que se repete na mesma direção para o mesmo partido em eleições sucessivas. Testes bilaterais, alfa 0,05, apresentação de todos os efeitos, inclusive contrários a H1. Resultado descritivo de quem ganhou não é teste de favorecimento.

Partido é o registrado na candidatura daquele ano. Não agregar coligações ou campos políticos. Mudança de partido de candidato não conta como continuidade partidária; ausência de candidatura não é efeito zero. Renomeações, fusões e incorporações requerem documentação, sem junção automática.

## Unidades, denominadores e exclusões

Hierarquia: UF, município, zona e seção/unidade agregada. Zona estadual usa UF+zona; município+zona é um recorte distinto, pois uma zona pode abranger municípios diferentes. Não somar seções entre cargos ou turnos como se fossem locais distintos. Preservar código e nome municipal, local de votação quando disponível e identificadores originais.

Excluir do universo de referência/sinalização ZZ, seções especiais, trânsito e unidades com menos de 50 aptos. Reportá-las separadamente. Situação desconhecida impede classificação confirmada; não equivale a seção comum. Agregações exigem mapa oficial: somar aptos das componentes uma única vez, conferir o denominador do BU e evitar duplicar a unidade receptora. Divergências não serão corrigidas por suposição.

Comparecimento é votantes/aptos; média ponderada territorial é soma(votantes)/soma(aptos). Também reportar mediana das taxas de seção municipal, estadual e nacional. Votos válidos são os votos nominais dos candidatos na disputa; brancos/nulos não entram nesse denominador. Não confundir comparecimento de presidente com o de governador, nem voto concluído no log com um voto para cada cargo.

## Indicadores fixos

**A — comparecimento elevado:** z = (taxa − mediana estadual)/MAD estadual, usando MAD bruto, sem fator 1,4826. A=1 se z>3 e taxa−mediana municipal≥0,10. MAD=0 torna o indicador indefinido. Mostrar diferenças em pontos percentuais contra médias ponderadas estadual e nacional, além das medianas. Calcular limiares somente no universo elegível do mesmo ano/turno/cargo; não usar médias de amostra como nacionais.

**B — votos concluídos após o horário previsto:** contar somente o evento de voto computado, estritamente posterior ao horário de referência. Até 2018, regra local documentada; 2022/2026, regra de Brasília e convenção do relógio verificadas por fonte oficial e configuração. Registrar horário previsto, encerramento efetivo, último voto, reversões/ajustes do relógio e qualidade temporal. Não inferir ajuste a partir de uma abertura presumida às 8h. Ausência de evidência temporal suficiente produz B indisponível, não zero. Bahia e Brasília terem o mesmo fuso em 2022 resolve a conversão nominal, mas não comprova a integridade de cada relógio.

B=1 quando proporção pós-horário>P99 estadual e quantidade≥20; percentil por interpolação linear (quantile_cont), no universo elegível de logs reconciliados e temporalmente válidos. Registrar votos nos 30 minutos anteriores, mediana e desvio-padrão amostral dos intervalos pós-horário. Menos de dois intervalos: desvio indisponível. Mediana<40s e desvio<10s é descrição secundária, não um novo teste confirmatório. Abertura atrasada>15min, substituição, contingência e agregação são controles/explicações operacionais.

**C — habilitação manual:** somente onde identificação biométrica estava ativa, conforme fonte oficial daquele pleito. Cadastro biométrico não prova uso ativo. Autorização normal pelo mesário, solicitação de dado pessoal e assinatura no caderno não equivalem automaticamente a confirmação de habilitação manual. Validar a sequência de eventos, cancelamentos, tentativas repetidas e voto concluído com documentação e exemplos técnicos; não usar uma frase hipotética de confirmação como taxonomia validada.

Proporção manual = votantes com sequência manual confirmada/votantes no log. Esperado por regressão linear ponderada por votantes, dentro de UF/ano/turno, sobre proporção sem cadastro biométrico, idades acima de 60 e de 70 anos, proporções das categorias oficiais de escolaridade e modelo de urna categórico. Omitir uma categoria de referência, definida pela ordem do código oficial, para evitar colinearidade. Predições não serão truncadas; reportar as fora de [0,1] e coeficientes. Faixas agregadas que não separam exatamente >60/>70 não permitem inventar essa separação: exigir dado compatível ou registrar emenda explícita antes dos testes. C=1 se resíduo>P99 estadual e resíduo≥0,10. Controles essenciais ausentes impedem C confirmado.

**D — coincidência:** B∩C e A∩B∩C, somente no universo comum com todos os componentes válidos. Esperado descritivo sob independência: N×pB×pC ou N×pA×pB×pC, estimando as proporções nesse mesmo universo. Não assumir prevalência de 1% para A ou C. Contar votos simultaneamente tardios e manuais pela sequência técnica da mesma sessão de votação. Não associar essa sequência a candidato ou identidade de eleitor. Arquivos derivados não conterão identificadores pessoais de eleitores.

## Comparação de resultados e testes

Para cada território, publicar vencedor, votos válidos de todos os candidatos/partidos, percentual do vencedor e margem entre primeiro e segundo colocados em pontos percentuais, tanto no conjunto quanto nas unidades B+C. Empates serão explícitos. No primeiro turno o denominador inclui todos os candidatos. A margem descritiva entre vencedores possivelmente diferentes não será tratada como efeito partidário: o efeito compara a participação do mesmo partido no sinalizado e no controle.

Modelo principal: regressão linear da proporção de votos válidos do partido, ponderada por aptos, com erros agrupados por UF+zona. Dois modelos separados: indicadores contínuos A/B/C e flags A/B/C, evitando incluir simultaneamente versões redundantes. Ajustes obrigatórios: aptos, agregação, cadastro biométrico, modelo de urna, idade, escolaridade, urbano/rural, mesorregião, substituição, abertura atrasada e contingência. Reportar versão sem ajustes e versão ajustada; efeitos fixos municipais como robustez. Dados faltantes não serão preenchidos por zero. Modelo principal indisponível se faltar controle obrigatório, houver matriz singular ou menos de 30 zonas independentes; registrar motivo. Resultados sem ajustes não substituem os ajustados.

Pareamento por indicador A, B, C, B+C e A+B+C: controle elegível não sinalizado nesse indicador; 1:1 com reposição, mesmo município, depois mesma zona, depois mesma mesorregião, sempre dentro de UF/pleito/cargo. Padronizar aptos, idade>60, biometria e proporções de escolaridade pela média/desvio do universo elegível; coordenada constante removida e documentada. Caliper máximo de 0,25 desvio-padrão em cada coordenada; dentre candidatos válidos, menor distância euclidiana, desempate por chave territorial. Sem par: não imputar. Reportar cobertura, reutilização, nível geográfico, desequilíbrios padronizados antes/depois e efeito restrito ao conjunto pareado. Esse efeito não representa automaticamente todas as unidades sinalizadas.

IC95%: bootstrap de 2.000 reamostragens por zona, semente 20261016, recalculando estimadores e pareamento em cada réplica; controles repetidos mantêm dependência com sua zona. Publicar número de réplicas válidas; menos de 95% válidas torna IC indisponível. Para diferenças pareadas com municípios/zonas cruzados, reamostrar o universo de zonas e refazer o pareamento, sem tratar pares como independentes.

Família BH única, registrada antes dos testes: todas as combinações planejadas de UF elegível no ano, pleito, cargo, partido oficialmente concorrente e coeficiente A/B/C nos modelos contínuo/flags ajustados, mais as cinco diferenças partidárias pareadas. Registrar a lista e seu hash após levantar a composição oficial, antes de ajustar modelos. Testes indisponíveis permanecem na lista e entram conservadoramente como p=1 apenas no cálculo de multiplicidade; saída p/efeito permanece nula, com motivo. q≤0,05 é o critério; não corrigir apenas resultados selecionados ou apenas o piloto. Modelos sem ajuste, efeitos fixos e diagnósticos serão marcados secundários, sem substituição oportunista do principal. O piloto terá resultados exploratórios separados da família confirmatória de dados não examinados.

## Persistência

Mesma chave textual não garante mesma unidade física/eleitorado. Exigir correspondência documental entre anos; separar seção mantida, renumerada, rezoneada, agregada e sem correspondência. Publicar cobertura por par de eleições. Contar recorrência em 3+ pleitos e, separadamente, em 3+ anos; os dois turnos do mesmo ano não são réplicas independentes.

Linha de base de independência usa probabilidades observadas por pleito no universo historicamente comparável. Permutação de 2.000 repetições, semente 20261016, dentro de município e com vetor dos turnos do mesmo ano movimentado conjuntamente para preservar dependência intranual. Municípios sem unidades permutáveis são reportados. Comparar também persistência de controles estruturais. Testes de persistência constituem família secundária separada, BH por todos os indicadores/UF planejados; não reivindicar confirmação histórica antes da validação das correspondências.

## Entregas e sequência

1. Piloto BA/2022/T2: validar taxonomia, tempo, identidade, exclusões, denominadores, controles e pareamento; apresentar resultados e lacunas para revisão antes da expansão, conforme pedido original.
2. Inventário oficial por ano/UF e ranking dos eleitorados; coletar só membros necessários por HTTP Range, com retomada, hash e cache. Indisponibilidade de Range não autoriza baixar arquivo nacional inteiro automaticamente.
3. Tabelas UF/município/zona/seção: A/B/C/D, quantidades observadas/esperadas, volume tardio+manual, vencedores, margens, controles, efeitos, IC/q, cobertura, exclusões, divergências e recorrência. Um campo indisponível é nulo com motivo, nunca zero.
4. Resultados favoráveis e contrários a H1 recebem o mesmo destaque. Votação após o horário pode decorrer de fila; habilitação manual pode decorrer de falha biométrica. Nenhum desses indicadores isoladamente prova irregularidade, fraude ou autoria.

## Evidência normativa consultada

- TSE, horário unificado em 2022: https://www.tse.jus.br/comunicacao/noticias/2022/Setembro/faltam-22-dias-horario-de-votacao-sera-unificado-em-todo-o-pais-nas-eleicoes-gerais-de-2022-102950/
- TSE, Resolução 23.669/2021, regras da votação de 2022: https://www.tse.jus.br/legislacao/compilada/res/2021/resolucao-no-23-669-de-14-de-dezembro-de-2021
- Manual do mesário 2022, documento a conferir para a taxonomia: https://www.justicaeleitoral.jus.br/eleicoes/mesario/assets/arquivos/manual-do-mesario-2022-digital.pdf
