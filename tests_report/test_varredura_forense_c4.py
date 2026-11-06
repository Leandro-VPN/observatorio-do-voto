"""Testes das funcoes puras de scripts/varredura_forense_c4.py (camada C4, totalizacao) com DataFrames sinteticos.
Sem rede e sem research/ ou relatorios/. Rodar com --basetemp=F:/votos/build/pytest_tmp_c4."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
C4 = pytest.importorskip('varredura_forense_c4')


def _sec2026():
    # 3 secoes no municipio 1 (uma so no T2) + 1 secao no municipio 2 + 1 no exterior
    rows = [
        dict(uf='MG', municipality=1, zone=1, section=1, _merge='both', t1_aptos=300, t1_comparecimento=250, t1_v13=100,
             t1_v22=120, t1_v55=10, t1_branco=10, t1_nulo=10, t2_aptos=300, t2_comparecimento=260, t2_v13=130, t2_v22=120,
             t2_branco=5, t2_nulo=5),
        dict(uf='MG', municipality=1, zone=1, section=2, _merge='both', t1_aptos=200, t1_comparecimento=150, t1_v13=60,
             t1_v22=70, t1_v55=5, t1_branco=10, t1_nulo=5, t2_aptos=200, t2_comparecimento=160, t2_v13=80, t2_v22=70,
             t2_branco=5, t2_nulo=5),
        dict(uf='MG', municipality=1, zone=1, section=3, _merge='right_only', t1_aptos=np.nan, t1_comparecimento=np.nan,
             t1_v13=np.nan, t1_v22=np.nan, t1_v55=np.nan, t1_branco=np.nan, t1_nulo=np.nan, t2_aptos=100, t2_comparecimento=90,
             t2_v13=50, t2_v22=30, t2_branco=5, t2_nulo=5),
        dict(uf='SP', municipality=2, zone=1, section=1, _merge='both', t1_aptos=400, t1_comparecimento=300, t1_v13=100,
             t1_v22=150, t1_v55=20, t1_branco=15, t1_nulo=15, t2_aptos=400, t2_comparecimento=310, t2_v13=150, t2_v22=140,
             t2_branco=10, t2_nulo=10),
        dict(uf='ZZ', municipality=29000, zone=1, section=1, _merge='both', t1_aptos=50, t1_comparecimento=40, t1_v13=10,
             t1_v22=20, t1_v55=5, t1_branco=3, t1_nulo=2, t2_aptos=50, t2_comparecimento=45, t2_v13=20, t2_v22=20,
             t2_branco=3, t2_nulo=2),
    ]
    return pd.DataFrame(rows)


def _mun2026():
    # municipio 1: oficial T1 inclui a secao 3 (sem BU): comparecimento 250+150+80 = 480, v13 160+40, v22 190+35, v55 15+0
    return pd.DataFrame([
        dict(uf='MG', municipality=1, municipality_name='A', t1_eleitorado=600, t1_comparecimento=480, t1_abstencao=120,
             t1_secoes=3, t1_validos=440, t1_v13=200, t1_v22=225, t1_v55=15, t2_eleitorado=600, t2_comparecimento=510,
             t2_abstencao=90, t2_secoes=3, t2_validos=480, t2_v13=260, t2_v22=220),
        dict(uf='SP', municipality=2, municipality_name='B', t1_eleitorado=400, t1_comparecimento=300, t1_abstencao=100,
             t1_secoes=1, t1_validos=270, t1_v13=100, t1_v22=150, t1_v55=20, t2_eleitorado=400, t2_comparecimento=310,
             t2_abstencao=90, t2_secoes=1, t2_validos=290, t2_v13=150, t2_v22=140),
    ])


def test_c4_01_reconciliacao_separa_t1_real_de_t2_artefato():
    m, uf, res = C4.c4_01_reconciliar_2026(_sec2026(), _mun2026())
    a = m[(m.uf == 'MG') & (m.municipality == 1)].iloc[0]
    assert not a.bate_t1 and a.bate_t2          # T2 fecha com a secao right_only incluida
    assert a.dif_t1_comparecimento == -80 and a.dif_t1_v13 == -40 and a.dif_t1_secoes == -1
    assert a.secoes_so_t2 == 1 and a.origem.startswith('T1: secao presente so no T2')
    b = m[(m.uf == 'SP')].iloc[0]
    assert b.status == 'OK' and b.bate_t1 and b.bate_t2
    z = m[m.uf == 'ZZ'].iloc[0]
    assert z.status.startswith('NOT_COMPARABLE')
    assert res['municipios_comparaveis'] == 2 and res['municipios_batem_t2'] == 2 and res['municipios_batem_t1'] == 1
    br = uf[uf.uf == 'BR (sem exterior)'].iloc[0]
    assert br.dif_t1_comparecimento == -80 and br.dif_t2_comparecimento == 0


def test_c4_01_candidato_sem_linha_oficial_vai_para_nulos():
    s = _sec2026()
    s['t1_v28'] = [5.0, 0.0, np.nan, 0.0, 0.0]        # votos no BU para candidato sem linha no oficial
    s.loc[0, 't1_nulo'] = 5                           # mantem comparecimento: 100+120+10+5+10+5 = 250
    mun = _mun2026()
    mun.loc[0, 't1_validos'] = 440                    # oficial: 28 nao conta como valido (vai para nulos)
    m, uf, res = C4.c4_01_reconciliar_2026(s, mun)
    a = m[(m.uf == 'MG') & (m.municipality == 1)].iloc[0]
    # BU (secoes 1 e 2): validos 370 - 5 (v28) = 365 x oficial 440 (inclui a secao 3); bn 30 + 5 = 35 x oficial 40
    assert a.t1_v_sem_linha_oficial == 5 and a.dif_t1_validos == -75 and a.dif_t1_bn == -5
    assert res['candidatos_sem_linha_oficial'] == {'t1_v28': 5} and 'dif_t1_v28' not in m.columns
    b = m[m.uf == 'SP'].iloc[0]
    assert b.bate_t1


def test_c4_01_invariante_e_canais():
    s = _sec2026()
    s.loc[0, 't2_nulo'] = 99                      # quebra v13+v22+branco+nulo = comparecimento
    f1, f2, f3 = C4.c4_01_invariante_secao(s)
    assert len(f1) == 0 and len(f2) == 1 and f2.iloc[0].section == 1 and len(f3) == 0
    canal = pd.DataFrame([dict(uf='MG', municipality=1, zone=1, section=1, aux_status='Totalizada', e6258_aptos=300,
                               e6258_comparecimento=260, e6258_c1_v13=130, e6258_c1_v22=120, e6258_c1_branco=5, e6258_c1_nulo=5),
                          dict(uf='MG', municipality=1, zone=1, section=2, aux_status='Recebida', e6258_aptos=200,
                               e6258_comparecimento=160, e6258_c1_v13=81, e6258_c1_v22=69, e6258_c1_branco=5, e6258_c1_nulo=5),
                          dict(uf='ZZ', municipality=29000, zone=1, section=1, aux_status='Totalizada', e6258_aptos=50,
                               e6258_comparecimento=45, e6258_c1_v13=20, e6258_c1_v22=20, e6258_c1_branco=3, e6258_c1_nulo=2)])
    sec = _sec2026()
    sec.loc[sec.uf == 'ZZ', 't2_nulo'] = 0                 # o canal 2 omite votaveis com zero votos (NaN == 0)
    canal.loc[canal.uf == 'ZZ', 'e6258_c1_nulo'] = np.nan
    dif, r, n, ig = C4.c4_01_canais_2026_t2(sec, canal)
    assert n == 3 and ig == 2 and len(dif) == 1 and dif.iloc[0].section == 2
    assert r[r.aux_status == 'Recebida'].diferentes.iloc[0] == 1
    assert r[r.uf == 'ZZ'].secoes_com_campo_nulo_no_canal2.iloc[0] == 1


def test_c4_02_stems_membros_e_esperadas():
    assert C4.stem_chave('o03221mg4123800390168') == (41238, 39, 168)
    assert C4.stem_chave('o00407-4375300940104') == (43753, 94, 104)
    assert C4.stem_chave('abc') is None
    assert C4.membro_stem_tipo('o03220mg4123800390168-busa.dat') == ('o03220mg4123800390168', 'busa.dat')
    assert C4.membro_stem_tipo('o00407-4375300940104.logjez') == ('o00407-4375300940104', 'logjez')
    assert C4.membro_stem_tipo('leiame.pdf') == (None, 'leiame.pdf')
    g = C4.membros_por_stem(['o03220mg0000100010001-bu.dat', 'o03220mg0000100010001-rdv.dat', 'o03220mg0000100010001-log.jez',
                             'o03220mg0000100010001-vota.vsc', 'o03220mg0000100010002-rdv.dat', 'o03220mg0000100010002-busa.dat',
                             'o03220mg0000100010002-sa.vsc', 'leiame.pdf']).set_index('stem')
    assert g.loc['o03220mg0000100010001', ['tem_bu', 'tem_rdv', 'tem_log', 'tem_assinatura']].all()
    s2 = g.loc['o03220mg0000100010002']
    assert not s2.tem_bu and s2.tem_rdv and s2.apuracao_separada
    esp = pd.DataFrame({'uf': ['MG', 'MG', 'MG'], 'municipality': [1, 1, 1], 'zone': [1, 1, 1], 'section': [1, 2, 3]})
    rec = C4.chaves_de_stems(['o03221mg0000100010001', 'o03221mg0000100010002', 'o03221mg0000100010009', 'ruim'], 'MG')
    assert rec.municipality.isna().sum() == 1
    m = C4.c4_02_esperadas_x_recebidas(esp, rec)
    st = m.set_index('section').status
    assert st[1] == 'OK' and st[3] == 'esperada sem BU no zip' and st[9] == 'BU no zip sem secao na lista oficial'
    cm = C4.c4_02_contagem_municipio(_sec2026(), _mun2026())
    a = cm[(cm.uf == 'MG')].iloc[0]
    assert a.t1 == 2 and a.t2 == 3 and a.dif_t1 == -1 and a.dif_t2 == 0 and a.status != 'OK'


def test_c4_02_ler_cs_json_marca_agregadas(tmp_path):
    j = {'abr': [{'cd': 'ac', 'mu': [{'cd': '01074', 'nm': 'CRUZEIRO DO SUL', 'zon': [{'cd': '0004', 'sec': [
        {'ns': '0001', 'da': '25/10/2026', 'ha': '21:26:45', 'nsa': '0270'}, {'ns': '0270', 'nsp': '0001'}]}]}]}]}
    p = tmp_path / 'AC-cs.json'
    p.write_text(__import__('json').dumps(j), encoding='utf-8')
    e = C4.ler_cs_json(p, 'AC')
    assert e.uf.tolist() == ['AC', 'AC'] and e.municipality.tolist() == [1074, 1074]
    assert e.iloc[0].recebido_em == pd.Timestamp('2026-10-25 21:26:45') and not e.iloc[0].agregada
    assert e.iloc[1].agregada and e.iloc[1].secao_principal == 1 and pd.isna(e.iloc[1].recebido_em)


def test_c4_03_bweb_x_bu_e_stem_esperado():
    bweb = pd.DataFrame({'uf': ['BA'] * 3, 'municipality': [10, 10, 10], 'zone': [1, 1, 1], 'section': [1, 2, 3],
                         'aptos': [100, 100, 100], 'comp': [80, 70, 60]})
    stems = C4.chaves_de_stems(['o00407-0001000010001', 'o00407-0001000010002', 'o00407-0001000010004'], 'BA')
    fora, por_uf = C4.c4_03_bweb_x_bu(bweb, stems)
    assert set(fora.status) == {C4.SEM_BU, C4.SEM_BWEB}
    assert fora[fora.status == C4.SEM_BU].section.tolist() == [3] and fora[fora.status == C4.SEM_BWEB].section.tolist() == [4]
    r = por_uf.iloc[0]
    assert r.bweb == 3 and r.bu_zip == 3 and r.bweb_sem_bu == 1 and r.bu_sem_bweb == 1
    pref = C4.prefixo_stems(stems)
    assert pref == 'o00407-' and C4.stem_esperado(pref, 10, 1, 3) == 'o00407-0001000010003'


def test_c4_04_municipios_e_uf():
    sec = pd.DataFrame({'uf': ['BA', 'BA', 'BA', 'ZZ'], 'municipality': [1, 1, 2, 29000], 'aptos': [100, 100, 50, 30],
                        'comp': [80, 70, 40, 20], 'abst': [20, 30, 10, 10], 'cd_tipo_urna': [1, 4, 1, 1],
                        'agregadas': [None, '3 / 4', None, None]})
    ref = pd.DataFrame({'uf': ['BA', 'BA', 'BA'], 'municipality': [1, 2, 3], 'municipio': ['A', 'B', 'C'],
                        'aptos_of': [200, 50, 10], 'comp_of': [80, 40, 5], 'abst_of': [120, 10, 5]})
    m = C4.c4_04_municipios(sec, ref)
    a = m[(m.uf == 'BA') & (m.municipality == 1)].iloc[0]
    assert a.secoes == 2 and a.anuladas == 1 and a.agregadas == 1 and a.dif_comp == 70 and a.dif_abst == -70 and a.status != 'OK'
    assert m[(m.uf == 'BA') & (m.municipality == 2)].iloc[0].status == 'OK'
    assert m[m.municipality == 3].iloc[0].status.startswith('NOT_COMPARABLE: referencia')
    assert m[m.uf == 'ZZ'].iloc[0].status.startswith('NOT_COMPARABLE: municipio')
    uf = C4.c4_04_por_uf(m)
    ba = uf[uf.uf == 'BA'].iloc[0]
    assert ba.municipios == 2 and ba.municipios_batem == 1 and ba.dif_comp == 70
    assert uf[uf.uf == 'TOTAL (com exterior)'].iloc[0].municipios == 2


def test_c4_05_duplicidade_e_inconsistencias():
    stems = C4.chaves_de_stems(['o00407-0001000010001', 'o00407-0001000010001', 'o00407-0001000010002', 'x'], 'BA')
    stems['pleito'] = '2022-t2'
    dup, inval = C4.c4_05_stems_duplicados(stems)
    assert len(dup) == 2 and len(inval) == 1
    sec = pd.DataFrame({'pleito': ['p'] * 4, 'uf': ['BA'] * 4, 'municipality': [1, 1, 1, 1], 'zone': [1, 1, 1, 1],
                        'section': [1, 2, 3, 4], 'n_urna': [1, 2, 1, 1], 'urna': [1, 2, 3, 4],
                        'aptos': [100, 100, 100, 100], 'aptos_min': [100, 100, 90, 100], 'comp': [80, 80, 80, 80],
                        'comp_min': [80, 80, 80, 80], 'abst': [20, 20, 20, 25], 'abst_min': [20, 20, 20, 25],
                        'votos_total': [80, 80, 80, 79], 'n_cargos': [1, 1, 1, 1]})
    casos, resumo, flags = C4.c4_05_bweb_inconsistencias(sec)
    assert casos.section.tolist() == [2, 3, 4]
    r = resumo.iloc[0]
    assert r.n_urna_gt1 == 1 and r.aptos_var == 1 and r.aptos_ne_comp_abst == 1 and r.votos_ne_comp == 1 and r.secoes == 4


def test_c4_07_anuladas_inclusao_no_oficial():
    sec = pd.DataFrame({'pleito': ['p', 'p', 'p'], 'uf': ['BA', 'BA', 'MG'], 'municipality': [1, 2, 3], 'zone': [1, 1, 1],
                        'section': [5, 6, 7], 'aptos': [100, 100, 100], 'comp': [80, 70, 0], 'cd_tipo_urna': [4, 3, 4]})
    mun = pd.DataFrame({'pleito': ['p'] * 3, 'uf': ['BA', 'BA', 'MG'], 'municipality': [1, 2, 3], 'municipio': ['A', 'B', 'C'],
                        'dif_aptos': [0, 100, 0], 'dif_comp': [0, 70, 0], 'status': ['OK', 'x', 'OK']})
    stems = pd.DataFrame({'pleito': ['p'], 'uf': ['BA'], 'municipality': [1], 'zone': [1], 'section': [5], 'stem': ['s']})
    out = C4.c4_07_anuladas(sec, mun, stems).set_index('section')
    assert out.loc[5].comp_no_oficial.startswith('total oficial inclui')
    assert out.loc[6].comp_no_oficial.startswith('total oficial exclui') and out.loc[6].aptos_no_oficial.startswith('total oficial exclui')
    assert out.loc[7].comp_no_oficial.startswith('valor 0')
    assert out.loc[5].tem_bu_no_zip == 'sem zip de urna no pleito'      # pleito 'p' nao tem zip de urna


def test_c4_08_agregadas():
    sec = pd.DataFrame({'pleito': ['2022-t2'] * 3, 'uf': ['SP'] * 3, 'municipality': [1, 1, 1], 'zone': [1, 1, 1],
                        'section': [10, 11, 12], 'agregadas': ['11 / 13', None, None], 'aptos': [500, 200, 300], 'comp': [400, 150, 250]})
    agr = C4.explodir_agregadas(sec)
    assert agr.agregada.tolist() == [11, 13]
    bp = C4.c4_08_agregadas_com_bu_proprio(agr, sec)
    assert bp.set_index('agregada').bu_proprio.to_dict() == {11: 1, 13: 0}
    perfil = pd.DataFrame({'uf': ['SP'] * 3, 'municipality': [1, 1, 1], 'zone': [1, 1, 1], 'section': [10, 11, 13],
                           'voters': [250, 150, 100]})
    g = C4.c4_08_aptos_vs_perfil(agr, sec, perfil)
    assert len(g) == 1 and g.iloc[0].dif_aptos_vs_principal_mais_agregadas == 0 and g.iloc[0].leitura == 'aptos = principal + agregadas'


def test_c4_10_recebimento_antes_e_relogio():
    fech = pd.DataFrame({'uf': ['PA', 'PA'], 'municipality': [1, 1], 'zone': [1, 1], 'section': [1, 2], 'min_rec_apos_enc': [-0.8, 120.0]})
    a = C4.c4_10_recebimento_antes(fech)
    assert len(a) == 1 and a.iloc[0].min_antes == pytest.approx(0.8)
    rel = pd.DataFrame({'eleicao': ['e'] * 3, 'uf': ['MG'] * 3, 'ok_tse_depois_da_urna': [True, False, False], 'sem_datas': [False, False, True],
                        'ok_carga_antes': [True, True, False], 'ok_data_eleicao': [True, True, True], 'ok_ordem_urna': [True, True, True]})
    ex, res = C4.c4_10_relogio_excecoes(rel)
    assert len(ex) == 1 and res.iloc[0].tse_antes_da_urna == 2 and res.iloc[0].carga_nao_anterior == 1 and res.iloc[0].sem_datas == 1


def test_c4_11_consolidar_flags():
    k = dict(pleito='2022-t2', uf='BA', municipality=1, zone=1, section=1)
    f = {'ceft': pd.DataFrame([k | {'origem_voto': 'Sistema de apuração'}]),
         'sem_bu': pd.DataFrame([k, k | {'section': 2}]), 'vazio': pd.DataFrame(columns=list(k))}
    out = C4.c4_11_consolidar(f)
    assert len(out) == 2 and set(out.columns) >= {'f_ceft', 'f_sem_bu', 'fontes'}
    assert out[out.section == 1].fontes.iloc[0] == 'ceft;sem_bu' and out[out.section == 2].fontes.iloc[0] == 'sem_bu'


def test_c4_12_proxy_e_comparacao():
    logs22 = pd.DataFrame({'uf': ['BA'] * 4 + ['SP'] * 2, 'n_logs': [1, 2, 3, 1, 1, 1], 'contingencia': [False, True, True, False, False, False]})
    logs26 = pd.DataFrame({'uf': ['BA'] * 4 + ['SP'] * 2, 'n_logs': [1, 1, 2, 1, 1, 1], 'contingencia': ['False', 'False', 'True', 'False', 'False', 'False']})
    p22 = C4.c4_12_proxy_trocas(logs22, '2022')
    p26 = C4.c4_12_proxy_trocas(logs26, '2026')
    assert p22.set_index('uf').loc['BA'].com_contingencia == 2 and p22.set_index('uf').loc['BA'].n_logs_3mais == 1
    ceft = pd.DataFrame({'eid': ['P2022b', 'P2026'], 'uf': ['BA', 'BA'], 'swaps': [2, 1], 'swap_pct': [50.0, 25.0]})
    c = C4.c4_12_comparar(p22, p26, ceft).set_index('uf')
    assert c.loc['BA'].razao_2026_2022 == pytest.approx(0.5) and c.loc['BA'].proxy_menos_ceft_2022t2_pp == pytest.approx(0.0)
    assert np.isnan(c.loc['SP'].swap_pct_ceft_2022t2)


def test_c4_13_atrasos_fuso_e_dia_seguinte():
    t = pd.Timestamp
    d = pd.DataFrame({'uf': ['AC', 'SP', 'SP'], 'municipality': [1, 2, 2],
                      'dt_emissao_bu': [t('2022-10-30 15:05'), t('2022-10-30 17:05'), t('2022-10-30 17:05')],
                      'dt_encerramento': [t('2022-10-30 15:01'), t('2022-10-30 17:01'), t('2022-10-30 17:01')],
                      'dt_bu_recebido': [t('2022-10-30 18:05'), t('2022-10-30 17:00'), t('2022-10-31 09:05')],
                      'desloc_h': [2.0, 0.0, 0.0]})
    res, ext = C4.c4_13_atrasos(d, '2022-10-30')
    ac = res[res.uf == 'AC'].iloc[0]
    assert ac.p50 == pytest.approx(60.0)                        # 18:05 - (15:05 + 2h)
    sp = res[res.uf == 'SP'].iloc[0]
    assert sp.recebido_antes_emissao == 1 and sp.recebido_dia_seguinte == 1
    assert len(ext) == 2 and res[res.uf == 'TOTAL'].iloc[0].secoes == 3


def test_c4_14_exterior_2026():
    nomes = pd.DataFrame({'uf': ['ZZ'], 'municipality': [29000], 'municipio': ['LISBOA']})
    g = C4.c4_14_exterior_2026(_sec2026(), nomes)
    assert len(g) == 1 and g.iloc[0].municipio == 'LISBOA' and g.iloc[0].t2_validos == 40 and g.iloc[0].status.startswith('NOT_COMPARABLE')
