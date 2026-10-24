"""Stage 2 of the mayor-vs-president comparison (needs 2024 urn logs): late votes, log-based manual share, cross-type persistence, leader-share association.
Reads the stage-1 CSVs written by make_mayor_comparison.py and rebuilds the PDF with the extra sections."""
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt
from reportlab.platypus import PageBreak, Paragraph

os.environ.setdefault('UF', 'BA')
import make_mayor_comparison as mc
import make_bahia_reports as M
import make_late_votes_study as S

ORDER, KEY, FIG, OUT = mc.ORDER, mc.KEY, mc.FIG, mc.OUT
n, spearman, match, flag_overlap, img, adir = mc.n, mc.spearman, mc.match, mc.flag_overlap, mc.img, mc.adir
E2 = [('P2022', 'Presidente 2022 T1', 'PRESIDENTE', 2022, 1), ('P2026', 'Presidente 2026 T1', 'PRESIDENTE', 2026, 1), ('M2024', 'Prefeito 2024 T1', 'PREFEITO', 2024, 1),
      ('P2022b', 'Presidente 2022 T2', 'PRESIDENTE', 2022, 2), ('M2024b', 'Prefeito 2024 T2', 'PREFEITO', 2024, 2)]
LAB = {e[0]: e[1] for e in E2}
COL2 = {'P2022': '#3182bd', 'P2026': '#08519c', 'M2024': '#e6550d', 'P2022b': '#9ecae1', 'M2024b': '#fdae6b'}
MCLS = ['<10 mil', '10–50 mil', '50–200 mil', '>200 mil']


def load2(office, year, turn):
    frames = []
    for uf in ORDER:
        f = adir(office, uf, year, turn)
        if not (f / 'summary.json').exists():
            continue
        cols = KEY + ['voting_place', 'eligible', 'attendance', 'turnout', 'valid_votes', 'vote_events', 'after_17_recorded', 'manual_sequence_votes', 'manual_bu',
                      'operational_eligible', 'raw_high_late', 'last_vote', 'late_interval_median_seconds']
        d = pd.read_parquet(f / 'sections.parquet', columns=cols)
        c = pd.read_parquet(f / 'candidate_sections.parquet')
        tot = c.groupby(['municipality', 'candidate_number']).votes.sum().reset_index()
        lead = tot.sort_values(['municipality', 'votes', 'candidate_number'], ascending=[True, False, True]).groupby('municipality').head(1)[['municipality', 'candidate_number']]
        lv = c.merge(lead, on=['municipality', 'candidate_number']).groupby(KEY).votes.sum().rename('lead_votes')
        d = d.join(lv, on=KEY)
        d['lead_votes'] = d.lead_votes.fillna(0)
        d['uf'] = uf
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    ok = d.vote_events.where(d.vote_events > 0)
    d['voting_place'] = d.voting_place.astype(str)
    d['elig_op'] = d.operational_eligible == True
    d['late_pct'] = (100 * d.after_17_recorded / ok).where(d.elig_op)
    d['manual_pct'] = 100 * d.manual_bu / d.attendance.where(d.attendance >= 50)
    d['manual_log_pct'] = (100 * d.manual_sequence_votes / ok).where(d.elig_op)
    lvt = pd.to_datetime(d.last_vote.astype(str).str[-8:], format='%H:%M:%S', errors='coerce')
    d['last_h'] = lvt.dt.hour + lvt.dt.minute / 60 + lvt.dt.second / 3600
    return d


def compute():
    D = {e[0]: load2(*e[2:]) for e in E2}
    rows, srows = [], []
    for eid, lab, office, year, turn in E2:
        d = D[eid]
        e = d[d.elig_op & (d.vote_events > 0)].copy()
        L, V = e.after_17_recorded.sum(), e.vote_events.sum()
        srt = e.after_17_recorded.sort_values(ascending=False)
        cs = srt.cumsum() / max(L, 1)
        e['sq'] = pd.qcut(e.eligible.rank(method='first'), 5, labels=False)
        mun = e.groupby(['uf', 'municipality']).eligible.transform('sum')
        e['mcls'] = pd.cut(mun, [0, 10000, 50000, 200000, 1e12], labels=MCLS)
        row = dict(eid=eid, lab=lab, sections=len(d), elig=len(e), votes=int(V), late=int(L), late_pct=100 * L / V, sec_ge1=100 * (e.after_17_recorded >= 1).mean(),
                   sec_ge10=100 * (e.after_17_recorded >= 10).mean(), p50=e.late_pct.quantile(.5), p90=e.late_pct.quantile(.9), p99=e.late_pct.quantile(.99),
                   top1=100 * cs.iloc[max(int(len(srt) * .01) - 1, 0)] if L else np.nan, top10=100 * cs.iloc[max(int(len(srt) * .1) - 1, 0)] if L else np.nan,
                   last_gt17=100 * (e.last_h > 17).mean(), last_ge19=100 * (e.last_h >= 19).mean(), manual_log=100 * e.manual_sequence_votes.sum() / V,
                   manual_bu=100 * e.manual_bu.sum() / e.attendance.sum(), rho_size=spearman(e.late_pct, e.eligible))
        for q in range(5):
            s_ = e[e.sq == q]
            row[f'q{q + 1}'] = 100 * s_.after_17_recorded.sum() / s_.vote_events.sum()
        for c in MCLS:
            s_ = e[e.mcls == c]
            row[f'm_{c}'] = 100 * s_.after_17_recorded.sum() / s_.vote_events.sum() if len(s_) else np.nan
        rows.append(row)
        for uf in ORDER:
            s_ = e[e.uf == uf]
            if len(s_):
                srows.append(dict(eid=eid, lab=lab, uf=uf, late_pct=100 * s_.after_17_recorded.sum() / s_.vote_events.sum(), sec_ge1=100 * (s_.after_17_recorded >= 1).mean(),
                                  manual_log=100 * s_.manual_sequence_votes.sum() / s_.vote_events.sum(), sections=len(s_)))
    R2, S2 = pd.DataFrame(rows), pd.DataFrame(srows)
    PRs, OVs = [], []
    for a, b in [('P2022', 'M2024'), ('M2024', 'P2026'), ('P2022', 'P2026')]:
        m = match(D[a], D[b])
        row = dict(pair=f'{LAB[a]} → {LAB[b]}', n=len(m), rho_size=spearman(m.eligible_1, m.eligible_2), rho_late=spearman(m.late_pct_1, m.late_pct_2),
                   rho_manual_log=spearman(m.manual_log_pct_1, m.manual_log_pct_2))
        m['place'] = m.uf + '|' + m.municipality.astype(str) + '|' + m.zone.astype(str) + '|' + m.voting_place_1
        w = m[m.groupby('place').late_pct_1.transform('size') >= 2].copy()
        for c in ('late_pct', 'manual_log_pct'):
            w2 = w[w[f'{c}_1'].notna() & w[f'{c}_2'].notna()]
            row[f'rho_{c}_place'] = spearman(w2[f'{c}_1'] - w2.groupby('place')[f'{c}_1'].transform('mean'), w2[f'{c}_2'] - w2.groupby('place')[f'{c}_2'].transform('mean'))
        PRs.append(row)
        for col, nm in (('late_pct', 'votos após 17h (log)'), ('manual_log_pct', 'manual (log)')):
            r = flag_overlap(m, col)
            if r:
                OVs.append(dict(pair=row['pair'], sinal=nm, **r))
        print('persist2', row['pair'], flush=True)
    regs = []
    for eid, lab, office, year, turn in E2[:3]:
        d = D[eid]
        e = d[d.elig_op & (d.vote_events > 0) & (d.valid_votes > 0) & (d.eligible >= 50)].copy()
        e['late'] = e.late_pct / 10.0
        e['lelig'] = np.log(e.eligible)
        e['turn'] = e.turnout * 10.0
        e['cl'] = e.uf + '|' + e.zone.astype(str)
        e['place'] = e.uf + '|' + e.municipality.astype(str) + '|' + e.zone.astype(str) + '|' + e.voting_place
        e['mun'] = e.uf + '|' + e.municipality.astype(str)
        e['vc_sum'] = e.valid_votes.astype(float)
        e['y'] = 100 * e.lead_votes / e.valid_votes
        for uf in ORDER + ['TODOS']:
            s_ = e if uf == 'TODOS' else e[e.uf == uf]
            for fe, c_ in (('município', 'mun'), ('local de votação', 'place')):
                b, se, nobs, ng = S.fe_regression(s_, 'y', [c_])
                regs.append(dict(eid=eid, lab=lab, uf=uf, fe=fe, coef=b, se=se, n=nobs, groups=ng))
        print('reg', eid, flush=True)
    G = pd.DataFrame(regs)
    G['lo'], G['hi'] = G.coef - 1.96 * G.se, G.coef + 1.96 * G.se
    G['p'] = 2 * (1 - stats.norm.cdf((G.coef / G.se).abs()))
    return R2, S2, pd.DataFrame(PRs), pd.DataFrame(OVs), G


def figures(R2, S2):
    f, ax = plt.subplots(1, 3, figsize=(13, 3.8))
    x = np.arange(len(ORDER))
    for a, col, ttl in zip(ax, ['late_pct', 'sec_ge1', 'manual_log'], ['Votos após 17h (% dos votos)', 'Seções com ≥1 voto após 17h (%)', 'Manual — log (% dos votos)']):
        for i, eid in enumerate(['P2022', 'P2026', 'M2024']):
            s = S2[S2.eid == eid].set_index('uf').reindex(ORDER)
            a.bar(x + (i - 1) * .27, s[col], .27, color=COL2[eid], label=LAB[eid])
        a.set_xticks(x)
        a.set_xticklabels(ORDER, fontsize=7)
        a.set_title(ttl, fontsize=8)
    ax[0].legend(fontsize=6)
    f.tight_layout()
    f.savefig(FIG / 'log_niveis.png', dpi=150)
    plt.close(f)
    f, ax = plt.subplots(figsize=(7.5, 3.6))
    for eid in ['P2022', 'P2026', 'M2024']:
        r = R2[R2.eid == eid].iloc[0]
        ax.plot(range(1, 6), [r[f'q{i}'] for i in range(1, 6)], marker='o', color=COL2[eid], label=r.lab)
    ax.set(xlabel='quintil de aptos da seção (1 = menores, 5 = maiores)', ylabel='% dos votos após 17h', title='Votos após 17h por tamanho da seção (10 estados)')
    ax.legend(fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'log_tamanho.png', dpi=150)
    plt.close(f)


def extra(R2, S2, PR2, OV2, G):
    P, H2 = M.P, M.H2
    st = [PageBreak(), Paragraph('4. Votos após 17h e habilitação manual pelo log (2024 vs. 2022 e 2026)', H2),
          Paragraph('Seções elegíveis (log identificado, igual ao comparecimento do BU, relógio coerente, ≥50 aptos). “Seções ≥1/≥10”: % das seções com pelo menos 1 ou 10 votos após 17h. '
                    'P50/P90/P99: percentis do % tardio por seção. “Top 1%/10%”: parcela dos votos tardios que está nas seções mais tardias.', P)]
    t = [['Eleição', 'Seções elegíveis', 'Votos (log)', 'Após 17h', '% após 17h', '% seções ≥1', '% seções ≥10', 'P50 %', 'P90 %', 'P99 %', 'Top 1% concentra', 'Top 10% concentra',
          'Último voto >17h (% seções)', '≥19h (% seções)', 'Manual log %', 'Manual BU %', 'ρ(% tardio, aptos)']]
    for r in R2.itertuples():
        t.append([r.lab, n(r.elig), n(r.votes), n(r.late), n(r.late_pct, 2), n(r.sec_ge1, 1), n(r.sec_ge10, 1), n(r.p50, 1), n(r.p90, 1), n(r.p99, 1), n(r.top1, 1), n(r.top10, 1),
                  n(r.last_gt17, 1), n(r.last_ge19, 1), n(r.manual_log, 2), n(r.manual_bu, 2), n(r.rho_size, 2)])
    st += [M.table(t, font=5.8), img(FIG / 'log_niveis.png', 24), img(FIG / 'log_tamanho.png', 13)]
    t = [['Eleição'] + [f'% tardio município {c}' for c in MCLS] + [f'% tardio quintil {i}' for i in range(1, 6)]]
    for i, r in R2.iterrows():
        t.append([r.lab] + [n(r[f'm_{c}'], 2) for c in MCLS] + [n(r[f'q{k}'], 2) for k in range(1, 6)])
    st += [M.table(t, font=6.5), PageBreak(), Paragraph('5. Por estado (log)', H2)]
    t = [['UF'] + [f'{LAB[k]}: % tardio / % seções ≥1 / manual log %' for k in ['P2022', 'P2026', 'M2024']]]
    for uf in ORDER:
        row = [uf]
        for k in ['P2022', 'P2026', 'M2024']:
            s = S2[(S2.eid == k) & (S2.uf == uf)]
            row.append(f'{n(s.late_pct.iloc[0], 2)} / {n(s.sec_ge1.iloc[0], 1)} / {n(s.manual_log.iloc[0], 2)}' if len(s) else '—')
        t.append(row)
    st += [M.table(t, font=7), Paragraph('6. As mesmas seções repetem o padrão de votos tardios e de manual entre tipos de eleição? (log)', H2)]
    t = [['Par', 'Seções', 'ρ aptos', 'ρ % tardio', '… desvio do local', 'ρ % manual (log)', '… desvio do local']]
    for r in PR2.itertuples():
        t.append([r.pair, n(r.n), n(r.rho_size, 2), n(r.rho_late, 2), n(r.rho_late_pct_place, 2), n(r.rho_manual_log, 2), n(r.rho_manual_log_pct_place, 2)])
    st += [M.table(t, font=7)]
    t = [['Par', 'Sinal (top 1% do estado)', 'Seções comparáveis', 'Sinalizadas A', 'Sinalizadas B', 'Sobreposição', 'Esperado ao acaso', 'Razão', 'p']]
    for r in OV2.itertuples():
        t.append([r.pair, r.sinal, n(r.N), n(r.n1), n(r.n2), n(r.obs), n(r.exp, 1), n(r.ratio, 1), n(r.p, 4)])
    st += [M.table(t, font=6.8), PageBreak(), Paragraph('7. Associação entre % de votos tardios e o voto, dentro do município e do local de votação', H2),
           Paragraph('Para comparar prefeito e presidente com a mesma régua: em cada município, o candidato mais votado (naquele cargo e eleição) é o “líder”; a variável é a % de votos válidos '
                     'do líder em cada seção. Coeficiente = variação dessa % (p.p.) por +10 p.p. de votos tardios na seção, com controle de log(aptos) e comparecimento, ponderado por votos válidos, '
                     'com efeito fixo de município (ou de local de votação) e erros agrupados por zona. Não há mapa de partidos: o líder pode ser de qualquer partido.', P)]
    for fe in ('município', 'local de votação'):
        t = [['UF'] + [f'{LAB[k]}: coef. [IC 95%]' for k in ['P2022', 'P2026', 'M2024']]]
        for uf in ORDER + ['TODOS']:
            row = [uf]
            for k in ['P2022', 'P2026', 'M2024']:
                s = G[(G.fe == fe) & (G.uf == uf) & (G.eid == k)]
                row.append(f'{n(s.coef.iloc[0], 2)} [{n(s.lo.iloc[0], 2)}; {n(s.hi.iloc[0], 2)}]' if len(s) and not np.isnan(s.coef.iloc[0]) else '—')
            t.append(row)
        st += [Paragraph(f'Efeito fixo de {fe}', P), M.table(t, font=7)]
    st += [Paragraph('8. Síntese (gerada dos números)', H2)]
    r = R2.set_index('eid')
    lines = [f'% de votos após 17h: Prefeito 2024 {n(r.loc["M2024", "late_pct"], 2)}% contra Presidente 2022 {n(r.loc["P2022", "late_pct"], 2)}% e 2026 {n(r.loc["P2026", "late_pct"], 2)}%. '
             f'Seções com ≥1 voto tardio: {n(r.loc["M2024", "sec_ge1"], 1)}% (prefeito) vs {n(r.loc["P2022", "sec_ge1"], 1)}% e {n(r.loc["P2026", "sec_ge1"], 1)}%.',
             f'Concentração: o 1% de seções mais tardias concentra {n(r.loc["M2024", "top1"], 1)}% dos votos tardios no prefeito, {n(r.loc["P2022", "top1"], 1)}% (pres. 2022) e {n(r.loc["P2026", "top1"], 1)}% (pres. 2026).',
             f'Habilitação manual pelo log: {n(r.loc["M2024", "manual_log"], 2)}% (prefeito 2024) vs {n(r.loc["P2022", "manual_log"], 2)}% e {n(r.loc["P2026", "manual_log"], 2)}%.',
             f'Estrutura: correlação entre % tardio e aptos da seção {n(r.loc["M2024", "rho_size"], 2)} (prefeito) vs {n(r.loc["P2022", "rho_size"], 2)} e {n(r.loc["P2026", "rho_size"], 2)}.']
    for l in lines:
        st.append(Paragraph('• ' + l, P))
    return st


if __name__ == '__main__':
    R = pd.read_csv(OUT / 'niveis_bu.csv', sep=';', decimal=',')
    Sb = pd.read_csv(OUT / 'por_estado_bu.csv', sep=';', decimal=',')
    PR = pd.read_csv(OUT / 'persistencia_entre_tipos.csv', sep=';', decimal=',')
    OV = pd.read_csv(OUT / 'sobreposicao_entre_tipos.csv', sep=';', decimal=',')
    R2, S2, PR2, OV2, G = compute()
    for nm, df in (('log_niveis', R2), ('log_por_estado', S2), ('log_persistencia_entre_tipos', PR2), ('log_sobreposicao_entre_tipos', OV2), ('log_associacao_lider', G)):
        df.round(4).to_csv(OUT / f'{nm}.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    figures(R2, S2)
    mc.pdf(R, Sb, PR, OV, extra(R2, S2, PR2, OV2, G))
    print('ok')
