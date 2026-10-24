"""Varredura completa por local de votação: votos tardios + habilitação manual (sem biometria), comparados às demais seções
do mesmo local, com teste de diferença real, cruzamento prefeito × presidente por seção e lista de locais para fiscalização.

Entrada: relatorios/fiscalizacao/secoes_indicadores_<eid>.parquet (gerados por make_fiscalizacao_study.py).
Saída:   relatorios/fiscalizacao/varredura/ (CSV, XLSX geral e por UF, PDF).

Comportamento por seção e eleição (mesmas definições do histórico):
  TARDIO  = fração de votos após 17h > P99 do estado (≥20 votos) OU último voto ≥19h OU encerramento >60 min sem troca de urna
  MANUAL  = habilitação manual pelo mesário acima do esperado (resíduo > P99) OU ≥10 habilitações manuais após 17h
Comparação: as outras seções do mesmo local de votação SEM comportamento ("pares"). Diferença real = |diferença| ≥ 5 p.p.
e |z| ≥ 2, onde z usa a dispersão dos pares (≥3 pares; senão, a dispersão das seções comuns do município) e o erro
binomial da própria seção. O mesmo teste aplicado às seções comuns (deixando cada uma de fora) dá a taxa-base de "diferença real"
que se espera por acaso.
Lado A = PT (presidente) ou candidato líder do município (prefeito); lado B = PL ou 2º colocado.
Sinalização não é acusação: mede desvio de comportamento operacional e de resultado, não compra de voto.
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
import make_bahia_reports as M  # noqa: E402  (estilos de PDF e formatação numérica)

SRC = Path('relatorios/fiscalizacao')
OUT = SRC / 'varredura'
OUT.mkdir(parents=True, exist_ok=True)
KEY = ['municipality', 'zone', 'section']
PKEY = ['uf', 'municipality', 'zone', 'voting_place']
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
ELECS = [('P2022', 'Pres 2022 T1', 'pres'), ('P2022b', 'Pres 2022 T2', 'pres'), ('M2024', 'Pref 2024 T1', 'pref'),
         ('M2024b', 'Pref 2024 T2', 'pref'), ('P2026', 'Pres 2026 T1', 'pres')]
EIDS = [e for e, _, _ in ELECS]
PRES = [e for e, _, t in ELECS if t == 'pres']
PREF = [e for e, _, t in ELECS if t == 'pref']
LAB = {e: lab for e, lab, _ in ELECS}
MIN_PP = 5.0     # diferença mínima (p.p.) para "diferença real"
BIG = 10.0       # "diferença alta"
ZMIN = 2.0       # |z| mínimo
MIN_PEERS = 3    # pares mínimos para usar a dispersão do próprio local
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')


def n(x, d=0):
    return M.n(x, d)


def load(eid):
    f = SRC / f'secoes_indicadores_{eid}.parquet'
    if not f.exists():
        return None
    d = pd.read_parquet(f)
    d = d[(d.eligible >= 50) & d.valid_votes.gt(0) & d.share_a.notna()].copy()
    for c in ['f_late', 'f_last19', 'f_close', 'f_manual', 'f_manual_late']:
        d[c] = d[c].fillna(False).astype(bool)
    d['LATE'] = d.f_late | d.f_last19 | d.f_close
    d['MANUAL'] = d.f_manual | d.f_manual_late
    d['BEH'] = d.LATE | d.MANUAL
    d['place_name'] = d.place_name.fillna('').astype(str)
    d['municipality_name'] = d.municipality_name.fillna('').astype(str)
    d['voting_place'] = d.voting_place.astype(str)
    d['after_17_recorded'] = d.after_17_recorded.fillna(0)
    d['after_17_manual_sequence'] = d.after_17_manual_sequence.fillna(0)
    d['eid'] = eid
    return d


def loo(d, by, clean, x, w):
    """Média ponderada, média simples e variância de x entre as seções `clean` do grupo `by`, excluindo a própria linha
    (leave-one-out). Para linhas com comportamento nada é excluído: os pares são todas as seções comuns do grupo."""
    c = clean.astype(float).values
    x = x.astype(float).values
    w = w.astype(float).values
    t = pd.DataFrame({'c': c, 'sx': x * c, 'sx2': x * x * c, 'sw': w * c, 'swx': w * x * c, 'g': d[by].values})
    S = t.groupby('g')[['c', 'sx', 'sx2', 'sw', 'swx']].transform('sum')
    npeer = S.c.values - c
    s1 = S.sx.values - x * c
    s2 = S.sx2.values - x * x * c
    sw = S.sw.values - w * c
    swx = S.swx.values - w * x * c
    with np.errstate(invalid='ignore', divide='ignore'):
        mean_w = np.where(sw > 0, swx / sw, np.nan)
        mean_u = np.where(npeer > 0, s1 / npeer, np.nan)
        var = np.where(npeer > 1, (s2 - npeer * mean_u ** 2) / (npeer - 1), np.nan)
    return npeer, mean_w, np.clip(var, 0, None)


def compare(d):
    clean = ~d.BEH
    n_pl, a_pl, v_pl = loo(d, 'place', clean, d.share_a, d.valid_votes)
    n_mu, a_mu, v_mu = loo(d, 'mun', clean, d.share_a, d.valid_votes)
    _, b_pl, _ = loo(d, 'place', clean, d.share_b, d.valid_votes)
    _, b_mu, _ = loo(d, 'mun', clean, d.share_b, d.valid_votes)
    use_pl = n_pl >= 1
    d['cmp_n'] = np.where(use_pl, n_pl, n_mu)
    d['cmp_level'] = np.select([n_pl >= MIN_PEERS, n_pl >= 1], ['local', 'local (poucos pares)'], 'município')
    d['cmp_a'] = np.where(use_pl, a_pl, a_mu)
    d['cmp_b'] = np.where(use_pl, b_pl, b_mu)
    var = np.where(n_pl >= MIN_PEERS, v_pl, v_mu)
    p = (d.share_a / 100).clip(.005, .995)
    se_bin = 100 * np.sqrt(p * (1 - p) / d.valid_votes)
    d['diff_a'] = d.share_a - d.cmp_a
    with np.errstate(invalid='ignore', divide='ignore'):
        d['z_a'] = d.diff_a / np.sqrt(var + se_bin ** 2)
    d['real'] = (d.diff_a.abs() >= MIN_PP) & (d.z_a.abs() >= ZMIN)
    d['big'] = d.diff_a.abs() >= BIG
    d['dir'] = np.where(d.real, np.where(d.diff_a > 0, 'A', 'B'), '')
    d['winner_ab'] = np.where(d.share_a > d.share_b, 'A', np.where(d.share_b > d.share_a, 'B', 'empate'))
    d['cmp_winner'] = np.where(d.cmp_a > d.cmp_b, 'A', np.where(d.cmp_b > d.cmp_a, 'B', 'empate'))
    d['excess_a_votes'] = d.diff_a / 100 * d.valid_votes
    tn_pl, tm_pl, _ = loo(d, 'place', clean, 100 * d.turnout, d.eligible)
    _, tm_mu, _ = loo(d, 'mun', clean, 100 * d.turnout, d.eligible)
    d['diff_turnout'] = 100 * d.turnout - np.where(tn_pl >= 1, tm_pl, tm_mu)
    # local inteiro: quando metade ou mais das seções do local tem comportamento, compara o local ao município
    g = d.groupby('place')
    d['place_n'] = g.section.transform('size')
    d['place_beh'] = g.BEH.transform('sum')
    d['place_share_a'] = 100 * g.votes_a.transform('sum') / g.valid_votes.transform('sum')
    mun_clean = d[clean].groupby('mun').apply(lambda s: pd.Series(dict(mun_clean_a=np.average(s.share_a, weights=s.valid_votes), mun_clean_var=s.share_a.var())), include_groups=False)
    d = d.join(mun_clean, on='mun')
    d['local_inteiro'] = (d.place_beh / d.place_n >= .5) & (d.place_n >= 2)
    with np.errstate(invalid='ignore', divide='ignore'):
        d['diff_local_mun'] = d.place_share_a - d.mun_clean_a
        d['z_local_mun'] = d.diff_local_mun / np.sqrt(d.mun_clean_var / d.place_n)
    return d


def per_election_summary(E):
    rows = []
    for eid, d in E.items():
        b, c = d[d.BEH], d[~d.BEH]
        br, cr = b[b.real], c[c.real]
        bd = b[b.diff_a.notna()]
        rows.append(dict(eid=eid, eleicao=LAB[eid], secoes=len(d), com_comportamento=len(b), tardia=int(d.LATE.sum()), manual=int(d.MANUAL.sum()), tardia_e_manual=int((d.LATE & d.MANUAL).sum()),
                         cmp_local=int((b.cmp_level == 'local').sum()), cmp_local_poucos=int((b.cmp_level == 'local (poucos pares)').sum()), cmp_municipio=int((b.cmp_level == 'município').sum()),
                         sem_comparacao=int(b.diff_a.isna().sum()),
                         dif_real_com_comportamento=len(br), pct_real_com_comportamento=100 * b.real.mean() if len(b) else np.nan,
                         pct_real_secoes_comuns=100 * c.real.mean() if len(c) else np.nan,
                         dif_real_favor_A=int((br.dir == 'A').sum()), dif_real_favor_B=int((br.dir == 'B').sum()),
                         comuns_real_favor_A=int((cr.dir == 'A').sum()), comuns_real_favor_B=int((cr.dir == 'B').sum()),
                         dif_media_pp=np.average(bd.diff_a, weights=bd.valid_votes) if len(bd) else np.nan,
                         dif_media_pp_real=np.average(br.diff_a, weights=br.valid_votes) if len(br) else np.nan,
                         comparecimento_dif_media_pp=np.average(b.diff_turnout.fillna(0), weights=b.eligible) if len(b) else np.nan,
                         vencedor_difere=int((b.winner_ab != b.cmp_winner).sum()), excesso_A_votos_real=float(br.excess_a_votes.sum()),
                         votos_apos_17h=int(b.after_17_recorded.sum()), manuais_apos_17h=int(b.after_17_manual_sequence.sum()),
                         locais_inteiros=int(d[d.local_inteiro].place.nunique())))
    return pd.DataFrame(rows)


def section_history(E):
    hist = None
    for eid in EIDS:
        if eid not in E:
            continue
        d = E[eid]
        h = d[KEY + ['uf', 'BEH', 'LATE', 'MANUAL', 'diff_a', 'z_a', 'real', 'dir', 'big', 'diff_turnout', 'after_17_recorded', 'after_17_manual_sequence', 'winner_ab', 'cmp_winner', 'cmp_level', 'share_a']].copy()
        h['present'] = True
        h.columns = KEY + ['uf'] + [f'{c}_{eid}' for c in ['BEH', 'LATE', 'MANUAL', 'dif', 'z', 'real', 'dir', 'big', 'dif_comp', 'tardios', 'manuais17', 'venc', 'venc_cmp', 'cmp', 'A', 'present']]
        hist = h if hist is None else hist.merge(h, on=KEY + ['uf'], how='outer')
    names = pd.concat([d[KEY + ['uf', 'municipality_name', 'voting_place', 'place_name']] for d in E.values()]).drop_duplicates(KEY + ['uf'], keep='last')
    hist = hist.merge(names, on=KEY + ['uf'], how='left')
    pres = [e for e in PRES if f'BEH_{e}' in hist]
    pref = [e for e in PREF if f'BEH_{e}' in hist]
    B = lambda e: hist[f'BEH_{e}'].fillna(False).astype(bool)  # noqa: E731
    R = lambda e: hist[f'real_{e}'].fillna(False).astype(bool)  # noqa: E731
    hist['n_eleicoes_comportamento'] = sum(B(e).astype(int) for e in pres + pref)
    hist['n_pres_comportamento'] = sum(B(e).astype(int) for e in pres)
    hist['n_pref_comportamento'] = sum(B(e).astype(int) for e in pref)
    hist['n_pres_dif_real'] = sum((B(e) & R(e)).astype(int) for e in pres)
    hist['n_pref_dif_real'] = sum((B(e) & R(e)).astype(int) for e in pref)
    hist['n_dif_real_favor_A'] = sum((B(e) & R(e) & (hist[f'dir_{e}'] == 'A')).astype(int) for e in pres + pref)
    hist['n_dif_real_favor_B'] = sum((B(e) & R(e) & (hist[f'dir_{e}'] == 'B')).astype(int) for e in pres + pref)
    hist['votos_tardios_total'] = sum(hist[f'tardios_{e}'].fillna(0) for e in pres + pref)
    hist['manuais_apos_17h_total'] = sum(hist[f'manuais17_{e}'].fillna(0) for e in pres + pref)
    pres_present = sum(hist[f'present_{e}'].fillna(False).astype(int) for e in pres) > 0
    pref_present = sum(hist[f'present_{e}'].fillna(False).astype(int) for e in pref) > 0
    pb, mb = hist.n_pres_comportamento > 0, hist.n_pref_comportamento > 0
    hist['padrao_comportamento'] = np.select(
        [pb & mb, pb & ~mb & pref_present, pb & ~mb & ~pref_present, ~pb & mb & pres_present, ~pb & mb & ~pres_present],
        ['presidenciais e municipais', 'só presidenciais', 'só presidenciais (sem dado municipal)', 'só municipais', 'só municipais (sem dado presidencial)'], 'nenhum')
    pr, mr = hist.n_pres_dif_real > 0, hist.n_pref_dif_real > 0
    hist['padrao_desvio_resultado'] = np.select(
        [pr & mr, pr & ~mr & pref_present, pr & ~mr & ~pref_present, ~pr & mr], ['desvio real em presidenciais e municipais', 'desvio real só em presidenciais', 'desvio real só em presidenciais (sem dado municipal)', 'desvio real só em municipais'], 'sem desvio real')
    hist['direcao'] = np.select([(hist.n_dif_real_favor_A > 0) & (hist.n_dif_real_favor_B == 0), (hist.n_dif_real_favor_B > 0) & (hist.n_dif_real_favor_A == 0), (hist.n_dif_real_favor_A > 0) & (hist.n_dif_real_favor_B > 0)],
                                ['sempre A', 'sempre B', 'mista'], '')
    hist['dif_media_pres_com_comportamento'] = pd.concat([hist[f'dif_{e}'].where(B(e)) for e in pres], axis=1).mean(axis=1)
    hist = hist[hist.n_eleicoes_comportamento >= 1].copy()
    first = KEY + ['uf', 'municipality_name', 'voting_place', 'place_name', 'n_eleicoes_comportamento', 'n_pres_comportamento', 'n_pref_comportamento', 'n_pres_dif_real', 'n_pref_dif_real',
                   'n_dif_real_favor_A', 'n_dif_real_favor_B', 'direcao', 'padrao_comportamento', 'padrao_desvio_resultado', 'dif_media_pres_com_comportamento', 'votos_tardios_total', 'manuais_apos_17h_total']
    hist = hist[first + [c for c in hist.columns if c not in first and not c.startswith('present_')]]
    return hist


def places_table(E, hist):
    # por eleição, por local
    pe = None
    for eid in EIDS:
        if eid not in E:
            continue
        d = E[eid].copy()
        d['beh_real'] = d.BEH & d.real
        d['beh_real_A'] = d.beh_real & (d.dir == 'A')
        d['beh_real_B'] = d.beh_real & (d.dir == 'B')
        d['beh_tardios'] = d.after_17_recorded.where(d.BEH, 0)
        d['beh_manuais17'] = d.after_17_manual_sequence.where(d.BEH, 0)
        d['beh_excess'] = d.excess_a_votes.where(d.beh_real, 0)
        d['venc_difere'] = d.BEH & (d.winner_ab != d.cmp_winner)
        g = d.groupby(PKEY).agg(secoes=('section', 'size'), comp=('BEH', 'sum'), tardio=('LATE', 'sum'), manual=('MANUAL', 'sum'), real=('beh_real', 'sum'), realA=('beh_real_A', 'sum'), realB=('beh_real_B', 'sum'),
                                tardios=('beh_tardios', 'sum'), manuais17=('beh_manuais17', 'sum'), excessoA=('beh_excess', 'sum'), vencdif=('venc_difere', 'sum'),
                                inteiro=('local_inteiro', 'max'), dif_local_mun=('diff_local_mun', 'first'), z_local_mun=('z_local_mun', 'first'), A_local=('place_share_a', 'first')).reset_index()
        g['inteiro'] = g.inteiro.fillna(False).astype(bool)
        g.columns = PKEY + [f'{c}_{eid}' for c in g.columns[len(PKEY):]]
        pe = g if pe is None else pe.merge(g, on=PKEY, how='outer')
    names = pd.concat([d[PKEY + ['municipality_name', 'place_name']] for d in E.values()]).drop_duplicates(PKEY, keep='last')
    pl = pe.merge(names, on=PKEY, how='left')
    # derivados do histórico por seção
    hp = hist.groupby(PKEY).agg(secoes_com_comportamento=('section', 'size'), recorrentes_2plus=('n_eleicoes_comportamento', lambda x: int((x >= 2).sum())),
                                recorrentes_3plus=('n_eleicoes_comportamento', lambda x: int((x >= 3).sum())), secoes_dif_real_pres=('n_pres_dif_real', lambda x: int((x > 0).sum())),
                                secoes_dif_real_pref=('n_pref_dif_real', lambda x: int((x > 0).sum())), so_presidenciais=('padrao_comportamento', lambda x: int((x == 'só presidenciais').sum())),
                                pres_e_municipais=('padrao_comportamento', lambda x: int((x == 'presidenciais e municipais').sum())), so_municipais=('padrao_comportamento', lambda x: int((x == 'só municipais').sum())),
                                desvio_so_pres=('padrao_desvio_resultado', lambda x: int((x == 'desvio real só em presidenciais').sum())),
                                favor_A=('n_dif_real_favor_A', 'sum'), favor_B=('n_dif_real_favor_B', 'sum'), votos_tardios_total=('votos_tardios_total', 'sum'), manuais_apos_17h_total=('manuais_apos_17h_total', 'sum'),
                                dif_media_pres=('dif_media_pres_com_comportamento', 'mean')).reset_index()
    pl = pl.merge(hp, on=PKEY, how='left')
    for c in hp.columns[len(PKEY):]:
        if c != 'dif_media_pres':
            pl[c] = pl[c].fillna(0).astype(int)
    pl['secoes_max'] = pl[[f'secoes_{e}' for e in EIDS if f'secoes_{e}' in pl]].max(axis=1).astype(int)
    pl['direcao'] = np.select([(pl.favor_A > 0) & (pl.favor_B == 0), (pl.favor_B > 0) & (pl.favor_A == 0), (pl.favor_A > 0) & (pl.favor_B > 0)], ['sempre A', 'sempre B', 'mista'], '')
    # pontuação transparente (0–100)
    comp26 = pl.get('comp_P2026', pd.Series(0, index=pl.index)).fillna(0)
    real26 = pl.get('real_P2026', pd.Series(0, index=pl.index)).fillna(0)
    inteiro26 = pl.get('inteiro_P2026', pd.Series(False, index=pl.index)).fillna(False).astype(bool)
    z_int26 = pl.get('z_local_mun_P2026', pd.Series(np.nan, index=pl.index))
    pts = pd.DataFrame(index=pl.index)
    pts['recorrencia'] = np.minimum(pl.recorrentes_2plus, 5) * 3 + np.minimum(pl.recorrentes_3plus, 3) * 2          # máx 21
    pts['desvio_real_pres'] = np.minimum(pl.secoes_dif_real_pres, 5) * 5                                               # máx 25
    pts['direcao_unica'] = np.where((pl.favor_A + pl.favor_B >= 2) & (pl.direcao != 'mista'), 8, 0)                   # máx 8
    pts['comportamento_2026'] = np.minimum(comp26, 4) * 3 + np.minimum(real26, 3) * 3                                   # máx 21
    pts['local_inteiro'] = np.where(inteiro26 & (z_int26.abs() >= ZMIN), 8, np.where(inteiro26, 4, 0))                 # máx 8
    pts['volume'] = np.select([pl.votos_tardios_total >= 500, pl.votos_tardios_total >= 100], [6, 3], 0) + np.select([pl.manuais_apos_17h_total >= 50, pl.manuais_apos_17h_total >= 20], [6, 3], 0)  # máx 12
    pts['so_presidenciais'] = np.where(pl.desvio_so_pres >= 2, 5, 0)                                                     # máx 5
    pl['pontos'] = pts.sum(axis=1).astype(int)
    for c in pts:
        pl[f'pts_{c}'] = pts[c].astype(int)
    pl['nivel_risco'] = np.select([pl.pontos >= 45, pl.pontos >= 25], ['alta', 'média'], 'baixa')
    # seções a checar: com comportamento em 2026 T1 ou recorrentes
    s26 = hist[(hist.get('BEH_P2026', False) == True) | (hist.n_eleicoes_comportamento >= 2)].copy()  # noqa: E712
    s26['sec'] = s26.section.astype(int).astype(str)
    chk = s26.sort_values('section').groupby(PKEY).sec.agg(lambda x: ', '.join(x)).rename('secoes_a_checar').reset_index()
    pl = pl.merge(chk, on=PKEY, how='left')
    pl['secoes_a_checar'] = pl.secoes_a_checar.fillna('')
    pl = pl[pl.secoes_com_comportamento >= 1].copy()
    order = ['uf', 'municipality', 'municipality_name', 'zone', 'voting_place', 'place_name', 'nivel_risco', 'pontos', 'secoes_max', 'secoes_com_comportamento', 'recorrentes_2plus', 'recorrentes_3plus',
             'secoes_dif_real_pres', 'secoes_dif_real_pref', 'direcao', 'favor_A', 'favor_B', 'so_presidenciais', 'pres_e_municipais', 'so_municipais', 'desvio_so_pres', 'dif_media_pres',
             'votos_tardios_total', 'manuais_apos_17h_total', 'secoes_a_checar']
    rest = [c for c in pl.columns if c not in order]
    pl = pl[order + rest].sort_values(['pontos', 'secoes_dif_real_pres', 'votos_tardios_total'], ascending=False)
    return pl


def aggregate(pl, keys, label):
    g = pl.groupby(keys).agg(locais_com_comportamento=('voting_place', 'size'), locais_risco_alta=('nivel_risco', lambda x: int((x == 'alta').sum())), locais_risco_media=('nivel_risco', lambda x: int((x == 'média').sum())),
                             pontos_max=('pontos', 'max'), pontos_medio=('pontos', 'mean'), secoes_com_comportamento=('secoes_com_comportamento', 'sum'), recorrentes_2plus=('recorrentes_2plus', 'sum'),
                             secoes_dif_real_pres=('secoes_dif_real_pres', 'sum'), favor_A=('favor_A', 'sum'), favor_B=('favor_B', 'sum'), votos_tardios=('votos_tardios_total', 'sum'),
                             manuais_apos_17h=('manuais_apos_17h_total', 'sum')).reset_index()
    if 'comp_P2026' in pl:
        g = g.merge(pl.groupby(keys).comp_P2026.sum().fillna(0).astype(int).rename('secoes_comportamento_2026').reset_index(), on=keys, how='left')
    g['nivel'] = label
    return g.sort_values(['locais_risco_alta', 'pontos_max', 'secoes_dif_real_pres'], ascending=False)


def readme():
    rows = [
        ('O que é', 'Varredura por local de votação: seções com votação tardia e/ou habilitação manual excessiva, comparadas às demais seções do mesmo local, em 2022 (T1/T2), 2024 (prefeito, T1/T2) e 2026 (T1).'),
        ('TARDIO', 'Fração de votos após 17h > P99 do estado (≥20 votos) OU último voto ≥19h OU encerramento >60 min após 17h sem troca de urna.'),
        ('MANUAL', 'Habilitação manual pelo mesário acima do esperado para a seção (biometria cadastrada, idade, escolaridade; resíduo > P99) OU ≥10 habilitações manuais após 17h.'),
        ('Comportamento', 'TARDIO ou MANUAL. Seção elegível: ≥50 aptos e votos válidos > 0.'),
        ('Lado A / lado B', 'Presidente: PT / PL. Prefeito: candidato líder do município / 2º colocado.'),
        ('Comparação (pares)', 'Outras seções do mesmo local SEM comportamento. cmp_level: "local" (≥3 pares), "local (poucos pares)" (1–2; dispersão tomada do município), "município" (sem pares no local).'),
        ('dif', '% do lado A na seção − % nos pares (p.p., ponderado por votos válidos).'),
        ('z', 'dif ÷ raiz(variância dos pares + erro binomial da seção). Mede se a diferença é maior do que a variação normal entre seções do mesmo local.'),
        ('Diferença real', '|dif| ≥ 5 p.p. e |z| ≥ 2. Nas seções comuns, o mesmo teste (cada uma contra as demais) dá a taxa-base esperada por acaso — ver resumo_por_eleicao.'),
        ('dif_comp', 'Comparecimento da seção − comparecimento dos pares (p.p.).'),
        ('Local inteiro', 'Quando ≥50% das seções do local têm comportamento, o local é comparado às seções comuns do município (dif_local_mun, z_local_mun).'),
        ('padrao_comportamento', 'Por seção: em que tipo de eleição o comportamento aparece (só presidenciais / só municipais / ambos). "Só presidenciais" exige que a seção exista nos dados de prefeito.'),
        ('padrao_desvio_resultado', 'Por seção: em que tipo de eleição a diferença real de resultado aparece.'),
        ('direcao', 'Nas diferenças reais da seção/local: sempre A, sempre B ou mista.'),
        ('pontos', 'Soma transparente: recorrência (máx 21), desvio real em presidenciais (25), direção única (8), comportamento em 2026 T1 (21), local inteiro atípico (8), volume de tardios/manuais (12), ≥2 seções com desvio real só nas presidenciais (5). Máximo 100.'),
        ('Aviso sobre "só presidenciais"', 'Votação tardia é estruturalmente muito mais comum nos 1º turnos presidenciais (filas) do que nas municipais; por isso o padrão de comportamento "só presidenciais" domina e, sozinho, não pontua. Só pontua o desvio REAL de resultado restrito às presidenciais.'),
        ('nivel_risco', 'alta ≥45 pontos; média 25–44; baixa <25.'),
        ('secoes_a_checar', 'Seções do local com comportamento em 2026 T1 ou recorrentes (2+ eleições).'),
        ('prioridade_2026_T2', 'Locais com seções presentes em 2026 e comportamento em 2026 T1 ou recorrente, ordenados por pontos. Uso: alocar fiscais, observar fila, habilitação manual e encerramento.'),
        ('Limites', 'Nada aqui observa compra de voto, coação ou intenção; mede desvio operacional e de resultado frente aos vizinhos. Seções do mesmo prédio podem ter eleitorados distintos. Sinalização não é acusação.'),
    ]
    return pd.DataFrame(rows, columns=['campo', 'descricao'])


def pdf(T, pl, prio, zones, cities, hist):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Varredura por local de votação: votos tardios + habilitação manual, diferença real frente às seções vizinhas e cruzamento prefeito × presidente', H1),
          Paragraph('Comportamento TARDIO = votos após 17h acima do P99 do estado (≥20), ou último voto após 19h, ou encerramento >60 min sem troca de urna. MANUAL = habilitação manual pelo mesário acima do '
                    'esperado (P99) ou ≥10 manuais após 17h. Cada seção com comportamento é comparada às outras seções do mesmo local sem comportamento. “Diferença real” = ≥5 p.p. no lado A e |z| ≥ 2 '
                    '(z usa a dispersão entre as seções vizinhas e o erro binomial da seção). O mesmo teste aplicado às seções comuns dá a taxa que se espera por acaso. Lado A = PT (presidente) ou líder do município (prefeito).', P),
          Paragraph('Como usar: a lista prioriza locais para fiscalização presencial (fila, habilitação manual, encerramento) no 2º turno de 2026 e nas eleições seguintes. Sinalização não é acusação; os dados não observam compra de voto.', NOTE),
          Paragraph('1. Visão geral por eleição', H2)]
    t = [['Eleição', 'Seções', 'Com comp.', 'Tardia', 'Manual', 'Ambas', 'Pares no local', 'poucos pares', 'município', 'Dif. real (com comp.)', '% com comp.', '% seções comuns (acaso)', 'favor A', 'favor B',
          'Comuns reais A / B', 'Dif. média p.p.', 'Dif. média (reais) p.p.', 'Comparec. dif. p.p.', 'Venc. difere', 'Excesso A (reais, votos)', 'Após 17h', 'Manuais após 17h', 'Locais inteiros']]
    for r in T.itertuples():
        t.append([r.eleicao, n(r.secoes), n(r.com_comportamento), n(r.tardia), n(r.manual), n(r.tardia_e_manual), n(r.cmp_local), n(r.cmp_local_poucos), n(r.cmp_municipio), n(r.dif_real_com_comportamento),
                  n(r.pct_real_com_comportamento, 1), n(r.pct_real_secoes_comuns, 1), n(r.dif_real_favor_A), n(r.dif_real_favor_B), f'{n(r.comuns_real_favor_A)} / {n(r.comuns_real_favor_B)}',
                  n(r.dif_media_pp, 2), n(r.dif_media_pp_real, 1), n(r.comparecimento_dif_media_pp, 2),
                  n(r.vencedor_difere), n(r.excesso_A_votos_real), n(r.votos_apos_17h), n(r.manuais_apos_17h), n(r.locais_inteiros)])
    st += [M.table(t, font=5.0),
           Paragraph('Leitura: “% com comp.” é a fração das seções com comportamento cuja votação difere de verdade das vizinhas; “% seções comuns” é a mesma fração nas seções sem comportamento. '
                     'Se as duas forem parecidas, a diferença não está ligada ao comportamento; se a primeira for bem maior, as seções com fila/habilitação manual votam diferente do prédio. '
                     '“Comuns reais A / B” mostra para que lado pendem as diferenças reais das seções comuns: é a referência para julgar se o excesso a favor de A ou de B nas seções com comportamento é incomum.', SM),
           Paragraph('2. Padrão por seção: prefeito × presidente', H2)]
    pc = hist.padrao_comportamento.value_counts()
    pdv = hist.padrao_desvio_resultado.value_counts()
    t = [['Padrão de comportamento', 'Seções', '', 'Padrão de desvio real de resultado', 'Seções']]
    a, b = list(pc.items()), list(pdv.items())
    for i in range(max(len(a), len(b))):
        t.append([a[i][0] if i < len(a) else '', n(a[i][1]) if i < len(a) else '', '', b[i][0] if i < len(b) else '', n(b[i][1]) if i < len(b) else ''])
    st += [M.table(t, [7 * cm, 2.5 * cm, .6 * cm, 8.5 * cm, 2.5 * cm], font=7),
           Paragraph('“Só presidenciais” = a seção existe nos dados de prefeito 2024 mas só mostra o comportamento (ou o desvio real) nas presidenciais. Direção entre as seções com diferença real: '
                     f'sempre A {n(int((hist.direcao == "sempre A").sum()))}, sempre B {n(int((hist.direcao == "sempre B").sum()))}, mista {n(int((hist.direcao == "mista").sum()))}.', SM),
           PageBreak(), Paragraph(f'3. Locais de votação por risco: {n(len(pl))} locais com comportamento; alta {n(int((pl.nivel_risco == "alta").sum()))}, média {n(int((pl.nivel_risco == "média").sum()))}', H2)]
    t = [['UF', 'Cidade', 'Zona', 'Local', 'Nome', 'Nível', 'Pontos', 'Seções', 'c/ comp.', 'Rec. 2+', 'Dif. real pres.', 'Direção', 'Só pres.', 'Dif. média p.p.', 'Após 17h', 'Manuais 17h', 'Seções a checar']]
    for r in pl.head(40).itertuples():
        t.append([r.uf, r.municipality_name[:22], str(r.zone), str(r.voting_place), r.place_name[:30], r.nivel_risco, n(r.pontos), n(r.secoes_max), n(r.secoes_com_comportamento), n(r.recorrentes_2plus),
                  n(r.secoes_dif_real_pres), r.direcao, n(r.so_presidenciais), n(r.dif_media_pres, 1), n(r.votos_tardios_total), n(r.manuais_apos_17h_total), r.secoes_a_checar[:28]])
    st += [M.table(t, font=5.2), PageBreak(), Paragraph(f'4. Prioridade para o 2º turno de 2026 (25/10/2026): {n(len(prio))} locais, {n(int((prio.nivel_risco == "alta").sum()))} de risco alto', H2),
           Paragraph('Locais com seções presentes em 2026 e comportamento em 2026 T1 ou recorrente. A coluna “seções a checar” indica onde posicionar o fiscal dentro do prédio.', P)]
    t = [['UF', 'Cidade', 'Zona', 'Local', 'Nome', 'Nível', 'Pontos', 'Comp. 2026', 'Dif. real 2026', 'Rec. 2+', 'Dif. real pres.', 'Direção', 'Após 17h', 'Seções a checar']]
    for r in prio.head(45).itertuples():
        t.append([r.uf, r.municipality_name[:22], str(r.zone), str(r.voting_place), r.place_name[:30], r.nivel_risco, n(r.pontos), n(getattr(r, 'comp_P2026', 0)), n(getattr(r, 'real_P2026', 0)), n(r.recorrentes_2plus),
                  n(r.secoes_dif_real_pres), r.direcao, n(r.votos_tardios_total), r.secoes_a_checar[:34]])
    st += [M.table(t, font=5.2), PageBreak(), Paragraph('5. Zonas e cidades com mais locais de risco', H2)]
    t = [['UF', 'Cidade', 'Zona', 'Locais c/ comp.', 'Risco alto', 'Risco médio', 'Pontos máx.', 'Seções c/ comp.', 'Rec. 2+', 'Dif. real pres.', 'favor A', 'favor B', 'Após 17h', 'Manuais 17h']]
    for r in zones.head(25).itertuples():
        t.append([r.uf, r.municipality_name[:24], str(r.zone), n(r.locais_com_comportamento), n(r.locais_risco_alta), n(r.locais_risco_media), n(r.pontos_max), n(r.secoes_com_comportamento), n(r.recorrentes_2plus),
                  n(r.secoes_dif_real_pres), n(r.favor_A), n(r.favor_B), n(r.votos_tardios), n(r.manuais_apos_17h)])
    st += [M.table(t, font=5.8)]
    t = [['UF', 'Cidade', 'Locais c/ comp.', 'Risco alto', 'Risco médio', 'Pontos máx.', 'Seções c/ comp.', 'Rec. 2+', 'Dif. real pres.', 'favor A', 'favor B', 'Após 17h', 'Manuais 17h']]
    for r in cities.head(25).itertuples():
        t.append([r.uf, r.municipality_name[:28], n(r.locais_com_comportamento), n(r.locais_risco_alta), n(r.locais_risco_media), n(r.pontos_max), n(r.secoes_com_comportamento), n(r.recorrentes_2plus),
                  n(r.secoes_dif_real_pres), n(r.favor_A), n(r.favor_B), n(r.votos_tardios), n(r.manuais_apos_17h)])
    st += [M.table(t, font=5.8), Paragraph('6. Síntese (gerada dos números)', H2)]
    lines = []
    for r in T.itertuples():
        lines.append(f'{r.eleicao}: {n(r.com_comportamento)} seções com comportamento, {n(r.dif_real_com_comportamento)} com diferença real ({n(r.pct_real_com_comportamento, 1)}% contra {n(r.pct_real_secoes_comuns, 1)}% nas seções comuns); '
                     f'{n(r.dif_real_favor_A)} a favor de A e {n(r.dif_real_favor_B)} de B (nas comuns: {n(r.comuns_real_favor_A)} / {n(r.comuns_real_favor_B)}); diferença média {n(r.dif_media_pp, 2)} p.p.; '
                     f'comparecimento {n(r.comparecimento_dif_media_pp, 2)} p.p. frente aos pares.')
    lines.append(f'Locais: {n(len(pl))} com ao menos uma seção com comportamento; {n(int((pl.nivel_risco == "alta").sum()))} de risco alto e {n(int((pl.nivel_risco == "média").sum()))} médio. '
                 f'Prioridade 2026 T2: {n(len(prio))} locais ({n(int((prio.nivel_risco == "alta").sum()))} alto).')
    lines.append(f'Seções com comportamento só nas presidenciais (existindo nos dados de prefeito): {n(int((hist.padrao_comportamento == "só presidenciais").sum()))}; '
                 f'com desvio real só nas presidenciais: {n(int((hist.padrao_desvio_resultado == "desvio real só em presidenciais").sum()))}.')
    for l in lines:  # noqa: E741
        st.append(Paragraph('• ' + l, P))
    st += [Paragraph('Limites', H2)]
    for t_ in ['A diferença frente aos vizinhos também reflete composição do eleitorado; o teste z reduz, mas não elimina, esse fator.',
               'Compra de votos, coação e abuso do mesário não aparecem nos dados; aparecem fila, habilitação manual, horário e resultado.',
               'Locais de seção única são comparados ao município (referência mais fraca); “local inteiro” usa o município como referência.',
               'Prefeito 2024 T2 só existe em municípios com segundo turno; o perfil do eleitorado é de 2022.', 'Nada aqui indica irregularidade nem a descarta.']:
        st.append(Paragraph('• ' + t_, P))

    def foot(c, d_):
        c.setFont('Helvetica', 7)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, 1 * cm, 'Instrumento de fiscalização — sinalização não é acusação')
        c.drawRightString(27.5 * cm, 1 * cm, f'pág. {d_.page}')
    SimpleDocTemplate(str(OUT / 'VARREDURA_LOCAIS_RISCO.pdf'), pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.6 * cm).build(st, onFirstPage=foot, onLaterPages=foot)


def xlsx(path, sheets):
    with pd.ExcelWriter(path, engine='xlsxwriter') as xw:
        for nm, df in sheets:
            df = df.round(3)
            df.to_excel(xw, sheet_name=nm[:31], index=False, freeze_panes=(1, 0))
            ws = xw.sheets[nm[:31]]
            ws.autofilter(0, 0, len(df), max(len(df.columns) - 1, 0))
            if nm == 'leia_me':
                ws.set_column(0, 0, 26)
                ws.set_column(1, 1, 140)


def main():
    E = {}
    for eid in EIDS:
        d = load(eid)
        if d is None:
            print('sem dados', eid, flush=True)
            continue
        E[eid] = compare(d)
        print('eleicao', eid, len(d), 'comp', int(d.BEH.sum()), 'real(comp)', int((d.BEH & d.real).sum()), 'real(comuns)%', round(100 * d[~d.BEH].real.mean(), 2), flush=True)
    T = per_election_summary(E)
    hist = section_history(E)
    pl = places_table(E, hist)
    prio = pl[(pl.get('secoes_P2026', 0).fillna(0) > 0) & ((pl.get('comp_P2026', 0).fillna(0) > 0) | (pl.recorrentes_2plus > 0))].copy()
    prio['prioridade'] = prio.nivel_risco
    zones = aggregate(pl, ['uf', 'municipality', 'municipality_name', 'zone'], 'zona')
    cities = aggregate(pl, ['uf', 'municipality', 'municipality_name'], 'cidade')
    long = pd.concat([d[d.BEH][['eid', 'uf'] + KEY + ['municipality_name', 'voting_place', 'place_name', 'eligible', 'attendance', 'valid_votes', 'LATE', 'MANUAL', 'f_late', 'f_last19', 'f_close', 'f_manual', 'f_manual_late',
                                   'after_17_recorded', 'after_17_manual_sequence', 'manual_sequence_votes', 'manual_resid', 'last_vote', 'close_min', 'swap', 'contingency', 'cand_a', 'share_a', 'cand_b', 'share_b',
                                   'cmp_level', 'cmp_n', 'cmp_a', 'cmp_b', 'diff_a', 'z_a', 'real', 'dir', 'big', 'diff_turnout', 'winner_ab', 'cmp_winner', 'excess_a_votes', 'local_inteiro', 'diff_local_mun', 'z_local_mun']]
                      for d in E.values()], ignore_index=True)
    # exportações
    T.round(3).to_csv(OUT / 'resumo_por_eleicao.csv', **CSV)
    pl.round(3).to_csv(OUT / 'locais_risco.csv', **CSV)
    prio.round(3).to_csv(OUT / 'prioridade_locais_2026_T2.csv', **CSV)
    zones.round(3).to_csv(OUT / 'zonas.csv', **CSV)
    cities.round(3).to_csv(OUT / 'cidades.csv', **CSV)
    hist.round(3).to_csv(OUT / 'secoes_historico.csv', **CSV)
    long.round(3).to_csv(OUT / 'secoes_com_comportamento_por_eleicao.csv', **CSV)
    pad = hist.groupby(['uf', 'padrao_comportamento']).size().unstack(fill_value=0).reset_index()
    pad.to_csv(OUT / 'padroes_pres_x_pref_por_uf.csv', **CSV)
    xlsx(OUT / 'VARREDURA_LOCAIS.xlsx', [('leia_me', readme()), ('prioridade_2026_T2', prio), ('locais', pl), ('zonas', zones), ('cidades', cities), ('resumo_por_eleicao', T), ('padroes_por_uf', pad), ('secoes_historico', hist)])
    for uf in ORDER:
        if uf not in pl.uf.values:
            continue
        xlsx(OUT / f'LOCAIS_{uf}.xlsx', [('leia_me', readme()), ('prioridade_2026_T2', prio[prio.uf == uf]), ('locais', pl[pl.uf == uf]), ('zonas', zones[zones.uf == uf]), ('cidades', cities[cities.uf == uf]),
                                        ('secoes_historico', hist[hist.uf == uf]), ('secoes_por_eleicao', long[long.uf == uf])])
        print('xlsx', uf, flush=True)
    pdf(T, pl, prio, zones, cities, hist)
    print('ok locais', len(pl), 'prioridade', len(prio), 'alta', int((prio.nivel_risco == 'alta').sum()), flush=True)


if __name__ == '__main__':
    main()
