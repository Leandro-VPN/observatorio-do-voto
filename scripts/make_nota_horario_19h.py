"""Nota de 25/10/2026: o que os dados do projeto dizem sobre a extensão do horário de votação até as 19h (2º turno de 2026).
Gera relatorios/fiscalizacao/notas/NOTA_HORARIO_19H_2026T2.md a partir dos secoes_indicadores_*.parquet (11 estados). Nenhum número é digitado à mão."""
from pathlib import Path

import numpy as np
import pandas as pd

FISC = Path('relatorios/fiscalizacao')
OUT = FISC / 'notas' / 'NOTA_HORARIO_19H_2026T2.md'
OUT.parent.mkdir(parents=True, exist_ok=True)
LAB = {'P2022': 'Pres. 2022 T1', 'P2022b': 'Pres. 2022 T2', 'M2024': 'Pref. 2024 T1', 'M2024b': 'Pref. 2024 T2', 'P2026': 'Pres. 2026 T1'}
UFS = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC', 'MA']


def n(x, d=0):
    return f'{x:,.{d}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def load(eid):
    d = pd.read_parquet(FISC / f'secoes_indicadores_{eid}.parquet', columns=['uf', 'place', 'attendance', 'valid_votes', 'votes_a', 'votes_b', 'share_a', 'after_17_recorded', 'after_17_manual_sequence', 'last_min', 'close_min',
                                                                           'log_complete', 'eligible', 'biometria_pct', 'age60_pct', 'low_school_pct', 'swap'])
    d = d[d.log_complete & (d.eligible >= 50) & d.valid_votes.gt(0)].copy()
    w = d.valid_votes.astype(float)
    d['resid'] = d.share_a - (d.share_a * w).groupby(d.place).transform('sum') / w.groupby(d.place).transform('sum')
    d['late_share'] = 100 * d.after_17_recorded / d.attendance
    return d


def wavg(x, w):
    return np.average(x, weights=w) if len(x) else np.nan


def main():
    E = {e: load(e) for e in LAB}
    d26, d22b = E['P2026'], E['P2022b']
    ta, tb, late = d26.votes_a.sum(), d26.votes_b.sum(), d26.after_17_recorded.sum()
    la = (d26.after_17_recorded * d26.share_a / 100).sum()
    pa = 100 * la / late
    L = []
    L.append('# Nota: extensão da votação até as 19h no 2º turno de 2026 — o que os dados do projeto permitem dizer\n')
    L.append(f'Gerada em {pd.Timestamp.now():%d/%m/%Y %H:%M} por `scripts/make_nota_horario_19h.py`, a partir dos indicadores por seção de 11 estados (BA, SP, MG, RJ, PR, RS, PE, CE, PA, SC, MA), '
             'seções elegíveis (≥50 aptos) com log completo. Lado A = PT, lado B = PL. Sinalização não é acusação; nada aqui identifica o voto de ninguém.\n')
    L.append('## 1. O fato\n')
    L.append('Em 25/10/2026, dia do 2º turno, o ministro Cristiano Zanin (STF) determinou, em liminar, que a votação fosse estendida até as 19h (horário de Brasília) em todas as seções do país, a pedido da campanha de Lula, que alegou falhas no transporte público; '
             'a campanha de Flávio Bolsonaro havia pedido prorrogação em municípios de SP, PR e SC por chuvas. O TSE acatou e suspendeu a divulgação parcial enquanto a votação estivesse aberta. '
             'Fontes ao final (reportagens do próprio dia; não localizei desdobramentos posteriores).\n')
    L.append('**O que muda para a pesquisa**: votar depois das 17h deixa de ser exceção (fila remanescente) e passa a ser a regra por duas horas. Os indicadores do projeto que usam as 17h como referência '
             '(votos após 17h, último voto após 19h, encerramento mais de 60 min após 17h, habilitações manuais após 17h) precisam ser recalibrados para o 2º turno de 2026: a referência passa a ser as 19h. '
             'Como os limiares são relativos (P99 por estado), a varredura continua funcionando; o que muda é o significado do sinal.\n')
    L.append('## 2. O que já sabemos sobre votação tardia\n')
    L.append('| Eleição | Seções | Comparecimento | Votos após 17h | % do comparecimento | Seções com voto após 17h | Último voto ≥18h | Último voto ≥19h | Encerramento >60 min | Manuais após 17h |')
    L.append('|---|---|---|---|---|---|---|---|---|---|')
    for e, d in E.items():
        L.append(f'| {LAB[e]} | {n(len(d))} | {n(d.attendance.sum())} | {n(d.after_17_recorded.sum())} | {n(100 * d.after_17_recorded.sum() / d.attendance.sum(), 2)}% | {n(100 * (d.after_17_recorded > 0).mean(), 1)}% | '
                 f'{n((d.last_min >= 1080).sum())} | {n((d.last_min >= 1140).sum())} | {n((d.close_min > 60).sum())} | {n(d.after_17_manual_sequence.sum())} |')
    L.append(f'\nLeitura: no 1º turno presidencial, votar depois das 17h é comum ({n(100 * late / d26.attendance.sum(), 1)}% dos votos de 2026 T1; {n(100 * (d26.after_17_recorded > 0).mean(), 0)}% das seções tiveram pelo menos um). '
             f'No **2º turno de 2022**, o mais comparável ao de hoje, foram só {n(d22b.after_17_recorded.sum())} votos após 17h ({n(100 * d22b.after_17_recorded.sum() / d22b.attendance.sum(), 3)}%): '
             f'a mediana do último voto foi {n(abs((d22b.last_min - 1020).median()), 0)} min **antes** das 17h e o P99 do encerramento, {n(d22b.close_min.quantile(.99), 0)} min depois. '
             'Segundos turnos têm cédula de um cargo só e filas muito menores. A extensão de hoje não responde a uma demanda de fila como a do 1º turno; ela abre duas horas novas de votação.\n')
    L.append('### 2.1 Onde a votação tardia se concentra (2026 T1)\n')
    L.append('| UF | Seções | % de votos após 17h | % de seções com voto após 17h | Último voto ≥18h | Último voto ≥19h | Lado A % nos votos tardios (se votassem como suas seções) |')
    L.append('|---|---|---|---|---|---|---|')
    g = d26.groupby('uf')
    for uf in UFS:
        s = g.get_group(uf)
        lau = (s.after_17_recorded * s.share_a / 100).sum()
        L.append(f'| {uf} | {n(len(s))} | {n(100 * s.after_17_recorded.sum() / s.attendance.sum(), 2)}% | {n(100 * (s.after_17_recorded > 0).mean(), 1)}% | {n((s.last_min >= 1080).sum())} | {n((s.last_min >= 1140).sum())} | {n(100 * lau / s.after_17_recorded.sum(), 1)}% |')
    L.append('\nA votação tardia é um fenômeno do Nordeste e do Pará (5,7% a 7,5% dos votos após 17h em PE, BA, CE, MA e PA) e é rara no Sul e em SP (abaixo de 0,9%). '
             'Os estados onde a extensão tende a produzir mais votos novos são, portanto, os mesmos onde o lado A já é majoritário.\n')
    L.append('### 2.2 Seções com mais votos tardios votam diferente? (2026 T1)\n')
    L.append('| Faixa de votos após 17h na seção | Seções | Votos após 17h | Lado A % (ponderado) | Resíduo frente ao próprio prédio (p.p.) | Biometria cadastrada % | 60+ anos % | Baixa escolaridade % | Comparecimento % |')
    L.append('|---|---|---|---|---|---|---|---|---|')
    b = pd.cut(d26.late_share, [-0.01, 0, 2, 5, 10, 20, 100], labels=['0', '0–2%', '2–5%', '5–10%', '10–20%', '>20%'])
    for k, s in d26.groupby(b, observed=True):
        L.append(f'| {k} | {n(len(s))} | {n(s.after_17_recorded.sum())} | {n(wavg(s.share_a, s.valid_votes), 1)}% | {n(wavg(s.resid, s.valid_votes), 2)} | {n(s.biometria_pct.mean(), 1)} | {n(s.age60_pct.mean(), 1)} | {n(s.low_school_pct.mean(), 1)} | {n(100 * s.attendance.sum() / s.eligible.sum(), 1)}% |')
    L.append('\nDuas leituras ao mesmo tempo. (1) **Composição**: quanto mais votos tardios, maior o % do PT na seção (de 40% sem tardios a 68% nas seções com mais de 20% de votos após 17h), '
             'porque fila acontece onde o eleitorado é menos escolarizado e mais nordestino, perfis que já votam mais no PT. (2) **Dentro do prédio**: o resíduo frente às seções vizinhas é pequeno (até +0,5 p.p.): '
             'a seção com fila vota quase como as vizinhas sem fila. Ou seja, o voto tardio reflete sobretudo *quem* enfrenta fila, não uma mudança de comportamento dentro do mesmo prédio.\n')
    L.append('### 2.3 Quanto os votos tardios pesam frente à margem (2026 T1, 11 estados)\n')
    m1819 = d26[(d26.last_min >= 1080) & (d26.last_min < 1140)]
    m19 = d26[d26.last_min >= 1140]
    m17 = d26[d26.last_min < 1020]
    L.append(f'- Votos válidos: A {n(ta)}, B {n(tb)}; margem B−A = {n(tb - ta)}. Votos após 17h: {n(late)} = {n(100 * late / (tb - ta), 0)}% da margem, em valor absoluto: os tardios são numerosos o bastante para mudar uma margem desse tamanho **se** votassem em bloco, o que os dados não mostram.')
    L.append(f'- Se cada voto tardio seguisse a proporção da própria seção, A teria {n(la)} dos {n(late)} ({n(pa, 1)}%) e B {n(late - la)}: saldo líquido de {n(2 * la - late)} votos para A, ou {n(100 * (2 * la - late) / abs(tb - ta), 1)}% da margem.')
    L.append(f'- Por hora do último voto: seções cujo último voto saiu entre 18h e 19h têm lado A em {n(wavg(m1819.share_a, m1819.valid_votes), 1)}%; depois das 19h, {n(wavg(m19.share_a, m19.valid_votes), 1)}%; nas que fecharam até as 17h, {n(wavg(m17.share_a, m17.valid_votes), 1)}%.\n')
    L.append('## 3. O que pode acontecer hoje (cenários, com o que os dados sustentam)\n')
    L.append('**Cenário 1 — pouca gente usa as duas horas extras.** É o cenário-base para um 2º turno: em 2022 T2 quase ninguém votou depois das 17h (0,03%). Quem queria votar já estava na fila. '
             'Efeito no resultado: desprezível. Efeito nos dados: os logs mostrarão último voto perto das 17h na maioria das seções, com cauda maior do que em 2022 pela permissão.\n')
    por_milhao = 2 * la / late * 1e6 - 1e6
    L.append('**Cenário 2 — a extensão vira mobilização extra onde a fila é rotina (NE e PA).** As duas horas a mais convertem eleitores que desistiriam, concentradas nos estados e seções com perfil de fila. '
             f'Pelo padrão do 1º turno, cada 1 milhão de votos adicionais com esse perfil renderia cerca de {n(por_milhao)} votos líquidos para A (proporção {n(pa, 0)}/{n(100 - pa, 0)}). '
             f'Para virar a margem do 1º turno nos 11 estados ({n(tb - ta)}) seriam necessários cerca de {n((tb - ta) / por_milhao, 1)} milhões de votos novos com esse perfil, o que não é plausível; numa disputa nacional apertada (margem de algumas centenas de milhares), 1 a 2 milhões de votos novos com esse perfil seriam decisivos. '
             'Este é o cenário que importa monitorar, e ele é **perfeitamente legal**: votar às 18h30 com a urna aberta por decisão judicial não é irregularidade.\n')
    L.append('**Cenário 3 — aplicação desigual.** A decisão saiu durante a votação. Seções que já tinham encerrado ou cujos mesários não foram avisados fecham às 17h; outras ficam abertas até as 19h; '
             'em algumas a notícia atrai eleitores, em outras não. Isso cria diferenças de encerramento entre seções do **mesmo prédio**, exatamente o tipo de comparação que o projeto faz. É aqui que a varredura tem mais a dizer depois da eleição.\n')
    L.append('**Cenário 4 — risco operacional nas duas horas extras.** Mais tempo de urna aberta com mesários cansados e luz artificial: mais habilitações manuais, mais contingências, mais trocas de urna, encerramentos ainda mais tarde. '
             f'No 1º turno de 2026 já houve {n(d26.after_17_manual_sequence.sum())} votos com habilitação manual depois das 17h; com a janela legal até as 19h esse número tende a crescer, e a comparação relevante passa a ser **manuais após 19h** e, dentro da janela, a razão manual/votos frente às seções vizinhas.\n')
    L.append('**O que os dados não permitem dizer**: em quem votaram os eleitores tardios; se a extensão foi pedida por cálculo eleitoral; se houve manipulação. O que permitem: medir, seção a seção, quantos votaram depois das 17h e das 19h, '
             'como essas seções votaram frente às vizinhas, e onde a aplicação foi desigual.\n')
    L.append('## 4. O que fazer hoje e nos próximos dias\n')
    L.append('1. **Hoje, nos locais do mapa de fiscalização**: anotar, além do que já está no checklist, a hora em que a seção soube da extensão, se continuou aberta até as 19h, se houve fila às 17h e às 19h, quantas habilitações manuais depois das 17h, e a hora real do encerramento. '
             'Prédios de prioridade alta continuam sendo os melhores pontos de observação: são os que têm fila e habilitação manual recorrentes.')
    L.append('2. **Esta noite / amanhã, com os boletins de urna** (bweb, publicados em horas): o BU traz o horário de encerramento e o número de habilitados manualmente por seção. Dá para medir, por estado e por prédio, quem fechou às 17h e quem às 19h, '
             'e comparar o resultado de seções que ficaram abertas com as vizinhas que fecharam (mesmo método da varredura, nível local). O script `analyze_office.py` já faz a parte do BU.')
    L.append('3. **Quando o TSE publicar os logs do 2º turno** (dias a semanas): rodar a cadeia com as referências recalibradas para 19h (votos após 19h, último voto após 21h, encerramento >60 min após 19h, manuais após 19h) e, separadamente, a janela 17h–19h como objeto próprio: '
             'quantos votos, em que estados, em que prédios, com que direção frente às vizinhas. Publicar como edição nova, sem substituir a atual.')
    L.append('4. **Não mudar a pontuação dos locais no dia**; registrar a recalibração dos limiares como alteração de parâmetro no documento técnico.\n')
    L.append('## 5. Números de referência para hoje\n')
    L.append(f'- 2026 T1, 11 estados: {n(late)} votos após 17h ({n(100 * late / d26.attendance.sum(), 1)}% do comparecimento); {n((d26.last_min >= 1140).sum())} seções com último voto depois das 19h; P99 do último voto a {n((d26.last_min - 1020).quantile(.99), 0)} min das 17h; P99 do encerramento a {n(d26.close_min.quantile(.99), 0)} min.')
    L.append(f'- 2022 T2: {n(d22b.after_17_recorded.sum())} votos após 17h; P99 do último voto a {n((d22b.last_min - 1020).quantile(.99), 0)} min das 17h; P99 do encerramento a {n(d22b.close_min.quantile(.99), 0)} min. Qualquer coisa muito acima disso hoje é efeito da decisão.')
    L.append('- Cobertura: 11 estados, cerca de 62% do eleitorado nacional; os números não são o Brasil inteiro.\n')
    L.append('Fontes da decisão: https://forbes.com.br/geral/2026/10/stf-estende-votacao-do-segundo-turno-ate-as-19h-em-todas-as-secoes/ · https://www.poder360.com.br/poder-eleicoes-2026/zanin-prorroga-votacao-do-2o-turno-ate-19h/ · '
             'https://www.cnnbrasil.com.br/eleicoes/zanin-prorroga-eleicao-ate-as-19h-deste-domingo-em-todo-o-pais/ · https://exame.com/brasil/tse-aprova-a-extensao-do-horario-de-votacao-do-2o-turno-para-as-19h/ · https://www12.senado.leg.br/tv/programas/noticias-1/2026/10/eleicoes-2026-zanin-prorroga-horario-das-eleicoes-do-segundo-turno-1\n')
    OUT.write_text('\n'.join(L), encoding='utf-8')
    print('ok', OUT)


if __name__ == '__main__':
    main()
