"""Analise aberta (feita depois do teste cego): mudanca do 1o para o 2o turno em 2014, 2018, 2022 e 2026, com nomes.

Partes (python scripts/padroes_aberta.py <parte> ...; sem parte, roda todas):
  alegacoes   encerramento apos 17h, habilitacao sem digital, secoes acima de 90%/100%, Benford e ultimo digito
  detectores  os mesmos detectores do teste cego, por eleicao e por UF (RJ e GO em destaque)
  curvas      ganho de cada candidato pela fatia do 1o turno; crescimento por secao; ganho x comparecimento
  espelho     2014->2018, 2018->2022, 2022->2026: municipios e secoes que parecem invertidos
  vizinhas    2026: secoes com voto depois das 17h (logs) x vizinhas do mesmo predio; 2022: encerramento tardio (BU)
  origem      dentro do mesmo predio: como os votos de outros candidatos, de branco/nulo e de abstencao se dividiram
  transferencias  para onde foi cada grupo do 1o turno (regressao ecologica com restricoes, bootstrap por local)
  montecarlo  previsao de cada UF pelas outras UFs da regiao (Monte Carlo); quantas secoes
              precisariam estar invertidas para mudar o resultado
  idosos      comparecimento por idade (90+, 100+): o recorte publico mais proximo da pergunta sobre titulos de falecidos
Saida: relatorios/verificacoes/padroes_2t/*.csv
Descritivo e estatistico: nada aqui, sozinho, indica ou descarta irregularidade.
"""
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from padroes_2t import HORA_BSB, INCUMBENTE, KEY, NOMES, OUT, WORK  # noqa: E402
import padroes_lib as L  # noqa: E402

ANOS = (2014, 2018, 2022, 2026)
CSV = dict(sep=';', decimal=',', encoding='utf-8-sig', index=False)


def _base(ano):
    return pd.read_parquet(WORK / f'base_{ano}.parquet')


def _pct(a, b):
    return 100 * a / b if b else np.nan


def _grupo(s, **k):
    a, b = int(s.t2_A.sum()), int(s.t2_B.sum())
    return dict(**k, secoes=len(s), comparecimento=int(s.t2_comp.sum()), votos_A=a, votos_B=b, pct_A=_pct(a, a + b), pct_B=_pct(b, a + b), margem_A_menos_B=a - b)


def _rotulos(ano):
    a, b = NOMES[ano]
    inc = INCUMBENTE[ano]
    return dict(ano=ano, A=a, B=b, incumbente={'A': a, 'B': b}.get(inc, 'nenhum'))


# ---------------------------------------------------------------- alegacoes
def alegacoes():
    enc, faixas, comp_uf, man, curva, ext, dig = [], [], [], [], [], [], []
    for ano in ANOS:
        b = _base(ano)
        r = _rotulos(ano)
        v = b.t2_A + b.t2_B
        pa = 100 * b.t2_A / v.where(v > 0)
        for lim in (90, 99):
            ext.append(dict(**r, criterio=f'mais de {lim}%', secoes_A=int((pa > lim).sum()), secoes_B=int((pa < 100 - lim).sum())))
        ext.append(dict(**r, criterio='90% ou mais', secoes_A=int((pa >= 90).sum()), secoes_B=int((pa <= 10).sum())))
        ext.append(dict(**r, criterio='100%', secoes_A=int((pa == 100).sum()), secoes_B=int((pa == 0).sum())))
        if 't2_manual' in b:
            taxa = 100 * b.t2_manual / b.t2_comp.where(b.t2_comp > 0)
            mun = taxa.groupby([b.uf, b.municipality]).transform('median')
            for lado, m in (('A', pa >= 90), ('B', pa <= 10)):
                ext.append(dict(**r, criterio=f'manual: secoes com 90%+ para {lado} menos mediana do municipio (p.p.)',
                                secoes_A=float((taxa - mun)[m].median()) if lado == 'A' else np.nan,
                                secoes_B=float((taxa - mun)[m].median()) if lado == 'B' else np.nan))
        o = L.digitos(L.formato_comum(b))
        dig.append(dict(**r, **o))
        if ano == 2014:
            continue
        # encerramento: o criterio da alegacao (hora local da urna) e a hora de Brasilia
        for nome, t in (('hora local da urna', b.t2_enc_min), ('hora de Brasília', b.t2_enc_bsb)):
            enc.append(_grupo(b[t.isna()], **r, criterio=nome, grupo='sem horário'))
            for g, m in (('até 17h00', t <= 1020), ('depois das 17h00', t > 1020), ('depois das 19h00', t > 1140),
                         ('até 17h00min59s (corte da alegação)', t < 1021), ('depois de 17h00min59s (corte da alegação)', t >= 1021)):
                enc.append(_grupo(b[m], **r, criterio=nome, grupo=g))
        t = b.t2_enc_bsb if HORA_BSB[ano] else b.t2_enc_min
        cortes = [-1e9, 1020, 1030, 1050, 1080, 1140, 1e9]
        rot = ['até 17h00', '17h00–17h10', '17h10–17h30', '17h30–18h00', '18h00–19h00', 'depois das 19h00']
        for g, s in b.groupby(pd.cut(t, cortes, labels=rot), observed=True):
            faixas.append(_grupo(s, **r, faixa=g, relogio='Brasília' if HORA_BSB[ano] else 'local (votação em hora local)'))
        ate = b[b.t2_enc_min <= 1020]
        for uf, s in ate.groupby('uf'):
            comp_uf.append(_grupo(s, **r, uf=uf, fuso_h=float(s.desloc_h.median()), pct_das_secoes_do_grupo=100 * len(s) / len(ate),
                                  pct_das_secoes_da_uf=100 * len(s) / int((b.uf == uf).sum())))
        # habilitacao sem digital
        for tt in ('t1', 't2'):
            a1, b1 = int(b[f'{tt}_A'].sum()), int(b[f'{tt}_B'].sum())
            man.append(dict(**r, turno=tt[1], habilitados_sem_digital=int(b[f'{tt}_manual'].sum()), comparecimento=int(b[f'{tt}_comp'].sum()),
                            pct_do_comparecimento=_pct(b[f'{tt}_manual'].sum(), b[f'{tt}_comp'].sum()),
                            margem_final=abs(a1 - b1) if tt == 't2' else np.nan,
                            manual_sobre_margem_pct=_pct(b[f'{tt}_manual'].sum(), abs(a1 - b1)) if tt == 't2' else np.nan))
        taxa = 100 * b.t2_manual / b.t2_comp.where(b.t2_comp > 0)
        for g, s in b.groupby(pd.cut(taxa, [0, 2, 4, 6, 8, 10, 15, 20, 30, 50, 100.01], right=False), observed=True):
            curva.append(_grupo(s, **r, faixa_manual_pct=str(g), manual_medio_pct=float(taxa[s.index].mean()),
                                regiao_mais_comum=s.regiao.mode().iloc[0]))
    pd.DataFrame(enc).to_csv(OUT / 'alegacao_encerramento.csv', **CSV)
    pd.DataFrame(faixas).to_csv(OUT / 'alegacao_encerramento_faixas.csv', **CSV)
    pd.DataFrame(comp_uf).to_csv(OUT / 'alegacao_encerramento_ate17h_por_uf.csv', **CSV)
    pd.DataFrame(man).to_csv(OUT / 'alegacao_manual_totais.csv', **CSV)
    pd.DataFrame(curva).to_csv(OUT / 'alegacao_manual_curva.csv', **CSV)
    pd.DataFrame(ext).to_csv(OUT / 'alegacao_extremos.csv', **CSV)
    pd.DataFrame(dig).to_csv(OUT / 'alegacao_digitos_benford.csv', **CSV)
    # votos depois das 17h pelos logs (2026, todas as secoes)
    u = pd.read_csv(ROOT / 'relatorios' / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv', sep=';', decimal=',',
                    encoding='utf-8-sig', usecols=['votos_log', 'votos_apos_17h', 'votos_apos_19h'])
    pd.DataFrame([dict(secoes_com_log=len(u), votos_no_log=int(u.votos_log.sum()), votos_apos_17h=int(u.votos_apos_17h.sum()),
                       secoes_com_voto_apos_17h=int((u.votos_apos_17h > 0).sum()), votos_apos_19h=int(u.votos_apos_19h.sum()),
                       secoes_com_voto_apos_19h=int((u.votos_apos_19h > 0).sum()))]).to_csv(OUT / 'alegacao_votos_apos_17h_logs.csv', **CSV)
    print('alegacoes ok', flush=True)


# ---------------------------------------------------------------- detectores por eleicao e por UF
def detectores():
    rows, ufs = [], []
    for ano in ANOS:
        b = _base(ano)
        d = L.formato_comum(b)
        rows.append(dict(**_rotulos(ano), **L.todos(d, seed=ano)))
        rng = np.random.default_rng(ano + 1)
        dd = L.prepara(d)
        e, phi = L.modelo_local(dd)
        tr, out = L._flags(e.t2_X.to_numpy(), e, phi)
        sims = [L._flags(L.simula(e, phi, rng), e, phi) for _ in range(20)]
        e = e.assign(troca=tr, fora=out, troca_sim=np.mean([s[0] for s in sims], axis=0), fora_sim=np.mean([s[1] for s in sims], axis=0),
                     fora_A=e.z > 4, fora_B=e.z < -4)
        if ano == 2026 or ano == 2022:
            e[e.troca | e.fora].merge(b[KEY + ['municipio', 'voting_place']], on=KEY + ['voting_place'], how='left')[
                KEY + ['municipio', 'voting_place', 't1_X', 't1_Y', 't2_X', 't2_Y', 'p_loo', 'z', 'z_troca', 'troca']].rename(
                columns={'t1_X': 't1_A', 't1_Y': 't1_B', 't2_X': 't2_A', 't2_Y': 't2_B', 'p_loo': 'fatia_A_prevista'}).to_csv(
                OUT / f'secoes_fora_do_modelo_{ano}.csv', **CSV)
        w1 = np.sign(dd.t1_X - dd.t1_Y)
        w2 = np.sign(dd.t2_X - dd.t2_Y)
        dd = dd.assign(vira_A=(w1 < 0) & (w2 > 0), vira_B=(w1 > 0) & (w2 < 0))
        tm = b.t2_enc_bsb if HORA_BSB[ano] else b.t2_enc_min if 't2_enc_min' in b else pd.Series(np.nan, index=b.index)
        b = b.assign(tarde=tm > 1050)
        for uf, g in dd.groupby('uf'):
            s = b[b.uf == uf]
            ge = e[e.uf == uf]
            v1, v2 = s.t1_validos.sum(), (s.t2_A + s.t2_B).sum()
            o = 'Caiado' if ano == 2026 else None
            ufs.append(dict(**_rotulos(ano), uf=uf, secoes=len(g), pct_A_1t=_pct(s.t1_A.sum(), v1), pct_B_1t=_pct(s.t1_B.sum(), v1),
                            pct_outros_1t=_pct(v1 - s.t1_A.sum() - s.t1_B.sum(), v1), pct_A_2t=_pct(s.t2_A.sum(), v2),
                            var_A_pp=_pct(s.t2_A.sum(), v2) - _pct(s.t1_A.sum(), v1), var_B_pp=_pct(s.t2_B.sum(), v2) - _pct(s.t1_B.sum(), v1),
                            cresc_votos_A_pct=_pct(s.t2_A.sum() - s.t1_A.sum(), s.t1_A.sum()), cresc_votos_B_pct=_pct(s.t2_B.sum() - s.t1_B.sum(), s.t1_B.sum()),
                            var_comparecimento_pct=_pct(s.t2_comp.sum() - s.t1_comp.sum(), s.t1_comp.sum()),
                            viradas_para_A=int(g.vira_A.sum()), viradas_para_B=int(g.vira_B.sum()),
                            secoes_no_modelo=len(ge), fora4_obs=int(ge.fora.sum()), fora4_sim=float(ge.fora_sim.sum()),
                            fora4_a_favor_A=int(ge.fora_A.sum()), fora4_a_favor_B=int(ge.fora_B.sum()),
                            trocas_obs=int(ge.troca.sum()), trocas_sim=float(ge.troca_sim.sum()),
                            manual_1t_pct=_pct(s.t1_manual.sum(), s.t1_comp.sum()) if 't1_manual' in s else np.nan,
                            manual_2t_pct=_pct(s.t2_manual.sum(), s.t2_comp.sum()) if 't2_manual' in s else np.nan,
                            pct_secoes_encerradas_apos_17h30=100 * s.tarde.mean() if tm.notna().any() else np.nan,
                            pct_caiado_1t=_pct(s.t1_v55.sum(), v1) if o and 't1_v55' in s else np.nan))
        print('detectores', ano, flush=True)
    pd.DataFrame(rows).to_csv(OUT / 'detectores_por_eleicao.csv', **CSV)
    pd.DataFrame(ufs).to_csv(OUT / 'detectores_por_uf.csv', **CSV)


# ---------------------------------------------------------------- curvas
def curvas():
    cur, q, comp = [], [], []
    for ano in ANOS:
        b = _base(ano)
        r = _rotulos(ano)
        ok = (b.t1_validos >= 30) & (b.t2_A + b.t2_B >= 30)
        s = b[ok]
        v2 = s.t2_A + s.t2_B
        p1 = 100 * s.t1_A / s.t1_validos
        dA = 100 * s.t2_A / v2 - p1
        dB = 100 * s.t2_B / v2 - 100 * s.t1_B / s.t1_validos
        for g, i in s.groupby(pd.cut(p1, np.arange(0, 100.01, 5), include_lowest=True), observed=True).groups.items():
            cur.append(dict(**r, faixa_A_1t=str(g), secoes=len(i), var_A_pp_media=float(dA[i].mean()), var_B_pp_media=float(dB[i].mean()),
                            var_A_pp_dp=float(dA[i].std()), cresc_A_pct=_pct(s.t2_A[i].sum() - s.t1_A[i].sum(), s.t1_A[i].sum()),
                            cresc_B_pct=_pct(s.t2_B[i].sum() - s.t1_B[i].sum(), s.t1_B[i].sum()),
                            outros_1t_pct=_pct((s.t1_validos - s.t1_A - s.t1_B)[i].sum(), s.t1_validos[i].sum())))
        for lado in ('A', 'B'):
            m = s[f't1_{lado}'] >= 20
            g = (s[f't2_{lado}'] / s[f't1_{lado}'])[m]
            q.append(dict(**r, candidato=lado, secoes=int(m.sum()), **{f'p{k}': float(g.quantile(k / 100)) for k in (1, 5, 25, 50, 75, 95, 99)},
                          var_pp_p5=float((dA if lado == 'A' else dB).quantile(.05)), var_pp_mediana=float((dA if lado == 'A' else dB).median()),
                          var_pp_p95=float((dA if lado == 'A' else dB).quantile(.95))))
        # ganho de A x variacao do comparecimento (entre secoes e dentro do mesmo local)
        dt = 100 * (s.t2_comp / s.t2_aptos - s.t1_comp / s.t1_aptos)
        loc = s.groupby(['uf', 'municipality', 'zone', 'voting_place']).ngroup()
        for nome, y, x in (('entre secoes', dA, dt), ('mesmo local', dA - dA.groupby(loc).transform('mean'), dt - dt.groupby(loc).transform('mean'))):
            m = x.notna() & y.notna() & np.isfinite(x)
            bb = float(((x - x[m].mean()) * (y - y[m].mean()))[m].sum() / ((x - x[m].mean()) ** 2)[m].sum())
            comp.append(dict(**r, comparacao=nome, inclinacao_pp_por_pp=bb, correlacao=float(np.corrcoef(x[m], y[m])[0, 1]),
                             var_comparecimento_pp_media=float(dt.mean())))
    pd.DataFrame(cur).to_csv(OUT / 'curva_ganho_por_fatia_1t.csv', **CSV)
    pd.DataFrame(q).to_csv(OUT / 'crescimento_por_secao_quantis.csv', **CSV)
    pd.DataFrame(comp).to_csv(OUT / 'ganho_x_comparecimento.csv', **CSV)
    print('curvas ok', flush=True)


# ---------------------------------------------------------------- espelho
def espelho():
    rows, ufs, mun_out = [], [], []
    for a0, a1 in ((2014, 2018), (2018, 2022), (2022, 2026)):
        x0, x1 = _base(a0), _base(a1)
        x0, x1 = x0[x0.uf != 'ZZ'], x1[x1.uf != 'ZZ']
        for nivel in ('municipio', 'secao'):
            k = ['uf', 'municipality'] if nivel == 'municipio' else KEY
            g0 = x0.groupby(k)[['t2_A', 't2_B', 't2_aptos']].sum()
            g1 = x1.groupby(k)[['t2_A', 't2_B', 't2_aptos']].sum()
            m = g0.join(g1, lsuffix='_0', rsuffix='_1', how='inner')
            m = m[(m.t2_A_0 + m.t2_B_0 >= 30) & (m.t2_A_1 + m.t2_B_1 >= 30)]
            if nivel == 'secao':  # mesma secao: eleitorado parecido (ate 25% de diferenca no numero de aptos)
                m = m[(m.t2_aptos_1 / m.t2_aptos_0 - 1).abs() <= .25]
            p0 = m.t2_A_0 / (m.t2_A_0 + m.t2_B_0)
            p1 = m.t2_A_1 / (m.t2_A_1 + m.t2_B_1)
            dn = x1.t2_A.sum() / (x1.t2_A.sum() + x1.t2_B.sum()) - x0.t2_A.sum() / (x0.t2_A.sum() + x0.t2_B.sum())
            r = p1 - (p0 + dn)
            rm = p1 - (1 - p0 - dn)
            vis = (1 - 2 * p0).abs() >= .25
            inv = vis & (rm.abs() < r.abs())
            forte = vis & (r.abs() >= .15) & (rm.abs() <= .05)
            rows.append(dict(de=a0, para=a1, nivel=nivel, unidades=len(m), mudanca_nacional_pp=100 * dn, correlacao=float(np.corrcoef(p0, p1)[0, 1]),
                             residuo_dp_pp=float(100 * r.std()), residuo_p99_pp=float(100 * r.abs().quantile(.99)), unidades_visiveis=int(vis.sum()),
                             mais_perto_do_espelho=int(inv.sum()), espelho_forte=int(forte.sum()),
                             espelho_forte_por_10mil=1e4 * forte.sum() / max(vis.sum(), 1)))
            if nivel == 'secao':
                t = m.assign(r=r, inv=inv, forte=forte, vis=vis).reset_index()
                for uf, s in t.groupby('uf'):
                    ufs.append(dict(de=a0, para=a1, uf=uf, secoes=len(s), residuo_dp_pp=float(100 * s.r.std()), visiveis=int(s.vis.sum()),
                                    espelho_forte=int(s.forte.sum()), espelho_forte_por_10mil=1e4 * s.forte.sum() / max(s.vis.sum(), 1)))
            else:
                mun_out.append(m.assign(de=a0, para=a1, fatia_A_antes=100 * p0, fatia_A_depois=100 * p1, residuo_pp=100 * r,
                                        residuo_espelho_pp=100 * rm, mais_perto_do_espelho=inv).reset_index()[
                    ['de', 'para', 'uf', 'municipality', 'fatia_A_antes', 'fatia_A_depois', 'residuo_pp', 'residuo_espelho_pp', 'mais_perto_do_espelho']])
    pd.DataFrame(rows).to_csv(OUT / 'espelho_resumo.csv', **CSV)
    pd.DataFrame(ufs).to_csv(OUT / 'espelho_secoes_por_uf.csv', **CSV)
    pd.concat(mun_out).to_csv(OUT / 'espelho_municipios.csv', **CSV)
    print('espelho ok', flush=True)


# ---------------------------------------------------------------- vizinhas
def _pares(b, marca, nome, ano):
    """Locais com secoes marcadas e nao marcadas: ganho medio de A nas marcadas menos nas nao marcadas do mesmo local."""
    ok = (b.t1_validos >= 30) & (b.t2_A + b.t2_B >= 30)
    s = b[ok].assign(m=marca[ok])
    s['dA'] = 100 * s.t2_A / (s.t2_A + s.t2_B) - 100 * s.t1_A / s.t1_validos
    loc = ['uf', 'municipality', 'zone', 'voting_place']
    g = s.groupby(loc + ['m']).agg(dA=('dA', 'mean'), n=('dA', 'size')).unstack('m').dropna()
    dif = g[('dA', True)] - g[('dA', False)]
    return dict(**_rotulos(ano), grupo=nome, secoes_marcadas=int(s.m.sum()), locais_com_os_dois_tipos=len(g),
                dif_ganho_A_pp_media=float(dif.mean()), dif_ic95_pp=float(1.96 * dif.std() / np.sqrt(len(g))), dif_mediana_pp=float(dif.median()),
                pct_locais_marcadas_ganham_mais=float(100 * (dif > 0).mean()))


def vizinhas():
    rows = []
    b = _base(2026)
    u = pd.read_csv(ROOT / 'relatorios' / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv', sep=';', decimal=',',
                    encoding='utf-8-sig', usecols=KEY + ['votos_apos_17h', 'votos_apos_19h'])
    for c in KEY[1:]:
        u[c] = u[c].astype(int)
    b = b.merge(u, on=KEY, how='left')
    rows.append(_pares(b, b.votos_apos_17h.fillna(0) >= 1, 'teve voto depois das 17h (log)', 2026))
    rows.append(_pares(b, b.votos_apos_17h.fillna(0) >= 10, 'teve 10+ votos depois das 17h (log)', 2026))
    rows.append(_pares(b, b.t2_enc_bsb > 1140, 'encerrou às 19h ou depois (BU)', 2026))
    rows.append(_pares(b, b.t2_enc_bsb > 1050, 'encerrou depois das 17h30 (BU)', 2026))
    for ano in (2018, 2022):
        c = _base(ano)
        t = c.t2_enc_bsb if HORA_BSB[ano] else c.t2_enc_min
        rows.append(_pares(c, t > 1050, 'encerrou depois das 17h30 (BU)', ano))
        rows.append(_pares(c, t > 1080, 'encerrou depois das 18h00 (BU)', ano))
    pd.DataFrame(rows).to_csv(OUT / 'vizinhas_tarde_x_cedo.csv', **CSV)
    print('vizinhas ok', flush=True)


# ---------------------------------------------------------------- Monte Carlo
def _nomes_grupos(ano, f, b):
    from virada_1t_2t_2026 import nomes_candidatos
    outros = sorted((c for c in b if c.startswith('t1_v') and c[4:].isdigit()), key=lambda c: -b[c].sum())
    nm = nomes_candidatos() if ano == 2026 else {}
    base = {'t1_X': f'{NOMES[ano][0]} (1º turno)', 't1_Y': f'{NOMES[ano][1]} (1º turno)', 't1_menores': 'demais candidatos',
            't1_bn': 'branco e nulo', 't1_abst': 'abstenção no 1º turno'}
    for i, c in enumerate(outros, 1):
        base[f't1_o{i}'] = nm.get(c[4:], f'candidato {c[4:]}')
    return [base[c] for c in f]


def _reamostra(places, rng):
    """Posicoes de uma reamostragem com reposicao dos locais de votacao (bootstrap por local: secoes do mesmo predio andam juntas)."""
    order = np.argsort(places, kind='stable')
    _, start, cnt = np.unique(places[order], return_index=True, return_counts=True)
    pick = rng.integers(0, len(start), len(start))
    s, c = start[pick], cnt[pick]
    return order[np.repeat(s, c) + np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c)]


def origem():
    """Dentro do mesmo predio (sem efeito de geografia): de cada voto a mais vindo de outros candidatos, de branco/nulo que caiu e de
    abstencao que caiu, quanto foi para cada finalista. Regressao das variacoes por secao (em % dos aptos), descontada a media do local."""
    rows, contas = [], []
    for ano in ANOS:
        b = _base(ano)
        bn1, bn2 = b.t1_branco + b.t1_nulo, b.t2_branco + b.t2_nulo
        contas.append(dict(**_rotulos(ano), outros_candidatos_1t=int((b.t1_validos - b.t1_A - b.t1_B).sum()), branco_nulo_1t=int(bn1.sum()),
                           branco_nulo_2t=int(bn2.sum()), comparecimento_1t=int(b.t1_comp.sum()), comparecimento_2t=int(b.t2_comp.sum()),
                           ganho_A=int((b.t2_A - b.t1_A).sum()), ganho_B=int((b.t2_B - b.t1_B).sum())))
        b = b[(b.t1_aptos >= 50) & (b.t2_aptos >= 50)]
        bn1, bn2 = b.t1_branco + b.t1_nulo, b.t2_branco + b.t2_nulo
        ap = b.t2_aptos
        fontes = {'outros candidatos do 1º turno': 100 * (b.t1_validos - b.t1_A - b.t1_B) / ap, 'branco e nulo que deixaram de ser': -100 * (bn2 - bn1) / ap,
                  'abstenção que deixou de ser': -100 * ((b.t2_aptos - b.t2_comp) - (b.t1_aptos - b.t1_comp)) / ap}
        loc = b.groupby(['uf', 'municipality', 'zone', 'voting_place']).ngroup()
        k = loc.map(loc.value_counts()) >= 2

        def dm(x):
            return (x - x.groupby(loc).transform('mean'))[k].to_numpy()
        Xm = np.column_stack([dm(v) for v in fontes.values()])
        ca = np.linalg.lstsq(Xm, dm(100 * (b.t2_A - b.t1_A) / ap), rcond=None)[0]
        cb = np.linalg.lstsq(Xm, dm(100 * (b.t2_B - b.t1_B) / ap), rcond=None)[0]
        for i, nm in enumerate(fontes):
            rows.append(dict(**_rotulos(ano), fonte=nm, para_A=float(ca[i]), para_B=float(cb[i])))
    pd.DataFrame(rows).to_csv(OUT / 'origem_ganho_mesmo_predio.csv', **CSV)
    pd.DataFrame(contas).to_csv(OUT / 'origem_contas_nacionais.csv', **CSV)
    print('origem ok', flush=True)


def _ajusta_fluxos(XtX, XtY):
    """Minimos quadrados com restricoes: cada grupo do 1o turno se divide entre os destinos do 2o turno (cada parte entre 0 e 1,
    soma 1 por grupo). Recebe X'X e X'Y ja somados."""
    from scipy.optimize import minimize
    k, o = XtY.shape
    sc = np.trace(XtX) / k
    A, C = XtX / sc, XtY / sc
    jac_eq = np.kron(np.eye(k), np.ones((1, o)))
    res = minimize(lambda b: float(np.sum(b.reshape(k, o) * (A @ b.reshape(k, o))) - 2 * np.sum(b.reshape(k, o) * C)), np.full(k * o, 1 / o),
                   jac=lambda b: (2 * A @ b.reshape(k, o) - 2 * C).ravel(), bounds=[(0, 1)] * (k * o), method='SLSQP',
                   constraints=[{'type': 'eq', 'fun': lambda b: b.reshape(k, o).sum(1) - 1, 'jac': lambda b: jac_eq}],
                   options={'maxiter': 1000, 'ftol': 1e-12})
    return res.x.reshape(k, o)


def transferencias(R=30):
    """Para onde foi cada grupo do 1o turno: candidato do PT, adversario, branco/nulo ou abstencao no 2o turno (votos, pais inteiro).
    Regressao ecologica com restricoes por regiao, intervalo de 95% por reamostragem dos locais de votacao."""
    rows = []
    for ano in ANOS:
        b = _base(ano)
        d = L.prepara(L.formato_comum(b))
        d['t2_abst'] = (b.t2_aptos - b.t2_comp).clip(lower=0).to_numpy()
        f = L._feats(d)
        dest = ['t2_X', 't2_Y', 't2_bn', 't2_abst']
        nomes = _nomes_grupos(ano, f, b)
        reg = L._reg(d).to_numpy()
        X, Y, places = d[f].to_numpy(float), d[dest].to_numpy(float), d.place.to_numpy()
        G = {rg: X[reg == rg].sum(0) for rg in np.unique(reg)}
        rng = np.random.default_rng(ano)
        res = []
        for r in range(R + 1):
            idx = np.arange(len(d)) if r == 0 else _reamostra(places, rng)
            Xr, Yr, rr = X[idx], Y[idx], reg[idx]
            F = np.zeros((len(f), len(dest)))
            for rg in G:
                m = rr == rg
                F += G[rg][:, None] * _ajusta_fluxos(Xr[m].T @ Xr[m], Xr[m].T @ Yr[m])
            res.append(F)
        F0, Fb = res[0], np.array(res[1:])
        lo, hi = np.quantile(Fb, .025, axis=0), np.quantile(Fb, .975, axis=0)
        for i, nm in enumerate(nomes):
            o = dict(**_rotulos(ano), grupo_1t=nm, votos_no_grupo=float(X[:, i].sum()))
            for j, dn in enumerate(['para_A', 'para_B', 'para_branco_nulo', 'para_abstencao']):
                o[dn], o[f'{dn}_ic_baixo'], o[f'{dn}_ic_alto'] = F0[i, j], lo[i, j], hi[i, j]
            rows.append(o)
        ia = f.index('t1_abst')
        ent = Fb[:, ia, :3].sum(1)
        sai = Fb[:, [i for i in range(len(f)) if i != ia], 3].sum(1)
        rows.append(dict(**_rotulos(ano), grupo_1t='entrantes brutos (abstenção no 1º turno que votou no 2º)', votos_no_grupo=np.nan,
                         para_A=F0[ia, :3].sum(), para_A_ic_baixo=np.quantile(ent, .025), para_A_ic_alto=np.quantile(ent, .975)))
        rows.append(dict(**_rotulos(ano), grupo_1t='saídas brutas (votou no 1º turno e se absteve no 2º)', votos_no_grupo=np.nan,
                         para_A=F0[[i for i in range(len(f)) if i != ia], 3].sum(), para_A_ic_baixo=np.quantile(sai, .025), para_A_ic_alto=np.quantile(sai, .975)))
        print('transferencias', ano, flush=True)
    pd.DataFrame(rows).to_csv(OUT / 'mc_transferencias.csv', **CSV)


def montecarlo(R=30, R_uf=10):
    ufs, nac, inv = [], [], []
    for ano in ANOS:
        b = _base(ano)
        d = L.prepara(L.formato_comum(b))
        rng = np.random.default_rng(ano)
        f = L._feats(d)
        reg = L._reg(d)
        # 2) cada UF prevista pelas outras UFs da regiao (sem ela), com bootstrap: P(A vence) no pais
        sims = []
        for r in range(R_uf):
            pa = pb = 0.0
            per_uf = {}
            for uf in sorted(d.uf.unique()):
                mu = (d.uf == uf).to_numpy()
                rg = reg[mu].iloc[0]
                tr = (reg == rg).to_numpy() & ~mu
                if uf == 'ZZ' or tr.sum() < 1000:  # exterior e UF sozinha na regiao: entra o observado
                    px, py = float(d.t2_X[mu].sum()), float(d.t2_Y[mu].sum())
                else:
                    t = d[tr]
                    if r > 0:
                        t = t.iloc[_reamostra(t.place.to_numpy(), rng)]
                    A = t[f].to_numpy(float)
                    cx = L.nnls(A, t.t2_X.to_numpy(float))[0]
                    cy = L.nnls(A, t.t2_Y.to_numpy(float))[0]
                    G = d.loc[mu, f].to_numpy(float)
                    px, py = float((G @ cx).sum()), float((G @ cy).sum())
                per_uf[uf] = (px, py)
                pa += px
                pb += py
            sims.append(100 * pa / (pa + pb))
            if r == 0:
                for uf, (px, py) in per_uf.items():
                    s = d[d.uf == uf]
                    obs = 100 * s.t2_X.sum() / (s.t2_X.sum() + s.t2_Y.sum())
                    ufs.append(dict(**_rotulos(ano), uf=uf, pct_A_observado=obs, pct_A_previsto_pelas_outras_ufs=100 * px / (px + py),
                                    residuo_pp=obs - 100 * px / (px + py)))
        obs = 100 * d.t2_X.sum() / (d.t2_X.sum() + d.t2_Y.sum())
        nac.append(dict(**_rotulos(ano), pct_A_observado=obs, pct_A_previsto=sims[0], previsto_p2_5=np.quantile(sims, .025),
                        previsto_p97_5=np.quantile(sims, .975), prob_A_vence_pct=100 * np.mean(np.array(sims) > 50), repeticoes=R_uf,
                        pct_A_1t_entre_A_e_B=100 * d.t1_X.sum() / (d.t1_X.sum() + d.t1_Y.sum())))
        # 3) quantas secoes invertidas seriam precisas para mudar o resultado (so secoes que o perdedor venceu)
        a, bb = d.t2_X.sum(), d.t2_Y.sum()
        perdedor = 'Y' if a > bb else 'X'
        ganha = d[f't2_{"X" if perdedor == "Y" else "Y"}']
        perde = d[f't2_{perdedor}']
        dif = (perde - ganha)[perde > ganha].sort_values(ascending=False)
        marg = abs(a - bb)
        n_min = int((2 * dif.cumsum() < marg).sum() + 1)
        n_tip = int(np.ceil(marg / (2 * dif.mean())))
        inv.append(dict(**_rotulos(ano), margem=int(marg), secoes_vencidas_pelo_perdedor=len(dif), invertidas_minimo=n_min,
                        invertidas_tipico=n_tip, diferenca_media_nessas_secoes=float(dif.mean())))
        print('montecarlo', ano, flush=True)
    pd.DataFrame(ufs).to_csv(OUT / 'mc_uf_prevista_pelas_outras.csv', **CSV)
    pd.DataFrame(nac).to_csv(OUT / 'mc_nacional.csv', **CSV)
    pd.DataFrame(inv).to_csv(OUT / 'mc_inversoes_necessarias.csv', **CSV)


# ---------------------------------------------------------------- idosos
IDADES_ALTAS = ['80 a 84 anos', '85 a 89 anos', '90 a 94 anos', '95 a 99 anos', '100 anos ou mais']


def _faixa(s):
    s = s.str.strip()
    return s.where(s.isin(IDADES_ALTAS), 'até 79 anos')


def idosos():
    pasta = ROOT / 'research' / 'eleitorado' / 'perfil_comparecimento'
    partes, zonas = [], []
    for ano in (2018, 2022, 2026):
        z = zipfile.ZipFile(pasta / f'perfil_comparecimento_abstencao_{ano}.zip')
        for nome in sorted(n for n in z.namelist() if n.endswith('.csv') and 'BRASIL' not in n):
            with z.open(nome) as fh:
                cab = fh.readline().decode('latin-1').strip().replace('"', '').split(';')
            uc = ['NR_TURNO', 'SG_UF', 'CD_MUNICIPIO', 'NR_ZONA', 'DS_FAIXA_ETARIA', 'QT_APTOS', 'QT_COMPARECIMENTO']
            if not set(uc) <= set(cab):
                print('colunas diferentes em', nome, cab[:12], flush=True)
                continue
            with z.open(nome) as fh:
                for ch in pd.read_csv(fh, sep=';', encoding='latin-1', usecols=uc, chunksize=1_000_000, dtype={'DS_FAIXA_ETARIA': str}):
                    ch['faixa'] = _faixa(ch.DS_FAIXA_ETARIA)
                    g = ch.groupby(['NR_TURNO', 'SG_UF', 'CD_MUNICIPIO', 'NR_ZONA', 'faixa'])[['QT_APTOS', 'QT_COMPARECIMENTO']].sum()
                    zonas.append(g.assign(ano=ano))
        print('idosos lido', ano, flush=True)
    zz = pd.concat(zonas).groupby(['ano', 'NR_TURNO', 'SG_UF', 'CD_MUNICIPIO', 'NR_ZONA', 'faixa']).sum().reset_index()
    zz.to_parquet(WORK / 'comparecimento_idade_zona.parquet', index=False)
    t = zz.groupby(['ano', 'NR_TURNO', 'faixa'])[['QT_APTOS', 'QT_COMPARECIMENTO']].sum().reset_index()
    t['comparecimento_pct'] = 100 * t.QT_COMPARECIMENTO / t.QT_APTOS
    t.to_csv(OUT / 'idosos_comparecimento_pais.csv', **CSV)
    u = zz[zz.SG_UF.isin(['RJ', 'GO'])].groupby(['ano', 'NR_TURNO', 'SG_UF', 'faixa'])[['QT_APTOS', 'QT_COMPARECIMENTO']].sum().reset_index()
    u['comparecimento_pct'] = 100 * u.QT_COMPARECIMENTO / u.QT_APTOS
    u.to_csv(OUT / 'idosos_comparecimento_rj_go.csv', **CSV)
    # zonas com comparecimento alto de quem tem 90 anos ou mais (no maximo 100%: nao ha como passar do numero de aptos)
    v = zz[zz.faixa.isin(['90 a 94 anos', '95 a 99 anos', '100 anos ou mais'])].groupby(['ano', 'NR_TURNO', 'SG_UF', 'CD_MUNICIPIO', 'NR_ZONA'])[
        ['QT_APTOS', 'QT_COMPARECIMENTO']].sum().reset_index()
    v = v[v.QT_APTOS >= 50]
    v['comparecimento_90mais_pct'] = 100 * v.QT_COMPARECIMENTO / v.QT_APTOS
    v.groupby(['ano', 'NR_TURNO']).comparecimento_90mais_pct.describe(percentiles=[.5, .9, .99]).reset_index().to_csv(
        OUT / 'idosos_zonas_90mais_distribuicao.csv', **CSV)
    v.sort_values('comparecimento_90mais_pct', ascending=False).groupby(['ano', 'NR_TURNO']).head(30).to_csv(OUT / 'idosos_zonas_90mais_maiores.csv', **CSV)
    print('idosos ok', flush=True)


def idosos_cruza():
    """Alta do comparecimento de 80 a 99 anos (1o turno 2022 -> 1o turno 2026) por UF e por zona, contra o voto em Lula em 2026."""
    zz = pd.read_parquet(WORK / 'comparecimento_idade_zona.parquet')
    v = zz[zz.faixa.isin(['80 a 84 anos', '85 a 89 anos', '90 a 94 anos', '95 a 99 anos'])]
    g = v[v.NR_TURNO == 1].groupby(['ano', 'SG_UF'])[['QT_APTOS', 'QT_COMPARECIMENTO']].sum()
    g['pct'] = 100 * g.QT_COMPARECIMENTO / g.QT_APTOS
    u = g.pct.unstack('ano')
    u['variacao_2022_2026_pp'] = u[2026] - u[2022]
    u.reset_index().rename(columns={2018: 'pct_2018_1t', 2022: 'pct_2022_1t', 2026: 'pct_2026_1t'}).to_csv(OUT / 'idosos_80a99_por_uf.csv', **CSV)
    z = v[v.NR_TURNO == 1].groupby(['ano', 'SG_UF', 'NR_ZONA'])[['QT_APTOS', 'QT_COMPARECIMENTO']].sum().reset_index()
    a = z[z.ano == 2022].set_index(['SG_UF', 'NR_ZONA'])
    c = z[z.ano == 2026].set_index(['SG_UF', 'NR_ZONA'])
    d = (100 * c.QT_COMPARECIMENTO / c.QT_APTOS - 100 * a.QT_COMPARECIMENTO / a.QT_APTOS).rename('var_80a99_pp').dropna()
    b = _base(2026).groupby(['uf', 'zone'])[['t1_A', 't1_validos', 't2_A', 't2_B']].sum()
    b['lula_1t'] = 100 * b.t1_A / b.t1_validos
    b['ganho_lula_pp'] = 100 * b.t2_A / (b.t2_A + b.t2_B) - b.lula_1t
    b.index.names = ['SG_UF', 'NR_ZONA']
    m = b.join(d, how='inner')
    q = m.groupby(pd.qcut(m.var_80a99_pp, 5), observed=True).agg(zonas=('lula_1t', 'size'), var_80a99_pp_media=('var_80a99_pp', 'mean'),
                                                                   lula_1t_media=('lula_1t', 'mean'), ganho_lula_pp_medio=('ganho_lula_pp', 'mean')).reset_index()
    q['faixa'] = q.pop('var_80a99_pp').astype(str)
    q['correlacao_com_lula_1t'] = float(m.var_80a99_pp.corr(m.lula_1t))
    q['correlacao_com_ganho_lula'] = float(m.var_80a99_pp.corr(m.ganho_lula_pp))
    q.to_csv(OUT / 'idosos_80a99_zona_x_lula.csv', **CSV)
    print('idosos_cruza ok', flush=True)


PARTES = {'alegacoes': alegacoes, 'detectores': detectores, 'curvas': curvas, 'espelho': espelho, 'vizinhas': vizinhas,
          'origem': origem, 'transferencias': transferencias, 'montecarlo': montecarlo, 'idosos': idosos, 'idosos_cruza': idosos_cruza}

if __name__ == '__main__':
    from baixa_pais import prioridade_baixa
    prioridade_baixa()
    OUT.mkdir(parents=True, exist_ok=True)
    for p in sys.argv[1:] or PARTES:
        PARTES[p]()
