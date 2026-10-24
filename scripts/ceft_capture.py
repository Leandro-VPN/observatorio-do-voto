"""Capture 'correspondências efetivadas' (CEFT) for 10 states, all elections 2012-2026, into research/ceft/<year>-t<turn>/<UF>.parquet.
One row per section: expected urn vs effective urn, load dates, receipt dates, vote origin (RED etc.)."""
import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from auditabr.acquisition import RemoteZipReader
from auditabr.catalog import Catalog
from auditabr.utils import write_json, utcnow

UFS = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
CATS = {2012: 'research/catalogo-municipais', 2014: 'research/catalogo-2014-2018', 2016: 'research/catalogo-municipais', 2018: 'research/catalogo-2014-2018',
        2020: 'research/catalogo-municipais', 2022: 'research/bahia-presidente-2022-2026', 2024: 'research/catalogo-municipais', 2026: 'research/bahia-presidente-2022-2026'}
OUT = Path('research/ceft')
# 2012-2016 files have no header; layout inferred from 2018 header order (documented in each zip's leiame)
COLS_OLD = ['DT_GERACAO', 'HH_GERACAO', 'CD_PLEITO', 'DT_PLEITO', 'SG_UF', 'CD_MUNICIPIO', 'NM_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'SQ_CORRESPONDENCIA_ESPERADA',
            'NR_URNA_ESPERADA', 'CD_CARGA_URNA_ESPERADA', 'CD_CARGA_1_URNA_ESPERADA', 'CD_CARGA_2_URNA_ESPERADA', 'CD_FLASHCARD_URNA_ESPERADA', 'DT_CARGA_URNA_ESPERADA',
            'DT_RECO_URNA_ESPERADA', 'SQ_CORRESPONDENCIA_EFETIVADA', 'NR_URNA_EFETIVADA', 'CD_CARGA_URNA_EFETIVADA', 'CD_CARGA_1_URNA_EFETIVADA', 'CD_CARGA_2_URNA_EFETIVADA',
            'CD_FLASHCARD_URNA_EFETIVADA', 'DT_CARGA_URNA_EFETIVADA', 'DT_RECO_URNA_EFETIVADA', 'CD_ORIGEM_VOTO', 'DS_ORIGEM_VOTO', 'DS_DIVERGENCIA', 'NR_LOCAL_VOTACAO']


def job(args):
    year, turn, uf = args
    dest = OUT / f'{year}-t{turn}' / f'{uf}.parquet'
    if dest.exists():
        return args, 'SKIP'
    res = Catalog(Path(CATS[year])).resources(year)
    m = [r for r in res if r['url'].split('/')[-1].lower().startswith(f'ceft_{turn}t_{uf}_'.lower()) and r['url'].lower().endswith('.zip')]
    if not m:
        return args, 'NO_ZIP'
    url = m[0]['url']
    if year == 2020:   # catalog path answers 503 intermittently; official mirror path serves the same file
        url = url.replace('https://cdn.tse.jus.br/eleicoes2020/', 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2020/')
    for attempt in range(5):
        try:
            with RemoteZipReader(url, budget=1024 ** 3) as rz, zipfile.ZipFile(rz) as z:
                nm = [i.filename for i in z.infolist() if i.filename.lower().endswith(('.csv', '.txt'))][0]
                with z.open(nm) as f:
                    raw = f.read()
            text = raw.decode('latin1')
            first = text.split('\n', 1)[0]
            if 'DT_GERACAO' in first.upper():
                d = pd.read_csv(io.StringIO(text), sep=';', dtype=str)
                d.columns = [c.strip().replace(' ', '') for c in d.columns]
            else:
                d = pd.read_csv(io.StringIO(text), sep=';', dtype=str, header=None)
                if d.shape[1] == len(COLS_OLD):
                    d.columns = COLS_OLD
                else:
                    d.columns = [f'c{i}' for i in range(d.shape[1])]
            dest.parent.mkdir(parents=True, exist_ok=True)
            d.to_parquet(dest, compression='zstd', index=False)
            write_json(dest.with_suffix('.json'), {'at': utcnow(), 'url': url, 'member': nm, 'rows': len(d), 'columns': list(d.columns)})
            return args, f'OK rows={len(d)} cols={d.shape[1]}'
        except Exception as exc:
            if attempt == 4:
                return args, 'FAILED ' + repr(exc)[:120]
            time.sleep(5 * (attempt + 1))


if __name__ == '__main__':
    jobs = [(y, t, uf) for y in CATS for t in ((1, 2) if y != 2026 else (1,)) for uf in UFS]
    bad = []
    with ThreadPoolExecutor(4) as ex:
        for args, r in ex.map(job, jobs):
            print(args, r, flush=True)
            if r.startswith('FAILED'):
                bad.append((args, r))
    print('CEFT DONE', len(jobs), 'failed', bad, flush=True)
    sys.exit(1 if bad else 0)
