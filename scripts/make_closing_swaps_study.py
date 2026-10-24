"""Closing time, urn replacement (contingency) and related behaviour across election types (mayor vs president/governor), 10 states.

Sources: BU sections (closing/opening/manual/aggregation/result), CEFT (expected vs effective urn), contingency-urn logs (2022/2024/2026), urn logs.
Descriptive only. President and governor share the same urns, so closing-time facts are reported once for "geral" elections.
"""
import os
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer
from PIL import Image as PI

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M

OUT = Path('relatorios/fechamento_e_trocas')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC', 'MA']
KEY = ['municipality', 'zone', 'section']
# eid, label, type, office used for section-level result, year, turn, election day
ELECS = [('P2018', 'Presidente 2018 T1', 'geral', 'PRESIDENTE', 2018, 1), ('P2018b', 'Presidente 2018 T2', 'geral', 'PRESIDENTE', 2018, 2),
         ('M2020', 'Prefeito 2020 T1', 'municipal', 'PREFEITO', 2020, 1), ('M2020b', 'Prefeito 2020 T2', 'municipal', 'PREFEITO', 2020, 2),
         ('P2022', 'Presidente 2022 T1', 'geral', 'PRESIDENTE', 2022, 1), ('P2022b', 'Presidente 2022 T2', 'geral', 'PRESIDENTE', 2022, 2),
         ('M2024', 'Prefeito 2024 T1', 'municipal', 'PREFEITO', 2024, 1), ('M2024b', 'Prefeito 2024 T2', 'municipal', 'PREFEITO', 2024, 2),
         ('P2026', 'Presidente 2026 T1', 'geral', 'PRESIDENTE', 2026, 1)]
FIRST = ['P2018', 'M2020', 'P2022', 'M2024', 'P2026']
LAB = {e[0]: e[1] for e in ELECS}
TYP = {e[0]: e[2] for e in ELECS}
COL = {'P2018': '#9ecae1', 'P2022': '#3182bd', 'P2026': '#08519c', 'M2020': '#fdae6b', 'M2024': '#e6550d', 'P2018b': '#c6dbef', 'P2022b': '#6baed6', 'M2020b': '#fdd0a2', 'M2024b': '#fd8d3c'}
CEFT_YEARS_ONLY = [(2012, 1), (2012, 2), (2014, 1), (2014, 2), (2016, 1), (2016, 2)]


def n(x, d=0):
    return M.n(x, d)


def adir(office, uf, year, turn):
    if office == 'PRESIDENTE' and year in (2022, 2026):
        return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / f'{year}-t{turn}' / 'analysis'
    return Path('research/analysis') / office / uf / f'{year}-t{turn}'


def ts(s):
    t = pd.to_datetime(s, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    return t.fillna(pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce'))


def minutes_after(s, hour):
    t = ts(s)
    return t.dt.hour * 60 + t.dt.minute + t.dt.second / 60 - hour * 60


def hhmm_to_min(s):
    t = pd.to_datetime(s.astype(str).str[-8:], format='%H:%M:%S', errors='coerce')
    return t.dt.hour * 60 + t.dt.minute + t.dt.second / 60


def load_ceft(year, turn, uf):
    f = Path('research/ceft') / f'{year}-t{turn}' / f'{uf}.parquet'
    if not f.exists():
        return None
    d = pd.read_parquet(f)
    if 'c0' in d.columns:   # 2012-2016 unlabelled layout (27 columns)
        d = d.rename(columns={'c5': 'CD_MUNICIPIO', 'c7': 'NR_ZONA', 'c8': 'NR_SECAO', 'c10': 'NR_URNA_ESPERADA', 'c18': 'NR_URNA_EFETIVADA',
                              'c23': 'DT_CARGA_URNA_EFETIVADA', 'c25': 'CD_ORIGEM_VOTO', 'c26': 'DS_DIVERGENCIA'})
        d['DS_ORIGEM_VOTO'] = d.CD_ORIGEM_VOTO
    for c in ('CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO'])
    out = pd.DataFrame({'municipality': d.CD_MUNICIPIO.astype(int), 'zone': d.NR_ZONA.astype(int), 'section': d.NR_SECAO.astype(int),
                        'urn_expected': d.NR_URNA_ESPERADA.astype(str).str.strip(), 'urn_effective': d.NR_URNA_EFETIVADA.astype(str).str.strip(),
                        'origin': d.DS_ORIGEM_VOTO.astype(str), 'load_effective': d.DT_CARGA_URNA_EFETIVADA.astype(str)})
    out['swap'] = out.urn_expected != out.urn_effective
    out['red'] = out.origin.str.contains('RED', case=False, na=False)
    return out.drop_duplicates(KEY)


def load_cont(folder_tag):
    f = Path('research/contingencia') / f'{folder_tag}.parquet'
    if not f.exists():
        return None
    c = pd.read_parquet(f)
    c = c[c.municipality.notna()].copy()
    for k in KEY:
        c[k] = c[k].astype(int)
    c['cont_start'] = c.contingency_start.str.split(';').str[0].replace('', np.nan)
    c['cont_start_min'] = hhmm_to_min(c.cont_start.fillna(''))
    c['cont_first_vote_min'] = hhmm_to_min(c.first_vote.fillna(''))
    c['cont_close_min'] = hhmm_to_min(c.closing_confirmed.str.split(';').str[0].fillna('')) - 1020
    return c.rename(columns={'votes': 'cont_votes', 'late_votes': 'cont_late', 'error_msgs': 'cont_errors', 'member': 'cont_member'})[
        KEY + ['cont_member', 'cont_start', 'cont_start_min', 'cont_first_vote_min', 'cont_votes', 'cont_late', 'cont_close_min', 'cont_errors', 'locale_zero', 'contingency_fail']]


def cont_tag(office, uf, year, turn):
    if office == 'PRESIDENTE' and year in (2022, 2026):
        base = 'bahia-presidente-2022-2026' if uf == 'BA' else f'estados_{uf}'
        if uf == 'BA' and (year, turn) == (2022, 2):
            base = 'estados_BA'
        return f'{base}_{year}-t{turn}'
    if office == 'PREFEITO' and year == 2024:
        return f'municipais_{uf}_{year}-t{turn}'
    return None


def load(eid):
    _, lab, typ, office, year, turn = next(e for e in ELECS if e[0] == eid)
    frames = []
    for uf in ORDER:
        f = adir(office, uf, year, turn) / 'sections.parquet'
        if not f.exists():
            continue
        cols = pd.read_parquet(f).columns
        want = [c for c in KEY + ['municipality_name', 'voting_place', 'eligible', 'attendance', 'valid_votes', 'manual_bu', 'aggregation_raw', 'opening_bu', 'closure_bu',
                                  'winner', 'winner_party', 'winner_pct', 'member', 'vote_events', 'after_17_recorded', 'first_vote', 'last_vote', 'votes_1630_1700',
                                  'operational_eligible', 'identity_status'] if c in cols]
        d = pd.read_parquet(f, columns=want)
        d['uf'] = uf
        ce = load_ceft(year, turn, uf)
        if ce is not None:
            d = d.merge(ce, on=KEY, how='left')
        tag = cont_tag(office, uf, year, turn)
        co = load_cont(tag) if tag else None
        if co is not None:
            d = d.merge(co, on=KEY, how='left')
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    for c in ['swap', 'red']:
        if c not in d:
            d[c] = np.nan
    d['has_log'] = d.get('member', pd.Series(index=d.index, dtype=object)).notna() if 'member' in d else False
    d['voting_place'] = d.voting_place.astype(str)
    d['close_min'] = minutes_after(d.closure_bu, 17)
    d['open_min'] = minutes_after(d.opening_bu, 8)
    d['window_min'] = minutes_after(d.closure_bu, 0) - minutes_after(d.opening_bu, 0)
    d['min_per_voter'] = d.window_min / d.attendance.where(d.attendance > 0)
    d['is_agg'] = d.aggregation_raw.notna() & ~d.aggregation_raw.astype(str).isin(['#NULO#', 'nan', 'None', ''])
    d['manual_pct'] = 100 * d.manual_bu / d.attendance.where(d.attendance >= 50)
    if 'votes_1630_1700' in d and d.vote_events.notna().any():
        d['last_vote_min'] = hhmm_to_min(d.last_vote.fillna('')) - 1020
        d['close_gap'] = d.close_min - d.last_vote_min
        d['late_pct'] = (100 * d.after_17_recorded / d.vote_events.where(d.vote_events > 0)).where(d.operational_eligible == True)
        d['q1630_pct'] = (100 * d.votes_1630_1700 / d.vote_events.where(d.vote_events > 0)).where(d.operational_eligible == True)
    d['eid'], d['lab'], d['typ'] = eid, lab, typ
    return d


def q(s, p):
    return s.quantile(p) if s.notna().any() else np.nan


def pct(a, b):
    return 100 * a / b if b else np.nan


def closing_tables(D):
    rows, srows = [], []
    for eid, d in D.items():
        e = d[d.eligible >= 50]
        c = e.close_min
        row = dict(eid=eid, lab=LAB[eid], typ=TYP[eid], sections=len(d), with_time=int(c.notna().sum()), mean=c.mean(), median=c.median(), p90=q(c, .9), p99=q(c, .99),
                   gt15=100 * (c > 15).mean(), gt60=100 * (c > 60).mean(), gt120=100 * (c > 120).mean(), open_med=e.open_min.median(), open_gt15=100 * (e.open_min > 15).mean(),
                   open_gt60=100 * (e.open_min > 60).mean(), window_med=e.window_min.median(), mpv_med=e.min_per_voter.median(),
                   late_closers_opened_late=100 * (e[e.close_min > 60].open_min > 15).mean() if (e.close_min > 60).any() else np.nan,
                   agg_pct=100 * e.is_agg.mean(), agg_close_med=e[e.is_agg].close_min.median() if e.is_agg.any() else np.nan, nonagg_close_med=e[~e.is_agg].close_min.median())
        if 'close_gap' in e:
            g = e[e.has_log & (e.operational_eligible == True)]
            row.update(gap_med=g.close_gap.median(), gap_p90=q(g.close_gap, .9), gap_gt30=100 * (g.close_gap > 30).mean(), gap_neg=100 * (g.close_gap < -0.5).mean(),
                       q1630_med=g.q1630_pct.median(), late_pct_pooled=pct(g.after_17_recorded.sum(), g.vote_events.sum()))
        # manual tertiles vs closing
        m = e[e.manual_pct.notna()]
        if len(m) > 100:
            t = pd.qcut(m.manual_pct.rank(method='first'), 3, labels=['baixo', 'médio', 'alto'])
            for lv in ['baixo', 'médio', 'alto']:
                row[f'close_gt60_manual_{lv}'] = 100 * (m[t == lv].close_min > 60).mean()
        # place-level clustering of late closers
        late = e[e.close_min > 60]
        if len(late):
            e2 = e.assign(place=e.uf + '|' + e.municipality.astype(str) + '|' + e.zone.astype(str) + '|' + e.voting_place)
            pl = e2.groupby('place').agg(n=('section', 'size'), late=('close_min', lambda x: (x > 60).sum()))
            pl['share'] = pl.late / pl.n
            late_pl = e2[e2.close_min > 60].place.map(pl.share)
            row['late_in_places_majority_late'] = 100 * (late_pl >= .5).mean()
            row['places_with_late'] = int((pl.late > 0).sum())
            row['places_total'] = len(pl)
        rows.append(row)
        for uf in ORDER:
            s = e[e.uf == uf]
            if len(s):
                srows.append(dict(eid=eid, lab=LAB[eid], uf=uf, sections=len(s), mean=s.close_min.mean(), median=s.close_min.median(), gt15=100 * (s.close_min > 15).mean(),
                                  gt60=100 * (s.close_min > 60).mean(), open_gt15=100 * (s.open_min > 15).mean(), mpv_med=s.min_per_voter.median()))
    return pd.DataFrame(rows), pd.DataFrame(srows)


def paired(D):
    rows = []
    for a, b in [('P2022', 'M2024'), ('M2024', 'P2026'), ('P2022', 'P2026'), ('P2018', 'M2020'), ('M2020', 'P2022'), ('P2018', 'P2022'), ('M2020', 'M2024')]:
        x, y = D[a], D[b]
        m = x.merge(y, on=['uf'] + KEY, suffixes=('_1', '_2'))
        m = m[(m.voting_place_1 == m.voting_place_2) & (m.eligible_2 / m.eligible_1).between(.6, 1.67) & (m.eligible_1 >= 50)]
        diff = m.close_min_2 - m.close_min_1
        ok = diff.notna()
        from scipy import stats
        rho = stats.spearmanr(m.close_min_1[ok], m.close_min_2[ok])[0] if ok.sum() > 30 else np.nan
        rows.append(dict(pair=f'{LAB[a]} → {LAB[b]}', kind=f'{TYP[a]}→{TYP[b]}', n=int(ok.sum()), median_1=m.close_min_1[ok].median(), median_2=m.close_min_2[ok].median(),
                         diff_median=diff[ok].median(), later_in_2=100 * (diff[ok] > 0).mean(), both_gt60=int(((m.close_min_1 > 60) & (m.close_min_2 > 60)).sum()),
                         gt60_1=int((m.close_min_1[ok] > 60).sum()), gt60_2=int((m.close_min_2[ok] > 60).sum()), rho=rho,
                         p_gt60_2_given_1=100 * ((m.close_min_1 > 60) & (m.close_min_2 > 60)).sum() / max((m.close_min_1[ok] > 60).sum(), 1)))
    return pd.DataFrame(rows)


def swap_tables(D):
    rows, srows, hours, errs = [], [], [], []
    for eid, d in D.items():
        if d.swap.isna().all():
            continue
        e = d.copy()
        sw = e[e.swap == True]
        row = dict(eid=eid, lab=LAB[eid], typ=TYP[eid], sections=len(e), ceft_matched=int(e.swap.notna().sum()), swaps=len(sw), swap_pct=pct(len(sw), e.swap.notna().sum()),
                   red=int(e.red.fillna(False).sum()), swap_close_med=sw.close_min.median(), nonswap_close_med=e[e.swap == False].close_min.median(),
                   swap_gt60=100 * (sw.close_min > 60).mean() if len(sw) else np.nan, nonswap_gt60=100 * (e[e.swap == False].close_min > 60).mean(),
                   late_closers=int((e.close_min > 60).sum()), late_closers_swapped=int(((e.close_min > 60) & (e.swap == True)).sum()),
                   late_closers_swapped_pct=pct(((e.close_min > 60) & (e.swap == True)).sum(), (e.close_min > 60).sum()),
                   swap_open_gt15=100 * (sw.open_min > 15).mean() if len(sw) else np.nan)
        if 'cont_start' in e:
            c = e[e.cont_member.notna()]
            cs = c[c.cont_start.notna()]
            row.update(cont_logs=len(c), cont_with_start=len(cs), cont_before_open=int((cs.cont_start_min < 480).sum()), cont_8_12=int(cs.cont_start_min.between(480, 720).sum()),
                       cont_12_16=int(cs.cont_start_min.between(720, 960, inclusive='right').sum()), cont_after_16=int((cs.cont_start_min > 960).sum()),
                       cont_restart_med=(cs.cont_first_vote_min - cs.cont_start_min).median(), votes_before_swap_med=(cs.attendance - cs.cont_votes).median(),
                       votes_before_swap_zero=int(((cs.attendance - cs.cont_votes) <= 0).sum()), cont_late_votes=int(c.cont_late.sum()),
                       cont_close_med=c.cont_close_min.median(), cont_close_gt60=100 * (c.cont_close_min > 60).mean() if len(c) else np.nan,
                       cont_log_votes_eq_bu=int((c.cont_votes == c.attendance).sum()), cont_fail=int((c.contingency_fail.fillna('') != '').sum()),
                       swaps_without_cont_log=int((e.swap == True).sum() - len(c[c.swap == True])), cont_logs_not_in_ceft=int(len(c) - len(c[c.swap == True])))
            for h, cnt in cs.cont_start_min.dropna().floordiv(60).value_counts().sort_index().items():
                hours.append(dict(eid=eid, lab=LAB[eid], hour=int(h), count=int(cnt)))
            for msg_list in c.cont_errors.dropna():
                for m_ in [x for x in msg_list.split(';') if x]:
                    errs.append(dict(eid=eid, lab=LAB[eid], msg=m_[:70]))
        rows.append(row)
        for uf in ORDER:
            s = e[e.uf == uf]
            if len(s) and s.swap.notna().any():
                srows.append(dict(eid=eid, lab=LAB[eid], uf=uf, sections=len(s), swaps=int((s.swap == True).sum()), swap_pct=pct((s.swap == True).sum(), s.swap.notna().sum()),
                                  red=int(s.red.fillna(False).sum()), late_closers=int((s.close_min > 60).sum()), late_swapped=int(((s.close_min > 60) & (s.swap == True)).sum()),
                                  cont_logs=int(s.cont_member.notna().sum()) if 'cont_member' in s else np.nan))
    E = pd.DataFrame(errs)
    E = E.groupby(['eid', 'lab', 'msg']).size().reset_index(name='count').sort_values(['eid', 'count'], ascending=[True, False]) if len(E) else E
    return pd.DataFrame(rows), pd.DataFrame(srows), pd.DataFrame(hours), E


def swap_history():
    rows = []
    for year, turn in CEFT_YEARS_ONLY + [(2018, 1), (2018, 2), (2020, 1), (2020, 2), (2022, 1), (2022, 2), (2024, 1), (2024, 2), (2026, 1)]:
        tot = sw = red = 0
        for uf in ORDER:
            c = load_ceft(year, turn, uf)
            if c is None:
                continue
            tot += len(c)
            sw += int(c.swap.sum())
            red += int(c.red.sum())
        if tot:
            rows.append(dict(year=year, turn=turn, typ='municipal' if year % 4 == 0 else 'geral', sections=tot, swaps=sw, swap_pct=100 * sw / tot, red=red))
    return pd.DataFrame(rows)


def winners(D):
    rows = []
    for eid, d in D.items():
        if d.swap.isna().all():
            continue
        e = d[d.winner_party.notna()]
        g = e.groupby(['uf', 'municipality'])
        for (uf, mun), s in g:
            sw = s[s.swap == True]
            if len(sw) == 0:
                continue
            # city winner by votes needs candidate data; use section-winner plurality as proxy is wrong -> use valid votes weighted winner_pct? not available per candidate.
            rows.append(dict(eid=eid, uf=uf, municipality=mun, sections=len(s), swaps=len(sw),
                             pt_or_lead_city=np.nan))
    return pd.DataFrame(rows)


def winners_candidates(D):
    """City-level winner vs winner within swapped sections, from candidate_sections."""
    rows = []
    for eid, d in D.items():
        if d.swap.isna().all():
            continue
        _, lab, typ, office, year, turn = next(e for e in ELECS if e[0] == eid)
        for uf in ORDER:
            f = adir(office, uf, year, turn) / 'candidate_sections.parquet'
            if not f.exists():
                continue
            c = pd.read_parquet(f)
            s = d[(d.uf == uf) & (d.swap == True)][KEY]
            if s.empty:
                continue
            c['swapped'] = c.merge(s.assign(_s=1), on=KEY, how='left')._s.fillna(0).astype(bool).values
            city = c.groupby(['municipality', 'candidate', 'party']).votes.sum().reset_index()
            city['valid'] = city.groupby('municipality').votes.transform('sum')
            w = city.sort_values(['municipality', 'votes'], ascending=[True, False]).groupby('municipality').head(1).set_index('municipality')
            sw = c[c.swapped].groupby(['municipality', 'candidate', 'party']).votes.sum().reset_index()
            sw['valid'] = sw.groupby('municipality').votes.transform('sum')
            ws = sw.sort_values(['municipality', 'votes'], ascending=[True, False]).groupby('municipality').head(1).set_index('municipality')
            j = w.join(ws, lsuffix='_city', rsuffix='_sw', how='inner')
            for mun, r in j.iterrows():
                rows.append(dict(eid=eid, lab=lab, uf=uf, municipality=mun, city_winner=r.candidate_city, city_party=r.party_city, city_pct=100 * r.votes_city / r.valid_city,
                                 swapped_valid=int(r.valid_sw), sw_winner=r.candidate_sw, sw_party=r.party_sw, sw_pct=100 * r.votes_sw / r.valid_sw,
                                 city_winner_pct_in_swapped=100 * sw[(sw.municipality == mun) & (sw.candidate == r.candidate_city)].votes.sum() / r.valid_sw,
                                 same=r.candidate_city == r.candidate_sw))
    return pd.DataFrame(rows)


def figures(R, S, SW, H):
    f, ax = plt.subplots(1, 3, figsize=(14, 3.8))
    for a, col, ttl in zip(ax, ['median', 'gt15', 'gt60'], ['Mediana de minutos após 17h até encerrar', 'Seções encerradas >15 min após 17h (%)', 'Seções encerradas >60 min (%)']):
        x = np.arange(len(ORDER))
        for i, eid in enumerate(FIRST):
            s = S[S.eid == eid].set_index('uf').reindex(ORDER)
            a.bar(x + (i - 2) * .16, s[col], .16, color=COL[eid], label=LAB[eid])
        a.set_xticks(x)
        a.set_xticklabels(ORDER, fontsize=7)
        a.set_title(ttl, fontsize=8)
    ax[0].legend(fontsize=6)
    f.tight_layout()
    f.savefig(FIG / 'closing_by_state.png', dpi=150)
    plt.close(f)
    f, ax = plt.subplots(figsize=(8, 3.6))
    for eid in FIRST:
        d = DATA[eid]
        c = d[d.eligible >= 50].close_min.dropna().clip(-10, 240)
        xs = np.sort(c.values)
        ax.step(xs, 1 - np.arange(len(xs)) / len(xs), where='post', color=COL[eid], label=LAB[eid], lw=1.3)
    ax.set_yscale('log')
    ax.set(xlabel='minutos após 17h até o encerramento da seção', ylabel='fração de seções que encerram depois de x', title='Distribuição do encerramento, 10 estados (1º turnos)')
    ax.legend(fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'closing_ccdf.png', dpi=150)
    plt.close(f)
    if len(H):
        f, ax = plt.subplots(figsize=(8, 3.4))
        for eid in H.eid.unique():
            h = H[H.eid == eid].set_index('hour')['count'].reindex(range(5, 19), fill_value=0)
            ax.plot(h.index, h.values, marker='o', ms=3, color=COL.get(eid, '#333'), label=LAB[eid])
        ax.axvline(8, color='k', ls=':', lw=.7)
        ax.axvline(17, color='k', ls=':', lw=.7)
        ax.set(xlabel='hora do início do procedimento de contingência (relógio da urna)', ylabel='urnas', title='Quando as urnas foram trocadas no dia da eleição')
        ax.legend(fontsize=7)
        f.tight_layout()
        f.savefig(FIG / 'swap_hours.png', dpi=150)
        plt.close(f)
    f, ax = plt.subplots(figsize=(8, 3.4))
    x = np.arange(len(SW))
    ax.bar(x - .2, SW.swap_gt60, .4, color='#c53030', label='urnas trocadas')
    ax.bar(x + .2, SW.nonswap_gt60, .4, color='#7f8fa6', label='não trocadas')
    ax.set_xticks(x)
    ax.set_xticklabels([l.replace(' ', '\n') for l in SW.lab], fontsize=6.5)
    ax.set(ylabel='% de seções encerradas >60 min após 17h', title='Encerramento tardio: seções com urna trocada vs demais')
    ax.legend(fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'swap_vs_late.png', dpi=150)
    plt.close(f)


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def build_pdf(R, S, PR, SW, SWS, H, E, HIST, W):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Encerramento das seções, troca de urnas e comportamento associado — prefeito × presidente/governador, 10 estados', H1),
          Paragraph('Fontes: boletins de urna (horário de abertura e encerramento, comparecimento, habilitação manual, seções agregadas, resultado); correspondências esperadas e efetivadas do TSE '
                    '(urna prevista × urna que de fato gerou o boletim); logs das urnas (2022, 2024 e 2026), inclusive os logs das urnas de contingência, que até aqui ficavam fora das medidas por '
                    'não trazerem a identificação da seção no conteúdo. Presidente e governador usam a mesma urna, por isso o encerramento é reportado uma vez por eleição geral. '
                    'Minutos são relativos às 17h00 (encerramento) e às 8h00 (abertura), pelo relógio registrado na urna.', P),
          Paragraph('O que NÃO existe nos dados públicos: o log da urna que falhou. Quando uma urna é trocada, o TSE publica apenas os arquivos da urna de contingência; o boletim preserva o '
                    'horário de abertura e o total de votos da seção (inclusive os votos dados na urna original), mas o motivo da falha fica apenas na urna substituída. O que dá para medir '
                    'é: quando a troca aconteceu, quantos votos já haviam sido dados, quanto tempo até o primeiro voto na urna nova, como a seção encerrou e os erros registrados pela urna nova.', NOTE),
          Paragraph('1. Encerramento por tipo de eleição (seções com ≥50 eleitores)', H2)]
    t = [['Eleição', 'Tipo', 'Seções', 'Média min.', 'Mediana', 'P90', 'P99', '>15 min %', '>60 min %', '>120 min %', 'Abertura: mediana min. após 8h', 'Abriu >15 min atrasada %',
          'Dos que encerraram >60 min, % que abriram atrasadas', 'Janela de votação (mediana min.)', 'Min. por eleitor (mediana)']]
    for r in R.itertuples():
        t.append([r.lab, r.typ, n(r.sections), n(r.mean, 1), n(r.median, 1), n(r.p90, 1), n(r.p99, 1), n(r.gt15, 1), n(r.gt60, 2), n(r.gt120, 2), n(r.open_med, 1), n(r.open_gt15, 1),
                  n(r.late_closers_opened_late, 1), n(r.window_med, 0), n(r.mpv_med, 2)])
    st += [M.table(t, font=6), img(FIG / 'closing_by_state.png', 25), img(FIG / 'closing_ccdf.png', 14), PageBreak(),
           Paragraph('2. Mesmas seções, eleições diferentes', H2),
           Paragraph('Pares de eleições nas mesmas seções (mesma chave, mesmo local, aptos entre 0,6× e 1,67×). “Diferença mediana” = minutos de encerramento na 2ª eleição menos na 1ª, por seção. '
                     '“Tardia nas duas” = seções >60 min nas duas; “% das tardias da 1ª que repetem” mede recorrência.', P)]
    t = [['Par', 'Tipo', 'Seções', 'Mediana 1ª', 'Mediana 2ª', 'Dif. mediana (min.)', '% mais tarde na 2ª', 'ρ Spearman', '>60 min na 1ª', '>60 min na 2ª', 'Tardia nas duas', '% das tardias da 1ª que repetem']]
    for r in PR.itertuples():
        t.append([r.pair, r.kind, n(r.n), n(r.median_1, 1), n(r.median_2, 1), n(r.diff_median, 1), n(r.later_in_2, 1), n(r.rho, 2), n(r.gt60_1), n(r.gt60_2), n(r.both_gt60), n(r.p_gt60_2_given_1, 1)])
    st += [M.table(t, font=6.5)]
    # section 3: logs-derived
    rl = R[R.gap_med.notna()] if 'gap_med' in R else R.iloc[0:0]
    if len(rl):
        st += [Paragraph('3. O que o log acrescenta (2022, 2024, 2026): tempo para fechar a urna, fila final e votos após 17h', H2),
               Paragraph('“Tempo para fechar” = encerramento (BU) menos o último voto (log). “Fila final” = % dos votos da seção concluídos entre 16h30 e 17h00. Seções elegíveis (log = BU, relógio coerente).', P)]
        t = [['Eleição', 'Tempo para fechar: mediana (min.)', 'P90', '>30 min %', 'Encerramento antes do último voto %', 'Votos 16h30–17h00 (% mediana por seção)', 'Votos após 17h (% dos votos)',
              '>60 min: manual baixo', 'manual médio', 'manual alto', 'Seções agregadas %', 'Encerr. mediana agregadas', 'não agregadas',
              'Tardias (>60) em locais onde ≥50% das seções são tardias %', 'Locais com ≥1 tardia']]
        for r in rl.itertuples():
            t.append([r.lab, n(r.gap_med, 1), n(r.gap_p90, 1), n(r.gap_gt30, 2), n(r.gap_neg, 2), n(r.q1630_med, 1), n(r.late_pct_pooled, 2),
                      n(getattr(r, 'close_gt60_manual_baixo', np.nan), 2), n(getattr(r, 'close_gt60_manual_médio', np.nan), 2), n(getattr(r, 'close_gt60_manual_alto', np.nan), 2),
                      n(r.agg_pct, 2), n(r.agg_close_med, 1), n(r.nonagg_close_med, 1), n(getattr(r, 'late_in_places_majority_late', np.nan), 1), n(getattr(r, 'places_with_late', np.nan))])
        st += [M.table(t, font=5.8)]
    r2 = R[R.gap_med.isna()] if 'gap_med' in R else R
    if len(r2):
        t = [['Eleição', '>60 min: manual baixo %', 'manual médio', 'manual alto', 'Seções agregadas %', 'Encerr. mediana agregadas', 'não agregadas', 'Tardias em locais majoritariamente tardios %', 'Locais com ≥1 tardia / total']]
        for r in r2.itertuples():
            t.append([r.lab, n(getattr(r, 'close_gt60_manual_baixo', np.nan), 2), n(getattr(r, 'close_gt60_manual_médio', np.nan), 2), n(getattr(r, 'close_gt60_manual_alto', np.nan), 2),
                      n(r.agg_pct, 2), n(r.agg_close_med, 1), n(r.nonagg_close_med, 1), n(getattr(r, 'late_in_places_majority_late', np.nan), 1),
                      f"{n(getattr(r, 'places_with_late', np.nan))} / {n(getattr(r, 'places_total', np.nan))}"])
        st += [Paragraph('Mesmos indicadores para eleições sem log (BU apenas):', M.P), M.table(t, font=6.3)]
    st += [PageBreak(), Paragraph('4. Troca de urna (correspondência esperada × efetivada)', H2),
           Paragraph('“Troca” = a urna que gerou o boletim não é a urna prevista para a seção. Inclui trocas feitas antes do dia da eleição (na preparação) e no dia (contingência). '
                     'A data de carga da urna efetivada é a da preparação, então o momento da troca só é conhecido pelo log da urna de contingência (2022, 2024, 2026). '
                     '“RED” = boletim gerado por recuperação de dados (a urna não conseguiu encerrar normalmente).', P)]
    t = [['Eleição', 'Tipo', 'Seções', 'Com correspondência', 'Trocas', '% trocas', 'RED', 'Encerr. mediana trocadas', 'não trocadas', '>60 min trocadas %', '>60 min não trocadas %',
          'Seções >60 min', '… com urna trocada', '% das tardias explicadas por troca', 'Trocadas que abriram >15 min atrasadas %']]
    for r in SW.itertuples():
        t.append([r.lab, r.typ, n(r.sections), n(r.ceft_matched), n(r.swaps), n(r.swap_pct, 2), n(r.red), n(r.swap_close_med, 1), n(r.nonswap_close_med, 1), n(r.swap_gt60, 1),
                  n(r.nonswap_gt60, 2), n(r.late_closers), n(r.late_closers_swapped), n(r.late_closers_swapped_pct, 1), n(r.swap_open_gt15, 1)])
    st += [M.table(t, font=6), img(FIG / 'swap_vs_late.png', 15)]
    t = [['Ano', 'Turno', 'Tipo', 'Seções', 'Trocas', '% trocas', 'RED']]
    for r in HIST.itertuples():
        t.append([str(r.year), str(r.turn), r.typ, n(r.sections), n(r.swaps), n(r.swap_pct, 2), n(r.red)])
    st += [Paragraph('Histórico de trocas, 2012 a 2026 (só a correspondência; 2012–2016 sem horários):', M.P), M.table(t, [2 * cm, 1.5 * cm, 2.5 * cm, 3 * cm, 2.5 * cm, 2.5 * cm, 2 * cm], font=7), PageBreak()]
    swl = SW[SW.get('cont_logs', pd.Series(dtype=float)).notna()] if 'cont_logs' in SW else SW.iloc[0:0]
    if len(swl):
        st += [Paragraph('5. O que o log da urna de contingência mostra (2022, 2024, 2026)', H2),
               Paragraph('Para cada seção trocada: hora do “início do procedimento de contingência”; votos já dados antes da troca = comparecimento do boletim − votos registrados na urna nova; '
                         '“tempo até o primeiro voto” = primeiro voto na urna nova − início da contingência (o tempo total sem votação é maior: inclui o período entre a falha e a chegada da urna nova, '
                         'que não está nos dados). Trocas “antes da abertura” = contingência feita antes das 8h (a seção começou já na urna nova).', P)]
        t = [['Eleição', 'Trocas (CEFT)', 'Logs de contingência', 'c/ hora da troca', 'Antes das 8h', '8h–12h', '12h–16h', 'Após 16h', 'Votos antes da troca (mediana)', 'Trocas sem voto anterior',
              'Até 1º voto na urna nova (mediana min.)', 'Votos após 17h nas urnas novas', 'Encerr. mediana (min.)', '>60 min %', 'Log = BU', 'Contingência c/ falha registrada']]
        for r in swl.itertuples():
            t.append([r.lab, n(r.swaps), n(r.cont_logs), n(r.cont_with_start), n(r.cont_before_open), n(r.cont_8_12), n(r.cont_12_16), n(r.cont_after_16), n(r.votes_before_swap_med, 0),
                      n(r.votes_before_swap_zero), n(r.cont_restart_med, 1), n(r.cont_late_votes), n(r.cont_close_med, 1), n(r.cont_close_gt60, 1), n(r.cont_log_votes_eq_bu), n(r.cont_fail)])
        st += [M.table(t, font=5.8), img(FIG / 'swap_hours.png', 14) if (FIG / 'swap_hours.png').exists() else Spacer(1, 1),
               Paragraph('“Log = BU” conta urnas de contingência cujos votos registrados igualam o comparecimento: trocas antes do primeiro voto. Nas demais, os votos anteriores à troca estão no boletim '
                         '(a mídia de resultado acompanha a seção), mas não no log publicado. Os votos após 17h destas urnas não entravam nas contagens anteriores deste estudo.', SM),
               Paragraph('Mensagens de erro registradas pelas urnas de contingência no dia (são erros da urna nova, não a causa da troca):', M.P)]
        if len(E):
            t = [['Eleição', 'Mensagem (números substituídos por N)', 'Urnas']]
            for eid in E.eid.unique():
                for r in E[E.eid == eid].head(8).itertuples():
                    t.append([r.lab, r.msg, n(r.count)])
            st += [M.table(t, [4 * cm, 17 * cm, 2 * cm], font=6.3)]
        st += [PageBreak()]
    st += [Paragraph('6. Por estado: encerramento e trocas', H2)]
    t = [['UF'] + [f'{LAB[e]}: mediana min. / >60 min % / trocas %' for e in FIRST]]
    for uf in ORDER:
        row = [uf]
        for e in FIRST:
            s = S[(S.eid == e) & (S.uf == uf)]
            w = SWS[(SWS.eid == e) & (SWS.uf == uf)]
            row.append(f"{n(s['median'].iloc[0], 1)} / {n(s.gt60.iloc[0], 1)} / {n(w.swap_pct.iloc[0], 2) if len(w) else '—'}" if len(s) else '—')
        t.append(row)
    st += [M.table(t, font=6.5)]
    if len(W):
        st += [Paragraph('7. Quem vence nas seções com urna trocada', H2),
               Paragraph('Por cidade com pelo menos uma troca: vencedor da cidade (votos válidos do cargo) e vencedor dentro das seções trocadas. Descreve onde as trocas ocorreram; não mede efeito da troca.', P)]
        t = [['Eleição', 'Cidades com troca', 'Seções trocadas c/ votos', 'Mesmo vencedor %', '% do vencedor da cidade nas seções trocadas − na cidade (mediana p.p.)']]
        for eid, g in W.groupby('eid', sort=False):
            t.append([LAB[eid], n(len(g)), n(g.swapped_valid.sum()), n(100 * g.same.mean(), 1), n((g.city_winner_pct_in_swapped - g.city_pct).median(), 2)])
        st += [M.table(t, font=7), Paragraph('Lista completa por cidade: vencedores_secoes_trocadas.csv.', SM)]
    # synthesis
    st += [PageBreak(), Paragraph('8. Síntese (gerada dos números)', H2)]
    g = R.set_index('eid')
    lines = []
    for eid in ['P2022', 'M2024', 'P2026']:
        if eid in g.index:
            lines.append(f'{LAB[eid]}: mediana de {n(g.loc[eid, "median"], 1)} min após 17h; {n(g.loc[eid, "gt60"], 2)}% das seções encerram >60 min; {n(g.loc[eid, "open_gt15"], 1)}% abriram >15 min atrasadas; '
                         f'tempo mediano para fechar após o último voto {n(g.loc[eid, "gap_med"], 1)} min.')
    gm = g[g.typ == 'municipal']
    gg = g[(g.typ == 'geral') & (g.index.isin(FIRST))]
    lines.append(f'Mediana de encerramento nos 1º turnos: eleições gerais {n(gg["median"].min(), 1)}–{n(gg["median"].max(), 1)} min; municipais {n(gm.loc[gm.index.isin(FIRST), "median"].min(), 1)}–{n(gm.loc[gm.index.isin(FIRST), "median"].max(), 1)} min. '
                 f'Seções >60 min: gerais {n(gg.gt60.min(), 2)}–{n(gg.gt60.max(), 2)}%; municipais {n(gm.loc[gm.index.isin(FIRST), "gt60"].min(), 2)}–{n(gm.loc[gm.index.isin(FIRST), "gt60"].max(), 2)}%.')
    s = SW.set_index('eid')
    for eid in s.index:
        lines.append(f'{LAB[eid]}: {n(s.loc[eid, "swaps"])} trocas ({n(s.loc[eid, "swap_pct"], 2)}% das seções); das {n(s.loc[eid, "late_closers"])} seções que encerraram >60 min, '
                     f'{n(s.loc[eid, "late_closers_swapped"])} ({n(s.loc[eid, "late_closers_swapped_pct"], 1)}%) tinham urna trocada; >60 min em {n(s.loc[eid, "swap_gt60"], 1)}% das trocadas vs {n(s.loc[eid, "nonswap_gt60"], 2)}% das demais.')
    if len(swl):
        for r in swl.itertuples():
            lines.append(f'{r.lab}, urnas de contingência: {n(r.cont_with_start)} com hora da troca — {n(r.cont_before_open)} antes das 8h, {n(r.cont_8_12)} entre 8h e 12h, {n(r.cont_12_16)} entre 12h e 16h, '
                         f'{n(r.cont_after_16)} após 16h; mediana de {n(r.votes_before_swap_med, 0)} votos já dados antes da troca; {n(r.cont_late_votes)} votos após 17h nessas urnas (fora das contagens anteriores).')
    for l in lines:
        st.append(Paragraph('• ' + l, P))
    st += [Paragraph('Limites', H2)]
    for t_ in ['O motivo da troca não é público: só a urna substituída registrou a falha e seu log não é publicado. As mensagens de erro listadas são da urna nova.',
               'Horários são do relógio registrado em cada urna, sem calibração independente; encerramento tardio inclui o tempo de fechar a urna, não só fila.',
               'Encerramento e abertura vêm do boletim; para 2012–2016 o boletim não traz horários (só a correspondência de urnas).',
               'As comparações entre tipos de eleição misturam anos diferentes; a urna municipal tem 2 cargos e a geral 5 ou 6, o que por si só altera o tempo de votação.',
               'Nada aqui indica irregularidade nem a descarta.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d.page}')
    SimpleDocTemplate(str(OUT / 'ANALISE_FECHAMENTO_E_TROCAS.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


DATA = {}

if __name__ == '__main__':
    for e in ELECS:
        try:
            DATA[e[0]] = load(e[0])
            print('loaded', e[0], len(DATA[e[0]]), flush=True)
        except Exception as exc:
            print('skip', e[0], repr(exc)[:150], flush=True)
    R, S = closing_tables(DATA)
    PR = paired(DATA)
    SW, SWS, H, E = swap_tables(DATA)
    HIST = swap_history()
    W = winners_candidates(DATA)
    for nm, df in (('encerramento_por_eleicao', R), ('encerramento_por_estado', S), ('encerramento_pares_mesmas_secoes', PR), ('trocas_por_eleicao', SW),
                   ('trocas_por_estado', SWS), ('trocas_hora_contingencia', H), ('trocas_erros_urna_nova', E), ('trocas_historico_2012_2026', HIST), ('vencedores_secoes_trocadas', W)):
        df.round(4).to_csv(OUT / f'{nm}.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    # section-level export of swapped sections with contingency facts
    parts = []
    for eid, d in DATA.items():
        if d.swap.isna().all():
            continue
        s = d[d.swap == True].copy()
        s['eid'] = eid
        keep = [c for c in ['eid', 'lab', 'uf', 'municipality', 'municipality_name', 'zone', 'section', 'voting_place', 'eligible', 'attendance', 'urn_expected', 'urn_effective', 'origin', 'red',
                            'opening_bu', 'closure_bu', 'close_min', 'cont_start', 'cont_votes', 'cont_late', 'cont_close_min', 'cont_errors', 'winner', 'winner_party', 'winner_pct'] if c in s]
        parts.append(s[keep])
    pd.concat(parts, ignore_index=True).round(2).to_csv(OUT / 'secoes_com_urna_trocada.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    figures(R, S, SW, H)
    build_pdf(R, S, PR, SW, SWS, H, E, HIST, W)
    print('ok')
