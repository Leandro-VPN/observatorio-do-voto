"""perfil_eleitor_secao_<year>_<UF>.zip -> per-section aggregates: voters, %60+, %70+, %low schooling, %biometria, place name. 10 states."""
import io
import sys
import time
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv

from auditabr.acquisition import RemoteZipReader
from auditabr.catalog import Catalog

UFS = ['BA', 'SP', 'MG', 'RJ', 'PR', 'RS', 'PE', 'CE', 'PA', 'SC']
CATS = {2018: 'research/catalogo-2014-2018', 2022: 'research/bahia-presidente-2022-2026', 2026: 'research/bahia-presidente-2022-2026'}
OUT = Path('research/perfil')


def capture(year, uf):
    dest = OUT / f'{year}' / f'{uf}.parquet'
    if dest.exists():
        return 'SKIP'
    res = Catalog(Path(CATS[year])).resources(year)
    u = [r['url'] for r in res if r['url'].endswith(f'perfil_eleitor_secao_{year}_{uf}.zip')][0]
    import duckdb
    with RemoteZipReader(u, budget=4 * 1024 ** 3) as rz, zipfile.ZipFile(rz) as z:
        nm = [i.filename for i in z.infolist() if i.filename.endswith('.csv')][0]
        with z.open(nm) as member, io.BufferedReader(member, 8 * 1024 ** 2) as stream:
            header = stream.peek(65536).split(b'\n', 1)[0].decode('latin1').strip().replace('"', '').split(';')
            qt = 'QT_ELEITORES_PERFIL' if 'QT_ELEITORES_PERFIL' in header else 'QT_ELEITORES'
            keep = ['CD_MUNICIPIO', 'NR_ZONA', 'NR_SECAO', 'NR_LOCAL_VOTACAO', 'NM_LOCAL_VOTACAO', 'CD_FAIXA_ETARIA', 'CD_GRAU_ESCOLARIDADE', qt, 'QT_ELEITORES_BIOMETRIA']
            reader = csv.open_csv(stream, read_options=csv.ReadOptions(encoding='latin1', block_size=16 * 1024 ** 2), parse_options=csv.ParseOptions(delimiter=';'),
                                  convert_options=csv.ConvertOptions(column_types={c: pa.string() for c in header}, include_columns=keep))
            tables = [pa.Table.from_batches([b]) for b in reader]
    t = pa.concat_tables(tables)
    d = duckdb.connect()
    d.register('p', t)
    # CD_FAIXA_ETARIA: 4-digit code like 6064 (60-64), 7074, 9999 (100+), 1600 (16), 1700 (17), 1800..., -3 invalid. age lower bound = code//100 for >= 1800? codes: 1600,1700,1800,1900,2000,2124,2529,...,9599,9999
    d.execute(f'''CREATE TABLE s AS SELECT cast(CD_MUNICIPIO AS INT) municipality, cast(NR_ZONA AS INT) AS "zone", cast(NR_SECAO AS INT) section,
        max(NR_LOCAL_VOTACAO) voting_place, max(NM_LOCAL_VOTACAO) place_name,
        sum(cast({qt} AS BIGINT)) voters, sum(cast(QT_ELEITORES_BIOMETRIA AS BIGINT)) biometria,
        sum(CASE WHEN try_cast(CD_FAIXA_ETARIA AS INT) >= 6064 AND try_cast(CD_FAIXA_ETARIA AS INT) <= 9999 THEN cast({qt} AS BIGINT) ELSE 0 END) age60,
        sum(CASE WHEN try_cast(CD_FAIXA_ETARIA AS INT) >= 7074 AND try_cast(CD_FAIXA_ETARIA AS INT) <= 9999 THEN cast({qt} AS BIGINT) ELSE 0 END) age70,
        sum(CASE WHEN try_cast(CD_FAIXA_ETARIA AS INT) IN (1600,1700) THEN cast({qt} AS BIGINT) ELSE 0 END) age16_17,
        sum(CASE WHEN try_cast(CD_GRAU_ESCOLARIDADE AS INT) BETWEEN 1 AND 3 THEN cast({qt} AS BIGINT) ELSE 0 END) low_school,
        sum(CASE WHEN try_cast(CD_GRAU_ESCOLARIDADE AS INT) IN (7,8) THEN cast({qt} AS BIGINT) ELSE 0 END) higher_ed,
        sum(CASE WHEN try_cast(CD_FAIXA_ETARIA AS INT) < 0 THEN cast({qt} AS BIGINT) ELSE 0 END) age_unknown
        FROM p GROUP BY ALL''')
    dest.parent.mkdir(parents=True, exist_ok=True)
    d.execute(f"COPY s TO '{dest.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    n = d.execute('SELECT count(*), sum(voters) FROM s').fetchone()
    return f'OK sections={n[0]} voters={n[1]}'


if __name__ == '__main__':
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
    for uf in UFS:
        for a in range(4):
            try:
                print(year, uf, capture(year, uf), flush=True)
                break
            except Exception as exc:
                if a == 3:
                    print(year, uf, 'FAILED', repr(exc)[:150], flush=True)
                time.sleep(10 * (a + 1))
    print('PROFILE DONE', flush=True)
