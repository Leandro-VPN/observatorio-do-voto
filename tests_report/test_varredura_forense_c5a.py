"""Testes das funcoes puras de scripts/varredura_forense_c5a.py (camada C5, parte A) com dados sinteticos.
Sem rede e sem research/ ou relatorios/. Rodar com --basetemp=F:/votos/build/pytest_tmp_c5a."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
C5 = pytest.importorskip('varredura_forense_c5a')
pl = pytest.importorskip('padroes_lib')


def _predios(n_places=200, k=5, seed=1, tau=.8, terc=True, persist=True):
    """Base preparada sintetica: cada predio tem k secoes; terceiros do 1o turno variam entre secoes e migram com tau."""
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(n_places):
        base = rng.uniform(.3, .7)
        for s in range(k):
            n = int(rng.integers(150, 400))
            t = rng.uniform(.0, .6) if terc else 0.0
            T = int(n * t)
            n12 = n - T
            x1 = rng.binomial(n12, base)
            y1 = n12 - x1
            xt = rng.binomial(T, tau)
            if persist:
                x2, y2 = x1 + xt, y1 + (T - xt)
            else:
                x2 = rng.binomial(n, (x1 + tau * T) / n)
                y2 = n - x2
            rows.append(dict(uf='SP', regiao='Sudeste', municipality=1 + p // 20, zone=1, voting_place=p, section=s + 1,
                             t1_X=x1, t1_Y=y1, t2_X=x2, t2_Y=y2, t1_validos=n, t1_aptos=n + 50, t2_aptos=n + 50,
                             t1_comp=n + 10, t2_comp=n + 10))
    return pl.prepara(pd.DataFrame(rows))


def test_phi_robusto_sem_piso():
    z = np.random.default_rng(0).normal(0, .5, 20000)
    assert abs(C5.phi_robusto(z) - .25) < .02  # o padroes_lib subiria para 1


def test_modelo_terceiros_absorve_transferencia():
    d = _predios()
    e, ph = C5.ajusta(d)
    # com persistencia do eleitorado o resto e quase deterministico: o modelo com terceiros fica muito mais justo
    assert e.z_terc_bruto.var() < .5 * e.z_bruto.var()
    assert ph['phi_terc'] < ph['phi_livre']
    assert set(['z_livre', 'z_terc_livre', 'p_terc', 'terc_t1']) <= set(e.columns)
    # sem terceiros, o modelo com terceiros nao piora muito o local
    e0, _ = C5.ajusta(_predios(terc=False, persist=False, seed=3))
    assert e0.z_terc_bruto.var() < 1.5 * e0.z_bruto.var()


def test_sorteio_escalado_variancia():
    rng = np.random.default_rng(2)
    n = np.full(50000, 300)
    p = np.full(50000, .4)
    for phi in (.25, 2.0):
        x = C5.sorteio_escalado(n, p, phi, rng)
        assert abs(x.var() / (300 * .4 * .6) - phi) < .1 * phi + .03


def test_fora_simulado_normal():
    rng = np.random.default_rng(3)
    n = np.full(200000, 1000)
    p = np.full(200000, .5)
    s = C5.fora_simulado(n, p, 1.0, rng, R=3, lim=3)
    assert abs(s.mean() / (2 * stats.norm.sf(3) * 200000) - 1) < .25


def test_permuta_dentro_preserva_grupos():
    rng = np.random.default_rng(4)
    g = np.repeat(np.arange(50), 4)
    v = np.arange(200)
    perm = C5.permuta_dentro(g, rng)
    w = v[perm]
    assert (g[perm] == g).all()
    for k in range(50):
        assert sorted(w[g == k]) == sorted(v[g == k])
    assert (w != v).mean() > .5


def test_permuta_mudanca_mantem_tamanhos():
    d = _predios(n_places=30)
    e, _ = pl.modelo_local(d)
    s = C5.permuta_mudanca(e, np.random.default_rng(5))
    assert (s.t2_X + s.t2_Y == e.n2.to_numpy()).all()
    assert s.t2_X.between(0, s.n2).all()


def test_dispersao_calibrada_subdispersa():
    d = _predios(seed=6, terc=False)
    e, _ = pl.modelo_local(d)
    o = C5.dispersao_calibrada(e)
    assert o['phi_disp'] < 1
    assert o['pct_uniforme_demais_lib'] > o['pct_uniforme_demais_calibrado']
    assert o['pct_uniforme_demais_calibrado'] < 10


def test_c5_09_causas_ordem():
    o = pd.DataFrame(dict(n_agreg_t1=[0, 1, 0, 0, 0, np.nan], n_agreg_t2=[0, 0, 0, 0, 0, np.nan],
                          t1_aptos=[300, 300, 400, 300, 300, 300], t2_aptos=[300, 300, 300, 300, 300, 300],
                          z_terc_livre=[1, 9, 9, 9, 9, 2], n2=[200, 200, 200, 50, 300, 300]))
    c = C5.c5_09_causas(o).causa.tolist()
    assert c == ['absorvida pelo modelo com terceiros do 1o turno', 'eleitorado ou agregacao diferente entre turnos',
                 'eleitorado ou agregacao diferente entre turnos', 'secao pequena (n2 < 100)', 'nao absorvida (restante)',
                 'absorvida pelo modelo com terceiros do 1o turno']


def test_p_zero_betabin():
    n = np.array([100, 200])
    p = np.array([.03, .05])
    assert np.allclose(C5.p_zero_betabin(n, p, 1.0), (1 - p) ** n)
    phi = 3.0
    rho = (phi - 1) / (n - 1)
    a, b = p * (1 / rho - 1), (1 - p) * (1 / rho - 1)
    ref = [stats.betabinom.pmf(0, n[i], a[i], b[i]) for i in range(2)]
    assert np.allclose(C5.p_zero_betabin(n, p, phi), ref)
    assert (C5.p_zero_betabin(n, p, phi) > (1 - p) ** n).all()


def test_loo_nivel_deixa_secao_fora():
    k = pd.Series([10, 20, 30])
    n = pd.Series([100, 100, 100])
    pl_ = pd.Series([0, 0, 0])
    p, z = C5.loo_nivel(k, n, pl_)
    assert np.isclose(p.iloc[0], (50 + .5) / 201)
    assert z.iloc[0] < 0 < z.iloc[2]


def test_c5_03_zeros_plantados():
    d = _predios(n_places=120, seed=7)
    rng = np.random.default_rng(8)
    d['t1_branco'] = rng.binomial(d.t1_comp, .04)
    d['t1_nulo'] = rng.binomial(d.t1_comp, .02)
    d['t2_branco'] = rng.binomial(d.t2_comp, .03)
    d['t2_nulo'] = rng.binomial(d.t2_comp, .015)
    zero = d.index[::8][:15]
    d.loc[zero, ['t2_branco', 't2_nulo']] = 0
    res, uf, dest, zeros, cruz = C5.c5_03_branco_nulo(d, 2099)
    r2 = res[(res.turno == 't2') & (res.medida == 'branco+nulo')].iloc[0]
    assert r2.zeros_obs >= 15
    assert r2.zeros_esp_binomial < 2
    assert (zeros.p0_binomial < 5e-3).all() and (zeros.z_nivel_livre < -2).all()
    assert set(zeros.turno) == {'t2'}


def test_digitos_heaping_detectado():
    rng = np.random.default_rng(9)
    n = rng.integers(300, 900, 30000)
    x = rng.binomial(n, .5)
    g = np.zeros(len(x), int)
    o, s = C5.digitos_referencia(x, n, g, 1, 'binomial', rng, R=60)
    r = C5.testa_digitos(o[0], s[:, 0])
    assert r['p_calibrado'] > 1e-3
    xh = x.copy()
    mexe = rng.random(len(x)) < .05
    xh[mexe] = (xh[mexe] // 10) * 10
    o2, s2 = C5.digitos_referencia(xh, n, g, 1, 'binomial', rng, R=60)
    r2 = C5.testa_digitos(o2[0], s2[:, 0])
    assert r2['mult10_z'] > 6 and r2['p_calibrado'] < 1e-6


def test_fracoes_exatas_plantadas():
    rng = np.random.default_rng(10)
    v = rng.integers(100, 400, 5000)
    x = rng.binomial(v, .5)
    f0 = C5.fracoes_exatas(x, v, rng, R=40)
    assert abs(f0.set_index('fracao').loc['todas', 'z']) < 4
    x2 = x.copy()
    par = v % 2 == 0
    x2[par[:]] = v[par] // 2
    f = C5.fracoes_exatas(x2, v, rng, R=40).set_index('fracao')
    assert f.loc['1/2', 'z'] > 10


def test_bh():
    q = C5.bh([.01, .02, .03, .5, np.nan])
    assert np.allclose(q[:4], [.04, .04, .04, .5])
    assert np.isnan(q[4])


def test_c5_12_pico_plantado():
    d = _predios(n_places=300, k=4, seed=11, terc=False, persist=False)
    # fixa a fatia em 60% em 8% das secoes
    rng = np.random.default_rng(12)
    m = rng.random(len(d)) < .08
    n2 = d.t2_X + d.t2_Y
    d.loc[m, 't2_X'] = np.rint(.6 * n2[m]).astype(int)
    d.loc[m, 't2_Y'] = n2[m] - d.loc[m, 't2_X']
    res, uf, ns, secs = C5.c5_12_picos(d, 2099)
    top = res[(res.serie == 'fatia') & (res['rank'] == 1)].iloc[0]
    assert .594 <= top.bin_ini <= .602
    assert top.obs > top.sim
    assert len(secs) == (secs.serie.isin(['fatia', 'razao'])).sum()


def test_invariantes_base():
    b = pd.DataFrame(dict(uf=['SP', 'SP'], municipality=[1, 1], zone=[1, 1], section=[1, 2],
                          t1_aptos=[100, 100], t1_comp=[90, 120], t1_branco=[5, 5], t1_nulo=[5, 5], t1_A=[40, 50], t1_B=[40, 50],
                          t1_validos=[80, 110], t2_aptos=[100, 100], t2_comp=[90, 90], t2_branco=[5, 5], t2_nulo=[5, 5],
                          t2_A=[40, 40], t2_B=[40, 40], t2_validos=[80, 80]))
    q = C5.invariantes_base(b, 2099)
    assert q.section.tolist() == [2]


def test_c5_06_digitos_base_sintetica():
    rng = np.random.default_rng(13)
    n = 4000
    aptos = rng.integers(200, 450, n)
    comp = rng.binomial(aptos, .8)
    bn = rng.binomial(comp, .05)
    br = rng.binomial(bn, .4)
    val = comp - bn
    a1 = rng.binomial(val, .45)
    b1 = rng.binomial(val - a1, .8)
    o1 = val - a1 - b1
    a2 = rng.binomial(val, .5)
    b = pd.DataFrame(dict(uf=np.where(np.arange(n) % 2, 'SP', 'MG'), municipality=1, zone=1, section=np.arange(n),
                          voting_place=np.arange(n) // 5, t1_aptos=aptos, t1_comp=comp, t1_branco=br, t1_nulo=bn - br,
                          t1_A=a1, t1_B=b1, t1_v12=o1,
                          t1_validos=val, t2_aptos=aptos, t2_comp=comp, t2_branco=br, t2_nulo=bn - br, t2_A=a2, t2_B=val - a2,
                          t2_validos=val))
    nac, puf, ref, fr = C5.c5_06_digitos(b, 2099, rng, R=40)
    assert {'t1_A', 't2_B', 't1_comp', 't2_aptos'} <= set(nac.serie)
    assert set(nac.minimo) == {100}
    # sem manipulacao nenhuma serie fica abaixo de 1e-4 na referencia calibrada
    assert (nac.p_calibrado > 1e-4).all()
    assert set(puf.uf) <= {'SP', 'MG'}
    assert len(ref) == len(nac)
    assert set(fr.fracao) >= {'1/2', 'todas'}


def test_referencia_em_torno_do_valor_viesada_em_contagens_pequenas():
    # documenta por que o C5-06 fica em contagens >= 100: com media ~10 a binomial em torno do valor observado alarga a
    # distribuicao e acusa diferenca sem manipulacao nenhuma; com media ~400 a mesma referencia fica calibrada
    rng = np.random.default_rng(14)
    g = np.zeros(20000, int)
    n = np.full(20000, 400)
    for media, minimo, esperado_baixo in ((10, 10, True), (400, 100, False)):
        x = rng.binomial(n, media / 400)
        o, s = C5.digitos_referencia(x, n, g, 1, 'binomial', rng, R=40, minimo=minimo)
        r = C5.testa_digitos(o[0], s[:, 0])
        assert (r['p_calibrado'] < 1e-6) == esperado_baixo
