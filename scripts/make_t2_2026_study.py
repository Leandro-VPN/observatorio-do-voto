"""2026 2nd round: sections kept open after 17h (Zanin order, restricted to sections still open), who won in them, votes after 17h,
the abstention drop T1->T2 vs history, and same-section comparison with T1. Descriptive; no claim about intent or fraud.
"""
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate
from PIL import Image as PI

sys.path.insert(0, 'scripts')
os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M

SRC = Path('research/segundo_turno_2026')
OUT = Path('relatorios/segundo_turno_2026')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
KEY = ['municipality', 'zone', 'section']
DAY = '25/10/2026 '
BA_CITIES = {38490: 'SALVADOR', 35157: 'FEIRA DE SANTANA', 36854: 'LAURO DE FREITAS'}
n = M.n
T1_ROOT = {'BA': Path('research/bahia-presidente-2022-2026/2026-t1/analysis')}


def t1_dir(uf):
    return T1_ROOT.get(uf, Path('research/estados') / uf / '2026-t1' / 'analysis')


# ------------------------------------------------------------------ logs
def parse_log(path):
    from auditabr.logs import read_log
    import analyze_pilot_operations as engine
    try:
        data = read_log(path)
    except Exception as exc:
        return dict(log_name=path.name, log_error=repr(exc)[:80])
    m = engine.parse(data, day=DAY, allow_named_authorization=True, allow_unattributed=True)
    txt = data.decode('utf-8-sig', 'ignore') if isinstance(data, bytes) else data
    buckets = np.zeros(10, dtype=int)   # 16:00-16:30, 16:30-17:00, 17:00-17:30, ..., 20:00+
    for line in txt.splitlines():
        if line.startswith(DAY) and '\tVOTA\t' in line and 'O voto do eleitor foi computado' in line:
            h, mi = int(line[11:13]), int(line[14:16])
            t = h * 60 + mi
            if t >= 960:
                buckets[min(9, (t - 960) // 30)] += 1
    rec = dict(log_name=path.name, vote_events=m['vote_events'], after_17=m['after_17_recorded'], manual_log=m['manual_sequence_votes'], manual_after_17=m['after_17_manual_sequence'],
               first_vote=m['first_vote'], last_vote=m['last_vote'], late_interval_median=m['late_interval_median_seconds'], cancellations=m.get('cancellations'),
               extension_msgs=sum(1 for l in txt.splitlines() if l.startswith(DAY) and re.search(r'prorroga|hor[aá]rio de encerramento|19:00', l, re.I)))
    for i in range(10):
        rec[f'b{i}'] = int(buckets[i])
    return rec


def load_logs(uf):
    cache = SRC / f'logparse_{uf}.parquet'
    folder = SRC / 'logs' / uf
    files = sorted(folder.glob('*.jez')) if folder.exists() else []
    if cache.exists():
        c = pd.read_parquet(cache)
        if len(c) == len(files):
            return c
    with ProcessPoolExecutor(6) as ex:
        rows = list(ex.map(parse_log, files, chunksize=16))
    c = pd.DataFrame(rows)
    c.to_parquet(cache, index=False)
    return c


# ------------------------------------------------------------------ load
def load(uf):
    import t2_2026_collect as T
    b = pd.read_parquet(SRC / 'bu' / f'{uf}.parquet')
    bad = b.status.astype(str).str.startswith('DECODE')
    if bad.any():   # rows that failed with the first decoder version: re-decode from the stored bytes
        fixed = [dict(T.decode_bu(r), status='OK') for r in b.loc[bad, 'bu_raw']]
        fx = pd.DataFrame(fixed, index=b.index[bad])
        for c in fx.columns:
            if c not in b:
                b[c] = np.nan
            b.loc[bad, c] = fx[c]
    b = b.drop(columns=['bu_raw'], errors='ignore')
    b = b[b.status == 'OK'].copy()
    for k in KEY + ['voting_place']:
        b[k] = b[k].astype(int)
    t = pd.to_datetime(b.closing, format='%Y%m%dT%H%M%S', errors='coerce')
    o = pd.to_datetime(b.opening, format='%Y%m%dT%H%M%S', errors='coerce')
    b['close_min'] = t.dt.hour * 60 + t.dt.minute + t.dt.second / 60 - 1020
    b['open_min'] = o.dt.hour * 60 + o.dt.minute + o.dt.second / 60 - 480
    b['aptos'] = b['e6258_aptos']
    b['comp'] = b['e6258_comparecimento']
    b['lula'] = b.get('e6258_c1_v13', 0).fillna(0)
    b['flavio'] = b.get('e6258_c1_v22', 0).fillna(0)
    b['validos'] = b.lula + b.flavio
    b['lula_pct'] = 100 * b.lula / b.validos.where(b.validos > 0)
    b['abst_pct'] = 100 * (1 - b.comp / b.aptos.where(b.aptos > 0))
    b['manual_bu'] = b.get('hab_2')
    lg = load_logs(uf)
    if len(lg):
        b = b.merge(lg, on='log_name', how='left')
    t1 = t1_dir(uf) / 'sections.parquet'
    if t1.exists():
        a = pd.read_parquet(t1, columns=KEY + ['voting_place', 'eligible', 'attendance', 'closure_bu', 'manual_bu', 'after_17_recorded', 'vote_events'])
        a['t1_close_min'] = pd.to_datetime(a.closure_bu, format='%Y-%m-%d %H:%M:%S', errors='coerce').pipe(lambda s: s.dt.hour * 60 + s.dt.minute + s.dt.second / 60 - 1020)
        c = pd.read_parquet(t1_dir(uf) / 'candidate_sections.parquet')
        lv = c[c.candidate_number.astype(str) == '13'].groupby(KEY).votes.sum().rename('t1_lula')
        fv = c[c.candidate_number.astype(str) == '22'].groupby(KEY).votes.sum().rename('t1_flavio')
        vv = c.groupby(KEY).votes.sum().rename('t1_validos')
        a = a.join(lv, on=KEY).join(fv, on=KEY).join(vv, on=KEY)
        a = a.rename(columns={'eligible': 't1_aptos', 'attendance': 't1_comp', 'manual_bu': 't1_manual', 'after_17_recorded': 't1_after17', 'voting_place': 't1_place'})
        b = b.merge(a.drop(columns=['closure_bu', 'vote_events']), on=KEY, how='left')
        b['t1_lula_pct'] = 100 * b.t1_lula / b.t1_validos.where(b.t1_validos > 0)
        b['t1_abst_pct'] = 100 * (1 - b.t1_comp / b.t1_aptos.where(b.t1_aptos > 0))
    b['place'] = b.uf + '|' + b.municipality.astype(str) + '|' + b.zone.astype(str) + '|' + b.voting_place.astype(str)
    return b


def tier(c):
    return pd.cut(c, [-1e9, 10, 30, 60, 120, 1e9], labels=['até 17:10', '17:10–17:30', '17:30–18:00', '18:00–19:00', 'após 19:00'])


def wavg(x, w):
    x, w = np.asarray(x, float), np.asarray(w, float)
    ok = np.isfinite(x) & np.isfinite(w) & (w > 0)
    return np.average(x[ok], weights=w[ok]) if ok.any() else np.nan


def analyze(D):
    rows, tiers, hours, cities, places = [], [], [], [], []
    for uf, b in D.items():
        b['tier'] = tier(b.close_min)
        late = b.close_min >= 10
        ctrl = b.log_why.eq('control') if 'log_why' in b else pd.Series(False, index=b.index)
        has = b.vote_events.notna() if 'vote_events' in b else pd.Series(False, index=b.index)
        # after-17 votes: logs of late sections + control sample scaled to non-late sections
        a17_late = b.loc[late & has, 'after_17'].sum() if 'after_17' in b else np.nan
        ctrl_rate = b.loc[ctrl & has & ~late, 'after_17'].sum() / max(b.loc[ctrl & has & ~late, 'vote_events'].sum(), 1) if 'after_17' in b else np.nan
        a17_rest = ctrl_rate * b.loc[~late, 'comp'].sum()
        lv, fv = b.lula.sum(), b.flavio.sum()
        # proportional allocation of after-17 votes by section shares (upper/lower bounds per section)
        L = b[late & has].copy()
        est_l = (L.after_17 * L.lula / L.validos.where(L.validos > 0) * (L.validos / L.comp.where(L.comp > 0))).sum()
        est_f = (L.after_17 * L.flavio / L.validos.where(L.validos > 0) * (L.validos / L.comp.where(L.comp > 0))).sum()
        maxnet_l = np.minimum(L.after_17, L.lula).sum() - np.maximum(0, L.after_17 - (L.comp - L.flavio)).sum()
        rows.append(dict(uf=uf, secoes=len(b), aptos=int(b.aptos.sum()), comparecimento=int(b.comp.sum()), abst_pct=100 * (1 - b.comp.sum() / b.aptos.sum()),
                         t1_abst_pct=100 * (1 - b.t1_comp.sum() / b.t1_aptos.sum()) if 't1_comp' in b else np.nan, comp_gain=int(b.comp.sum() - b.t1_comp.sum()) if 't1_comp' in b else np.nan,
                         late_secoes=int(late.sum()), late_pct=100 * late.mean(), after19_secoes=int((b.close_min >= 120).sum()),
                         late_logs=int((late & has).sum()), a17_late=a17_late, a17_rest_est=a17_rest, a17_total_est=a17_late + a17_rest,
                         lula=int(lv), flavio=int(fv), margem=int(lv - fv), margem_pp=100 * (lv - fv) / (lv + fv),
                         late_lula_pct=wavg(b.loc[late, 'lula_pct'], b.loc[late, 'validos']), ontime_lula_pct=wavg(b.loc[~late, 'lula_pct'], b.loc[~late, 'validos']),
                         est_l=est_l, est_f=est_f, est_net=est_l - est_f, maxnet_l=maxnet_l,
                         t1_late_secoes=int((b.t1_close_min >= 10).sum()) if 't1_close_min' in b else np.nan))
        for tr, s in b.groupby('tier', observed=True):
            tiers.append(dict(uf=uf, tier=str(tr), secoes=len(s), comp=int(s.comp.sum()), lula_pct=wavg(s.lula_pct, s.validos), abst_pct=100 * (1 - s.comp.sum() / s.aptos.sum()),
                              t1_lula_pct=wavg(s.t1_lula_pct, s.t1_validos) if 't1_lula_pct' in s else np.nan,
                              t1_abst_pct=100 * (1 - s.t1_comp.sum() / s.t1_aptos.sum()) if 't1_comp' in s else np.nan,
                              after17=s.after_17.sum() if 'after_17' in s else np.nan, logs=int(s.vote_events.notna().sum()) if 'vote_events' in s else 0,
                              manual_pct=100 * s.manual_bu.sum() / s.comp.sum(), t1_manual_pct=100 * s.t1_manual.sum() / s.t1_comp.sum() if 't1_manual' in s else np.nan,
                              open_late=100 * (s.open_min > 15).mean(), t1_late=100 * (s.t1_close_min >= 10).mean() if 't1_close_min' in s else np.nan))
        if 'b0' in b:
            hb = b[late & has][[f'b{i}' for i in range(10)]].sum()
            hours.append(dict(uf=uf, **{f'b{i}': int(hb[f'b{i}']) for i in range(10)}))
        # place-level comparison: late sections vs on-time sections of the same place
        g = b[b.validos > 0].copy()
        g['late'] = g.close_min >= 10
        pl = g.groupby('place').agg(n_late=('late', 'sum'), n=('late', 'size'))
        mixed = pl[(pl.n_late > 0) & (pl.n_late < pl.n)].index
        mm = g[g.place.isin(mixed)]
        ml = mm.groupby(['place', 'late']).apply(lambda s: pd.Series(dict(lula=wavg(s.lula_pct, s.validos), abst=100 * (1 - s.comp.sum() / s.aptos.sum()),
                                                                          t1_lula=wavg(s.t1_lula_pct, s.t1_validos) if 't1_lula_pct' in s else np.nan)), include_groups=False).unstack()
        if len(ml):
            places.append(dict(uf=uf, locais_mistos=len(ml), lula_late=ml[('lula', True)].mean(), lula_ontime=ml[('lula', False)].mean(),
                               diff_lula=(ml[('lula', True)] - ml[('lula', False)]).mean(), diff_lula_t1=(ml[('t1_lula', True)] - ml[('t1_lula', False)]).mean(),
                               diff_abst=(ml[('abst', True)] - ml[('abst', False)]).mean()))
        if uf == 'BA':
            for cd, nm in BA_CITIES.items():
                s = b[b.municipality == cd]
                cities.append(dict(city=nm, secoes=len(s), late=int((s.close_min >= 10).sum()), after19=int((s.close_min >= 120).sum()), comp=int(s.comp.sum()),
                                   abst=100 * (1 - s.comp.sum() / s.aptos.sum()), t1_abst=100 * (1 - s.t1_comp.sum() / s.t1_aptos.sum()) if 't1_comp' in s else np.nan,
                                   lula_pct=wavg(s.lula_pct, s.validos), t1_lula_pct=wavg(s.t1_lula_pct, s.t1_validos) if 't1_lula_pct' in s else np.nan,
                                   after17=s.after_17.sum() if 'after_17' in s else np.nan, logs=int(s.vote_events.notna().sum()) if 'vote_events' in s else 0,
                                   late_lula=wavg(s.loc[s.close_min >= 10, 'lula_pct'], s.loc[s.close_min >= 10, 'validos']),
                                   ontime_lula=wavg(s.loc[s.close_min < 10, 'lula_pct'], s.loc[s.close_min < 10, 'validos'])))
    return pd.DataFrame(rows), pd.DataFrame(tiers), pd.DataFrame(hours), pd.DataFrame(cities), pd.DataFrame(places)


def municipal(D):
    m = pd.read_parquet(SRC / 'mun_todos.parquet')
    m['abs_t1'] = 100 * m.t1_abstencao / m.t1_eleitorado
    m['abs_t2'] = 100 * m.t2_abstencao / m.t2_eleitorado
    m['queda'] = m.abs_t1 - m.abs_t2
    m['lula_t1'] = 100 * m.t1_v13 / (m.t1_validos.where(m.t1_validos > 0))
    m['lula_t2'] = 100 * m.t2_v13 / (m.t2_v13 + m.t2_v22)
    m['comp_gain'] = m.t2_comparecimento - m.t1_comparecimento
    # late share per municipality (sections closing >= 17:10)
    late = []
    for uf, b in D.items():
        g = b.groupby('municipality').agg(late_secoes=('close_min', lambda x: int((x >= 10).sum())), secoes_bu=('close_min', 'size'),
                                          after17=('after_17', 'sum') if 'after_17' in b else ('close_min', lambda x: np.nan)).reset_index()
        g['uf'] = uf
        late.append(g)
    L = pd.concat(late)
    L['mun_cd'] = L.municipality.astype(str).str.zfill(5)
    m['mun_cd'] = m.mun_cd.astype(str).str.zfill(5)
    m = m.merge(L.drop(columns='municipality'), on=['uf', 'mun_cd'], how='left')
    m['late_share'] = m.late_secoes / m.secoes_bu
    return m


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def figures(R, H, TI, m):
    if len(H):
        f, ax = plt.subplots(figsize=(9, 3.6))
        labs = ['16:00', '16:30', '17:00', '17:30', '18:00', '18:30', '19:00', '19:30', '20:00', '20:30+']
        tot = H[[f'b{i}' for i in range(10)]].sum()
        ax.bar(range(10), tot.values, color=['#7f8fa6'] * 2 + ['#c53030'] * 8)
        ax.set_xticks(range(10))
        ax.set_xticklabels(labs, fontsize=7)
        ax.set(ylabel='votos computados', title='Votos por meia hora nas seções que fecharam após 17:10 (logs)')
        f.tight_layout()
        f.savefig(FIG / 'votos_por_meia_hora.png', dpi=150)
        plt.close(f)
    hist = pd.read_parquet(SRC / 'abstencao_uf_historico.parquet')
    w = hist.pivot(index='SG_UF', columns='y', values='queda').drop(index='ZZ', errors='ignore').sort_values(2026)
    f, ax = plt.subplots(figsize=(11, 4))
    x = np.arange(len(w))
    for i, y in enumerate([2014, 2018, 2022, 2026]):
        ax.scatter(x, w[y], s=18 if y != 2026 else 40, label=str(y), marker='o' if y != 2026 else 'D', zorder=3 if y == 2026 else 2)
    ax.axhline(0, color='k', lw=.6)
    ax.set_xticks(x)
    ax.set_xticklabels(w.index, fontsize=7)
    ax.set(ylabel='queda da abstenção do 1º para o 2º turno (p.p.)', title='Variação da abstenção entre turnos (positivo = abstenção caiu no 2º turno)')
    ax.legend(fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'abstencao_historico.png', dpi=150)
    plt.close(f)
    mm = m[m.late_share.notna()]
    f, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    ax[0].scatter(100 * mm.late_share, mm.queda, s=4, alpha=.4)
    ax[0].set(xlabel='% das seções do município que fecharam após 17:10', ylabel='queda da abstenção T1→T2 (p.p.)', title='Municípios (14 estados)')
    ax[1].scatter(mm.lula_t2 - mm.lula_t1, mm.queda, s=4, alpha=.4, color='#c53030')
    ax[1].set(xlabel='variação do % de Lula T1→T2 (p.p., válidos)', ylabel='queda da abstenção (p.p.)', title='Queda da abstenção × variação do voto')
    f.tight_layout()
    f.savefig(FIG / 'municipios_queda.png', dpi=150)
    plt.close(f)


def pdf(R, TI, H, C, PL, m):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('2º turno de 2026 — urnas que ficaram abertas após 17h, quem venceu nelas e a queda da abstenção', H1),
          Paragraph('Fontes: sistema de resultados do TSE (arquivos de cada urna do pleito 3221: boletim de urna e log), resultados por município do 1º e 2º turnos, '
                    'detalhe da votação por município de 2014, 2018 e 2022 (dados abertos). Contexto: decisão do ministro Cristiano Zanin (STF) em 25/10/2026 prorrogando a votação até 19h; '
                    'depois restrita, por esclarecimento do próprio ministro e decisão do presidente do TSE, às seções que ainda estavam abertas. Não há lista oficial das seções alcançadas; '
                    'aqui “urna que ficou aberta” = encerramento registrado no boletim às 17:10 ou depois.', P),
          Paragraph('Os horários são do relógio de cada urna. Fila ao fim do dia é normal e o eleitor na fila às 17h vota; a diferença em 2026 T2 é que seções abertas puderam receber eleitores até 19h. '
                    'O log não liga voto a candidato: “quem venceu” é o resultado da seção inteira; a parcela dos votos após 17h atribuída a cada candidato é estimativa proporcional, com limites.', NOTE),
          Paragraph('1. Abstenção: os números citados conferem com o TSE?', H2)]
    hist = pd.read_parquet(SRC / 'abstencao_uf_historico.parquet')
    t = [['UF', 'Abstenção T1 2026', 'T2 2026', 'Queda (p.p.)', 'Queda relativa', 'Queda média T1→T2 em 2014/2018/2022', '2026 acima do histórico (p.p.)']]
    w = hist.pivot(index='SG_UF', columns='y', values='queda')
    a = hist[hist.y == 2026].set_index('SG_UF')
    for uf in a.sort_values('t2').index:
        mh = w.loc[uf, [2014, 2018, 2022]].mean()
        t.append([uf, n(a.loc[uf, 't1'], 2) + '%', n(a.loc[uf, 't2'], 2) + '%', n(a.loc[uf, 'queda'], 2), n(100 * a.loc[uf, 'queda'] / a.loc[uf, 't1'], 1) + '%', n(mh, 2), n(a.loc[uf, 'queda'] - mh, 2)])
    st += [M.table(t, font=6.3), img(FIG / 'abstencao_historico.png', 22),
           Paragraph('Brasil: abstenção 20,84% no 1º turno e 18,99% no 2º (queda de 1,85 p.p.). Em 2014, 2018 e 2022 a abstenção do 2º turno foi 21,10%, 21,30% e 20,58% (contra 19,39%, 20,33% e 20,95% no 1º). '
                     'Os 10 municípios com menor abstenção e os estados citados conferem com os dados do TSE (diferenças de centésimos nos valores de 2022). '
                     'A Bahia tem a maior queda em pontos (3,26 p.p.); em termos relativos, Pernambuco (16,4%) fica à frente da Bahia (16,3%).', SM), PageBreak()]
    st += [Paragraph('2. Urnas que ficaram abertas após 17h (encerramento ≥17:10 no boletim) e quem venceu nelas', H2)]
    t = [['UF', 'Seções', 'Abertas ≥17:10', '%', 'Fechadas ≥19:00', 'No 1º turno (≥17:10)', 'Lula % nas abertas', 'Lula % nas demais', 'Lula % no estado', 'Margem Lula−Flávio (votos)',
          'Votos após 17h (logs das abertas)', 'Votos após 17h estimados (demais)', 'Estimativa líquida p/ Lula dos votos após 17h', 'Máximo teórico líquido p/ Lula']]
    for r in R.itertuples():
        t.append([r.uf, n(r.secoes), n(r.late_secoes), n(r.late_pct, 1), n(r.after19_secoes), n(r.t1_late_secoes), n(r.late_lula_pct, 1), n(r.ontime_lula_pct, 1), n(100 * r.lula / (r.lula + r.flavio), 1),
                  n(r.margem), n(r.a17_late), n(r.a17_rest_est), n(r.est_net), n(r.maxnet_l)])
    st += [M.table(t, font=5.6),
           Paragraph('“Estimativa líquida” = votos após 17h de cada urna aberta repartidos na proporção do resultado da própria urna (Lula − Flávio). “Máximo teórico” = caso extremo em que todo voto após 17h tivesse ido para Lula '
                     'até o limite dos votos que ele teve na urna, menos o mínimo forçado para Flávio. Servem como ordem de grandeza diante da margem.', SM)]
    if len(H):
        st += [img(FIG / 'votos_por_meia_hora.png', 15)]
    st += [PageBreak(), Paragraph('3. Por faixa de horário de encerramento — mesmas seções no 1º turno', H2)]
    t = [['UF', 'Encerramento', 'Seções', 'Comparecimento', 'Lula % T2', 'Lula % T1 (mesmas seções)', 'Abstenção T2', 'Abstenção T1', 'Votos após 17h (logs)', 'Manual T2 %', 'Manual T1 %', 'Abriu atrasada %', 'Fechou tarde também no T1 %']]
    for r in TI.itertuples():
        t.append([r.uf, r.tier, n(r.secoes), n(r.comp), n(r.lula_pct, 1), n(r.t1_lula_pct, 1), n(r.abst_pct, 1), n(r.t1_abst_pct, 1), n(r.after17), n(r.manual_pct, 1), n(r.t1_manual_pct, 1), n(r.open_late, 1), n(r.t1_late, 1)])
    st += [M.table(t, font=5.6)]
    if len(PL):
        st += [Paragraph('Mesmo local de votação: seções que ficaram abertas × seções do mesmo prédio que fecharam no horário', H2)]
        t = [['UF', 'Locais com os dois tipos', 'Lula % (abertas)', 'Lula % (no horário)', 'Diferença T2 (p.p.)', 'Mesma diferença no T1 (p.p.)', 'Diferença de abstenção T2 (p.p.)']]
        for r in PL.itertuples():
            t.append([r.uf, n(r.locais_mistos), n(r.lula_late, 1), n(r.lula_ontime, 1), n(r.diff_lula, 2), n(r.diff_lula_t1, 2), n(r.diff_abst, 2)])
        st += [M.table(t, font=6.5), Paragraph('Se a diferença do 2º turno for igual à do 1º, as urnas que ficaram abertas já votavam diferente das vizinhas antes da prorrogação (composição do eleitorado), e a prorrogação não alterou o padrão.', SM)]
    if len(C):
        st += [PageBreak(), Paragraph('4. As três cidades do pedido (Salvador, Feira de Santana, Lauro de Freitas)', H2)]
        t = [['Cidade', 'Seções', 'Abertas ≥17:10', 'Fechadas ≥19:00', 'Comparecimento', 'Abstenção T2', 'T1', 'Lula % T2', 'T1', 'Lula % nas abertas', 'nas demais', 'Votos após 17h (logs)', 'Logs lidos']]
        for r in C.itertuples():
            t.append([r.city, n(r.secoes), n(r.late), n(r.after19), n(r.comp), n(r.abst, 2), n(r.t1_abst, 2), n(r.lula_pct, 1), n(r.t1_lula_pct, 1), n(r.late_lula, 1), n(r.ontime_lula, 1), n(r.after17), n(r.logs)])
        st += [M.table(t, font=6.3)]
    st += [PageBreak(), Paragraph('5. A queda da abstenção tem relação com as urnas abertas?', H2), img(FIG / 'municipios_queda.png', 22)]
    mm = m[m.late_share.notna()]
    if len(mm):
        from scipy import stats
        rho1 = stats.spearmanr(mm.late_share, mm.queda)[0]
        rho2 = stats.spearmanr(mm.lula_t2 - mm.lula_t1, mm.queda)[0]
        t = [['UF', 'Ganho de comparecimento T1→T2 (votos)', 'Votos após 17h no T2 (logs + estimativa)', 'Votos após 17h ÷ ganho de comparecimento']]
        for r in R.itertuples():
            t.append([r.uf, n(r.comp_gain), n(r.a17_total_est), n(100 * r.a17_total_est / r.comp_gain, 1) + '%' if r.comp_gain and r.comp_gain > 0 else '—'])
        st += [M.table(t, font=7), Paragraph(f'Correlação (Spearman, municípios) entre % de seções abertas após 17:10 e queda da abstenção: {n(rho1, 2)}; entre variação do voto em Lula e queda da abstenção: {n(rho2, 2)}.', P),
               Paragraph('Leitura: se os votos após 17h forem pequenos frente ao ganho de comparecimento, a queda da abstenção ocorreu ao longo do dia e em todo o país, e não pode ser atribuída à prorrogação.', SM)]
    st += [Paragraph('Limites', H2)]
    for t_ in ['Arquivos do 2º turno obtidos do sistema de resultados do TSE antes da publicação nos dados abertos; podem ser substituídos se houver retotalização.',
               'Não há lista oficial das seções alcançadas pela prorrogação; a classificação usa o encerramento registrado no boletim.',
               'O log não identifica voto nem eleitor; a divisão dos votos após 17h entre candidatos é estimada pela proporção da urna, com limites teóricos.',
               'Comparação com o 1º turno usa a mesma chave de seção; seções criadas, agregadas ou movidas entre turnos ficam sem par.',
               'Nada aqui indica irregularidade nem a descarta.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d_):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo — não indica irregularidade nem a descarta')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'SEGUNDO_TURNO_2026_URNAS_ABERTAS_E_ABSTENCAO.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    ufs = [p.stem for p in sorted((SRC / 'bu').glob('*.parquet'))]
    D = {}
    for uf in ufs:
        D[uf] = load(uf)
        print('loaded', uf, len(D[uf]), flush=True)
    R, TI, H, C, PL = analyze(D)
    m = municipal(D)
    for nm, df in (('resumo_por_uf', R), ('faixas_encerramento', TI), ('votos_meia_hora', H), ('cidades_pedido_BA', C), ('mesmo_local', PL)):
        df.round(4).to_csv(OUT / f'{nm}.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    m.round(4).to_csv(OUT / 'municipios_abstencao_2026.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    with pd.ExcelWriter(OUT / 'URNAS_ABERTAS_2T_2026.xlsx', engine='xlsxwriter') as xw:
        for uf, b in D.items():
            cols = [c for c in ['uf', 'municipality_name', 'municipality', 'zone', 'section', 'voting_place', 'aptos', 'comp', 'abst_pct', 'opening', 'closing', 'close_min', 'lula', 'flavio', 'lula_pct',
                                'after_17', 'manual_bu', 'manual_after_17', 'last_vote', 't1_comp', 't1_abst_pct', 't1_lula_pct', 't1_close_min', 't1_manual'] if c in b]
            s = b[b.close_min >= 10][cols].sort_values('close_min', ascending=False).copy()
            s.insert(s.columns.get_loc('lula_pct') + 1, 'vencedor_na_urna', np.where(s.lula > s.flavio, 'LULA', np.where(s.flavio > s.lula, 'FLÁVIO BOLSONARO', 'EMPATE')))
            s.insert(s.columns.get_loc('vencedor_na_urna') + 1, 'margem_na_urna_votos', (s.lula - s.flavio).abs())
            s.round(2).to_excel(xw, sheet_name=f'abertas_{uf}', index=False, freeze_panes=(1, 0))
    figures(R, H, TI, m)
    pdf(R, TI, H, C, PL, m)
    print('ok')
