"""Study of votes after 17:00 across 10 states, 2022 T1/T2 and 2026 T1. Descriptive/statistical only; no causal or partisan claims.

Outputs (relatorios/votos_apos_17h/):
  secoes_apos_17h_<UF>.xlsx  one sheet per election, every section with >=1 vote after 17:00
  secoes_apos_17h_todas.csv  same rows, all states
  ANALISE_VOTOS_APOS_17H.pdf analysis report
"""
import warnings
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

warnings.filterwarnings('ignore')
OUT = Path('relatorios/votos_apos_17h') if M.OFFICE == 'PRESIDENTE' else Path('relatorios/governador/votos_apos_17h')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
NAMES = M.NAMES
RUNS = [('2022-t1', '2022 · 1º turno'), ('2022-t2', '2022 · 2º turno'), ('2026-t1', '2026 · 1º turno')]


def CL(j):
    if M.OFFICE == 'PRESIDENTE':
        return 'PT' if j == 1 else 'PL'
    return '1º colocado do estado' if j == 1 else '2º colocado do estado'

STCOL = dict(zip(ORDER, plt.cm.tab10.colors))


def adir(uf, k):
    return M.analysis_dir(uf, k)


# ------------------------------------------------------------------ load
def load_all():
    frames, cands = [], {}
    for uf in ORDER:
        for k, lab in RUNS:
            folder = adir(uf, k)
            if not (folder / 'summary.json').exists():
                continue
            s = pd.read_parquet(folder / 'sections.parquet')
            c = pd.read_parquet(folder / 'candidate_sections.parquet')
            key = ['municipality', 'zone', 'section']
            c = c.sort_values(key + ['votes', 'candidate_number'], ascending=[True] * 3 + [False, True])
            top = c.groupby(key).head(2)
            top['rk'] = top.groupby(key).cumcount() + 1
            w = top[top.rk == 1].set_index(key)[['votes']].rename(columns={'votes': 'winner_votes'})
            r = top[top.rk == 2].set_index(key)[['candidate', 'party', 'votes']].rename(
                columns={'candidate': 'runner_up', 'party': 'runner_up_party', 'votes': 'runner_up_votes'})
            s = s.join(w, on=key).join(r, on=key)
            s['margin_votes'] = s.winner_votes - s.runner_up_votes
            s['late_pct'] = 100 * s.after_17_recorded / s.vote_events.where(s.vote_events > 0)
            s['uf'], s['k'], s['recorte'] = uf, k, lab
            # candidate votes wide for the two state-level leaders
            tot = c.groupby(['candidate_number', 'candidate', 'party']).votes.sum().sort_values(ascending=False)
            top2 = list(tot.index[:2])
            cands[(uf, k)] = [dict(number=i[0], name=i[1], party=i[2], votes=int(tot.iloc[j])) for j, i in enumerate(top2)]
            if M.OFFICE == 'PRESIDENTE':
                assert {i[2] for i in top2} == {'PT', 'PL'}, (uf, k, top2)
                lead = sorted(top2, key=lambda i: i[2] != 'PT')   # c1 = PT candidate, c2 = PL candidate
            else:
                lead = top2                                         # c1 = statewide winner, c2 = runner-up
            cands[(uf, k, 'pt_pl')] = [dict(number=i[0], name=i[1], party=i[2], votes=int(tot.loc[i])) for i in lead]
            for j, i in enumerate(lead):
                v = c[c.candidate_number == i[0]].set_index(key).votes.rename(f'c{j + 1}_votes')
                s = s.join(v, on=key)
                s[f'c{j + 1}_votes'] = s[f'c{j + 1}_votes'].fillna(0)
            s['vc_sum'] = c.groupby(key).votes.sum().reindex(s.set_index(key).index).values
            frames.append(s)
        print('loaded', uf, flush=True)
    return pd.concat(frames, ignore_index=True), cands


# ------------------------------------------------------------------ helpers
def n(x, d=0):
    return M.n(x, d)


def late_df(df):
    d = df[df.vote_events.notna() & (df.vote_events > 0)].copy()
    d['late_pct'] = 100 * d.after_17_recorded / d.vote_events
    d['margin_votes'] = d.winner_votes - d.runner_up_votes
    return d


def fe_regression(d, ycol, group_cols, controls=('late', 'lelig', 'turn'), cluster='cl'):
    """Weighted FE OLS via within transformation; cluster-robust SE. Returns (coef_late, se, n_obs, n_groups)."""
    g = d[group_cols].astype(str).agg('|'.join, axis=1) if isinstance(group_cols, list) else d[group_cols]
    g = g.values
    X = d[list(controls)].values.astype(float)
    y = d[ycol].values.astype(float)
    w = d.vc_sum.values.astype(float)
    sw = np.sqrt(w)
    codes, uniq = pd.factorize(g)
    G = len(uniq)
    wsum = np.bincount(codes, weights=w, minlength=G)
    cnt = np.bincount(codes, minlength=G)

    def demean(v):
        m = np.bincount(codes, weights=w * v, minlength=G) / np.where(wsum > 0, wsum, 1)
        return (v - m[codes]) * sw
    keep = cnt[codes] > 1
    Xt = np.column_stack([demean(X[:, j]) for j in range(X.shape[1])])[keep]
    yt = demean(y)[keep]
    cl = d[cluster].values[keep]
    XtX = Xt.T @ Xt
    if np.linalg.cond(XtX) > 1e12:
        return np.nan, np.nan, int(keep.sum()), int((cnt > 1).sum())
    inv = np.linalg.inv(XtX)
    beta = inv @ Xt.T @ yt
    e = yt - Xt @ beta
    sc = pd.DataFrame(Xt * e[:, None]).groupby(pd.factorize(cl)[0]).sum().values
    Gc = sc.shape[0]
    meat = sc.T @ sc * (Gc / max(Gc - 1, 1))
    V = inv @ meat @ inv
    return beta[0], float(np.sqrt(V[0, 0])), int(keep.sum()), int((cnt > 1).sum())


def bh(p):
    p = np.asarray(p, float)
    ok = ~np.isnan(p)
    q = np.full_like(p, np.nan)
    pv = p[ok]
    order = np.argsort(pv)
    ranked = pv[order] * len(pv) / (np.arange(len(pv)) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(pv)
    out[order] = np.minimum(ranked, 1)
    q[ok] = out
    return q


# ------------------------------------------------------------------ exports
def export_lists(all_):
    cols = [('uf', 'UF'), ('recorte', 'Pleito'), ('municipality_name', 'Município'), ('municipality', 'Cód. município'), ('zone', 'Zona'),
            ('section', 'Seção'), ('voting_place', 'Local de votação (nº)'), ('eligible', 'Aptos'), ('attendance', 'Comparecimento (BU)'),
            ('vote_events', 'Votos concluídos (log)'), ('after_17_recorded', 'Votos após 17h'), ('late_pct', '% dos votos da seção após 17h'),
            ('last_vote_t', 'Último voto'), ('winner', 'Vencedor na seção'), ('winner_party', 'Partido vencedor'),
            ('winner_pct', '% do vencedor (votos válidos)'), ('runner_up', '2º colocado'), ('runner_up_party', 'Partido 2º'),
            ('runner_up_pct', '% do 2º (votos válidos)'), ('margin_pp', 'Margem 1º–2º (p.p.)'), ('margin_votes', 'Margem 1º–2º (votos)'),
            ('late_ge_margin', 'Votos após 17h ≥ margem?'), ('log_igual_bu', 'Votos do log = comparecimento do BU?'),
            ('elig_op', 'Elegível à regra B (limpa)'), ('flag_B', 'Sinalizada pela regra B (>P99)')]
    out = []
    for uf in ORDER:
        sub = all_[all_.uf == uf]
        with pd.ExcelWriter(OUT / f'secoes_apos_17h_{uf}.xlsx', engine='xlsxwriter') as xw:
            for k, lab in RUNS:
                d = sub[(sub.k == k) & (sub.after_17_recorded > 0)].copy()
                d['last_vote_t'] = d.last_vote.astype(str).str[-8:]
                d['runner_up_pct'] = 100 * d.runner_up_votes / d.vc_sum.where(d.vc_sum > 0)
                d['late_ge_margin'] = np.where(d.after_17_recorded >= d.margin_votes, 'sim', 'não')
                d['log_igual_bu'] = np.where(d.vote_events == d.attendance, 'sim', 'não')
                d['elig_op'] = np.where(d.operational_eligible == True, 'sim', 'não')
                d['flag_B'] = np.where(d.raw_high_late == True, 'sim', 'não')
                d = d.sort_values(['after_17_recorded', 'late_pct'], ascending=False)
                t = d[[c for c, _ in cols]].rename(columns=dict(cols))
                for c in ('% dos votos da seção após 17h', '% do vencedor (votos válidos)', '% do 2º (votos válidos)', 'Margem 1º–2º (p.p.)'):
                    t[c] = t[c].round(2)
                sheet = lab.replace('º', '').replace('·', '-').replace(' ', '_')[:31]
                t.to_excel(xw, sheet_name=sheet, index=False, freeze_panes=(1, 0))
                ws = xw.sheets[sheet]
                ws.autofilter(0, 0, len(t), len(t.columns) - 1)
                ws.set_column(0, 1, 14)
                ws.set_column(2, 2, 26)
                ws.set_column(3, len(t.columns) - 1, 14)
                out.append(t)
        print('xlsx', uf, flush=True)
    full = pd.concat(out, ignore_index=True)
    full.to_csv(OUT / 'secoes_apos_17h_todas.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    return len(full)


# ------------------------------------------------------------------ statistics
def per_recorte(all_, cands):
    rows, reg = [], []
    for (uf, k, lab), df in all_.groupby(['uf', 'k', 'recorte'], sort=False):
        d = late_df(df)
        e = d[(d.operational_eligible == True)]
        L, V = e.after_17_recorded.sum(), e.vote_events.sum()
        q = e.late_pct.quantile([.5, .9, .99]).values
        srt = e.after_17_recorded.sort_values(ascending=False)
        cs = srt.cumsum() / max(L, 1)
        top1 = cs.iloc[max(int(len(srt) * .01) - 1, 0)] * 100 if L else np.nan
        top10 = cs.iloc[max(int(len(srt) * .10) - 1, 0)] * 100 if L else np.nan
        tot_votes = int(df.attendance.sum())
        lead = cands[(uf, k)]
        marg_votes = lead[0]['votes'] - lead[1]['votes']
        ge = e[e.after_17_recorded >= e.margin_votes]
        # size quintiles
        e = e.assign(sq=pd.qcut(e.eligible.rank(method='first'), 5, labels=False))
        qshare = e.groupby('sq').apply(lambda x: 100 * x.after_17_recorded.sum() / max(x.vote_events.sum(), 1)).values
        mun = e.groupby('municipality').eligible.sum()
        e = e.assign(mcls=pd.cut(e.municipality.map(mun), [0, 10000, 50000, 200000, 1e9], labels=['<10 mil', '10–50 mil', '50–200 mil', '>200 mil']))
        mshare = e.groupby('mcls').apply(lambda x: 100 * x.after_17_recorded.sum() / max(x.vote_events.sum(), 1))
        lv = pd.to_datetime(d.last_vote.astype(str).str[-8:], format='%H:%M:%S', errors='coerce')
        lvh = (lv.dt.hour + lv.dt.minute / 60 + lv.dt.second / 3600)
        rho = stats.spearmanr(e.late_pct, 100 * e.turnout)[0] if len(e) > 10 and e.late_pct.nunique() > 1 else np.nan
        rho_sz = stats.spearmanr(e.late_pct, e.eligible)[0] if len(e) > 10 and e.late_pct.nunique() > 1 else np.nan
        iv = e[e.after_17_recorded >= 20].late_interval_median_seconds.dropna()
        rows.append(dict(uf=uf, k=k, recorte=lab, sections=len(df), linked=len(d), elig_op=len(e), votes=int(V), late=int(L),
                         late_pct=100 * L / max(V, 1), sec_ge1=int((e.after_17_recorded >= 1).sum()), sec_ge10=int((e.after_17_recorded >= 10).sum()),
                         sec_ge50=int((e.after_17_recorded >= 50).sum()), sec_ge100=int((e.after_17_recorded >= 100).sum()),
                         p50=q[0], p90=q[1], p99=q[2], maxlate=e.late_pct.max(), top1_share=top1, top10_share=top10,
                         flagB=int((e.raw_high_late == True).sum()),
                         winner=lead[0]['name'], winner_party=lead[0]['party'], winner_votes=lead[0]['votes'],
                         ru=lead[1]['name'], ru_party=lead[1]['party'], ru_votes=lead[1]['votes'],
                         margin_votes=marg_votes, margin_pp=100 * marg_votes / max(int(df.valid_votes.sum()), 1),
                         late_over_margin=100 * L / max(marg_votes, 1), sec_late_ge_margin=len(ge), late_in_ge=int(ge.after_17_recorded.sum()),
                         rho_turnout=rho, rho_size=rho_sz, lv_med=lvh.median(), lv_p90=lvh.quantile(.9), lv_p99=lvh.quantile(.99),
                         sec_last_after17=100 * (lvh > 17).mean(), sec_last_after19=100 * (lvh >= 19).mean(),
                         iv_med=iv.median() if len(iv) else np.nan, iv_lt30=int((iv < 30).sum()), iv_n=len(iv),
                         **{f'q{i + 1}': qshare[i] for i in range(5)}, **{f'm_{c}': mshare.get(c, np.nan) for c in ['<10 mil', '10–50 mil', '50–200 mil', '>200 mil']}))
        # regressions: candidate share ~ late share, FE municipality / FE voting place
        r = e[(e.vc_sum > 0) & (e.eligible >= 50)].copy()
        r['late'] = r.late_pct / 10.0            # per +10 pp
        r['lelig'] = np.log(r.eligible)
        r['turn'] = r.turnout * 10.0             # per +10 pp turnout
        r['cl'] = r.zone.astype(str)
        r['place'] = r.municipality.astype(str) + '|' + r.zone.astype(str) + '|' + r.voting_place.astype(str)
        for j in (1, 2):
            r['y'] = 100 * r[f'c{j}_votes'] / r.vc_sum
            cinfo = cands[(uf, k, 'pt_pl')][j - 1]
            raw_hi = r[r.late_pct >= r.late_pct.quantile(.9)]
            raw_lo = r[r.late_pct < r.late_pct.quantile(.9)]
            for fe, cols in (('município', ['municipality']), ('local de votação', ['place'])):
                b, se, nobs, ng = fe_regression(r, 'y', cols)
                z = b / se if se and not np.isnan(se) and se > 0 else np.nan
                reg.append(dict(uf=uf, k=k, recorte=lab, cand=f"{cinfo['name']} ({cinfo['party']})", j=j, fe=fe, coef=b, se=se,
                                lo=b - 1.96 * se, hi=b + 1.96 * se, p=2 * (1 - stats.norm.cdf(abs(z))) if not np.isnan(z) else np.nan,
                                n=nobs, groups=ng,
                                raw_diff=(np.average(raw_hi.y, weights=raw_hi.vc_sum) - np.average(raw_lo.y, weights=raw_lo.vc_sum)) if len(raw_hi) and len(raw_lo) else np.nan,
                                late_range=r.late_pct.max()))
        print('stats', uf, k, flush=True)
    R = pd.DataFrame(rows)
    G = pd.DataFrame(reg)
    G['q'] = np.nan
    for fe in G.fe.unique():
        m = G.fe == fe
        G.loc[m, 'q'] = bh(G.loc[m, 'p'].values)
    return R, G


# ------------------------------------------------------------------ figures
def figures(R, G, all_):
    f, ax = plt.subplots(figsize=(11, 3.6))
    x = np.arange(len(ORDER))
    for i, (k, lab) in enumerate(RUNS):
        s = R[R.k == k].set_index('uf').reindex(ORDER)
        ax.bar(x + (i - 1) * .27, s.late_pct, .27, label=lab, color=list(M.COL.values())[i])
    ax.set_xticks(x)
    ax.set_xticklabels(ORDER)
    ax.set(ylabel='% dos votos concluídos após 17h', title='Votos após 17h por estado e pleito (seções elegíveis)')
    ax.legend()
    f.tight_layout()
    f.savefig(FIG / 'late_by_state.png', dpi=150)
    plt.close(f)
    f, ax = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    for a, (k, lab) in zip(ax, [RUNS[0], RUNS[2]]):
        for uf in ORDER:
            d = late_df(all_[(all_.uf == uf) & (all_.k == k)])
            d = d[d.operational_eligible == True]
            xs = np.sort(d.late_pct.values)
            a.step(xs, 1 - np.arange(len(xs)) / len(xs), where='post', color=STCOL[uf], label=uf, lw=1.2)
        a.set_yscale('log')
        a.set(title=lab, xlabel='% dos votos da seção após 17h', ylabel='fração de seções com ≥ x')
    ax[1].legend(ncol=2, fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'ccdf.png', dpi=150)
    plt.close(f)
    f, ax = plt.subplots(1, 3, figsize=(12, 3.6), sharey=True)
    for a, (k, lab) in zip(ax, RUNS):
        for uf in ORDER:
            s = R[(R.uf == uf) & (R.k == k)]
            if s.empty:
                continue
            s = s.iloc[0]
            a.plot(range(1, 6), [s[f'q{i}'] for i in range(1, 6)], marker='o', ms=3, color=STCOL[uf], label=uf, lw=1)
        a.set(title=lab, xlabel='quintil de aptos da seção (1 = menores, 5 = maiores)')
    ax[0].set_ylabel('% dos votos após 17h')
    ax[2].legend(ncol=2, fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'size.png', dpi=150)
    plt.close(f)
    for tag, fe in (('forest_mun', 'município'), ('forest_place', 'local de votação')):
        f, ax = plt.subplots(2, 3, figsize=(13, 7.5), sharey=True)
        for c, (k, lab) in enumerate([RUNS[0], RUNS[1], RUNS[2]]):
            for rr, j in enumerate((1, 2)):
                a = ax[rr, c]
                s = G[(G.k == k) & (G.j == j) & (G.fe == fe)].set_index('uf').reindex(ORDER)
                ypos = np.arange(len(ORDER))[::-1]
                a.errorbar(s.coef, ypos, xerr=[s.coef - s.lo, s.hi - s.coef], fmt='o', ms=4, color='#1a365d', ecolor='#7f8fa6', capsize=2)
                a.axvline(0, color='k', lw=.7)
                a.set_yticks(ypos)
                a.set_yticklabels(ORDER)

                a.set_title(lab + ' — ' + CL(j), fontsize=8)
                a.set_xlabel('variação na % do candidato por +10 p.p. de votos tardios (p.p.)', fontsize=7)
        f.suptitle(f'Associação dentro do mesmo {fe} (coef. e IC 95%); nada aqui mede causa', fontsize=10)
        f.tight_layout()
        f.savefig(FIG / f'{tag}.png', dpi=140)
        plt.close(f)
    f, ax = plt.subplots(figsize=(10, 3.4))
    for i, (k, lab) in enumerate(RUNS[:1] + RUNS[2:]):
        s = R[R.k == k].set_index('uf').reindex(ORDER)
        ax.bar(x + (i - .5) * .38, s.sec_last_after17, .38, label=lab, color=[M.COL['2022-t1'], M.COL['2026-t1']][i])
    ax.set_xticks(x)
    ax.set_xticklabels(ORDER)
    ax.set(ylabel='% das seções', title='Seções cujo último voto foi registrado após 17h00')
    ax.legend()
    f.tight_layout()
    f.savefig(FIG / 'last_after17.png', dpi=150)
    plt.close(f)


# ------------------------------------------------------------------ PDF
def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def build_pdf(R, G, all_, cands, nlist):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph(f'Votos concluídos após as 17h — 10 estados · {M.OFFICE_LABEL} · 2022 (1º e 2º turnos) e 2026 (1º turno)', H1),
          Paragraph('Escopo: BA, SP, MG, RJ, PR, RS, PE, CE, PA e SC. Fontes: boletins de urna (BU) e logs oficiais das urnas (TSE). '
                    'Medida: eventos “voto do eleitor foi computado” com horário estritamente posterior a 17:00:00 no relógio da própria urna, em seções cujo log foi '
                    'identificado sem ambiguidade, cuja contagem de votos do log coincide com o comparecimento do BU, sem inversão de relógio e com ≥50 aptos '
                    '(“seções elegíveis”). Este documento apenas descreve e testa associações; não atribui causa nem intenção.', P),
          Paragraph('Como ler: o log não identifica eleitor nem candidato, então não é possível dizer em quem votaram os eleitores que votaram após as 17h. '
                    'Todas as comparações abaixo são entre seções (ecológicas). Quem estava na fila às 17h00 tem direito de votar; votos após esse horário são esperados.', NOTE)]
    # 1. coverage & prevalence
    st += [Paragraph('1. Quantidade e peso dos votos após as 17h', H2)]
    hdr = ['UF', 'Pleito', 'Seções', 'Elegíveis', 'Votos (log)', 'Após 17h', '% após 17h', 'Seções ≥1', 'Seções ≥10', 'Seções ≥50', 'Seções ≥100', 'P50 %', 'P90 %', 'P99 %', 'Máx %']
    t = [hdr]
    for r in R.itertuples():
        t.append([r.uf, r.recorte, n(r.sections), n(r.elig_op), n(r.votes), n(r.late), n(r.late_pct, 2), n(r.sec_ge1), n(r.sec_ge10), n(r.sec_ge50), n(r.sec_ge100),
                  n(r.p50, 1), n(r.p90, 1), n(r.p99, 1), n(r.maxlate, 1)])
    st += [M.table(t, font=6.2), Paragraph('% = votos após 17h ÷ votos concluídos na seção. P50/P90/P99/Máx são percentis da distribuição desse percentual entre seções elegíveis.', SM),
           img(FIG / 'late_by_state.png', 22), PageBreak()]
    # 2. concentration & structure
    st += [Paragraph('2. Onde se concentram', H2),
           Paragraph('Concentração: parcela dos votos tardios que está no 1% e nos 10% de seções com mais votos tardios. Estrutura: o percentual tardio por quintil de tamanho da seção '
                     '(aptos) e por porte do município (soma de aptos nas seções elegíveis). Correlações de Spearman entre o % tardio da seção e (i) o comparecimento e (ii) o número de aptos.', P)]
    hdr = ['UF', 'Pleito', 'Top 1% seções: % dos votos tardios', 'Top 10%: %', 'Q1 %', 'Q2 %', 'Q3 %', 'Q4 %', 'Q5 %', 'Mun. <10 mil', '10–50 mil', '50–200 mil', '>200 mil', 'ρ comparecimento', 'ρ aptos']
    t = [hdr]
    for r in R.itertuples():
        t.append([r.uf, r.recorte, n(r.top1_share, 1), n(r.top10_share, 1), n(r.q1, 2), n(r.q2, 2), n(r.q3, 2), n(r.q4, 2), n(r.q5, 2),
                  n(R.loc[r.Index, 'm_<10 mil'], 2), n(R.loc[r.Index, 'm_10–50 mil'], 2), n(R.loc[r.Index, 'm_50–200 mil'], 2), n(R.loc[r.Index, 'm_>200 mil'], 2),
                  n(r.rho_turnout, 2), n(r.rho_size, 2)])
    st += [M.table(t, font=6.2), img(FIG / 'size.png', 24), img(FIG / 'ccdf.png', 20), PageBreak()]
    # 3. timing
    st += [Paragraph('3. Horário do último voto e ritmo após 17h', H2),
           Paragraph('Último voto por seção (hora decimal do relógio da urna) e ritmo: mediana dos intervalos entre votos consecutivos após 17h, nas seções com ≥20 votos tardios. '
                     'Intervalos curtos (<30 s) podem ocorrer com fila grande e eleitores já habilitados; não são, isoladamente, indicação de nada.', P)]
    hdr = ['UF', 'Pleito', 'Seções c/ último voto >17h %', '… ≥19h %', 'Último voto: mediana (h)', 'P90 (h)', 'P99 (h)', 'Seções ≥20 tardios', 'Mediana intervalo (s)', 'Seções c/ mediana <30 s']
    t = [hdr]
    for r in R.itertuples():
        t.append([r.uf, r.recorte, n(r.sec_last_after17, 1), n(r.sec_last_after19, 1), n(r.lv_med, 2), n(r.lv_p90, 2), n(r.lv_p99, 2), n(r.iv_n), n(r.iv_med, 0), n(r.iv_lt30)])
    st += [M.table(t, font=6.5), img(FIG / 'last_after17.png', 18), PageBreak()]
    # 4. margin magnitude
    st += [Paragraph('4. Resultado do estado e magnitude dos votos tardios frente à margem', H2),
           Paragraph('Para cada pleito: vencedor no estado, votos de cada um dos dois mais votados e a margem. “Votos tardios ÷ margem” é uma razão aritmética de ordem de grandeza '
                     '(não há como saber o voto de cada eleitor tardio): mostra o tamanho do total de votos tardios em relação à margem estadual. Também: quantas seções tiveram '
                     'votos tardios maiores ou iguais à margem local entre 1º e 2º (limite aritmético por seção, não indica que o voto foi destinado a alguém).', P)]
    hdr = ['UF', 'Pleito', 'Vencedor (estado)', 'Votos', '2º colocado', 'Votos 2º', 'Margem (votos)', 'Margem (p.p.)', 'Votos tardios', 'Tardios ÷ margem', 'Seções c/ tardios ≥ margem local', '% das elegíveis']
    t = [hdr]
    for r in R.itertuples():
        t.append([r.uf, r.recorte, f'{r.winner} ({r.winner_party})', n(r.winner_votes), f'{r.ru} ({r.ru_party})', n(r.ru_votes), n(r.margin_votes), n(r.margin_pp, 1),
                  n(r.late), n(r.late_over_margin, 1) + '%', n(r.sec_late_ge_margin), n(100 * r.sec_late_ge_margin / max(r.elig_op, 1), 1) + '%'])
    st += [M.table(t, font=6), PageBreak()]
    # 5. association with result
    st += [Paragraph('5. Associação entre % de votos tardios na seção e o resultado', H2),
           Paragraph('Pergunta: seções com mais votos tardios têm, em média, mais ou menos votos para o candidato A ou B do que seções comparáveis? Modelo: regressão da % de votos '
                     'válidos do candidato na seção contra o % de votos tardios (por +10 p.p.), com controle de log(aptos) e comparecimento, ponderada pelos votos válidos, '
                     'com efeito fixo de <b>município</b> (compara seções do mesmo município) e, como robustez, de <b>local de votação</b> (compara seções do mesmo local físico). '
                     'Erros-padrão agrupados por zona eleitoral. Candidatos A e B = ' + ('o candidato do PT e o do PL (os dois mais votados em todos os estados e pleitos)' if M.OFFICE == 'PRESIDENTE' else 'o 1º e o 2º colocados no estado em cada pleito') + '. Valor-p corrigido por Benjamini–Hochberg '
                     'dentro de cada especificação (q). “Dif. bruta” = diferença simples ponderada entre seções no decil mais tardio e as demais (sem controles).', P),
           Paragraph('Limites: associação entre seções, não entre eleitores; outros fatores (zona urbana/rural, bairro, tamanho, equipamento, horário de chegada dos eleitores) podem '
                     'afetar tanto a fila quanto o voto. Sem pareamento nem controles demográficos completos (idade, escolaridade, biometria, modelo de urna) — pendentes.', NOTE),
           img(FIG / 'forest_mun.png', 25), PageBreak(), img(FIG / 'forest_place.png', 25), PageBreak()]
    for fe in ('município', 'local de votação'):
        st += [Paragraph(f'Coeficientes — efeito fixo de {fe} (variação em p.p. na % do candidato por +10 p.p. de votos tardios)', H2)]
        hdr = ['UF', 'Pleito', 'Candidato', 'Coef.', 'IC 95%', 'q (BH)', 'Dif. bruta (decil mais tardio − demais), p.p.', 'Seções', 'Grupos']
        t = [hdr]
        for r in G[G.fe == fe].sort_values(['k', 'j', 'uf']).itertuples():
            t.append([r.uf, r.recorte, r.cand, n(r.coef, 2), f'[{n(r.lo, 2)}; {n(r.hi, 2)}]', n(r.q, 3), n(r.raw_diff, 2), n(r.n), n(r.groups)])
        st += [M.table(t, font=6.2), PageBreak()]
    # 6. summary (computed)
    st += [Paragraph('6. Síntese dos números (gerada automaticamente a partir das tabelas)', H2)]
    lines = []
    for k, lab in RUNS:
        s = R[R.k == k]
        if s.empty:
            continue
        lines.append(f'<b>{lab}</b>: percentual de votos após 17h entre {n(s.late_pct.min(), 2)}% ({s.loc[s.late_pct.idxmin(), "uf"]}) e {n(s.late_pct.max(), 2)}% '
                     f'({s.loc[s.late_pct.idxmax(), "uf"]}); no conjunto, {n(s.late.sum())} votos tardios em {n(s.votes.sum())} votos concluídos '
                     f'({n(100 * s.late.sum() / s.votes.sum(), 2)}%). Maior razão votos tardios ÷ margem estadual: {n(s.late_over_margin.max(), 1)}% '
                     f'({s.loc[s.late_over_margin.idxmax(), "uf"]}).')
    for fe in ('município', 'local de votação'):
        g = G[(G.fe == fe) & G.coef.notna()]
        sig = g[g.q < .05]
        lines.append(f'<b>Efeito fixo de {fe}</b>: {len(g)} estimativas; {len(sig)} com q&lt;0,05 ({int((sig.coef > 0).sum())} positivas, {int((sig.coef < 0).sum())} negativas). '
                     f'Coeficientes entre {n(g.coef.min(), 2)} e {n(g.coef.max(), 2)} p.p. por +10 p.p. de votos tardios (mediana {n(g.coef.median(), 2)}). '
                     f'Intervalos de confiança que incluem zero: {int(((g.lo <= 0) & (g.hi >= 0)).sum())} de {len(g)}.')
    g1 = G[(G.k != '2022-t2') & G.coef.notna()]
    for fe in ('município', 'local de votação'):
        s = g1[g1.fe == fe]
        lines.append(f'<b>Somente 1º turnos (2022 e 2026), efeito fixo de {fe}</b>: |coeficiente| mediano {n(s.coef.abs().median(), 2)} p.p. por +10 p.p. de votos tardios '
                     f'(mín. {n(s.coef.abs().min(), 2)}, máx. {n(s.coef.abs().max(), 2)}); {int((s.q < .05).sum())} de {len(s)} estimativas com q&lt;0,05.')
    a = g1[g1.fe == 'município'].coef.abs().median()
    b = g1[g1.fe == 'local de votação'].coef.abs().median()
    lines.append(f'Ao comparar seções do <b>mesmo local de votação</b> (em vez do mesmo município), o |coeficiente| mediano cai de {n(a, 2)} para {n(b, 2)} p.p. '
                 f'(redução de {n(100 * (1 - b / a), 0)}%): a maior parte da associação entre % tardio e voto aparece entre locais/bairros dentro do município; '
                 f'a parcela restante entre seções do mesmo local não foi explicada por nenhuma variável disponível neste estudo.')
    big = R[R.late_over_margin >= 100]
    lines.append(f'Pleitos em que o total de votos tardios do estado supera a margem estadual entre os dois mais votados: {len(big)} de {len(R)}'
                 + (' (' + ', '.join(f'{r.uf} {r.recorte}: {n(r.late_over_margin, 0)}%' for r in big.itertuples()) + ')' if len(big) else '')
                 + '. É uma razão de ordem de grandeza, não um cálculo de efeito: os votos tardios, como os demais, se dividem entre todos os candidatos.')
    cc = G[(G.fe == 'município') & G.coef.notna()]
    for k, lab in RUNS:
        for j in (1, 2):
            s = cc[(cc.k == k) & (cc.j == j)]
            if len(s):
                lines.append(f'{lab}, {CL(j)}: sinal positivo em {int((s.coef > 0).sum())} de {len(s)} estados; '
                             f'significativo (q&lt;0,05) em {int((s.q < .05).sum())}.')
    for l in lines:
        st.append(Paragraph('• ' + l, P))
    st += [Paragraph('Leitura honesta dos limites', H2)]
    for t_ in ['Nenhum resultado aqui indica fraude, irregularidade ou favorecimento; também não os descarta. Votos tardios são consequência esperada de fila no encerramento.',
               'Associação estatística entre seções não é efeito sobre eleitores; fila é maior em seções grandes, urbanas e de maior comparecimento, o que também correlaciona com perfil de voto. '
               'Os controles aqui usados (município ou local de votação, tamanho e comparecimento) reduzem, mas não eliminam, essa confusão.',
               'Não testado por falta de dados nesta etapa: se o perfil do eleitorado da seção (faixa etária, escolaridade, biometria cadastrada) explica a diferença que sobra entre seções do '
               'mesmo local de votação. O TSE publica o perfil do eleitor por seção; incorporá-lo é o passo seguinte natural.',
               'A regra do horário usa o relógio registrado na urna, não calibrado de forma independente; seções com inversão de relógio ou log divergente do BU ficam fora das medidas “elegíveis”.',
               'Em 2022/2º turno quase não há votos tardios (a distribuição é quase toda zero), então as estimativas desse pleito se apoiam em pouquíssimas seções, têm escala instável e '
               'intervalos muito largos; a “dif. bruta” fica indisponível porque o decil mais tardio coincide com zero.',
               'Mais de 100 estimativas são apresentadas; o valor q corrige a multiplicidade apenas dentro de cada especificação.']:
        st.append(Paragraph('• ' + t_, P))
    # annex: top sections
    st += [PageBreak(), Paragraph('Anexo A — 10 seções com mais votos após 17h em cada pleito (lista completa nos arquivos de planilha)', H2)]
    for (uf, k, lab), df in all_.groupby(['uf', 'k', 'recorte'], sort=False):
        d = late_df(df)
        d = d[d.operational_eligible == True].sort_values('after_17_recorded', ascending=False).head(10)
        t = [['Município', 'Zona', 'Seção', 'Local', 'Aptos', 'Votos', 'Após 17h', '% após', 'Último voto', 'Vencedor', '% venc.', '2º', '% 2º', 'Margem p.p.']]
        for x in d.itertuples():
            t.append([x.municipality_name, str(x.zone), str(x.section), str(x.voting_place), n(x.eligible), n(x.vote_events), n(x.after_17_recorded), n(x.late_pct, 1),
                      str(x.last_vote)[-8:], f'{x.winner_party}', n(x.winner_pct, 1), f'{x.runner_up_party}', n(100 * x.runner_up_votes / x.vc_sum, 1) if x.vc_sum else '—', n(x.margin_pp, 1)])
        st += [Paragraph(f'{NAMES[uf]} · {lab}', M.P), M.table(t, font=6.2), Spacer(1, 4)]
    st += [Paragraph(f'Anexo B — lista completa: {n(nlist)} seções com ≥1 voto após 17h em 10 arquivos .xlsx (um por estado, uma aba por pleito) e no CSV consolidado, '
                     'com local de votação, % de votos após 17h, vencedor e 2º colocado com percentuais, margem em p.p. e em votos, e sinalizações.', P)]

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo e estatístico — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'ANALISE_VOTOS_APOS_17H.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm, title='Votos após 17h — 10 estados').build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    all_, cands = load_all()
    nlist = export_lists(all_)
    R, G = per_recorte(all_, cands)
    R.to_csv(OUT / 'resumo_por_pleito.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    G.to_csv(OUT / 'associacao_resultado.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    figures(R, G, all_)
    build_pdf(R, G, all_, cands, nlist)
    print('ok', nlist)
