"""Varredura completa por local de votação: votos tardios + habilitação manual (sem biometria), comparados às demais seções
do mesmo local, com teste de diferença acima do limiar, cruzamento prefeito × presidente por seção e lista de locais para fiscalização.

Entrada: relatorios/fiscalizacao/secoes_indicadores_<eid>.parquet (gerados por make_fiscalizacao_study.py).
Saída:   relatorios/fiscalizacao/varredura/ (CSV, XLSX geral e por UF, PDF).

Comportamento por seção e eleição (mesmas definições do histórico):
  TARDIO  = fração de votos após 17h > P99 do estado (≥20 votos) OU último voto ≥19h OU encerramento >60 min sem troca de urna
  MANUAL  = habilitação manual pelo mesário acima do esperado (resíduo > P99) OU ≥10 habilitações manuais após 17h
Comparação: as outras seções do mesmo local de votação SEM comportamento ("pares"). Diferença acima do limiar ("real" nas colunas)
= |diferença| ≥ 5 p.p. e |z| ≥ 2, onde z usa a dispersão dos pares (≥3 pares; senão, a dispersão das seções comuns do município)
e o erro binomial da própria seção. Sem par no local, a comparação é com as seções comuns do município (nível "município").
O mesmo teste aplicado às seções comuns (deixando cada uma de fora) dá a taxa-base esperada por acaso, por nível de comparação.
Lado A = PT (presidente) ou candidato líder do município (prefeito); lado B = PL ou 2º colocado.
Resultado principal = nível "local" (≥3 pares no mesmo prédio); o nível "município" é reportado em separado.
A pontuação ordena locais para observação presencial (prioridade de observação); não é probabilidade de irregularidade.
Sinalização não é acusação: mede desvio de comportamento operacional e de resultado, não compra de voto.

Registro de alterações: 24/10/2026 — após parecer externo: estratificação por nível de comparação; direção e pontos de direção só nas
presidenciais; cruzamento prefeito × presidente pareado; rótulo "prioridade de observação"; pontos operacionais × de resultado;
componente "só presidenciais" renomeado para "≥2 seções com desvio nas presidenciais" (peso mantido; redundante com desvio real pres.).
"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate
from scipy.stats import binomtest

os.environ.setdefault('UF', 'BA')
import make_bahia_reports as M  # noqa: E402  (estilos de PDF e formatação numérica)

SRC = Path('relatorios/fiscalizacao')
OUT = SRC / 'varredura'
OUT.mkdir(parents=True, exist_ok=True)
KEY = ['municipality', 'zone', 'section']
PKEY = ['uf', 'municipality', 'zone', 'voting_place']
ORDER = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC', 'MA']
ELECS = [('P2022', 'Pres 2022 T1', 'pres'), ('P2022b', 'Pres 2022 T2', 'pres'), ('M2024', 'Pref 2024 T1', 'pref'),
         ('M2024b', 'Pref 2024 T2', 'pref'), ('P2026', 'Pres 2026 T1', 'pres')]
EIDS = [e for e, _, _ in ELECS]
PRES = [e for e, _, t in ELECS if t == 'pres']
PREF = [e for e, _, t in ELECS if t == 'pref']
LAB = {e: lab for e, lab, _ in ELECS}
LEVELS = ['local', 'local (poucos pares)', 'município']
MIN_PP = 5.0     # diferença mínima (p.p.) para "acima do limiar"
BIG = 10.0       # "diferença alta"
ZMIN = 2.0       # |z| mínimo
MIN_PEERS = 3    # pares mínimos para usar a dispersão do próprio local
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')


def n(x, d=0):
    return M.n(x, d)


def pct(a, b, d=1):
    return 100 * a / b if b else np.nan


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
    # limite aritmético: mesmo que TODOS os votos após 17h fossem do lado A, o excesso da seção seria explicado?
    d['excesso_alem_tardios'] = d.excess_a_votes > d.after_17_recorded * (1 - d.cmp_a / 100)
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
    d['origem_municipio'] = np.where(d.cmp_level != 'município', '', np.where(d.place_n == 1, 'seção única', 'prédio sem par comum'))
    with np.errstate(invalid='ignore', divide='ignore'):
        d['diff_local_mun'] = d.place_share_a - d.mun_clean_a
        d['z_local_mun'] = d.diff_local_mun / np.sqrt(d.mun_clean_var / d.place_n)
    return d


def _grp(x):
    r = x[x.real]
    return dict(n=len(x), real=int(x.real.sum()), favor_A=int((r.dir == 'A').sum()), favor_B=int((r.dir == 'B').sum()),
                pct_real=pct(x.real.sum(), len(x)), pct_A=pct((r.dir == 'A').sum(), len(r)), dif_media_pp=np.average(x.diff_a[x.diff_a.notna()], weights=x.valid_votes[x.diff_a.notna()]) if x.diff_a.notna().any() else np.nan)


def per_election_summary(E):
    """Uma linha por eleição (totais + recorte 'local') e uma tabela longa por eleição × grupo × nível de comparação."""
    rows, longrows = [], []
    for eid, d in E.items():
        b, c = d[d.BEH], d[~d.BEH]
        br, cr = b[b.real], c[c.real]
        bl, cl = b[b.cmp_level == 'local'], c[c.cmp_level == 'local']
        brl, crl = bl[bl.real], cl[cl.real]
        # razão de chances de Mantel–Haenszel (favor A × grupo), estratos = nível de comparação
        num = den = 0.0
        for lv in LEVELS:
            a_ = int(((br.cmp_level == lv) & (br.dir == 'A')).sum()); b_ = int(((br.cmp_level == lv) & (br.dir == 'B')).sum())
            c_ = int(((cr.cmp_level == lv) & (cr.dir == 'A')).sum()); d_ = int(((cr.cmp_level == lv) & (cr.dir == 'B')).sum())
            tot = a_ + b_ + c_ + d_
            if tot:
                num += a_ * d_ / tot
                den += b_ * c_ / tot
            for grupo, x in (('com comportamento', b[b.cmp_level == lv]), ('comuns', c[c.cmp_level == lv])):
                longrows.append(dict(eid=eid, eleicao=LAB[eid], grupo=grupo, nivel=lv, **_grp(x)))
        bra = br[br.dir == 'A']
        rows.append(dict(eid=eid, eleicao=LAB[eid], secoes=len(d), com_comportamento=len(b), tardia=int(d.LATE.sum()), manual=int(d.MANUAL.sum()), tardia_e_manual=int((d.LATE & d.MANUAL).sum()),
                         cmp_local=int((b.cmp_level == 'local').sum()), cmp_local_poucos=int((b.cmp_level == 'local (poucos pares)').sum()), cmp_municipio=int((b.cmp_level == 'município').sum()),
                         municipio_secao_unica=int((b.origem_municipio == 'seção única').sum()), municipio_predio_sem_par=int((b.origem_municipio == 'prédio sem par comum').sum()),
                         sem_comparacao=int(b.diff_a.isna().sum()),
                         # totais (misturam níveis; manter para continuidade)
                         dif_real_com_comportamento=len(br), pct_real_com_comportamento=pct(len(br), len(b)), pct_real_secoes_comuns=pct(len(cr), len(c)),
                         dif_real_favor_A=int((br.dir == 'A').sum()), dif_real_favor_B=int((br.dir == 'B').sum()),
                         comuns_real_favor_A=int((cr.dir == 'A').sum()), comuns_real_favor_B=int((cr.dir == 'B').sum()),
                         real_municipio=int((br.cmp_level == 'município').sum()), real_local=len(brl), real_local_poucos=int((br.cmp_level == 'local (poucos pares)').sum()),
                         # recorte principal: mesmo prédio, ≥3 pares
                         local_com_comportamento=len(bl), local_dif_real=len(brl), local_pct_real_com_comportamento=pct(len(brl), len(bl)),
                         local_comuns=len(cl), local_comuns_real=len(crl), local_pct_real_secoes_comuns=pct(len(crl), len(cl)),
                         local_favor_A=int((brl.dir == 'A').sum()), local_favor_B=int((brl.dir == 'B').sum()), local_comuns_favor_A=int((crl.dir == 'A').sum()), local_comuns_favor_B=int((crl.dir == 'B').sum()),
                         local_pct_A=pct((brl.dir == 'A').sum(), len(brl)), local_comuns_pct_A=pct((crl.dir == 'A').sum(), len(crl)),
                         or_mantel_haenszel=(num / den) if den else np.nan,
                         dif_media_pp=np.average(b.diff_a[b.diff_a.notna()], weights=b.valid_votes[b.diff_a.notna()]) if b.diff_a.notna().any() else np.nan,
                         dif_media_pp_real=np.average(br.diff_a, weights=br.valid_votes) if len(br) else np.nan,
                         comparecimento_dif_media_pp=np.average(b.diff_turnout.fillna(0), weights=b.eligible) if len(b) else np.nan,
                         vencedor_difere=int((b.winner_ab != b.cmp_winner).sum()), excesso_A_votos_real=float(br.excess_a_votes.sum()),
                         pct_excesso_alem_tardios=pct(bra.excesso_alem_tardios.sum(), len(bra)),
                         votos_apos_17h=int(b.after_17_recorded.sum()), manuais_apos_17h=int(b.after_17_manual_sequence.sum()),
                         locais_inteiros=int(d[d.local_inteiro].place.nunique())))
    return pd.DataFrame(rows), pd.DataFrame(longrows)


def recorrencia(E):
    """Recorrência condicional entre primeiros turnos, nas seções presentes em ambas as eleições."""
    rows = []
    for a, b in (('P2022', 'P2026'), ('M2024', 'P2026'), ('P2022', 'M2024')):
        if a not in E or b not in E:
            continue
        x = E[a][['uf'] + KEY + ['BEH']].merge(E[b][['uf'] + KEY + ['BEH']], on=['uf'] + KEY, suffixes=('_a', '_b'))
        rows.append(dict(de=LAB[a], para=LAB[b], secoes_presentes_em_ambas=len(x), com_comportamento_em=int(x.BEH_a.sum()),
                         pct_repete=pct(x[x.BEH_a].BEH_b.sum(), x.BEH_a.sum()), pct_sem_comportamento_antes=pct(x[~x.BEH_a].BEH_b.sum(), (~x.BEH_a).sum()),
                         razao=(x[x.BEH_a].BEH_b.mean() / x[~x.BEH_a].BEH_b.mean()) if (~x.BEH_a).any() and x[~x.BEH_a].BEH_b.mean() > 0 else np.nan))
    return pd.DataFrame(rows)


def pres_x_pref(E):
    """Comparação pareada entre primeiros turnos (presidente 2022, prefeito 2024, presidente 2026) nas mesmas seções, com denominadores,
    por recorte (todas / nível local), e comparação estrita nas seções com comportamento nos dois cargos (McNemar)."""
    ids = [e for e in ('P2022', 'M2024', 'P2026') if e in E]
    if len(ids) < 2:
        return pd.DataFrame(), pd.DataFrame()
    P = None
    for e in ids:
        x = E[e][['uf'] + KEY + ['BEH', 'real', 'cmp_level', 'dir']].rename(columns={'BEH': f'BEH_{e}', 'real': f'real_{e}', 'cmp_level': f'cmp_{e}', 'dir': f'dir_{e}'})
        P = x if P is None else P.merge(x, on=['uf'] + KEY, how='inner')
    rows = []
    for e in ids:
        for recorte in ('todas', 'local'):
            s = P if recorte == 'todas' else P[P[f'cmp_{e}'] == 'local']
            beh, real = s[f'BEH_{e}'], s[f'real_{e}']
            br = s[beh & real]
            rows.append(dict(eleicao=LAB[e], eid=e, recorte=recorte, presentes=len(s), com_comportamento=int(beh.sum()), pct_com_comportamento=pct(beh.sum(), len(s)),
                             com_comportamento_e_dif=int((beh & real).sum()), pct_dif_entre_comportamento=pct((beh & real).sum(), beh.sum()),
                             comuns=int((~beh).sum()), comuns_dif=int((~beh & real).sum()), pct_dif_entre_comuns=pct((~beh & real).sum(), (~beh).sum()),
                             favor_A=int((br[f'dir_{e}'] == 'A').sum()), favor_B=int((br[f'dir_{e}'] == 'B').sum())))
    pares = []
    if 'M2024' in ids:
        for e in ('P2022', 'P2026'):
            if e not in ids:
                continue
            for recorte in ('todas', 'local'):
                s = P[P[f'BEH_{e}'] & P.BEH_M2024]
                if recorte == 'local':
                    s = s[(s[f'cmp_{e}'] == 'local') & (s.cmp_M2024 == 'local')]
                rp, rm = s[f'real_{e}'], s.real_M2024
                b_, c_ = int((rp & ~rm).sum()), int((~rp & rm).sum())
                pares.append(dict(par=f'{LAB[e]} × {LAB["M2024"]}', recorte=recorte, secoes_com_comportamento_em_ambas=len(s), dif_na_presidencial=int(rp.sum()), dif_na_municipal=int(rm.sum()),
                                  pct_dif_presidencial=pct(rp.sum(), len(s)), pct_dif_municipal=pct(rm.sum(), len(s)), so_presidencial=b_, so_municipal=c_,
                                  p_mcnemar=binomtest(min(b_, c_), b_ + c_, .5).pvalue if b_ + c_ else np.nan))
    return pd.DataFrame(rows), pd.DataFrame(pares)


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
    L = lambda e: hist[f'cmp_{e}'] == 'local'  # noqa: E731
    hist['n_eleicoes_comportamento'] = sum(B(e).astype(int) for e in pres + pref)
    hist['n_pres_comportamento'] = sum(B(e).astype(int) for e in pres)
    hist['n_pref_comportamento'] = sum(B(e).astype(int) for e in pref)
    hist['n_pres_dif_real'] = sum((B(e) & R(e)).astype(int) for e in pres)
    hist['n_pres_dif_real_local'] = sum((B(e) & R(e) & L(e)).astype(int) for e in pres)
    hist['n_pref_dif_real'] = sum((B(e) & R(e)).astype(int) for e in pref)
    # direção: só nas presidenciais (lado A = PT tem significado estável); prefeito reportado à parte
    hist['n_pres_favor_A'] = sum((B(e) & R(e) & (hist[f'dir_{e}'] == 'A')).astype(int) for e in pres)
    hist['n_pres_favor_B'] = sum((B(e) & R(e) & (hist[f'dir_{e}'] == 'B')).astype(int) for e in pres)
    hist['n_pref_favor_lider'] = sum((B(e) & R(e) & (hist[f'dir_{e}'] == 'A')).astype(int) for e in pref)
    hist['n_pref_favor_segundo'] = sum((B(e) & R(e) & (hist[f'dir_{e}'] == 'B')).astype(int) for e in pref)
    hist['n_dif_real_favor_A'] = hist.n_pres_favor_A   # compatibilidade de nome: agora só presidenciais
    hist['n_dif_real_favor_B'] = hist.n_pres_favor_B
    hist['votos_tardios_total'] = sum(hist[f'tardios_{e}'].fillna(0) for e in pres + pref)
    hist['manuais_apos_17h_total'] = sum(hist[f'manuais17_{e}'].fillna(0) for e in pres + pref)
    zero = pd.Series(0, index=hist.index)
    pres_present = (zero + sum(hist[f'present_{e}'].fillna(False).astype(int) for e in pres)) > 0
    pref_present = (zero + sum(hist[f'present_{e}'].fillna(False).astype(int) for e in pref)) > 0
    pb, mb = hist.n_pres_comportamento > 0, hist.n_pref_comportamento > 0
    hist['padrao_comportamento'] = np.select(
        [pb & mb, pb & ~mb & pref_present, pb & ~mb & ~pref_present, ~pb & mb & pres_present, ~pb & mb & ~pres_present],
        ['presidenciais e municipais', 'só presidenciais', 'só presidenciais (sem dado municipal)', 'só municipais', 'só municipais (sem dado presidencial)'], 'nenhum')
    pr, mr = hist.n_pres_dif_real > 0, hist.n_pref_dif_real > 0
    hist['padrao_desvio_resultado'] = np.select(
        [pr & mr, pr & ~mr & pref_present, pr & ~mr & ~pref_present, ~pr & mr & pres_present, ~pr & mr & ~pres_present],
        ['desvio em presidenciais e municipais', 'desvio só em presidenciais', 'desvio só em presidenciais (sem dado municipal)', 'desvio só em municipais', 'desvio só em municipais (sem dado presidencial)'], 'sem desvio acima do limiar')
    hist['direcao'] = np.select([(hist.n_pres_favor_A > 0) & (hist.n_pres_favor_B == 0), (hist.n_pres_favor_B > 0) & (hist.n_pres_favor_A == 0), (hist.n_pres_favor_A > 0) & (hist.n_pres_favor_B > 0)],
                                ['sempre A', 'sempre B', 'mista'], '')
    hist['dif_media_pres_com_comportamento'] = pd.concat([hist[f'dif_{e}'].where(B(e)) for e in pres], axis=1).mean(axis=1)
    hist = hist[hist.n_eleicoes_comportamento >= 1].copy()
    first = KEY + ['uf', 'municipality_name', 'voting_place', 'place_name', 'n_eleicoes_comportamento', 'n_pres_comportamento', 'n_pref_comportamento', 'n_pres_dif_real', 'n_pres_dif_real_local', 'n_pref_dif_real',
                   'n_pres_favor_A', 'n_pres_favor_B', 'n_pref_favor_lider', 'n_pref_favor_segundo', 'direcao', 'padrao_comportamento', 'padrao_desvio_resultado', 'dif_media_pres_com_comportamento',
                   'votos_tardios_total', 'manuais_apos_17h_total']
    hist = hist[first + [c for c in hist.columns if c not in first and not c.startswith('present_')]]
    return hist


def places_table(E, hist):
    pe = None
    for eid in EIDS:
        if eid not in E:
            continue
        d = E[eid].copy()
        d['beh_real'] = d.BEH & d.real
        d['beh_real_local'] = d.beh_real & (d.cmp_level == 'local')
        d['beh_real_A'] = d.beh_real & (d.dir == 'A')
        d['beh_real_B'] = d.beh_real & (d.dir == 'B')
        d['beh_tardios'] = d.after_17_recorded.where(d.BEH, 0)
        d['beh_manuais17'] = d.after_17_manual_sequence.where(d.BEH, 0)
        d['beh_excess'] = d.excess_a_votes.where(d.beh_real, 0)
        d['venc_difere'] = d.BEH & (d.winner_ab != d.cmp_winner)
        g = d.groupby(PKEY).agg(secoes=('section', 'size'), comp=('BEH', 'sum'), tardio=('LATE', 'sum'), manual=('MANUAL', 'sum'), real=('beh_real', 'sum'), real_local=('beh_real_local', 'sum'),
                                realA=('beh_real_A', 'sum'), realB=('beh_real_B', 'sum'), tardios=('beh_tardios', 'sum'), manuais17=('beh_manuais17', 'sum'), excessoA=('beh_excess', 'sum'), vencdif=('venc_difere', 'sum'),
                                inteiro=('local_inteiro', 'max'), dif_local_mun=('diff_local_mun', 'first'), z_local_mun=('z_local_mun', 'first'), A_local=('place_share_a', 'first')).reset_index()
        g['inteiro'] = g.inteiro.fillna(False).astype(bool)
        g.columns = PKEY + [f'{c}_{eid}' for c in g.columns[len(PKEY):]]
        pe = g if pe is None else pe.merge(g, on=PKEY, how='outer')
    names = pd.concat([d[PKEY + ['municipality_name', 'place_name']] for d in E.values()]).drop_duplicates(PKEY, keep='last')
    pl = pe.merge(names, on=PKEY, how='left')
    hp = hist.groupby(PKEY).agg(secoes_com_comportamento=('section', 'size'), recorrentes_2plus=('n_eleicoes_comportamento', lambda x: int((x >= 2).sum())),
                                recorrentes_3plus=('n_eleicoes_comportamento', lambda x: int((x >= 3).sum())), secoes_dif_real_pres=('n_pres_dif_real', lambda x: int((x > 0).sum())),
                                secoes_dif_real_pres_local=('n_pres_dif_real_local', lambda x: int((x > 0).sum())), secoes_dif_real_pref=('n_pref_dif_real', lambda x: int((x > 0).sum())),
                                so_presidenciais=('padrao_comportamento', lambda x: int((x == 'só presidenciais').sum())),
                                pres_e_municipais=('padrao_comportamento', lambda x: int((x == 'presidenciais e municipais').sum())), so_municipais=('padrao_comportamento', lambda x: int((x == 'só municipais').sum())),
                                desvio_so_pres=('padrao_desvio_resultado', lambda x: int((x == 'desvio só em presidenciais').sum())),
                                favor_A=('n_pres_favor_A', 'sum'), favor_B=('n_pres_favor_B', 'sum'), pref_favor_lider=('n_pref_favor_lider', 'sum'), pref_favor_segundo=('n_pref_favor_segundo', 'sum'),
                                votos_tardios_total=('votos_tardios_total', 'sum'), manuais_apos_17h_total=('manuais_apos_17h_total', 'sum'),
                                dif_media_pres=('dif_media_pres_com_comportamento', 'mean')).reset_index()
    pl = pl.merge(hp, on=PKEY, how='left')
    for c in hp.columns[len(PKEY):]:
        if c != 'dif_media_pres':
            pl[c] = pl[c].fillna(0).astype(int)
    pl['secoes_max'] = pl[[f'secoes_{e}' for e in EIDS if f'secoes_{e}' in pl]].max(axis=1).astype(int)
    pl['direcao'] = np.select([(pl.favor_A > 0) & (pl.favor_B == 0), (pl.favor_B > 0) & (pl.favor_A == 0), (pl.favor_A > 0) & (pl.favor_B > 0)], ['sempre A', 'sempre B', 'mista'], '')
    comp26 = pl.get('comp_P2026', pd.Series(0, index=pl.index)).fillna(0)
    real26 = pl.get('real_P2026', pd.Series(0, index=pl.index)).fillna(0)
    inteiro26 = pl.get('inteiro_P2026', pd.Series(False, index=pl.index)).fillna(False).astype(bool)
    z_int26 = pl.get('z_local_mun_P2026', pd.Series(np.nan, index=pl.index))
    # pontuação transparente (0–100); operacional × resultado separados
    pts = pd.DataFrame(index=pl.index)
    pts['recorrencia'] = np.minimum(pl.recorrentes_2plus, 5) * 3 + np.minimum(pl.recorrentes_3plus, 3) * 2          # máx 21 (operacional)
    pts['desvio_real_pres'] = np.minimum(pl.secoes_dif_real_pres, 5) * 5                                               # máx 25 (resultado)
    pts['direcao_unica'] = np.where((pl.favor_A + pl.favor_B >= 2) & (pl.direcao != 'mista'), 8, 0)                   # máx 8  (resultado; só presidenciais)
    pts['comportamento_2026_comp'] = np.minimum(comp26, 4) * 3                                                          # máx 12 (operacional)
    pts['comportamento_2026_real'] = np.minimum(real26, 3) * 3                                                          # máx 9  (resultado)
    pts['local_inteiro'] = np.where(inteiro26 & (z_int26.abs() >= ZMIN), 8, np.where(inteiro26, 4, 0))                 # 8 = resultado (vs município); 4 = operacional
    pts['volume'] = np.select([pl.votos_tardios_total >= 500, pl.votos_tardios_total >= 100], [6, 3], 0) + np.select([pl.manuais_apos_17h_total >= 50, pl.manuais_apos_17h_total >= 20], [6, 3], 0)  # máx 12 (operacional)
    pts['desvio_2plus_pres'] = np.where(pl.desvio_so_pres >= 2, 5, 0)                                                   # máx 5 (resultado; ≥2 seções com desvio só nas presidenciais)
    pl['pontos'] = pts.sum(axis=1).astype(int)
    for c in pts:
        pl[f'pts_{c}'] = pts[c].astype(int)
    pl['pts_comportamento_2026'] = pl.pts_comportamento_2026_comp + pl.pts_comportamento_2026_real
    pl['pts_so_presidenciais'] = pl.pts_desvio_2plus_pres   # nome antigo da coluna, mantido
    pl['pts_operacional'] = pl.pts_recorrencia + pl.pts_volume + pl.pts_comportamento_2026_comp + np.where(pl.pts_local_inteiro == 4, 4, 0)
    pl['pts_resultado'] = pl.pontos - pl.pts_operacional
    secs = (pl.secoes_dif_real_pres + pl.secoes_dif_real_pref) > 0
    loc8 = pl.pts_local_inteiro == 8
    pl['sinal_resultado'] = np.select([secs & loc8, secs, loc8], ['seções + local', 'seções', 'só local (vs município)'], 'nenhum')
    pl['prioridade_observacao'] = np.select([pl.pontos >= 45, pl.pontos >= 25], ['alta', 'média'], 'baixa')
    pl['nivel_risco'] = pl.prioridade_observacao   # alias do nome anterior
    s26 = hist[(hist.get('BEH_P2026', False) == True) | (hist.n_eleicoes_comportamento >= 2)].copy()  # noqa: E712
    s26['sec'] = s26.section.astype(int).astype(str)
    chk = s26.sort_values('section').groupby(PKEY).sec.agg(lambda x: ', '.join(x)).rename('secoes_a_checar').reset_index()
    pl = pl.merge(chk, on=PKEY, how='left')
    pl['secoes_a_checar'] = pl.secoes_a_checar.fillna('')
    pl = pl[pl.secoes_com_comportamento >= 1].copy()
    order = ['uf', 'municipality', 'municipality_name', 'zone', 'voting_place', 'place_name', 'prioridade_observacao', 'pontos', 'pts_operacional', 'pts_resultado', 'sinal_resultado', 'secoes_max', 'secoes_com_comportamento',
             'recorrentes_2plus', 'recorrentes_3plus', 'secoes_dif_real_pres', 'secoes_dif_real_pres_local', 'secoes_dif_real_pref', 'direcao', 'favor_A', 'favor_B', 'pref_favor_lider', 'pref_favor_segundo',
             'so_presidenciais', 'pres_e_municipais', 'so_municipais', 'desvio_so_pres', 'dif_media_pres', 'votos_tardios_total', 'manuais_apos_17h_total', 'secoes_a_checar', 'nivel_risco']
    rest = [c for c in pl.columns if c not in order]
    pl = pl[order + rest].sort_values(['pontos', 'secoes_dif_real_pres', 'votos_tardios_total'], ascending=False)
    return pl


def aggregate(pl, keys, label):
    g = pl.groupby(keys).agg(locais_com_comportamento=('voting_place', 'size'), locais_prioridade_alta=('prioridade_observacao', lambda x: int((x == 'alta').sum())),
                             locais_prioridade_media=('prioridade_observacao', lambda x: int((x == 'média').sum())),
                             pontos_max=('pontos', 'max'), pontos_medio=('pontos', 'mean'), secoes_com_comportamento=('secoes_com_comportamento', 'sum'), recorrentes_2plus=('recorrentes_2plus', 'sum'),
                             secoes_dif_real_pres=('secoes_dif_real_pres', 'sum'), secoes_dif_real_pres_local=('secoes_dif_real_pres_local', 'sum'), favor_A=('favor_A', 'sum'), favor_B=('favor_B', 'sum'),
                             votos_tardios=('votos_tardios_total', 'sum'), manuais_apos_17h=('manuais_apos_17h_total', 'sum')).reset_index()
    if 'comp_P2026' in pl:
        g = g.merge(pl.groupby(keys).comp_P2026.sum().fillna(0).astype(int).rename('secoes_comportamento_2026').reset_index(), on=keys, how='left')
    g['locais_risco_alta'] = g.locais_prioridade_alta     # aliases dos nomes anteriores
    g['locais_risco_media'] = g.locais_prioridade_media
    g['nivel'] = label
    return g.sort_values(['locais_prioridade_alta', 'pontos_max', 'secoes_dif_real_pres'], ascending=False)


def readme():
    rows = [
        ('O que é', 'Varredura por local de votação: seções com votação tardia e/ou habilitação manual excessiva, comparadas às demais seções do mesmo local, em 2022 (T1/T2), 2024 (prefeito, T1/T2) e 2026 (T1). 11 estados.'),
        ('TARDIO', 'Fração de votos após 17h > P99 do estado (≥20 votos) OU último voto ≥19h OU encerramento >60 min após 17h sem troca de urna.'),
        ('MANUAL', 'Habilitação manual pelo mesário acima do esperado para a seção (biometria cadastrada, idade, escolaridade; resíduo > P99) OU ≥10 habilitações manuais após 17h.'),
        ('Comportamento', 'TARDIO ou MANUAL. Seção elegível: ≥50 aptos e votos válidos > 0.'),
        ('Lado A / lado B', 'Presidente: PT / PL. Prefeito: candidato líder do município / 2º colocado. Direção e pontos de direção usam só as presidenciais.'),
        ('Comparação (pares)', 'Outras seções do mesmo local SEM comportamento. cmp_level: "local" (≥3 pares) é o resultado principal; "local (poucos pares)" (1–2; dispersão tomada do município); "município" (sem par comum no local: seção única ou prédio em que todas as demais seções também têm comportamento). A taxa-base de "diferença acima do limiar" é 2 a 6 vezes maior no nível município; ver comparacao_por_nivel.csv.'),
        ('dif', '% do lado A na seção − % nos pares (p.p., ponderado por votos válidos).'),
        ('z', 'dif ÷ raiz(variância dos pares + erro binomial da seção). Mede se a diferença é maior do que a variação normal entre seções do mesmo local.'),
        ('Diferença acima do limiar', '|dif| ≥ 5 p.p. e |z| ≥ 2. Nas colunas chama-se "real" (nome herdado). Nas seções comuns, o mesmo teste (cada uma contra as demais) dá a taxa-base esperada por acaso, por nível.'),
        ('dif_comp', 'Comparecimento da seção − comparecimento dos pares (p.p.).'),
        ('Local inteiro', 'Quando ≥50% das seções do local têm comportamento, o local é comparado às seções comuns do município (dif_local_mun, z_local_mun). Referência mais fraca que o próprio prédio.'),
        ('padrao_comportamento', 'Por seção: em que tipo de eleição o comportamento aparece. "Só presidenciais" exige que a seção exista nos dados de prefeito; "só municipais" exige que exista nos de presidente.'),
        ('padrao_desvio_resultado', 'Por seção: em que tipo de eleição a diferença acima do limiar aparece. A contagem bruta reflete quantas seções têm comportamento em cada tipo de eleição; ver pres_x_pref_pareado.csv para a comparação com denominadores.'),
        ('direcao', 'Nas diferenças acima do limiar das presidenciais: sempre A, sempre B ou mista. Prefeito: pref_favor_lider / pref_favor_segundo, à parte.'),
        ('pontos', 'Soma transparente (máx 100): recorrência (21), desvio acima do limiar nas presidenciais (25), direção única nas presidenciais (8), comportamento em 2026 T1 (12) + diferença em 2026 T1 (9), local inteiro atípico (8), volume de tardios/manuais (12), ≥2 seções com desvio só nas presidenciais (5; redundante com o desvio presidencial, mantido com registro).'),
        ('pts_operacional / pts_resultado', 'Operacional = recorrência + volume + seções com comportamento em 2026 T1 + local inteiro sem desvio (4). Resultado = desvio por seção, direção única, ≥2 desvios só nas presidenciais, diferenças em 2026 T1, local inteiro com |z|≥2 frente ao município (8).'),
        ('sinal_resultado', 'nenhum / só local (vs município) / seções / seções + local: de onde vem o sinal de resultado do local, se houver.'),
        ('prioridade_observacao', 'Prioridade de observação presencial: alta ≥45 pontos; média 25–44; baixa <25. É ordem de prioridade, não probabilidade nem estimativa de irregularidade. Locais sem nenhuma seção com diferença acima do limiar podem ser de prioridade alta por fila/habilitação manual recorrentes, volume e prédio inteiro divergente. nivel_risco = mesmo valor (nome anterior).'),
        ('secoes_a_checar', 'Seções do local com comportamento em 2026 T1 ou recorrentes (2+ eleições).'),
        ('prioridade_2026_T2', 'Locais com seções presentes em 2026 e comportamento em 2026 T1 ou recorrente, ordenados por pontos. Uso: alocar fiscais, observar fila, habilitação manual e encerramento.'),
        ('Limites', 'Nada aqui observa compra de voto, coação ou intenção; mede desvio operacional e de resultado frente aos vizinhos. Não se sabe em quem votaram os eleitores tardios ou habilitados manualmente; compara-se a seção inteira. Seções do mesmo prédio podem ter eleitorados distintos. Sinalização não é acusação.'),
        ('Registro de alterações', '24/10/2026: estratificação por nível de comparação; direção só nas presidenciais; cruzamento prefeito × presidente pareado; rótulo "prioridade de observação"; pontos operacionais × resultado; componente "só presidenciais" renomeado, peso mantido. Maranhão incluído (11 estados).'),
    ]
    return pd.DataFrame(rows, columns=['campo', 'descricao'])


TW_L = 26.7 * cm - 12   # largura útil do texto em A4 paisagem com margens de 1,5 cm


def wtable(rows, widths, font=6.0):
    """Tabela que cabe na largura do texto: larguras relativas escaladas a TW_L, células em Paragraph (quebram por palavra), cabeçalho em negrito branco."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Table, TableStyle
    w = np.array(widths, float)
    w = w / w.sum() * TW_L
    body = ParagraphStyle('wt_body', parent=M.P, fontSize=font, leading=font + 1.8)
    hdr = ParagraphStyle('wt_hdr', parent=body, fontName='Helvetica-Bold', textColor=colors.white)
    esc = lambda s: str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')  # noqa: E731
    data = [[Paragraph(esc(c), hdr) for c in rows[0]]] + [[Paragraph(esc(c), body) for c in r] for r in rows[1:]]
    t = Table(data, colWidths=list(w), repeatRows=1)
    t.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), .25, colors.HexColor('#cccccc')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
                           ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f8fa')]), ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                           ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
    assert t.wrap(TW_L, 1e6)[0] <= TW_L + .5, 'tabela mais larga que o texto'
    return t


def pdf(T, NV, REC, PX, PXP, pl, prio, zones, cities, hist):
    P, H1, H2, SM, NOTE = M.P, M.H1, M.H2, M.SM, M.NOTE
    st = [Paragraph('Varredura por local de votação: votos tardios + habilitação manual, diferença acima do limiar frente às seções vizinhas e cruzamento prefeito × presidente', H1),
          Paragraph('Comportamento TARDIO = votos após 17h acima do P99 do estado (≥20), ou último voto após 19h, ou encerramento >60 min sem troca de urna. MANUAL = habilitação manual pelo mesário acima do '
                    'esperado (P99) ou ≥10 manuais após 17h. Cada seção com comportamento é comparada às outras seções do mesmo local sem comportamento; sem par no local, ao município. “Diferença acima do limiar” = ≥5 p.p. em módulo na fração do lado A e |z| ≥ 2. '
                    'O mesmo teste aplicado às seções comuns dá a taxa esperada por acaso, por nível de comparação. Resultado principal: nível “local” (≥3 pares no mesmo prédio). Lado A = PT (presidente) ou líder do município (prefeito).', P),
          Paragraph('Como usar: a lista prioriza locais para observação presencial (fila, habilitação manual, encerramento) no 2º turno de 2026 e nas eleições seguintes. É ordem de prioridade, não probabilidade de irregularidade. '
                    'Sinalização não é acusação; os dados não observam compra de voto nem em quem votaram os eleitores tardios.', NOTE),
          Paragraph('1. Visão geral por eleição — mesmo prédio (≥3 pares) como resultado principal', H2)]
    t = [['Eleição', 'Seções', 'Com comp.', 'Tardia', 'Manual', 'Comp. c/ pares no local', 'poucos pares', 'sem par (município)', 'Dif. acima do limiar (local)', '% com comp. (local)', '% comuns (local)', 'favor A / B (local)', 'comuns A / B (local)',
          'Dif. (município)', 'OR Mantel–Haenszel', 'Comparec. dif. p.p.', 'Após 17h', 'Manuais após 17h', 'Locais inteiros']]
    for r in T.itertuples():
        t.append([r.eleicao, n(r.secoes), n(r.com_comportamento), n(r.tardia), n(r.manual), n(r.cmp_local), n(r.cmp_local_poucos), n(r.cmp_municipio), n(r.local_dif_real), n(r.local_pct_real_com_comportamento, 1), n(r.local_pct_real_secoes_comuns, 1),
                  f'{n(r.local_favor_A)} / {n(r.local_favor_B)}', f'{n(r.local_comuns_favor_A)} / {n(r.local_comuns_favor_B)}', n(r.real_municipio), n(r.or_mantel_haenszel, 2), n(r.comparecimento_dif_media_pp, 2),
                  n(r.votos_apos_17h), n(r.manuais_apos_17h), n(r.locais_inteiros)])
    st += [wtable(t, [1.8, 1.2, 1.1, 1.1, 1.1, 1.3, 1.1, 1.3, 1.4, 1.2, 1.2, 1.4, 1.4, 1.2, 1.3, 1.3, 1.2, 1.2, 1.1], font=5.6),
           Paragraph('Leitura: “% com comp. (local)” é a fração das seções com comportamento, com ≥3 pares no mesmo prédio, cuja votação ultrapassa o limiar frente às vizinhas; “% comuns (local)” é a mesma fração nas seções sem comportamento. '
                     'A razão de chances de Mantel–Haenszel resume, por estrato de comparação, quanto as diferenças das seções com comportamento pendem mais para A do que as das comuns (1 = igual).', SM),
           Paragraph('1.1 Por nível de comparação (taxa de diferença acima do limiar e direção), por eleição', H2)]
    t = [['Eleição', 'Nível', 'Com comp.: n', 'dif', '% dif', 'favor A', 'favor B', '% A', 'Comuns: n', 'dif', '% dif', 'favor A', 'favor B', '% A']]
    for eid in EIDS:
        for lv in LEVELS:
            b = NV[(NV.eid == eid) & (NV.grupo == 'com comportamento') & (NV.nivel == lv)]
            c = NV[(NV.eid == eid) & (NV.grupo == 'comuns') & (NV.nivel == lv)]
            if b.empty or c.empty:
                continue
            b, c = b.iloc[0], c.iloc[0]
            t.append([LAB[eid], lv, n(b.n), n(b.real), n(b.pct_real, 1), n(b.favor_A), n(b.favor_B), n(b.pct_A, 1), n(c.n), n(c.real), n(c.pct_real, 1), n(c.favor_A), n(c.favor_B), n(c.pct_A, 1)])
    st += [M.table(t, font=5.6),
           Paragraph('No nível “município” (seção única ou prédio em que todas as demais seções têm comportamento) a taxa de diferença acima do limiar é várias vezes maior nos dois grupos, e muitas vezes menor nas seções com comportamento '
                     'do que nas comuns: é uma referência fraca, reportada em separado e não misturada ao resultado principal.', SM),
           PageBreak(), Paragraph('2. Prefeito × presidente, nas mesmas seções (primeiros turnos)', H2),
           Paragraph('Seções presentes nas três eleições de primeiro turno. A contagem bruta de seções com desvio “só nas presidenciais” reflete quantas seções têm comportamento em cada tipo de eleição (fila de 1º turno presidencial); '
                     'a comparação correta usa taxas com denominadores e, de forma estrita, as mesmas seções com comportamento nos dois cargos.', P)]
    if not PX.empty:
        t = [['Eleição', 'Recorte', 'Presentes', 'Com comp.', '% com comp.', 'Com comp. e dif.', '% dif entre com comp.', 'Comuns', 'Comuns c/ dif.', '% dif entre comuns', 'favor A / B']]
        for r in PX.itertuples():
            t.append([r.eleicao, r.recorte, n(r.presentes), n(r.com_comportamento), n(r.pct_com_comportamento, 2), n(r.com_comportamento_e_dif), n(r.pct_dif_entre_comportamento, 2), n(r.comuns), n(r.comuns_dif), n(r.pct_dif_entre_comuns, 2),
                      f'{n(r.favor_A)} / {n(r.favor_B)}'])
        st += [M.table(t, font=6)]
    if not PXP.empty:
        t = [['Par', 'Recorte', 'Seções c/ comp. nos dois cargos', 'Dif. na presidencial', 'Dif. na municipal', '% pres.', '% mun.', 'Só pres.', 'Só mun.', 'p (McNemar)']]
        for r in PXP.itertuples():
            t.append([r.par, r.recorte, n(r.secoes_com_comportamento_em_ambas), n(r.dif_na_presidencial), n(r.dif_na_municipal), n(r.pct_dif_presidencial, 2), n(r.pct_dif_municipal, 2), n(r.so_presidencial), n(r.so_municipal), n(r.p_mcnemar, 3)])
        st += [M.table(t, font=6.2), Paragraph('Comparação estrita: nas mesmas seções com comportamento nos dois cargos, a propensão a ultrapassar o limiar é parecida; p alto = sem evidência de assimetria entre cargos.', SM)]
    if not REC.empty:
        st += [Paragraph('2.1 Recorrência condicional (seções presentes nas duas eleições)', H2)]
        t = [['De', 'Para', 'Seções presentes', 'Com comportamento em “de”', '% que repete', '% entre as sem comportamento antes', 'Razão']]
        for r in REC.itertuples():
            t.append([r.de, r.para, n(r.secoes_presentes_em_ambas), n(r.com_comportamento_em), n(r.pct_repete, 1), n(r.pct_sem_comportamento_antes, 1), n(r.razao, 1)])
        st += [M.table(t, font=6.5), Paragraph('A recorrência é alta e pode ter causas estruturais (prédio grande, eleitorado sem biometria, zona com filas sempre); por isso pesa na pontuação sem indicar irregularidade.', SM)]
    pc = hist.padrao_comportamento.value_counts()
    pdv = hist.padrao_desvio_resultado.value_counts()
    t = [['Padrão de comportamento', 'Seções', '', 'Padrão de desvio acima do limiar', 'Seções']]
    a, b = list(pc.items()), list(pdv.items())
    for i in range(max(len(a), len(b))):
        t.append([a[i][0] if i < len(a) else '', n(a[i][1]) if i < len(a) else '', '', b[i][0] if i < len(b) else '', n(b[i][1]) if i < len(b) else ''])
    st += [Paragraph('2.2 Contagens brutas por seção (para referência; não comparam cargos)', H2), M.table(t, [7 * cm, 2.5 * cm, .6 * cm, 8.5 * cm, 2.5 * cm], font=7),
           PageBreak(), Paragraph(f'3. Locais de votação por prioridade de observação: {n(len(pl))} locais com comportamento; alta {n(int((pl.prioridade_observacao == "alta").sum()))}, média {n(int((pl.prioridade_observacao == "média").sum()))}', H2),
           Paragraph(f'Locais de prioridade alta sem nenhuma seção com diferença acima do limiar: {n(int(((pl.prioridade_observacao == "alta") & (pl.sinal_resultado.isin(["nenhum", "só local (vs município)"]))).sum()))} '
                     f'(entram por fila/habilitação manual recorrentes, volume e prédio inteiro divergente do município). Pontos operacionais e de resultado são mostrados separados.', P)]
    t = [['UF', 'Cidade', 'Zona', 'Local', 'Nome', 'Prior.', 'Pts', 'Oper.', 'Result.', 'Sinal de resultado', 'Seções', 'c/ comp.', 'Rec. 2+', 'Dif. pres.', 'no prédio', 'Direção', 'Após 17h', 'Manuais 17h', 'Seções a checar']]
    for r in pl.head(40).itertuples():
        t.append([r.uf, r.municipality_name[:20], str(r.zone), str(r.voting_place), r.place_name[:26], r.prioridade_observacao, n(r.pontos), n(r.pts_operacional), n(r.pts_resultado), r.sinal_resultado, n(r.secoes_max), n(r.secoes_com_comportamento),
                  n(r.recorrentes_2plus), n(r.secoes_dif_real_pres), n(r.secoes_dif_real_pres_local), r.direcao, n(r.votos_tardios_total), n(r.manuais_apos_17h_total), r.secoes_a_checar[:24]])
    st += [M.table(t, font=5.0), PageBreak(), Paragraph(f'4. Prioridade para o 2º turno de 2026 (25/10/2026): {n(len(prio))} locais, {n(int((prio.prioridade_observacao == "alta").sum()))} de prioridade alta', H2),
           Paragraph('Locais com seções presentes em 2026 e comportamento em 2026 T1 ou recorrente. A coluna “seções a checar” indica onde posicionar o fiscal dentro do prédio.', P)]
    t = [['UF', 'Cidade', 'Zona', 'Local', 'Nome', 'Prior.', 'Pts', 'Oper.', 'Result.', 'Comp. 2026', 'Dif. 2026', 'Rec. 2+', 'Dif. pres. (prédio)', 'Direção', 'Após 17h', 'Seções a checar']]
    for r in prio.head(45).itertuples():
        t.append([r.uf, r.municipality_name[:20], str(r.zone), str(r.voting_place), r.place_name[:26], r.prioridade_observacao, n(r.pontos), n(r.pts_operacional), n(r.pts_resultado), n(getattr(r, 'comp_P2026', 0)), n(getattr(r, 'real_P2026', 0)),
                  n(r.recorrentes_2plus), f'{n(r.secoes_dif_real_pres)} ({n(r.secoes_dif_real_pres_local)})', r.direcao, n(r.votos_tardios_total), r.secoes_a_checar[:30]])
    st += [M.table(t, font=5.0), PageBreak(), Paragraph('5. Zonas e cidades com mais locais de prioridade alta', H2)]
    t = [['UF', 'Cidade', 'Zona', 'Locais c/ comp.', 'Prior. alta', 'Prior. média', 'Pontos máx.', 'Seções c/ comp.', 'Rec. 2+', 'Dif. pres.', 'favor A', 'favor B', 'Após 17h', 'Manuais 17h']]
    for r in zones.head(25).itertuples():
        t.append([r.uf, r.municipality_name[:24], str(r.zone), n(r.locais_com_comportamento), n(r.locais_prioridade_alta), n(r.locais_prioridade_media), n(r.pontos_max), n(r.secoes_com_comportamento), n(r.recorrentes_2plus),
                  n(r.secoes_dif_real_pres), n(r.favor_A), n(r.favor_B), n(r.votos_tardios), n(r.manuais_apos_17h)])
    st += [M.table(t, font=5.8)]
    t = [['UF', 'Cidade', 'Locais c/ comp.', 'Prior. alta', 'Prior. média', 'Pontos máx.', 'Seções c/ comp.', 'Rec. 2+', 'Dif. pres.', 'favor A', 'favor B', 'Após 17h', 'Manuais 17h']]
    for r in cities.head(25).itertuples():
        t.append([r.uf, r.municipality_name[:28], n(r.locais_com_comportamento), n(r.locais_prioridade_alta), n(r.locais_prioridade_media), n(r.pontos_max), n(r.secoes_com_comportamento), n(r.recorrentes_2plus),
                  n(r.secoes_dif_real_pres), n(r.favor_A), n(r.favor_B), n(r.votos_tardios), n(r.manuais_apos_17h)])
    st += [M.table(t, font=5.8), Paragraph('6. Síntese (gerada dos números)', H2)]
    lines = []
    for r in T.itertuples():
        lines.append(f'{r.eleicao}, mesmo prédio (≥3 pares): {n(r.local_com_comportamento)} seções com comportamento, {n(r.local_dif_real)} acima do limiar ({n(r.local_pct_real_com_comportamento, 1)}% contra {n(r.local_pct_real_secoes_comuns, 1)}% nas seções comuns); '
                     f'{n(r.local_favor_A)} a favor de A e {n(r.local_favor_B)} de B ({n(r.local_pct_A, 0)}% A, contra {n(r.local_comuns_pct_A, 0)}% nas comuns); OR de Mantel–Haenszel {n(r.or_mantel_haenszel, 2)}. '
                     f'No total, misturando níveis: {n(r.dif_real_com_comportamento)} acima do limiar, das quais {n(r.real_municipio)} comparadas ao município.')
    lines.append(f'Locais: {n(len(pl))} com ao menos uma seção com comportamento; prioridade alta {n(int((pl.prioridade_observacao == "alta").sum()))} e média {n(int((pl.prioridade_observacao == "média").sum()))}. '
                 f'Prioridade 2026 T2: {n(len(prio))} locais ({n(int((prio.prioridade_observacao == "alta").sum()))} alta).')
    if not PXP.empty:
        r = PXP[(PXP.recorte == 'todas')].iloc[-1]
        lines.append(f'Prefeito × presidente, mesmas seções com comportamento nos dois cargos ({r.par}): {n(r.pct_dif_presidencial, 1)}% contra {n(r.pct_dif_municipal, 1)}% acima do limiar (p McNemar {n(r.p_mcnemar, 2)}): sem evidência de assimetria entre cargos.')
    for s in lines:
        st.append(Paragraph('• ' + s, P))
    st += [Paragraph('Limites', H2)]
    for t_ in ['A diferença frente aos vizinhos também reflete composição do eleitorado; o teste z e a taxa-base reduzem, mas não eliminam, esse fator.',
               'Compra de votos, coação e abuso do mesário não aparecem nos dados; aparecem fila, habilitação manual, horário e resultado. Não se sabe em quem votaram os eleitores tardios ou habilitados manualmente.',
               'Seções sem par comum no prédio (seção única ou prédio inteiro com comportamento) são comparadas ao município, referência fraca com taxa-base alta; estão separadas do resultado principal.',
               'A pontuação é uma regra transparente escolhida pelos autores, não um modelo validado; ordena prioridades de observação. Mudanças de pesos mudam a lista e são registradas.',
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


def git_info():
    """SHA do código produtor: git no PATH, com o caminho padrão do Windows como alternativa; 'n/d' se não houver git."""
    import shutil
    import subprocess
    exe = shutil.which('git') or ('C:/Program Files/Git/cmd/git.exe' if Path('C:/Program Files/Git/cmd/git.exe').exists() else None)
    if not exe:
        return {'codigo_sha': 'n/d', 'codigo_sujo': None}
    try:
        sha = subprocess.run([exe, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
        dirty = bool(subprocess.run([exe, 'status', '--porcelain', '--', 'scripts', 'src'], capture_output=True, text=True, timeout=20, check=True).stdout.strip())
        return {'codigo_sha': sha, 'codigo_sujo': dirty}
    except Exception:
        return {'codigo_sha': 'n/d', 'codigo_sujo': None}


def sha256_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(8 * 1024 ** 2), b''):
            h.update(b)
    return h.hexdigest()


def write_manifest(E):
    """Manifesto da edição: data da geração, código produtor, parâmetros e hashes das entradas. É a fonte da data/tag da edição (não o mtime)."""
    import json
    ufs = sorted({u for d in E.values() for u in d.uf.unique()}, key=lambda u: ORDER.index(u) if u in ORDER else 99)
    man = {'edicao': pd.Timestamp.now().strftime('%Y-%m-%d'), 'gerado_em': pd.Timestamp.now().isoformat(timespec='seconds'), **git_info(), 'script': 'scripts/make_varredura_locais.py',
           'parametros': {'MIN_PP': MIN_PP, 'BIG': BIG, 'ZMIN': ZMIN, 'MIN_PEERS': MIN_PEERS, 'elegibilidade_aptos_min': 50, 'cortes_prioridade': {'alta': 45, 'media': 25}},
           'ufs': ufs, 'eleicoes': list(E.keys()), 'entradas': {f'secoes_indicadores_{eid}.parquet': sha256_file(SRC / f'secoes_indicadores_{eid}.parquet') for eid in E}}
    (OUT / 'edicao.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
    return man


def main():
    E = {}
    for eid in EIDS:
        d = load(eid)
        if d is None:
            print('sem dados', eid, flush=True)
            continue
        E[eid] = compare(d)
        print('eleicao', eid, len(d), 'comp', int(d.BEH.sum()), 'dif(comp)', int((d.BEH & d.real).sum()), 'dif(comuns)%', round(100 * d[~d.BEH].real.mean(), 2), flush=True)
    man = write_manifest(E)
    print('edicao', man['edicao'], 'codigo', man['codigo_sha'][:7], 'sujo' if man['codigo_sujo'] else 'limpo', flush=True)
    T, NV = per_election_summary(E)
    REC = recorrencia(E)
    PX, PXP = pres_x_pref(E)
    hist = section_history(E)
    pl = places_table(E, hist)
    prio = pl[(pl.get('secoes_P2026', 0).fillna(0) > 0) & ((pl.get('comp_P2026', 0).fillna(0) > 0) | (pl.recorrentes_2plus > 0))].copy()
    prio['prioridade'] = prio.prioridade_observacao
    zones = aggregate(pl, ['uf', 'municipality', 'municipality_name', 'zone'], 'zona')
    cities = aggregate(pl, ['uf', 'municipality', 'municipality_name'], 'cidade')
    long = pd.concat([d[d.BEH][['eid', 'uf'] + KEY + ['municipality_name', 'voting_place', 'place_name', 'eligible', 'attendance', 'valid_votes', 'LATE', 'MANUAL', 'f_late', 'f_last19', 'f_close', 'f_manual', 'f_manual_late',
                                   'after_17_recorded', 'after_17_manual_sequence', 'manual_sequence_votes', 'manual_resid', 'last_vote', 'close_min', 'swap', 'contingency', 'cand_a', 'share_a', 'cand_b', 'share_b',
                                   'cmp_level', 'origem_municipio', 'cmp_n', 'cmp_a', 'cmp_b', 'diff_a', 'z_a', 'real', 'dir', 'big', 'excesso_alem_tardios', 'diff_turnout', 'winner_ab', 'cmp_winner', 'excess_a_votes',
                                   'local_inteiro', 'diff_local_mun', 'z_local_mun']] for d in E.values()], ignore_index=True)
    T.round(3).to_csv(OUT / 'resumo_por_eleicao.csv', **CSV)
    NV.round(3).to_csv(OUT / 'comparacao_por_nivel.csv', **CSV)
    REC.round(3).to_csv(OUT / 'recorrencia_condicional.csv', **CSV)
    PX.round(4).to_csv(OUT / 'pres_x_pref_pareado.csv', **CSV)
    PXP.round(4).to_csv(OUT / 'pres_x_pref_mesmas_secoes.csv', **CSV)
    pl.round(3).to_csv(OUT / 'locais_risco.csv', **CSV)
    prio.round(3).to_csv(OUT / 'prioridade_locais_2026_T2.csv', **CSV)
    zones.round(3).to_csv(OUT / 'zonas.csv', **CSV)
    cities.round(3).to_csv(OUT / 'cidades.csv', **CSV)
    hist.round(3).to_csv(OUT / 'secoes_historico.csv', **CSV)
    long.round(3).to_csv(OUT / 'secoes_com_comportamento_por_eleicao.csv', **CSV)
    pad = hist.groupby(['uf', 'padrao_comportamento']).size().unstack(fill_value=0).reset_index()
    pad.to_csv(OUT / 'padroes_pres_x_pref_por_uf.csv', **CSV)
    xlsx(OUT / 'VARREDURA_LOCAIS.xlsx', [('leia_me', readme()), ('prioridade_2026_T2', prio), ('locais', pl), ('zonas', zones), ('cidades', cities), ('resumo_por_eleicao', T), ('comparacao_por_nivel', NV),
                                        ('pres_x_pref_pareado', PX), ('pres_x_pref_mesmas_secoes', PXP), ('recorrencia_condicional', REC), ('padroes_por_uf', pad), ('secoes_historico', hist)])
    for uf in ORDER:
        if uf not in pl.uf.values:
            continue
        xlsx(OUT / f'LOCAIS_{uf}.xlsx', [('leia_me', readme()), ('prioridade_2026_T2', prio[prio.uf == uf]), ('locais', pl[pl.uf == uf]), ('zonas', zones[zones.uf == uf]), ('cidades', cities[cities.uf == uf]),
                                        ('secoes_historico', hist[hist.uf == uf]), ('secoes_por_eleicao', long[long.uf == uf])])
        print('xlsx', uf, flush=True)
    pdf(T, NV, REC, PX, PXP, pl, prio, zones, cities, hist)
    print('ok locais', len(pl), 'prioridade', len(prio), 'alta', int((prio.prioridade_observacao == 'alta').sum()), flush=True)


if __name__ == '__main__':
    main()
