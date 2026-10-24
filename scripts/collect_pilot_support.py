"""Only small official documentation and effective correspondence for BA2022T2."""
import json
from pathlib import Path
import zipfile

from auditabr.acquisition import RemoteZipReader
from auditabr.utils import sha256, utcnow, write_json

root = Path('research/piloto-ba-2022-t2')
out = root / 'support'
out.mkdir(exist_ok=True)
inventory = json.loads((root/'remote-inventory.json').read_text(encoding='utf-8'))
for entry in inventory:
    url = entry['resource']['url']
    if not any(key in url for key in ('/buweb/', '/correspefet/')):
        continue
    names = [m['name'] for m in entry['members'] if m['name'].endswith('.pdf') or '/correspefet/' in url]
    for name in names:
        target = out / Path(name).name
        receipt = target.with_suffix(target.suffix+'.json')
        if target.exists() and receipt.exists() and sha256(target) == json.loads(receipt.read_text())['sha256']:
            continue
        with RemoteZipReader(url, budget=10*1024**2) as remote, zipfile.ZipFile(remote) as archive:
            target.write_bytes(archive.read(name))
            write_json(receipt, {'at': utcnow(), 'url': url, 'member': name,
                       'sha256': sha256(target), 'bytes': target.stat().st_size,
                       'transport_bytes': remote.transferred, 'http': remote.headers})
            print(name, target.stat().st_size, flush=True)
