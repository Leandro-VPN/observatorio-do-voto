"""Publish the three acquired real log samples, then record reproducible evidence."""
import json
import time
from pathlib import Path

from auditabr.catalog import Catalog
from auditabr.domain import YEARS
from auditabr.logs import ingest_log
from auditabr.queries import Scope, analysis, turnout
from auditabr.reporting import create_report
from auditabr.storage import current_manifest, reader, rows
from auditabr.utils import read_json, sha256, utcnow, write_json

root = Path("storage")
if (root / "writer.lock").exists():
    raise SystemExit("Aguarde o coletor encerrar antes de publicar as amostras de logs")

# Retain observations from the bootstrap process started before this handler existed.
for line in (root / "bootstrap-focused.log").read_text(encoding="utf-8-sig").splitlines():
    try:
        observation = json.loads(line)
    except json.JSONDecodeError:
        continue
    if observation.get("status") in ("FAILED", "NOT_APPLICABLE") and "round" in observation:
        write_json(root / "coverage" / "{year}-{round}-{uf}-{family}.json".format(**observation), observation)

for year, municipality, zone, section in ((2022, "01392", "0009", "0463"),
                                          (2024, "01570", "0006", "0114"),
                                          (2026, "01538", "0008", "0207")):
    receipt = read_json(root / "cache" / f"log-sample-{year}.json")
    with reader(root) as db:
        exists = db.execute("SELECT 1 FROM operational_section_metrics WHERE asset_id=?", [receipt["sha256"]]).fetchone()
    if not exists:
        ingest_log(root, receipt, year, 1, "AC", municipality, zone, section)

manifest = current_manifest(root)
assert manifest is not None
snapshot = manifest["snapshot_id"]
with reader(root, snapshot) as db:
    totals = rows(db, """SELECT year,round,uf,count(*) sections,sum(eligible)::BIGINT eligible,
        sum(present)::BIGINT present,sum(absent)::BIGINT absent FROM section_turnout GROUP BY ALL ORDER BY ALL""")
    votes = rows(db, "SELECT year,round,uf,office,count(*) candidate_rows,sum(votes)::BIGINT votes FROM candidate_vote GROUP BY ALL ORDER BY ALL")
    logs = rows(db, """SELECT o.year,o.section_id,o.vote_events,s.present,o.clock_quality,o.taxonomy_status,
        o.biometric,o.manual,o.after_cutoff FROM operational_section_metrics o
        LEFT JOIN section_turnout s USING(section_id) ORDER BY o.year""")
    issues = rows(db, "SELECT family,code,count(*) records FROM quality_issue GROUP BY ALL ORDER BY ALL")
    assert db.execute("SELECT count(*) FROM candidate_vote WHERE office NOT IN ('PRESIDENTE','PREFEITO')").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM section_turnout WHERE eligible!=present+absent").fetchone()[0] == 0

checks = [{"file": str(root / "gold" / f"{snapshot}.duckdb"),
           "ok": sha256(root / "gold" / f"{snapshot}.duckdb") == manifest["database_sha256"]}]
for asset in manifest["sources"]:
    checks.append({"file": asset["path"], "ok": sha256(Path(asset["path"])) == asset["sha256"]})
assert all(c["ok"] for c in checks)

benchmarks = []
for name, fn in (("aggregate_ma2022", turnout), ("score_ma2022", analysis)):
    start = time.perf_counter()
    result = fn(root, Scope(year=2022, uf="MA", snapshot=snapshot))
    benchmarks.append({"operation": name, "seconds": time.perf_counter()-start,
                       "returned_rows": len(result["data"]), "method": "single warm local invocation"})

reports = []
for year, uf in ((2022, "MA"), (2024, "AC")):
    for turn in (1, 2):
        report = create_report(root, Scope(year=year, round=turn, uf=uf, snapshot=snapshot))
        reports.append({"year": year, "round": turn, "uf": uf, "report_id": report["report_id"]})

catalog = Catalog(root)
inventory = [{"year": y, "datasets": len(read_json(root / "catalog" / f"{y}.json")["datasets"]),
              "resources": len(catalog.resources(y))} for y in YEARS]
storage = {folder: sum(p.stat().st_size for p in (root / folder).rglob("*") if p.is_file())
           for folder in ("raw", "silver", "gold", "cache", "reports")}
evidence = {"at": utcnow(), "snapshot_id": snapshot, "totals": totals, "votes": votes, "logs": logs,
            "quality_issues": issues, "catalog": inventory, "hash_checks": checks, "benchmarks": benchmarks,
            "reports": reports, "storage_bytes": storage,
            "collection_observations": [read_json(p) for p in (root / "coverage").glob("*.json")]}
write_json(root / "manifests" / "execution-evidence.json", evidence)
print(f"Snapshot validado: {snapshot}; {len(checks)} hashes; {len(reports)} relatórios", flush=True)
