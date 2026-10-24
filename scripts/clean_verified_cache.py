"""Remove only redundant cache files whose identical raw copy is verified.

Never deletes raw, snapshots, reports, metadata or resumable partial downloads.
"""
import json
from pathlib import Path

from auditabr.utils import read_json, sha256, utcnow, write_json

root=Path('storage').resolve()
cache=(root/'cache').resolve()
assets={}
for receipt in (root/'manifests'/'assets').glob('*.json'):
    a=read_json(receipt)
    p=Path(a['path'])
    if p.exists():
        assets[a['sha256']]=p
removed=[]
for candidate in cache.rglob('*'):
    path=candidate.resolve()
    if not candidate.is_file() or candidate.suffix in ('.json','.part'):
        continue
    if cache not in path.parents:
        raise ValueError('Path outside cache')
    checksum=sha256(path)
    if checksum in assets and sha256(assets[checksum])==checksum:
        removed.append({'path':str(path),'bytes':path.stat().st_size,'sha256':checksum})
        path.unlink()
write_json(root/'manifests'/'cache-cleanup.json',{'at':utcnow(),'removed':removed})
print(json.dumps({'files':len(removed),'bytes_recovered':sum(r['bytes'] for r in removed)}))
