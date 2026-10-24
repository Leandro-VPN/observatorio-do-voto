"""Mayor (2012-2024) vs President/Governor: late votes, manual (non-biometric) habilitation, closing time, turnout; same-section persistence across election types.

Stage 1 (BU only): manual BU count, closing time, turnout for 2018/2022/2026 (general) and 2020/2024 (municipal).
Stage 2 (needs 2024 urn logs): votes after 17:00, log-based manual share, cross-type persistence, association with the leading candidate.
"""
import os
import sys
from itertools import combinations
from pathlib import Path

import duckdb
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

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M

OUT = Path('relatorios/prefeito')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
KEY = ['municipality', 'zone', 'section']
# (election id, label, type, source)
ELECS = [('P2018', 'Presidente 2018', 'geral', 'PRESIDENTE', 2018), ('P2022', 'Presidente 2022', 'geral', 'PRESIDENTE', 2022), ('P2026', 'Presidente 2026', 'geral', 'PRESIDENTE', 2026),
         ('M2020', 'Prefeito 2020', 'municipal', 'PREFEITO', 2020), ('M2024', 'Prefeito 2024', 'municipal', 'PREFEITO', 2024)]
PAL = {'P2018': '#9ecae1', 'P2022': '#3182bd', 'P2026': '#08519c', 'M2020': '#fdae6b', 'M2024': '#e6550d'}
rng = np.random.default_rng(20261016)
REPS = 1000


def n(x, d=0):
    return M.n(x, d)


def adir(office, uf, year, turn=1):
    if office == 'PRESIDENTE' and year in (2022, 2026):
        return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / f'{year}-t{turn}' / 'analysis'
    return Path('research/analysis') / office / uf / f'{year}-t{turn}'


def closing_minutes(s):
    t = pd.to_datetime(s, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    t = t.fillna(pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce'))
    return t.dt.hour * 60 + t.dt.minute + t.dt.second / 60 - 1020


def units_from_bu(uf, year, office='PREFEITO', turn=1):
    f = Path('research/bu') / f'{year}-t{turn}' / f'{uf}_{office}.parquet'
    d = duckdb.connect()
    d.read_parquet(str(f)).create_view('b')
    cols = {r[0] for r in d.execute('DESCRIBE b').fetchall()}
    nh = next((c for c in ('QT_ELEITORES_BIOMETRIA_NH', 'QT_ELEI_BIOM_SEM_HABILITACAO') if c in cols), None)
    q = f'''SELECT cast(CD_MUNICIPIO AS INT) municipality,cast(NR_ZONA AS INT) zone,cast(NR_SECAO AS INT) section,max(NR_LOCAL_VOTACAO) voting_place,
        max(cast(QT_APTOS AS BIGINT)) eligible,max(cast(QT_COMPARECIMENTO AS BIGINT)) attendance,
        {f'max(try_cast({nh} AS BIGINT))' if nh else 'CAST(NULL AS BIGINT)'} manual_bu,
        {'max(DT_ENCERRAMENTO)' if 'DT_ENCERRAMENTO' in cols else 'CAST(NULL AS VARCHAR)'} closure_bu FROM b GROUP BY ALL'''
    return d.execute(q).df()


def load_units(eid, office, year):
    frames = []
    for uf in ORDER:
        f = adir(office, uf, year) / 'sections.parquet'
        if f.exists():
            d = pd.read_parquet(f, columns=KEY + ['voting_place', 'eligible', 'attendance', 'manual_bu', 'closure_bu'])
        else:
            d = units_from_bu(uf, year) if office == 'PREFEITO' else None
        d['uf'] = uf
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d['voting_place'] = d.voting_place.astype(str)
    d['turnout'] = 100 * d.attendance / d.eligible.where(d.eligible > 0)
    d['manual_pct'] = 100 * d.manual_bu / d.attendance.where(d.attendance >= 50)
    d['close_min'] = closing_minutes(d.closure_bu).clip(lower=-30)
    return d


def stage1():
    U = {eid: load_units(eid, office, year) for eid, _, _, office, year in ELECS}
    rows, srows = [], []
    for eid, lab, typ, office, year in ELECS:
        d = U[eid]
        e = d[d.eligible >= 50]
        mun = d.groupby(['uf', 'municipality']).eligible.transform('sum')
        d['mcls'] = pd.cut(mun, [0, 10000, 50000, 200000, 1e12], labels=['<10 mil', '10–50 mil', '50–200 mil', '>200 mil'])
        e = d[d.eligible >= 50]
        row = dict(eid=eid, lab=lab, typ=typ, sections=len(d), eligible=int(d.eligible.sum()), turnout=100 * d.attendance.sum() / d.eligible.sum(),
                   manual_pooled=100 * d.manual_bu.sum() / d.attendance.sum(), manual_med=e.manual_pct.median(), manual_p90=e.manual_pct.quantile(.9),
                   manual_p99=e.manual_pct.quantile(.99), manual_zero=100 * (e.manual_bu == 0).mean(),
                   close_med=e.close_min.median(), close_gt15=100 * (e.close_min > 15).mean(), close_gt60=100 * (e.close_min > 60).mean(),
                   close_p99=e.close_min.quantile(.99))
        for c in ['<10 mil', '10–50 mil', '50–200 mil', '>200 mil']:
            s = d[d.mcls == c]
            row[f'manual_{c}'] = 100 * s.manual_bu.sum() / s.attendance.sum() if len(s) else np.nan
            row[f'close60_{c}'] = 100 * (s[s.eligible >= 50].close_min > 60).mean() if len(s) else np.nan
        rows.append(row)
        for uf in ORDER:
            s = d[d.uf == uf]
            se = s[s.eligible >= 50]
            srows.append(dict(eid=eid, lab=lab, uf=uf, sections=len(s), turnout=100 * s.attendance.sum() / s.eligible.sum(), manual=100 * s.manual_bu.sum() / s.attendance.sum(),
                              close_gt60=100 * (se.close_min > 60).mean(), close_med=se.close_min.median()))
    return U, pd.DataFrame(rows), pd.DataFrame(srows)


def match(a, b, lo=.6, hi=1.67):
    m = a.merge(b, on=KEY + ['uf'], suffixes=('_1', '_2'))
    m = m[(m.voting_place_1 == m.voting_place_2) & (m.eligible_2 / m.eligible_1).between(lo, hi)]
    return m


def spearman(x, y):
    ok = x.notna() & y.notna()
    if ok.sum() < 30 or x[ok].nunique() < 3 or y[ok].nunique() < 3:
        return np.nan
    return stats.spearmanr(x[ok], y[ok])[0]


def flag_overlap(m, col):
    """Permutation within municipality of the top-1% flag (state-specific P99) overlap between two elections."""
    f = {}
    for k in ('1', '2'):
        thr = m.groupby('uf')[f'{col}_{k}'].transform(lambda s: s.quantile(.99))
        f[k] = ((m[f'{col}_{k}'] > thr) & m[f'{col}_{k}'].notna()).values
    grp = pd.factorize(m.uf + '|' + m.municipality.astype(str))[0].astype(float)
    ok = (m[f'{col}_1'].notna() & m[f'{col}_2'].notna()).values
    f1, f2, g = f['1'][ok], f['2'][ok], grp[ok]
    if f1.sum() < 10 or f2.sum() < 10:
        return None
    order0 = np.argsort(g, kind='stable')
    f1_0 = f1[order0]
    obs = int((f1 & f2).sum())
    null = np.empty(REPS)
    for i in range(REPS):
        o1 = np.argsort(g + rng.random(len(g)), kind='stable')
        null[i] = (f1_0 & f2[o1]).sum()
    return dict(N=int(ok.sum()), n1=int(f1.sum()), n2=int(f2.sum()), obs=obs, exp=null.mean(), ratio=obs / null.mean() if null.mean() else np.nan, p=(1 + (null >= obs).sum()) / (REPS + 1))


def stage1_persistence(U):
    ids = [e[0] for e in ELECS]
    typ = {e[0]: e[2] for e in ELECS}
    lab = {e[0]: e[1] for e in ELECS}
    yr = {e[0]: e[4] for e in ELECS}
    pairs = [('P2018', 'M2020'), ('M2020', 'P2022'), ('P2022', 'M2024'), ('M2024', 'P2026'), ('P2018', 'P2022'), ('M2020', 'M2024'), ('P2022', 'P2026'), ('P2018', 'P2026')]
    rows, ov = [], []
    for a, b in pairs:
        m = match(U[a], U[b])
        row = dict(pair=f'{lab[a]} → {lab[b]}', kind=f'{typ[a]}→{typ[b]}', gap=yr[b] - yr[a], n=len(m), pct=100 * len(m) / min(len(U[a]), len(U[b])),
                   rho_size=spearman(m.eligible_1, m.eligible_2), rho_turnout=spearman(m.turnout_1, m.turnout_2), rho_manual=spearman(m.manual_pct_1, m.manual_pct_2),
                   rho_close=spearman(m.close_min_1, m.close_min_2))
        m['place'] = m.uf + '|' + m.municipality.astype(str) + '|' + m.zone.astype(str) + '|' + m.voting_place_1
        w = m[m.groupby('place').turnout_1.transform('size') >= 2].copy()
        for c in ('manual_pct', 'close_min'):
            row[f'rho_{c}_place'] = spearman(w[f'{c}_1'] - w.groupby('place')[f'{c}_1'].transform('mean'), w[f'{c}_2'] - w.groupby('place')[f'{c}_2'].transform('mean'))
        rows.append(row)
        for col, nm in (('manual_pct', 'manual (BU)'), ('close_min', 'encerramento tardio (BU)')):
            r = flag_overlap(m, col)
            if r:
                ov.append(dict(pair=row['pair'], kind=row['kind'], sinal=nm, **r))
        print('persist', row['pair'], flush=True)
    return pd.DataFrame(rows), pd.DataFrame(ov)


def figures1(R, S):
    f, ax = plt.subplots(1, 3, figsize=(13, 3.8))
    x = np.arange(len(ORDER))
    w = .16
    for a, col, ttl in zip(ax, ['manual', 'close_gt60', 'turnout'], ['Habilitação manual — BU (% do comparecimento)', 'Seções encerradas >60 min após 17h (%)', 'Comparecimento (%)']):
        for i, e in enumerate(ELECS):
            s = S[S.eid == e[0]].set_index('uf').reindex(ORDER)
            a.bar(x + (i - 2) * w, s[col], w, color=PAL[e[0]], label=e[1])
        a.set_xticks(x)
        a.set_xticklabels(ORDER, fontsize=7)
        a.set_title(ttl, fontsize=8)
    ax[2].set_ylim(60, 90)
    ax[0].legend(fontsize=6)
    f.tight_layout()
    f.savefig(FIG / 'bu_niveis.png', dpi=150)
    plt.close(f)


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def pdf(R, S, PR, OV, extra=None):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Eleição de prefeito × eleições de presidente: o padrão se repete?', H1),
          Paragraph('Mesmos 10 estados (BA, SP, MG, RJ, PR, RS, PE, CE, PA e SC) e 3.710 municípios. Comparamos o 1º turno de prefeito (2020 e 2024) com o 1º turno de presidente (2018, 2022 e 2026). '
                    'Do boletim de urna (BU): comparecimento, habilitação manual (“sem biometria”) e horário de encerramento da seção. Votos após 17h exigem log de urna: existe para 2022, 2026 e 2024 '
                    '(prefeito); não existe para 2012, 2016, 2018 e 2020.', P),
          Paragraph('Atenção ao que “sem biometria” mede: o BU registra eleitores <b>com biometria cadastrada que foram habilitados manualmente pelo mesário</b> (a digital não habilitou). '
                    'Eleitores sem biometria cadastrada usam outra rotina e não entram nessa contagem. Na eleição municipal a urna tem 2 cargos (prefeito e vereador); na geral há 5 ou 6; '
                    'isso muda o tempo de votação e, portanto, a fila.', NOTE),
          Paragraph('1. Níveis (todos os estados juntos)', H2)]
    t = [['Eleição', 'Seções', 'Comparecimento %', 'Manual BU % (agregado)', 'Mediana por seção %', 'P90 %', 'P99 %', '% seções com 0 manual', 'Mediana min. até encerrar', '% encerradas >15 min', '% encerradas >60 min']]
    for r in R.itertuples():
        t.append([r.lab, n(r.sections), n(r.turnout, 1), n(r.manual_pooled, 2), n(r.manual_med, 2), n(r.manual_p90, 1), n(r.manual_p99, 1), n(r.manual_zero, 1), n(r.close_med, 1), n(r.close_gt15, 1), n(r.close_gt60, 1)])
    st += [M.table(t, font=6.8), Paragraph('Por porte do município (aptos totais do município):', M.P)]
    t = [['Eleição'] + [f'Manual % {c}' for c in ['<10 mil', '10–50 mil', '50–200 mil', '>200 mil']] + [f'>60 min % {c}' for c in ['<10 mil', '10–50 mil', '50–200 mil', '>200 mil']]]
    for r in R.itertuples():
        t.append([r.lab] + [n(R.loc[r.Index, f'manual_{c}'], 2) for c in ['<10 mil', '10–50 mil', '50–200 mil', '>200 mil']]
                 + [n(R.loc[r.Index, f'close60_{c}'], 1) for c in ['<10 mil', '10–50 mil', '50–200 mil', '>200 mil']])
    st += [M.table(t, font=6.8), img(FIG / 'bu_niveis.png', 24), PageBreak()]
    st += [Paragraph('2. Por estado', H2)]
    t = [['UF'] + [f'{e[1]}: manual % / >60 min %' for e in ELECS]]
    for uf in ORDER:
        row = [uf]
        for e in ELECS:
            s = S[(S.eid == e[0]) & (S.uf == uf)].iloc[0]
            row.append(f'{n(s.manual, 1)} / {n(s.close_gt60, 1)}')
        t.append(row)
    st += [M.table(t, font=7)]
    st += [Paragraph('3. As mesmas seções repetem o padrão, mesmo trocando o tipo de eleição?', H2),
           Paragraph('Correlação (Spearman) entre eleições, nas mesmas seções (mesma chave município-zona-seção, mesmo local, aptos entre 0,6× e 1,67×). '
                     'Se seções que têm muita habilitação manual ou demoram a encerrar numa eleição geral também têm numa municipal, as correlações “geral→municipal” ficam próximas às “geral→geral”.', P)]
    t = [['Par', 'Tipo', 'Anos', 'Seções pareadas', '% pareadas', 'ρ aptos', 'ρ comparecimento', 'ρ manual BU', '… desvio do local', 'ρ minutos até encerrar', '… desvio do local']]
    for r in PR.itertuples():
        t.append([r.pair, r.kind, n(r.gap), n(r.n), n(r.pct, 1), n(r.rho_size, 2), n(r.rho_turnout, 2), n(r.rho_manual, 2), n(r.rho_manual_pct_place, 2), n(r.rho_close, 2), n(r.rho_close_min_place, 2)])
    st += [M.table(t, font=6.3)]
    t = [['Par', 'Sinal (top 1% do estado)', 'Seções comparáveis', 'Sinalizadas A', 'Sinalizadas B', 'Sobreposição observada', 'Esperado ao acaso (mesmo município)', 'Razão', 'p']]
    for r in OV.itertuples():
        t.append([r.pair, r.sinal, n(r.N), n(r.n1), n(r.n2), n(r.obs), n(r.exp, 1), n(r.ratio, 1), n(r.p, 4)])
    st += [Paragraph('Sobreposição do 1% mais extremo de cada estado:', M.P), M.table(t, font=6.3)]
    if extra:
        st += extra
    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'COMPARATIVO_PREFEITO_X_PRESIDENTE.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    U, R, S = stage1()
    figures1(R, S)
    PR, OV = stage1_persistence(U)
    for nm, df in (('niveis_bu', R), ('por_estado_bu', S), ('persistencia_entre_tipos', PR), ('sobreposicao_entre_tipos', OV)):
        df.round(4).to_csv(OUT / f'{nm}.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    pdf(R, S, PR, OV)
    print('ok')
