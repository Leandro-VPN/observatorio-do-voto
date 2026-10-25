"""Nota de 25/10/2026: o cenário mais perigoso — o que uma operação de compra de votos poderia fazer com a janela até as 19h, o que deixaria nos dados
e qual é o teto numérico, calculado dos resultados do projeto (11 estados, 1º turno de 2026). Gera relatorios/fiscalizacao/notas/NOTA_CENARIO_COMPRA_DE_VOTOS_2026T2.md."""
from pathlib import Path

import pandas as pd

FISC = Path('relatorios/fiscalizacao')
VAR = FISC / 'varredura'
OUT = FISC / 'notas' / 'NOTA_CENARIO_COMPRA_DE_VOTOS_2026T2.md'
CSV = dict(sep=';', decimal=',', low_memory=False)
KEY = ['uf', 'municipality', 'zone', 'voting_place']


def n(x, d=0):
    return f'{x:,.{d}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def main():
    L = pd.read_csv(VAR / 'locais_risco.csv', **CSV)
    H = pd.read_csv(VAR / 'secoes_historico.csv', **CSV)
    S = pd.read_csv(VAR / 'secoes_com_comportamento_por_eleicao.csv', **CSV)
    for df in (L, H, S):
        df['voting_place'] = df.voting_place.astype(str)
    s26 = S[S.eid == 'P2026'].copy()
    s26['real'] = s26.real.astype(str).eq('True')
    m = s26.merge(L[KEY + ['prioridade_observacao', 'secoes_max']], on=KEY, how='left')
    d = pd.read_parquet(FISC / 'secoes_indicadores_P2026.parquet', columns=['uf', 'valid_votes', 'votes_a', 'votes_b', 'after_17_recorded', 'late_interval_median_seconds', 'eligible', 'attendance', 'log_complete', 'share_a'])
    d = d[d.log_complete & (d.eligible >= 50)]
    e = d[d.after_17_recorded >= 20]
    med_int = e.late_interval_median_seconds.median()
    pace = 3600 / med_int
    pace_hi = 3600 / e.late_interval_median_seconds.quantile(.1)
    ausentes, aptos = (d.eligible - d.attendance).sum(), d.eligible.sum()
    ta, tb, late = d.votes_a.sum(), d.votes_b.sum(), d.after_17_recorded.sum()
    pa_tardios = (d.after_17_recorded * d.share_a / 100).sum() / late
    core = H[(H.n_eleicoes_comportamento >= 2) & (H.n_pres_favor_A >= 1)].merge(L[KEY + ['prioridade_observacao']], on=KEY, how='left')
    c26 = core[KEY + ['section']].merge(s26[KEY + ['section', 'after_17_recorded', 'valid_votes', 'eligible', 'share_a', 'cmp_a', 'excess_a_votes']], on=KEY + ['section'], how='inner')
    pa_core = c26.share_a.mean() / 100

    def grp(x):
        r = x[x.real]
        return dict(locais=x.groupby(KEY).ngroups, secoes=len(x), tardios=int(x.after_17_recorded.sum()), manuais17=int(x.after_17_manual_sequence.sum()), reais=len(r), A=int((r.dir == 'A').sum()), B=int((r.dir == 'B').sum()),
                    excA=float(r.excess_a_votes[r.dir == 'A'].sum()), excB=float(-r.excess_a_votes[r.dir == 'B'].sum()), validos=int(x.valid_votes.sum()), aptos=int(x.eligible.sum()), secoes_locais=int(x.drop_duplicates(KEY).secoes_max.sum()))
    G = {k: grp(m[m.prioridade_observacao == k]) for k in ('alta', 'média', 'baixa')}
    alta, media, baixa = G['alta'], G['média'], G['baixa']
    sec_alta = alta['secoes_locais']
    sec_mapa = int(pd.read_csv(FISC / 'mapa_2026_T2/resumo_por_uf.csv', **CSV).secoes_a_checar.sum())
    margem = tb - ta
    T = []
    T.append('# Nota: o cenário mais perigoso — compra de votos com a janela até as 19h, o que deixaria nos dados e qual é o teto\n')
    T.append(f'Gerada em {pd.Timestamp.now():%d/%m/%Y %H:%M} por `scripts/make_nota_cenario_compra.py`, com os indicadores por seção do 1º turno de 2026 em 11 estados (seções elegíveis com log completo) e a varredura por local. '
             'Lado A = PT, lado B = PL. Esta nota raciocina sobre hipóteses: os dados não observam compra de votos, dinheiro, transporte nem intenção; observam horários, habilitações, encerramento e votos por seção. '
             'Nenhuma seção ou local aqui é acusado de nada. Complementa a [nota sobre a extensão até as 19h](NOTA_HORARIO_19H_2026T2.html).\n')
    T.append('## 1. Como uma operação de compra de votos usaria duas horas a mais\n')
    T.append('Compra de votos, nas formas que a Justiça Eleitoral documenta em cassações, não é um eleitor isolado: é logística. Dinheiro ou bens trocados por comparecimento, transporte organizado, cabos eleitorais que levam o eleitor até a seção e conferem que ele foi, '
             'e pressão sobre quem depende de alguém (emprego, benefício, terra). O gargalo dessa operação é o **tempo de levar gente até a urna**. A extensão até as 19h ataca exatamente esse gargalo:\n')
    T.append('- **Duas horas a mais de transporte** depois do horário em que a maioria já votou, quando as filas são curtas e cada veículo descarrega eleitores que votam em minutos.')
    T.append('- **Cobertura legal**: votar às 18h30 passa a ser normal em qualquer seção. O sinal que o projeto usava para destacar seções (votos depois das 17h) deixa de distinguir fila remanescente de mobilização tardia.')
    T.append('- **Fim de dia**: mesários cansados, menos fiscais presentes; é quando a habilitação manual (eleitor liberado sem biometria) tende a ser menos conferida.')
    T.append('- **Decisão no meio do dia**: a operação que já tinha estrutura montada (transporte, listas) ganha duas horas; o eleitor comum que não soube da extensão, não. A vantagem é assimétrica por construção.\n')
    T.append('## 2. O que isso deixaria nos dados (assinaturas que o projeto consegue medir)\n')
    T.append('| Assinatura | O que se mede | Onde | Como separar de mobilização legítima |')
    T.append('|---|---|---|---|')
    T.append('| Pico concentrado de votos entre 17h e 19h em poucos locais, não difuso | votos por hora por seção frente à distribuição do estado | logs do 2º turno (`uf_pipeline.py`) | legítimo tende a ser difuso e proporcional ao eleitorado; operação é concentrada em prédios específicos e recorrentes |')
    T.append(f'| Ritmo de fila cheia até perto do fechamento | mediana do intervalo entre votos após 17h (no 1º turno, {n(med_int)} s, ~{n(pace)} votos/hora por seção) | logs | fila orquestrada mantém intervalos curtos e regulares até o fim; fila espontânea rareia |')
    T.append('| Habilitação manual acima do esperado na janela extra | votos de sequência manual após 19h frente ao esperado por biometria, idade e escolaridade | logs + perfil | liberação manual não é prova de nada; a assinatura é excesso frente às vizinhas, repetido |')
    T.append('| Resultado da seção destoando das vizinhas do mesmo prédio, na direção de um lado só | diferença acima do limiar (≥5 p.p. e z≥2) e direção, nível local | varredura (`make_varredura_locais.py`) | composição explica muito; o que importa é o salto **dentro do prédio** e a recorrência |')
    T.append('| Salto de comparecimento frente ao 1º turno na mesma seção, acima das vizinhas | comparecimento T2 − T1 por seção, contra os pares | boletins de urna (hoje à noite) | legítimo sobe junto com as vizinhas; operação sobe em seções específicas |')
    T.append('| Encerramento muito depois das 19h, sem troca de urna | horário de encerramento no BU | boletins (hoje) | permitido para quem estava na fila às 19h; o sinal é a concentração |')
    T.append('| Recorrência: as mesmas seções em 2022, 2024 e 2026 | histórico por seção | varredura | prédio grande ou bairro explica parte; a direção repetida para o mesmo lado, não |')
    T.append('\nNenhuma assinatura isolada prova compra de votos. A combinação que exige explicação é: **concentração + ritmo cheio até o fim + manual acima do esperado + resultado destoando do prédio para o mesmo lado + recorrência**. '
             'É exatamente o que a pontuação de prioridade da varredura soma, e é por isso que o mapa de fiscalização aponta para esses prédios.\n')
    T.append('## 3. O tamanho do problema, com os números do 1º turno de 2026\n')
    T.append('Seções com comportamento (votação tardia ou manual acima do P99 do estado) no 1º turno de 2026, agrupadas pela prioridade do local na varredura:\n')
    T.append('| Prioridade do local | Locais | Seções com comportamento | Votos após 17h | Manuais após 17h | Diferenças acima do limiar (A / B) | Excesso de votos A | Excesso de votos B | Votos válidos das seções |')
    T.append('|---|---|---|---|---|---|---|---|---|')
    for k, g in G.items():
        T.append(f'| {k} | {n(g["locais"])} | {n(g["secoes"])} | {n(g["tardios"])} | {n(g["manuais17"])} | {n(g["reais"])} ({n(g["A"])} / {n(g["B"])}) | {n(g["excA"])} | {n(g["excB"])} | {n(g["validos"])} |')
    excA_tot, excB_tot = alta['excA'] + media['excA'] + baixa['excA'], alta['excB'] + media['excB'] + baixa['excB']
    T.append(f'\nNos {n(alta["locais"])} locais de prioridade alta, os votos após 17h foram {n(100 * alta["tardios"] / alta["validos"], 1)}% dos votos válidos dessas seções (contra {n(100 * late / d.valid_votes.sum(), 1)}% no conjunto dos 11 estados). '
             f'O "excesso" do lado A (votos acima do que a seção teria se votasse como as vizinhas do prédio) somou {n(alta["excA"])} votos nos locais de prioridade alta e {n(excA_tot)} em todos; o excesso do lado B, {n(excB_tot)}. '
             'São ordens de grandeza do desvio, não contagem de votos comprados: parte disso é composição, acaso e fila real.\n')
    T.append(f'**Núcleo mais sensível**: {n(len(core))} seções com comportamento em 2 ou mais eleições e diferença acima do limiar a favor de A em alguma presidencial; '
             f'{n(len(c26))} delas tiveram comportamento também no 1º turno de 2026, com {n(c26.valid_votes.sum())} votos válidos, {n(c26.after_17_recorded.sum())} votos após 17h, '
             f'lado A em {n(100 * pa_core, 1)}% contra {n(c26.cmp_a.mean(), 1)}% nas vizinhas, e excesso A de {n(c26.excess_a_votes.sum())} votos. '
             f'{n(int(core.prioridade_observacao.eq("alta").sum()))} estão em locais de prioridade alta e {n(int(core.prioridade_observacao.eq("média").sum()))} em média. '
             'Esse núcleo é onde uma operação já existente teria mais a ganhar com duas horas extras, e onde um fiscal tem mais o que ver.\n')
    T.append('## 4. O teto: quantos votos cabem em duas horas\n')
    T.append(f'Uma seção com fila cheia computa cerca de {n(pace)} votos por hora (mediana do intervalo entre votos após 17h no 1º turno, nas seções com 20 ou mais votos tardios; as 10% mais rápidas chegam a {n(pace_hi)}). '
             f'Duas horas extras cabem, portanto, no máximo ~{n(2 * pace)} votos por seção, e isso só se a fila for mantida cheia do início ao fim.\n')
    T.append('| Hipótese de alcance da operação | Seções | Capacidade máxima em 2 h | Votos líquidos para A se os novos votos seguirem o padrão dos tardios do 1º turno | Se seguirem o padrão do núcleo recorrente |')
    T.append('|---|---|---|---|---|')
    for rot, sec in (('todas as seções dos locais de prioridade alta', sec_alta), ('todas as seções a checar do mapa (locais alta e média)', sec_mapa), ('só o núcleo recorrente com direção A', len(c26))):
        cap = sec * 2 * pace
        T.append(f'| {rot} | {n(sec)} | {n(cap)} | {n(cap * (2 * pa_tardios - 1))} | {n(cap * (2 * pa_core - 1))} |')
    T.append(f'\nOs dois padrões: votos após 17h no 1º turno foram {n(100 * pa_tardios, 1)}% para A; o núcleo recorrente, {n(100 * pa_core, 1)}% para A. '
             f'Para comparação, a margem do 1º turno nos 11 estados foi de {n(margem)} votos (B à frente), e o reservatório de abstenção é de {n(ausentes)} eleitores ({n(100 * ausentes / aptos, 1)}% dos aptos).\n')
    T.append('Leitura: mesmo no teto físico, uma operação restrita aos locais que já têm sinal não vira uma margem desse tamanho. O que ela pode fazer é decidir uma disputa nacional apertada (centenas de milhares de votos), ou disputas locais, '
             'e fazê-lo com cobertura legal. O teto só sobe se a operação se espalhar por prédios que hoje não têm sinal nenhum, e aí ela deixa o rastro difuso que a comparação com as vizinhas captura. '
             'O cenário mais perigoso, portanto, não é o da virada aritmética: é o de uma disputa decidida por poucos votos em que as duas horas extras, concentradas onde já havia estrutura, fazem a diferença sem deixar prova individual.\n')
    nA, nB = alta['A'] + media['A'] + baixa['A'], alta['B'] + media['B'] + baixa['B']
    T.append(f'**Os dois lados.** A tabela de teto usa a direção A porque é a dominante nos desvios medidos ({n(nA)} seções acima do limiar a favor de A contra {n(nB)} a favor de B no 1º turno de 2026). '
             'O mecanismo não tem lado: uma operação a favor de B usaria as mesmas duas horas, os mesmos veículos e deixaria as mesmas assinaturas. As seções com desvio para B estão no mesmo mapa e recebem o mesmo checklist.\n')
    T.append('## 5. Por que este é o cenário mais perigoso para a fiscalização, e não só para o resultado\n')
    T.append('- O sinal "votou depois das 17h" perde valor de uma vez: qualquer explicação de fila passa a ser aceita. O projeto precisa mudar a referência para 19h e tratar a janela 17h–19h como objeto próprio.')
    T.append('- A decisão no meio do dia produz aplicação desigual (seções que fecharam às 17h ao lado de seções que ficaram abertas), o que gera ruído legítimo e dificulta separar operação de confusão.')
    T.append('- A observação presencial é o único instrumento que distingue veículo fretado de ônibus urbano, cabo eleitoral de parente, dinheiro de nada. Por isso o checklist do mapa pede o horário em que a seção soube da extensão, fila às 17h e às 19h, manuais observadas e encerramento real.\n')
    T.append('## 6. Protocolo para as próximas 72 horas\n')
    T.append('1. **Hoje à noite, com os boletins** (`bu_capture_all.py` e `analyze_office.py` para 2026 T2): por seção, horário de encerramento, habilitados manualmente (campo do BU) e comparecimento; comparar com o 1º turno na mesma seção e com as vizinhas. Lista 1: seções com salto de comparecimento frente ao T1 acima das vizinhas e encerramento depois das 19h.')
    T.append('2. **Cruzar a lista 1 com a varredura**: seções que já estavam no mapa (prioridade alta ou média, recorrentes, direção A) sobem para o topo; seções novas, sem histórico, ficam numa lista separada para olhar com cautela.')
    T.append('3. **Quando saírem os logs** (dias a semanas): votos por hora entre 17h e 19h e depois das 19h; ritmo; manuais na janela; refazer a varredura com referência 19h e publicar como edição nova, sem substituir a atual.')
    T.append('4. **Encaminhamento**: o que a varredura produz é uma lista de prédios e seções com padrão a explicar. Quem pode pedir explicação é o Ministério Público Eleitoral e os partidos; o material certo para isso é a lista com os números e os relatos de fiscais com horário, nunca a afirmação de que houve compra.\n')
    T.append('**O que esta nota não diz**: que houve ou haverá compra de votos; que a extensão foi feita para isso; quem comprou ou vendeu. **O que ela diz**: onde uma operação desse tipo teria mais a ganhar, quanto no máximo poderia render e como ela apareceria nos dados.\n')
    T.append('## Números de referência\n')
    for k, v in (('Seções elegíveis com log completo, 2026 T1, 11 UFs', len(d)), ('Votos após 17h, 2026 T1', late), ('Parcela de A nos votos após 17h', f'{n(100 * pa_tardios, 1)}%'), ('Intervalo mediano entre votos após 17h (s)', med_int),
                 ('Votos por hora por seção (mediana / P10 do intervalo)', f'{n(pace)} / {n(pace_hi)}'), ('Seções nos locais de prioridade alta', sec_alta), ('Seções a checar no mapa', sec_mapa), ('Núcleo recorrente com direção A e comportamento em 2026 T1', len(c26)),
                 ('Margem B − A no 1º turno, 11 UFs', margem), ('Ausentes no 1º turno, 11 UFs', ausentes)):
        T.append(f'- {k}: {v if isinstance(v, str) else n(v)}')
    OUT.write_text('\n'.join(T), encoding='utf-8')
    print('ok', OUT)


if __name__ == '__main__':
    main()