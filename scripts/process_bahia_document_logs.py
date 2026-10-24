"""Year-specific operational adapters; compact results, no voter identifiers."""
import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import json
from pathlib import Path
import re
import time

import analyze_pilot_operations as engine
from pilot_log_count import parse_count
from auditabr.logs import read_log
from auditabr.utils import read_json, sha256, utcnow, write_json

VERSION='bahia-document-log-2'
ROOT=None
YEAR=None


def initialize(root,year):
    global ROOT,YEAR
    ROOT=Path(root);YEAR=year
    engine.DAY='02/10/2022 ' if year==2022 else '04/10/2026 '


def process(name):
    path=ROOT/'logs'/name;dest=ROOT/'operational-logs'/(name+'.json')
    if dest.exists():
        saved=read_json(dest)
        if saved.get('parser_version')==VERSION and saved.get('status')=='PARSED':return 'REUSED'
    try:
        receipt=read_json(path.with_suffix(path.suffix+'.json'))
        assert sha256(path)==receipt['sha256']
        data=read_log(path)
        identities=parse_count(data)
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:text=data.decode('latin1')
        independent=sum(1 for line in text.splitlines() if line.startswith(engine.DAY)
                        and len(f:=line.split('\t',5))>=5 and f[3]=='VOTA' and f[4]=='O voto do eleitor foi computado')
        metrics=engine.parse(data,day=engine.DAY,allow_named_authorization=YEAR==2026,allow_unattributed=YEAR==2026)
        assert metrics['vote_events']==independent
        metrics['worker_authorization_markers']=metrics.pop('worker_fingerprint_captures')
        record={'status':'PARSED','parser_version':VERSION,'year':YEAR,'round':1,'member':name,
            'source_sha256':receipt['sha256'],'identity_status':identities['status'],
            **{k:identities.get(k) for k in ('municipality','zone','section')},**metrics,
            'manual_rule':'REQUEST_CAPTURE_ENABLED_VOTE' if YEAR==2022 else 'REQUEST_AUTHORIZATION_OR_UNATTRIBUTED_CAPTURE_ENABLED_VOTE; unattributed count separate'}
        write_json(dest,record)
        return 'PARSED'
    except Exception as exc:
        write_json(dest,{'status':'FAILED','member':name,'error':str(exc),'parser_version':VERSION})
        return 'FAILED'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--year',type=int,choices=[2022,2026],required=True)
    parser.add_argument('--limit',type=int);parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();root=Path(f'research/bahia-presidente-2022-2026/{args.year}-t1')
    (root/'operational-logs').mkdir(exist_ok=True)
    all_names=[m['name'] for m in read_json(root/'remote-inventory.json')[0]['members'] if m['name'].lower().endswith(('.logjez','-log.jez'))]
    names=all_names[:args.limit] if args.limit else all_names
    done=set();start=time.monotonic();failures=0
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(str(root),args.year)) as pool:
        while len(done)<len(names):
            available=[n for n in names if n not in done and (root/'logs'/(n+'.json')).exists()]
            if not available:
                run=root/'log-collection-run.json'
                if run.exists() and read_json(run).get('failures'):break
                time.sleep(3);continue
            for name,status in zip(available,pool.map(process,available,chunksize=8)):
                done.add(name);failures+=int(status=='FAILED')
                if len(done)%1000==0 or len(done)==len(names):
                    print({'year':args.year,'processed':len(done),'expected':len(names),'failures':failures,'seconds':round(time.monotonic()-start)},flush=True)
    if not args.limit:
        with (root/'operations.jsonl').open('w',encoding='utf-8') as stream,ThreadPoolExecutor(max_workers=8) as pool:
            for record in pool.map(lambda n:read_json(root/'operational-logs'/(n+'.json')),names):
                stream.write(json.dumps(record,ensure_ascii=False)+'\n')
    write_json(root/'processing-run.json',{'at':utcnow(),'expected':len(all_names),'selected':len(names),'processed':len(done),
        'failures':failures,'complete_scope':len(done)==len(all_names) and failures==0,'parser_version':VERSION,
        'script_sha256':sha256(Path(__file__)),'engine_sha256':sha256(Path(engine.__file__)),
        'manual_taxonomy':'Observed per-year sequence; verify against official BU non-biometric habilitation counts'})


if __name__=='__main__':main()
