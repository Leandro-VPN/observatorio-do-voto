"""Independent HTTP Range log collector; method reviewed in ralbuque/esteleicao.
Defaults to all logs in the pilot; --limit is only a transport validation batch.
"""
import argparse
import threading
import time
import zipfile
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from auditabr.acquisition import RemoteZipReader
from auditabr.utils import read_json,write_json,sha256,utcnow
parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int);parser.add_argument('--connections',type=int,default=8);parser.add_argument('--root',default='research/piloto-ba-2022-t2');args=parser.parse_args()
if not 1<=args.connections<=8:raise ValueError('Use entre 1 e 8 conexões')
root=Path(args.root);target=root/'logs';target.mkdir(exist_ok=True)
e=next(e for e in read_json(root/'remote-inventory.json') if 'arqurnatot' in e['resource']['url'])
names=[m['name'] for m in e['members'] if m['name'].lower().endswith(('.logjez','-log.jez'))]
local=threading.local();handles=[];lock=threading.Lock()
def acquire(name):
 if Path(name).name!=name:raise ValueError('Nome inseguro')
 path=target/name;receipt=path.with_suffix(path.suffix+'.json')
 if path.exists() and receipt.exists() and sha256(path)==read_json(receipt)['sha256']:return 'REUSED'
 for attempt in range(4):
  try:
   if not hasattr(local,'archive'):
    remote=RemoteZipReader(e['resource']['url'],budget=4*1024**3)
    if remote.size!=e['container_bytes']:raise ValueError('Fonte mudou; atualizar inventário')
    local.remote=remote;local.archive=zipfile.ZipFile(remote)
    with lock:handles.append((local.archive,remote))
   info=local.archive.getinfo(name)
   if info.file_size>32*1024**2:raise ValueError('Log excede limite')
   remote=local.remote
   remote.seek(info.header_offset)
   block=remote.read(min(remote.size-info.header_offset,30+len(name.encode('utf-8'))+1024+info.compress_size))
   if block[:4]!=b'PK\x03\x04':raise ValueError('Cabeçalho ZIP inválido')
   n,x=struct.unpack('<HH',block[26:30]);start=30+n+x
   if len(block)<start+info.compress_size:
    remote.seek(info.header_offset+len(block));block+=remote.read(start+info.compress_size-len(block))
   compressed=block[start:start+info.compress_size]
   if info.compress_type==zipfile.ZIP_DEFLATED:content=zlib.decompress(compressed,-15)
   elif info.compress_type==zipfile.ZIP_STORED:content=compressed
   else:raise ValueError('Compressão não suportada')
   if len(content)!=info.file_size or zlib.crc32(content)&0xffffffff!=info.CRC:raise ValueError('CRC/tamanho divergente')
   part=path.with_suffix(path.suffix+'.part');part.write_bytes(content);part.replace(path)
   write_json(receipt,{'at':utcnow(),'source_url':e['resource']['url'],'resource_id':e['resource']['id'],'member':name,'crc32':info.CRC,'sha256':sha256(path),'bytes':len(content),'http':local.remote.headers})
   return 'DOWNLOADED'
  except Exception:
   if attempt==3:raise
   time.sleep(2**attempt)
counts={'DOWNLOADED':0,'REUSED':0};failures=[]
selected=names[:args.limit] if args.limit else names
try:
 with ThreadPoolExecutor(max_workers=args.connections) as executor:
  def guarded(name):
   try:return name,acquire(name),None
   except Exception as exc:return name,'FAILED',str(exc)
  for name,status,error in executor.map(guarded,selected):
   if error:failures.append({'member':name,'error':error})
   else:counts[status]+=1
   if (sum(counts.values())+len(failures))%50==0:print(counts,'failures',len(failures),flush=True)
finally:
 for archive,remote in handles:archive.close();remote.close()
result={'at':utcnow(),'expected':len(names),'selected':len(selected),'counts':counts,'failures':failures,'complete_scope':len(selected)==len(names) and not failures,'connections':args.connections,'method_reference':read_json(Path('research/references/esteleicao/reference.json'))['commit']}
write_json(root/'log-collection-run.json',result);print(result,flush=True)
if failures:raise SystemExit(1)
