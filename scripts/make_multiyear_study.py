"""Multi-year (2014, 2018, 2022, 2026) BU-based persistence study for one office (PRESIDENTE or GOVERNADOR), 10 states.

Indicators available from BU only: turnout (all years), BU manual-habilitation count (2018+), BU closing time (2018+; a proxy for late voting).
Votes after 17:00 per se require urn logs (2022/2026 only; see the log-based studies). Descriptive; no causal claims.
"""
import os
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

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M

OFFICE = M.OFFICE
OUT = Path('relatorios/multiano') if OFFICE == 'PRESIDENTE' else Path('relatorios/governador/multiano')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
YEARS = [2014, 2018, 2022, 2026]
KEY = ['municipality', 'zone', 'section']
REPS = 1000
rng = np.random.default_rng(20261016)
ALIAS = {'PMDB': 'MDB', 'DEM': 'UNIÃO', 'PRB': 'REPUBLICANOS', 'PPS': 'CIDADANIA', 'PT do B': 'AVANTE', 'PTN': 'PODE', 'SOLIDARIEDADE': 'SD',
         'PEN': 'PATRI', 'PATRI': 'PRD', 'PTC': 'AGIR', 'PSDC': 'DC', 'PR': 'PL', 'PSL': 'UNIÃO', 'PC do B': 'PCdoB'}


def n(x, d=0):
    return M.n(x, d)


def adir(uf, year, turn):
    if OFFICE == 'PRESIDENTE' and year in (2022, 2026):
        return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / f'{year}-t{turn}' / 'analysis'
    return Path('research/analysis') / OFFICE / uf / f'{year}-t{turn}'


def closing_minutes(s):
    t = pd.to_datetime(s, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    t = t.fillna(pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce'))
    return t.dt.hour * 60 + t.dt.minute + t.dt.second / 60 - 1020


def load(turns=(1, 2)):
    data = {}
    for uf in ORDER:
        for year in YEARS:
            for turn in turns:
                if turn == 2 and year == 2026:
                    continue
                f = adir(uf, year, turn)
                if not (f / 'summary.json').exists():
                    continue
                cols = KEY + ['municipality_name', 'voting_place', 'eligible', 'attendance', 'turnout', 'manual_bu', 'closure_bu', 'opening_bu', 'raw_high_turnout',
                              'winner_party', 'winner_pct', 'margin_pp', 'valid_votes', 'state_median']
                d = pd.read_parquet(f / 'sections.parquet', columns=cols)
                d['voting_place'] = d.voting_place.astype(str)
                d['turnout_pct'] = 100 * d.turnout
                d['manual_pct'] = 100 * d.manual_bu / d.attendance.where(d.attendance >= 50)
                d['close_min'] = closing_minutes(d.closure_bu).clip(lower=-30)
                d['open_late_min'] = closing_minutes(d.opening_bu) + 540        # minutes after 08:00
                d['party'] = d.winner_party.replace(ALIAS)
                big = d.eligible >= 50
                if d.manual_pct.notna().any():
                    d['Cb'] = (d.manual_pct > d.loc[big, 'manual_pct'].quantile(.99)).where(d.manual_pct.notna())
                else:
                    d['Cb'] = np.nan
                if d.close_min.notna().any():
                    d['Bc'] = (d.close_min > d.loc[big, 'close_min'].quantile(.99)).where(d.close_min.notna() & big)
                else:
                    d['Bc'] = np.nan
                d['A'] = d.raw_high_turnout
                d['uf'] = uf
                data[(uf, year, turn)] = d
        print('loaded', uf, flush=True)
    return data


def pair(data, uf, y1, y2, lo=.6, hi=1.67):
    a, b = data[(uf, y1, 1)], data[(uf, y2, 1)]
    m = a.merge(b, on=KEY, suffixes=('_1', '_2'))
    same = m.voting_place_1 == m.voting_place_2
    m['strict'] = same & (m.eligible_2 / m.eligible_1).between(lo, hi)
    m['same_place'] = same
    return m, len(a), len(b)


def spearman(x, y):
    ok = x.notna() & y.notna()
    if ok.sum() < 30 or x[ok].nunique() < 3 or y[ok].nunique() < 3:
        return np.nan
    return stats.spearmanr(x[ok], y[ok])[0]


def demean(m, col, grp):
    return m[col] - m.groupby(grp)[col].transform('mean')


def perm_overlap(group, f1, f2, reps):
    f1, f2 = f1.astype(bool), f2.astype(bool)
    order0 = np.argsort(group, kind='stable')
    f1_0 = f1[order0]
    obs = int((f1 & f2).sum())
    null = np.empty(reps)
    for i in range(reps):
        order1 = np.argsort(group + rng.random(len(group)), kind='stable')
        null[i] = (f1_0 & f2[order1]).sum()
    return obs, null


def build():
    data = load()
    PAIRS = list(combinations(YEARS, 2))
    # --------------------------------------------- availability
    avail = []
    for y in YEARS:
        ex = [data[(uf, y, 1)] for uf in ORDER if (uf, y, 1) in data]
        avail.append(dict(year=y, states=len(ex), sections=sum(len(d) for d in ex), manual=any(d.manual_pct.notna().any() for d in ex),
                          closing=any(d.close_min.notna().any() for d in ex)))
    AV = pd.DataFrame(avail)
    # --------------------------------------------- pair metrics
    met, pooled = [], {}
    for uf in ORDER:
        for y1, y2 in PAIRS:
            if (uf, y1, 1) not in data or (uf, y2, 1) not in data:
                continue
            m, n1, n2 = pair(data, uf, y1, y2)
            s = m[m.strict].copy()
            row = dict(uf=uf, y1=y1, y2=y2, n1=n1, n2=n2, key=len(m), same_place=int(m.same_place.sum()), strict=len(s), pct_strict=100 * len(s) / min(n1, n2))
            row['rho_turnout'] = spearman(s.turnout_pct_1, s.turnout_pct_2)
            s['place'] = s.municipality.astype(str) + '|' + s.zone.astype(str) + '|' + s.voting_place_1
            sw = s[s.groupby('place').turnout_pct_1.transform('size') >= 2].copy()
            row['rho_turnout_place'] = spearman(demean(sw, 'turnout_pct_1', 'place'), demean(sw, 'turnout_pct_2', 'place'))
            row['rho_manual'] = spearman(s.manual_pct_1, s.manual_pct_2)
            row['rho_manual_place'] = spearman(demean(sw, 'manual_pct_1', 'place'), demean(sw, 'manual_pct_2', 'place')) if sw.manual_pct_1.notna().any() else np.nan
            row['rho_close'] = spearman(s.close_min_1, s.close_min_2)
            row['rho_close_place'] = spearman(demean(sw, 'close_min_1', 'place'), demean(sw, 'close_min_2', 'place')) if sw.close_min_1.notna().any() else np.nan
            row['rho_size'] = spearman(s.eligible_1, s.eligible_2)
            for nm, c in (('turnout', 'turnout_pct'), ('manual', 'manual_pct'), ('close', 'close_min')):
                if s[f'{c}_1'].notna().any() and s[f'{c}_2'].notna().any():
                    g = s.groupby('zone')[[f'{c}_1', f'{c}_2']].mean()
                    row[f'rho_zone_{nm}'] = spearman(g[f'{c}_1'], g[f'{c}_2'])
                    g = s.groupby('municipality')[[f'{c}_1', f'{c}_2']].mean()
                    row[f'rho_mun_{nm}'] = spearman(g[f'{c}_1'], g[f'{c}_2'])
                else:
                    row[f'rho_zone_{nm}'] = row[f'rho_mun_{nm}'] = np.nan
            w = s[(s.party_1 != 'EMPATE') & (s.party_2 != 'EMPATE')]
            row['winner_same_pct'] = 100 * (w.party_1 == w.party_2).mean() if len(w) else np.nan
            row['winner_pct_rho'] = spearman(s.winner_pct_1, s.winner_pct_2)
            met.append(row)
            pooled.setdefault((y1, y2), []).append(s.assign(uf=uf))
        print('metrics', uf, flush=True)
    MET = pd.DataFrame(met)
    # --------------------------------------------- permutation tests per consecutive pair
    perm = []
    for (y1, y2), lst in pooled.items():
        if (y1, y2) not in [(2014, 2018), (2018, 2022), (2022, 2026)]:
            continue
        allp = pd.concat(lst, ignore_index=True)
        grp = pd.factorize(allp.uf + '|' + allp.municipality.astype(str))[0].astype(float)
        for flag, nm in (('A', 'A — comparecimento alto'), ('Cb', 'C — manual alto (BU)'), ('Bc', 'B — encerramento tardio (BU, proxy)')):
            f1, f2 = allp[f'{flag}_1'], allp[f'{flag}_2']
            ok = f1.notna() & f2.notna()
            if ok.sum() < 100:
                continue
            f1b, f2b = f1[ok].astype(bool).values, f2[ok].astype(bool).values
            obs, null = perm_overlap(grp[ok.values], f1b, f2b, REPS)
            perm.append(dict(pair=f'{y1} → {y2}', flag=nm, N=int(ok.sum()), n1=int(f1b.sum()), n2=int(f2b.sum()), obs=obs, null_mean=null.mean(),
                             p975=np.quantile(null, .975), ratio=obs / null.mean() if null.mean() else np.nan, p=(1 + (null >= obs).sum()) / (REPS + 1)))
            print('perm', y1, y2, flag, obs, round(null.mean(), 1), flush=True)
    PERM = pd.DataFrame(perm)
    # --------------------------------------------- recurrence across the 4 years (flag A)
    rec = []
    for uf in ORDER:
        if not all((uf, y, 1) in data for y in YEARS):
            continue
        ms = data[(uf, 2014, 1)][KEY + ['voting_place', 'A']].rename(columns={'voting_place': 'vp_2014', 'A': 'A_2014'})
        for y in YEARS[1:]:
            ms = ms.merge(data[(uf, y, 1)][KEY + ['voting_place', 'A']].rename(columns={'voting_place': f'vp_{y}', 'A': f'A_{y}'}), on=KEY)
        same = (ms.vp_2014 == ms.vp_2018) & (ms.vp_2018 == ms.vp_2022) & (ms.vp_2022 == ms.vp_2026)
        F = ms.loc[same, [f'A_{y}' for y in YEARS]].astype(float).dropna().astype(bool)
        p = F.mean().values
        cnt = F.sum(axis=1).value_counts().reindex(range(5), fill_value=0)
        pdist = np.array([1.0])
        for pi in p:
            pdist = np.convolve(pdist, [1 - pi, pi])
        rec.append(dict(uf=uf, N=len(F), **{f'obs{i}': int(cnt[i]) for i in range(5)}, **{f'exp{i}': pdist[i] * len(F) for i in range(5)}))
    REC = pd.DataFrame(rec)
    # --------------------------------------------- summaries per election (all rounds)
    srows = []
    for (uf, y, t), d in data.items():
        e = d[d.eligible >= 50]
        srows.append(dict(uf=uf, year=y, turn=t, sections=len(d), eligible=int(d.eligible.sum()), turnout=100 * d.attendance.sum() / d.eligible.sum(),
                          manual_pct=100 * d.manual_bu.sum() / d.attendance.sum() if d.manual_bu.notna().any() else np.nan,
                          close_med=e.close_min.median() if e.close_min.notna().any() else np.nan,
                          close_gt15=100 * (e.close_min > 15).mean() if e.close_min.notna().any() else np.nan,
                          close_gt60=100 * (e.close_min > 60).mean() if e.close_min.notna().any() else np.nan,
                          A=int((d.A == True).sum()), winner_party=d.party.value_counts().index[0], winner_share=100 * d.party.value_counts().iloc[0] / len(d)))
    SUM = pd.DataFrame(srows).sort_values(['uf', 'year', 'turn'])
    # --------------------------------------------- proxy validation (2022/2026 with logs, presidential analysis has logs; governor too)
    val = []
    for uf in ORDER:
        for y in (2022, 2026):
            f = adir(uf, y, 1)
            if not (f / 'summary.json').exists():
                continue
            d = pd.read_parquet(f / 'sections.parquet', columns=['closure_bu', 'operational_eligible', 'after_17_recorded'])
            d = d[d.operational_eligible == True]
            if len(d) < 100:
                continue
            val.append(dict(uf=uf, year=y, rho=spearman(closing_minutes(d.closure_bu).clip(lower=0), d.after_17_recorded), n=len(d)))
    VAL = pd.DataFrame(val)
    # --------------------------------------------- exports
    OUT.mkdir(parents=True, exist_ok=True)
    MET.round(4).to_csv(OUT / 'persistencia_multiano_metricas.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    PERM.round(4).to_csv(OUT / 'sobreposicao_vs_acaso.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    SUM.round(3).to_csv(OUT / 'resumo_por_estado_e_eleicao.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    REC.round(3).to_csv(OUT / 'recorrencia_4_anos.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    # zone ranking for closing time and turnout across years
    zr = []
    for uf in ORDER:
        z = None
        for y in YEARS:
            if (uf, y, 1) not in data:
                continue
            d = data[(uf, y, 1)]
            g = d.groupby('zone').agg(**{f'turnout_{y}': ('turnout_pct', 'mean'), f'manual_{y}': ('manual_pct', 'mean'), f'close_{y}': ('close_min', 'mean')})
            z = g if z is None else z.join(g, how='outer')
        z['uf'] = uf
        zr.append(z.reset_index())
    ZN = pd.concat(zr, ignore_index=True)
    ZN.round(2).to_csv(OUT / 'zonas_multiano.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    figures(MET, SUM)
    pdf(AV, MET, PERM, REC, SUM, VAL, ZN, data)
    print('ok')


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def figures(MET, SUM):
    x = np.arange(len(ORDER))
    f, ax = plt.subplots(1, 3, figsize=(13, 3.8), sharey=True)
    for a, col, ttl in zip(ax, ['rho_turnout', 'rho_manual', 'rho_close'], ['comparecimento', '% manual (BU)', 'minutos até o encerramento (BU)']):
        for (y1, y2), mk in zip([(2014, 2018), (2018, 2022), (2022, 2026), (2014, 2026)], ['o', 's', '^', 'x']):
            s = MET[(MET.y1 == y1) & (MET.y2 == y2)].set_index('uf').reindex(ORDER)
            a.scatter(x, s[col], s=18, marker=mk, label=f'{y1}→{y2}')
        a.set_xticks(x)
        a.set_xticklabels(ORDER, fontsize=7)
        a.set_title(f'Persistência por seção: {ttl}', fontsize=8)
        a.axhline(0, color='k', lw=.6)
    ax[0].set_ylabel('Spearman entre eleições')
    ax[0].legend(fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'rho_pairs.png', dpi=150)
    plt.close(f)
    t1 = SUM[SUM.turn == 1]
    f, ax = plt.subplots(1, 3, figsize=(13, 3.6))
    for a, col, ttl in zip(ax, ['turnout', 'manual_pct', 'close_gt15'], ['Comparecimento (%)', 'Habilitação manual — BU (% do comparecimento)', 'Seções encerradas >15 min após 17h (%)']):
        for y in YEARS:
            s = t1[t1.year == y].set_index('uf').reindex(ORDER)
            a.plot(x, s[col], marker='o', ms=3, label=str(y))
        a.set_xticks(x)
        a.set_xticklabels(ORDER, fontsize=7)
        a.set_title(ttl, fontsize=8)
    ax[0].legend(fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'levels.png', dpi=150)
    plt.close(f)


def pdf(AV, MET, PERM, REC, SUM, VAL, ZN, data):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph(f'{M.OFFICE_LABEL} — persistência por seção e zona, 2014 a 2026 (indicadores do boletim de urna)', H1),
          Paragraph('Os logs de urna só existem para 2022 e 2026 (nada foi publicado para 2014 e 2018 no catálogo do TSE). Por isso, para os quatro anos, usamos o que está no próprio boletim de urna (BU): '
                    'comparecimento; quantidade de eleitores com biometria que não foram habilitados por ela, “manual (BU)” (2018 em diante); e o horário de encerramento da seção, que serve como '
                    '<b>aproximação</b> da votação após 17h (2018 em diante). O horário de encerramento inclui o tempo de fechar a urna (mediana de 5 a 9 min após o último voto em 2022/2026), '
                    'e a correlação dele com os votos tardios contados no log é irregular entre estados (tabela na seção 4). Nada aqui conta votos tardios diretamente em 2014 e 2018; 2014 não tem horários no BU.', P),
          Paragraph('Persistência não é prova de nada: a mesma seção, no mesmo local, com o mesmo eleitorado tende a repetir. Seções são “as mesmas” se têm a mesma chave município-zona-seção, o mesmo local de votação '
                    'e aptos entre 0,6× e 1,67×; não há correspondência oficial entre anos.', NOTE),
          Paragraph('1. O que existe em cada ano', H2)]
    t = [['Ano', 'Estados com BU', 'Seções (1º turno)', 'Manual (BU) disponível', 'Horário de encerramento disponível', 'Logs de urna']]
    for r in AV.itertuples():
        t.append([str(r.year), n(r.states), n(r.sections), 'sim' if r.manual else 'não', 'sim' if r.closing else 'não', 'sim' if r.year in (2022, 2026) else 'não publicados'])
    st += [M.table(t, font=7.5), Paragraph('2. Níveis por estado e ano (1º turno)', H2), img(FIG / 'levels.png', 24)]
    t = [['UF', 'Ano', 'Seções', 'Comparecimento %', 'Manual BU %', 'Mediana min. até encerrar (após 17h)', '% encerradas >15 min', '% encerradas >60 min', 'Sinal A', 'Partido com mais seções']]
    for r in SUM[SUM.turn == 1].itertuples():
        t.append([r.uf, str(r.year), n(r.sections), n(r.turnout, 1), n(r.manual_pct, 1), n(r.close_med, 1), n(r.close_gt15, 1), n(r.close_gt60, 1), n(r.A),
                  f'{r.winner_party} ({n(r.winner_share, 0)}%)'])
    st += [M.table(t, font=6.3), PageBreak()]
    # matching
    st += [Paragraph('3. Correspondência entre seções (1º turno)', H2)]
    t = [['UF', 'Par de anos', 'Seções y1', 'Seções y2', 'Mesma chave', 'Mesmo local', 'Usadas (aptos 0,6–1,67×)', '% usadas']]
    for r in MET.itertuples():
        t.append([r.uf, f'{r.y1}→{r.y2}', n(r.n1), n(r.n2), n(r.key), n(r.same_place), n(r.strict), n(r.pct_strict, 1)])
    st += [M.table(t, font=6.2), PageBreak()]
    # persistence
    st += [Paragraph('4. Persistência por seção, município e zona (Spearman)', H2),
           Paragraph('“Desvio do local”: cada seção comparada com a média do seu local de votação. O tamanho da seção (aptos) é a referência estrutural. “Zona/Município”: correlação entre médias.', P)]
    for y1, y2 in [(2014, 2018), (2018, 2022), (2022, 2026), (2018, 2026)]:
        s = MET[(MET.y1 == y1) & (MET.y2 == y2)]
        t = [['UF', 'Seções', 'ρ aptos', 'ρ comparecimento', '… desvio do local', '… zona', 'ρ manual BU', '… desvio do local', '… zona', 'ρ minutos até encerrar', '… desvio do local', '… zona', 'Mesmo partido vencedor %']]
        for r in s.itertuples():
            t.append([r.uf, n(r.strict), n(r.rho_size, 2), n(r.rho_turnout, 2), n(r.rho_turnout_place, 2), n(r.rho_zone_turnout, 2), n(r.rho_manual, 2), n(r.rho_manual_place, 2),
                      n(r.rho_zone_manual, 2), n(r.rho_close, 2), n(r.rho_close_place, 2), n(r.rho_zone_close, 2), n(r.winner_same_pct, 1)])
        st += [Paragraph(f'{y1} → {y2}', M.P), M.table(t, font=6.2), Spacer(1, 3)]
    st += [img(FIG / 'rho_pairs.png', 24), PageBreak()]
    if len(VAL):
        st += [Paragraph('Validação do horário de encerramento como aproximação de votos tardios (2022 e 2026, onde há log)', H2),
               Paragraph('Correlação de Spearman, por seção, entre minutos até o encerramento (BU) e votos após 17h contados no log. Valores baixos significam que o horário de encerramento é uma aproximação fraca naquele estado.', P)]
        t = [['UF'] + [str(y) for y in (2022, 2026)]]
        for uf in ORDER:
            t.append([uf] + [n(VAL[(VAL.uf == uf) & (VAL.year == y)].rho.iloc[0], 2) if len(VAL[(VAL.uf == uf) & (VAL.year == y)]) else '—' for y in (2022, 2026)])
        st += [M.table(t, [2 * cm, 3 * cm, 3 * cm], font=7.5)]
    # overlap
    st += [Paragraph('5. Sinalizações brutas: sobreposição observada vs. acaso', H2),
           Paragraph('Sinal A: comparecimento muito acima do típico (z&gt;3 e ≥10 p.p. acima da mediana municipal). C: % manual (BU) acima do P99 do estado e ano. B: encerramento tardio, minutos até o '
                     'encerramento acima do P99 do estado e ano (proxy). Esperado = média da sobreposição quando o vetor do ano seguinte é embaralhado entre seções do mesmo município '
                     f'({REPS} repetições); p = fração dos embaralhamentos com sobreposição ≥ observada.', P)]
    t = [['Par', 'Sinal', 'Seções comparáveis', 'Sinalizadas y1', 'Sinalizadas y2', 'Sobreposição observada', 'Esperado ao acaso', 'P97,5% do acaso', 'Razão', 'p']]
    for r in PERM.itertuples():
        t.append([r.pair, r.flag, n(r.N), n(r.n1), n(r.n2), n(r.obs), n(r.null_mean, 1), n(r.p975, 1), n(r.ratio, 1), n(r.p, 4)])
    st += [M.table(t, font=6.5)]
    if len(REC):
        st += [Paragraph('Recorrência do sinal A (comparecimento alto) nos 4 anos', H2),
               Paragraph('Seções com mesma chave e mesmo local em 2014, 2018, 2022 e 2026: quantas foram sinalizadas em 0 a 4 anos, e quantas seriam esperadas em cada contagem se os anos fossem independentes '
                         '(taxas observadas por ano).', P)]
        t = [['UF', 'Seções', '0 anos', '1', '2', 'Esperado 2', '3', 'Esperado 3', '4', 'Esperado 4']]
        for r in REC.itertuples():
            t.append([r.uf, n(r.N), n(r.obs0), n(r.obs1), n(r.obs2), n(r.exp2, 1), n(r.obs3), n(r.exp3, 2), n(r.obs4), n(r.exp4, 3)])
        st += [M.table(t, font=6.8)]
    # synthesis
    st += [PageBreak(), Paragraph('6. Síntese (gerada dos números)', H2)]
    lines = []
    for y1, y2 in [(2014, 2018), (2018, 2022), (2022, 2026)]:
        s = MET[(MET.y1 == y1) & (MET.y2 == y2)]
        if s.empty:
            continue
        lines.append(f'{y1}→{y2}: {n(s.strict.sum())} seções pareadas ({n(s.pct_strict.mean(), 1)}% em média); ρ comparecimento mediano {n(s.rho_turnout.median(), 2)} (desvio do local {n(s.rho_turnout_place.median(), 2)}); '
                     f'ρ aptos mediano {n(s.rho_size.median(), 2)}; mesmo partido vencedor em {n(s.winner_same_pct.min(), 0)}–{n(s.winner_same_pct.max(), 0)}% das seções.'
                     + (f' ρ manual (BU) mediano {n(s.rho_manual.median(), 2)}; ρ minutos até encerrar mediano {n(s.rho_close.median(), 2)}.' if s.rho_manual.notna().any() else ''))
    for r in PERM.itertuples():
        lines.append(f'{r.pair}, {r.flag}: {n(r.obs)} seções sinalizadas nos dois anos vs. {n(r.null_mean, 1)} esperadas ao acaso (razão {n(r.ratio, 1)}×, p={n(r.p, 4)}).')
    for l in lines:
        st.append(Paragraph('• ' + l, P))
    st += [Paragraph('Limites', H2)]
    for t_ in ['2014 e 2018 não têm logs de urna publicados: não é possível contar votos após 17h nesses anos; o horário de encerramento do BU é aproximação, com validade variável por estado.',
               '2014 não tem horários nem contagem de habilitação manual no BU; só comparecimento e resultado.',
               'O 2º turno de 2018 e 2014 não entra na persistência (compartilha eleitorado com o 1º turno).',
               'Persistência é esperada por estrutura (tamanho, local, zona, eleitorado); sobreposição acima do acaso dentro do município pode refletir isso. Sem controles demográficos.',
               'Partidos mudam de nome/fusões entre anos; aplicamos um mapa simples de renomeações apenas para comparar o partido vencedor da seção.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'ANALISE_MULTIANO_2014_2026.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    build()
