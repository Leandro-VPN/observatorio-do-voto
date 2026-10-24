"""Incremental, resumable log parsing and log/BU reconciliation; no party inference."""
import json,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import duckdb
from auditabr.logs import read_log
from pilot_log_count import parse_count,VERSION
from auditabr.utils import read_json,write_json,sha256,utcnow
ROOT=Path('research/piloto-ba-2022-t2')
def process(receipt):
 r=read_json(receipt);path=receipt.with_suffix('');out=ROOT/'parsed-logs'/(path.name+'.json')
 if out.exists():return
 try:
  assert sha256(path)==r['sha256']
  m=parse_count(read_log(path));identity={k:m[k] for k in ('municipality','zone','section') if k in m}
  write_json(out,{'member':path.name,'sha256':r['sha256'],'parser_version':VERSION,'status':'PARSED' if len(identity)==3 else 'AMBIGUOUS_IDENTITY',**identity,**m})
 except Exception as exc:write_json(out,{'member':path.name,'sha256':r['sha256'],'status':'PARSE_FAILED','error':str(exc)})
def summarize(rebuild_index=True):
 d=duckdb.connect();d.execute("SET memory_limit='512MB'")
 compact=ROOT/'parsed-log-index.jsonl'
 fields=['member','sha256','parser_version','status','municipality','zone','section','vote_events','clock_quality','taxonomy_status']
 if rebuild_index:
  with compact.open('w',encoding='utf-8') as stream:
   for path in sorted((ROOT/'parsed-logs').glob('*.json')):
    record=read_json(path)
    stream.write(json.dumps({k:record.get(k) for k in fields})+'\n')
 d.read_json(str(compact),format='newline_delimited').create_view('logs')
 d.read_parquet(str(ROOT/'captures/bweb_2t_BA_311020221535.parquet')).create_view('bu')
 d.execute("""CREATE TABLE reconciled AS WITH b AS (SELECT cast(CD_MUNICIPIO AS INT) municipality,cast(NR_ZONA AS INT) AS "zone",cast(NR_SECAO AS INT) section,DS_CARGO_PERGUNTA office,max(cast(QT_COMPARECIMENTO AS BIGINT)) present,sum(cast(QT_VOTOS AS BIGINT)) votes FROM bu GROUP BY ALL) SELECT l.member,l.sha256,l.status,l.municipality,l.zone,l.section,b.office,l.vote_events,b.present,b.votes,l.vote_events-b.present difference,l.clock_quality,l.taxonomy_status FROM logs l LEFT JOIN b USING(municipality,zone,section)""")
 d.execute(f"COPY reconciled TO '{(ROOT/'log-bu-reconciliation.parquet').as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)")
 d.execute(f"COPY reconciled TO '{(ROOT/'log-bu-reconciliation.csv').as_posix()}' (HEADER,DELIMITER ';')")
 def rows(sql):
  cur=d.execute(sql);return [dict(zip([c[0] for c in cur.description],r)) for r in cur.fetchall()]
 result={'at':utcnow(),'collection':read_json(ROOT/'log-collection-run.json'),'logs':rows('SELECT status,count(*) files,sum(vote_events) vote_events FROM logs GROUP BY status'),'reconciliation':rows('SELECT office,count(*) compared,count(*) FILTER(WHERE difference=0) equal,count(*) FILTER(WHERE difference!=0) different,count(*) FILTER(WHERE difference IS NULL) unavailable FROM reconciled GROUP BY office'),'limits':['Neither missing nor zero-event logs prove electoral irregularity','Clock and taxonomy not validated: B/C/D and party associations unavailable','Special sections, transit, aggregation and mandatory controls still require validation'],'script_sha256':sha256(Path(__file__)),'count_parser_sha256':sha256(Path(__file__).with_name('pilot_log_count.py'))}
 write_json(ROOT/'full-log-results.json',result);print(json.dumps(result,ensure_ascii=True),flush=True)
if __name__=='__main__':
 (ROOT/'parsed-logs').mkdir(exist_ok=True)
 with ProcessPoolExecutor(max_workers=4) as pool:
  while True:
   pending=[p for p in (ROOT/'logs').glob('*.json') if not (ROOT/'parsed-logs'/p.name).exists()]
   for _ in pool.map(process,pending,chunksize=8):pass
   print('parsed',len(list((ROOT/'parsed-logs').glob('*.json'))),flush=True)
   run=read_json(ROOT/'log-collection-run.json')
   if run['selected']==run['expected'] and not pending:break
   time.sleep(10)
 summarize()
