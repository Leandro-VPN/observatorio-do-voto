"""Testes da passada de BUs binários (scripts/varredura_forense_bu.py) com BUs sintéticos codificados em BER pelo
codificador deste arquivo, nos dois formatos (2022 e 2024/2026), e com os invariantes. Sem rede, sem research/ nem relatorios/.
Rodar com --basetemp=F:/votos/build/pytest_tmp_vfbu."""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
V = pytest.importorskip('varredura_forense_bu')


# ------------------------------------------------------------------ codificador BER mínimo
def tlv(tag, content):
    n = len(content)
    ln = bytes([n]) if n < 128 else (b'\x81' + bytes([n]) if n < 256 else b'\x82' + n.to_bytes(2, 'big'))
    return bytes([tag]) + ln + content


def integer(v, tag=0x02):
    n = max(1, (v.bit_length() + 8) // 8)
    return tlv(tag, v.to_bytes(n, 'big', signed=True))


def enum(v):
    return integer(v, 0x0a)


def gs(s):
    return tlv(0x1b, s.encode('latin1'))


def octet(b):
    return tlv(0x04, b)


def seq(*parts):
    return tlv(0x30, b''.join(parts))


def ctx(n, *parts):
    """[n] construído (IMPLICIT sobre SEQUENCE)."""
    return tlv(0xa0 | n, b''.join(parts))


def ctxp(n, v):
    """[n] primitivo com INTEGER/ENUM implícito."""
    return integer(v, 0x80 | n)


def ident_secao(mun, zona, local, secao):
    return ctx(0, seq(integer(mun), integer(zona)), integer(local), integer(secao))


def votavel(tipo, qtd, numero=None, partido=None, novo=False, ordem=1):
    partes = [ctxp(1, tipo), ctxp(2, qtd)]
    if numero is not None:
        partes.append(ctx(3, integer(partido if partido is not None else int(str(numero)[:2])), integer(numero)))
    if novo:
        partes.append(integer(ordem))
    partes.append(octet(b'\x5a' * 64))
    return seq(*partes)


def cargo(cod, ordem, votos, branco, nulo, legenda=None, novo=False, livre=False):
    vs = [votavel(1, q, n, novo=novo, ordem=i + 1) for i, (n, q) in enumerate(votos.items())]
    for p, q in (legenda or {}).items():
        vs.append(votavel(4, q, p, p, novo=novo))
    vs += [votavel(2, branco, novo=novo), votavel(3, nulo, novo=novo)]
    return seq(ctxp(2 if livre else 1, cod), integer(ordem), seq(*vs))


def eleicao(eid, aptos, comp, cargos, novo=False, int2=None, int3=None, tipo_cargo=1):
    """cargos: lista de bytes de TotalVotosCargo (todos com o mesmo comparecimento neste helper)."""
    partes = [integer(eid), integer(aptos)]
    if novo:
        partes += [integer(aptos if int2 is None else int2), integer(0 if int3 is None else int3)]
    partes.append(seq(seq(enum(tipo_cargo), integer(comp), seq(*cargos))))
    if novo:
        partes += [octet(b'\x11' * 64), octet(b'\x22' * 132)]
    return seq(*partes)


def urna(tipo_urna=1, versao='8.26.0.0 - Onça-pintada', mun=1015, zona=2, secao=88, interno=1031727, fc=b'\x26\x8d\x23\xee',
         data_carga='20220922T150200', codigo='552077994049280709935409', novo=False, contingencia=False):
    carga = [integer(interno), octet(fc)]
    if novo:
        carga.append(seq(gs('ZAC001STD29'), gs('6F4108493CC3D22AB9B7'), gs('FF1FE3B5')))
    carga += [gs(data_carga), gs(codigo)]
    idn = ctx(1, seq(integer(mun), integer(zona))) if contingencia else ident_secao(mun, zona, 1, secao)
    return seq(enum(tipo_urna), gs(versao), seq(idn, seq(*carga)), enum(1), octet(b'\x5a\x98\x48\x6f'))


def bu(novo=False, mun=1015, zona=2, local=1112, secao=88, aptos=196, comp=139, votos=None, branco=1, nulo=1, lib=25, bio=133,
       hab=(8, 117, 14), eid=545, pleito=407, cargos=None, env_secao=None, abertura='20221030T060836',
       encerramento='20221030T150726', emissao='20221030T150939', geracao='20221030T151014', data_carga='20220922T150200',
       codigo='552077994049280709935409', trailer=None, tipo_urna=1, contingencia=False, int2=None, int3=None,
       historico=False, fase=2, extra=None):
    votos = {13: 53, 22: 84} if votos is None else votos
    if cargos is None:
        cargos = [cargo(1, 1, votos, branco, nulo, novo=novo)]
    cab = seq(gs(geracao), ctxp(2, pleito))
    campos = [cab, enum(fase), urna(tipo_urna, novo=novo, mun=mun, zona=zona, secao=secao, data_carga=data_carga, codigo=codigo,
                                   contingencia=contingencia),
              seq(seq(integer(mun), integer(zona)), integer(local), integer(secao)), gs(emissao), ctx(0, gs(abertura), gs(encerramento))]
    if novo:
        campos += [integer(comp), ctx(1, *[integer(h) for h in hab]),
                   seq(eleicao(eid, aptos, comp, cargos, novo=True, int2=int2, int3=int3))]
        campos.append(seq(*[gs(c) for c in (trailer or [codigo])]))
    else:
        campos += [ctxp(1, lib), ctxp(2, bio), ctx(3, eleicao(eid, aptos, comp, cargos))]
        if historico:
            campos.append(ctx(4, seq(ident_secao(mun, zona, 1, 71), seq(integer(1103911), octet(b'\x26\x8d\x23\xee'),
                                                                        gs('20220922T114600'), gs('501572107644433923141321')))))
        campos.append(octet(b'\x00' * 32))
    if extra is not None:
        campos.append(extra)
    conteudo = seq(*campos)
    es = env_secao or (mun, zona, local, secao)
    return seq(cab, enum(fase), ident_secao(*es), enum(1), octet(conteudo))


STEM22 = 'o00407-0101500020088'
STEM26 = 'o03221ac0101500020088'


# ------------------------------------------------------------------ testes
def test_ber_tree_e_stem():
    t = V.ber_tree(seq(integer(300), gs('x'), ctx(0, integer(-1))))
    assert t[0][0] == 0 and t[0][1] == 16 and V._int(t[0][2][0]) == 300 and V._str(t[0][2][1]) == 'x'
    assert t[0][2][2][0] == 2 and V._int(t[0][2][2][2][0]) == -1
    with pytest.raises(ValueError):
        V.ber_tree(b'\x30\x05\x02\x01')          # TLV ultrapassa o pai
    assert V.analisa_stem(STEM22) == {'stem_fase': 'o', 'stem_pleito': 407, 'stem_uf': None, 'stem_municipio': 1015,
                                      'stem_zona': 2, 'stem_secao': 88}
    assert V.analisa_stem(STEM26)['stem_uf'] == 'AC' and V.analisa_stem('lixo')['stem_municipio'] is None


def test_decodifica_formato_2022():
    raw = bu(historico=True)
    d = V.decodifica_bu(raw)
    assert d['env_id'] == 407 and d['env_tipo_envelope'] == 1 and d['bu_fase'] == 2
    assert d['tipo_urna'] == 1 and d['versao_votacao'] == '8.26.0.0 - Onça-pintada' and d['tipo_arquivo'] == 1
    assert d['numero_interno_urna'] == 1031727 and d['numero_serie_fc'] == '268d23ee' and d['numero_serie_fv'] == '5a98486f'
    assert d['data_hora_carga'] == '20220922T150200' and d['codigo_carga'] == '552077994049280709935409'
    assert d['carga_extra'] is None and d['comparecimento_bu'] is None and d['hab_lista'] is None
    assert d['hab_lib_codigo'] == 25 and d['hab_comp_biometrico'] == 133
    assert (d['municipality'], d['zone'], d['voting_place'], d['section']) == (1015, 2, 1112, 88)
    assert d['data_hora_abertura'] == '20221030T060836' and d['data_hora_encerramento'] == '20221030T150726'
    assert d['eleicoes_tag'] == 'C3' and len(d['eleicoes']) == 1 and d['chave_assinatura'] == '00' * 32
    assert d['historico_correspondencias'][0]['codigo_carga'] == '501572107644433923141321'
    e = d['eleicoes'][0]
    assert e['id'] == 545 and e['aptos'] == 196 and e['aptos_int2'] is None
    c = e['cargos'][0]
    assert c['cargo'] == 1 and c['comparecimento'] == 139 and c['votaveis'] == {13: 53, 22: 84}
    assert c['nominal'] == 137 and c['branco'] == 1 and c['nulo'] == 1 and c['dif_soma'] == 0
    assert d['extras'] == []
    r = V.achata(d, STEM22, 'AC', 'x.bu', {1: {13, 22}}, raw)
    assert r['inv_id_stem_bu'] and r['inv_id_env_bu'] and r['inv_corresp_secao'] and r['inv_cargos_soma']
    assert r['inv_hab_soma_comp'] is None and r['inv_comp_bu_cargo'] is None and r['inv_aptos_int'] is None
    assert r['inv_trailer_carga'] is None and r['inv_cronologia'] and r['inv_lista'] and r['inv_sem_extras']
    assert r['e545_c1_votaveis'] == '{"13":53,"22":84}' and r['e545_faltas_calc'] == 57 and r['n_correspondencias'] == 1
    assert r['cargos'] == 'e545_c1' and r['lista_status'] == 'completa: ok' and r['bu_bytes'] == len(raw)


def test_decodifica_formato_2024_2026():
    raw = bu(novo=True, eid=6258, pleito=3221, comp=139, hab=(8, 117, 14), int2=195, int3=1,
             cargos=[cargo(13, 1, {10000: 65, 11127: 67}, 1, 1, legenda={15: 4, 22: 1}, novo=True),
                     cargo(11, 2, {15: 57, 44: 78}, 2, 2, novo=True)], aptos=196)
    d = V.decodifica_bu(raw)
    assert d['carga_extra'] == ['ZAC001STD29', '6F4108493CC3D22AB9B7', 'FF1FE3B5'] and d['comparecimento_bu'] == 139
    assert d['hab_lista'] == [8, 117, 14] and d['hab_lib_codigo'] is None and d['eleicoes_tag'] == 'U16'
    assert d['trailer_cargas'] == ['552077994049280709935409'] and d['chave_assinatura'] is None
    e = d['eleicoes'][0]
    assert (e['aptos'], e['aptos_int2'], e['aptos_int3'], e['trailer_octets']) == (196, 195, 1, [64, 132])
    c13 = next(c for c in e['cargos'] if c['cargo'] == 13)
    assert c13['legenda'] == 5 and c13['legenda_partidos'] == {15: 4, 22: 1} and c13['nominal'] == 132 and c13['n_votaveis'] == 6
    r = V.achata(d, STEM26, 'AC', 'x-bu.dat', {}, raw)
    assert r['hab_0'] == 8 and r['hab_2'] == 14 and r['hab_soma'] == 139 and r['inv_hab_soma_comp'] is True
    assert r['inv_comp_bu_cargo'] is True and r['inv_aptos_int'] is True and r['inv_trailer_carga'] is True
    assert r['modelo_carga'] == 'ZAC001STD29' and r['cargos'] == 'e6258_c13,e6258_c11' and r['cargos_set'] == 'e6258_c11,e6258_c13'
    assert r['e6258_c13_legenda_partidos'] == '{"15":4,"22":1}' and r['e6258_c13_lista'] == 'sem lista'
    assert r['lista_status'] == 'sem lista' and r['inv_lista'] is None and r['inv_cargos_unicos'] and r['inv_numeros_unicos']
    # comparecimento do cargo 13 = comparecimento do cargo 11 neste helper -> soma por cargo confere nos dois
    assert r['inv_cargos_soma'] is True and r['e6258_c13_dif_soma'] == 0


def test_invariantes_falham_e_diferencas():
    # comparecimento acima dos aptos; soma do cargo diferente; hab diferente; stem e envelope divergentes; número fora da lista
    raw = bu(novo=True, eid=6258, pleito=3221, aptos=100, comp=139, hab=(8, 117, 10), int2=99, int3=0, votos={13: 53, 23: 84},
             env_secao=(1015, 2, 1112, 89), trailer=['111', '222'], abertura='20221030T160000')
    r = V.achata(V.decodifica_bu(raw), 'o03221ac0101500020087', 'AC', 'x', {1: {13, 22}}, raw)
    assert r['inv_aptos_comp'] is False and r['aptos_comp_dif_min'] == -39
    assert r['inv_hab_soma_comp'] is False and r['hab_comp_dif'] == -4
    assert r['inv_id_stem_bu'] is False and '87' in r['id_stem_bu_dif']
    assert r['inv_id_env_bu'] is False and r['id_env_bu_dif']
    assert r['inv_lista'] is False and json.loads(r['numeros_fora_lista']) == {'e6258_c1': [23]} and r['e6258_c1_fora_lista'] == '[23]'
    assert r['inv_aptos_int'] is False and r['inv_trailer_carga'] is False
    assert r['inv_cronologia'] is False and r['cronologia_dif'] == 'abertura>encerramento'
    # soma por cargo errada e cargo duplicado
    raw2 = bu(cargos=[cargo(1, 1, {13: 53, 22: 84}, 1, 1), cargo(1, 2, {13: 10, 22: 10}, 0, 0)])
    r2 = V.achata(V.decodifica_bu(raw2), STEM22, 'AC', 'x', None, raw2)
    assert r2['inv_cargos_unicos'] is False and r2['cargos_duplicados_lista'] == 'e545_c1' and r2['cargos_duplicados']
    assert r2['inv_cargos_soma'] is False and json.loads(r2['cargos_soma_dif']) == {'e545_c1': -119}
    # campo não reconhecido vai para extras
    raw3 = bu(extra=tlv(0x87, b'\x01'))
    r3 = V.achata(V.decodifica_bu(raw3), STEM22, 'AC', 'x', None, raw3)
    assert r3['inv_sem_extras'] is False and 'C7' in r3['extras']
    # partido incoerente com o número e número repetido
    raw4 = bu(cargos=[seq(ctxp(1, 1), integer(1), seq(votavel(1, 5, 13, partido=22), votavel(1, 6, 13), votavel(2, 1), votavel(3, 1)))],
              comp=13)
    r4 = V.achata(V.decodifica_bu(raw4), STEM22, 'AC', 'x', None, raw4)
    assert r4['inv_partido_numero'] is False and r4['inv_numeros_unicos'] is False and r4['e545_c1_votaveis'] == '{"13":11}'


def test_contingencia_e_sa():
    raw = bu(novo=True, eid=6258, pleito=3221, tipo_urna=4, contingencia=True, trailer=['259', '552077994049280709935409'])
    r = V.achata(V.decodifica_bu(raw), STEM26, 'AC', 'x', None, raw)
    assert r['tipo_urna_ds'] == 'reservaSecao' and r['corresp_tipo'] == 'contingencia' and r['inv_corresp_secao'] is True
    assert r['n_trailer_cargas'] == 2 and r['inv_trailer_carga'] is True
    # correspondência de outro município -> inv_corresp_secao False
    raw2 = bu()
    d2 = V.decodifica_bu(raw2)
    d2['corresp_municipio'] = 9999
    assert V.achata(d2, STEM22, 'AC', 'x', None, raw2)['inv_corresp_secao'] is False


def test_erro_de_decodificacao_vira_linha():
    r = V.linha_bu(STEM22, 'x.bu', b'\x30\x03\x02\x01', 'AC')
    assert r['erro'] and r['stem_municipio'] == 1015 and r['uf'] == 'AC'
    r = V.linha_bu(STEM22, 'x.bu', seq(integer(1)), 'AC')
    assert 'conteudo' in r['erro']


def test_tabela_tipos_e_colunas_base():
    raws = [bu(), bu(novo=True, eid=6258, pleito=3221)]
    df = V.tabela([V.linha_bu(STEM22, 'a', raws[0], 'AC', {1: {13, 22}}), V.linha_bu(STEM26, 'b', raws[1], 'AC'),
                   V.linha_bu(STEM22, 'c', b'\x00', 'AC')])
    assert list(df.columns[:len(V.COLUNAS_BASE)]) == list(V.COLUNAS_BASE)
    assert str(df['inv_hab_soma_comp'].dtype) == 'boolean' and str(df['e6258_c1_nominal'].dtype) == 'Int64'
    assert str(df['e545_c1_votaveis'].dtype) == 'string' and df['erro'].notna().sum() == 1
    assert df['inv_hab_soma_comp'].tolist()[0] is pd.NA and df['inv_hab_soma_comp'].tolist()[1] is True


def test_quarentena_e_cargos_esperados():
    df = pd.DataFrame({'uf': ['AC'] * 4, 'stem': ['a', 'b', 'c', 'd'], 'municipality': [1, 1, 1, 1], 'zone': [1, 1, 1, 1],
                       'section': [1, 2, 3, 4], 'erro': [None, None, 'ValueError: x', None],
                       'cargos_set': ['e1_c1,e1_c3', 'e1_c1,e1_c3', None, 'e1_c1'],
                       'inv_cargos_soma': pd.array([True, False, None, True], dtype='boolean'),
                       'cargos_soma_dif': [None, '{"e1_c1":-2}', None, None], 'e1_c1_comparecimento': [10, 10, None, 10]})
    esp = V.cargos_esperados(df)
    assert esp.cargos_esperados.tolist() == ['e1_c1,e1_c3'] * 4
    assert [None if pd.isna(x) else x for x in esp.cargos_faltando] == [None, None, 'e1_c1,e1_c3', 'e1_c3']
    assert [None if pd.isna(x) else x for x in esp.cargos_extras] == [None] * 4
    assert esp.inv_cargos_esperados.tolist()[0] is True and esp.inv_cargos_esperados.tolist()[3] is False
    assert esp.inv_cargos_esperados.tolist()[2] is pd.NA
    cv = V._colunas_valores(list(df.columns), 'inv_cargos_soma')
    assert set(cv) == {'cargos_soma_dif', 'e1_c1_comparecimento'}
    q = V.linhas_quarentena(df, 'inv_cargos_soma', '2026-t2', cv)
    assert len(q) == 1 and q[0]['stem'] == 'b' and q[0]['valores']['cargos_soma_dif'] == '{"e1_c1":-2}' and q[0]['reason']
    qe = V.linhas_quarentena(df, 'erro', '2026-t2', ['erro'])
    assert len(qe) == 1 and qe[0]['checagem'] == 'erro' and qe[0]['section'] == 3


def test_compara_decodificados_entre_canais():
    a = bu(novo=True, eid=6258, pleito=3221)
    b = bu(novo=True, eid=6258, pleito=3221, votos={13: 54, 22: 83})
    assert V.compara_decodificados(a, a) == {}
    dif = V.compara_decodificados(a, b, 'AC', STEM26)
    assert dif['e6258_c1_votaveis'] == ['{"13":53,"22":84}', '{"13":54,"22":83}'] and 'e6258_c1_nominal' not in dif
    assert V.stem_2026t2('BA', '30058', '1', '12') == 'o03221ba3005800010012'
