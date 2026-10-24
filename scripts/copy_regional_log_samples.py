"""Preserve only the three already acquired in-scope samples; no additional download."""
from pathlib import Path

from auditabr.acquisition import preserve_asset
from auditabr.logs import ingest_log
from auditabr.storage import reader
from auditabr.utils import read_json, storage_root

root = storage_root()
if (root/"writer.lock").exists():
    raise SystemExit("Aguarde o coletor terminar")
for year,municipality,zone,section in ((2022,"01392","0009","0463"),(2024,"01570","0006","0114"),(2026,"01538","0008","0207")):
    prior = read_json(Path("storage/cache")/f"log-sample-{year}.json")
    resource = {"id":prior["resource_id"],"dataset_id":prior["dataset_id"],"url":prior["source_url"],
                "page_url":prior.get("page_url"),"catalog_hash":prior.get("catalog_hash"),"license":prior.get("license")}
    asset = preserve_asset(root,Path(prior["path"]),resource,{"acquisition":"VERIFIED_LOCAL_REUSE","parent_receipt":prior})
    with reader(root) as db:
        exists=db.execute("SELECT 1 FROM operational_section_metrics WHERE asset_id=?",[asset["sha256"]]).fetchone()
    if not exists:
        ingest_log(root,asset,year,1,"AC",municipality,zone,section)
    print(f"Log {year} preservado no recorte regional",flush=True)
