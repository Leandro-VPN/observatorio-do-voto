"""Testes das funcoes puras de scripts/varredura_forense_c7.py (camada C7, espelhamento e duplicidade) com DataFrames
sinteticos. Sem rede e sem research/ ou relatorios/. Rodar com --basetemp=F:/votos/build/pytest_tmp_c7."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
C7 = pytest.importorskip('varredura_forense_c7')


def _base():
    # 8 secoes: s1 = s2 (mesmo local), s3 = s4 (outra UF), s5 e s6 sao A/B trocados, s7 degenerada (B = 0), s8 comp < 50
    rows = [
        ('MG', 1, 1, 1, 10, 300, 250, 100, 120, 10, 20),
        ('MG', 1, 1, 2, 10, 300, 250, 100, 120, 10, 20),
        ('MG', 1, 1, 3, 11, 300, 240, 90, 130, 10, 10),
        ('SP', 2, 5, 9, 70, 300, 240, 90, 130, 10, 10),
        ('MG', 1, 2, 5, 12, 280, 200, 80, 100, 10, 10),
        ('MG', 3, 2, 6, 13, 280, 200, 100, 80, 10, 10),
        ('MG', 1, 1, 7, 10, 300, 250, 250, 0, 0, 0),
        ('MG', 1, 1, 8, 10, 60, 40, 20, 15, 3, 2),
    ]
    d = pd.DataFrame(rows, columns=['uf', 'municipality', 'zone', 'section', 'voting_place'] + C7.VEC_T2)
    d['ano'] = 2026
    d['elegivel'] = (d.uf != 'ZZ') & (d.t2_comp >= C7.COMP_MIN) & (d.t2_A > 0) & (d.t2_B > 0)
    return d


def test_pares_iguais_e_trocados_e_niveis():
    d = _base()
    e = d[d.elegivel]
    pares, grupos, secoes = C7.conta_pares_iguais(C7.hash_vetor(e, C7.VEC_T2))
    assert (pares, grupos, secoes) == (2, 2, 4)
    assert C7.conta_pares_trocados(e, C7.VEC_T2, C7.VEC_T2_TROCADO) == 1
    m = C7.enumera_pares(e, C7.VEC_T2)
    assert len(m) == 2 and sorted(m.nivel) == ['mesmo_local', 'outra_uf']
    # a secao degenerada (s7) e a pequena (s8) nao entram; um grupo de 3 iguais daria 3 pares
    e3 = pd.concat([e, e.iloc[[0]].assign(section=99)])
    assert C7.conta_pares_iguais(C7.hash_vetor(e3, C7.VEC_T2))[0] == 4  # 3 do trio + 1 do par


def test_permuta_dentro_preserva_multiconjunto_por_grupo():
    rng = np.random.default_rng(1)
    v = np.array([1, 2, 3, 10, 20, 30, 40, 5])
    gid = np.array([0, 0, 0, 1, 1, 1, 1, 2])
    out = C7.permuta_dentro(v, gid, rng)
    for g in (0, 1, 2):
        assert sorted(out[gid == g]) == sorted(v[gid == g])


def test_simula_vetores_respeita_comp_e_phi():
    d = _base()
    d = d[d.elegivel].reset_index(drop=True)
    m, phi = C7.modelo_parametrico(d)
    assert phi['phi_A'] >= 1 and set(m.columns) >= {'p_A', 'p_branco', 'p_nulo'}
    s = C7.simula_vetores(m, phi, np.random.default_rng(0))
    assert ((s.t2_A + s.t2_B + s.t2_branco + s.t2_nulo).to_numpy() == d.t2_comp.to_numpy()).all()
    assert (s >= 0).all().all()


def test_calibracao_devolve_observado_e_nulos():
    rng = np.random.default_rng(2)
    d = _base()
    cal, geo, uf, fx, info = C7.c7_01_calibracao(d, rng, r_param=5, r_perm=5)
    c = cal.set_index('medida')
    assert c.loc['pares_identicos', 'observado'] == 2 and c.loc['pares_trocados', 'observado'] == 1
    assert 0 < c.loc['pares_identicos', 'nulo1_p_excesso'] <= 1 and 'nulo2_media' in c
    assert abs(geo['frac_obs_mesmo_local'] - .5) < 1e-9 and info['secoes_elegiveis'] == 6


def test_c7_04_entre_pleitos_conta_iguais_trocas_e_proporcao():
    b0 = _base()
    b1 = b0.copy()
    b1.loc[b1.section == 1, ['t2_A', 't2_B']] = [120, 100]          # troca exata A/B
    b1.loc[b1.section == 3, ['t2_A', 't2_B', 't2_comp']] = [45, 65, 130]  # mesma proporcao 90:130, n diferente
    b1.loc[b1.section == 5, 't2_aptos'] = 1000                        # fora do filtro de aptos +-25%
    m, o = C7.c7_04_entre_pleitos(b0, b1, 2022, 2026)
    assert o['secoes_pareadas'] == 5 and o['votos_identicos'] == 3 and o['ab_trocados'] == 1
    assert o['proporcao_igual_n_diferente'] == 1


def test_c7_04_espelho_forte_detecta_inversao_de_fatia():
    b0 = _base()
    b0 = b0[b0.elegivel]
    b1 = b0.copy()
    b1['t2_A'], b1['t2_B'] = 220, 30  # todas passam a ~88% A: inversao para as secoes que tinham A minoritario
    out, res = C7.c7_04_espelho_forte(b0, b1, 2022, 2026)
    assert res['unidades'] == 6 and res['espelho_forte'] >= 0
    assert set(out.columns) >= {'fatia_A_antes_pct', 'fatia_A_depois_pct', 'residuo_espelho_pp'}


def test_runs_iguais_e_c7_05():
    pares, trios, maior = C7.runs_iguais([5, 5, 5, 7, 7, 1, 1], [0, 0, 0, 0, 1, 1, 1])
    assert (pares, trios, maior) == (3, 1, 3)   # 5,5,5 (2 pares, 1 trio) + 1,1 (1 par); 7,7 cruza grupo
    rows = []
    for s in range(1, 7):
        rows.append(('MG', 1, 1, s, 1 + s // 4, 300, 200 if s <= 3 else 150 + s, 90, 90, 10, 10))
    d = pd.DataFrame(rows, columns=['uf', 'municipality', 'zone', 'section', 'voting_place'] + C7.VEC_T2)
    d['elegivel'] = True
    o, por_uf, por_faixa, lista = C7.c7_05_comparecimento(d, np.random.default_rng(0), r=10)
    assert o['pares_consecutivos_iguais'] == 2 and o['trios_consecutivos_iguais'] == 1 and len(lista) == 2
    assert o['pares_iguais_secoes_numeradas_em_sequencia'] == 2 and 'nuloB_p_excesso' in o
    assert por_uf.iloc[0].pares_iguais == 2 and 'faixa_aptos' in por_faixa.columns


def test_medidas_predio_progressao_e_run():
    v = [10, 20, 30, 31, 31, 31, 5]
    gid = [0, 0, 0, 0, 0, 0, 1]
    prog, const, run = C7.medidas_predio(v, gid)
    assert prog == 1 and const == 1 and run == 4   # 10,20,30 e 10,20,30,31 crescente; 31,31,31 constante


def test_c7_06_sequencias_sintetico():
    rows = []
    for s, a in enumerate([10, 20, 30, 40], start=1):     # predio 1: progressao perfeita, ultimo digito igual, A-B constante
        rows.append(('MG', 1, 1, s, 1, 300, 200, a, a - 5, 5, 5))
    for s, a in enumerate([13, 7, 22, 9], start=5):      # predio 2: sem padrao
        rows.append(('MG', 1, 1, s, 2, 300, 200, a, 50, 5, 5))
    d = pd.DataFrame(rows, columns=['uf', 'municipality', 'zone', 'section', 'voting_place'] + C7.VEC_T2)
    d['elegivel'] = True
    o, tab, lista = C7.c7_06_sequencias(d, np.random.default_rng(0), r=10)
    assert o['predios_3mais'] == 2 and o['A_trios_progressao'] == 2 and o['predios_ultimo_digito_A_igual'] == 1
    assert o['predios_A_menos_B_constante'] == 1 and o['A_maior_run_monotono'] == 4
    assert len(lista) == 1 and lista.iloc[0].voting_place == 1


def test_c7_07_l1_e_quase_duplicatas():
    assert C7.l1_dicts({'00': 2, '11': 1}, {'00': 1, '12': 1}) == 3
    rows = [('MG', 1, 1, 1, 100, 80, 5, 3, '{"00": 2, "11": 1}'), ('MG', 1, 1, 2, 100, 80, 5, 3, '{"00": 2, "11": 1}'),
            ('SP', 2, 1, 1, 100, 80, 5, 3, '{"00": 1, "12": 2}'), ('SP', 2, 1, 2, 60, 90, 2, 3, '{"00": 3}')]
    rdv = pd.DataFrame(rows, columns=['uf', 'municipality', 'zone', 'section', 'v13', 'v22', 'branco', 'nulo', 'nulos'])
    m, o = C7.c7_07_quase_duplicatas(rdv, np.random.default_rng(0), r=3)
    assert o['pares_votos_identicos'] == 3 and o['pares_nulos_identicos'] == 1 and o['pares_nulos_identicos_nulo_ge3'] == 1


def test_c7_09_series_repetidas_e_resumo():
    rows = [('2022-t2', 'PA', 1, 1, 17, 10, '1809943', 1, 'APURADA', 300, 200, None, None, None, '13:100|22:90|95:5|96:5'),
            ('2022-t2', 'PA', 1, 1, 18, 10, '1809943', 1, 'APURADA', 300, 200, None, None, None, '13:100|22:90|95:5|96:5'),
            ('2022-t2', 'PA', 1, 1, 19, 10, '1809943', 1, 'APURADA', 310, 210, None, None, None, '13:110|22:90|95:5|96:5'),
            ('2022-t2', 'PA', 2, 1, 1, 11, '1111111', 1, 'Urna', 300, 200, None, None, None, '13:1|22:2|95:0|96:0'),
            ('2022-t2', 'PA', 2, 1, 2, 11, None, 0, 'Urna', 300, 200, None, None, None, '13:1|22:2|95:0|96:0')]
    sec = pd.DataFrame(rows, columns=['pleito', 'uf', 'municipality', 'zone', 'section', 'voting_place', 'urna', 'n_urna', 'tipo_urna',
                                      'aptos', 'comp', 'abertura', 'encerramento', 'carga', 'vetor'])
    rep, res = C7.c7_09_series_repetidas(sec)
    assert len(rep) == 3 and len(res) == 1 and res.iloc[0].secoes == 3 and res.iloc[0].vetores_distintos == 2 and bool(res.iloc[0].vetores_identicos)
    r = C7.c7_09_resumo_pleito(sec, rep).iloc[0]
    assert r.secoes == 5 and r.secoes_sem_serie == 1 and r.series_repetidas == 1 and r.secoes_em_serie_repetida == 3


def test_c7_09_ceft_resumo():
    ceft = pd.DataFrame({'pleito': '2022-t2', 'uf': 'BA', 'municipality': [1, 1, 1], 'zone': 1, 'section': [1, 2, 3],
                         'esperada': ['100', '200', '300'], 'efetivada': ['100', '999', '999'], 'origem': ['U', 'R', 'U'],
                         'divergencia': [None, '**', '**'], 'layout': 'com cabecalho'})
    ceft['troca'] = ceft.esperada != ceft.efetivada
    o = C7.c7_09_ceft_resumo(ceft).iloc[0]
    assert o.secoes == 3 and o.efetivada_diferente_da_esperada == 2 and o.series_efetivadas_em_mais_de_uma_secao == 1
    assert o.secoes_com_serie_efetivada_repetida == 2


def test_c7_13_duplicatas_chave():
    df = pd.DataFrame({'k': [1, 1, 2, 3, 3, 3], 'v': [5, 5, 1, 7, 8, 7]})
    o, dup = C7.c7_13_duplicatas_chave(df, ['k'], 'v')
    assert o == {'linhas': 6, 'chaves': 3, 'chaves_duplicadas': 2, 'chaves_duplicadas_com_valor_diferente': 1}
    assert len(dup) == 5 and dup[dup.k == 3].valor_diferente.all() and not dup[dup.k == 1].valor_diferente.any()


def test_c7_03_t1_e_t2_marca_pares_sem_vetor():
    pares = pd.DataFrame({'uf_1': ['MG', 'MG'], 'municipality_1': [1, 1], 'zone_1': [1, 1], 'section_1': [1, 3],
                          'uf_2': ['MG', 'SP'], 'municipality_2': [1, 2], 'zone_2': [1, 1], 'section_2': [2, 9]})
    t1 = pd.Series([11, 11, 22], index=pd.MultiIndex.from_tuples([('MG', 1, 1, 1), ('MG', 1, 1, 2), ('MG', 1, 1, 3)], names=C7.KEY))
    out = C7.c7_03_t1_e_t2(pares, t1)
    assert out.t1_identico.tolist() == [True, False] and out.t1_status.iloc[1].startswith('NOT_COMPARABLE')


def test_vetor_t1_2026_inclui_todos_os_votaveis():
    d = pd.DataFrame({'t1_v13': [1.0], 't1_v22': [2.0], 't1_v99': [np.nan], 't1_branco': [3], 't1_nulo': [4], 't1_comparecimento': [10], 't1_aptos': [20]})
    v, cols = C7.vetor_t1_2026(d)
    assert v.iloc[0] == '1|2|-1|3|4|10|20' and cols[0] == 't1_v13'


def test_c7_08_lista_fase_a_classifica():
    bins = pd.DataFrame({'uf': ['ES'] * 3, 'municipality': [1, 1, 1], 'zone': [1, 1, 1], 'section': [1, 2, 3], 'n_logs': [1, 2, 3],
                         'contingencia': [False, False, True]})
    lst = C7.c7_08_lista_fase_a(bins, 2026)
    assert len(lst) == 2 and sorted(lst.classe) == ['n_logs>=2 com contingencia', 'n_logs>=2 sem marca de contingencia']


def test_p_empirico_e_faixa():
    p = C7.p_empirico([1, 2, 3, 4], 3)
    assert abs(p['p_excesso'] - 3 / 5) < 1e-9 and abs(p['p_deficit'] - 4 / 5) < 1e-9
    assert C7.faixa_comp(pd.Series([50, 99, 100, 450])).tolist() == ['50-99', '50-99', '100-199', '400+']


def test_series_entre_ufs_e_layout_ceft_sem_cabecalho():
    sec = pd.DataFrame({'pleito': '2022-t1', 'uf': ['PA', 'AM', 'PA', 'SP'], 'urna': ['1', '1', '2', None]})
    out = C7.series_entre_ufs(sec)
    assert out.urna.tolist() == ['1'] and out.ufs.tolist() == [2]
    # CEFT 2012-2016: c10/c18 sao os numeros de urna (c9/c17 sao SQ_CORRESPONDENCIA)
    assert C7.CEFT_SEM_CABECALHO['esperada'] == 'c10' and C7.CEFT_SEM_CABECALHO['efetivada'] == 'c18'


def test_fatia_persistencia_conserva_desvio_e_aplica_mudanca_do_predio():
    # predio 1: 3 secoes; vizinhas passam de 50% para ~73% (logito +1); a secao alvo partia de 80%
    m = pd.DataFrame({'uf': 'MG', 'municipality': 1, 'voting_place': [1, 1, 1, 2],
                      't2_A_0': [80, 50, 50, 30], 't2_B_0': [20, 50, 50, 70],
                      't2_A_1': [90, 73, 73, 30], 't2_B_1': [10, 27, 27, 70]})
    p = C7.fatia_persistencia(m)
    lg = np.log(73 / 27) - 0.0  # logito(0,73) - logito(0,50)
    esperado = 1 / (1 + np.exp(-(np.log((80.5 / 101) / (1 - 80.5 / 101)) + lg)))
    assert abs(p[0] - esperado) < 1e-9
    # predio 2 tem uma secao so: cai para o municipio (outras 3 secoes do municipio)
    assert 0 < p[3] < 1 and p[3] > 30.5 / 101


def test_sensibilidade_phi1_devolve_contagens_por_nivel():
    sims = C7.c7_01_sensibilidade_phi(_base(), np.random.default_rng(3), r=3)
    assert len(sims) == 3 and {'pares_identicos', 'pares_mesmo_local', 'pares_outra_uf'} <= set(sims.columns)
    assert (sims.pares_identicos >= sims.pares_mesmo_local).all()


def test_contexto_espelho_traz_t1_e_fatia_do_predio():
    base = pd.DataFrame({'uf': 'RS', 'municipality': 1, 'zone': 1, 'section': [1, 2], 'voting_place': [10, 10],
                         't1_A': [60, 10], 't1_B': [40, 90], 't2_A': [70, 30], 't2_B': [30, 70]})
    fortes = pd.DataFrame({'uf': ['RS'], 'municipality': [1], 'zone': [1], 'section': [1], 'de': [2022], 'para': [2026]})
    out = C7.contexto_espelho(fortes, {2022: base, 2026: base})
    assert out.fatia_A_t1_pct_0.iloc[0] == 60 and out.fatia_A_predio_pct_1.iloc[0] == 50 and out.secoes_predio_0.iloc[0] == 2


def test_serie_nula_reconhece_marcadores_do_tse():
    assert C7.serie_nula(pd.Series(['#NULO#', '', None, '-1', '1095313', ' #ne# '])).tolist() == [True, True, True, True, False, True]
    sec = pd.DataFrame({'pleito': '2018-t1', 'uf': 'BA', 'municipality': [1, 2], 'zone': 1, 'section': [1, 2], 'urna': '#NULO#',
                        'tipo_urna': 'Apurada', 'comp': [10, 20], 'n_urna': 1})
    rep, res = C7.c7_09_series_repetidas(sec)
    assert rep.empty and C7.c7_09_resumo_pleito(sec, rep).secoes_sem_serie.iloc[0] == 2


def test_c7_07_nulo_estratificado_por_uf():
    rows = [('MG', 1, 1, 1, 100, 80, 5, 3, '{"00": 2, "11": 1}'), ('MG', 1, 1, 2, 100, 80, 5, 3, '{"00": 2, "11": 1}'),
            ('SP', 2, 1, 1, 90, 80, 5, 3, '{"00": 3}'), ('MG', 1, 1, 3, 70, 90, 2, 3, '{"00": 2, "11": 1}')]
    rdv = pd.DataFrame(rows, columns=['uf', 'municipality', 'zone', 'section', 'v13', 'v22', 'branco', 'nulo', 'nulos'])
    m, o = C7.c7_07_quase_duplicatas(rdv, np.random.default_rng(0), r=4)
    # na mesma UF (MG) os outros pools de nulo = 3 tem o mesmo padrao: o nulo por UF reproduz a igualdade sempre
    assert o['pares_nulos_identicos'] == 1 and o['nulo_uf_media_identicos'] == 1.0 and o['frac_mesma_uf_pares_nulos_identicos'] == 1.0
