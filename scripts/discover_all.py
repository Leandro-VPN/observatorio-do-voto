"""Coleta apenas metadados; resultados de cada ano são persistidos separadamente."""
import json
from pathlib import Path

from auditabr.catalog import Catalog, family
from auditabr.domain import YEARS
from auditabr.utils import utcnow, write_json

root = Path("storage")
catalog = Catalog(root)
summary = []
for year in YEARS:
    try:
        data = catalog.discover(year)
        resources = catalog.resources(year)
        entry = {"year": year, "datasets": len(data["datasets"]), "resources": len(resources),
                 "status": data["status"], "catalog_hash": data["catalog_hash"]}
        print(json.dumps(entry), flush=True)
        for resource in resources:
            if family(resource) in ("turnout", "votes"):
                print(json.dumps({k: resource.get(k) for k in ("id", "name", "url", "size")}), flush=True)
        summary.append(entry)
    except Exception as exc:
        entry = {"year": year, "status": "FAILED", "error": str(exc)}
        print(json.dumps(entry), flush=True)
        summary.append(entry)
write_json(root / "manifests" / "discovery_summary.json", {"as_of": utcnow(), "years": summary})

