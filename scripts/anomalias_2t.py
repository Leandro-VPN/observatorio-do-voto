"""Busca de padrao destoante em todas as urnas do 2o turno de 2026, com 2022 de controle, por varios modelos.

M1 modelo do local (padroes_lib): a secao repete o proprio 1o turno + a mudanca das outras secoes do mesmo local.
M2 gradient boosting fora da amostra: preve a fatia do PT no 2o turno pela composicao do 1o turno (todos os candidatos,
   brancos/nulos, abstencao, liberacao manual) e pela mudanca das vizinhas do local e do municipio; cada secao e prevista
   por um modelo treinado sem o municipio dela (validacao cruzada por municipio). Residuo em desvios-padrao robustos.
M3 multivariado: vetor de mudanca de cada secao (PT, adversario, branco/nulo, comparecimento, liberacao manual) contra as
   vizinhas do local; distancia de Mahalanobis robusta (MCD) e Isolation Forest.
M4 impressao digital comparecimento x voto (Klimek et al., PNAS 2012): histograma 2D observado contra o simulado pelo
   modelo do local (comparecimento e voto); excesso nos cantos de comparecimento e fatia altos (enchimento de urna).
M5 regional: cada municipio previsto por um modelo treinado so nas outras UFs; residuo por municipio e por UF.
M6 horario: residuo da secao contra votos depois das 17h e das 19h (prorrogacao de 2026), encerramento e abertura,
   dentro do mesmo local.
Validacao: as mesmas medidas em copias de 2026 com manipulacoes plantadas (inversao local, proporcional, votos tardios,
   regional suave, enchimento de urna).

secoes        roda M1-M6 em 2022 e 2026 e nas copias plantadas; lista as secoes destoantes (para a pericia de log)
Saida: relatorios/verificacoes/anomalias_2t/ e research/anomalias_2t/. Requer scikit-learn.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import expit, logit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from padroes_lib import EPS, formato_comum, modelo_local, prepara  # noqa: E402

WORK = ROOT / 'research' / 'anomalias_2t'
OUT = ROOT / 'relatorios' / 'verificacoes' / 'anomalias_2t'
CSV = dict(sep=';', decimal=',', index=False, encoding='utf-8-sig')
SEED = 20261030
CHAVE = ['uf', 'municipality', 'zone', 'section']
UV = ROOT / 'relatorios' / 'verificacoes' / 'ultimo_voto_2026t2' / 'ultimo_voto_por_secao.csv'
PLANTADAS = ['inversao_local', 'proporcional', 'votos_tardios', 'regional_suave', 'enchimento']


def _lg(a, n):
    return logit(np.clip((np.asarray(a, float) + .5) / (np.asarray(n, float) + 1), EPS, 1 - EPS))


def _min_do_dia(s):
    t = pd.to_datetime(s, errors='coerce')
    return t.dt.hour * 60 + t.dt.minute + t.dt.second / 60


def carrega(ano):
    """Base seca a secao (padroes_2t) no formato comum; em 2026, com o horario dos votos lido do log (ultimo_voto_2026t2)."""
    b = pd.read_parquet(ROOT / 'research' / 'padroes_2t' / f'base_{ano}.parquet')
    d = prepara(formato_comum(b))
    for c in ('municipality', 'zone', 'section'):
        d[c] = d[c].astype(int)
    for c in ('t2_enc_bsb', 't2_abre_min', 'desloc_h'):
        d[c] = b[c].to_numpy()
    d['mun'] = d.groupby(['uf', 'municipality'], sort=False).ngroup()
    if ano == 2026:
        u = pd.read_csv(UV, sep=';', decimal=',', encoding='utf-8-sig', low_memory=False,
                        usecols=CHAVE + ['votos_log', 'votos_apos_17h', 'votos_apos_19h', 'primeiro_voto', 'ultimo_voto'])
        for c in ('municipality', 'zone', 'section'):
            u[c] = u[c].astype(int)
        u['primeiro_voto_min'] = _min_do_dia(u.pop('primeiro_voto'))
        u['ultimo_voto_min'] = _min_do_dia(u.pop('ultimo_voto'))
        d = d.merge(u.drop_duplicates(CHAVE), on=CHAVE, how='left')
    return d


# ------------------------------------------------------------------ modelos
def _loo(e, k1, n1, k2, n2, grupo='place'):
    """Razao k/n no 2o turno prevista pelo 1o turno da propria secao + mudanca das outras secoes do grupo (logit)."""
    g = e.groupby(grupo)
    S = {c: g[c].transform('sum') for c in (k1, n1, k2, n2)}
    p = expit(_lg(e[k1], e[n1]) + _lg(S[k2] - e[k2], S[n2] - e[n2]) - _lg(S[k1] - e[k1], S[n1] - e[n1]))
    return np.clip(p, EPS, 1 - EPS)


def _escala(z):
    return float(1.4826 * np.median(np.abs(z - np.median(z))))


def _betabin(n, p, phi, rng):
    n = np.maximum(np.asarray(n, int), 0)
    if phi <= 1:
        return rng.binomial(n, p)
    rho = np.clip((phi - 1) / np.maximum(n - 1, 1), 1e-9, .99)
    return rng.binomial(n, rng.beta(p * (1 / rho - 1), (1 - p) * (1 / rho - 1)))


def _outros(e):
    return sorted((c for c in e if c.startswith('t1_o') and c[4:].isdigit()), key=lambda c: int(c[4:]))[:6]


def _feats(e):
    """Variaveis do M2: so o 1o turno da secao e a mudanca das vizinhas (nada do proprio 2o turno da secao)."""
    f = pd.DataFrame(index=e.index)
    c1 = e.t1_comp.clip(lower=1)
    for c in ['t1_X', 't1_Y'] + _outros(e) + ['t1_menores', 't1_bn']:
        f['s_' + c] = e[c] / c1
    f['abst1'] = e.t1_abst / e.t1_aptos.clip(lower=1)
    f['man1'] = e.t1_manual / c1
    f['lg1'] = _lg(e.t1_X, e.n1)
    f['sw_local'] = logit(e.p_loo) - f.lg1
    g = e.groupby('mun')
    S = {c: g[c].transform('sum') for c in ('t1_X', 'n1', 't2_X', 'n2', 't1_comp', 't1_aptos', 't2_comp', 't2_aptos')}
    f['sw_mun'] = _lg(S['t2_X'] - e.t2_X, S['n2'] - e.n2) - _lg(S['t1_X'] - e.t1_X, S['n1'] - e.n1)
    f['turn_viz'] = _lg(S['t2_comp'] - e.t2_comp, S['t2_aptos'] - e.t2_aptos) - _lg(S['t1_comp'] - e.t1_comp, S['t1_aptos'] - e.t1_aptos)
    f['regiao'] = e.regiao.astype('category').cat.codes
    f['log_n1'] = np.log(e.n1)
    return f.fillna(0)


def m2_boosting(e):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.model_selection import GroupKFold
    X = _feats(e).to_numpy(np.float32)
    y = _lg(e.t2_X, e.n2)
    w = e.n2.to_numpy(float)
    pred = np.zeros(len(e))
    for tr, te in GroupKFold(5).split(X, y, e.mun):
        m = HistGradientBoostingRegressor(max_iter=250, learning_rate=.08, max_leaf_nodes=63, min_samples_leaf=200,
                                          l2_regularization=1.0, early_stopping=False, random_state=SEED)
        m.fit(X[tr], y[tr], sample_weight=w[tr])
        pred[te] = m.predict(X[te])
    p = np.clip(expit(pred), EPS, 1 - EPS)
    z = (e.t2_X - e.n2 * p) / np.sqrt(e.n2 * p * (1 - p))
    return p, z / _escala(z)


def m3_multivariado(e):
    from sklearn.covariance import MinCovDet
    from sklearn.ensemble import IsolationForest
    a1, a2 = e.t1_aptos.clip(lower=1), e.t2_aptos.clip(lower=1)
    v = pd.DataFrame({'d_PT': e.t2_X / a2 - e.t1_X / a1, 'd_adversario': e.t2_Y / a2 - e.t1_Y / a1, 'd_branco_nulo': e.t2_bn / a2 - e.t1_bn / a1,
                      'd_comparecimento': e.t2_comp / a2 - e.t1_comp / a1,
                      'd_manual': e.t2_manual / e.t2_comp.clip(lower=1) - e.t1_manual / e.t1_comp.clip(lower=1)}).fillna(0)
    w = (v - v.groupby(e.place).transform('mean')).mul(np.sqrt(e.n2 / e.n2.median()), axis=0)
    amostra = w.sample(min(len(w), 60000), random_state=SEED)
    d2 = MinCovDet(random_state=SEED, support_fraction=.9).fit(amostra).mahalanobis(w)
    iso = IsolationForest(n_estimators=200, max_samples=4096, random_state=SEED, n_jobs=2).fit(amostra)
    return d2, -iso.score_samples(w), list(v.columns)


def _dentro(v, place):
    v = pd.Series(np.asarray(v, float), index=place.index)
    return (v - v.groupby(place).transform('mean')).to_numpy()


def m4_impressao(e, phi, rng, R=8):
    """Histograma 2D (comparecimento x fatia do PT entre os dois) observado contra o simulado pelo modelo do local."""
    pt = _loo(e, 't1_comp', 't1_aptos', 't2_comp', 't2_aptos')
    zt = (e.t2_comp - e.t2_aptos * pt) / np.sqrt(e.t2_aptos * pt * (1 - pt))
    phit = _escala(zt) ** 2
    bins = np.linspace(0, 1, 101)

    def h(comp, x, n):
        return np.histogram2d(np.clip(comp / e.t2_aptos.clip(lower=1), 0, 1), np.clip(x / np.maximum(n, 1), 0, 1), [bins, bins])[0]
    obs = h(e.t2_comp, e.t2_X, e.n2)
    sims = []
    for _ in range(R):
        comp = _betabin(e.t2_aptos, pt, phit, rng)
        n2 = np.round(e.n2 * comp / e.t2_comp.clip(lower=1))
        sims.append(h(comp, _betabin(n2, e.p_loo.to_numpy(), phi, rng), n2))
    sims = np.array(sims)
    mu, var = sims.mean(0), sims.var(0)
    o = {'phi_comparecimento': phit}
    zts, zv = (zt / np.sqrt(phit)).to_numpy(), e.z.to_numpy()
    o['corr_comparecimento_voto'] = float(np.corrcoef(_dentro(zts, e.place), _dentro(zv, e.place))[0, 1])
    o['conjunto_comp4_PT2'] = int(((zts > 4) & (zv > 2)).sum())
    o['conjunto_comp4_adv2'] = int(((zts > 4) & (zv < -2)).sum())
    for nome, sl in {'canto_comp90_PT90': (slice(90, None), slice(90, None)), 'canto_comp95_PT95': (slice(95, None), slice(95, None)),
                     'canto_comp90_adv90': (slice(90, None), slice(None, 10)), 'canto_comp95_adv95': (slice(95, None), slice(None, 5))}.items():
        a, m_, v_ = obs[sl].sum(), mu[sl].sum(), var[sl].sum()
        o[nome + '_obs'] = float(a)
        o[nome + '_sim'] = float(m_)
        o[nome + '_z'] = float((a - m_) / np.sqrt(v_ + m_ + 1))
    zc = (obs - mu) / np.sqrt(var + mu + 1)
    o['celula_max_z'] = float(zc.max())
    i, j = np.unravel_index(np.argmax(zc), zc.shape)
    o['celula_max_onde'] = f'comparecimento {bins[i]:.2f}-{bins[i + 1]:.2f}, PT {bins[j]:.2f}-{bins[j + 1]:.2f}'
    return o, obs, mu


def m5_regional(e):
    """Municipio previsto por modelo treinado nas outras UFs (composicao do 1o turno); residuo em pontos da fatia do PT."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    cols = ['t1_X', 't1_Y'] + _outros(e) + ['t1_menores', 't1_bn', 't1_abst', 't1_comp', 't1_aptos', 't1_manual', 't2_X', 'n1', 'n2']
    partes = ['t1_X', 't1_Y'] + _outros(e) + ['t1_menores', 't1_bn']
    m = e.groupby(['uf', 'municipality'])[cols].sum()
    m['regiao'] = e.groupby(['uf', 'municipality']).regiao.first().astype('category').cat.codes
    m = m.reset_index()
    X = pd.DataFrame({c: m[c] / m.t1_comp.clip(lower=1) for c in partes})
    X['abst'] = m.t1_abst / m.t1_aptos
    X['man'] = m.t1_manual / m.t1_comp.clip(lower=1)
    X['lg1'] = _lg(m.t1_X, m.n1)
    X['regiao'] = m.regiao
    X['log_n'] = np.log(m.n1)
    X = X.fillna(0).to_numpy(np.float32)
    y = _lg(m.t2_X, m.n2)
    p = np.zeros(len(m))
    for uf in m.uf.unique():
        te = (m.uf == uf).to_numpy()
        mod = HistGradientBoostingRegressor(max_iter=300, learning_rate=.06, min_samples_leaf=20, random_state=SEED)
        mod.fit(X[~te], y[~te], sample_weight=m.n2[~te])
        p[te] = expit(mod.predict(X[te]))
    m['previsto_pt_pct'] = 100 * p
    m['observado_pt_pct'] = 100 * m.t2_X / m.n2
    m['residuo_pp'] = m.observado_pt_pct - m.previsto_pt_pct
    u = m.groupby('uf').apply(lambda g: pd.Series({'municipios': len(g), 'votos': g.n2.sum(),
                                                   'residuo_pp': np.average(g.residuo_pp, weights=g.n2),
                                                   'dp_municipios_pp': float(np.sqrt(np.cov(g.residuo_pp, aweights=g.n2))) if len(g) > 1 else np.nan}),
                              include_groups=False).reset_index()
    return m, u


def m6_horario(e, ano):
    """Residuo (pontos da fatia do PT, M1) contra variaveis de horario, comparando secoes do mesmo local."""
    y = _dentro(e.res_pp, e.place)
    regs = {'encerrou_depois_17h30': (e.t2_enc_bsb >= 1050).astype(float), 'abriu_depois_8h15': (e.t2_abre_min + 60 * e.desloc_h.fillna(0) > 495).astype(float)}
    if ano == 2026 and 'votos_apos_17h' in e:
        vl = e.votos_log.where(e.votos_log > 0)
        regs.update({'fracao_votos_apos_17h': (e.votos_apos_17h / vl).fillna(0), 'teve_voto_apos_17h': (e.votos_apos_17h > 0).astype(float),
                     'teve_voto_apos_19h': (e.votos_apos_19h > 0).astype(float), 'votos_apos_17h_10': (e.votos_apos_17h >= 10).astype(float)})
    C = np.column_stack([_dentro(e.t2_comp / e.t2_aptos.clip(lower=1) - e.t1_comp / e.t1_aptos.clip(lower=1), e.place),
                         _dentro(np.log(e.n2), e.place), _dentro(e.t2_manual.fillna(0) / e.t2_comp.clip(lower=1), e.place)])
    Q, _ = np.linalg.qr(C)
    yc = y - Q @ (Q.T @ y)
    rows = []
    for nome, x in regs.items():
        xi = _dentro(x, e.place)
        row = dict(ano=ano, variavel=nome, secoes_com=int((x > 0).sum()))
        for suf, xx, yy in (('', xi, y), ('_com_controles', xi - Q @ (Q.T @ xi), yc)):
            ss = float(xx @ xx)
            if ss <= 0:
                break
            b = float(xx @ yy) / ss
            se = float(np.sqrt(np.sum((xx * (yy - b * xx)) ** 2))) / ss
            row.update({f'efeito_pp{suf}': b, f'ep_pp{suf}': se, f't{suf}': b / se})
        if 't' in row:
            rows.append(row)
    return pd.DataFrame(rows)


def roda(d, ano, rng, tudo=True):
    """Todos os modelos numa base; devolve metricas (para comparar real x plantado) e o frame por secao."""
    t0 = time.time()
    e, phi = modelo_local(d)
    e['res_pp'] = 100 * (e.t2_X / e.n2 - e.p_loo)
    e['p_m2'], e['z_m2'] = m2_boosting(e)
    e['d2_m3'], e['iso_m3'], _ = m3_multivariado(e)
    imp, obs, mu = m4_impressao(e, phi, rng)
    mun, uf = m5_regional(e)
    hor = m6_horario(e, ano)
    n = len(e)
    o = dict(secoes_no_modelo=n, phi_m1=phi, m1_fora4=int((e.z.abs() > 4).sum()), m1_fora4_PT=int((e.z > 4).sum()),
             m2_fora4=int((e.z_m2.abs() > 4).sum()), m2_fora4_PT=int((e.z_m2 > 4).sum()), m2_fora5=int((e.z_m2.abs() > 5).sum()),
             m2_esperado_normal_4=n * 2 * stats.norm.sf(4),
             m3_p1e6=int((stats.chi2.sf(e.d2_m3, 5) < 1e-6).sum()), m3_p1e9=int((stats.chi2.sf(e.d2_m3, 5) < 1e-9).sum()),
             m3_iso_p9999=float(np.quantile(e.iso_m3, .9999)),
             m1_z_media=float(np.average(e.z.clip(-10, 10), weights=e.n2)), m1_z_assimetria=float(stats.skew(e.z.clip(-10, 10))),
             m1_z_curtose=float(stats.kurtosis(e.z.clip(-10, 10))), m2_z_assimetria=float(stats.skew(e.z_m2.clip(-10, 10))),
             m2_z_curtose=float(stats.kurtosis(e.z_m2.clip(-10, 10))),
             m5_residuos_uf=json.dumps({k: round(v, 3) for k, v in zip(uf.uf, uf.residuo_pp)}),
             m5_uf_max_abs_pp=float(uf.residuo_pp.abs().max()), m5_uf_max_onde=uf.loc[uf.residuo_pp.abs().idxmax(), 'uf'],
             m5_mun_dp_pp=float(np.sqrt(np.cov(mun.residuo_pp, aweights=mun.n2))), **{'m4_' + k: v for k, v in imp.items()})
    for x in hor.itertuples():
        o[f'm6_{x.variavel}_t'] = x.t
        o[f'm6_{x.variavel}_pp'] = x.efeito_pp
        o[f'm6_{x.variavel}_t_ctrl'] = x.t_com_controles
    o['segundos'] = round(time.time() - t0)
    return o, e, dict(municipios=mun, ufs=uf, horario=hor, impressao_obs=obs, impressao_sim=mu)


# ------------------------------------------------------------------ manipulacoes plantadas (validacao)
def planta(d, tipo, rng):
    d = d.copy()
    n2 = (d.t2_X + d.t2_Y).to_numpy()
    x, y = d.t2_X.to_numpy().copy(), d.t2_Y.to_numpy().copy()
    info = {}
    if tipo == 'inversao_local':          # 250 secoes de lado claro com X e Y trocados
        el = np.flatnonzero((n2 >= 100) & (np.abs(x / np.maximum(n2, 1) - .5) >= .15) & (y > x))
        s = rng.choice(el, 250, replace=False)
        x[s], y[s] = y[s].copy(), x[s].copy()
    elif tipo == 'proporcional':          # 10% das secoes: 5% dos votos do adversario passam para o PT
        s = np.flatnonzero(rng.random(len(d)) < .10)
        k = np.floor(.05 * y[s]).astype(int)
        x[s] += k
        y[s] -= k
    elif tipo == 'votos_tardios':         # todo voto dado depois das 17h vai para o PT (tirado do adversario)
        s = np.flatnonzero(d.votos_apos_17h.fillna(0).to_numpy() >= 1)
        k = np.minimum(d.votos_apos_17h.to_numpy()[s].astype(int), y[s])
        x[s] += k
        y[s] -= k
    elif tipo == 'regional_suave':        # uma UF inteira: 2% dos votos do adversario passam para o PT
        uf = rng.choice(sorted(set(d.uf) - {'ZZ', 'DF'}))
        s = np.flatnonzero((d.uf == uf).to_numpy())
        k = np.floor(.02 * y[s]).astype(int)
        x[s] += k
        y[s] -= k
        info['uf'] = uf
    elif tipo == 'enchimento':            # 0,5% das secoes: metade dos ausentes vira voto no PT
        s = np.flatnonzero(rng.random(len(d)) < .005)
        k = np.round(.5 * (d.t2_aptos.to_numpy()[s] - d.t2_comp.to_numpy()[s])).clip(0).astype(int)
        x[s] += k
        d.loc[d.index[s], 't2_comp'] += k
    d['t2_X'], d['t2_Y'] = x, y
    d['n2'] = d.t2_X + d.t2_Y
    info['secoes_alteradas'] = int(len(s))
    info['votos_movidos'] = int(k.sum()) if tipo not in ('inversao_local',) else int(np.abs(x[s] - y[s]).sum())
    return d, info


def secoes():
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    linhas, extras = [], {}
    for ano in (2022, 2026):
        d = carrega(ano)
        o, e, x = roda(d, ano, rng)
        linhas.append(dict(base=f'real {ano}', ano=ano, **o))
        print(linhas[-1], flush=True)
        keep = CHAVE + ['voting_place', 'regiao', 'n1', 'n2', 't1_X', 't2_X', 't1_Y', 't2_Y', 'p_loo', 'z', 'res_pp', 'p_m2', 'z_m2', 'd2_m3', 'iso_m3']
        e[[c for c in keep if c in e] + [c for c in ('votos_log', 'votos_apos_17h', 'votos_apos_19h', 't2_enc_bsb') if c in e]].to_parquet(
            WORK / f'secoes_{ano}.parquet', index=False)
        extras[ano] = x
        x['municipios'].assign(ano=ano).to_csv(OUT / f'm5_municipios_{ano}.csv', **CSV)
        x['ufs'].assign(ano=ano).to_csv(OUT / f'm5_ufs_{ano}.csv', **CSV)
        np.savez_compressed(WORK / f'impressao_{ano}.npz', obs=x['impressao_obs'], sim=x['impressao_sim'])
        if ano == 2026:
            base26 = d
    pd.concat([extras[a]['horario'] for a in extras]).to_csv(OUT / 'm6_horario.csv', **CSV)
    for tipo in PLANTADAS:
        p, info = planta(base26, tipo, rng)
        o, _, _ = roda(p, 2026, rng)
        linhas.append(dict(base=f'plantada {tipo}', ano=2026, **info, **o))
        print(linhas[-1], flush=True)
        pd.DataFrame(linhas).to_csv(OUT / 'metricas_real_x_plantadas.csv', **CSV)
    pd.DataFrame(linhas).to_csv(OUT / 'metricas_real_x_plantadas.csv', **CSV)


if __name__ == '__main__':
    from baixa_pais import prioridade_baixa
    prioridade_baixa()
    {'secoes': secoes}[sys.argv[1]]()
