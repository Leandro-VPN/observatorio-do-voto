from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

import duckdb

from auditabr.domain import UFS
from auditabr.utils import digest, read_json, sha256, utcnow, write_json


def migrate(connection):
    sql = files("auditabr").joinpath("resources/runtime.sql").read_text(encoding="utf-8")
    connection.execute(sql)
    checksum = digest(sql)
    previous = connection.execute("SELECT checksum FROM schema_migration WHERE version='001'").fetchone()
    if previous and previous[0] != checksum:
        raise ValueError("Migração 001 alterada após aplicação; crie nova migração")
    connection.execute("INSERT INTO schema_migration VALUES ('001',?,?) ON CONFLICT DO NOTHING", [checksum, utcnow()])
    scoped_sql = files("auditabr").joinpath("resources/002_scope.sql").read_text(encoding="utf-8")
    scoped_hash = digest(scoped_sql)
    applied = connection.execute("SELECT checksum FROM schema_migration WHERE version='002'").fetchone()
    if applied and applied[0] != scoped_hash:
        raise ValueError("Migração 002 alterada após aplicação")
    if not applied:
        connection.execute(scoped_sql)
        connection.execute("INSERT INTO schema_migration VALUES ('002',?,?)", [scoped_hash, utcnow()])


def initialize(root: Path, mode="official"):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "mode.json"
    if path.exists() and read_json(path)["mode"] != mode:
        raise ValueError("Dados sintéticos e oficiais não podem compartilhar storage")
    if not path.exists():
        write_json(path, {"mode": mode})
    for folder in ("raw", "bronze", "silver", "gold", "manifests", "reports", "quarantine", "jobs"):
        (root / folder).mkdir(exist_ok=True)


def current_manifest(root: Path, snapshot: str | None = None) -> dict | None:
    if snapshot and (not snapshot.isalnum() or len(snapshot) != 24):
        raise ValueError("Snapshot inválido")
    path = root / "manifests" / "snapshots" / f"{snapshot}.json" if snapshot else root / "current.json"
    return read_json(path) if path.exists() else None


@contextmanager
def reader(root: Path, snapshot: str | None = None):
    manifest = current_manifest(root, snapshot)
    if manifest:
        database = root / "gold" / f"{manifest['snapshot_id']}.duckdb"
        if not database.exists():
            raise ValueError("Versão física indisponível pela política de retenção; selecione um snapshot disponível")
        connection = duckdb.connect(str(database), read_only=True)
    else:
        connection = duckdb.connect(":memory:")
        migrate(connection)
    try:
        yield connection
    finally:
        connection.close()


def rows(connection, sql, params=None):
    result = connection.execute(sql, params or [])
    columns = [c[0] for c in result.description]
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def insert_dicts(connection, table: str, records: list[dict]):
    if not records:
        return
    import pyarrow as pa
    batch = pa.Table.from_pylist(records)
    connection.register("incoming_batch", batch)
    try:
        # Internal table/column names only; external filters always parameterized.
        columns = ",".join(f'"{c}"' for c in batch.column_names)
        connection.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM incoming_batch")
    finally:
        connection.unregister("incoming_batch")


class SnapshotBuilder:
    def __init__(self, root: Path, parameters: dict, assets: list[dict], version: str, mode="official"):
        initialize(root, mode)
        self.root, self.parameters, self.assets, self.version = root, parameters, assets, version
        self.parent = current_manifest(root)
        self.run_id = digest({"parameters": parameters, "assets": [a["sha256"] for a in assets], "version": version})
        self.snapshot_id = digest([self.parent and self.parent["snapshot_id"], self.run_id])[:24]
        self.path = root / "gold" / f"{self.snapshot_id}.staging.duckdb"
        self.lock = root / "writer.lock"
        self.connection: duckdb.DuckDBPyConnection | None = None

    def __enter__(self):
        try:
            self.lock.open("x").close()
        except FileExistsError:
            raise ValueError("Outro escritor está ativo; confira writer.lock antes de retomar") from None
        try:
            if self.path.exists():
                self.path.unlink()
            if self.parent:
                shutil.copyfile(self.root / "gold" / f"{self.parent['snapshot_id']}.duckdb", self.path)
            self.connection = duckdb.connect(str(self.path))
            self.connection.execute("SET memory_limit='1GB'")
            migrate(self.connection)
            for asset in self.assets:
                raw = Path(asset["path"])
                if not raw.exists() or sha256(raw) != asset["sha256"]:
                    raise ValueError("Hash raw não confere")
                self.connection.execute("INSERT INTO source_asset VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                                        [asset["sha256"], asset["resource_id"], asset["dataset_id"], asset["source_url"],
                                         asset["sha256"], asset["bytes"], asset["path"], json.dumps(asset)])
            return self
        except Exception:
            if self.connection:
                self.connection.close()
            self.lock.unlink(missing_ok=True)
            raise

    def publish(self, quality: dict):
        assert self.connection is not None
        if quality.get("blocking", 0):
            raise ValueError("Gates de publicação falharam")
        result = self.connection.execute("SELECT count(*) FROM candidate_vote WHERE office NOT IN ('PRESIDENTE','PREFEITO')").fetchone()
        assert result is not None
        excluded = result[0]
        if excluded:
            raise ValueError("Cargo fora do escopo solicitado; publicação bloqueada")
        for table in ("section_turnout", "candidate_vote", "operational_section_metrics"):
            found = self.connection.execute(f"SELECT DISTINCT uf FROM {table}").fetchall()
            if any(uf not in UFS for (uf,) in found):
                raise ValueError("UF fora do Norte/Nordeste; publicação bloqueada")
        self.connection.execute("""DELETE FROM source_asset WHERE asset_id NOT IN (
            SELECT asset_id FROM section_turnout UNION SELECT asset_id FROM candidate_vote
            UNION SELECT asset_id FROM contest_vote_summary UNION SELECT asset_id FROM operational_section_metrics
            UNION SELECT asset_id FROM quality_issue)""")
        self.connection.execute("CHECKPOINT")
        self.connection.close()
        self.connection = None
        destination = self.root / "gold" / f"{self.snapshot_id}.duckdb"
        self.path.replace(destination)
        manifest = {"snapshot_id": self.snapshot_id, "parent": self.parent and self.parent["snapshot_id"],
                    "run_id": self.run_id, "published_at": utcnow(), "parameters": self.parameters,
                    "parser_version": self.version, "mode": read_json(self.root / "mode.json")["mode"],
                    "scope_offices": ["PRESIDENTE", "PREFEITO"],
                    "scope_ufs": sorted(UFS), "scope_regions": ["NORTE", "NORDESTE"],
                    "database_sha256": sha256(destination), "quality": quality, "status": "PUBLISHED"}
        with duckdb.connect(str(destination), read_only=True) as db:
            manifest["sources"] = [json.loads(r[0]) for r in db.execute("SELECT receipt FROM source_asset").fetchall()]
            manifest["partitions"] = rows(db, "SELECT * FROM partition_registry ORDER BY year,round,uf,family")
        write_json(self.root / "manifests" / "snapshots" / f"{self.snapshot_id}.json", manifest)
        write_json(self.root / "current.json", manifest)
        return manifest

    def __exit__(self, exc_type, exc, tb):
        if self.connection:
            self.connection.close()
        if exc:
            write_json(self.root / "quarantine" / f"{self.snapshot_id}.json",
                       {"run_id": self.run_id, "error": str(exc), "parameters": self.parameters, "at": utcnow()})
        self.lock.unlink(missing_ok=True)
