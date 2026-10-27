"""Consistencia 1o x 2o turno por secao - presidencial 2022 (Lula 13 x Bolsonaro 22).

Mesma secao, mesmo eleitorado em intervalo de 4 semanas. A fracao de votos de um candidato
no 1o e no 2o turno e fortemente correlacionada. Uma secao que inverte o padrao local e um
outlier estatistico. Mede-se o residuo de cada secao contra uma reta ajustada por municipio
(onde ha secoes bastante) e marca-se |z| alto. Isso nao prova fraude: mapeia as secoes que
mais fogem do padrao, que e onde uma distorcao localizada apareceria.

Fontes: research/estados/<UF>/2022-t1 e 2022-t2/bu.parquet (presidencial).
Saida:  relatorios/verificacoes/turno1x2_por_secao.parquet, turno1x2_resumo.csv, turno1x2_outliers.csv
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'research'
OUT = ROOT / 'relatorios' / 'verificacoes'
CHAVE = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO']


def frac_bolsonaro(uf, el):
    p = R / 'estados' / uf / el / 'bu.parquet'
    b = pd.read_parquet(p, columns=CHAVE + ['DS_CARGO_PERGUNTA', 'NR_VOTAVEL', 'QT_VOTOS', 'NM_MUNICIPIO'])
    b = b[b.DS_CARGO_PERGUNTA.str.contains('Presidente', case=False, na=False)].copy()
    for c in CHAVE:
        b[c] = b[c].astype(int)
    b['QT_VOTOS'] = pd.to_numeric(b.QT_VOTOS, errors='coerce').fillna(0)
    b['NR_VOTAVEL'] = pd.to_numeric(b.NR_VOTAVEL, errors='coerce')
    tot = b.groupby(CHAVE).QT_VOTOS.sum().rename('validos_mais_bn')
    b22 = b[b.NR_VOTAVEL == 22].groupby(CHAVE).QT_VOTOS.sum().rename('v22')
    nome = b.groupby(CHAVE).NM_MUNICIPIO.first()
    d = pd.concat([tot, b22, nome], axis=1).reset_index()
    d['v22'] = d.v22.fillna(0)
    d['frac22'] = d.v22 / d.validos_mais_bn.replace(0, np.nan)
    return d


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ufs = sorted(p.name for p in (R / 'estados').iterdir() if (p / '2022-t1' / 'bu.parquet').exists()
                 and (p / '2022-t2' / 'bu.parquet').exists())
    partes = []
    for uf in ufs:
        t1 = frac_bolsonaro(uf, '2022-t1')[CHAVE + ['NM_MUNICIPIO', 'frac22', 'validos_mais_bn']].rename(
            columns={'frac22': 'frac22_t1', 'validos_mais_bn': 'votos_t1'})
        t2 = frac_bolsonaro(uf, '2022-t2')[CHAVE + ['frac22', 'validos_mais_bn']].rename(
            columns={'frac22': 'frac22_t2', 'validos_mais_bn': 'votos_t2'})
        m = t1.merge(t2, on=CHAVE)
        m['uf'] = uf
        partes.append(m)
    s = pd.concat(partes, ignore_index=True)
    s = s[s.votos_t1.ge(10) & s.votos_t2.ge(10) & s.frac22_t1.notna() & s.frac22_t2.notna()]

    # reta frac_t2 ~ a + b*frac_t1 por municipio (so com >=5 secoes); residuo padronizado
    s['res'] = np.nan
    for mun, d in s.groupby('CD_MUNICIPIO'):
        if len(d) < 5:
            continue
        x, y = d.frac22_t1.values, d.frac22_t2.values
        b, a = np.polyfit(x, y, 1)
        r = y - (a + b * x)
        sd = r.std(ddof=1)
        s.loc[d.index, 'res'] = r / sd if sd > 1e-9 else 0.0
    s['z_abs'] = s.res.abs()
    s.to_parquet(OUT / 'turno1x2_por_secao.parquet', index=False)

    corr_geral = s.frac22_t1.corr(s.frac22_t2)
    res = s.groupby('uf').apply(lambda d: pd.Series({
        'secoes': len(d),
        'correlacao_t1_t2': round(d.frac22_t1.corr(d.frac22_t2), 4),
        'secoes_modeladas': int(d.res.notna().sum()),
        'outliers_z>4': int((d.z_abs > 4).sum()),
        'outliers_z>5': int((d.z_abs > 5).sum()),
    })).reset_index()
    res.to_csv(OUT / 'turno1x2_resumo.csv', index=False, sep=';', encoding='utf-8-sig')
    out = s[s.z_abs > 4].sort_values('z_abs', ascending=False)
    out.to_csv(OUT / 'turno1x2_outliers.csv', index=False, sep=';', encoding='utf-8-sig')
    pd.set_option('display.width', 220)
    print(res.to_string(index=False))
    print(f'\ncorrelacao geral frac22 t1 x t2: {corr_geral:.4f} | secoes: {len(s)} | outliers z>4: {int((s.z_abs>4).sum())} | z>5: {int((s.z_abs>5).sum())}')
    print(out.head(15)[['uf', 'NM_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'frac22_t1', 'frac22_t2', 'votos_t2', 'res']].to_string(index=False))


if __name__ == '__main__':
    main()
