"""Detectores de padrao na mudanca do 1o para o 2o turno (usados por scripts/padroes_2t.py na analise aberta e no teste cego).

Cada funcao recebe uma base no formato comum: uma linha por secao com os dois finalistas como X e Y (rotulos neutros; no teste
cego nao se sabe quem e quem nem de que eleicao e a base): t1_X, t1_Y, t2_X, t2_Y, t1_o1.. (outros candidatos do 1o turno),
t1_menores, t1_bn (branco+nulo), t1_abst, t1_comp, t2_comp, e, quando houver, t1_manual e t2_manual.

Modelo de referencia ("modelo do local"): a secao repete o proprio 1o turno (fatia de X entre X e Y) mais a mudanca que as OUTRAS
secoes do mesmo local de votacao tiveram, em escala logit. Os detectores medem o que sai desse modelo: secoes muito fora,
secoes que ficam no lugar se X e Y forem trocados, secoes parecidas demais entre si, digitos e proporcoes que se repetem demais.
A referencia do "normal" vem de simulacao (Monte Carlo, beta-binomial com a dispersao estimada da propria base) e das outras eleicoes.
"""
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import nnls
from scipy.special import expit, logit

LOC = ['uf', 'municipality', 'zone', 'voting_place']
MIN_N = 30   # secoes com menos de 30 votos em X+Y num dos turnos ficam fora dos detectores por secao
EPS = .005
BENFORD2 = np.array([sum(np.log10(1 + 1 / (10 * a + k)) for a in range(1, 10)) for k in range(10)])
BENFORD1 = np.log10(1 + 1 / np.arange(1, 10))


def formato_comum(b, troca_rotulos=False):
    """base_<ano>.parquet -> formato comum. A (PT) vira X e B vira Y; com troca_rotulos=True, o contrario."""
    a, y = ('B', 'A') if troca_rotulos else ('A', 'B')
    d = pd.DataFrame({c: b[c] for c in ('uf', 'regiao', 'municipality', 'zone', 'voting_place', 'section')})
    for t in ('t1', 't2'):
        d[f'{t}_X'] = b[f'{t}_{a}'].astype(int)
        d[f'{t}_Y'] = b[f'{t}_{y}'].astype(int)
        d[f'{t}_comp'] = b[f'{t}_comp']
        d[f'{t}_aptos'] = b[f'{t}_aptos']
        d[f'{t}_bn'] = b[f'{t}_branco'] + b[f'{t}_nulo']
        d[f'{t}_manual'] = b[f'{t}_manual'] if f'{t}_manual' in b else np.nan
    d['t1_abst'] = (b.t1_aptos - b.t1_comp).clip(lower=0)
    outros = sorted((c for c in b if c.startswith('t1_v') and c[4:].isdigit()), key=lambda c: -b[c].sum())
    for i, c in enumerate(outros, 1):
        d[f't1_o{i}'] = b[c]
    d['t1_menores'] = b.t1_menores
    return d


def prepara(d):
    d = d.copy()
    d['n1'] = d.t1_X + d.t1_Y
    d['n2'] = d.t2_X + d.t2_Y
    d['place'] = d.groupby(LOC, sort=False).ngroup()
    return d


def _lg(a, b):
    return logit(np.clip((a + .5) / (b + 1), EPS, 1 - EPS))


def modelo_local(d):
    """Previsao de cada secao (p_loo) pelo proprio 1o turno + mudanca das outras secoes do local; z = desvio padronizado."""
    e = d[(d.n1 >= MIN_N) & (d.n2 >= MIN_N)].copy()
    e['k'] = e.groupby('place').n2.transform('size')
    e = e[e.k >= 3].copy()
    g = e.groupby('place')
    S1X, S1N, S2X, S2N = (g[c].transform('sum') for c in ('t1_X', 'n1', 't2_X', 'n2'))
    base = _lg(e.t1_X, e.n1)
    e['p_loo'] = np.clip(expit(base + _lg(S2X - e.t2_X, S2N - e.n2) - _lg(S1X - e.t1_X, S1N - e.n1)), EPS, 1 - EPS)
    e['p_full'] = np.clip(expit(base + _lg(S2X, S2N) - _lg(S1X, S1N)), EPS, 1 - EPS)
    e['sd'] = np.sqrt(e.n2 * e.p_loo * (1 - e.p_loo))
    z = (e.t2_X - e.n2 * e.p_loo) / e.sd
    phi = max(float((1.4826 * np.median(np.abs(z - np.median(z)))) ** 2), 1.0)
    e['z'] = z / np.sqrt(phi)
    e['z_troca'] = (e.t2_Y - e.n2 * e.p_loo) / (e.sd * np.sqrt(phi))
    return e, phi


def simula(e, phi, rng):
    """Votos de X no 2o turno sorteados do modelo do local (beta-binomial com a dispersao phi da propria base)."""
    n = e.n2.to_numpy()
    p = e.p_loo.to_numpy()
    rho = np.clip((phi - 1) / np.maximum(n - 1, 1), 1e-9, .99)
    q = rng.beta(p * (1 / rho - 1), (1 - p) * (1 / rho - 1))
    return rng.binomial(n, q)


def _flags(x, e, phi):
    n, p, sd = e.n2.to_numpy(), e.p_loo.to_numpy(), e.sd.to_numpy() * np.sqrt(phi)
    z = (x - n * p) / sd
    zt = ((n - x) - n * p) / sd
    troca = (np.abs(z) > 4) & (np.abs(zt) < 2) & (np.abs(1 - 2 * p) >= .25)
    return troca, np.abs(z) > 4


def trocas(e, phi, rng, R=20):
    """Secoes que ficam fora do modelo, mas voltam para dentro se X e Y forem trocados; contagem observada x simulada."""
    tr, out = _flags(e.t2_X.to_numpy(), e, phi)
    sim_tr, sim_out = [], []
    for _ in range(R):
        a, b = _flags(simula(e, phi, rng), e, phi)
        sim_tr.append(a.sum())
        sim_out.append(b.sum())
    elig = int((np.abs(1 - 2 * e.p_loo) >= .25).sum())
    return dict(secoes_no_modelo=len(e), phi=phi, elegiveis_troca=elig, trocas_obs=int(tr.sum()), trocas_sim=float(np.mean(sim_tr)),
                trocas_por_10mil=1e4 * tr.sum() / max(elig, 1), fora4_obs=int(out.sum()), fora4_sim=float(np.mean(sim_out)),
                fora4_por_10mil=1e4 * out.sum() / len(e),
                fora4_saldo_X=int(((e.z > 4)).sum() - (e.z < -4).sum())), tr


def dispersao(e):
    """Por local: secoes parecidas demais (uniforme demais) ou diferentes demais entre si, contra o piso binomial."""
    g = e.groupby('place')
    df = g.size() - 1
    r = ((e.t2_X - e.n2 * e.p_full) ** 2 / (e.n2 * e.p_full * (1 - e.p_full))).groupby(e.place).sum()
    P = (g.t2_X.transform('sum') / g.n2.transform('sum')).clip(EPS, 1 - EPS)
    h = ((e.t2_X - e.n2 * P) ** 2 / (e.n2 * P * (1 - P))).groupby(e.place).sum()
    o = {'locais': int(len(df))}
    for nome, x in (('ganho', r), ('fatia', h)):
        o[f'{nome}_razao_mediana'] = float(np.median(x / df))
        o[f'{nome}_pct_uniforme_demais'] = 100 * float((stats.chi2.cdf(x, df) < .01).mean())
        o[f'{nome}_pct_disperso_demais'] = 100 * float((stats.chi2.sf(x, df) < .01).mean())
    return o


def digitos(d):
    """Ultimo digito (contagens >= 100: deve ser uniforme), 1o e 2o digito de Benford, para X e Y no 2o turno."""
    o = {}
    for c in ('t2_X', 't2_Y'):
        k = c[3:]
        v = d[c].to_numpy().astype(int)
        u = np.bincount(v[v >= 100] % 10, minlength=10)
        o[f'ultimo_dig_{k}_p'] = float(stats.chisquare(u).pvalue)
        o[f'ultimo_dig_{k}_desvio_max_pp'] = float(100 * np.abs(u / u.sum() - .1).max())
        s = pd.Series(v[v >= 10]).astype(str)
        f2 = np.bincount(s.str[1].astype(int), minlength=10)
        o[f'benford2_{k}_p'] = float(stats.chisquare(f2, BENFORD2 * f2.sum()).pvalue)
        o[f'benford2_{k}_mad'] = float(np.abs(f2 / f2.sum() - BENFORD2).mean())
        f1 = np.bincount(pd.Series(v[v >= 1]).astype(str).str[0].astype(int), minlength=10)[1:]
        o[f'benford1_{k}_mad'] = float(np.abs(f1 / f1.sum() - BENFORD1).mean())
    return o


def _picos(obs, sim):
    """z dos picos: quanto cada faixa sobe acima das vizinhas no observado, descontado o mesmo no simulado."""
    sm_o = pd.Series(obs).rolling(21, center=True, min_periods=5).median().to_numpy()
    sm_s = pd.Series(sim).rolling(21, center=True, min_periods=5).median().to_numpy()
    ex = obs - sm_o * np.where(sm_s > 0, sim / np.where(sm_s > 0, sm_s, 1), 1)
    return ex / np.sqrt(np.maximum(sm_o, 1))


def amontoamento(e, phi, rng, R=10):
    """Proporcoes que se repetem demais: razao votos 2o/1o turno de X e fatia de X no 2o turno, contra a simulacao."""
    ok = (e.t1_X >= 20).to_numpy()
    b1 = np.arange(.5, 4.0001, .005)
    b2 = np.arange(0, 1.0001, .002)
    x1, n2 = e.t1_X.to_numpy()[ok], e.n2.to_numpy()
    o1 = np.histogram(e.t2_X.to_numpy()[ok] / x1, b1)[0]
    o2 = np.histogram(e.t2_X / e.n2, b2)[0]
    s1, s2 = np.zeros(len(b1) - 1), np.zeros(len(b2) - 1)
    for _ in range(R):
        x = simula(e, phi, rng)
        s1 += np.histogram(x[ok] / x1, b1)[0] / R
        s2 += np.histogram(x / n2, b2)[0] / R
    z1, z2 = _picos(o1, s1), _picos(o2, s2)
    return dict(razao_max_z=float(np.nanmax(z1)), razao_picos_z6=int(np.nansum(z1 > 6)), razao_pico_em=float(b1[np.nanargmax(z1)]),
                fatia_max_z=float(np.nanmax(z2)), fatia_picos_z6=int(np.nansum(z2 > 6)), fatia_pico_em=float(b2[np.nanargmax(z2)]))


def manual(d):
    """Habilitacao sem digital x voto. Nivel (2o turno) e mudanca (1o -> 2o turno), entre secoes e dentro do mesmo local."""
    if d.t2_manual.isna().all() or d.t1_manual.isna().all():
        return {}
    e = d[(d.n1 >= MIN_N) & (d.n2 >= MIN_N) & (d.t1_comp > 0) & (d.t2_comp > 0)].dropna(subset=['t1_manual', 't2_manual'])
    s2 = 100 * e.t2_X / e.n2
    ds = s2 - 100 * e.t1_X / e.n1
    m2 = 100 * e.t2_manual / e.t2_comp
    dm = m2 - 100 * e.t1_manual / e.t1_comp
    k = e.groupby('place').place.transform('size') >= 2

    def incl(y, x, fe):
        if fe:
            y = (y - y.groupby(e.place).transform('mean'))[k]
            x = (x - x.groupby(e.place).transform('mean'))[k]
        else:
            y, x = y - y.mean(), x - x.mean()
        b = float((x * y).sum() / (x ** 2).sum())
        se = float(np.sqrt(((y - b * x) ** 2).sum() / (len(x) - 2) / (x ** 2).sum()))
        return b, b / se
    o = {'manual_t1_pct': float(100 * e.t1_manual.sum() / e.t1_comp.sum()), 'manual_t2_pct': float(100 * e.t2_manual.sum() / e.t2_comp.sum())}
    for nome, (y, x, fe) in {'nivel_entre_secoes': (s2, m2, False), 'nivel_mesmo_local': (s2, m2, True),
                             'mudanca_entre_secoes': (ds, dm, False), 'mudanca_mesmo_local': (ds, dm, True)}.items():
        o[f'manual_{nome}_incl'], o[f'manual_{nome}_t'] = incl(y, x, fe)
    return o


def viradas(e, phi, rng, R=20):
    """Secoes que trocam de vencedor (X x Y) do 1o para o 2o turno: observado x esperado pelo modelo do local."""
    w1 = np.sign(e.t1_X - e.t1_Y).to_numpy()
    n = e.n2.to_numpy()

    def conta(x):
        w2 = np.sign(2 * x - n)
        return ((w1 < 0) & (w2 > 0)).sum(), ((w1 > 0) & (w2 < 0)).sum()
    ox, oy = conta(e.t2_X.to_numpy())
    sx, sy = np.mean([conta(simula(e, phi, rng)) for _ in range(R)], axis=0)
    return dict(viradas_para_X_obs=int(ox), viradas_para_X_sim=float(sx), viradas_para_Y_obs=int(oy), viradas_para_Y_sim=float(sy),
                viradas_razao_obs_sim=float((ox + oy) / max(sx + sy, 1)))


def variancia(d):
    """Mudanca da fatia de X (pontos), decomposta entre municipios, entre locais do municipio e dentro do local; piso binomial."""
    e = d[(d.n1 >= MIN_N) & (d.n2 >= MIN_N)].copy()
    e['ds'] = 100 * (e.t2_X / e.n2 - e.t1_X / e.n1)
    p1, p2 = e.t1_X / e.n1, e.t2_X / e.n2
    piso = (1e4 * (p1 * (1 - p1) / e.n1 + p2 * (1 - p2) / e.n2)).mean()
    mun = e.groupby(['uf', 'municipality']).ds.transform('mean')
    loc = e.groupby('place').ds.transform('mean')
    tot = e.ds.var()
    k = e.groupby('place').ds.transform('size')
    loo = (loc * k - e.ds) / (k - 1)
    m = k >= 2
    return dict(var_total=float(tot), pct_entre_municipios=float(100 * mun.var() / tot), pct_entre_locais=float(100 * (loc - mun).var() / tot),
                pct_dentro_local=float(100 * (e.ds - loc).var() / tot), dentro_local_sobre_piso=float((e.ds - loc)[m].var() / piso),
                corr_com_vizinhas=float(np.corrcoef(e.ds[m], loo[m])[0, 1]))


def _feats(d):
    return ['t1_X', 't1_Y'] + sorted((c for c in d if c.startswith('t1_o') and c[4:].isdigit()), key=lambda c: int(c[4:])) + \
        ['t1_menores', 't1_bn', 't1_abst']


def _reg(d):
    # o DF e um municipio so: no sorteio por municipio ele cairia inteiro de um lado; entra no modelo do Centro-Oeste
    return d.regiao.replace({'Distrito Federal': 'Centro-Oeste (sem DF)'})


def transferencia(d, treino):
    """Coeficientes (0 a 1, minimos quadrados nao negativos) de cada grupo do 1o turno para X e para Y no 2o turno, por regiao."""
    f = _feats(d)
    co = {}
    for reg, g in d[treino].groupby(_reg(d[treino])):
        A = g[f].to_numpy(float)
        co[reg] = (nnls(A, g.t2_X.to_numpy(float))[0], nnls(A, g.t2_Y.to_numpy(float))[0])
    return f, co


def preve(d, f, co):
    px, py = np.full(len(d), np.nan), np.full(len(d), np.nan)
    for reg, (cx, cy) in co.items():
        m = (_reg(d) == reg).to_numpy()
        A = d.loc[m, f].to_numpy(float)
        px[m], py[m] = A @ cx, A @ cy
    return px, py


def transferencia_fora_da_amostra(d, rng, R=10):
    """Monte Carlo: ajusta as transferencias em metade dos municipios (sorteada) e preve a outra metade.
    Mede o erro nacional (pontos) e o erro por municipio; se a mudanca seguir a composicao do 1o turno, o erro e pequeno."""
    mun = d[['uf', 'municipality']].drop_duplicates()
    nac, rmse, p99 = [], [], []
    for _ in range(R):
        te = mun.sample(frac=.5, random_state=int(rng.integers(1 << 31)))
        m = d.set_index(['uf', 'municipality']).index.isin(te.set_index(['uf', 'municipality']).index)
        f, co = transferencia(d, ~m)
        t = d[m]
        px, py = preve(t, f, co)
        nac.append(100 * (px.sum() / (px.sum() + py.sum()) - t.t2_X.sum() / (t.t2_X.sum() + t.t2_Y.sum())))
        g = t.assign(px=px, py=py).groupby(['uf', 'municipality'])[['px', 'py', 't2_X', 't2_Y']].sum()
        g = g[(g.px + g.py > 0) & (g.t2_X + g.t2_Y > 0)]
        err = 100 * (g.px / (g.px + g.py) - g.t2_X / (g.t2_X + g.t2_Y))
        w = g.t2_X + g.t2_Y
        rmse.append(float(np.sqrt((w * err ** 2).sum() / w.sum())))
        p99.append(float(err.abs().quantile(.99)))
    return dict(transf_erro_nacional_pp_medio=float(np.mean(np.abs(nac))), transf_erro_nacional_pp_dp=float(np.std(nac)),
                transf_rmse_municipio_pp=float(np.mean(rmse)), transf_p99_municipio_pp=float(np.mean(p99)))


def todos(d, seed=0):
    """Todos os detectores numa base; devolve um dicionario de metricas (so taxas e razoes, sem totais que identifiquem a eleicao)."""
    rng = np.random.default_rng(seed)
    d = prepara(d)
    e, phi = modelo_local(d)
    o, _ = trocas(e, phi, rng)
    o.pop('secoes_no_modelo')
    o.pop('elegiveis_troca')
    for k in ('trocas_obs', 'fora4_obs'):
        o[k.replace('_obs', '_razao_obs_sim')] = o[k] / max(o[k.replace('_obs', '_sim')], 1)
        o.pop(k)
        o.pop(k.replace('_obs', '_sim'))
    o['fora4_saldo_X_por_10mil'] = 1e4 * o.pop('fora4_saldo_X') / len(e)
    o.update(dispersao(e))
    o.pop('locais')
    o.update(digitos(d))
    o.update(amontoamento(e, phi, rng))
    o.update(manual(d))
    v = viradas(e, phi, rng)
    o['viradas_razao_obs_sim'] = v['viradas_razao_obs_sim']
    o.update(variancia(d))
    o.update(transferencia_fora_da_amostra(d, rng))
    return o
