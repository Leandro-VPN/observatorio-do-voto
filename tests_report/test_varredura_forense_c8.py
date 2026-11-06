"""Testes das funcoes puras de scripts/varredura_forense_c8.py (camada C8, clusters) com DataFrames sinteticos.
Sem rede e sem research/ ou relatorios/. Rodar com --basetemp=F:/votos/build/pytest_tmp_c8."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
C8 = pytest.importorskip('varredura_forense_c8')


def _secoes(seed=1, n_uf=3, n_mun=20, n_sec=10, plant=None):
    """3 UFs x 20 municipios x 10 secoes; micro = municipio // 5; meso = municipio // 10; predio = 2 secoes."""
    rng = np.random.default_rng(seed)
    rows = []
    for u in range(n_uf):
        for m in range(n_mun):
            for s in range(n_sec):
                r = rng.normal()
                if plant and plant(u, m, s):
                    r += 2.0
                rows.append(dict(uf=f'U{u}', municipality=m + 100 * u, zone=m // 2, section=s, voting_place=1000 + s // 2,
                                 micro=f'{u}-{m // 5}', meso=f'{u}-{m // 10}', res_pp=r, n2=200 + rng.integers(0, 100)))
    return pd.DataFrame(rows)


def test_permuta_dentro_preserva_multiconjunto_por_grupo():
    rng = np.random.default_rng(0)
    v = np.arange(12)
    g = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 2, 2])
    p = C8.permuta_dentro(v, g, rng)
    for k in range(3):
        assert sorted(p[g == k]) == sorted(v[g == k])
    assert not np.array_equal(p, v)


def test_padroniza_por_uf_media_zero_desvio_um():
    r = np.array([1., 2., 3., 10., 20., 30.])
    w = np.ones(6)
    uf = np.array([0, 0, 0, 1, 1, 1])
    z = C8.padroniza_por_uf(r, w, uf)
    assert abs(z[:3].mean()) < 1e-12 and abs(z[:3].std() - 1) < 1e-12
    assert abs(z[3:].mean()) < 1e-12
    # UF com variancia zero -> 0 (sem divisao por zero)
    z0 = C8.padroniza_por_uf(np.array([5., 5., 5.]), np.ones(3), np.array([0, 0, 0]))
    assert np.all(z0 == 0)


def test_scan_hierarquico_detecta_micro_plantada_e_nao_marca_sem_planta():
    d = _secoes(plant=lambda u, m, s: u == 1 and m < 5)   # micro '1-0' (5 municipios, 50 secoes) +2
    d['bloco'] = np.arange(len(d))
    g, lim = C8.scan_hierarquico(d, 'res_pp', 'n2', ['municipality', 'micro', 'meso'], 'bloco', n_perm=60, seed=3)
    mi = g[(g.nivel == 'micro')].sort_values('t', key=np.abs, ascending=False).iloc[0]
    assert mi.grupo == '1-0' and mi.uf == 'U1' and mi.acima_limite and mi.t > lim[lim.nivel == 'micro'].limite_p95_max_abs_t.iloc[0]
    assert mi.p_max_perm <= 1 / 61 + 1e-9
    assert set(lim.nivel) == {'municipality', 'micro', 'meso'} and (lim.grupos == [60, 12, 6]).all()
    d0 = _secoes(seed=7)
    d0['bloco'] = np.arange(len(d0))
    g0, lim0 = C8.scan_hierarquico(d0, 'res_pp', 'n2', ['micro', 'meso'], 'bloco', n_perm=60, seed=3)
    assert g0.acima_limite.sum() <= 1          # p95: raramente um grupo por nivel
    assert lim0.limite_p95_max_abs_t.between(1.5, 4).all()   # meso: 2 grupos por UF, t anticorrelacionados (soma 0 na UF)


def test_scan_hierarquico_bloco_predio_mantem_predios_juntos():
    d = _secoes(seed=2)
    d['bloco'] = d['uf'] + '|' + d['municipality'].astype(str) + '|' + d['voting_place'].astype(str)
    g, lim = C8.scan_hierarquico(d, 'res_pp', 'n2', ['micro'], 'bloco', n_perm=20, seed=1)
    assert len(g) == 12 and lim.sem_rotulo.iloc[0] == 0
    # nivel com rotulo nulo em algumas linhas: contado em sem_rotulo e fora dos grupos
    d.loc[d.uf == 'U2', 'micro'] = None
    g2, lim2 = C8.scan_hierarquico(d, 'res_pp', 'n2', ['micro'], 'bloco', n_perm=5, seed=1)
    assert lim2.sem_rotulo.iloc[0] == 200 and len(g2) == 8


def test_dispersao_dentro_marca_micro_com_municipios_opostos():
    d = _secoes(seed=5, plant=lambda u, m, s: u == 0 and m in (0, 2))
    d.loc[(d.uf == 'U0') & (d.municipality.isin([1, 3])), 'res_pp'] -= 2.0   # micro 0-0: municipios +2 / -2 alternados
    di = C8.dispersao_dentro(d, 'res_pp', 'n2', 'municipality', 'micro', n_perm=60, seed=4)
    top = di.sort_values('chi2_medio', ascending=False).iloc[0]
    assert top.grupo_externo == '0-0' and top.acima_limite and top.unidades_internas == 5


def _tecnico(seed=0, efeito=0.0, n_zonas=6, predios=15, secoes=8):
    """Secoes com predio e zona; geracao alternada dentro do predio (metade dos predios mistos); efeito plantado."""
    rng = np.random.default_rng(seed)
    rows = []
    serie = 1
    for z in range(n_zonas):
        base_zona = rng.normal() * 3
        for p in range(predios):
            base_predio = rng.normal() * 2
            misto = p % 2 == 0
            for s in range(secoes):
                ger = 'A' if (misto and s % 2 == 0) or (not misto and p % 4 == 1) else 'B'
                y = base_zona + base_predio + rng.normal() + (efeito if ger == 'A' else 0)
                rows.append(dict(zona_id=f'Z{z}', voting_place=z * 1000 + p, section=s, geracao=ger, cert_num=serie, y=y))
                serie += 1
    return pd.DataFrame(rows)


def test_efeito_dentro_predio_zero_quando_atributo_e_so_geografia():
    d = _tecnico(seed=1)
    d['attr_zona'] = d['zona_id']                    # atributo identico a zona: nada sobra com efeito fixo de zona/predio
    res, tab = C8.efeito_dentro_predio(d, 'y', 'attr_zona', n_perm=20, seed=1)
    assert res['status'] == 'feita' and res['estat_ef_zona'] < 1e-8 and res['estat_ef_predio'] < 1e-8
    assert res['predios_mistos'] == 0


def test_efeito_dentro_predio_detecta_geracao_plantada():
    d = _tecnico(seed=2, efeito=1.0)
    res, tab = C8.efeito_dentro_predio(d, 'y', 'geracao', n_perm=99, seed=2)
    assert res['status'] == 'feita' and res['p_perm_ef_predio'] <= 0.02 and res['predios_mistos'] == 6 * 8
    a = tab.set_index('geracao')
    assert a.loc['A', 'media_ef_predio'] > a.loc['B', 'media_ef_predio'] and a.loc['A', 't_ef_predio'] > 3
    d0 = _tecnico(seed=3, efeito=0.0)
    res0, _ = C8.efeito_dentro_predio(d0, 'y', 'geracao', n_perm=99, seed=2)
    assert res0['p_perm_ef_predio'] > 0.05
    res1, tab1 = C8.efeito_dentro_predio(d0.assign(geracao='A'), 'y', 'geracao')
    assert res1['status'] == C8.NOT_COMP and tab1.empty


def test_estat_entre_grupos_e_demean():
    y = np.array([1., 3., 10., 12.])
    c = np.array([0, 0, 1, 1])
    assert np.allclose(C8.demean_por(y, c), [-1, 1, -1, 1])
    # soma n_g * (media_g - media)^2 / var = (2*4,5^2 + 2*4,5^2) / var(y)
    assert np.isclose(C8.estat_entre_grupos(y, c), (2 * 4.5 ** 2 + 2 * 4.5 ** 2) / y.var())
    assert np.isclose(C8.estat_entre_grupos(y + 100, c), C8.estat_entre_grupos(y, c))   # invariante a deslocamento


def test_predio_id_inclui_zona():
    d = pd.DataFrame({'uf': ['SP', 'SP', 'SP'], 'municipality': [71072, 71072, 71072], 'zone': [1, 2, 1],
                      'voting_place': [1015, 1015, None]})
    k = C8.predio_id(d)
    assert k.iloc[0] != k.iloc[1] and k.iloc[0] == 'SP|71072|1|1015' and pd.isna(k.iloc[2])
    assert C8.estat_entre_grupos(np.array([2., 2., 2.]), np.array([0, 1, 1])) == 0.0


def test_autocorrelacao_serie_detecta_bloco_de_series_consecutivas():
    d = _tecnico(seed=4)
    # series espalhadas entre os predios da zona (como no real); blocos de 40 series consecutivas com nivel comum
    # (marca "tecnica" ao longo da serie, cruzando predios)
    rng = np.random.default_rng(4)
    d['cert_num'] = C8.permuta_dentro(d['cert_num'].to_numpy(), pd.factorize(d['zona_id'])[0], rng)
    bloco = (d['cert_num'] // 40).to_numpy()
    d['y'] = d['y'] + rng.normal(size=bloco.max() + 1)[bloco] * 1.5
    r = C8.autocorrelacao_serie(d, 'y', 'cert_num', n_perm=99, seed=4, janela=20)
    assert r['rho_lag1_outro_predio'] > 0.2 and r['p_perm_rho'] <= 0.02 and r['p_perm_var_janelas'] <= 0.02
    d0 = _tecnico(seed=5)
    d0['cert_num'] = C8.permuta_dentro(d0['cert_num'].to_numpy(), pd.factorize(d0['zona_id'])[0], rng)
    r0 = C8.autocorrelacao_serie(d0, 'y', 'cert_num', n_perm=99, seed=4, janela=20)
    assert abs(r0['rho_lag1_outro_predio']) < 0.15 and r0['p_perm_rho'] > 0.05


def test_bh():
    p = np.array([0.001, 0.01, 0.03, 0.2, 0.5, np.nan])
    ok = C8.bh(p, 0.05)
    assert ok.tolist() == [True, True, True, False, False, False]   # 0,03 <= 3/5 * 0,05
    assert C8.bh(np.array([np.nan, np.nan])).sum() == 0


def test_chave_stem():
    k = C8.chave_stem(pd.Series(['o00407-1479600440104', 'o03220ba3911000460366', 'xx']))
    assert k.iloc[0].tolist() == [14796, 44, 104] and k.iloc[1].tolist() == [39110, 46, 366]
    assert k.iloc[2].isna().all()


def test_c8_08_concentracao_binomial_e_bh():
    rows = []
    for z in range(30):
        for k in range(20):
            rows.append(dict(uf='BA', municipality=z, municipality_name=f'M{z}', zone=z, voting_place=k,
                             prioridade_observacao='alta' if (z == 0 and k < 12) or (z > 0 and k == 0) else 'baixa'))
    g = C8.c8_08_concentracao(pd.DataFrame(rows), ['uf', 'municipality', 'municipality_name', 'zone'])
    assert g.iloc[0].zone == 0 and g.iloc[0].alta == 12 and g.iloc[0].bh_5pct
    assert g.bh_5pct.sum() == 1 and np.isclose(g.taxa_uf.iloc[0], (12 + 29) / 600)


def test_c8_08_predios_vs_municipio():
    pred = pd.DataFrame([dict(uf='BA', municipality=1, zone=1, voting_place=p, y=(5 if p < 2 else 0) + (p % 2) * 0.1) for p in range(8)]
                        + [dict(uf='BA', municipality=2, zone=2, voting_place=p, y=10 + (p % 3)) for p in range(6)])
    marc = pd.DataFrame([dict(uf='BA', municipality=1, zone=1, voting_place=0), dict(uf='BA', municipality=1, zone=1, voting_place=1)])
    r = C8.c8_08_predios_vs_municipio(pred, marc, ['y'])
    assert r.predios_alta.iloc[0] == 2 and r.predios_outros_mesmo_mun.iloc[0] == 12
    assert 4 < r.diferenca_dentro_mun.iloc[0] < 5


def test_c8_11_classifica_troca_e_sem_ceft():
    exc = pd.DataFrame([
        dict(eleicao='2022-t1', uf='PR', municipio=1.0, zona=2.0, secao=3.0, urna=111, carga=pd.Timestamp('2022-10-02 08:30'),
             ok_data_eleicao=True, ok_carga_antes=False, ok_ordem_urna=True, ok_tse_depois_da_urna=True),
        dict(eleicao='2022-t1', uf='PR', municipio=1.0, zona=2.0, secao=4.0, urna=222, carga=pd.Timestamp('2022-10-02 09:00'),
             ok_data_eleicao=True, ok_carga_antes=False, ok_ordem_urna=True, ok_tse_depois_da_urna=True),
        dict(eleicao='2026-t2', uf='PA', municipio=9.0, zona=9.0, secao=9.0, urna=333, carga=pd.Timestamp('2026-10-25 08:00'),
             ok_data_eleicao=True, ok_carga_antes=True, ok_ordem_urna=True, ok_tse_depois_da_urna=False)])
    ceft = pd.DataFrame([
        dict(eleicao='2022-t1', uf='PR', municipality=1, zone=2, section=3, urna_esperada=100, urna_efetivada=111, dt_carga=pd.Timestamp('2022-10-02 08:30'),
             dt_carga_esperada=pd.Timestamp('2022-09-20 10:00'), troca=True, divergencia='C', origem_voto='Urna Eletronica'),
        dict(eleicao='2022-t1', uf='PR', municipality=1, zone=2, section=4, urna_esperada=222, urna_efetivada=222, dt_carga=pd.Timestamp('2022-10-02 09:05'),
             dt_carga_esperada=pd.Timestamp('2022-10-02 09:05'), troca=False, divergencia=None, origem_voto='Urna Eletronica')])
    integ = pd.DataFrame([dict(eleicao='2022-t1', uf='PR', municipality=1, zone=2, section=3, cert_num=111, cert_emissor='AC URNA', assinado_em='20221002T170000')])
    out = C8.c8_11_classifica(exc, ceft, integ)
    assert out.classe.tolist() == ['troca de urna no CEFT (esperada != efetivada)', 'carga original no dia, CEFT confirma a data', 'sem CEFT']
    assert out.status.tolist()[2].startswith(C8.NOT_COMP) and out.urna_bate_ceft.tolist()[:2] == [True, True]


def test_c8_12_exterior_not_comparable_sem_par():
    def base(ano, muns):
        return pd.DataFrame([dict(uf='ZZ', municipality=m, municipio=f'P{m}', zone=1, section=s, t2_aptos=100, t2_comp=80, t2_A=40, t2_B=30,
                                  t1_comp=70, t1_A=30, t1_validos=60, t2_validos=70) for m in muns for s in range(3)])
    m26 = pd.DataFrame([dict(uf='ZZ', municipality=1, residuo_pp=-2.0, n2=210), dict(uf='ZZ', municipality=2, residuo_pp=1.0, n2=210)])
    m22 = pd.DataFrame([dict(uf='ZZ', municipality=1, residuo_pp=-1.0, n2=210)])
    z = C8.c8_12_exterior(m26, m22, base(2026, [1, 2]), base(2022, [1]))
    assert len(z) == 2 and z.set_index('municipality').loc[2, 'status'].startswith(C8.NOT_COMP)
    assert z.set_index('municipality').loc[1, 'status'] == 'comparavel'
    assert np.isclose(z.set_index('municipality').loc[1, 'fatia_A_t2_pct_2026'], 100 * 120 / 210)


def test_c8_04_scan_processo_e_residuo_trocadas():
    d = _secoes(seed=9)
    d['aptos'] = 300
    d['comp'] = d['n2']
    d['contingencia'] = 0.0
    marca = (d.uf == 'U0') & (d.zone == 0) & (d.section < 6)             # zona 0 da U0: 12 de 20 secoes com contingencia
    d.loc[marca, 'contingencia'] = 1.0
    d.loc[marca, 'res_pp'] += 1.0
    rng = np.random.default_rng(1)
    d.loc[rng.random(len(d)) < 0.05, 'contingencia'] = 1.0
    g, lim = C8.c8_04_scan_processo(d, 'contingencia', None, n_perm=40, seed=1)
    za = g[(g.nivel == 'zona') & g.acima_limite]
    assert (za.uf == 'U0').all() and '0' in za.grupo.tolist()
    tr = C8.c8_04_residuo_trocadas(d, za)
    assert tr.status.iloc[0] == 'feita' and tr.diferenca_pp.iloc[0] > 0.3


def test_c8_10_excesso_por_zona():
    d = _secoes(seed=3)
    d['contingencia'] = (d.zone == 1).astype(float)
    d['manual_share'] = d['res_pp']
    z = C8.c8_10_excesso_por_zona(d, ['contingencia', 'manual_share'])
    assert len(z) == 30 and {'t_contingencia', 't_manual_share', 'n_contingencia'} <= set(z.columns)
    assert (z[z.zone == '1'].t_contingencia > 3).all()


def test_c8_03_maquina_universo_sem_troca_para_resultado():
    d = _tecnico(seed=6)
    d['predio_id'] = d['voting_place'].astype(str)
    d['maquina'] = np.where(d['geracao'] == 'A', 'M1', 'M2')
    d['troca'] = False
    d.loc[d.index % 7 == 0, 'troca'] = True
    d['share'] = d['y']
    d.loc[d['troca'] & (d['maquina'] == 'M1'), 'share'] += 50.0     # efeito so nas secoes com troca
    d['troca_ceft'] = d['troca'].astype(float)
    r, tab = C8.c8_03_maquina(d, {'share': 'share', 'troca_ceft': 'troca_ceft'}, atributos=('maquina',), com_troca=('troca_ceft',))
    rs = r.set_index('desfecho')
    assert rs.loc['share', 'universo'] == 'sem troca no CEFT' and rs.loc['share', 'n'] == int((~d['troca']).sum())
    assert rs.loc['troca_ceft', 'n'] == len(d) and rs.loc['share', 'p_perm_ef_predio'] > 0.01
    assert set(tab['desfecho']) == {'share', 'troca_ceft'}


def test_c8_03_turno_controle_ordem_absorve_confusao():
    rng = np.random.default_rng(11)
    rows = []
    for z in range(8):
        for p in range(20):
            for s in range(10):
                rank = s / 9
                manha = float(s < 5)                       # carga segue a ordem das secoes
                rows.append(dict(zona_id=f'Z{z}', predio_id=f'{z}-{p}', section=s, eligible=300, manha=manha,
                                 y=50 + 3.0 * rank + rng.normal(scale=0.5)))   # resultado depende so da ordem
    d = pd.DataFrame(rows)
    r = C8.c8_03_turno_controle(d, n_perm=50, seed=1)
    assert r['coef_manha_pp'] < -1.0 and r['p_perm_so'] <= 0.04
    assert abs(r['coef_manha_controle_ordem_tamanho_pp']) < 0.3 and r['corr_manha_rank'] < -0.8
