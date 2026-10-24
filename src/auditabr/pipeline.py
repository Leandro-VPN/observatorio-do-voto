"""Streaming ingest -> deduplication -> validation -> immutable publication."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from auditabr.domain import check_scope, temporal_status
from auditabr.parsers import VERSION, parse_record, read_rows
from auditabr.storage import SnapshotBuilder, current_manifest, insert_dicts, reader, rows
from auditabr.utils import digest, sha256, utcnow, write_json


def reconcile(db):
    db.execute("DELETE FROM quality_issue WHERE family='reconciliation'")
    differences = rows(db, """
        WITH v AS (SELECT section_id,office,SUM(votes) total FROM candidate_vote GROUP BY ALL)
        SELECT s.section_id,s.office,s.total summary_total,v.total votes_total,s.asset_id
        FROM contest_vote_summary s JOIN v USING(section_id,office)
        WHERE s.total IS NOT NULL AND s.total != v.total
    """)
    for item in differences:
        db.execute("INSERT INTO quality_issue VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                   [digest(item), item["section_id"], "reconciliation", "WARNING", "VOTES_VS_SUMMARY",
                    json.dumps(item), item["asset_id"]])
    return {"blocking": 0, "vote_summary_differences": len(differences),
            "sections": db.execute("SELECT count(*) FROM section_turnout").fetchone()[0],
            "candidate_rows": db.execute("SELECT count(*) FROM candidate_vote").fetchone()[0],
            "limitations": ["Totais de candidatos e apuração podem refletir extrações diferentes; divergências são preservadas.",
                            "Comparecimento usa a disputa presidencial nos pleitos gerais e prefeito nos municipais."]}


def ingest(root: Path, assets: list[dict], year: int, round: int, uf: str, family: str, mode="official"):
    check_scope(year, round, uf)
    if temporal_status(year, round) == "FUTURE":
        raise ValueError("FUTURE: não é permitido publicar pleito futuro")
    if family not in ("turnout", "votes"):
        raise ValueError("Família inválida")
    if not assets:
        raise ValueError("Nenhum arquivo selecionado")
    parameters = {"year": year, "round": round, "uf": uf, "family": family}
    run_id = digest({"parameters": parameters, "assets": [a["sha256"] for a in assets], "version": VERSION})
    with reader(root) as db:
        existing = db.execute("SELECT run_id FROM partition_registry WHERE year=? AND round=? AND uf=? AND family=?",
                              [year, round, uf, family]).fetchone()
    if existing and existing[0] == run_id:
        current = current_manifest(root)
        assert current is not None
        return {**current, "idempotent": True}
    start = time.perf_counter()
    observations: dict[str, Any] = {"started_at": utcnow(), "source_rows": 0, "selected_rows": 0, "parameters": parameters}
    job_path = root / "jobs" / f"{run_id}.json"
    write_json(job_path, {"status": "PARSING", **observations})
    try:
        with SnapshotBuilder(root, parameters, assets, VERSION, mode) as builder:
            db = builder.connection
            assert db is not None
            load_partition(root, db, assets, year, round, uf, family, builder.run_id, observations)
            quality = reconcile(db)
            observations["elapsed_seconds"] = time.perf_counter() - start
            quality["ingest"] = observations
            manifest = builder.publish(quality)
        write_json(job_path, {"status": "PUBLISHED", "snapshot_id": manifest["snapshot_id"], **observations})
        return manifest
    except Exception as exc:
        write_json(job_path, {"status": "FAILED", "error": str(exc), **observations})
        raise


def load_partition(root: Path, db, assets: list[dict], year: int, round: int, uf: str, family: str,
                   run_id: str, observations: dict, quarantine_bad_counts=False):
    parameters = {"year": year, "round": round, "uf": uf, "family": family}
    tables = ["section_turnout", "contest_vote_summary"] if family == "turnout" else ["candidate_vote"]
    for table in tables:
        db.execute(f"CREATE OR REPLACE TEMP TABLE stage_{table} AS SELECT * FROM {table} WHERE FALSE")
    batches: dict[str, list] = {table: [] for table in tables}
    quarantined = []
    for asset in assets:
        for line, row in read_rows(Path(asset["path"]), uf, family, observations):
            try:
                record = parse_record(row, year, round, uf, asset["sha256"], family)
            except ValueError as exc:
                if quarantine_bad_counts and family == "turnout" and "aptos != presentes + ausentes" in str(exc):
                    quarantined.append({"parameters":parameters,"asset_id":asset["sha256"],"source_record":line,
                        "section_id":str(exc).split(": aptos")[0].removeprefix("Seção "),
                        "eligible":row["QT_APTOS"],"present":row["QT_COMPARECIMENTO"],"absent":row["QT_ABSTENCOES"],
                        "reason":str(exc)})
                    continue
                raise ValueError(f"{asset['sha256'][:12]} linha {line}: {exc}") from exc
            if record is None:
                continue
            observations["selected_rows"] += 1
            for table, result in zip(tables, record if family == "turnout" else [record], strict=True):
                batches[table].append(result)
                if len(batches[table]) >= 10000:
                    insert_dicts(db, f"stage_{table}", batches[table])
                    batches[table].clear()
        write_json(root / "bronze" / f"{asset['sha256']}-{family}.json", observations)
    if not observations["selected_rows"]:
        raise ValueError("Nenhuma linha do recorte ordinário selecionado; partição anterior preservada")
    for table in tables:
        insert_dicts(db, f"stage_{table}", batches[table])
    if family == "turnout":
        conflicts = db.execute("""SELECT count(*) FROM (SELECT section_id FROM stage_section_turnout
          GROUP BY section_id HAVING count(DISTINCT (eligible,present,absent,place)) > 1)""").fetchone()[0]
        if conflicts:
            raise ValueError(f"{conflicts} seções com comparecimento/local divergente entre cargos; revisão necessária")
        summary_conflicts = db.execute("""SELECT count(*) FROM (SELECT section_id,office FROM stage_contest_vote_summary
          GROUP BY section_id,office HAVING count(DISTINCT (nominal,blank,null_votes,other)) > 1)""").fetchone()[0]
        if summary_conflicts:
            raise ValueError("Resumos eleitorais conflitantes")
    else:
        conflicts = db.execute("""SELECT count(*) FROM (SELECT section_id,office,candidate_id,vote_status
          FROM stage_candidate_vote GROUP BY ALL HAVING count(DISTINCT votes)>1)""").fetchone()[0]
        if conflicts:
            raise ValueError("Candidaturas com votos conflitantes; não somar versões")
    for table in tables:
        db.execute(f"DELETE FROM {table} WHERE year=? AND round=? AND uf=?", [year, round, uf])
        keys = ("section_id" if table == "section_turnout" else "section_id,office" if table == "contest_vote_summary"
                else "section_id,office,candidate_id,vote_status")
        db.execute(f"INSERT INTO {table} SELECT * FROM stage_{table} QUALIFY row_number() OVER (PARTITION BY {keys} ORDER BY asset_id)=1")
        directory = root / "silver" / table / f"year={year}" / f"round={round}" / f"uf={uf}" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / "data.parquet"
        # Output paths are generated locally, never accepted from API filters.
        query = f"SELECT * FROM {table} WHERE year={year} AND round={round} AND uf='{uf}'"
        db.sql(query).write_parquet(str(output), compression="zstd")
        write_json(directory / "lineage.json", {"run_id": run_id, "parser": VERSION,
            "assets": [a["sha256"] for a in assets], "sha256": sha256(output), "parameters": parameters})
    row_count = db.execute(f"SELECT count(*) FROM {tables[0]} WHERE year=? AND round=? AND uf=?", [year, round, uf]).fetchone()[0]
    if family == "turnout":
        db.execute("DELETE FROM quality_issue WHERE family='validation' AND section_id LIKE ?",
                   [f"BR-{year}-%-T{round}:{uf}:%"])
    for item in quarantined:
        db.execute("INSERT INTO quality_issue VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                   [digest(item),item["section_id"],"validation","ERROR","TURNOUT_ARITHMETIC_INVALID",
                    json.dumps(item),item["asset_id"]])
    observations["quarantined_rows"] = len(quarantined)
    if quarantined:
        write_json(root/"quarantine"/f"rows-{run_id}.json",quarantined)
    db.execute("INSERT OR REPLACE INTO partition_registry VALUES (?,?,?,?,?,?,?,?)",
               [year, round, uf, family, run_id, json.dumps([a["sha256"] for a in assets]), row_count,
                "VALIDATED_WITH_EXCLUSIONS" if quarantined else "VALIDATED"])
