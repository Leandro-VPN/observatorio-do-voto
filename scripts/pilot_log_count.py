"""Count-only reconciliation parser: fixed election day, exact completion event."""
import re
from auditabr.parsers import normalized
VERSION='log-count-2022-1'
def parse_count(data):
 try:text=data.decode('utf-8-sig')
 except UnicodeDecodeError:text=data.decode('latin1')
 identities={};count=0
 for line in text.splitlines():
  fields=line.split('\t',5)
  if len(fields)<5:continue
  if fields[3]=='GAP':
   msg=normalized(fields[4])
   for label,key in [('MUNICIPIO','municipality'),('ZONA ELEITORAL','zone'),('SECAO ELEITORAL','section')]:
    if msg.startswith(label+':'):
     m=re.match(r'\s*(\d+)',msg.split(':',1)[1])
     if m:identities.setdefault(key,set()).add(int(m[1]))
  if fields[0].startswith('30/10/2022 ') and fields[3]=='VOTA' and fields[4]=='O voto do eleitor foi computado':count+=1
 identity={k:next(iter(v)) for k,v in identities.items() if len(v)==1}
 return {'status':'PARSED' if len(identity)==3 else 'AMBIGUOUS_IDENTITY',**identity,'vote_events':count,'clock_quality':'UNKNOWN','taxonomy_status':'UNVERIFIED'}
