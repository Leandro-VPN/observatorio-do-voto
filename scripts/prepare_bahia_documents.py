"""BA-only presidential study: compact captures and log inventories, no front-end."""
import io
import json
from pathlib import Path
import shutil
import zipfile

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as csv
import pyarrow.parquet as pq

from auditabr.acquisition import RemoteZipReader
from auditabr.catalog import Catalog
from auditabr.utils import read_json, write_json, sha256, utcnow

ROOT = Path('research/bahia-presidente-2022-2026')
CAT = Catalog(ROOT)


def inventory(resource, destination):
    path = destination/'remote-inventory.json'
    if path.exists():
        return read_json(path)
    with RemoteZipReader(resource['url'], budget=64*1024**2) as remote, zipfile.ZipFile(remote) as archive:
        result = [{'resource':resource,'container_bytes':remote.size,'members':[
            {'name':m.filename,'bytes':m.file_size,'compressed':m.compress_size}
            for m in archive.infolist() if not m.is_dir()]}]
    write_json(path,result)
    return result


def capture(resource, destination, kind):
    out = destination/(kind+'.parquet')
    receipt = out.with_suffix('.json')
    if receipt.exists() and out.exists() and sha256(out)==read_json(receipt)['sha256']:
        print('REUSED',str(out),flush=True)
        return
    with RemoteZipReader(resource['url'],budget=512*1024**2) as remote, zipfile.ZipFile(remote) as archive:
        names = [i.filename for i in archive.infolist() if i.filename.endswith('.csv')]
        if kind=='candidates':
            names = [n for n in names if Path(n).stem.endswith('_BR')]
        if len(names)!=1:
            raise ValueError(('Expected one target CSV',kind,names))
        name = names[0]
        with archive.open(name) as member, io.BufferedReader(member,8*1024**2) as stream:
            header = stream.peek(65536).split(b'\n',1)[0].decode('latin1').strip().replace('"','').split(';')
            keep = header
            if kind=='candidates':
                keep=[c for c in header if c in ['ANO_ELEICAO','NR_TURNO','SG_UF','CD_CARGO','DS_CARGO','SQ_CANDIDATO','NR_CANDIDATO','NM_URNA_CANDIDATO','NR_PARTIDO','SG_PARTIDO','DS_SIT_TOT_TURNO']]
            elif kind=='profile':
                keep=[c for c in header if c in ['ANO_ELEICAO','SG_UF','CD_MUNICIPIO','NM_MUNICIPIO','NR_ZONA','NR_SECAO','NR_LOCAL_VOTACAO','CD_FAIXA_ETARIA','DS_FAIXA_ETARIA','CD_GRAU_ESCOLARIDADE','DS_GRAU_ESCOLARIDADE','QT_ELEITORES_PERFIL','QT_ELEITORES_BIOMETRIA']]
            reader=csv.open_csv(stream,read_options=csv.ReadOptions(encoding='latin1',block_size=8*1024**2),parse_options=csv.ParseOptions(delimiter=';'),convert_options=csv.ConvertOptions(column_types={c:pa.string() for c in header},include_columns=keep))
            writer=None;count=0
            try:
                for batch in reader:
                    table=pa.Table.from_batches([batch])
                    if kind in ('bu','candidates'):
                        column='DS_CARGO_PERGUNTA' if kind=='bu' else 'DS_CARGO'
                        table=table.filter(pc.equal(pc.utf8_upper(table[column]),'PRESIDENTE'))
                    if kind=='bu':
                        table=table.filter(pc.equal(table['SG_UF'],'BA'))
                    if writer is None:
                        writer=pq.ParquetWriter(out,table.schema,compression='zstd')
                    writer.write_table(table);count+=len(table)
            finally:
                if writer:writer.close()
        write_json(receipt,{'at':utcnow(),'resource':resource,'member':name,'member_crc32':archive.getinfo(name).CRC,
            'sha256':sha256(out),'rows':count,'bytes':out.stat().st_size,'transport_bytes':remote.transferred,
            'scope':'BA PRESIDENTE; profile geography only; candidates national presidential list',
            'http':remote.headers})
        print(json.dumps({'capture':str(out),'rows':count,'bytes':out.stat().st_size}),flush=True)


def main():
    write_json(ROOT/'scope.json',{'at':utcnow(),'scope':'BA PRESIDENTE 2022 T1/T2 and 2026 T1',
        'deliverables':'PDF reports and static graphs; no front-end work',
        'free_bytes_before':shutil.disk_usage(ROOT.resolve().anchor).free,
        'reuse_2022_t2':'research/piloto-ba-2022-t2',
        'reuse_2022_profile':'research/piloto-ba-2022-t2/captures/perfil_eleitor_secao_2022_BA.parquet',
        'storage':'HTTP Range ZIP members; retain compressed logs; scoped ZSTD Parquet; no whole archive fallback'})
    for year in (2022,2026):
        folder=ROOT/f'{year}-t1';folder.mkdir(exist_ok=True)
        resources=CAT.resources(year)
        log=next(r for r in resources if '/arqurnatot/' in r['url'] and f'_{year}_1t_BA.zip' in r['url'])
        inv=inventory(log,folder)
        logs=[m for m in inv[0]['members'] if m['name'].lower().endswith(('.logjez','-log.jez'))]
        print(json.dumps({'year':year,'log_files':len(logs),'log_storage_bytes':sum(m['bytes'] for m in logs)}),flush=True)
        bu=next(r for r in resources if '/buweb/bweb_1t_BA_' in r['url'] and r['url'].endswith('.zip'))
        capture(bu,folder,'bu')
        if year==2026:
            candidates=next(r for r in resources if r['url'].endswith('/consulta_cand_2026.zip'))
            profile=next(r for r in resources if r['url'].endswith('/perfil_eleitor_secao_2026_BA.zip'))
            capture(candidates,folder,'candidates')
            capture(profile,folder,'profile')


if __name__=='__main__':
    main()
