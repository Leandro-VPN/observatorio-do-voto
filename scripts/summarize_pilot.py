import json
from pathlib import Path
import duckdb
from auditabr.utils import read_json,write_json,sha256,utcnow
from auditabr.logs import read_log,parse_log
p=Path('research/piloto-ba-2022-t2');c=p/'captures';d=duckdb.connect()
def query(sql):
 cur=d.execute(sql);return [dict(zip([x[0] for x in cur.description],r)) for r in cur.fetchall()]
d.read_parquet(str(c/'bweb_2t_BA_311020221535.parquet')).create_view('bu')
d.read_parquet(str(c/'votacao_secao_2022_BA.parquet')).create_view('votes')
d.read_parquet(str(c/'consulta_cand_2022_*.parquet')).create_view('candidates')
parties=query("SELECT DISTINCT DS_CARGO,NR_CANDIDATO,NM_URNA_CANDIDATO,NR_PARTIDO,SG_PARTIDO FROM candidates WHERE NR_TURNO='2' ORDER BY DS_CARGO,NR_CANDIDATO")
write_json(p/'party-mapping.json',{'at':utcnow(),'mapping':parties,'sources':[read_json(f) for f in c.glob('consulta*.json')]})
summary=query("SELECT DS_CARGO_PERGUNTA cargo,SG_PARTIDO partido,NM_VOTAVEL candidato,NR_VOTAVEL numero,sum(cast(QT_VOTOS AS BIGINT)) votos FROM bu WHERE CD_TIPO_VOTAVEL='1' GROUP BY ALL ORDER BY cargo,votos DESC")
recon=query("""WITH b AS (SELECT CD_MUNICIPIO,NR_ZONA,NR_SECAO,CD_CARGO_PERGUNTA cargo,NR_VOTAVEL,sum(cast(QT_VOTOS AS BIGINT)) n FROM bu WHERE CD_CARGO_PERGUNTA='3' GROUP BY ALL),v AS (SELECT CD_MUNICIPIO,NR_ZONA,NR_SECAO,CD_CARGO cargo,NR_VOTAVEL,sum(cast(QT_VOTOS AS BIGINT)) n FROM votes WHERE CD_CARGO='3' GROUP BY ALL) SELECT count(*) keys_compared,count(*) FILTER(WHERE b.n IS DISTINCT FROM v.n) differences FROM b FULL JOIN v USING(CD_MUNICIPIO,NR_ZONA,NR_SECAO,cargo,NR_VOTAVEL)""")
r=read_json(p/'log-parser-sample.json')['receipt'];log=parse_log(read_log(Path(r['path'])),2022,2,r['sha256']);ids=log['identities'];print('log_identity',ids)
logbu=query("SELECT DS_CARGO_PERGUNTA cargo,max(cast(QT_COMPARECIMENTO AS BIGINT)) comparecimento,sum(cast(QT_VOTOS AS BIGINT)) votos FROM bu WHERE cast(CD_MUNICIPIO AS INT)=34134 AND cast(NR_ZONA AS INT)=171 AND cast(NR_SECAO AS INT)=232 GROUP BY ALL")
checks=[{'path':str(f),'hash_ok':sha256(f.with_suffix('.parquet'))==read_json(f)['sha256']} for f in c.glob('*.json')];assert all(x['hash_ok'] for x in checks)
report={'at':utcnow(),'status':'INITIAL_COLLECTION_NOT_COMPLETE_PILOT','party_results_descriptive_only':summary,'governor_BU_vs_section_votes':recon,'sample_log':{'identities':ids,'metrics':log['metric'],'bu':logbu,'representative':False},'hash_checks':checks,'capture_bytes':sum(f.stat().st_size for f in c.glob('*.parquet')),'remaining':['complete logs acquisition and classification validation','special/transit exclusions','aggregation denominator reconstruction','biometrics active and operational controls','matching and adjusted models','pilot review before scaling']}
write_json(p/'collection-results.json',report)
print(json.dumps({'parties':parties,'descriptive_results':summary,'reconciliation':recon,'sample_vote_events':log['metric']['vote_events'],'sample_bu':logbu,'capture_bytes':report['capture_bytes']},ensure_ascii=True))
