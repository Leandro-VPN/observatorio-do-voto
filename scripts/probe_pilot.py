import zipfile,json
from pathlib import Path
from auditabr.catalog import Catalog
from auditabr.acquisition import RemoteZipReader
from auditabr.utils import storage_root,write_json
root=Path('research/piloto-ba-2022-t2'); cat=Catalog(storage_root());out=[]
for rid in ['435145fd-bc9d-446a-ac9d-273f585a0bb9','aca0a7a4-8d07-4d59-affe-98ca29809226','2c8f2a51-5614-43bf-b069-5629a76708ef','7b6e7ebb-f701-41cc-aef0-04c15ed64968','5ddc12f6-afad-49bf-872a-cb2e0f3797fc','c2579fb8-38c5-45b0-846a-d56ec51ba1a1']:
 r=cat.resource(rid)
 with RemoteZipReader(r['url'],budget=64*1024**2) as remote,zipfile.ZipFile(remote) as z:
  members=[{'name':i.filename,'bytes':i.file_size,'compressed':i.compress_size} for i in z.infolist() if not i.is_dir()]
  entry={'resource':r,'container_bytes':remote.size,'members':members};out.append(entry)
  print(json.dumps({'id':rid,'bytes':remote.size,'members':len(members),'sample':members[:3]},ensure_ascii=True),flush=True)
 write_json(root/'remote-inventory.json',out)
