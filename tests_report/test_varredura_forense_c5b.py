"""Testes da varredura forense C5 parte B (funções puras, dados sintéticos, sem disco nem rede)."""
import numpy as np
import pytest

pd = pytest.importorskip('pandas')
pytest.importorskip('scipy')
V = pytest.importorskip('varredura_forense_c5b')


def test_bh_rejeita_so_os_menores():
    p = np.array([1e-6, 0.01, 0.02, 0.5, np.nan, 0.9])
    rej = V.bh(p, q=0.05)
    # m = 5 válidos; limiares 0.01, 0.02, 0.03, 0.04, 0.05 -> rejeita 1e-6, 0.01, 0.02
    assert rej.tolist() == [True, True, True, False, False, False]


def test_estima_rho_recupera_dispersao_conhecida():
    rng = np.random.default_rng(0)
    n = np.full(20000, 300.0)
    rho = 0.01
    a = np.ones_like(n)
    b = n - 1
    r2 = (1 + (n - 1) * rho) * rng.chisquare(1, size=len(n))
    est, phi = V.estima_rho(r2, a, b)
    assert abs(est - rho) < 0.002
    assert phi == 1.0
    # subdispersão: rho = 0 e phi < 1
    est0, phi0 = V.estima_rho(0.5 * rng.chisquare(1, size=5000), np.ones(5000), np.full(5000, 299.0))
    assert est0 == 0.0 and 0.4 < phi0 < 0.6


def test_residuo_predio_deixa_uma_de_fora():
    # prédio 0 com 4 seções, prédio 1 com 2 seções (sem pares suficientes)
    x = np.array([50, 60, 70, 200, 10, 10], dtype=float)
    n = np.array([100, 100, 100, 250, 50, 50], dtype=float)
    place = np.array([0, 0, 0, 0, 1, 1])
    ok = np.ones(6, dtype=bool)
    res = V.residuo_predio(x, n, place, ok, rho_phi=(0.0, 1.0))
    # seção 3: pares = seções 0,1,2 -> (180 + .5) / (300 + 1)
    assert res['mu'][3] == pytest.approx(180.5 / 301)
    assert res['k_pares'][3] == 3
    assert res['testavel'][:4].all() and not res['testavel'][4:].any()
    mu = 180.5 / 301
    a = 1 + 250 / 300
    z = (200 - 250 * mu) / np.sqrt(250 * mu * (1 - mu) * a)
    assert res['z'][3] == pytest.approx(z)
    assert np.isnan(res['z'][4])


def test_residuo_predio_margem_e_simetrica():
    rng = np.random.default_rng(1)
    k = 400
    place = np.repeat(np.arange(k // 5), 5)
    n = rng.integers(150, 300, size=k).astype(float)
    xa = rng.binomial(n.astype(int), 0.45).astype(float)
    xb = n - xa - rng.binomial((n - xa).astype(int), 0.05)
    ok = np.ones(k, dtype=bool)
    r_ab = V.residuo_predio(xa, n, place, ok, y=xb)
    r_ba = V.residuo_predio(xb, n, place, ok, y=xa)
    m = np.isfinite(r_ab['z'])
    assert m.sum() > 300
    assert np.allclose(r_ab['z'][m], -r_ba['z'][m])


def test_simula_nulo_tem_caudas_proximas_da_normal():
    rng = np.random.default_rng(2)
    k = 6000
    place = np.repeat(np.arange(k // 6), 6)
    n = rng.integers(200, 400, size=k)
    ok = np.ones(k, dtype=bool)
    p = rng.uniform(0.2, 0.7, size=k // 6)[place]
    x = rng.binomial(n, p).astype(float)
    res = V.residuo_predio(x, n, place, ok)
    xs, _ = V.simula_nulo(x, n, place, ok, res['rho'], rng)
    rs = V.residuo_predio(xs, n, place, ok)
    c = V.caudas(rs['z'])
    assert 0.8 < c['var'] < 1.25
    assert c['pos4'] + c['neg4'] <= 3


def test_bweb_para_secoes_pivot_e_quarentena():
    linhas = []
    for sec, (a, b, br, nu, comp, aptos) in {'1': (10, 5, 1, 2, 18, 30), '2': (7, 7, 0, 0, 15, 20),
                                              '3': (4, 4, 0, 0, 8, 7)}.items():
        for tipo, nr, q in (('1', '13', a), ('1', '22', b), ('2', '95', br), ('3', '96', nu)):
            if q:
                linhas.append(dict(CD_MUNICIPIO='100', NR_ZONA='1', NR_SECAO=sec, NR_LOCAL_VOTACAO='1015',
                                   QT_APTOS=str(aptos), QT_COMPARECIMENTO=str(comp), CD_TIPO_VOTAVEL=tipo,
                                   NR_VOTAVEL=nr, NM_VOTAVEL='X' + nr, QT_VOTOS=str(q), DS_TIPO_URNA='APURADA',
                                   DS_AGREGADAS='#NULO#'))
    d = pd.DataFrame(linhas)
    s, nomes = V.bweb_para_secoes(d, 'XX', 'teste', 'PRESIDENTE', checagem='teste')
    s = s.set_index('section')
    assert s.loc[1, 'v13'] == 10 and s.loc[1, 'branco'] == 1 and s.loc[1, 'validos'] == 15
    assert s.loc[1, 'status'] == 'OK'
    assert s.loc[2, 'status'].startswith('QUARENTENA: soma')   # 14 votos para comparecimento 15
    assert s.loc[3, 'status'].startswith('QUARENTENA: comparecimento maior')
    assert nomes['13'] == 'X13'
    assert not s.agregada.any()


def test_compara_vizinhas_dois_lados():
    # prédio com 5 seções; a seção 0 tem 80% para A, as outras 50%
    d = pd.DataFrame({'share_a': [80, 50, 51, 49, 50.0], 'share_b': [20, 50, 49, 51, 50.0],
                      'valid_votes': [300] * 5, 'place': [0] * 5, 'mun': [0] * 5})
    r = V.compara_vizinhas(d)
    assert r.loc[0, 'real_a'] and r.loc[0, 'diff_a'] == pytest.approx(30)
    assert r.loc[0, 'real_b'] and r.loc[0, 'diff_b'] == pytest.approx(-30)
    assert r.loc[0, 'nivel'] == 'local'
    # com a seção 0 marcada como comportamento, as comuns não a usam como par
    r2 = V.compara_vizinhas(d, beh=[True, False, False, False, False])
    assert r2.loc[1, 'diff_a'] == pytest.approx(50 - 50)
    assert r2.loc[1, 'nivel'] == 'local'   # pares 2, 3, 4 (a 0 fica de fora)


def test_classifica_pres_gov():
    base = dict(uf='XX', municipality=1, zone=1, branco=1, nulo=1, validos=0, status='OK', voting_place=1)
    p = pd.DataFrame([base | dict(section=s, aptos=a, comp=c) for s, a, c in
                      [(1, 100, 80), (2, 110, 85), (3, 100, 90), (4, 100, 70), (5, 100, 80), (6, 105, 80)]])
    g = pd.DataFrame([base | dict(section=s, aptos=a, comp=c) for s, a, c in
                      [(1, 100, 80), (2, 100, 80), (3, 100, 80), (4, 100, 75), (6, 100, 80), (7, 50, 40)]])
    j = V.classifica_pres_gov(p, g).set_index('section')
    assert j.loc[1, 'classe'] == 'igual'
    assert j.loc[2, 'classe'] == 'presidente maior, dentro dos aptos só-presidente'   # dc 5 <= da 10
    assert j.loc[3, 'classe'] == 'presidente maior que os aptos só-presidente explicam'  # dc 10 > da 0
    assert j.loc[4, 'classe'] == 'governador maior'
    assert j.loc[5, 'classe'] == 'NOT_COMPARABLE: sem BU de governador'
    assert j.loc[6, 'classe'] == 'aptos só-presidente sem comparecimento'
    assert j.loc[7, 'classe'] == 'NOT_COMPARABLE: sem BU de presidente'


def test_marca_extremos():
    s = pd.DataFrame({'uf': 'XX', 'municipality': [1, 1, 1, 2], 'zone': 1, 'section': [1, 2, 3, 4],
                      'voting_place': [10, 10, 11, 12], 'v13': [50, 40, 0, 30], 'v22': [0, 10, 5, 0],
                      'branco': 0, 'nulo': 0, 'aptos': [60, 80, 5, 30], 'comp': [50, 50, 5, 30]})
    s['validos'] = s.v13 + s.v22
    e = V.marca_extremos(s).set_index('section')
    assert e.loc[1, 'cem'] and e.loc[1, 'cand'] == '13'
    assert e.loc[1, 'local_outras_pct_cand'] == pytest.approx(80.0)
    assert e.loc[3, 'cem'] and e.loc[3, 'cand'] == '22' and e.loc[3, 'local_outras_secoes'] == 0
    assert e.loc[3, 'comp_eq_aptos'] and e.loc[4, 'comp_eq_aptos'] and not e.loc[1, 'comp_eq_aptos']
    assert e.loc[4, 'candidatos_com_voto_no_municipio'] == 1
    assert not e.loc[2, 'cem']


def test_c5_02_pleito_sintetico_acha_secao_plantada():
    rng = np.random.default_rng(3)
    k = 3000
    place = np.repeat(np.arange(k // 6), 6)
    n = rng.integers(200, 350, size=k)
    p13 = rng.uniform(0.3, 0.6, size=k // 6)[place]
    v13 = rng.binomial(n, p13)
    v22 = rng.binomial(n - v13, 0.85)
    v15 = n - v13 - v22
    v13[0] = n[0] - 5                              # seção plantada: quase tudo para 13
    v22[0] = 3
    v15[0] = 2
    s = pd.DataFrame({'uf': 'XX', 'municipality': 1, 'zone': 1, 'section': np.arange(k), 'voting_place': place,
                      'aptos': n + 50, 'comp': n + 10, 'v13': v13, 'v22': v22, 'v15': v15, 'branco': 4, 'nulo': 6,
                      'outros_tipo': 0, 'validos': n, 'agregada': False, 'status': 'OK',
                      'tipo_urna': 'APURADA'})
    fam, dest, st, Z = V.c5_02_pleito('2022-t1', s, {'13': 'A', '22': 'B'}, rng)
    assert set(fam.categoria) >= {'13', '22', '15', 'BRANCO', 'NULO', 'MARGEM_A-B'}
    d0 = dest[dest.section == 0]
    assert {'13', 'MARGEM_A-B'} <= set(d0.categoria)
    assert (d0.loc[d0.categoria == '13', 'lado'] == 'acima do prédio').all()
    assert (d0.loc[d0.categoria == '22', 'lado'] == 'abaixo do prédio').all()
    assert len(dest[dest.section != 0]) <= 3


def test_bweb_linhas_identicas_repetidas_sao_removidas_e_registradas():
    linha = dict(CD_MUNICIPIO='100', NR_ZONA='1', NR_SECAO='7', NR_LOCAL_VOTACAO='1015', QT_APTOS='50',
                 QT_COMPARECIMENTO='12', CD_TIPO_VOTAVEL='1', NR_VOTAVEL='13', NM_VOTAVEL='A', QT_VOTOS='12',
                 DS_TIPO_URNA='APURADA')
    d = pd.DataFrame([linha, linha])               # arquivo com a mesma linha duas vezes
    antes = len(V._QUARENTENA)
    s, _ = V.bweb_para_secoes(d, 'XX', 'teste', 'PREFEITO', checagem='teste')
    assert len(s) == 1 and s.loc[0, 'status'] == 'OK' and s.loc[0, 'v13'] == 12
    reg = V._QUARENTENA[antes:]
    assert len(reg) == 1 and reg[0]['linhas_identicas_removidas'] == '1'
    del V._QUARENTENA[antes:]
