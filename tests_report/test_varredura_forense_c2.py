"""Testes das funções puras de scripts/varredura_forense_c2.py (camada C2 da varredura forense) com dados sintéticos
pequenos. Rodam no ambiente .venv-report, sem rede e sem research/ ou relatorios/."""
import io
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / 'scripts'))
C2 = pytest.importorskip('varredura_forense_c2')


def _zip(membros):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for nome, dados in membros:
            z.writestr(nome, dados)
    return buf.getvalue()


def _log(inicio, serial, secao, votos, dia='25/10/2026'):
    linhas = [f'{inicio}\tINFO\t{serial}\tLOGD\tInício das operações do logd\tABCD',
              f'{inicio}\tINFO\t{serial}\tGAP\tSeção Eleitoral: {secao:04d}\tABCD']
    for h in votos:
        linhas.append(f'{dia} {h}\tINFO\t{serial}\tVOTA\tVoto confirmado para [Presidente]\tABCD')
        linhas.append(f'{dia} {h}\tINFO\t{serial}\tVOTA\tO voto do eleitor foi computado\tABCD')
    return ('\n'.join(linhas) + '\n').encode('latin-1')


# ------------------------------------------------------------------------------------------ chaves e nomes
def test_stem_e_chave_2022_e_2026():
    assert C2.stem_de('o00407-1479600440104.logjez') == 'o00407-1479600440104'
    assert C2.stem_de('o03221es5793200090085-log.jez') == 'o03221es5793200090085'
    assert C2.stem_de('o03221es5793200090085-vota.vsc') == 'o03221es5793200090085'
    assert C2.chave_do_stem('o00407-1479600440104') == (None, 14796, 44, 104)
    assert C2.chave_do_stem('o03221es5793200090085') == ('ES', 57932, 9, 85)
    assert C2.stem_2026t2('ES', 57932, 9, 85) == 'o03221es5793200090085'
    assert C2.tipo_de('x.logjez') == 'log' and C2.tipo_de('x-bu.dat') == 'bu' and C2.tipo_de('x.vscmr') == 'assinatura'
    with pytest.raises(ValueError):
        C2.chave_do_stem('abc')


# ------------------------------------------------------------------------------------------ C2-01 / C2-09: pacotes
def test_membros_pacote_aninhado_e_fatos_do_log():
    urna_a = _log('04/10/2026 07:00:00', '01841837', 85, ['08:10:00', '08:20:00', '09:00:00'])
    urna_b = _log('04/10/2026 07:00:00', '01750820', 112, ['08:30:00'])
    cont = _log('25/10/2026 19:00:00', '01758779', 0, [])
    pacote = _zip([('0175877925102026ME.jez', _zip([('logd.dat', urna_a)])),
                   ('0175877925102026-02.jez', _zip([('logd.dat', urna_b)])), ('logd.dat', cont)])
    m = C2.membros_pacote(pacote)
    tipos = [(d, t) for d, _, t, _ in m]
    assert tipos == [(0, 'pacote'), (1, 'logd'), (0, 'pacote'), (1, 'logd'), (0, 'logd')]
    f = C2.fatos_log(m[1][3], {'t2': '25/10/2026', 't1': '04/10/2026'})
    assert f['serial'] == '01841837' and f['secoes_declaradas'] == '85' and f['votos_t2'] == 3 and f['votos_t1'] == 0
    assert f['linhas'] == 8 and len(f['sha512_16']) == 16
    assert C2.fatos_log(m[4][3], {'t2': '25/10/2026'})['secoes_declaradas'] == '0'


def test_sequencia_apos_ultimo_computado_e_classificacao_c2_01():
    texto = _log('25/10/2026 07:00:00', '01', 1, ['08:10:00']).decode('latin-1') + \
        '25/10/2026 16:44:41\tINFO\t01\tVOTA\tVoto confirmado para [Presidente]\tX\n' \
        '25/10/2026 16:44:45\tALERTA\t01\tVOTA\tBateria em nível crítico 123456789012\tX\n'
    seq = C2.sequencia_apos_ultimo_computado(texto, '25/10/2026')
    assert [s['mensagem'] for s in seq] == ['O voto do eleitor foi computado', 'Voto confirmado para [Presidente]',
                                            'Bateria em nível crítico #']
    assert C2.sequencia_apos_ultimo_computado('sem votos', '25/10/2026') == []
    # (bu, releitura, leitor antigo, n_logd, contingência, arquivo, órfãos, duplicados, outra seção)
    assert C2.classifica_caso_c2_01(234, 233, 233, 1, False, True, 1, 0, 0)[1] == 'EXPLICADO'
    assert C2.classifica_caso_c2_01(308, 308, 612, 3, True, True, 0, 0, 1)[1] == 'ARTEFATO'
    assert 'outra seção' in C2.classifica_caso_c2_01(308, 308, 612, 3, True, True, 0, 0, 1)[0]
    assert 'duas exportações' in C2.classifica_caso_c2_01(228, 228, 413, 3, True, True, 0, 1, 0)[0]
    assert C2.classifica_caso_c2_01(224, 188, 188, 2, True, True, 0, 0, 1)[1] == 'NAO_TESTAVEL'
    assert C2.classifica_caso_c2_01(268, None, None, None, None, False, 0, 0, 0)[1] == 'NAO_TESTAVEL'
    assert C2.classifica_caso_c2_01(200, 205, 205, 1, False, True, 0, 0, 0)[1] == 'INEXPLICADO'
    assert C2.classifica_caso_c2_01(200, 199, 199, 1, False, True, 0, 0, 0)[1] == 'INEXPLICADO'


def test_confirmados_sem_computado_no_meio_do_dia():
    base = _log('25/10/2026 07:00:00', '01', 1, ['08:10:00', '09:00:00']).decode('latin-1')
    linhas = base.splitlines()
    # voto das 08:30 confirmado, bateria cai, próximo eleitor habilitado sem o 'computado'
    extra = ['25/10/2026 08:30:00\tINFO\t01\tVOTA\tVoto confirmado para [Presidente]\tX',
             '25/10/2026 08:30:02\tALERTA\t01\tVOTA\tBateria em nível crítico\tX',
             '25/10/2026 08:40:00\tINFO\t01\tVOTA\tEleitor foi habilitado\tX']
    texto = '\n'.join(linhas[:4] + extra + linhas[4:]) + '\n'
    n_conf, n_comp, jan = C2.confirmados_sem_computado(texto, '25/10/2026')
    assert (n_conf, n_comp, len(jan)) == (3, 2, 1)
    assert [s['mensagem'] for s in jan[0]] == ['Voto confirmado para [Presidente]', 'Bateria em nível crítico']
    # dois cargos confirmados pelo mesmo eleitor antes de um único 'computado' não são órfãos
    t2 = '\n'.join(['25/10/2026 08:00:00\tINFO\t01\tVOTA\tVoto confirmado para [Presidente]\tX',
                    '25/10/2026 08:00:05\tINFO\t01\tVOTA\tVoto confirmado para [Consulta Popular]\tX',
                    '25/10/2026 08:00:06\tINFO\t01\tVOTA\tO voto do eleitor foi computado\tX'])
    assert C2.confirmados_sem_computado(t2, '25/10/2026') == (2, 1, [])
    assert C2.confirmados_sem_computado('', '25/10/2026') == (0, 0, [])


def test_votos_aninhados_delta_e_status():
    v1 = pd.DataFrame({'nome': ['a', 'b', 'c'], 'votos_log': [0, 100, 50]})
    v2 = pd.DataFrame({'nome': ['a', 'b', 'd'], 'votos_log': [250, 100, 7]})
    m = C2.votos_aninhados(v1, v2).set_index('nome')
    assert m.loc['a', 'delta'] == 250 and m.loc['a', 'status'] == 'votos só em log aninhado'
    assert m.loc['b', 'status'] == 'iguais' and m.loc['c', 'status'].startswith('NOT_COMPARABLE')
    assert m.loc['d', 'status'].startswith('NOT_COMPARABLE')


# ------------------------------------------------------------------------------------------ C2-07: manual log × BU
def _secoes():
    n = 12
    return pd.DataFrame({
        'eid': 'P2022', 'uf': 'SP', 'municipality': 1, 'zone': 1, 'section': range(1, n + 1),
        'member': ['m%d.logjez' % i for i in range(1, n)] + [None],
        'identity_status': ['PARSED'] * 9 + ['PARSED_FILENAME'] * 2 + [None],
        'vote_events': [300] * 8 + [290, 300, 120, np.nan], 'attendance': [300] * 12,
        'manual_sequence_votes': [40, 40, 41, 39, 40, 40, 45, 40, 30, 40, 10, np.nan],
        'manual_bu': [40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40],
        'manual_requests': [40, 40, 42, 39, 40, 40, 45, 40, 30, 40, 10, 0],
        'cancellations': [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        'manual_unattributed_votes': [0] * 12, 'swap': [False] * 12, 'red': [False] * 12, 'contingency': [False] * 12,
        'has_log': [True] * 11 + [False], 'log_complete': [True] * 8 + [False, True, False, False], 'eligible': 400,
        'aggregation_raw': ['#NULO#'] * 6 + ['7'] + ['#NULO#'] * 5, 'cert_emissor': ['AC URNA'] * 6 + ['AC UE2020'] * 6,
        'first_vote': '08:05:00', 'last_vote': '16:50:00', 'opening_bu': '02/10/2022 08:00:01',
        'closure_bu': '02/10/2022 17:01:00'})


def test_classifica_manual_e_resumo():
    d = C2.classifica_manual(_secoes())
    assert d['comparavel'].str.startswith('NOT_COMPARABLE').sum() == 1
    assert list(d['classe'].value_counts().sort_index().index) == ['contingência (identidade pelo nome)', 'limpa',
                                                                  'log ≠ BU em votos', 'não comparável', 'seção agregada']
    assert d['discorda'].sum() == 5                       # +1, −1, +5 (agregada), −10 (log incompleto), −30 (contingência)
    assert d.loc[8, 'd_igual_dif_votos'] and d.loc[8, 'd'] == -10 and d.loc[8, 'dif_votos'] == -10
    assert not d.loc[10, 'd_igual_dif_votos'] and d.loc[10, 'd'] == -30 and d.loc[10, 'dif_votos'] == -180
    r = C2.resumo_manual(d, ['eid', 'uf']).iloc[0]
    assert r['secoes'] == 12 and r['comparaveis'] == 11 and r['discordantes'] == 5
    assert r['limpa_n'] == 7 and r['limpa_discordantes'] == 2 and r['log_maior'] == 2 and r['log_menor'] == 3
    assert r['soma_d'] == 1 - 1 + 5 - 10 - 30 and abs(r['pct_limpa_discordantes'] - 100 * 2 / 7) < 1e-9
    assert r['manual_log'] == 405 and r['manual_bu'] == 440


def test_taxa_por_fator_e_histograma():
    d = C2.classifica_manual(_secoes())
    t = C2.taxa_por_fator(d, 'cancelamentos > 0', d['cancellations'] > 0).iloc[0]
    assert t['n_com'] == 1 and t['disc_com'] == 1 and t['pct_com'] == 100.0
    assert t['n_sem'] == 10 and t['disc_sem'] == 4 and abs(t['razao_de_taxas'] - 100 / 40) < 1e-9
    h = C2.histograma_d(d)
    assert h['secoes'].sum() == 5 and set(h['faixa_d']) == {'−1', '+1', '+2 a +10', '−10 a −2', '≤ −11'}


def test_relogio_log_x_bu_minutos_e_flags():
    d = _secoes()
    d.loc[0, 'last_vote'] = '17:03:30'          # último voto depois do encerramento do BU
    d.loc[1, 'first_vote'] = '07:58:01'         # primeiro voto antes da abertura
    r = C2.relogio_log_x_bu(d, '02/10/2022')
    assert abs(r.loc[0, 'min_enc_bu_menos_ultimo_voto'] + 2.5) < 1e-9 and r.loc[0, 'ultimo_voto_apos_encerramento_bu']
    assert abs(r.loc[2, 'min_enc_bu_menos_ultimo_voto'] - 11.0) < 1e-9 and not r.loc[2, 'ultimo_voto_apos_encerramento_bu']
    assert abs(r.loc[1, 'min_primeiro_voto_menos_abertura_bu'] + 2.0) < 1e-9 and r.loc[1, 'primeiro_voto_antes_da_abertura_bu']


# ------------------------------------------------------------------------------------------ C2-14: assinatura × BU
def test_assinatura_vs_bu_ordem_e_flags():
    d = pd.DataFrame({'assinado_em': ['20221002T171000', '20221002T165000', '20221003T001600', '20221002T190000', None],
                      'emissao_bu': pd.to_datetime(['2022-10-02 17:05:00'] * 5),
                      'encerramento': pd.to_datetime(['2022-10-02 17:03:00'] * 5),
                      'recebido_tse': pd.to_datetime(['2022-10-02 18:00:00'] * 5)})
    r = C2.assinatura_vs_bu(d, '02/10/2022')
    assert list(r['min_assin_apos_emissao'].round(1)[:4]) == [5.0, -15.0, 431.0, 115.0]
    assert list(r['assinou_antes_da_emissao'][:4]) == [False, True, False, False]
    assert list(r['assinou_antes_17h'][:4]) == [False, True, False, False]
    assert list(r['assinou_fora_do_dia'][:4]) == [False, False, True, False]
    assert list(r['assinou_depois_de_recebido'][:4]) == [False, False, True, True]
    assert r['assinado'].isna().iloc[4] and not r['assinou_fora_do_dia'].iloc[4]


# ------------------------------------------------------------------------------------------ C2-15: fase do erro
def test_fase_do_erro():
    ab, pv, uv, en = (pd.Timestamp(f'2024-10-27 {h}') for h in ('08:00:01', '08:05:00', '16:50:00', '17:02:00'))
    assert C2.fase_do_erro(pd.Timestamp('2024-10-27 07:30:00'), ab, pv, uv, en) == 'antes_da_abertura'
    assert C2.fase_do_erro(pd.Timestamp('2024-10-27 08:02:00'), ab, pv, uv, en) == 'entre_abertura_e_primeiro_voto'
    assert C2.fase_do_erro(pd.Timestamp('2024-10-27 12:00:00'), ab, pv, uv, en) == 'durante_votacao'
    assert C2.fase_do_erro(pd.Timestamp('2024-10-27 16:55:00'), ab, pv, uv, en) == 'entre_ultimo_voto_e_encerramento'
    assert C2.fase_do_erro(pd.Timestamp('2024-10-27 18:00:00'), ab, pv, uv, en) == 'depois_do_encerramento'
    assert C2.fase_do_erro(pd.NaT, ab, pv, uv, en) == 'indeterminado'


# ------------------------------------------------------------------------------------------ C2-12: inventário
def test_assimetrias_inventario_e_faltantes_por_tipo():
    inv = pd.DataFrame({'eleicao': ['2022-t1'] * 3, 'uf': ['AC', 'ZZ', 'XX'], 'status': ['ok', 'ok', '404'],
                        'urnas': [10, 14, 0], 'bu_arquivos': [10, 12, 0], 'log_arquivos': [10, 11, 0],
                        'rdv_arquivos': [10, 13, 0], 'assinatura_arquivos': [10, 12, 0]})
    a = C2.assimetrias_inventario(inv)
    assert list(a['uf']) == ['ZZ', 'XX']
    assert a.iloc[0][['log_menos_bu', 'rdv_menos_bu', 'assinatura_menos_bu', 'urnas_menos_bu']].tolist() == [-1, 1, 0, 2]
    nomes = ['o00406-0000100010001.bu', 'o00406-0000100010001.logjez', 'o00406-0000100010001.rdv', 'o00406-0000100010001.vscmr',
             'o00406-0000100010002.bu', 'o00406-0000100010002.rdv', 'o00406-0000100010002.vscmr',
             'o00406-0000100010003.rdv', 'o00406-0000100010004.busa', 'leia-me.pdf']
    f = C2.faltantes_por_tipo(nomes)
    assert f['log'] == ['o00406-0000100010002', 'o00406-0000100010003']
    assert f['bu'] == ['o00406-0000100010003'] and f['assinatura'] == ['o00406-0000100010003'] and f['rdv'] == []
    assert 'o00406-0000100010004' in f['_stems'] and 'o00406-0000100010004' not in f['bu']


# ------------------------------------------------------------------------------------------ manifesto (TLV)
def _der_seq(*filhos):
    corpo = b''.join(filhos)
    return b'\x30' + _len(len(corpo)) + corpo


def _len(n):
    return bytes([n]) if n < 128 else b'\x82' + n.to_bytes(2, 'big')


def _octets(b):
    return b'\x04' + _len(len(b)) + b


def test_blocos_manifesto_sintetico():
    # Mesma estrutura que parse_manifest percorre: top → bloco → [0] SEQ{SEQ{SEQ{nome, SEQ{alg, hash, sig}}…}}, [27] when,
    # e a identidade do assinante numa SEQ de 4 elementos cujo primeiro é SEQ{nome}.
    h1, h2 = bytes(range(64)), bytes(range(64, 128))

    def entrada(nome, h):
        return _der_seq(_octets(nome), _der_seq(_octets(b'sha512'), _octets(h), _octets(b'sig')))

    entradas = _octets(_der_seq(_der_seq(entrada(b'x-log.jez', h1), entrada(b'x-bu.dat', h2))))  # OCTET STRING com DER
    quando = b'\x9b' + _len(15) + b'20261025T171000'                                             # [27] 15 bytes
    ident = _der_seq(_der_seq(_octets(b'UEAO123')), _octets(b'a'), _octets(b'b'), _octets(b'c'))  # SEQ de 4, 1º = SEQ{nome}
    bloco = _der_seq(entradas, quando, ident)
    raw = _der_seq(bloco)
    bl = C2.blocos_manifesto(raw)
    assert len(bl) == 1 and bl[0]['user'] == 'UEAO123' and bl[0]['when'] == '20261025T171000'
    assert bl[0]['entries'] == {'x-log.jez': h1.hex(), 'x-bu.dat': h2.hex()}
    assert C2.bloco_hardware(bl) is bl[0] and C2.bloco_hardware([]) is None
