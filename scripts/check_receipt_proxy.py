"""Does the BU-receipt-at-TSE time (public 'detalhe_votacao_secao') track closing time and late votes? Validation on years where logs / closing time exist."""
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from auditabr.acquisition import RemoteZipReader
from auditabr.catalog import Catalog

CATS = {2016: 'research/catalogo-municipais', 2018: 'research/catalogo-2014-2018', 2020: 'research/catalogo-municipais', 2022: 'research/bahia-presidente-2022-2026',
        2024: 'research/catalogo-municipais'}
OFFICE = {2016: ('PREFEITO', 'PREFEITO'), 2018: ('PRESIDENTE', 'PRESIDENTE'), 2020: ('PREFEITO', 'PREFEITO'), 2022: ('PRESIDENTE', 'PRESIDENTE'), 2024: ('PREFEITO', 'PREFEITO')}


def adir(office, uf, year):
    if office == 'PRESIDENTE' and year in (2022, 2026):
        return (Path('research/bahia-presidente-2022-2026') if uf == 'BA' else Path('research/estados') / uf) / f'{year}-t1' / 'analysis'
    if office == 'PREFEITO' and year == 2024:
        return Path('research/analysis/PREFEITO') / uf / '2024-t1'
    return Path('research/analysis') / office / uf / f'{year}-t1'


def closing_minutes(s):
    t = pd.to_datetime(s, format='%d/%m/%Y %H:%M:%S', errors='coerce')
    t = t.fillna(pd.to_datetime(s, format='%Y-%m-%d %H:%M:%S', errors='coerce'))
    return t.dt.hour * 60 + t.dt.minute + t.dt.second / 60 - 1020


def detalhe(year, uf, cargo):
    res = Catalog(Path(CATS[year])).resources(year)
    u = [r for r in res if r['url'].split('/')[-1].startswith('detalhe_votacao_secao')][0]['url']
    with RemoteZipReader(u, budget=2 * 1024 ** 3) as rz, zipfile.ZipFile(rz) as z:
        nm = [i.filename for i in z.infolist() if i.filename.endswith(f'_{uf}.csv')][0]
        with z.open(nm) as f:
            d = pd.read_csv(io.TextIOWrapper(f, encoding='latin1'), sep=';', dtype=str)
    d = d[(d.NR_TURNO == '1') & (d.DS_CARGO.str.upper() == cargo)]
    d = d[['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'DT_RECEBIMENTO_BU_HOR_TSE', 'DT_PRIM_TOT_PARCIAL_HOR_TSE', 'ST_SECAO_INSTALADA', 'CD_MODELO_URNA', 'DS_MODELO_URNA']].drop_duplicates()
    d['municipality'] = d.CD_MUNICIPIO.astype(int)
    d['zone'] = d.NR_ZONA.astype(int)
    d['section'] = d.NR_SECAO.astype(int)
    d['receipt_min'] = closing_minutes(d.DT_RECEBIMENTO_BU_HOR_TSE)
    return d


def rho(x, y):
    ok = x.notna() & y.notna()
    return stats.spearmanr(x[ok], y[ok])[0] if ok.sum() > 30 else np.nan


rows = []
for year in (2016, 2018, 2020, 2022, 2024):
    office, cargo = OFFICE[year]
    for uf in ('BA', 'SP', 'MG', 'PE', 'RS'):
        f = adir(office, uf, year) / 'sections.parquet'
        det = detalhe(year, uf, cargo)
        row = dict(year=year, uf=uf, n_detalhe=len(det), receipt_ok=int(det.receipt_min.notna().sum()), median_receipt_min=det.receipt_min.median(),
                   pct_gt15=100 * (det.receipt_min > 15).mean() if det.receipt_min.notna().any() else np.nan)
        if f.exists():
            cols = ['municipality', 'zone', 'section', 'closure_bu', 'after_17_recorded', 'operational_eligible']
            s = pd.read_parquet(f, columns=[c for c in cols if c in pd.read_parquet(f).columns])
            m = s.merge(det, on=['municipality', 'zone', 'section'])
            m['close_min'] = closing_minutes(m.closure_bu) if 'closure_bu' in m else np.nan
            row['rho_receipt_vs_closing'] = rho(m.receipt_min, m.close_min)
            if 'after_17_recorded' in m and m.after_17_recorded.notna().any():
                e = m[m.operational_eligible == True]
                row['rho_receipt_vs_late'] = rho(e.receipt_min.clip(lower=0), e.after_17_recorded)
                row['rho_closing_vs_late'] = rho(e.close_min.clip(lower=0), e.after_17_recorded)
        rows.append(row)
        print(row, flush=True)
pd.DataFrame(rows).round(3).to_csv('research/catalogo-municipais/receipt_proxy_validation.csv', index=False)
