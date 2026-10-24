"""Persistence of section / voting-place / zone patterns across 2022 T1, 2022 T2 and 2026 T1 (10 states). Descriptive; no causal claims."""
from itertools import combinations
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer
from PIL import Image as PI

import make_bahia_reports as M

OUT = Path('relatorios/persistencia') if M.OFFICE == 'PRESIDENTE' else Path('relatorios/governador/persistencia')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
KEYS = ['2022-t1', '2022-t2', '2026-t1']
LAB = {'2022-t1': '2022 T1', '2022-t2': '2022 T2', '2026-t1': '2026 T1'}
KEY = ['municipality', 'zone', 'section']
COLS = KEY + ['municipality_name', 'voting_place', 'eligible', 'attendance', 'turnout', 'vote_events', 'after_17_recorded', 'manual_sequence_votes',
              'operational_eligible', 'raw_high_turnout', 'raw_high_late', 'winner_party', 'winner_pct', 'valid_votes']
REPS = 2000
rng = np.random.default_rng(20261016)




def n(x, d=0):
    return M.n(x, d)


def load():
    data = {}
    for uf in ORDER:
        for k in KEYS:
            if not (M.analysis_dir(uf, k) / 'summary.json').exists():
                continue
            d = pd.read_parquet(M.analysis_dir(uf, k) / 'sections.parquet', columns=COLS)
            ok = d.vote_events.where(d.vote_events > 0)
            d['late_pct'] = 100 * d.after_17_recorded / ok
            d['manual_pct'] = 100 * d.manual_sequence_votes / ok
            elig = d.operational_eligible == True
            d['elig_op'] = elig
            p99 = d.loc[elig, 'manual_pct'].quantile(.99)
            d['C'] = (d.manual_pct > p99).where(elig)
            d['B'] = d.raw_high_late
            d['A'] = d.raw_high_turnout
            d['voting_place'] = d.voting_place.astype(str)
            d['uf'] = uf
            data[(uf, k)] = d
        print('loaded', uf, flush=True)
    return data


def pair(data, uf, k1, k2):
    a, b = data[(uf, k1)], data[(uf, k2)]
    m = a.merge(b, on=KEY, suffixes=('_1', '_2'))
    same = m.voting_place_1 == m.voting_place_2
    ratio = m.eligible_2 / m.eligible_1
    m['strict'] = same & ratio.between(.7, 1.43)
    m['same_place'] = same
    return m, len(a), len(b)


def spearman(x, y):
    ok = x.notna() & y.notna()
    if ok.sum() < 30 or x[ok].nunique() < 3 or y[ok].nunique() < 3:
        return np.nan
    return stats.spearmanr(x[ok], y[ok])[0]


def demean(m, col, grp):
    return m[col] - m.groupby(grp)[col].transform('mean')


def perm_overlap(group, f1, f2, reps, states):
    """Overlap count of two boolean vectors; null by permuting f2 within group. Returns observed, null array (reps), per-state obs and null."""
    f1 = f1.astype(bool)
    f2 = f2.astype(bool)
    order0 = np.argsort(group, kind='stable')
    g0 = group[order0]
    obs = int((f1 & f2).sum())
    ns = states.max() + 1
    obs_s = np.bincount(states, weights=(f1 & f2), minlength=ns)
    null = np.empty(reps)
    null_s = np.empty((reps, ns))
    f2s = f2[order0]
    f1_0, st0 = f1[order0], states[order0]
    for i in range(reps):
        order1 = np.argsort(group + rng.random(len(group)), kind='stable')
        perm = f2[order1]          # block structure identical to order0 (same group order)
        both = f1_0 & perm
        null[i] = both.sum()
        null_s[i] = np.bincount(st0, weights=both, minlength=ns)
    return obs, null, obs_s, null_s


def main():
    data = load()
    # ------------------------------------------------ matching table
    rows = []
    for uf in ORDER:
        for k1, k2 in [('2022-t1', '2026-t1')]:
            m, n1, n2 = pair(data, uf, k1, k2)
            rows.append(dict(uf=uf, n1=n1, n2=n2, key=len(m), same_place=int(m.same_place.sum()), strict=int(m.strict.sum()),
                             pct_strict=100 * m.strict.sum() / min(n1, n2)))
    MT = pd.DataFrame(rows)
    # ------------------------------------------------ persistence metrics
    met = []
    pooled = {}
    for uf in ORDER:
        for k1, k2 in combinations(KEYS, 2):
            if (uf, k1) not in data or (uf, k2) not in data:
                continue
            m, _, _ = pair(data, uf, k1, k2)
            s = m[m.strict].copy()
            e = s[(s.elig_op_1) & (s.elig_op_2)].copy()
            row = dict(uf=uf, pair=f'{LAB[k1]} → {LAB[k2]}', n_strict=len(s), n_elig=len(e))
            row['rho_late'] = spearman(e.late_pct_1, e.late_pct_2)
            row['rho_late_keyonly'] = spearman(m[(m.elig_op_1) & (m.elig_op_2)].late_pct_1, m[(m.elig_op_1) & (m.elig_op_2)].late_pct_2)
            row['rho_size'] = spearman(e.eligible_1, e.eligible_2)
            row['rho_turnout'] = spearman(s.turnout_1, s.turnout_2)
            row['rho_manual'] = spearman(e.manual_pct_1, e.manual_pct_2)
            # within voting place (demeaned)
            e['place'] = e.municipality.astype(str) + '|' + e.zone.astype(str) + '|' + e.voting_place_1
            cnt = e.groupby('place').late_pct_1.transform('size')
            ew = e[cnt >= 2].copy()
            row['rho_late_place'] = spearman(demean(ew, 'late_pct_1', 'place'), demean(ew, 'late_pct_2', 'place'))
            row['rho_manual_place'] = spearman(demean(ew, 'manual_pct_1', 'place'), demean(ew, 'manual_pct_2', 'place'))
            row['rho_turnout_place'] = spearman(demean(ew.assign(t1=100 * ew.turnout_1, t2=100 * ew.turnout_2), 't1', 'place'), demean(ew.assign(t1=100 * ew.turnout_1, t2=100 * ew.turnout_2), 't2', 'place'))
            # within municipality
            row['rho_late_mun'] = spearman(demean(e, 'late_pct_1', 'municipality'), demean(e, 'late_pct_2', 'municipality'))
            # aggregated levels
            for lvl, g in (('place', 'place'), ('mun', 'municipality'), ('zone', 'zone')):
                agg = e.groupby(g).agg(l1=('after_17_recorded_1', 'sum'), l2=('after_17_recorded_2', 'sum'), v1=('vote_events_1', 'sum'), v2=('vote_events_2', 'sum'))
                row[f'rho_late_agg_{lvl}'] = spearman(100 * agg.l1 / agg.v1, 100 * agg.l2 / agg.v2)
                row[f'n_{lvl}'] = len(agg)
            # decile persistence
            q1, q2 = e.late_pct_1.quantile(.9), e.late_pct_2.quantile(.9)
            t1, t2 = (e.late_pct_1 >= q1) & (e.late_pct_1 > 0), (e.late_pct_2 >= q2) & (e.late_pct_2 > 0)
            row['p_top_given_top'] = 100 * (t1 & t2).sum() / max(t1.sum(), 1)
            row['top_n'] = int(t1.sum())
            # winner persistence
            w = s[(s.winner_party_1 != 'EMPATE') & (s.winner_party_2 != 'EMPATE')]
            row['winner_same_pct'] = 100 * (w.winner_party_1 == w.winner_party_2).mean() if len(w) else np.nan
            row['winner_pct_rho'] = spearman(s.winner_pct_1, s.winner_pct_2)
            met.append(row)
            if (k1, k2) == ('2022-t1', '2026-t1'):
                pooled[uf] = e.assign(uf=uf)
        print('metrics', uf, flush=True)
    MET = pd.DataFrame(met)
    # ------------------------------------------------ permutation tests (2022 T1 vs 2026 T1), within municipality
    allp = pd.concat(pooled.values(), ignore_index=True)
    allp['grp'] = pd.factorize(allp.uf + '|' + allp.municipality.astype(str))[0].astype(float)
    st = pd.Categorical(allp.uf, categories=ORDER).codes.astype(int)
    perm = {}
    for name, f1, f2 in [('B', allp.B_1.fillna(False).astype(bool), allp.B_2.fillna(False).astype(bool)),
                         ('C', allp.C_1.fillna(False).astype(bool), allp.C_2.fillna(False).astype(bool)),
                         ('A', allp.A_1.fillna(False).astype(bool), allp.A_2.fillna(False).astype(bool))]:
        obs, null, obs_s, null_s = perm_overlap(allp.grp.values, f1.values, f2.values, REPS, st)
        perm[name] = dict(obs=obs, null_mean=null.mean(), null_p975=np.quantile(null, .975), p=(1 + (null >= obs).sum()) / (REPS + 1),
                          n1=int(f1.sum()), n2=int(f2.sum()), N=len(allp),
                          per_state=[dict(uf=ORDER[i], obs=int(obs_s[i]), null_mean=null_s[:, i].mean(), p=(1 + (null_s[:, i] >= obs_s[i]).sum()) / (REPS + 1),
                                          n1=int(f1[st == i].sum()), n2=int(f2[st == i].sum())) for i in range(len(ORDER))])
        print('perm', name, perm[name]['obs'], round(perm[name]['null_mean'], 1), perm[name]['p'], flush=True)
    # ------------------------------------------------ recurrence A and C over three elections
    rec = []
    for uf in ORDER:
        if not all((uf, k) in data for k in KEYS):
            continue
        a, b, c = (data[(uf, k)] for k in KEYS)
        m = a.merge(b, on=KEY, suffixes=('_1', '_2')).merge(c.add_suffix('_3').rename(columns={f'{x}_3': x for x in KEY}), on=KEY)
        s = m[(m.voting_place_1 == m.voting_place_2) & (m.voting_place_2 == m.voting_place_3)]
        for flag in ('A', 'C'):
            F = s[[f'{flag}_1', f'{flag}_2', f'{flag}_3']].astype(float)
            ok = F.notna().all(axis=1)
            F = F[ok].astype(bool)
            N = len(F)
            p = F.mean().values
            cnt = F.sum(axis=1).value_counts().reindex([0, 1, 2, 3], fill_value=0)
            # expected counts under independence of three Bernoulli(p_i)
            exp = np.zeros(4)
            for bits in np.ndindex(2, 2, 2):
                pr = np.prod([p[i] if bits[i] else 1 - p[i] for i in range(3)])
                exp[sum(bits)] += pr * N
            rec.append(dict(uf=uf, flag=flag, N=N, obs0=int(cnt[0]), obs1=int(cnt[1]), obs2=int(cnt[2]), obs3=int(cnt[3]),
                            exp2=exp[2], exp3=exp[3]))
    REC = pd.DataFrame(rec)
    # ------------------------------------------------ zones and recurrent sections (exports)
    zrows, srows = [], []
    for uf in ORDER:
        z = {}
        for k in KEYS:
            if (uf, k) not in data:
                continue
            d = data[(uf, k)]
            e = d[d.elig_op]
            g = e.groupby('zone').agg(secoes=('section', 'size'), votos=('vote_events', 'sum'), tardios=('after_17_recorded', 'sum'),
                                      manual=('manual_sequence_votes', 'sum'), apt=('eligible', 'sum'), comp=('attendance', 'sum'))
            g['late_pct'] = 100 * g.tardios / g.votos
            g['manual_pct'] = 100 * g.manual / g.votos
            g['turnout_pct'] = 100 * g.comp / g.apt
            z[k] = g
        if '2022-t1' not in z or '2026-t1' not in z:
            continue
        t = z['2022-t1'][['secoes', 'late_pct', 'manual_pct', 'turnout_pct']].join(z['2026-t1'][['secoes', 'late_pct', 'manual_pct', 'turnout_pct']], lsuffix='_2022T1', rsuffix='_2026T1', how='inner')
        if '2022-t2' in z:
            t = t.join(z['2022-t2'][['late_pct', 'manual_pct', 'turnout_pct']].add_suffix('_2022T2'), how='left')
        t['uf'] = uf
        t['rank_late_2022T1'] = t.late_pct_2022T1.rank(ascending=False)
        t['rank_late_2026T1'] = t.late_pct_2026T1.rank(ascending=False)
        zrows.append(t.reset_index())
        m, _, _ = pair(data, uf, '2022-t1', '2026-t1')
        s = m[m.strict & m.B_1.fillna(False).astype(bool) & m.B_2.fillna(False).astype(bool)]
        srows.append(s.assign(uf=uf)[['uf', 'municipality_name_1', 'zone', 'section', 'voting_place_1', 'eligible_1', 'eligible_2', 'late_pct_1', 'late_pct_2',
                                     'after_17_recorded_1', 'after_17_recorded_2', 'winner_party_1', 'winner_pct_1', 'winner_party_2', 'winner_pct_2']])
    ZN = pd.concat(zrows, ignore_index=True)
    SR = pd.concat(srows, ignore_index=True)
    ZN.round(2).to_csv(OUT / 'zonas_persistencia.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    SR.columns = ['UF', 'Município', 'Zona', 'Seção', 'Local', 'Aptos 2022', 'Aptos 2026', '% tardio 2022 T1', '% tardio 2026 T1', 'Votos após 17h 2022 T1',
                  'Votos após 17h 2026 T1', 'Partido venc. 2022 T1', '% venc. 2022 T1', 'Partido venc. 2026 T1', '% venc. 2026 T1']
    SR.round(2).to_csv(OUT / 'secoes_sinalizadas_B_nos_dois_primeiros_turnos.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    MET.round(4).to_csv(OUT / 'persistencia_metricas.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    MT.to_csv(OUT / 'correspondencia_secoes.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    # ------------------------------------------------ figures
    main_ = MET[MET.pair == '2022 T1 → 2026 T1'].set_index('uf').reindex(ORDER)
    f, ax = plt.subplots(figsize=(11, 3.8))
    x = np.arange(len(ORDER))
    w = .2
    for i, (c, lab) in enumerate([('rho_late', 'seção'), ('rho_late_place', 'seção vs. mesmo local (desvio do local)'), ('rho_late_agg_mun', 'município'), ('rho_late_agg_zone', 'zona')]):
        ax.bar(x + (i - 1.5) * w, main_[c], w, label=lab)
    ax.set_xticks(x)
    ax.set_xticklabels(ORDER)
    ax.set(ylabel='correlação de Spearman (2022 T1 × 2026 T1)', title='Persistência do % de votos após 17h')
    ax.legend(fontsize=7)
    ax.axhline(0, color='k', lw=.6)
    f.tight_layout()
    f.savefig(FIG / 'rho_late.png', dpi=150)
    plt.close(f)
    f, ax = plt.subplots(1, 3, figsize=(12, 3.8))
    for a, c, lab in zip(ax, ['rho_late', 'rho_manual', 'rho_turnout'], ['% votos após 17h', '% manual (log)', 'comparecimento']):
        for i, (k, lb) in enumerate([('2022 T1 → 2026 T1', 'T1 → T1'), ('2022 T2 → 2026 T1', 'T2 → 2026'), ('2022 T1 → 2022 T2', '2022 T1→T2')]):
            s = MET[MET.pair == k].set_index('uf').reindex(ORDER)
            a.scatter(x, s[c], s=14, label=lb)
        a.set_xticks(x)
        a.set_xticklabels(ORDER, fontsize=7)
        a.set_title(lab, fontsize=9)
        a.axhline(0, color='k', lw=.6)
    ax[0].set_ylabel('Spearman entre pleitos (seção)')
    ax[0].legend(fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'rho_pairs.png', dpi=150)
    plt.close(f)
    pl = allp[(allp.late_pct_1.notna()) & (allp.late_pct_2.notna())]
    f, ax = plt.subplots(figsize=(5.5, 5))
    hb = ax.hexbin(pl.late_pct_1, pl.late_pct_2, gridsize=60, bins='log', mincnt=1, cmap='viridis')
    ax.set(xlabel='% votos após 17h — 2022 T1', ylabel='% votos após 17h — 2026 T1', title='Mesmas seções (10 estados): cada célula = nº de seções (escala log)')
    ax.title.set_fontsize(8)
    f.colorbar(hb)
    f.tight_layout()
    f.savefig(FIG / 'hexbin.png', dpi=150)
    plt.close(f)
    build_pdf(MT, MET, perm, REC, ZN, SR, allp)
    print('ok')


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def build_pdf(MT, MET, perm, REC, ZN, SR, allp):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    mn = MET[MET.pair == '2022 T1 → 2026 T1'].set_index('uf').reindex(ORDER)
    st = [Paragraph(f'{M.OFFICE_LABEL} — as mesmas seções, locais e zonas repetem o padrão? — persistência entre 2022 e 2026', H1),
          Paragraph('Escopo: BA, SP, MG, RJ, PR, RS, PE, CE, PA e SC; ' + M.OFFICE_LABEL + '; 2022 T1, 2022 T2 e 2026 T1. Medimos se as seções (e locais de votação, municípios e zonas) '
                    'que tiveram muitos votos após 17h, comparecimento alto ou muita habilitação manual numa eleição tendem a repetir na outra, e comparamos com o que se esperaria ao acaso '
                    '(permutação dentro do município, 2.000 repetições, semente fixa). Os dois turnos do mesmo ano não são réplicas independentes; a comparação principal é 2022 T1 × 2026 T1.', P),
          Paragraph('Persistência não é prova de nada: uma seção tem os mesmos eleitores, no mesmo local, com o mesmo porte, de uma eleição para outra. Padrões que vêm da estrutura '
                    '(tamanho, zona urbana, perfil do eleitorado) devem se repetir. A pergunta útil é quanto da repetição sobra além do que a estrutura explica.', NOTE),
          Paragraph('1. Correspondência entre seções', H2)]
    t = [['UF', 'Seções 2022 T1', 'Seções 2026 T1', 'Mesma chave (município-zona-seção)', 'E mesmo local de votação', 'E aptos ±30% (usadas)', '% usadas']]
    for r in MT.itertuples():
        t.append([r.uf, n(r.n1), n(r.n2), n(r.key), n(r.same_place), n(r.strict), n(r.pct_strict, 1) + '%'])
    st += [M.table(t, font=7), Paragraph('A mesma chave textual não garante a mesma unidade física. Usamos como “mesma seção” apenas pares com chave igual, mesmo número de local de votação e aptos entre 0,7× e 1,43×. '
                                         'Renumerações, agregações e mudanças de local ficam de fora; não há correspondência documental oficial nesta etapa.', SM), PageBreak()]
    # section 2: late persistence
    st += [Paragraph('2. Votos após 17h: a seção que é “mais tardia” numa eleição é também na outra?', H2),
           Paragraph('ρ = correlação de Spearman entre o % de votos após 17h da seção em 2022 T1 e em 2026 T1 (seções elegíveis nas duas). “Desvio do local” compara cada seção com a média do seu local de votação, '
                     'removendo o que é comum ao local. Agregados: ρ entre locais, municípios e zonas. “Decil → decil”: dentre as seções no decil mais tardio em 2022, % que continua no decil mais tardio em 2026 '
                     '(10% seria o acaso). ρ(aptos) mede a persistência do tamanho da seção, como referência estrutural.', P)]
    t = [['UF', 'Seções', 'ρ seção', 'ρ sem a chave exata', 'ρ desvio do local', 'ρ no município (desvio)', 'ρ local (agr.)', 'ρ município (agr.)', 'ρ zona (agr.)', 'Zonas', 'Decil→decil %', 'ρ aptos (ref.)']]
    for uf in ORDER:
        r = mn.loc[uf]
        t.append([uf, n(r.n_elig), n(r.rho_late, 2), n(r.rho_late_keyonly, 2), n(r.rho_late_place, 2), n(r.rho_late_mun, 2), n(r.rho_late_agg_place, 2), n(r.rho_late_agg_mun, 2),
                  n(r.rho_late_agg_zone, 2), n(r.n_zone), n(r.p_top_given_top, 1), n(r.rho_size, 2)])
    st += [M.table(t, font=6.8), img(FIG / 'rho_late.png', 21), PageBreak(), img(FIG / 'hexbin.png', 12)]
    # flags overlap
    st += [Paragraph('3. Sinalizações brutas: sobreposição observada vs. acaso', H2),
           Paragraph('Sinalização A: comparecimento muito acima da seção típica (z&gt;3 e ≥10 p.p. acima da mediana municipal). B: fração de votos após 17h acima do P99 do estado e ≥20 votos. '
                     'C: proporção de habilitação manual (log) acima do P99 do estado. “Sobreposição” = seções sinalizadas nos dois pleitos (2022 T1 e 2026 T1). “Esperado” = média da sobreposição '
                     'quando o vetor de 2026 é embaralhado entre seções do mesmo município. p = fração de embaralhamentos com sobreposição ≥ a observada.', P)]
    t = [['Sinal', 'Seções comparáveis', 'Sinalizadas 2022 T1', 'Sinalizadas 2026 T1', 'Sobreposição observada', 'Esperado ao acaso', 'Percentil 97,5% do acaso', 'Razão obs./esp.', 'p']]
    for k, nm in (('B', 'B — votos tardios'), ('C', 'C — manual alto'), ('A', 'A — comparecimento alto')):
        d = perm[k]
        t.append([nm, n(d['N']), n(d['n1']), n(d['n2']), n(d['obs']), n(d['null_mean'], 1), n(d['null_p975'], 1), n(d['obs'] / d['null_mean'], 1) if d['null_mean'] else '—', n(d['p'], 4)])
    st += [M.table(t, font=7)]
    for k, nm in (('B', 'B — votos tardios'), ('C', 'C — manual alto'), ('A', 'A — comparecimento alto')):
        t = [['UF', '2022 T1', '2026 T1', 'Sobreposição obs.', 'Esperado', 'Razão', 'p']]
        for r in perm[k]['per_state']:
            t.append([r['uf'], n(r['n1']), n(r['n2']), n(r['obs']), n(r['null_mean'], 1), n(r['obs'] / r['null_mean'], 1) if r['null_mean'] else '—', n(r['p'], 4)])
        st += [Paragraph(f'Por estado — {nm}', M.P), M.table(t, font=6.8)]
    st += [PageBreak(), Paragraph('4. Todos os pares de pleitos (persistência por seção)', H2)]
    t = [['UF', 'Par', 'Seções usadas', 'ρ % tardio', 'ρ % tardio (desvio do local)', 'ρ % manual', 'ρ % manual (desvio do local)', 'ρ comparecimento', 'ρ comparecimento (desvio do local)', 'Vencedor igual %', 'ρ % do vencedor']]
    for r in MET.sort_values(['pair', 'uf'], key=lambda c: c.map({u: i for i, u in enumerate(ORDER)}) if c.name == 'uf' else c).itertuples():
        t.append([r.uf, r.pair, n(r.n_elig), n(r.rho_late, 2), n(r.rho_late_place, 2), n(r.rho_manual, 2), n(r.rho_manual_place, 2), n(r.rho_turnout, 2), n(r.rho_turnout_place, 2),
                  n(r.winner_same_pct, 1), n(r.winner_pct_rho, 2)])
    st += [M.table(t, font=6.2), img(FIG / 'rho_pairs.png', 22), PageBreak()]
    # recurrence
    st += [Paragraph('5. Recorrência de comparecimento alto (A) e manual alto (C) nos 3 pleitos', H2),
           Paragraph('Seções com os mesmos local e chave nos três pleitos: quantas foram sinalizadas em 0, 1, 2 e nos 3 pleitos, e quantas seriam esperadas em 2 e 3 se os três pleitos fossem independentes '
                     '(taxas observadas por pleito). Lembrando: 2022 T1 e T2 compartilham a mesma eleição e eleitorado, então recorrência “2 de 3” entre T1 e T2 é esperada.', P)]
    t = [['UF', 'Sinal', 'Seções', '0 vezes', '1 vez', '2 vezes', 'Esperado 2', '3 vezes', 'Esperado 3']]
    for r in REC.itertuples():
        t.append([r.uf, r.flag, n(r.N), n(r.obs0), n(r.obs1), n(r.obs2), n(r.exp2, 1), n(r.obs3), n(r.exp3, 2)])
    st += [M.table(t, font=6.8), PageBreak()]
    # zones
    st += [Paragraph('6. Zonas eleitorais: o ranking se repete?', H2),
           Paragraph('Para cada estado, as 10 zonas com maior % de votos após 17h em 2022 T1 e a posição e valor delas em 2026 T1 (zonas presentes nos dois pleitos). Lista completa de zonas: zonas_persistencia.csv.', P)]
    for uf in ORDER:
        z = ZN[ZN.uf == uf].sort_values('late_pct_2022T1', ascending=False).head(8)
        t = [['Zona', 'Seções 2022', '% tardio 2022 T1', 'Posição 2022', '% tardio 2026 T1', 'Posição 2026', '% manual 2022', '% manual 2026', 'Comparecimento 2022', 'Comparecimento 2026']]
        for r in z.itertuples():
            t.append([str(r.zone), n(r.secoes_2022T1), n(r.late_pct_2022T1, 2), n(r.rank_late_2022T1), n(r.late_pct_2026T1, 2), n(r.rank_late_2026T1),
                      n(r.manual_pct_2022T1, 1), n(r.manual_pct_2026T1, 1), n(r.turnout_pct_2022T1, 1), n(r.turnout_pct_2026T1, 1)])
        st += [Paragraph(f'{M.NAMES[uf]} — {ZN[ZN.uf == uf].shape[0]} zonas', M.P), M.table(t, font=6.5), Spacer(1, 3)]
    st += [PageBreak(), Paragraph('7. Seções sinalizadas pela regra B nos dois primeiros turnos (2022 e 2026)', H2),
           Paragraph(f'{n(len(SR))} seções com a mesma identificação (chave, local, porte) foram sinalizadas por votos tardios em 2022 T1 e em 2026 T1. Lista completa: secoes_sinalizadas_B_nos_dois_primeiros_turnos.csv. '
                     f'Abaixo, as 30 com mais votos tardios somados.', P)]
    t = [['UF', 'Município', 'Zona', 'Seção', 'Local', '% tardio 2022', '% tardio 2026', 'Votos tardios 22+26', 'Vencedor 2022', 'Vencedor 2026']]
    top = SR.assign(s=SR['Votos após 17h 2022 T1'] + SR['Votos após 17h 2026 T1']).sort_values('s', ascending=False).head(30)
    for r in top.itertuples(index=False):
        t.append([r[0], r[1], str(r[2]), str(r[3]), str(r[4]), n(r[7], 1), n(r[8], 1), n(r[15]), f'{r[11]} {n(r[12], 0)}%', f'{r[13]} {n(r[14], 0)}%'])
    st += [M.table(t, font=6.5)]
    # summary
    st += [PageBreak(), Paragraph('8. Síntese (gerada dos números)', H2)]
    lines = [f'Seções usadas como “as mesmas” entre 2022 T1 e 2026 T1: {n(MT.strict.sum())} de {n(MT.n1.sum())} (2022) — {n(100 * MT.strict.sum() / MT.n1.sum(), 1)}%.',
             f'% de votos após 17h por seção, correlação 2022 T1 × 2026 T1: ρ entre {n(mn.rho_late.min(), 2)} ({mn.rho_late.idxmin()}) e {n(mn.rho_late.max(), 2)} ({mn.rho_late.idxmax()}), mediana {n(mn.rho_late.median(), 2)}.',
             f'Tamanho da seção (aptos), referência estrutural: ρ mediano {n(mn.rho_size.median(), 2)}.',
             f'Comparando cada seção só com as do mesmo local (desvio do local): ρ mediano {n(mn.rho_late_place.median(), 2)}; no nível da zona, ρ mediano {n(mn.rho_late_agg_zone.median(), 2)}; no município, {n(mn.rho_late_agg_mun.median(), 2)}.',
             f'Dentre as seções do decil mais tardio em 2022, em média {n(mn.p_top_given_top.mean(), 1)}% continuam no decil mais tardio em 2026 (acaso: 10%).']
    for k, nm in (('B', 'B (votos tardios)'), ('C', 'C (manual alto)'), ('A', 'A (comparecimento alto)')):
        d = perm[k]
        lines.append(f'Sinalização {nm}: {n(d["obs"])} seções nos dois pleitos vs. {n(d["null_mean"], 1)} esperadas ao acaso dentro do município (razão {n(d["obs"] / d["null_mean"], 1)}×; p={n(d["p"], 4)}).')
    w = MET[MET.pair == '2022 T1 → 2026 T1']
    lines.append(f'Resultado: o partido vencedor da seção é o mesmo em 2022 T1 e 2026 T1 em {n(w.winner_same_pct.min(), 1)}% a {n(w.winner_same_pct.max(), 1)}% das seções, conforme o estado.')
    for l in lines:
        st.append(Paragraph('• ' + l, P))
    st += [Paragraph('Leitura e limites', H2)]
    for t_ in ['Há persistência forte do padrão de votos tardios por seção, e ela é em grande parte estrutural: o porte da seção (que também persiste) e o local de votação explicam boa parte. '
               'O que sobra ao comparar seções do mesmo local mostra se a seção tem uma característica própria (por exemplo, composição do eleitorado) que se repete.',
               'Repetição de uma seção na lista de sinalizadas não indica irregularidade; é compatível com fila recorrente no mesmo local e com eleitorado estável.',
               'Não há correspondência documental oficial entre seções de anos diferentes: seções renumeradas, agregadas ou com mudança de local ficam de fora ou podem estar mal pareadas.',
               'A permutação preserva o município, mas não o local nem a zona; sobreposições acima do acaso podem refletir também porte e zona. Nenhum controle demográfico (idade, escolaridade, biometria) foi usado.',
               'Os dois turnos de 2022 não são independentes; a comparação principal de recorrência é entre 2022 T1 e 2026 T1.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo e estatístico — persistência não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'ANALISE_PERSISTENCIA_SECOES_ZONAS.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm, title='Persistência de padrões por seção e zona').build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    main()
