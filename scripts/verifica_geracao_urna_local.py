"""Resultado por geracao de urna dentro do mesmo local de votacao - presidencial 2022 2o turno.

Num mesmo local (predio), as secoes recebem urnas de geracoes diferentes, de forma praticamente
aleatoria quanto ao eleitorado. Duas geracoes no conjunto:
  - Ed521  : UE2020/UE2022 (AC UE2020/UE2022), urnas mais novas;
  - ECDSA  : AC URNA, modelos UE2009-UE2015, urnas mais antigas.
Se a geracao da urna influenciasse o resultado, a fracao de um candidato diferiria entre geracoes
DENTRO do mesmo local. Mede-se a fracao de Bolsonaro (22) por secao, remove-se a media do local
(efeito fixo de local) e compara-se o residuo entre geracoes. Diferenca proxima de zero = a geracao
nao muda o resultado. Nao prova ausencia de fraude; testa uma via especifica (urna de modelo X).

Fontes: relatorios/integridade/integridade_todas_urnas.parquet (geracao por secao via nome do log),
        research/estados/<UF>/2022-t2/bu.parquet (presidencial).
Saida:  relatorios/verificacoes/geracao_local_resumo.csv
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
OUT = ROOT / 'relatorios' / 'verificacoes'
NOME = [re.compile(r'^o0*\d+-(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})'),
        re.compile(r'^o0*\d+[a-z]{2}(?P<mun>\d{5})(?P<zona>\d{4})(?P<sec>\d{4})')]
CHAVE = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO']


def geracao_por_secao(el):
    d = pd.read_parquet(ROOT / 'relatorios/integridade/integridade_todas_urnas.parquet',
                        columns=['eleicao', 'uf', 'urna', 'cert_emissor'])
    d = d[d.eleicao == el].copy()
    mz = d.urna.str.extract(NOME[0]).fillna(d.urna.str.extract(NOME[1]))
    d['CD_MUNICIPIO'] = pd.to_numeric(mz['mun'], errors='coerce')
    d['NR_ZONA'] = pd.to_numeric(mz['zona'], errors='coerce')
    d['NR_SECAO'] = pd.to_numeric(mz['sec'], errors='coerce')
    d['geracao'] = np.where(d.cert_emissor.str.contains('UE'), 'nova (UE2020/22, Ed521)', 'antiga (AC URNA, ECDSA)')
    return d.dropna(subset=CHAVE).drop_duplicates(CHAVE)[['uf'] + CHAVE + ['geracao']]


def bolsonaro_por_secao(uf, el):
    b = pd.read_parquet(R / 'estados' / uf / el / 'bu.parquet',
                        columns=CHAVE + ['DS_CARGO_PERGUNTA', 'NR_VOTAVEL', 'QT_VOTOS', 'NR_LOCAL_VOTACAO']).copy()
    b = b[b.DS_CARGO_PERGUNTA.str.contains('Presidente', case=False, na=False)]
    for c in CHAVE:
        b[c] = b[c].astype(int)
    b['QT_VOTOS'] = pd.to_numeric(b.QT_VOTOS, errors='coerce').fillna(0)
    b['NR_VOTAVEL'] = pd.to_numeric(b.NR_VOTAVEL, errors='coerce')
    b['NR_LOCAL_VOTACAO'] = b.NR_LOCAL_VOTACAO.astype(int)
    tot = b.groupby(CHAVE).QT_VOTOS.sum().rename('validos')
    v22 = b[b.NR_VOTAVEL == 22].groupby(CHAVE).QT_VOTOS.sum().rename('v22')
    loc = b.groupby(CHAVE).NR_LOCAL_VOTACAO.first()
    d = pd.concat([tot, v22, loc], axis=1).reset_index()
    d['v22'] = d.v22.fillna(0)
    d['frac22'] = d.v22 / d.validos.replace(0, np.nan)
    return d


def main():
    el = '2022-t2'
    OUT.mkdir(parents=True, exist_ok=True)
    ger = geracao_por_secao(el)
    ufs = sorted(p.name for p in (R / 'estados').iterdir() if (p / el / 'bu.parquet').exists())
    partes = []
    for uf in ufs:
        b = bolsonaro_por_secao(uf, el)
        g = ger[ger.uf == uf]
        m = b.merge(g, on=CHAVE)
        m = m[m.validos.ge(50) & m.frac22.notna()]
        # local de votacao = municipio + zona + numero do local (o numero so e unico no municipio)
        m['loc_id'] = (uf + '-' + m.CD_MUNICIPIO.astype(str) + '-' + m.NR_ZONA.astype(str)
                       + '-' + m.NR_LOCAL_VOTACAO.astype(str))
        partes.append(m)
    s = pd.concat(partes, ignore_index=True)
    locs = s.groupby('loc_id').geracao.nunique()
    mistos = s[s.loc_id.isin(locs[locs == 2].index)].copy()
    mistos = mistos[mistos.groupby('loc_id').frac22.transform('size') >= 4]
    mistos['frac22_sem_local'] = mistos.frac22 - mistos.groupby('loc_id').frac22.transform('mean')

    dif = (mistos[mistos.geracao.str.startswith('nova')].frac22_sem_local.mean()
           - mistos[mistos.geracao.str.startswith('antiga')].frac22_sem_local.mean())
    res = mistos.groupby('geracao').agg(secoes=('frac22', 'size'),
                                        frac22_media=('frac22', 'mean'),
                                        frac22_sem_efeito_local=('frac22_sem_local', 'mean')).round(4)
    poruf = mistos.groupby(['uf', 'geracao']).frac22_sem_local.mean().unstack().round(4)
    poruf['dif_nova_menos_antiga_pp'] = ((poruf.iloc[:, 1] - poruf.iloc[:, 0]) * 100).round(2)
    res.to_csv(OUT / 'geracao_local_resumo.csv', sep=';', encoding='utf-8-sig')
    poruf.to_csv(OUT / 'geracao_local_por_uf.csv', sep=';', encoding='utf-8-sig')
    pd.set_option('display.width', 200)
    print('locais com as duas geracoes (>=4 secoes):', mistos.loc_id.nunique(), '| secoes:', len(mistos))
    print(res.to_string())
    print(f'\nfracao Bolsonaro (sem efeito de local): nova - antiga = {dif*100:+.3f} pontos percentuais')
    print('\npor UF (residuo medio por geracao, e diferenca nova-antiga em pp):')
    print(poruf.to_string())


if __name__ == '__main__':
    main()
