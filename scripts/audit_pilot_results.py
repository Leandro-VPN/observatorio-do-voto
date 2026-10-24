"""Audit completed reconciliation and write compact reproducible findings."""
import json,re
from collections import Counter
from pathlib import Path
import duckdb
from auditabr.utils import read_json,write_json,sha256,utcnow
p=Path('research/piloto-ba-2022-t2')
r=read_json(p/'full-log-results.json');keys=Counter();statuses=Counter();mismatch=[];total=0
with (p/'parsed-log-index.jsonl').open(encoding='utf-8') as f:
 for line in f:
  x=json.loads(line);total+=1;statuses[x['status']]+=1
  if x['status']=='PARSED':
   key=tuple(x[k] for k in ('municipality','zone','section'));keys[key]+=1
   m=re.search(r'(\d{5})(\d{4})(\d{4})(?:\.logjez|-log\.jez)$',x['member'])
   if not m or tuple(map(int,m.groups()))!=key:mismatch.append(x['member'])
assert total==34424,total
assert not mismatch,mismatch[:10]
assert all(v==1 for v in keys.values()),'Duplicate section identities'
d=duckdb.connect();d.read_parquet(str(p/'log-bu-reconciliation.parquet')).create_view('r')
cur=d.execute('SELECT office,sum(vote_events)::BIGINT log_events,sum(present)::BIGINT bu_attendance,sum(votes)::BIGINT bu_votes,min(difference) min_difference,max(difference) max_difference FROM r GROUP BY office');sums=[dict(zip([x[0] for x in cur.description],row)) for row in cur.fetchall()]
r['audit']={'at':utcnow(),'records':total,'identity_matches_filename':True,'unique_verified_section_keys':len(keys),'status_counts':dict(statuses),'totals':sums,'source_capture_sha256':sha256(p/'captures/bweb_2t_BA_311020221535.parquet'),'count_parser_sha256':sha256(Path('scripts/pilot_log_count.py')),'outputs':{name:sha256(p/name) for name in ('parsed-log-index.jsonl','log-bu-reconciliation.csv','log-bu-reconciliation.parquet')}}
write_json(p/'full-log-results.json',r)
text=['# Piloto Bahia/2022/2º turno — coleta e reconciliação','',f'Concluído em {r["audit"]["at"]}. Coleta de 34.424 logs oficiais por HTTP Range, oito conexões e retomada por arquivo.','',f'Situações do parser: {dict(statuses)}. Identidades inequívocas verificadas contra os nomes dos arquivos, sem duplicação: {len(keys)}.','']
for row in r['reconciliation']:text.append(f'- {row["office"] or "Sem casamento seguro"}: {row["compared"]} registros; {row["equal"]} iguais ao comparecimento do BU; {row["different"]} diferentes; {row["unavailable"]} sem comparação disponível.')
text+=['','As linhas por cargo não devem ser somadas como eleitores: o mesmo log é comparado separadamente ao BU de cada disputa. Eventos contados são conclusões registradas em 30/10/2022; não são votos atribuídos a candidatos.','', 'Diferenças podem envolver cobertura do log, contingência, agregação e limitações do parser. Não são prova de irregularidade. Relógio e taxonomia não foram validados; B/C/D e associações partidárias continuam indisponíveis. Este resultado conclui a coleta dos logs e a conferência de contagens, não todo o protocolo inferencial.','', 'Evidências: full-log-results.json; log-bu-reconciliation.csv; log-bu-reconciliation.parquet. Scripts: scripts/collect_pilot_logs.py, scripts/process_pilot_logs.py, scripts/pilot_log_count.py e scripts/audit_pilot_results.py.']
(p/'RESULTADOS_LOGS.md').write_text('\n'.join(text),encoding='utf-8');print(json.dumps(r,ensure_ascii=True))
