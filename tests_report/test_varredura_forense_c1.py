"""Testes das funções puras de scripts/varredura_forense_c1.py (camada C1 da varredura forense) com dados sintéticos
pequenos. Rodam no ambiente .venv-report, sem rede e sem research/ ou relatorios/."""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / 'scripts'))
C1 = pytest.importorskip('varredura_forense_c1')


# ------------------------------------------------------------------------------------------ nomes, stems e membros
def test_tipo_membro_e_chave_do_stem():
    assert C1.tipo_membro('o00407-1479600440104.logjez') == ('o00407-1479600440104', 'log')
    assert C1.tipo_membro('o00407-1479600440104.busa') == ('o00407-1479600440104', 'bu_sa')
    assert C1.tipo_membro('o00407-1479600440104.logsajez') == ('o00407-1479600440104', 'log_sa')
    assert C1.tipo_membro('o03220mg4123800390168-sa.vsc') == ('o03220mg4123800390168', 'assinatura_sa')
    assert C1.tipo_membro('o03220mg4123800390168-imgbusa.dat') == ('o03220mg4123800390168', 'imgbu_sa')
    assert C1.tipo_membro('o03221es5793200090085-vota.vsc') == ('o03221es5793200090085', 'assinatura')
    assert C1.tipo_membro('leiame.pdf')[1] == 'leiame'
    assert C1.tipo_membro('MG - Arquivos transmitidos para totalização - Primeiro turno')[1] == 'pasta'
    assert C1.tipo_membro('x.chvtp')[1] == 'outro'
    assert C1.chave_do_stem('o00407-1479600440104') == (None, 14796, 44, 104)
    assert C1.chave_do_stem('o03221es5793200090085') == ('ES', 57932, 9, 85)
    assert C1.chave_do_stem('abc') is None
    k = C1.chaves_de_stems(['o00406-0000100020003', 'xyz'], 'AC')
    assert k.chave_ok.tolist() == [True, False] and k.uf.tolist() == ['AC', 'AC'] and int(k.section[0]) == 3


def test_classifica_membros_sa_e_incompletos():
    nomes = ['leiame.pdf', 'a.bu', 'a.imgbu', 'a.logjez', 'a.rdv', 'a.vscmr',
             'b.busa', 'b.imgbusa', 'b.logsajez', 'b.rdv', 'b.vscsa',
             'c.bu', 'c.imgbu', 'c.rdv', 'c.vscmr', 'pasta', 'z.chvtp']
    m = C1.classifica_membros(nomes).set_index('stem')
    assert m.loc['a', 'padrao_completo'] and not m.loc['a', 'tem_sa']
    assert m.loc['b', 'tem_sa'] and not m.loc['b', 'tem_bu'] and m.loc['b', 'tem_rdv'] and m.loc['b', 'tipos'] == 'assinatura_sa;bu_sa;imgbu_sa;log_sa;rdv'
    assert not m.loc['c', 'padrao_completo'] and not m.loc['c', 'tem_log'] and not m.loc['c', 'tem_sa']
    assert sorted(t for _, t in m.attrs['extras']) == ['leiame', 'outro', 'pasta']


# ------------------------------------------------------------------------------------------ C1-01: cobertura e diferenças
def test_diferencas_chaves_e_tabela_cobertura():
    a = pd.DataFrame({'uf': ['AC', 'AC', 'AC'], 'municipality': [1, 1, 2], 'zone': [1, 1, 1], 'section': [1, 2, 3]})
    b = pd.DataFrame({'uf': ['AC', 'AC'], 'municipality': pd.array([1, 2], dtype='Int64'), 'zone': pd.array([1, 1], dtype='Int64'),
                      'section': pd.array([2, 9], dtype='Int64')})
    d = C1.diferencas_chaves(a, b, 'ref', 'bu')
    assert sorted(d.lado.tolist()) == ['so_em_bu', 'so_em_ref', 'so_em_ref']
    assert set(d[d.lado == 'so_em_bu'].section) == {9}
    s = C1.diferencas_chaves(pd.DataFrame({'uf': ['AC'], 'stem': ['x']}), pd.DataFrame({'uf': ['AC'], 'stem': ['y']}),
                             'a', 'b', chave=['uf', 'stem'])
    assert len(s) == 2
    longa = pd.DataFrame([{'pleito': '2022-t2', 'uf': 'AC', 'familia': 'secoes_ref', 'n': 100},
                          {'pleito': '2022-t2', 'uf': 'AC', 'familia': 'bu_hd', 'n': 99},
                          {'pleito': '2022-t2', 'uf': 'AC', 'familia': 'bu_zip', 'n': 99},
                          {'pleito': '2022-t2', 'uf': 'AC', 'familia': 'log_usado', 'n': 98}])
    w = C1.tabela_cobertura(longa)
    assert len(w) == 1 and abs(w.r_bu_hd_x_secoes[0] - 0.99) < 1e-9 and abs(w.r_log_usado_x_bu_hd[0] - 98 / 99) < 1e-9
    assert pd.isna(w.r_assinatura_hd_x_bu_zip[0])


# ------------------------------------------------------------------------------------------ C1-02 / C1-10: outros
def test_decompoe_outros():
    assert C1.decompoe_outros(117, 1310, 1281, 4) == {'leiame': 1, 'stems_sem_bu': 29, 'sa_esperados': 116, 'residuo': 0}
    assert C1.decompoe_outros(16, 103656, 103656, 3)['residuo'] == 15
    assert pd.isna(C1.decompoe_outros(float("nan"), 10, 10)["residuo"]) and pd.isna(C1.decompoe_outros(5, float("nan"), 1)["stems_sem_bu"])


# ------------------------------------------------------------------------------------------ C1-06: layouts e scripts
def test_diff_layout_e_fingerprint():
    a = ['A', 'DS_AGREGADAS', 'QT_ELEITORES_BIOMETRIA_NH', 'X']
    b = ['A', 'DS_SECOES_AGREGADAS', 'QT_ELEI_BIOM_SEM_HABILITACAO', 'Y']
    d = C1.diff_layout(a, b)
    assert d['adicionadas'] == ['Y'] and d['removidas'] == ['X'] and not d['ordem_igual']
    assert d['renomeadas'] == ['QT_ELEITORES_BIOMETRIA_NH->QT_ELEI_BIOM_SEM_HABILITACAO', 'DS_AGREGADAS->DS_SECOES_AGREGADAS']
    assert C1.diff_layout(a, a) == {'adicionadas': [], 'removidas': [], 'renomeadas': [], 'ordem_igual': True}
    assert C1.fingerprint(a) != C1.fingerprint(b) and len(C1.fingerprint(a)) == 12
    assert C1.classifica_uso_coluna("x = 'DS_AGREGADAS' if ano == 2022 else 'DS_SECOES_AGREGADAS'", 'DS_AGREGADAS', 'DS_SECOES_AGREGADAS') == 'trata ambos'
    assert C1.classifica_uso_coluna("extra = ['QT_ELEITORES_BIOMETRIA_NH']", 'QT_ELEITORES_BIOMETRIA_NH', 'QT_ELEI_BIOM_SEM_HABILITACAO') == 'só antiga'
    assert C1.classifica_uso_coluna('nada', 'A', 'B') == 'não usa'


# ------------------------------------------------------------------------------------------ C1-13 / C1-14
def test_classifica_prova_e_secao_em_agregadas():
    assert C1.classifica_prova('bu', 'APURADA', 'Sistema de apuração', '**', True).startswith('membros SA')
    assert 'origem do voto' in C1.classifica_prova('log', 'APURADA', 'Sistema de apuração', None, False)
    assert 'divergência' in C1.classifica_prova('log', 'APURADA', 'Urna Eletrônica', '**', False)
    assert 'não explicada' in C1.classifica_prova('rdv', 'APURADA', 'Urna Eletrônica', '#NULO#', False)
    assert 'NOT_COMPARABLE' in C1.classifica_prova('rdv', None, None, None, None)
    assert C1.secao_em_agregadas('12', 12) and C1.secao_em_agregadas('0012, 15', 15) and not C1.secao_em_agregadas('#NULO#', 1)
    assert not C1.secao_em_agregadas('120', 12)


def test_compara_cargos():
    pres = pd.DataFrame({'uf': ['MA', 'MA'], 'municipality': [1, 1], 'zone': [1, 1], 'section': [1, 2],
                         'aptos': [366, 300], 'comparecimento': [314, 250], 'abstencoes': [52, 50]})
    gov = pd.DataFrame({'uf': ['MA', 'MA'], 'municipality': [1, 1], 'zone': [1, 1], 'section': [1, 2],
                        'aptos': [356, 300], 'comparecimento': [304, 250], 'abstencoes': [52, 50]})
    m = C1.compara_cargos(pres, gov)
    assert m.difere.tolist() == [True, False] and int(m.dif_aptos[0]) == 10 and int(m.dif_comparecimento[0]) == 10


# ------------------------------------------------------------------------------------------ leitores leves (cs.json, download.log)
def test_ler_cs_json_e_download_log(tmp_path):
    cs = {'abr': [{'cd': 'ac', 'mu': [{'cd': '01074', 'nm': 'X', 'zon': [{'cd': '0004', 'sec': [
        {'ns': '0001', 'da': '25/10/2026', 'ha': '21:26:45'}, {'ns': '0005', 'nsp': '0001'}]}]}]}]}
    p = tmp_path / 'AC-cs.json'
    p.write_text(json.dumps(cs), encoding='utf-8')
    df = C1.ler_cs_json(p, 'ac')
    assert len(df) == 2 and df.uf.tolist() == ['AC', 'AC'] and df.agregada.tolist() == [False, True]
    assert df.recebido_em[0] == '25/10/2026 21:26:45' and int(df.municipality[0]) == 1074
    log = tmp_path / 'download.log'
    log.write_text('2026-t2 AC completo: urnas 2270 blocos pendentes 0\n2026-t2 AC completo CONCLUIDO erros 0\n'
                   '2022-t1 BA so_bu CONCLUIDO erros 2\n', encoding='utf-8')
    orig = C1.DOWNLOAD_LOG
    C1.DOWNLOAD_LOG = log
    try:
        d = C1.download_concluido()
    finally:
        C1.DOWNLOAD_LOG = orig
    assert d.to_dict('records') == [{'pleito': '2026-t2', 'uf': 'AC', 'modo': 'completo', 'erros': 0},
                                    {'pleito': '2022-t1', 'uf': 'BA', 'modo': 'so_bu', 'erros': 2}]


def test_membros_inventario_local_regex(tmp_path, monkeypatch):
    raiz = tmp_path / 'estados' / 'SP' / '2022-t2'
    raiz.mkdir(parents=True)
    inv = [{'resource': {'name': 'SP - Arquivos transmitidos - Segundo turno', 'url': 'x'}, 'container_bytes': 1,
            'members': [{'name': 'o00407-1.bu', 'bytes': 1, 'compressed': 1}, {'name': 'leiame.pdf', 'bytes': 2, 'compressed': 2}]}]
    (raiz / 'remote-inventory.json').write_text(json.dumps(inv, indent=2), encoding='utf-8')
    monkeypatch.setattr(C1, 'R', tmp_path)
    assert C1.membros_inventario_local('2022-t2', 'SP') == ['o00407-1.bu', 'leiame.pdf']
    assert C1.membros_inventario_local('2022-t2', 'AC') is None


def test_divergencia_e_agregadas():
    assert C1.divergencia_marcada('**') and C1.divergencia_marcada('C') and C1.divergencia_marcada(' * ')
    assert not C1.divergencia_marcada('#NULO#') and not C1.divergencia_marcada(None)
    assert not C1.divergencia_marcada(float('nan'))
    bw = pd.DataFrame({'uf': ['SP', 'SP', 'SP'], 'municipality': [1, 1, 2], 'zone': [5, 5, 5], 'section': [10, 11, 10],
                       'agregadas': ['0012, 0013', None, '14']})
    ch = pd.DataFrame({'municipality': [1, 1, 2, 1], 'zone': [5, 5, 5, 6], 'section': [12, 14, 14, 13]})
    assert C1.marca_agregadas(bw, ch).tolist() == [True, False, True, False]


def test_download_log_ja_concluido(tmp_path, monkeypatch):
    log = tmp_path / 'download.log'
    linhas = ['2022-t1 RR completo JA CONCLUIDO', '2022-t1 RR completo JA CONCLUIDO', '2022-t1 AC completo JA CONCLUIDO',
              '2022-t1 AC completo CONCLUIDO erros 0']
    log.write_text('\n'.join(linhas) + '\n', encoding='utf-8')
    monkeypatch.setattr(C1, 'DOWNLOAD_LOG', log)
    d = C1.download_concluido().set_index('uf')
    assert len(d) == 2 and d.loc['AC', 'erros'] == 0 and pd.isna(d.loc['RR', 'erros'])


def test_i0():
    assert C1.i0(3.0) == 3 and C1.i0(float('nan')) is None
