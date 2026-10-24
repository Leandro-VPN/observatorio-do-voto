import json
import zipfile

from auditabr.acquisition import RemoteZipReader, fetch_member, safe_members
from auditabr.catalog import Catalog, family
from auditabr.utils import read_json, storage_root, write_json

root = storage_root()
catalog = Catalog(root)
for year in (2022, 2024, 2026):
    resource = next(r for r in catalog.resources(year) if family(r) == "logs" and "1t_AC" in r["url"])
    destination = root / "cache" / f"log-sample-{year}.json"
    if destination.exists():
        print(json.dumps(read_json(destination)), flush=True)
        continue
    with RemoteZipReader(resource["url"], budget=16 * 1024**2) as remote:
        with zipfile.ZipFile(remote) as archive:
            members = [i for i in safe_members(archive) if "log" in i.filename.lower() and not i.is_dir()]
            # Smallest complete log container, never truncates a log and claims completeness.
            member = min(members, key=lambda i: i.file_size)
            print(json.dumps({"year": year, "member": member.filename, "bytes": member.file_size,
                              "log_members": len(members), "container_bytes": remote.size}), flush=True)
    receipt = fetch_member(root, resource, member.filename, budget=16 * 1024**2)
    write_json(destination, receipt)
    print(json.dumps(receipt), flush=True)
