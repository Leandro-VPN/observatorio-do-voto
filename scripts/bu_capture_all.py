"""Capture BU (boletim de urna) rows by office for 10 states, 2014/2018/2022/2026, into normalized-name Parquet.

2014/2018: PRESIDENTE and GOVERNADOR, turns 1 and 2.  2022/2026: GOVERNADOR (presidential BUs already captured).
Output: research/bu/<year>-t<turn>/<UF>_<OFFICE>.parquet (+ .json receipt). Streams ZIP members via HTTP Range; no archive is stored.
"""
import argparse
import io
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq

from auditabr.acquisition import RemoteZipReader
from auditabr.catalog import Catalog
from auditabr.utils import read_json, sha256, utcnow, write_json

UFS = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC', 'MA']
OUT = Path('research/bu')
MUN = Path('research/catalogo-municipais')
CATS = {2012: MUN, 2016: MUN, 2020: MUN, 2024: MUN,
        2014: Path('research/catalogo-2014-2018'), 2018: Path('research/catalogo-2014-2018'),
        2022: Path('research/bahia-presidente-2022-2026'), 2026: Path('research/bahia-presidente-2022-2026')}
COLS_2014 = ['DT_GERACAO', 'HH_GERACAO', 'CD_PLEITO', 'CD_ELEICAO', 'SG_UF', 'CD_CARGO_PERGUNTA', 'DS_CARGO_PERGUNTA', 'NR_ZONA', 'NR_SECAO',
             'NR_LOCAL_VOTACAO', 'NR_PARTIDO', 'SG_PARTIDO', 'CD_MUNICIPIO', 'NM_MUNICIPIO', 'DT_BU_RECEBIDO', 'QT_APTOS', 'QT_ABSTENCOES',
             'QT_COMPARECIMENTO', 'CD_TIPO_ELEICAO', 'CD_TIPO_URNA', 'DS_TIPO_URNA', 'NR_VOTAVEL', 'NM_VOTAVEL', 'QT_VOTOS', 'CD_TIPO_VOTAVEL',
             'NR_URNA_EFETIVADA', 'CD_CARGA_1', 'CD_CARGA_2', 'DT_CARGA', 'CD_FLASHCARD', 'DS_CARGO_PERGUNTA_SECAO']


COLS_2012 = COLS_2014[:18] + ['CD_TIPO_ELEICAO', 'DS_TIPO_ELEICAO'] + COLS_2014[19:]   # 2012 adds the election-type description


def offices_for(year):
    if year in (2012, 2016, 2020, 2024):
        return ('PREFEITO',)
    return ('PRESIDENTE', 'GOVERNADOR') if year in (2014, 2018) else ('GOVERNADOR',)


def find_zip(year, turn, uf):
    res = Catalog(CATS[year]).resources(year)
    m = [x for x in res if f'bweb_{turn}t_{uf}_'.lower() in x['url'].lower() and x['url'].lower().endswith('.zip')]
    if len(m) == 0:
        return None
    if len(m) != 1:
        raise ValueError(('BU zip not unique', year, turn, uf, [x['url'] for x in m]))
    r = dict(m[0])
    if year == 2020:   # the catalog path intermittently answers 503 to Range requests; the official mirror path serves the same file
        r['url'] = r['url'].replace('https://cdn.tse.jus.br/eleicoes2020/', 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2020/')
    return r


def capture(year, turn, uf):
    folder = OUT / f'{year}-t{turn}'
    folder.mkdir(parents=True, exist_ok=True)
    offices = offices_for(year)
    done = all((folder / f'{uf}_{o}.json').exists() for o in offices)
    if done:
        return 'SKIP'
    resource = find_zip(year, turn, uf)
    if resource is None:
        for o in offices:
            write_json(folder / f'{uf}_{o}.json', {'at': utcnow(), 'rows': 0, 'no_such_office': True, 'no_zip': True})
        return 'NO_ZIP'
    with RemoteZipReader(resource['url'], budget=8 * 1024 ** 3) as remote, zipfile.ZipFile(remote) as archive:
        names = [i.filename for i in archive.infolist() if i.filename.lower().endswith(('.csv', '.txt'))]
        if len(names) != 1:
            raise ValueError(('Expected one BU data file', names))
        name = names[0]
        with archive.open(name) as member, io.BufferedReader(member, 8 * 1024 ** 2) as stream:
            if year in (2012, 2014, 2016):
                header = COLS_2012 if year == 2012 else COLS_2014
                ro = csv.ReadOptions(encoding='latin1', block_size=8 * 1024 ** 2, column_names=header)
            else:
                header = [h.replace(' ', '') for h in stream.peek(65536).split(b'\n', 1)[0].decode('latin1').strip().replace('"', '').split(';')]
                ro = csv.ReadOptions(encoding='latin1', block_size=8 * 1024 ** 2, column_names=header, skip_rows=1)
            reader = csv.open_csv(stream, read_options=ro, parse_options=csv.ParseOptions(delimiter=';'),
                                  convert_options=csv.ConvertOptions(column_types={c: pa.string() for c in header}))
            writers, counts = {}, {o: 0 for o in offices}
            tmp = {o: folder / f'{uf}_{o}.parquet.part' for o in offices}
            try:
                for batch in reader:
                    table = pa.Table.from_batches([batch])
                    cargo = pc.utf8_upper(table['DS_CARGO_PERGUNTA'])
                    uf_ok = pc.equal(table['SG_UF'], uf)
                    for o in offices:
                        t = table.filter(pc.and_(pc.equal(cargo, o), uf_ok))
                        if len(t) == 0:
                            continue
                        if o not in writers:
                            writers[o] = pq.ParquetWriter(tmp[o], t.schema, compression='zstd')
                        writers[o].write_table(t)
                        counts[o] += len(t)
            finally:
                for w in writers.values():
                    w.close()
            for o in offices:
                final = folder / f'{uf}_{o}.parquet'
                if counts[o]:
                    tmp[o].replace(final)
                    write_json(folder / f'{uf}_{o}.json', {'at': utcnow(), 'resource': resource, 'member': name, 'rows': counts[o],
                                                           'sha256': sha256(final), 'bytes': final.stat().st_size, 'columns': header})
                else:   # office not on the ballot in this round/state
                    tmp[o].unlink(missing_ok=True)
                    write_json(folder / f'{uf}_{o}.json', {'at': utcnow(), 'resource': resource, 'member': name, 'rows': 0, 'no_such_office': True})
    return 'OK ' + ' '.join(f'{o}={c}' for o, c in counts.items())


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--years', default='2014,2018,2022,2026')
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--turns', default='1,2')
    a = p.parse_args()
    jobs = []
    for y in map(int, a.years.split(',')):
        for t in ([int(x) for x in a.turns.split(',')] if y != 2026 else (1,)):
            for uf in UFS:
                jobs.append((y, t, uf))

    def run(j):
        for attempt in range(6):
            try:
                r = capture(*j)
                print(j, r, flush=True)
                return j, None
            except Exception as exc:
                if attempt == 5:
                    print(j, 'FAILED', repr(exc), flush=True)
                    return j, repr(exc)
                time.sleep(10 * (attempt + 1))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        res = list(pool.map(run, jobs))
    bad = [r for r in res if r[1]]
    print('CAPTURE DONE', len(jobs), 'failed', bad, flush=True)
    sys.exit(1 if bad else 0)
