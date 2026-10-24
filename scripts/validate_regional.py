"""Independent SQL reconciliation of every projected capture against published facts."""
import json
import time
from pathlib import Path

import duckdb

from auditabr.domain import UFS, YEARS, temporal_status
from auditabr.queries import Scope, turnout
from auditabr.storage import current_manifest, reader, rows
from auditabr.utils import read_json, sha256, storage_root, utcnow, write_json

root = storage_root()
manifest = current_manifest(root)
assert manifest is not None
snapshot = manifest["snapshot_id"]
assets = {}
for path in (root/"captures").glob("*.json"):
    for asset in read_json(path)["assets"].values():
        assets[(asset["year"],asset["uf"],asset["family"])]=asset

checks = []
with reader(root,snapshot) as published, duckdb.connect(":memory:") as independent:
    independent.execute("SET memory_limit='512MB'")
    coverage = rows(published,"SELECT * FROM partition_registry ORDER BY year,round,uf,family")
    present = {(r["year"],r["round"],r["uf"],r["family"]) for r in coverage}
    missing = [(y,uf,kind) for y in YEARS for uf in sorted(UFS) for kind in ("turnout","votes")
               if (y,1,uf,kind) not in present]
    for (year,uf,kind),asset in sorted(assets.items()):
        if sha256(Path(asset["path"])) != asset["sha256"]:
            raise ValueError(f"Hash da captura diverge: {asset['path']}")
        relation = independent.read_parquet(asset["path"])
        relation.create_view("capture",replace=True)
        columns = relation.columns
        states = independent.execute("SELECT DISTINCT SG_UF FROM capture").fetchall()
        offices = independent.execute("SELECT DISTINCT upper(DS_CARGO) FROM capture").fetchall()
        assert all(state==uf for (state,) in states), states
        assert all(office==("PREFEITO" if year%4==0 else "PRESIDENTE") for (office,) in offices), offices
        if kind=="turnout":
            expected = independent.execute("""SELECT cast(NR_TURNO AS INTEGER),count(*),sum(n),sum(p),sum(a) FROM (
                SELECT DISTINCT NR_TURNO,cast(CD_MUNICIPIO AS INTEGER),cast(NR_ZONA AS INTEGER),cast(NR_SECAO AS INTEGER),
                 try_cast(QT_APTOS AS BIGINT) n,try_cast(QT_COMPARECIMENTO AS BIGINT) p,try_cast(QT_ABSTENCOES AS BIGINT) a
                FROM capture WHERE n>=0 AND p>=0 AND a>=0 AND n=p+a) GROUP BY NR_TURNO""").fetchall()
            actual = published.execute("SELECT round,count(*),sum(eligible),sum(present),sum(absent) FROM section_turnout WHERE year=? AND uf=? GROUP BY round",[year,uf]).fetchall()
        else:
            candidate = "coalesce(nullif(nullif(nullif(SQ_CANDIDATO,'#NULO#'),'-1'),'-3'),NR_VOTAVEL)" if "SQ_CANDIDATO" in columns else "NR_VOTAVEL"
            status = "coalesce(nullif(nullif(DS_SIT_TOT_TURNO,'#NULO#'),''),'AS_PUBLISHED')" if "DS_SIT_TOT_TURNO" in columns else "'AS_PUBLISHED'"
            expected = independent.execute(f"""SELECT cast(NR_TURNO AS INTEGER),count(*),sum(votes) FROM (
                 SELECT NR_TURNO,cast(CD_MUNICIPIO AS INTEGER),cast(NR_ZONA AS INTEGER),cast(NR_SECAO AS INTEGER),
                 {candidate} candidate,{status} status,max(cast(QT_VOTOS AS BIGINT)) votes
                 FROM capture GROUP BY ALL) GROUP BY NR_TURNO""").fetchall()
            actual = published.execute("SELECT round,count(*),sum(votes) FROM candidate_vote WHERE year=? AND uf=? GROUP BY round",[year,uf]).fetchall()
        expected = sorted(expected)
        actual = sorted(actual)
        checks.append({"year":year,"uf":uf,"family":kind,"equal":expected==actual,
                       "expected":expected,"published":actual,"asset_id":asset["sha256"]})
    excluded = rows(published,"SELECT code,count(*) records FROM quality_issue GROUP BY code")
    totals = rows(published,"SELECT year,round,uf,count(*) sections,sum(eligible)::BIGINT eligible,sum(present)::BIGINT present,sum(absent)::BIGINT absent FROM section_turnout GROUP BY ALL ORDER BY ALL")
    votes = rows(published,"SELECT year,round,uf,office,count(*) records,sum(votes)::BIGINT votes FROM candidate_vote GROUP BY ALL ORDER BY ALL")
    logs = rows(published,"SELECT o.year,o.section_id,o.vote_events,s.present,o.clock_quality,o.taxonomy_status FROM operational_section_metrics o LEFT JOIN section_turnout s USING(section_id) ORDER BY o.year")
    for table in ("section_turnout","candidate_vote","operational_section_metrics"):
        assert {r[0] for r in published.execute(f"SELECT DISTINCT uf FROM {table}").fetchall()} <= UFS

source_checks = [{"asset_id":a["sha256"],"ok":sha256(Path(a["path"]))==a["sha256"]} for a in manifest["sources"]]
db_ok = sha256(root/"gold"/f"{snapshot}.duckdb")==manifest["database_sha256"]
assert db_ok and all(a["ok"] for a in source_checks)
start = time.perf_counter()
turnout(root,Scope(year=2022,snapshot=snapshot))
duration = time.perf_counter()-start
size = {folder:sum(p.stat().st_size for p in (root/folder).rglob("*") if p.is_file())
        for folder in ("raw","silver","gold","cache","reports")}
observations = [read_json(p) for p in (root/"coverage").glob("*.json")]
evidence = {"at":utcnow(),"snapshot_id":snapshot,"scope_ufs":sorted(UFS),"checks":checks,"missing_first_round_partitions":missing,
            "source_hashes":source_checks,"database_hash_ok":db_ok,"totals":totals,"votes":votes,"logs":logs,
            "quality_issues":excluded,"storage_bytes":size,"coverage_observations":observations,
            "aggregate_query_seconds":duration,"future_2026_round2":temporal_status(2026,2)}
write_json(root/"manifests"/"regional-validation.json",evidence)
print(json.dumps({"snapshot":snapshot,"checks":len(checks),"differences":sum(not x["equal"] for x in checks),
                  "missing":missing,"sections":sum(x["sections"] for x in totals),"vote_rows":sum(x["records"] for x in votes),
                  "bytes":size,"quality_issues":excluded},ensure_ascii=True),flush=True)
assert not missing, missing
assert all(x["equal"] for x in checks), [x for x in checks if not x["equal"]]
