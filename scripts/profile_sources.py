"""Inspeciona índices/cabeçalhos oficiais; nenhum conteúdo eleitoral é fabricado."""
import json
import zipfile
from pathlib import Path

from auditabr.acquisition import RemoteZipReader, safe_members
from auditabr.catalog import Catalog, family
from auditabr.utils import utcnow, write_json

root = Path("storage")
catalog = Catalog(root)
out = []
for year, uf in [(2022, "MA"), (2024, "AC"), (2012, "AC"), (2018, "AC"), (2026, "AC")]:
    resources = catalog.resources(year)
    selected = [r for r in resources if family(r) == "turnout" or
                (family(r) == "votes" and f"_{uf}.zip" in r["url"])]
    for r in selected:
        try:
            with RemoteZipReader(r["url"], budget=4 * 1024**2) as remote:
                with zipfile.ZipFile(remote) as archive:
                    entries = safe_members(archive)
                    candidates = [i for i in entries if i.filename.lower().endswith((".csv", ".txt"))
                                  and (f"_{uf}." in i.filename or len(entries) < 4)]
                    entry = {"year": year, "uf": uf, "resource_id": r["id"], "family": family(r),
                             "url": r["url"], "container_size": remote.size,
                             "members": [{"name": i.filename, "bytes": i.file_size, "compressed": i.compress_size} for i in entries]}
                    if candidates:
                        with archive.open(candidates[0]) as stream:
                            sample = stream.read(4096).decode("latin-1")
                        entry["sample"] = sample.splitlines()[:3]
                    out.append(entry)
                    print(json.dumps(entry, ensure_ascii=True), flush=True)
        except Exception as exc:
            print(json.dumps({"year": year, "resource_id": r["id"], "error": str(exc)}), flush=True)
write_json(root / "bronze" / "source_profiles.json", {"observed_at": utcnow(), "profiles": out})
