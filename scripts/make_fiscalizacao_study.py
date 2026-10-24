"""Inconsistency indicators per section, side-A/side-B association tests (permutation), magnitude vs margin, and an oversight-priority list.

Elections with urn logs: presidente 2022 T1/T2, 2026 T1; prefeito 2024 T1/T2. Logs re-identified by file name (contingency/reloaded urns included).
This measures statistical inconsistencies and whether they align with one side; it cannot observe vote buying or intent. Descriptive + permutation tests.
"""
import os
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

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M
import make_closing_swaps_study as X

OUT = Path('relatorios/fiscalizacao')
FIG = OUT / 'figuras'
FIG.mkdir(parents=True, exist_ok=True)
ORDER = X.ORDER
KEY = X.KEY
n = X.n
rng = np.random.default_rng(20261016)
REPS = 500
ELECS = [('P2022', 'Presidente 2022 T1', 'PRESIDENTE', 2022, 1), ('P2022b', 'Presidente 2022 T2', 'PRESIDENTE', 2022, 2), ('P2026', 'Presidente 2026 T1', 'PRESIDENTE', 2026, 1),
         ('M2024', 'Prefeito 2024 T1', 'PREFEITO', 2024, 1), ('M2024b', 'Prefeito 2024 T2', 'PREFEITO', 2024, 2)]
LAB = {e[0]: e[1] for e in ELECS}
FLAGS = [('f_late', 'Votos após 17h: fração acima do P99 do estado (≥20 votos)'), ('f_manual', 'Habilitação manual pelo mesário acima do esperado (resíduo > P99)'),
         ('f_manual_late', 'Habilitações manuais após 17h ≥ 10'), ('f_fast', 'Ritmo após 17h acelerado (mediana < 40 s entre votos, ≥20 votos)'),
         ('f_last19', 'Último voto depois das 19h'), ('f_turnout', 'Comparecimento muito acima do município (z>3 e +10 p.p.)'),
         ('f_close', 'Encerrou >60 min após 17h sem troca de urna'), ('f_cancel', 'Cancelamentos/suspensões pelo mesário acima do P99 (≥5)')]
FCOLS = [f for f, _ in FLAGS]
_PROF = None


def ops_path(office, uf, year, turn):
    if office == 'PRESIDENTE':
        if uf == 'BA' and (year, turn) == (2022, 2):
            return Path('research/piloto-ba-2022-t2/analysis/operations.jsonl')
        return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / f'{year}-t{turn}' / 'operations.jsonl'
    return Path('research/municipais') / uf / f'{year}-t{turn}' / 'operations.jsonl'


def profile():
    global _PROF
    if _PROF is None:
        fr = []
        for uf in ORDER:
            f = Path('research/perfil/2022') / f'{uf}.parquet'
            if f.exists():
                p = pd.read_parquet(f)
                p['uf'] = uf
                v = p.voters.where(p.voters > 0)
                p['biometria_pct'] = 100 * p.biometria / v
                p['age60_pct'] = 100 * p.age60 / v
                p['low_school_pct'] = 100 * p.low_school / v
                fr.append(p[KEY + ['uf', 'place_name', 'voters', 'biometria_pct', 'age60_pct', 'low_school_pct']])
        _PROF = pd.concat(fr, ignore_index=True) if fr else None
    return _PROF


def load_election(eid):
    _, lab, office, year, turn = next(e for e in ELECS if e[0] == eid)
    frames = []
    prof = profile()
    for uf in ORDER:
        f = X.adir(office, uf, year, turn)
        if not (f / 'summary.json').exists():
            continue
        s = pd.read_parquet(f / 'sections.parquet', columns=KEY + ['municipality_name', 'voting_place', 'eligible', 'attendance', 'valid_votes', 'manual_bu', 'opening_bu', 'closure_bu',
                                                                 'turnout', 'municipal_median', 'state_median', 'state_mad', 'winner_party', 'winner_pct', 'margin_pp'])
        o = pd.read_json(ops_path(office, uf, year, turn), lines=True, dtype=False)
        if 'identity_status' not in o:
            o['identity_status'] = o.get('status', 'PARSED')
        o = o[o.identity_status.isin(['PARSED', 'PARSED_FILENAME'])].copy()
        for k in KEY:
            o[k] = pd.to_numeric(o[k], errors='coerce')
        o = o.dropna(subset=KEY).drop_duplicates(KEY)
        o[KEY] = o[KEY].astype(int)
        keep = [c for c in ['member', 'identity_status', 'vote_events', 'after_17_recorded', 'manual_sequence_votes', 'after_17_manual_sequence', 'manual_requests', 'cancellations',
                            'manual_unattributed_votes', 'after_17_manual_unattributed', 'late_interval_median_seconds', 'votes_1630_1700', 'last_vote', 'first_vote', 'clock_reversals'] if c in o]
        s = s.merge(o[KEY + keep], on=KEY, how='left')
        c = pd.read_parquet(f / 'candidate_sections.parquet')
        if office == 'PRESIDENTE':
            s = s.join(c[c.party == 'PT'].groupby(KEY).votes.sum().rename('votes_a'), on=KEY).join(c[c.party == 'PL'].groupby(KEY).votes.sum().rename('votes_b'), on=KEY)
            s['cand_a'], s['cand_b'] = 'PT', 'PL'
        else:
            tot = c.groupby(['municipality', 'candidate_number']).votes.sum().reset_index().sort_values(['municipality', 'votes'], ascending=[True, False])
            tot['r'] = tot.groupby('municipality').cumcount()
            lead, run = tot[tot.r == 0][['municipality', 'candidate_number']], tot[tot.r == 1][['municipality', 'candidate_number']]
            s = s.join(c.merge(lead, on=['municipality', 'candidate_number']).groupby(KEY).votes.sum().rename('votes_a'), on=KEY)
            s = s.join(c.merge(run, on=['municipality', 'candidate_number']).groupby(KEY).votes.sum().rename('votes_b'), on=KEY)
            s['cand_a'], s['cand_b'] = 'líder do município', '2º do município'
        ce = X.load_ceft(year, turn, uf)
        if ce is not None:
            s = s.merge(ce[KEY + ['swap', 'red']], on=KEY, how='left')
        else:
            s['swap'] = np.nan
        s['uf'] = uf
        if prof is not None:
            s = s.merge(prof[prof.uf == uf][KEY + ['place_name', 'voters', 'biometria_pct', 'age60_pct', 'low_school_pct']], on=KEY, how='left')
        frames.append(s)
    d = pd.concat(frames, ignore_index=True)
    for c in ['cancellations', 'manual_requests', 'late_interval_median_seconds', 'place_name', 'biometria_pct', 'age60_pct', 'low_school_pct']:
        if c not in d:
            d[c] = np.nan
    d['eid'], d['lab'] = eid, lab
    d['voting_place'] = d.voting_place.astype(str)
    d['place'] = d.uf + '|' + d.municipality.astype(str) + '|' + d.zone.astype(str) + '|' + d.voting_place
    d['mun'] = d.uf + '|' + d.municipality.astype(str)
    d['has_log'] = d.vote_events.notna() & (d.vote_events > 0)
    d['log_complete'] = d.has_log & (d.vote_events == d.attendance)
    d['contingency'] = d.identity_status.eq('PARSED_FILENAME')
    v = d.vote_events.where(d.has_log)
    d['late_share'] = d.after_17_recorded / v
    d['manual_share'] = d.manual_sequence_votes / v
    d['cancel_rate'] = d.cancellations / v
    d['last_min'] = X.hhmm_to_min(d.last_vote.fillna(''))
    d['close_min'] = X.minutes_after(d.closure_bu, 17)
    vv = d.valid_votes.where(d.valid_votes > 0)
    d['share_a'] = 100 * d.votes_a.fillna(0) / vv
    d['share_b'] = 100 * d.votes_b.fillna(0) / vv
    d['diff_ab'] = d.share_a - d.share_b
    return d


def expected_manual(d):
    d['manual_resid'] = np.nan
    for uf, g in d.groupby('uf'):
        ls = g.low_school_pct.fillna(g.low_school_pct.median())
        ok = g.log_complete & g.manual_share.notna() & g.biometria_pct.notna() & g.age60_pct.notna() & (g.eligible >= 50)
        if ok.sum() < 200:
            continue
        Xm = np.column_stack([np.ones(ok.sum()), g.biometria_pct[ok], g.age60_pct[ok], ls[ok]])
        beta, *_ = np.linalg.lstsq(Xm, g.manual_share[ok], rcond=None)
        allok = g.manual_share.notna() & g.biometria_pct.notna() & g.age60_pct.notna()
        Xa = np.column_stack([np.ones(allok.sum()), g.biometria_pct[allok], g.age60_pct[allok], ls[allok]])
        d.loc[g.index[allok], 'manual_resid'] = g.manual_share[allok] - Xa @ beta
    return d


def flags(d):
    d = expected_manual(d)
    e = d.eligible >= 50
    base = e & d.log_complete

    def p99(col):
        thr = d[base].groupby('uf')[col].quantile(.99)
        return d.uf.map(thr)
    d['f_late'] = (d.late_share > p99('late_share')) & (d.after_17_recorded >= 20) & base
    d['f_manual'] = (d.manual_resid > p99('manual_resid')) & base
    d['f_manual_late'] = (d.after_17_manual_sequence >= 10) & base
    d['f_fast'] = (d.late_interval_median_seconds < 40) & (d.after_17_recorded >= 20) & base
    d['f_last19'] = (d.last_min >= 19 * 60) & base
    z = (d.turnout - d.state_median) / d.state_mad.where(d.state_mad > 0)
    d['f_turnout'] = (z > 3) & (d.turnout - d.municipal_median >= .1) & e
    d['f_close'] = (d.close_min > 60) & (d.swap != True) & e
    d['f_cancel'] = (d.cancel_rate > p99('cancel_rate')) & (d.cancellations >= 5) & base
    for f in FCOLS:
        d[f] = d[f].fillna(False).astype(bool)
    d['score'] = d[FCOLS].sum(axis=1)
    return d


def place_wmean(df, col, w='valid_votes'):
    """Média de `col` no local de votação PONDERADA por votos válidos: a mesma referência usada no teste de permutação e na varredura."""
    ww = df[w].astype(float)
    return (df[col] * ww).groupby(df.place).transform('sum') / ww.groupby(df.place).transform('sum')


def perm_test(d, flag, y='diff_ab', reps=REPS):
    """Diferença (A − B) entre seções sinalizadas e não sinalizadas, medida como desvio da média PONDERADA do próprio local.
    Dois esquemas de embaralhamento da sinalização: dentro do município (colunas sem sufixo) e dentro do local de votação (sufixo _local).
    Além do DP, devolve média e quantis 2,5%/97,5% do nulo, para desenhar a faixa do acaso centrada no nulo e não no efeito observado."""
    g = d[d[y].notna() & (d.eligible >= 50) & d.valid_votes.gt(0)].copy()
    w = g.valid_votes.astype(float)
    wmean = (g[y] * w).groupby(g.place).transform('sum') / w.groupby(g.place).transform('sum')
    g['yr'] = g[y] - wmean
    f = g[flag].values.astype(bool)
    if f.sum() < 10:
        return None
    yr, w = g.yr.values, w.values

    def stat(ff):
        return np.average(yr[ff], weights=w[ff]) - np.average(yr[~ff], weights=w[~ff])
    obs = stat(f)
    raw = np.average(g[y].values[f], weights=w[f]) - np.average(g[y].values[~f], weights=w[~f])
    ra = (g.share_a - place_wmean(g, 'share_a')).values
    out = dict(flag=flag, n_flag=int(f.sum()), n=len(g), raw_diff=raw, within_place_diff=obs, excess_votes_a=float((ra / 100 * w)[f].sum()),
               share_a_flag=np.average(g.share_a.values[f], weights=w[f]), share_a_rest=np.average(g.share_a.values[~f], weights=w[~f]))
    for suffix, key in (('', g.mun), ('_local', g.place)):
        grp = pd.factorize(key)[0].astype(float)
        o0 = np.argsort(grp, kind='stable')
        f0 = f[o0]
        null = np.empty(reps)
        for i in range(reps):
            o1 = np.argsort(grp + rng.random(len(grp)), kind='stable')
            fp = np.empty_like(f)
            fp[o1] = f0
            null[i] = stat(fp)
        q = np.quantile(null, [.025, .975])
        out.update({f'null_sd{suffix}': null.std(), f'null_mean{suffix}': null.mean(), f'null_q025{suffix}': q[0], f'null_q975{suffix}': q[1],
                    f'p_perm{suffix}': (1 + (np.abs(null) >= abs(obs)).sum()) / (reps + 1)})
    return out


def bh(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    ranked = p[order] * len(p) / (np.arange(len(p)) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    q = np.empty_like(p)
    q[order] = np.minimum(ranked, 1)
    return q


def run():
    results, tests, by_state, score_tab, lists = [], [], [], [], []
    for eid, lab, office, year, turn in ELECS:
        d = flags(load_election(eid))
        d.to_parquet(OUT / f'secoes_indicadores_{eid}.parquet', index=False)
        tot = dict(eid=eid, lab=lab, sections=len(d), with_log=int(d.has_log.sum()), log_complete=int(d.log_complete.sum()), contingency_logs=int(d.contingency.sum()),
                   late_votes_all=int(d.after_17_recorded.fillna(0).sum()), late_votes_contingency=int(d.after_17_recorded[d.contingency].fillna(0).sum()),
                   manual_votes=int(d.manual_sequence_votes.fillna(0).sum()), manual_late=int(d.after_17_manual_sequence.fillna(0).sum()))
        for f in FCOLS:
            tot[f] = int(d[f].sum())
        for k in range(5):
            tot[f'score_{k}'] = int((d.score == k).sum()) if k < 4 else int((d.score >= 4).sum())
        results.append(tot)
        d['score2'], d['score3'] = d.score >= 2, d.score >= 3
        for f in FCOLS + ['score2', 'score3']:
            r = perm_test(d, f)
            if r:
                r.update(eid=eid, lab=lab)
                tests.append(r)
                print('test', eid, f, round(r['within_place_diff'], 3), r['p_perm'], flush=True)
        g = d[(d.eligible >= 50) & d.valid_votes.gt(0)].copy()
        g['ra'] = g.share_a - place_wmean(g, 'share_a')
        for k in range(4):
            s = g[(g.score == k) if k < 3 else (g.score >= 3)]
            if len(s) < 5:
                continue
            wv, rv = s.valid_votes.values.astype(float), s.ra.values
            boots = [np.average(rv[idx], weights=wv[idx]) for idx in (rng.integers(0, len(s), len(s)) for _ in range(300))]
            score_tab.append(dict(eid=eid, lab=lab, score=str(k) if k < 3 else '3+', sections=len(s), share_a=np.average(s.share_a, weights=wv), resid_a=np.average(rv, weights=wv),
                                  lo=np.quantile(boots, .025), hi=np.quantile(boots, .975), late_votes=int(s.after_17_recorded.fillna(0).sum())))
        for uf, s in d.groupby('uf'):
            va, vb = s.votes_a.fillna(0).sum(), s.votes_b.fillna(0).sum()
            gg = g[g.uf == uf]
            fl = gg.score >= 2
            by_state.append(dict(eid=eid, lab=lab, uf=uf, sections=len(s), votes_a=int(va), votes_b=int(vb), margin_votes=int(va - vb), margin_pp=100 * (va - vb) / s.valid_votes.sum(),
                                 flagged2=int(fl.sum()), late_flag=int(s.f_late.sum()), manual_flag=int(s.f_manual.sum()), excess_a_flagged=float((gg.ra / 100 * gg.valid_votes)[fl].sum()),
                                 late_votes_flagged=int(gg.after_17_recorded[fl].fillna(0).sum()), share_a_flagged=np.average(gg.share_a[fl], weights=gg.valid_votes[fl]) if fl.any() else np.nan,
                                 share_a_state=100 * va / s.valid_votes.sum()))
        cols = ['eid', 'lab', 'uf', 'municipality', 'municipality_name', 'zone', 'section', 'voting_place', 'place_name', 'eligible', 'attendance', 'score'] + FCOLS + \
               ['after_17_recorded', 'late_share', 'manual_sequence_votes', 'manual_resid', 'after_17_manual_sequence', 'late_interval_median_seconds', 'last_vote', 'close_min', 'swap', 'contingency',
                'cand_a', 'share_a', 'cand_b', 'share_b', 'winner_party', 'winner_pct']
        L = d[d.score >= 2][cols].copy()
        L['resid_a_place'] = (d.share_a - place_wmean(d, 'share_a'))[L.index]
        lists.append(L)
    R, T, S, SC, L = pd.DataFrame(results), pd.DataFrame(tests), pd.DataFrame(by_state), pd.DataFrame(score_tab), pd.concat(lists, ignore_index=True)
    T['q'] = bh(T.p_perm.values)
    T['q_local'] = bh(T.p_perm_local.values)
    a = L[L.eid == 'P2022'][KEY + ['uf', 'score']].rename(columns={'score': 'score_2022'})
    prio = L[L.eid == 'P2026'].merge(a, on=KEY + ['uf'], how='left')
    prio['recorrente'] = prio.score_2022.notna()
    prio = prio.sort_values(['recorrente', 'score', 'after_17_recorded'], ascending=[False, False, False])
    zones = prio.groupby(['uf', 'municipality_name', 'zone']).agg(secoes_sinalizadas=('section', 'size'), recorrentes=('recorrente', 'sum'), score_medio=('score', 'mean'),
                                                                   votos_apos_17h=('after_17_recorded', 'sum'), manuais_apos_17h=('after_17_manual_sequence', 'sum')).reset_index()
    zones = zones.sort_values(['secoes_sinalizadas', 'recorrentes'], ascending=False)
    return R, T, S, SC, L, prio, zones


def figures(T):
    f, ax = plt.subplots(figsize=(11, 4.2))
    labs = FCOLS + ['score2', 'score3']
    x = np.arange(len(labs))
    for i, eid in enumerate(['P2022', 'P2026', 'M2024']):
        s = T[T.eid == eid].set_index('flag').reindex(labs)
        xx = x + (i - 1) * .25
        ax.vlines(xx, s.null_q025, s.null_q975, color='#c3c2b7', lw=5, zorder=1, label='faixa de 95% do acaso' if i == 0 else None)
        ax.plot(xx, s.within_place_diff, 'o', ms=4.5, label=LAB[eid], zorder=3)
    ax.axhline(0, color='k', lw=.7)
    ax.set_xticks(x)
    ax.set_xticklabels([lb.replace('f_', '') for lb in labs], fontsize=7)
    ax.set(ylabel='dif. (A − B) sinalizadas − demais, dentro do mesmo local, p.p.',
           title='A sinalização se associa a um lado? (faixa cinza = 2,5%–97,5% do acaso, embaralhando no município; ponto = observado)')
    ax.legend(fontsize=7)
    f.tight_layout()
    f.savefig(FIG / 'perm_tests.png', dpi=150)
    plt.close(f)


def img(p, w):
    iw, ih = PI.open(p).size
    return Image(str(p), width=w * cm, height=w * cm * ih / iw)


def pdf(R, T, S, SC, L, prio, zones):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Inconsistências por seção, teste de direção por permutação (lado A × lado B) e ferramenta de fiscalização', H1),
          Paragraph('Base: logs de urna re-identificados (inclui urnas de contingência e recarregadas), boletins, correspondências de urnas e perfil do eleitorado 2022. 10 estados; presidente 2022 (T1 e T2) e 2026 (T1); '
                    'prefeito 2024 (T1 e T2). Lado A = PT (presidente) ou candidato líder no município (prefeito); lado B = PL ou 2º colocado. Os indicadores medem comportamento operacional da seção '
                    '(horários, habilitações manuais pelo mesário, ritmo, comparecimento); nenhum observa compra de voto, coação ou intenção. “Inconsistência” aqui é desvio estatístico, e o teste '
                    'pergunta apenas se as seções desviantes votam diferente das vizinhas do mesmo local de votação.', P),
          Paragraph(f'Método do teste: diferença (A − B) entre seções sinalizadas e não sinalizadas, medida como desvio da média ponderada do próprio local de votação (remove bairro/eleitorado), ponderada por votos válidos. '
                    f'p = fração de {REPS} embaralhamentos da sinalização que produzem diferença igual ou maior em módulo (bilateral), em dois esquemas: dentro do município e, como sensibilidade mais fiel à pergunta do mesmo prédio, '
                    'dentro do próprio local de votação (colunas “local”). q = correção para múltiplos testes (Benjamini–Hochberg). “Excesso de votos do lado A” = soma, nas seções sinalizadas, de (% do lado A na seção − média PONDERADA por votos válidos do local) × votos válidos: ordem de grandeza descritiva, não efeito nem votos irregulares. '
                    'Associação não é causa: a direção pode refletir o perfil de quem enfrenta fila.', NOTE),
          Paragraph('1. Indicadores e sinalizações (seções com ≥50 eleitores e log completo, salvo comparecimento e encerramento)', H2)]
    t = [['Eleição', 'Seções', 'Com log', 'Log completo', 'Contingência / recarregadas', 'Votos após 17h (todos os logs)', '… em contingência', 'Manuais', 'Manuais após 17h'] + [f.replace('f_', '') for f in FCOLS] + ['score 0', '1', '2', '3', '4+']]
    for r in R.itertuples():
        t.append([r.lab, n(r.sections), n(r.with_log), n(r.log_complete), n(r.contingency_logs), n(r.late_votes_all), n(r.late_votes_contingency), n(r.manual_votes), n(r.manual_late)] +
                 [n(getattr(r, f)) for f in FCOLS] + [n(r.score_0), n(r.score_1), n(r.score_2), n(r.score_3), n(r.score_4)])
    st += [M.table(t, font=5.4)]
    t = [['Sinalização', 'Definição']]
    for f, desc in FLAGS:
        t.append([f.replace('f_', ''), desc])
    st += [M.table(t, [3 * cm, 20 * cm], font=7), PageBreak(), Paragraph('2. A sinalização se associa a um lado? (permutação dentro do município e dentro do local)', H2), img(FIG / 'perm_tests.png', 22)]
    t = [['Eleição', 'Sinalização', 'Seções sinalizadas', 'Lado A % (sinalizadas)', 'Lado A % (demais)', 'Dif. bruta A−B p.p.', 'Dif. dentro do local p.p.', 'Faixa 95% do acaso (município)', 'p (município)', 'q (BH)', 'DP acaso (local)', 'p (local)', 'Excesso de votos do lado A nas sinalizadas']]
    for r in T.itertuples():
        t.append([r.lab, r.flag.replace('f_', ''), n(r.n_flag), n(r.share_a_flag, 1), n(r.share_a_rest, 1), n(r.raw_diff, 2), n(r.within_place_diff, 2), f'[{n(r.null_q025, 2)}; {n(r.null_q975, 2)}]', n(r.p_perm, 3), n(r.q, 3),
                  n(r.null_sd_local, 2), n(r.p_perm_local, 3), n(r.excess_votes_a)])
    st += [M.table(t, font=5.2), PageBreak(), Paragraph('3. Quanto mais sinalizações, mais desvio?', H2),
           Paragraph('Resíduo = % do lado A na seção − % no seu local de votação (ponderado por votos válidos); IC 95% por bootstrap.', P)]
    t = [['Eleição', 'Score', 'Seções', 'Lado A %', 'Resíduo vs local p.p.', 'IC 95%', 'Votos após 17h']]
    for r in SC.itertuples():
        t.append([r.lab, r.score, n(r.sections), n(r.share_a, 1), n(r.resid_a, 2), f'[{n(r.lo, 2)}; {n(r.hi, 2)}]', n(r.late_votes)])
    st += [M.table(t, font=6.5), Paragraph('4. Por estado: magnitude frente à margem', H2),
           Paragraph('“Excesso do lado A nas seções com score ≥2” comparado à margem do estado entre A e B. Se o excesso for pequeno frente à margem, as inconsistências não têm escala para alterar o resultado estadual, '
                     'qualquer que seja sua causa.', P)]
    t = [['Eleição', 'UF', 'Seções', 'Votos A', 'Votos B', 'Margem A−B (votos)', 'Margem p.p.', 'Seções score ≥2', 'Lado A % nelas', 'Lado A % no estado', 'Excesso A nelas (votos)', 'Excesso ÷ margem %', 'Votos após 17h nelas']]
    for r in S[S.eid.isin(['P2022', 'P2026', 'M2024'])].itertuples():
        t.append([r.lab, r.uf, n(r.sections), n(r.votes_a), n(r.votes_b), n(r.margin_votes), n(r.margin_pp, 1), n(r.flagged2), n(r.share_a_flagged, 1), n(r.share_a_state, 1), n(r.excess_a_flagged),
                  n(100 * r.excess_a_flagged / r.margin_votes, 2) if r.margin_votes else '—', n(r.late_votes_flagged)])
    st += [M.table(t, font=5.6), PageBreak(), Paragraph('5. Ferramenta de fiscalização: zonas e seções prioritárias', H2),
           Paragraph(f'Lista prioritária para o 2º turno de 2026: seções com score ≥2 em 2026 T1, ordenadas por recorrência (também sinalizadas em 2022 T1), score e votos após 17h. '
                     f'{n(len(prio))} seções, {n(int(prio.recorrente.sum()))} recorrentes. Zonas com mais seções sinalizadas abaixo; listas completas em XLSX/CSV nesta pasta. '
                     'Uso: priorizar fiscais de partido/MP e checagem presencial de fila, habilitação manual e encerramento. Sinalização não é acusação.', P)]
    t = [['UF', 'Município', 'Zona', 'Seções sinalizadas', 'Recorrentes', 'Score médio', 'Votos após 17h', 'Manuais após 17h']]
    for r in zones.head(30).itertuples():
        t.append([r.uf, r.municipality_name, str(r.zone), n(r.secoes_sinalizadas), n(r.recorrentes), n(r.score_medio, 1), n(r.votos_apos_17h), n(r.manuais_apos_17h)])
    st += [M.table(t, font=6.5), Paragraph('Seções prioritárias (25 primeiras):', M.P)]
    t = [['UF', 'Município', 'Zona', 'Seção', 'Local', 'Score', 'Sinais', 'Após 17h', 'Manuais após 17h', 'Último voto', 'Lado A %', 'Resíduo vs local', 'Rec. 2022']]
    for r in prio.head(25).itertuples():
        sig = ','.join(f.replace('f_', '') for f in FCOLS if getattr(r, f))
        t.append([r.uf, r.municipality_name, str(r.zone), str(r.section), (r.place_name or '')[:30] if isinstance(r.place_name, str) else '', n(r.score), sig, n(r.after_17_recorded), n(r.after_17_manual_sequence),
                  str(r.last_vote)[-8:], n(r.share_a, 1), n(r.resid_a_place, 1), 'sim' if r.recorrente else 'não'])
    st += [M.table(t, font=5.4), PageBreak(), Paragraph('6. Síntese (gerada dos números)', H2)]
    lines = []
    for eid in ['P2022', 'P2026', 'M2024']:
        tt = T[T.eid == eid]
        if tt.empty:
            continue
        sig = tt[tt.q < .05]
        lines.append(f'{LAB[eid]}: {len(tt)} testes; {len(sig)} com q<0,05 ({int((sig.within_place_diff > 0).sum())} a favor do lado A, {int((sig.within_place_diff < 0).sum())} contra). '
                     f'Maior diferença dentro do local: {n(tt.within_place_diff.abs().max(), 2)} p.p. ({tt.loc[tt.within_place_diff.abs().idxmax(), "flag"].replace("f_", "")}).')
    s26 = S[S.eid == 'P2026']
    lines.append('Presidente 2026 T1, excesso do lado A nas seções com score ≥2 ÷ margem estadual: ' + '; '.join(f'{r.uf} {n(100 * r.excess_a_flagged / r.margin_votes, 1)}%' for r in s26.itertuples() if r.margin_votes) + '.')
    r = R.set_index('eid')
    lines.append(f'Votos após 17h agora contados em todos os logs: 2022 T1 {n(r.loc["P2022", "late_votes_all"])} (dos quais {n(r.loc["P2022", "late_votes_contingency"])} em urnas de contingência/recarregadas), '
                 f'2024 T1 {n(r.loc["M2024", "late_votes_all"])} ({n(r.loc["M2024", "late_votes_contingency"])}), 2026 T1 {n(r.loc["P2026", "late_votes_all"])} ({n(r.loc["P2026", "late_votes_contingency"])}).')
    for l in lines:
        st.append(Paragraph('• ' + l, P))
    st += [Paragraph('Limites', H2)]
    for t_ in ['Compra de voto, coação e uso indevido de prerrogativas do mesário não são observáveis nos dados; os indicadores medem desvios operacionais e o teste mede apenas alinhamento com um lado.',
               'Diferença dentro do local reduz, mas não elimina, fatores de composição (seções do mesmo prédio podem reunir eleitorados diferentes).',
               'Nos 1º turnos, filas longas ocorrem onde o eleitorado é mais jovem, menos escolarizado e com mais habilitação manual — perfil que também se associa ao voto; o teste dentro do local controla parte disso.',
               'O perfil é de 2022; horários são do relógio de cada urna; 2022 T2 e 2024 T2 têm poucas seções sinalizadas e testes de baixo poder.',
               'Nada aqui indica irregularidade nem a descarta; é instrumento de priorização de fiscalização.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d_):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Descritivo e estatístico — sinalização não é acusação')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'INCONSISTENCIAS_E_FISCALIZACAO.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    R, T, S, SC, L, prio, zones = run()
    for nm, df in (('resumo_indicadores', R), ('testes_permutacao', T), ('por_estado_margem', S), ('score_vs_residuo', SC), ('zonas_prioritarias_2026', zones)):
        df.round(4).to_csv(OUT / f'{nm}.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    L.round(4).to_csv(OUT / 'secoes_sinalizadas_todas.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    prio.round(4).to_csv(OUT / 'lista_prioritaria_2026_T2.csv', sep=';', decimal=',', index=False, encoding='utf-8-sig')
    with pd.ExcelWriter(OUT / 'FERRAMENTA_FISCALIZACAO.xlsx', engine='xlsxwriter') as xw:
        zones.round(2).to_excel(xw, sheet_name='zonas_prioritarias_2026', index=False, freeze_panes=(1, 0))
        prio.round(3).to_excel(xw, sheet_name='secoes_prioritarias_2026', index=False, freeze_panes=(1, 0))
        for eid in L.eid.unique():
            L[L.eid == eid].round(3).to_excel(xw, sheet_name=f'sinalizadas_{eid}', index=False, freeze_panes=(1, 0))
        T.round(4).to_excel(xw, sheet_name='testes', index=False)
    figures(T)
    pdf(R, T, S, SC, L, prio, zones)
    print('ok')
