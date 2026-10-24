"""Section-level history of late voting / excess mesário habilitation across elections, compared with neighbouring sections without the behaviour,
aggregated to voting place, zone and city, with a priority list for oversight (2026 2nd round and later).

Behaviour (per election with logs): LATE = late-vote share > state P99 (≥20) OR last vote ≥19h OR closed >60 min without swap; MANUAL = mesário manual habilitation above expected (P99)
OR ≥10 manual habilitations after 17h. Comparison group = other sections of the same voting place without the behaviour; if none, sections of the same municipality without it.
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M
import make_closing_swaps_study as X

SRC = Path('relatorios/fiscalizacao')
OUT = Path('relatorios/fiscalizacao/historico')
OUT.mkdir(parents=True, exist_ok=True)
KEY = X.KEY
n = X.n
ELECS = [('P2022', 'Pres 2022 T1'), ('P2022b', 'Pres 2022 T2'), ('M2024', 'Pref 2024 T1'), ('P2026', 'Pres 2026 T1')]
BIG = 10.0   # p.p.


def wavg(x, w):
    x, w = np.asarray(x, float), np.asarray(w, float)
    ok = np.isfinite(x) & np.isfinite(w)
    return np.average(x[ok], weights=w[ok]) if ok.any() and w[ok].sum() > 0 else np.nan


def per_election(eid):
    d = pd.read_parquet(SRC / f'secoes_indicadores_{eid}.parquet')
    d = d[(d.eligible >= 50) & d.valid_votes.gt(0)].copy()
    d['LATE'] = d.f_late | d.f_last19 | d.f_close
    d['MANUAL'] = d.f_manual | d.f_manual_late
    d['BEH'] = d.LATE | d.MANUAL
    d['winner_ab'] = np.where(d.share_a > d.share_b, 'A', np.where(d.share_b > d.share_a, 'B', 'empate'))
    # comparison groups among non-behaviour sections
    clean = d[~d.BEH]
    gp = clean.groupby('place').apply(lambda g: pd.Series(dict(cmp_place_n=len(g), cmp_place_a=wavg(g.share_a, g.valid_votes), cmp_place_b=wavg(g.share_b, g.valid_votes))), include_groups=False)
    gm = clean.groupby('mun').apply(lambda g: pd.Series(dict(cmp_mun_n=len(g), cmp_mun_a=wavg(g.share_a, g.valid_votes), cmp_mun_b=wavg(g.share_b, g.valid_votes))), include_groups=False)
    d = d.join(gp, on='place').join(gm, on='mun')
    use_place = d.cmp_place_n.fillna(0) >= 1
    d['cmp_level'] = np.where(use_place, 'local', 'município')
    d['cmp_n'] = np.where(use_place, d.cmp_place_n, d.cmp_mun_n)
    d['cmp_a'] = np.where(use_place, d.cmp_place_a, d.cmp_mun_a)
    d['cmp_b'] = np.where(use_place, d.cmp_place_b, d.cmp_mun_b)
    d['cmp_winner'] = np.where(d.cmp_a > d.cmp_b, 'A', np.where(d.cmp_b > d.cmp_a, 'B', 'empate'))
    d['diff_a'] = d.share_a - d.cmp_a
    d['big'] = d.diff_a.abs() >= BIG
    d['excess_a_votes'] = d.diff_a / 100 * d.valid_votes
    d['eid'] = eid
    return d


def main():
    E = {eid: per_election(eid) for eid, _ in ELECS}
    beh = pd.concat([d[d.BEH] for d in E.values()], ignore_index=True)
    cols = ['eid', 'uf', 'municipality', 'municipality_name', 'zone', 'section', 'voting_place', 'place_name', 'eligible', 'attendance', 'LATE', 'MANUAL', 'score',
            'after_17_recorded', 'late_share', 'last_vote', 'close_min', 'manual_sequence_votes', 'manual_resid', 'after_17_manual_sequence', 'swap', 'contingency',
            'cand_a', 'share_a', 'cand_b', 'share_b', 'winner_ab', 'winner_party', 'cmp_level', 'cmp_n', 'cmp_a', 'cmp_b', 'cmp_winner', 'diff_a', 'big', 'excess_a_votes']
    beh = beh[[c for c in cols if c in beh]]
    # section history (wide)
    hist = None
    for eid, lab in ELECS:
        d = E[eid]
        h = d[KEY + ['uf', 'BEH', 'LATE', 'MANUAL', 'winner_ab', 'cmp_winner', 'diff_a', 'big', 'share_a', 'after_17_recorded', 'after_17_manual_sequence']].copy()
        h.columns = KEY + ['uf'] + [f'{c}_{eid}' for c in ['BEH', 'LATE', 'MANUAL', 'winner_ab', 'cmp_winner', 'diff_a', 'big', 'share_a', 'late', 'manual_late']]
        hist = h if hist is None else hist.merge(h, on=KEY + ['uf'], how='outer')
    names = pd.concat([d[KEY + ['uf', 'municipality_name', 'voting_place', 'place_name']] for d in E.values()]).drop_duplicates(KEY + ['uf'], keep='last')
    hist = hist.merge(names, on=KEY + ['uf'], how='left')
    be = [f'BEH_{e}' for e, _ in ELECS]
    hist['n_eleicoes_comportamento'] = hist[be].fillna(False).sum(axis=1)
    hist['n_eleicoes_pres_comportamento'] = hist[['BEH_P2022', 'BEH_P2022b', 'BEH_P2026']].fillna(False).sum(axis=1)
    pres_big = [(f'big_{e}', f'diff_a_{e}', f'BEH_{e}') for e in ['P2022', 'P2022b', 'P2026']]
    hist['n_pres_dif_alta_favor_A'] = sum(((hist[b].fillna(False)) & (hist[dcol] > 0) & hist[bh].fillna(False)).astype(int) for b, dcol, bh in pres_big)
    hist['n_pres_dif_alta_favor_B'] = sum(((hist[b].fillna(False)) & (hist[dcol] < 0) & hist[bh].fillna(False)).astype(int) for b, dcol, bh in pres_big)
    hist['dif_media_pres_quando_comportamento'] = hist.apply(lambda r: np.nanmean([r[f'diff_a_{e}'] for e in ['P2022', 'P2022b', 'P2026'] if r.get(f'BEH_{e}') is True or r.get(f'BEH_{e}') == True]) if r.n_eleicoes_pres_comportamento else np.nan, axis=1)
    hist['votos_tardios_total'] = hist[[f'late_{e}' for e, _ in ELECS]].fillna(0).sum(axis=1)
    hist['manuais_apos_17h_total'] = hist[[f'manual_late_{e}' for e, _ in ELECS]].fillna(0).sum(axis=1)
    hist = hist[hist.n_eleicoes_comportamento >= 1].copy()
    # priority for 2026 T2: behaviour in 2026 T1 and (recurrent or big diff)
    prio = hist[(hist.BEH_P2026 == True) & ((hist.n_eleicoes_comportamento >= 2) | (hist.big_P2026 == True))].copy()
    prio['prioridade'] = np.where(prio.n_eleicoes_comportamento >= 3, 'alta', np.where((prio.n_eleicoes_comportamento == 2) | (prio.big_P2026 == True), 'média', 'baixa'))
    prio = prio.sort_values(['n_eleicoes_comportamento', 'n_pres_dif_alta_favor_A', 'votos_tardios_total'], ascending=False)
    # aggregates
    def agg(df, keys, label):
        g = df.groupby(keys).agg(secoes_com_comportamento=('section', 'size'), recorrentes_2plus=('n_eleicoes_comportamento', lambda x: int((x >= 2).sum())),
                                 recorrentes_3plus=('n_eleicoes_comportamento', lambda x: int((x >= 3).sum())), dif_alta_favor_A=('n_pres_dif_alta_favor_A', 'sum'),
                                 dif_alta_favor_B=('n_pres_dif_alta_favor_B', 'sum'), dif_media_pres=('dif_media_pres_quando_comportamento', 'mean'),
                                 votos_tardios=('votos_tardios_total', 'sum'), manuais_apos_17h=('manuais_apos_17h_total', 'sum')).reset_index()
        g['nivel'] = label
        return g.sort_values(['recorrentes_3plus', 'recorrentes_2plus', 'secoes_com_comportamento'], ascending=False)
    cities = agg(hist, ['uf', 'municipality', 'municipality_name'], 'cidade')
    places = agg(hist, ['uf', 'municipality_name', 'zone', 'voting_place', 'place_name'], 'local')
    zones = agg(hist, ['uf', 'municipality_name', 'zone'], 'zona')
    # totals per election for the report
    tots = []
    for eid, lab in ELECS:
        d = E[eid]
        b = d[d.BEH]
        tots.append(dict(eleicao=lab, secoes=len(d), com_comportamento=len(b), tardia=int(d.LATE.sum()), manual=int(d.MANUAL.sum()), comparacao_local=int((b.cmp_level == 'local').sum()),
                         comparacao_municipio=int((b.cmp_level == 'município').sum()), mesmo_vencedor=100 * (b.winner_ab == b.cmp_winner).mean(), vencedor_difere=int((b.winner_ab != b.cmp_winner).sum()),
                         dif_media=wavg(b.diff_a, b.valid_votes), dif_alta=int(b.big.sum()), dif_alta_favor_A=int((b.big & (b.diff_a > 0)).sum()), dif_alta_favor_B=int((b.big & (b.diff_a < 0)).sum()),
                         excesso_A_votos=float(b.excess_a_votes.sum()), votos_tardios=int(b.after_17_recorded.fillna(0).sum()),
                         clean_big_rate=100 * (d[~d.BEH].diff_a.abs() >= BIG).mean() if (~d.BEH).any() else np.nan))
    T = pd.DataFrame(tots)
    # exports
    beh.round(3).to_csv(OUT / 'secoes_com_comportamento_por_eleicao.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    hist.round(3).to_csv(OUT / 'historico_secoes.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    prio.round(3).to_csv(OUT / 'prioridade_2026_T2.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    for nm, df in (('cidades', cities), ('locais', places), ('zonas', zones), ('resumo_por_eleicao', T)):
        df.round(3).to_csv(OUT / f'{nm}.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    for uf in X.ORDER:
        with pd.ExcelWriter(OUT / f'FISCALIZACAO_{uf}.xlsx', engine='xlsxwriter') as xw:
            for nm, df in (('prioridade_2026_T2', prio[prio.uf == uf]), ('cidades', cities[cities.uf == uf]), ('zonas', zones[zones.uf == uf]), ('locais', places[places.uf == uf]),
                           ('historico_secoes', hist[hist.uf == uf]), ('por_eleicao', beh[beh.uf == uf])):
                df.round(3).to_excel(xw, sheet_name=nm, index=False, freeze_panes=(1, 0))
                xw.sheets[nm].autofilter(0, 0, len(df), max(len(df.columns) - 1, 0))
    pdf(T, hist, prio, cities, zones, places, E)
    print('ok', len(hist), len(prio))


def pdf(T, hist, prio, cities, zones, places, E):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Histórico por seção: votação tardia e habilitação manual excessiva — quem venceu, comparado às seções vizinhas', H1),
          Paragraph('Comportamento TARDIO = fração de votos após 17h acima do P99 do estado (≥20 votos), ou último voto após 19h, ou encerramento >60 min sem troca de urna. '
                    'MANUAL = habilitação manual pelo mesário acima do esperado (dado biometria cadastrada, idade e escolaridade da seção; P99) ou ≥10 habilitações manuais após 17h. '
                    'Comparação: as outras seções do mesmo local de votação sem o comportamento (se não houver, as do município sem o comportamento). Lado A = PT (presidente) ou líder do município (prefeito). '
                    f'“Diferença alta” = % do lado A na seção difere da comparação em ≥{int(BIG)} p.p. Eleições com log: 2022 T1 e T2, 2024 T1 (prefeito) e 2026 T1.', P),
          Paragraph('Como ler: uma seção com fila e diferença alta a favor de um lado é um ponto a fiscalizar presencialmente (fila, habilitação manual, encerramento), não uma prova. '
                    'Seções de locais com uma só seção são comparadas ao município, uma referência mais fraca. Relatos de compra de votos não são observáveis nos dados; o que se mede é desvio de comportamento e de resultado.', NOTE),
          Paragraph('1. Visão geral por eleição', H2)]
    t = [['Eleição', 'Seções', 'Com comportamento', 'Tardia', 'Manual', 'Comparadas ao local', 'ao município', 'Mesmo vencedor da comparação %', 'Vencedor difere', 'Dif. média lado A (p.p.)', 'Dif. alta (≥10 p.p.)', 'a favor de A', 'a favor de B', 'Dif. alta nas seções SEM comportamento %', 'Excesso A (votos)', 'Votos após 17h']]
    for r in T.itertuples():
        t.append([r.eleicao, n(r.secoes), n(r.com_comportamento), n(r.tardia), n(r.manual), n(r.comparacao_local), n(r.comparacao_municipio), n(r.mesmo_vencedor, 1), n(r.vencedor_difere), n(r.dif_media, 2),
                  n(r.dif_alta), n(r.dif_alta_favor_A), n(r.dif_alta_favor_B), n(r.clean_big_rate, 1), n(r.excesso_A_votos), n(r.votos_tardios)])
    st += [M.table(t, font=5.6),
           Paragraph('“Dif. alta nas seções sem comportamento” é a base de comparação: quanto uma seção comum difere do seu local por acaso. Se as seções com comportamento tiverem taxa parecida, a diferença alta não está ligada ao comportamento.', SM),
           Paragraph('2. Recorrência por seção (seções com comportamento em pelo menos uma eleição)', H2)]
    vc = hist.n_eleicoes_comportamento.value_counts().sort_index()
    t = [['Eleições com comportamento', 'Seções', 'Dif. alta a favor de A (soma, presidenciais)', 'Dif. alta a favor de B', 'Dif. média lado A quando há comportamento (p.p.)']]
    for k, v in vc.items():
        s = hist[hist.n_eleicoes_comportamento == k]
        t.append([str(int(k)), n(v), n(s.n_pres_dif_alta_favor_A.sum()), n(s.n_pres_dif_alta_favor_B.sum()), n(s.dif_media_pres_quando_comportamento.mean(), 2)])
    st += [M.table(t, font=7), PageBreak(), Paragraph('3. Cidades com mais seções recorrentes', H2)]
    t = [['UF', 'Cidade', 'Seções c/ comportamento', 'Recorrentes (2+)', 'Recorrentes (3+)', 'Dif. alta favor A', 'favor B', 'Dif. média pres. (p.p.)', 'Votos após 17h', 'Manuais após 17h']]
    for r in cities.head(30).itertuples():
        t.append([r.uf, r.municipality_name, n(r.secoes_com_comportamento), n(r.recorrentes_2plus), n(r.recorrentes_3plus), n(r.dif_alta_favor_A), n(r.dif_alta_favor_B), n(r.dif_media_pres, 1), n(r.votos_tardios), n(r.manuais_apos_17h)])
    st += [M.table(t, font=6.2), Paragraph('4. Locais de votação (colégios) com mais seções recorrentes', H2)]
    t = [['UF', 'Cidade', 'Zona', 'Local', 'Nome do local', 'Seções c/ comp.', 'Rec. 2+', 'Rec. 3+', 'Dif. alta A', 'Dif. alta B', 'Dif. média (p.p.)', 'Votos após 17h']]
    for r in places.head(30).itertuples():
        t.append([r.uf, r.municipality_name, str(r.zone), str(r.voting_place), (r.place_name or '')[:34] if isinstance(r.place_name, str) else '', n(r.secoes_com_comportamento), n(r.recorrentes_2plus), n(r.recorrentes_3plus),
                  n(r.dif_alta_favor_A), n(r.dif_alta_favor_B), n(r.dif_media_pres, 1), n(r.votos_tardios)])
    st += [M.table(t, font=5.8), PageBreak(), Paragraph(f'5. Prioridade para o 2º turno de 2026: {n(len(prio))} seções (comportamento em 2026 T1 e recorrente ou com diferença alta)', H2)]
    t = [['UF', 'Cidade', 'Zona', 'Seção', 'Local', 'Prior.', 'Eleições c/ comp.', 'Tardia 22/22b/24/26', 'Manual 22/22b/24/26', 'Venc. seção vs comparação (26)', 'Dif. A 2026 (p.p.)', 'Dif. alta A / B (pres.)', 'Após 17h (total)', 'Manuais após 17h']]
    for r in prio.head(40).itertuples():
        lt = ''.join('T' if getattr(r, f'LATE_{e}') == True else '-' for e, _ in ELECS)
        mn = ''.join('M' if getattr(r, f'MANUAL_{e}') == True else '-' for e, _ in ELECS)
        t.append([r.uf, r.municipality_name, str(r.zone), str(r.section), (r.place_name or '')[:26] if isinstance(r.place_name, str) else '', r.prioridade, n(r.n_eleicoes_comportamento), lt, mn,
                  f'{r.winner_ab_P2026} vs {r.cmp_winner_P2026}', n(r.diff_a_P2026, 1), f'{n(r.n_pres_dif_alta_favor_A)} / {n(r.n_pres_dif_alta_favor_B)}', n(r.votos_tardios_total), n(r.manuais_apos_17h_total)])
    st += [M.table(t, font=5.4), Paragraph('Listas completas por estado: FISCALIZACAO_<UF>.xlsx (abas: prioridade 2026 T2, cidades, zonas, locais, histórico de seções, por eleição).', SM),
           Paragraph('6. Síntese (gerada dos números)', H2)]
    lines = []
    for r in T.itertuples():
        lines.append(f'{r.eleicao}: {n(r.com_comportamento)} seções com comportamento; em {n(r.mesmo_vencedor, 1)}% o vencedor é o mesmo da comparação; diferença média do lado A {n(r.dif_media, 2)} p.p.; '
                     f'diferença alta em {n(r.dif_alta)} ({n(r.dif_alta_favor_A)} a favor de A, {n(r.dif_alta_favor_B)} de B), contra {n(r.clean_big_rate, 1)}% de diferença alta nas seções comuns.')
    lines.append(f'Seções com comportamento em 3 ou mais das 4 eleições com log: {n(int((hist.n_eleicoes_comportamento >= 3).sum()))}; em 2 ou mais: {n(int((hist.n_eleicoes_comportamento >= 2).sum()))}.')
    for l in lines:
        st.append(Paragraph('• ' + l, P))
    st += [Paragraph('Limites', H2)]
    for t_ in ['A diferença para as seções vizinhas mede composição do eleitorado tanto quanto qualquer outra coisa; seções do mesmo prédio podem reunir ruas e perfis distintos.',
               'Compra de votos, coação e abuso do mesário não aparecem nos dados; aparecem fila, habilitação manual, horário e resultado. A lista serve para olhar presencialmente, não para concluir.',
               'Comparação ao município (locais de seção única) é mais fraca; o campo cmp_level indica qual foi usada.', 'Nada aqui indica irregularidade nem a descarta.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d_):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Instrumento de fiscalização — sinalização não é acusação')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'HISTORICO_SECOES_FISCALIZACAO.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    main()
