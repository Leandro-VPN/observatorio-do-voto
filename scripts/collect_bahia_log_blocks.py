"""Bounded Range batches; keep only required compressed log containers on disk."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import struct
import threading
import time
import zipfile
import zlib

from auditabr.acquisition import RemoteZipReader
from auditabr.utils import read_json, sha256, utcnow, write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--connections',type=int,default=4)
    args=parser.parse_args()
    root=Path(args.root);target=root/'logs';target.mkdir(exist_ok=True)
    e=read_json(root/'remote-inventory.json')[0]
    with RemoteZipReader(e['resource']['url'],budget=64*1024**2) as remote,zipfile.ZipFile(remote) as archive:
        infos=sorted([i for i in archive.infolist() if i.filename.lower().endswith(('.logjez','-log.jez'))],key=lambda i:i.header_offset)
        assert remote.size==e['container_bytes']
    state=threading.local();handles=[];lock=threading.Lock()
    def batch(infos):
        missing=[];reused=0
        for info in infos:
            if Path(info.filename).name!=info.filename or info.file_size>32*1024**2:
                raise ValueError('Unsafe log member')
            path=target/info.filename;receipt=path.with_suffix(path.suffix+'.json')
            try:
                ok=path.exists() and receipt.exists() and sha256(path)==read_json(receipt)['sha256']
            except ValueError:
                ok=False
            if ok:
                reused+=1
            else:
                missing.append(info)
        if not missing:
            return 0,reused,0
        begin=missing[0].header_offset
        end=min(e['container_bytes'],missing[-1].header_offset+missing[-1].compress_size+2048)
        if end-begin>32*1024**2:
            if len(infos)==1:
                raise ValueError('Range exceeds 32 MiB')
            a=batch(infos[:len(infos)//2]);b=batch(infos[len(infos)//2:])
            return tuple(x+y for x,y in zip(a,b))
        for attempt in range(4):
            try:
                if not hasattr(state,'remote'):
                    state.remote=RemoteZipReader(e['resource']['url'],budget=8*1024**3)
                    assert state.remote.size==e['container_bytes']
                    with lock:handles.append(state.remote)
                remote=state.remote;remote.seek(begin);block=remote.read(end-begin)
                for info in missing:
                    offset=info.header_offset-begin
                    if block[offset:offset+4]!=b'PK\x03\x04':raise ValueError('Invalid local header')
                    n,x=struct.unpack('<HH',block[offset+26:offset+30]);start=offset+30+n+x
                    compressed=block[start:start+info.compress_size]
                    if info.compress_type==zipfile.ZIP_DEFLATED:content=zlib.decompress(compressed,-15)
                    elif info.compress_type==zipfile.ZIP_STORED:content=compressed
                    else:raise ValueError('Unsupported compression')
                    assert len(content)==info.file_size and zlib.crc32(content)&0xffffffff==info.CRC
                    path=target/info.filename;part=path.with_suffix(path.suffix+'.part')
                    part.write_bytes(content);part.replace(path)
                    write_json(path.with_suffix(path.suffix+'.json'),{'at':utcnow(),'source_url':e['resource']['url'],
                        'resource_id':e['resource']['id'],'member':info.filename,'crc32':info.CRC,
                        'sha256':sha256(path),'bytes':len(content),'http':remote.headers,
                        'range_start':begin,'range_end_exclusive':end,'method':'BOUNDED_RANGE_BATCH_ONLY_LOGS_RETAINED'})
                return len(missing),reused,len(block)
            except Exception:
                if attempt==3:raise
                time.sleep(2**attempt)
    counts={'DOWNLOADED':0,'REUSED':0};failures=[];transferred=0;start=time.monotonic()
    def guarded(group):
        try:return batch(group),None
        except Exception as exc:return (0,0,0),{'members':[i.filename for i in group],'error':str(exc)}
    groups=[infos[i:i+32] for i in range(0,len(infos),32)]
    try:
        with ThreadPoolExecutor(max_workers=args.connections) as pool:
            for i,(result,error) in enumerate(pool.map(guarded,groups),1):
                counts['DOWNLOADED']+=result[0];counts['REUSED']+=result[1];transferred+=result[2]
                if error:failures.append(error)
                if i%32==0 or i==len(groups):
                    print({'root':root.name,'done':sum(counts.values()),'expected':len(infos),'failures':len(failures),'seconds':round(time.monotonic()-start)},flush=True)
    finally:
        for remote in handles:remote.close()
    write_json(root/'log-collection-run.json',{'at':utcnow(),'expected':len(infos),'selected':len(infos),
        'counts':counts,'failures':failures,'complete_scope':not failures and sum(counts.values())==len(infos),
        'method':'Bounded Range batches; adjacent compressed bytes may transit memory, only logs saved',
        'connections':args.connections,'batch_transfer_bytes':transferred,'script_sha256':sha256(Path(__file__))})
    if failures:raise RuntimeError(f'{len(failures)} batches failed; rerun resumes verified files')


if __name__=='__main__':main()
