"""Relogio da urna x relogio do servidor do TSE, em todas as secoes com BU no HD.

A urna grava no BU a data da carga, a abertura, o encerramento e a emissao do BU (relogio da urna).
O TSE grava a hora em que recebeu o BU (relogio do servidor de totalizacao, fora da urna).
Uma urna com relogio adiantado teria BU emitido depois do recebimento; e isso que se procura.
Tambem confere a ordem interna: carga < abertura <= encerramento <= emissao, todas na data certa.

Fontes: research/estados/<UF>/<el>/bu.parquet, research/bahia-presidente-2022-2026/<el>/bu.parquet
        (presidente), research/segundo_turno_2026/bu_todos_decodificados.parquet (sem emissao do BU).
Saida:  relatorios/verificacoes/relogio_por_secao.parquet, relogio_resumo.csv, relogio_excecoes.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
OUT = ROOT / 'relatorios' / 'verificacoes'
DIA = {'2022-t1': '2022-10-02', '2022-t2': '2022-10-30', '2026-t1': '2026-10-04', '2026-t2': '2026-10-25'}
NORONHA = 'FERNANDO DE NORONHA'  # UTC-2: a urna marca hora local, 1 h a frente de Brasilia (hora do TSE)
COLS = ['SG_UF', 'CD_MUNICIPIO', 'NM_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_LOCAL_VOTACAO', 'NR_URNA_EFETIVADA', 'DT_CARGA_URNA_EFETIVADA',
        'DT_ABERTURA', 'DT_ENCERRAMENTO', 'DT_EMISSAO_BU', 'DT_BU_RECEBIDO']


def dt(s, fmt='%d/%m/%Y %H:%M:%S'):
    a = pd.to_datetime(s, format=fmt, errors='coerce')
    if fmt.startswith('%d') and a.isna().all():  # dados abertos de 2026 vem em ISO (AAAA-MM-DD)
        a = pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce')
    return a


def secoes_dados_abertos():
    fontes = [(p.parent.name, p) for p in sorted(R.glob('estados/*/*/bu.parquet'))]
    fontes += [(p.parent.name, p) for p in sorted(R.glob('bahia-presidente-2022-2026/*/bu.parquet'))]
    for el, p in fontes:
        b = pd.read_parquet(p, columns=COLS).drop_duplicates(['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO'])
        yield pd.DataFrame({
            'eleicao': el, 'uf': b.SG_UF.values, 'municipio': b.CD_MUNICIPIO.astype(int).values, 'nome_municipio': b.NM_MUNICIPIO.values,
            'zona': b.NR_ZONA.astype(int).values, 'secao': b.NR_SECAO.astype(int).values,
            'local': b.NR_LOCAL_VOTACAO.astype(int).values, 'urna': b.NR_URNA_EFETIVADA.astype(str).values,
            'carga': dt(b.DT_CARGA_URNA_EFETIVADA, '%d/%m/%Y %H:%M:%S').values,
            'abertura': dt(b.DT_ABERTURA).values, 'encerramento': dt(b.DT_ENCERRAMENTO).values,
            'emissao_bu': dt(b.DT_EMISSAO_BU).values, 'recebido_tse': dt(b.DT_BU_RECEBIDO).values})


def secoes_t2_2026():
    t = pd.read_parquet(R / 'segundo_turno_2026' / 'bu_todos_decodificados.parquet',
                        columns=['uf', 'municipality', 'municipality_name', 'zone', 'section', 'voting_place', 'receipt_date', 'receipt_time',
                                 'opening', 'closing'])
    return pd.DataFrame({
        'eleicao': '2026-t2', 'uf': t.uf.values, 'municipio': pd.to_numeric(t.municipality, errors='coerce').values,
        'nome_municipio': t.municipality_name.str.upper().values,
        'zona': pd.to_numeric(t.zone, errors='coerce').values, 'secao': pd.to_numeric(t.section, errors='coerce').values,
        'local': pd.to_numeric(t.voting_place, errors='coerce').values, 'urna': None, 'carga': pd.NaT,
        'abertura': dt(t.opening, '%Y%m%dT%H%M%S').values, 'encerramento': dt(t.closing, '%Y%m%dT%H%M%S').values,
        'emissao_bu': pd.NaT, 'recebido_tse': dt(t.receipt_date + ' ' + t.receipt_time).values})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = pd.concat([*secoes_dados_abertos(), secoes_t2_2026()], ignore_index=True)
    s = s.drop_duplicates(['eleicao', 'uf', 'municipio', 'zona', 'secao'])
    s['noronha'] = s.nome_municipio.eq(NORONHA)
    fim_urna = s.emissao_bu.fillna(s.encerramento)  # ultimo instante gravado pela urna
    fim_urna = fim_urna - pd.to_timedelta(s.noronha.astype(int), unit='h')  # leva a urna para a hora de Brasilia
    s['min_urna_ate_tse'] = (s.recebido_tse - fim_urna).dt.total_seconds() / 60
    s['min_abertura_apos_8h'] = (s.abertura - (s.abertura.dt.normalize() + pd.Timedelta(hours=8))).dt.total_seconds() / 60
    s['min_encerramento_apos_17h'] = (s.encerramento - (s.encerramento.dt.normalize() + pd.Timedelta(hours=17))).dt.total_seconds() / 60
    dia = pd.to_datetime(s.eleicao.map(DIA))
    s['ok_data_eleicao'] = s.abertura.dt.normalize().eq(dia) & s.encerramento.dt.normalize().eq(dia)
    s['ok_carga_antes'] = s.carga.isna() | (s.carga < s.abertura.dt.normalize())
    s['ok_ordem_urna'] = (s.abertura <= s.encerramento) & (s.emissao_bu.isna() | (s.encerramento <= s.emissao_bu))
    s['ok_tse_depois_da_urna'] = s.min_urna_ate_tse > 0
    s['sem_datas'] = s.abertura.isna() | s.encerramento.isna() | s.recebido_tse.isna()
    s.to_parquet(OUT / 'relogio_por_secao.parquet', index=False)

    ok = ~s.sem_datas
    g = s[ok].groupby(['eleicao', 'uf'])
    res = pd.DataFrame({
        'secoes': s.groupby(['eleicao', 'uf']).size(),
        'secoes_com_datas': g.size(),
        'urna_emitiu_depois_do_tse_receber': g.apply(lambda d: int((~d.ok_tse_depois_da_urna).sum())),
        'menor_intervalo_urna_ate_tse_min': g.min_urna_ate_tse.min().round(1),
        'mediana_intervalo_urna_ate_tse_min': g.min_urna_ate_tse.median().round(1),
        'fora_da_data_da_eleicao': g.apply(lambda d: int((~d.ok_data_eleicao).sum())),
        'carga_nao_anterior_ao_dia': g.apply(lambda d: int((~d.ok_carga_antes).sum())),
        'ordem_interna_invertida': g.apply(lambda d: int((~d.ok_ordem_urna).sum())),
        'abertura_antes_7h30': g.apply(lambda d: int((d.min_abertura_apos_8h < -30).sum())),
        'encerramento_antes_17h': g.apply(lambda d: int((d.min_encerramento_apos_17h < 0).sum())),
    }).reset_index()
    tot = res.drop(columns='uf').groupby('eleicao').agg({c: ('min' if 'menor' in c else 'median' if 'mediana' in c else 'sum')
                                                          for c in res.columns if c not in ('eleicao', 'uf')}).reset_index()
    tot['uf'] = 'TOTAL'
    res = pd.concat([res, tot[res.columns]], ignore_index=True).sort_values(['eleicao', 'uf'])
    res.to_csv(OUT / 'relogio_resumo.csv', index=False, sep=';', encoding='utf-8-sig')

    exc = s[ok & ~(s.ok_tse_depois_da_urna & s.ok_data_eleicao & s.ok_carga_antes & s.ok_ordem_urna)
            | ok & (s.min_encerramento_apos_17h < 0) | ok & (s.min_abertura_apos_8h < -30)]
    exc.to_csv(OUT / 'relogio_excecoes.csv', index=False, sep=';', encoding='utf-8-sig')
    pd.set_option('display.width', 250)
    print(res.to_string(index=False))
    print('\nsecoes sem alguma data:', int(s.sem_datas.sum()), '| excecoes:', len(exc))
    print(exc.head(30).to_string())


if __name__ == '__main__':
    main()
