"""Selective streamed acquisition for the BA 2022 T2 research pilot."""
import io,json,zipfile
from pathlib import Path
import pyarrow as pa
import pyarrow.csv as csv
import pyarrow.compute as pc
import pyarrow.parquet as pq
from auditabr.acquisition import RemoteZipReader
from auditabr.utils import read_json,write_json,sha256,utcnow
root=Path('research/piloto-ba-2022-t2');dest=root/'captures';dest.mkdir(exist_ok=True)
inventory=read_json(root/'remote-inventory.json')
for family,prefix in [('candidates','consulta_cand'),('bu','bweb'),('profile','perfil_eleitor'),('votes','votacao_secao')]:
 entry=next(e for e in inventory if prefix in e['resource']['url'])
 names=[m['name'] for m in entry['members'] if m['name'].endswith('.csv') and (family!='candidates' or m['name'] in ('consulta_cand_2022_BA.csv','consulta_cand_2022_BR.csv'))]
 for name in names:
  out=dest/(Path(name).stem+'.parquet');receipt=out.with_suffix('.json')
  if receipt.exists() and out.exists() and sha256(out)==read_json(receipt)['sha256']:
   print('REUSED',name,flush=True);continue
  writer=None;count=0
  with RemoteZipReader(entry['resource']['url'],budget=512*1024**2) as remote,zipfile.ZipFile(remote) as z:
   info=z.getinfo(name)
   with z.open(info) as member,io.BufferedReader(member,8*1024**2) as stream:
    header=stream.peek(65536).split(b'\n',1)[0].decode('latin1').strip().replace('"','').split(';')
    keep=header
    if family=='candidates':keep=[c for c in header if c in ('ANO_ELEICAO','SG_UF','CD_CARGO','DS_CARGO','SQ_CANDIDATO','NR_CANDIDATO','NM_CANDIDATO','NM_URNA_CANDIDATO','NR_PARTIDO','SG_PARTIDO','NM_PARTIDO','DS_SITUACAO_CANDIDATURA','DS_SIT_TOT_TURNO','NR_TURNO')]
    reader=csv.open_csv(stream,read_options=csv.ReadOptions(encoding='latin1',block_size=8*1024**2),parse_options=csv.ParseOptions(delimiter=';'),convert_options=csv.ConvertOptions(column_types={c:pa.string() for c in header},include_columns=keep))
    for batch in reader:
     t=pa.Table.from_batches([batch]);cols=t.column_names
     if family in ('candidates','votes','bu'):
      cargo=next((c for c in ('DS_CARGO','DS_CARGO_PERGUNTA') if c in cols),None)
      if cargo:t=t.filter(pc.is_in(pc.utf8_upper(t[cargo]),value_set=pa.array(['PRESIDENTE','GOVERNADOR'])))
      elif 'CD_CARGO_PERGUNTA' in cols:t=t.filter(pc.is_in(t['CD_CARGO_PERGUNTA'],value_set=pa.array(['1','3'])))
      else:raise ValueError('Cargo não identificado: '+str(cols))
     if 'NR_TURNO' in cols and family!='candidates':t=t.filter(pc.equal(t['NR_TURNO'],'2'))
     if writer is None:writer=pq.ParquetWriter(out,t.schema,compression='zstd')
     writer.write_table(t);count+=len(t)
   if writer:writer.close()
   write_json(receipt,{'at':utcnow(),'family':family,'resource':entry['resource'],'member':name,'member_crc32':info.CRC,'http':remote.headers,'transport_bytes':remote.transferred,'capture_kind':'SCOPED_PROJECTED_RECORDS','sha256':sha256(out),'rows':count,'bytes':out.stat().st_size,'script_sha256':sha256(Path(__file__))})
  print(json.dumps({'family':family,'member':name,'rows':count,'bytes':out.stat().st_size}),flush=True)
