"""Testes das funções puras de scripts/varredura_forense_c3.py (camada C3, cronologia e processo da seção) com dados
sintéticos pequenos. Sem rede e sem research/ ou relatorios/. Rodar com --basetemp=F:/votos/build/pytest_tmp_c3."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
C3 = pytest.importorskip('varredura_forense_c3')


# ------------------------------------------------------------------------------------------ utilidades
def test_chave_do_stem_e_parse_dt():
    assert C3.chave_do_stem('o00407-1479600440104') == (None, 14796, 44, 104)
    assert C3.chave_do_stem('o03221es5793200090085') == ('ES', 57932, 9, 85)
    assert C3.stem_de('o03221es5793200090085-log.jez') == 'o03221es5793200090085'
    assert C3.stem_de('o00407-1479600440104.logjez') == 'o00407-1479600440104'
    with pytest.raises(ValueError):
        C3.chave_do_stem('xyz')
    s = pd.Series(['2022-10-02 08:00:01', '02/10/2022 17:01:05', '27/09/2022 08:18', '20221002T170417', None, 'lixo'])
    d = C3.parse_dt(s)
    assert d.iloc[0] == pd.Timestamp('2022-10-02 08:00:01')
    assert d.iloc[1] == pd.Timestamp('2022-10-02 17:01:05')
    assert d.iloc[2] == pd.Timestamp('2022-09-27 08:18:00')
    assert d.iloc[3] == pd.Timestamp('2022-10-02 17:04:17')
    assert d.iloc[4] is pd.NaT and d.iloc[5] is pd.NaT
    h = C3.hora_no_dia(pd.Series(['08:03:22', '', None]), '02/10/2022')
    assert h.iloc[0] == pd.Timestamp('2022-10-02 08:03:22') and pd.isna(h.iloc[1]) and pd.isna(h.iloc[2])


def test_desloc_por_municipio():
    df = pd.DataFrame({'uf': ['AM', 'AM', 'AM', 'SP', 'ZZ'], 'municipality': [1, 1, 1, 2, 3],
                       'abertura': pd.to_datetime(['2022-10-30 07:00:01', '2022-10-30 07:05:00', '2022-10-30 08:30:00',
                                                   '2022-10-30 08:00:01', '2022-10-30 10:00:00'])})
    d = C3.desloc_por_municipio(df)
    assert d[('AM', 1)] == 1.0 and d[('SP', 2)] == 0.0 and np.isnan(d[('ZZ', 3)])


# ------------------------------------------------------------------------------------------ C3-01: ordem dos marcos
def _lt():
    t = pd.Timestamp
    return pd.DataFrame({
        'uf': ['SP', 'SP', 'AM', 'PE', 'SP', 'ZZ'], 'municipality': [1, 1, 2, 30015, 1, 9], 'zone': [1] * 6, 'section': [1, 2, 3, 4, 5, 6],
        # 1: tudo em ordem; 2: último voto após o encerramento e carga no dia (igual à abertura não: carga > abertura);
        # 3: AM (desloc +1): recebimento em Brasília 1 h depois do relógio local → ok só com fuso; 4: emissão em 2009 (antes do encerramento)
        # 5: só abertura e encerramento; 6: ZZ sem fuso, recebimento 'antes' da emissão em hora local
        'carga': [t('2022-09-20 10:00'), t('2022-10-02 08:00:01'), t('2022-09-20 10:00'), t('2022-09-20 10:00'), pd.NaT, t('2022-09-20 10:00')],
        'abertura': [t('2022-10-02 08:00:01'), t('2022-10-02 08:00:01'), t('2022-10-02 07:00:01'), t('2022-10-02 09:00:01'), t('2022-10-02 08:00:01'), t('2022-10-02 08:00:01')],
        'primeiro_voto': [t('2022-10-02 08:03:00'), t('2022-10-02 08:03:00'), pd.NaT, t('2022-10-02 09:03:00'), pd.NaT, pd.NaT],
        'ultimo_voto': [t('2022-10-02 16:50:00'), t('2022-10-02 17:10:00'), pd.NaT, t('2022-10-02 17:50:00'), pd.NaT, pd.NaT],
        'encerramento': [t('2022-10-02 17:01:00'), t('2022-10-02 17:01:00'), t('2022-10-02 16:01:00'), t('2022-10-02 18:01:00'), t('2022-10-02 17:01:00'), t('2022-10-02 17:01:00')],
        'emissao': [t('2022-10-02 17:03:00'), t('2022-10-02 17:03:00'), t('2022-10-02 16:03:00'), t('2009-01-01 00:16:19'), pd.NaT, t('2022-10-02 17:03:00')],
        'assinatura': [t('2022-10-02 17:04:00'), t('2022-10-02 17:04:00'), pd.NaT, t('2009-01-01 00:18:19'), pd.NaT, pd.NaT],
        'recebimento': [t('2022-10-02 18:00:00'), t('2022-10-02 18:00:00'), t('2022-10-02 17:10:00'), t('2022-10-02 18:56:00'), pd.NaT, t('2022-10-02 17:02:00')],
        'desloc_h': [0.0, 0.0, 1.0, -1.0, 0.0, np.nan]})


def test_ordem_marcos_lista_violacoes_com_tamanho_e_fuso():
    d = C3.ordem_marcos(_lt()).set_index('section')
    assert d.loc[1, 'n_violacoes'] == 0 and d.loc[1, 'status'] == 'comparavel'
    assert d.loc[1, 'dif_apos_emissao'] == 1.0 and d.loc[1, 'dif_apos_assinatura'] == 56.0
    # seção 2: carga = abertura (estrito) e último voto 9 min após o encerramento
    assert d.loc[2, 'n_violacoes'] == 2
    assert 'carga>abertura' in d.loc[2, 'violacoes'] and 'ultimo_voto>encerramento' in d.loc[2, 'violacoes']
    assert d.loc[2, 'dif_apos_ultimo_voto'] == -9.0
    # seção 3: AM, recebimento 17:10 Brasília = 16:10 local, 7 min após a emissão local 16:03 → sem violação graças ao fuso
    assert d.loc[3, 'n_violacoes'] == 0 and d.loc[3, 'dif_apos_emissao'] == 7.0
    # seção 4: emissão em 2009 → encerramento>emissao (gigante), assinatura ≥ emissão ok, recebimento > assinatura ok
    assert 'encerramento>emissao' in d.loc[4, 'violacoes'] and d.loc[4, 'dif_apos_encerramento'] < -1e6
    assert d.loc[4, 'n_violacoes'] == 1
    # seção 5: só abertura e encerramento: um par, comparável
    assert d.loc[5, 'n_pares'] == 1 and d.loc[5, 'n_violacoes'] == 0
    # seção 6: ZZ sem fuso: o par com o recebimento não conta como violação, status parcial
    assert d.loc[6, 'n_violacoes'] == 0 and d.loc[6, 'status'].startswith('PARCIAL')
    # linha sem nenhum marco
    v = C3.ordem_marcos(pd.DataFrame({'abertura': [pd.NaT], 'encerramento': [pd.NaT]}))
    assert v.loc[0, 'status'].startswith('NOT_COMPARABLE')


def test_distribuicao_intervalos():
    d = C3.ordem_marcos(_lt())
    d['pleito'] = '2022-t1'
    r = C3.distribuicao_intervalos(d, ['pleito', 'uf'])
    sp = r[(r.uf == 'SP') & (r.intervalo == 'apos_abertura')].iloc[0]
    assert sp['n'] == 3 and sp['negativos'] == 0  # abertura→1º voto (3 e 3 min) e abertura→encerramento (541 min, seção 5)
    assert sp['proximo_marco_mais_comum'] == 'primeiro_voto'


# ------------------------------------------------------------------------------------------ C3-02: deriva relativa
def test_deriva_relativa_por_geracao():
    rng = np.random.default_rng(0)
    n = 300
    d = pd.DataFrame({'pleito': '2022-t1', 'uf': 'SP', 'geracao': ['UE2020'] * n + ['UE2009-2015 (ECDSA)'] * n,
                      'referencia': 'emissao', 'min_assin_apos_ref': rng.uniform(1, 3, 2 * n),
                      'min_receb_apos_assin': np.r_[rng.uniform(10, 100, n), rng.uniform(10, 100, n) - 8]})  # 2ª geração 8 min "adiantada"
    r = C3.deriva_relativa(d).set_index('geracao')
    assert r.loc['UE2020', 'urnas'] == n and r.loc['UE2020', 'assin_antes_ref'] == 0
    assert r.loc['UE2009-2015 (ECDSA)', 'p01_rel_uf'] < r.loc['UE2020', 'p01_rel_uf']
    assert abs(r.loc['UE2020', 'p50_rel_uf'] - r.loc['UE2009-2015 (ECDSA)', 'p50_rel_uf'] - 8) < 5


# ------------------------------------------------------------------------------------------ C3-07: gaps
def test_faixas_gap_e_resumo():
    d = pd.DataFrame({'pleito': ['a'] * 5, 'classe': ['sem troca'] * 5, 'gap_enc_ultimo': [-1.0, 5.0, 70.0, 130.0, 400.0],
                      'gap_primeiro_abertura': [-2.0, 3.0, 95.0, np.nan, 10.0]})
    f = C3.faixas_gap(d, 'gap_enc_ultimo').astype(str).tolist()
    assert f == ['negativo', '0–15', '60–120', '120–300', '>300']
    r = C3.resumo_gaps(d, ['pleito', 'classe']).iloc[0]
    assert r['gap_negativo'] == 1 and r['gap_gt60'] == 3 and r['gap_gt120'] == 2 and r['gap_gt300'] == 1
    assert r['primeiro_antes_abertura'] == 1 and r['primeiro_gt60_apos_abertura'] == 1 and r['abertura_primeiro_n'] == 4


# ------------------------------------------------------------------------------------------ C3-03: urna repetida
def test_urnas_repetidas():
    d = pd.DataFrame({'uf': ['PA'] * 4 + ['SC'] * 2, 'municipality': [1] * 4 + [2] * 2, 'zone': [1] * 6, 'section': [1, 2, 3, 3, 1, 2],
                      'urna': ['100', '100', '200', '200', '-1', '-1']})
    r = C3.urnas_repetidas(d, 'urna')
    assert r['urna'].tolist() == ['100', '100'] and r['n_secoes_da_urna'].tolist() == [2, 2]  # seção 3 duplicada conta uma vez; -1 ignorado


# ------------------------------------------------------------------------------------------ C3-06: piso e BH
def test_bh_e_excesso_abaixo_do_piso():
    p = np.array([0.001, 0.02, 0.5, 0.9, np.nan])
    rej = C3.bh_rejeita(p, 0.05)
    assert rej.tolist() == [True, True, False, False, False]
    rng = np.random.default_rng(1)
    keys = pd.DataFrame({'municipality': [1] * 2000, 'zone': [1] * 2000, 'section': [1] * 1000 + [2] * 1000})
    v = rng.uniform(20, 200, 2000)
    v[:300] = 5.0  # seção 1 com 30% abaixo do piso
    piso = 10.0
    r = C3.excesso_abaixo_do_piso(keys, v, piso, 0.001).set_index('section')
    assert r.loc[1, 'n_abaixo'] == 300 and r.loc[2, 'n_abaixo'] == 0
    assert bool(r.loc[1, 'bh_5pct']) and not bool(r.loc[2, 'bh_5pct'])
    assert r.loc[1, 'esperado'] == 1.0


# ------------------------------------------------------------------------------------------ C3-09: ligamentos
def test_classifica_ligamentos():
    r = C3.classifica_ligamentos('07:34:02;13:11:10;17:30:00', '08:01:59', '16:54:27', '07:35:00;13:12:00')
    assert (r['n_ligamentos'], r['lig_antes_1o_voto'], r['lig_durante_votacao'], r['lig_apos_ultimo_voto']) == (3, 1, 1, 1)
    assert not r['padrao_periodico_30min'] and r['n_modo_votacao'] == 2 and r['primeiro_ligamento'] == 7 * 3600 + 34 * 60 + 2
    per = ';'.join(f'{h:02d}:{m:02d}:36' for h in range(10, 14) for m in (18, 48))
    r = C3.classifica_ligamentos('09:34:15;09:42:42;' + per, '08:10:00', '16:00:00')  # ligamentos reais + série de 30 min
    assert r['padrao_periodico_30min'] and r['lig_durante_votacao'] == 10 and r['intervalos_de_30min'] == 7
    r = C3.classifica_ligamentos('09:00:00;09:30:00;10:00:00', '08:10:00', '16:00:00')  # só 2 intervalos: não basta
    assert not r['padrao_periodico_30min']
    r = C3.classifica_ligamentos('', '', '')
    assert r['n_ligamentos'] == 0 and not r['padrao_periodico_30min']
    r = C3.classifica_ligamentos('09:00:00', '', '')  # sem votos: tudo 'antes'
    assert r['lig_antes_1o_voto'] == 1


# ------------------------------------------------------------------------------------------ C3-15: hash_time
def test_dif_hash_recebimento():
    d = C3.dif_hash_recebimento(pd.Series(['25/10/2026', '25/10/2026', '25/10/2026']), pd.Series(['19:36:08', '19:19:06', '20:00:00']),
                                pd.Series(['19:35:18', '19:19:02', 'x']))
    assert abs(d.iloc[0] - (-50 / 60)) < 1e-9 and abs(d.iloc[1] - (-4 / 60)) < 1e-9 and pd.isna(d.iloc[2])


# ------------------------------------------------------------------------------------------ C3-08: eventos
def test_conta_eventos():
    ev = '{"INFO | VOTA | Operador cancelou o encerramento da votação": 2, "ALERTA | VOTA | Encerramento só pode ser solicitado após as #:#:# horas": 1, "x": 5}'
    r = C3.conta_eventos(ev, ('cancelou o encerramento', 'Encerramento só pode ser solicitado', 'Votação suspensa'))
    assert r == {'cancelou o encerramento': 2, 'Encerramento só pode ser solicitado': 1, 'Votação suspensa': 0}
    assert C3.conta_eventos(None, ('a',)) == {'a': 0}


# ------------------------------------------------------------------------------------------ C3-13: pausas nos bins
def test_pausas_nos_bins():
    m = np.array([[0, 3, 0, 0, 2, 0, 1, 0],  # votos nos bins 1, 4, 6: 3 vazios entre, maior sequência 2 (30 min)
                  [0, 0, 0, 0, 0, 0, 0, 0],  # sem votos
                  [1, 1, 1, 1, 1, 1, 1, 1]])
    p = C3.pausas_nos_bins(m)
    assert p.loc[0].tolist() == [3.0, 30.0, 3.0]
    assert np.isnan(p.loc[1, 'pausas_15min_bins']) and p.loc[1, 'bins_com_voto'] == 0
    assert p.loc[2].tolist() == [0.0, 0.0, 8.0]


# ------------------------------------------------------------------------------------------ C3-06: agregação por seção (sid)
def test_excesso_por_sid_contiguo_e_nao_contiguo():
    sid = C3.sid_de([30007, 30007, 30007, 41000, 41000], [205, 205, 205, 1, 1], [46, 46, 46, 9, 9])
    assert sid[0] == 30007 * 10**8 + 205 * 10**4 + 46
    k = C3.sid_para_chave(sid[:1]).iloc[0].tolist()
    assert k == [30007, 205, 46]
    v = np.array([5.0, 30.0, np.nan, 40.0, 50.0], dtype=np.float32)
    r = C3.excesso_por_sid(sid, v, 10.0, 0.001).set_index('section')
    assert r.loc[46, 'n'] == 2 and r.loc[46, 'n_abaixo'] == 1 and r.loc[46, 'minimo'] == 5.0 and r.loc[46, 'mediana'] == 17.5
    assert r.loc[9, 'n'] == 2 and r.loc[9, 'n_abaixo'] == 0 and r.loc[9, 'mediana'] == 45.0
    ordem = np.array([3, 0, 4, 1, 2])  # mesma seção em blocos separados: ordena antes e dá o mesmo resultado
    r2 = C3.excesso_por_sid(sid[ordem], v[ordem], 10.0, 0.001).set_index('section')
    assert r2.loc[46, ['n', 'n_abaixo', 'minimo', 'mediana']].tolist() == r.loc[46, ['n', 'n_abaixo', 'minimo', 'mediana']].tolist()


# ------------------------------------------------------------------------------------------ C3-07: faixa do encerramento
def test_faixa_encerramento():
    e = pd.Series(pd.to_datetime(['2026-10-25 17:01:00', '2026-10-25 18:30:00', '2026-10-25 19:00:05', None]))
    assert C3.faixa_encerramento(e).tolist() == ['<18h', '18h–19h', '≥19h', 'sem encerramento']


# ------------------------------------------------------------------------------------------ C3-03: DuckDB por arquivo
def test_sql_repetidas_bweb(tmp_path):
    pytest.importorskip('duckdb')
    a = pd.DataFrame({'SG_UF': ['PA'] * 4, 'CD_MUNICIPIO': ['4898'] * 4, 'NR_ZONA': ['99'] * 4, 'NR_SECAO': ['17', '17', '37', '40'],
                      'NR_URNA_EFETIVADA': ['1809943', '1809943', '1809943', '1700000'], 'DT_ABERTURA': [None, None, '30/10/2022 08:00:01', 'x'],
                      'NR_VOTAVEL': ['13', '22', '13', '13']})
    b = pd.DataFrame({'SG_UF': ['SC'], 'CD_MUNICIPIO': ['83011'], 'NR_ZONA': ['46'], 'NR_SECAO': ['21'], 'NR_URNA_EFETIVADA': ['1700000'],
                      'NR_VOTAVEL': ['13']})  # sem DT_ABERTURA neste arquivo: vira NULL
    fa, fb = tmp_path / 'PA_PRESIDENTE.parquet', tmp_path / 'SC_PRESIDENTE.parquet'
    a.to_parquet(fa, index=False)
    b.to_parquet(fb, index=False)
    c = C3.con()
    rep, res = C3._sql_repetidas(c, [fa, fb], C3._sel_bweb, chave_sel=C3.SEL_CHAVE_BWEB)
    c.close()
    assert sorted(rep['urna'].unique()) == ['1700000', '1809943']  # 1700000 em duas UFs também conta
    assert rep.loc[rep['urna'] == '1809943', 'n_secoes_da_urna'].tolist() == [2, 2]  # seção 17 (duas linhas de votável) conta uma vez
    assert rep.loc[(rep['urna'] == '1809943') & (rep['section'] == 37), 'abertura'].iloc[0] == '30/10/2022 08:00:01'
    assert res.set_index('uf').loc['PA', 'secoes'] == 3


# ------------------------------------------------------------------------------------------ leitores via DuckDB
def test_ler_ultimo_voto_e_indicadores(tmp_path, monkeypatch):
    pytest.importorskip('duckdb')
    csv = tmp_path / 'u.csv'
    csv.write_text('\ufeffuf;municipality;zone;section;desloc_h;votos_log;primeiro_voto;path\n'
                   'BA;30058,0;188,0;295,0;0,0;212,0;2026-10-25 08:02:38;' + r'F:\votos\logs\BA\o03221ba3005801880295-log.jez' + '\n'
                   'AM;2550,0;1,0;7,0;1,0;;;\n', encoding='utf-8')
    monkeypatch.setattr(C3, 'ULTIMO_VOTO', csv)
    d = C3.ler_ultimo_voto(['desloc_h', 'votos_log'], ['primeiro_voto'],
                           extra_sql=["regexp_extract(replace(path, chr(92), '/'), '[^/]+$') log_nome"])
    assert d['municipality'].tolist() == [30058, 2550] and d['votos_log'].iloc[0] == 212.0 and pd.isna(d['votos_log'].iloc[1])
    assert d['log_nome'].iloc[0] == 'o03221ba3005801880295-log.jez' and d['desloc_h'].iloc[1] == 1.0
    ind = pd.DataFrame({'uf': ['SP', 'SP'], 'municipality': np.array([1, 1], dtype='int32'), 'zone': np.array([1, 1], dtype='int32'),
                        'section': np.array([1, 2], dtype='int32'), 'member': ['a', 'b'], 'identity_status': ['PARSED', 'PARSED_FILENAME'],
                        'has_log': [True, True], 'log_complete': [True, True], 'contingency': [False, None], 'swap': [False, False],
                        'red': [False, False], 'first_vote': ['08:01:58', ''], 'last_vote': ['16:59:00', None],
                        'clock_reversals': [0.0, 0.0], 'vote_events': [10.0, 0.0], 'attendance': [10, 0],
                        'opening_bu': ['2022-10-02 08:00:01', None], 'closure_bu': ['2022-10-02 17:00:01', None], 'voting_place': ['1015', '1015']})
    ind.to_parquet(tmp_path / 'secoes_indicadores_P2022.parquet', index=False)
    monkeypatch.setattr(C3, 'INDICADORES', tmp_path)
    f = C3._indicadores('P2022').set_index('section')
    assert f.loc[1, 'primeiro_voto'] == pd.Timestamp('2022-10-02 08:01:58') and pd.isna(f.loc[2, 'primeiro_voto'])
    assert not f.loc[1, 'troca_urna'] and f.loc[2, 'troca_urna']  # identidade só pelo nome do arquivo = troca
