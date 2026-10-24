"""Norte/Nordeste: stream official sources, retain only scoped projected records."""
from __future__ import annotations

import csv
import io
import shutil
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as arrow_csv
import pyarrow.parquet as pq

from auditabr.acquisition import RemoteZipReader, preserve_asset, safe_members
from auditabr.catalog import Catalog, family
from auditabr.domain import UFS, YEARS, election_date, temporal_status
from auditabr.parsers import REQUIRED, VERSION
from auditabr.pipeline import load_partition, reconcile
from auditabr.storage import SnapshotBuilder, current_manifest, initialize, reader
from auditabr.utils import digest, read_json, sha256, utcnow, write_json

CAPTURE_VERSION = "regional-projection-1.0.0"
NEEDED = REQUIRED | {"DT_ELEICAO", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "NM_MUNICIPIO",
    "QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES", "QT_VOTOS_NOMINAIS", "QT_VOTOS_BRANCOS",
    "QT_VOTOS_NULOS", "QT_VOTOS_ANULADOS_APU_SEP", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS",
    "SQ_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO"}


def project_stream(source, destination: Path, year: int, states: tuple[str, ...]):
    """Keep exact field strings and original CSV record ordinals, not national CSVs."""
    if not set(states) <= UFS:
        raise ValueError("Captura fora do Norte/Nordeste")
    destination.mkdir(parents=True, exist_ok=True)
    buffered = source if hasattr(source, "peek") else io.BufferedReader(source)
    prefix = buffered.peek(65536)
    encoding = "utf-8-sig" if prefix.startswith(b"\xef\xbb\xbf") else "latin1"
    header = next(csv.reader([prefix.split(b"\n", 1)[0].decode(encoding)], delimiter=";"))
    if not REQUIRED <= set(header):
        raise ValueError("Fonte sem cabeçalho oficial reconhecido")
    columns = [c for c in header if c in NEEDED]
    schema = pa.schema([(c, pa.string()) for c in columns] + [("_SOURCE_ROW", pa.int64())])
    writers = {uf: pq.ParquetWriter(destination / f"{uf}.parquet", schema, compression="zstd") for uf in states}
    counts = dict.fromkeys(states, 0)
    offset = 0
    try:
        stream = arrow_csv.open_csv(buffered,
            read_options=arrow_csv.ReadOptions(encoding=encoding, block_size=8*1024**2),
            parse_options=arrow_csv.ParseOptions(delimiter=";", newlines_in_values=True),
            convert_options=arrow_csv.ConvertOptions(include_columns=columns, column_types={c:pa.string() for c in columns}))
        for batch in stream:
            original_rows = pa.array(range(offset+2, offset+2+batch.num_rows), type=pa.int64())
            offset += batch.num_rows
            batch = batch.append_column("_SOURCE_ROW", original_rows)
            mask = pc.and_(pc.is_in(batch["SG_UF"], value_set=pa.array(states)),
                           pc.equal(pc.utf8_upper(batch["DS_CARGO"]), "PREFEITO" if year%4==0 else "PRESIDENTE"))
            mask = pc.and_(mask, pc.equal(batch["ANO_ELEICAO"], str(year)))
            if "DT_ELEICAO" in columns:
                dates = pa.array([election_date(year,r).strftime("%d/%m/%Y") for r in (1,2)
                                  if temporal_status(year,r) != "FUTURE"])
                mask = pc.and_(mask, pc.is_in(batch["DT_ELEICAO"], value_set=dates))
            selected = batch.filter(mask)
            for uf in states:
                part = selected.filter(pc.equal(selected["SG_UF"], uf))
                if part.num_rows:
                    writers[uf].write_batch(part)
                    counts[uf] += part.num_rows
    finally:
        for writer in writers.values():
            writer.close()
    return {"input_records": offset, "selected_records": counts, "columns": columns,
            "encoding": encoding, "capture_version": CAPTURE_VERSION}


@contextmanager
def source_stream(root: Path, legacy: Path, resource: dict, year: int, source_scope: str, kind: str, refresh=False):
    existing = legacy / "cache" / f"acquired-{year}-{source_scope}-{kind}.json"
    if existing.exists() and not refresh:
        asset = read_json(existing)
        path = Path(asset["path"])
        if path.exists() and sha256(path) == asset["sha256"]:
            with path.open("rb") as stream:
                yield stream, {"member": asset.get("member", path.name), "original_member_sha256": asset["sha256"],
                               "parent_receipt": asset, "transport_bytes": 0, "method": "LOCAL_VERIFIED_REUSE"}
            return
    remote = RemoteZipReader(resource["url"], budget=1024**3)
    try:
        # A bounded read-ahead avoids a network request for every small decompressor read.
        buffer_size = 8*1024**2 if kind == "votes" else 256*1024
        with io.BufferedReader(remote, buffer_size=buffer_size) as buffered, zipfile.ZipFile(buffered) as archive:
            entries = safe_members(archive, max_member=12*1024**3, max_total=80*1024**3)
            members = [e for e in entries if e.filename.lower().endswith(".csv") and f"_{source_scope}." in e.filename]
            if len(members) != 1:
                raise ValueError("Membro oficial do recorte não identificado sem ambiguidade")
            info = members[0]
            details = {"member": info.filename, "original_member_bytes": info.file_size,
                       "member_crc32": info.CRC, "container_bytes": remote.size, "http": remote.headers,
                       "method": "REMOTE_RANGE_STREAM", "original_member_sha256": None}
            with archive.open(info) as stream:
                yield stream, details
            details["transport_bytes"] = remote.transferred
            details["crc_verified"] = True  # EOF reached by the Arrow reader, enforced by zipfile.
    finally:
        remote.close()


def capture(root: Path, legacy: Path, resource: dict, year: int, kind: str, states: tuple[str, ...], refresh=False):
    source_scope = "BR" if year%4==2 else states[0]
    key = digest([resource["id"], year, kind, states, CAPTURE_VERSION])
    index = root / "captures" / f"{key}.json"
    if index.exists() and not refresh:
        saved = read_json(index)
        if all(Path(a["path"]).exists() for a in saved["assets"].values()):
            return saved
    if not refresh:
        for previous in (root/"captures").glob("*.json"):
            saved = read_json(previous)
            if (set(states) <= saved["assets"].keys() and saved["projection"].get("capture_version") == CAPTURE_VERSION
                    and all(saved["assets"][uf]["resource_id"] == resource["id"]
                            and Path(saved["assets"][uf]["path"]).exists() for uf in states)):
                return {**saved,"assets":{uf:saved["assets"][uf] for uf in states}}
    staging = root / "cache" / key
    started = time.perf_counter()
    with source_stream(root, legacy, resource, year, source_scope, kind, refresh) as (source, details):
        projection = project_stream(source, staging, year, states)
    assets = {}
    for uf in states:
        assets[uf] = preserve_asset(root, staging / f"{uf}.parquet", resource,
            {"acquisition": "SCOPED_PROJECTED_RECORDS", "year":year,"uf":uf,"family":kind,
             "projection": projection, "source_read": details,
             "note": "Hash da captura filtrada; não é hash do CSV nacional/ZIP remoto. Campos originais preservados nas colunas selecionadas."})
    result = {"assets": assets, "projection": projection, "source_read": details,
              "elapsed_seconds": time.perf_counter()-started, "at": utcnow()}
    write_json(index, result)
    return result


def publish_year(root: Path, year: int, captured: dict, notify=print, rounds=(1,2), mode="official"):
    initialize(root,mode)
    current = current_manifest(root)
    unchanged = current is not None
    if current:
        with reader(root,current["snapshot_id"]) as existing_db:
            for (uf,kind), item in captured.items():
                for turn in rounds:
                    if temporal_status(year,turn)=="FUTURE":
                        continue
                    asset = item[uf]
                    parameters = {"year":year,"round":turn,"uf":uf,"family":kind}
                    run_id = digest({"parameters":parameters,"assets":[asset["sha256"]],"version":VERSION})
                    found = existing_db.execute("SELECT run_id FROM partition_registry WHERE year=? AND round=? AND uf=? AND family=?",
                        [year,turn,uf,kind]).fetchone()
                    observation_path = root/"coverage"/f"{year}-{turn}-{uf}-{kind}.json"
                    observation = read_json(observation_path) if observation_path.exists() else {}
                    not_applicable = observation.get("status")=="NOT_APPLICABLE" and observation.get("asset_id")==asset["sha256"]
                    if not ((found and found[0]==run_id) or not_applicable):
                        unchanged = False
    if unchanged:
        assert current is not None
        return {**current,"idempotent":True}
    assets = {a["sha256"]: a for item in captured.values() for a in item.values()}
    parameters = {"year":year, "states":sorted(UFS), "family":"regional_batch", "capture_version":CAPTURE_VERSION}
    observations = []
    with SnapshotBuilder(root, parameters, list(assets.values()), VERSION,mode) as builder:
        db = builder.connection
        assert db is not None
        for (uf, kind), item in sorted(captured.items()):
            asset = item[uf]
            for turn in rounds:
                scope = {"year":year,"round":turn,"uf":uf,"family":kind}
                if temporal_status(year,turn) == "FUTURE":
                    observations.append({**scope,"status":"FUTURE"})
                    continue
                run_id = digest({"parameters":scope,"assets":[asset["sha256"]],"version":VERSION})
                existing = db.execute("SELECT run_id FROM partition_registry WHERE year=? AND round=? AND uf=? AND family=?",
                                      [year,turn,uf,kind]).fetchone()
                if existing and existing[0] == run_id:
                    observations.append({**scope,"status":"REUSED"})
                    continue
                observation = {"source_rows":0,"selected_rows":0,"parameters":scope}
                db.execute("BEGIN TRANSACTION")
                try:
                    load_partition(root,db,[asset],year,turn,uf,kind,run_id,observation,quarantine_bad_counts=True)
                    db.execute("COMMIT")
                    state = {**scope,"status":"VALIDATED_WITH_EXCLUSIONS" if observation["quarantined_rows"] else "VALIDATED",
                             "rows":observation["selected_rows"],"quarantined_rows":observation["quarantined_rows"]}
                except ValueError as exc:
                    db.execute("ROLLBACK")
                    state = {**scope,"status":"NOT_APPLICABLE" if "Nenhuma linha" in str(exc) else "FAILED",
                             "reason":str(exc),"asset_id":asset["sha256"]}
                observations.append(state)
                write_json(root/"coverage"/f"{year}-{turn}-{uf}-{kind}.json",state)
                notify(state)
        quality = reconcile(db)
        quality["collection_observations"] = observations
        quality["scope_regions"] = ["NORTE","NORDESTE"]
        manifest = builder.publish(quality)
    write_json(root/"jobs"/f"regional-{year}.json",{"status":"COMPLETED_WITH_GAPS" if any(o["status"]=="FAILED" for o in observations) else "COMPLETED",
                "snapshot_id":manifest["snapshot_id"],"observations":observations,"at":utcnow()})
    return manifest


def collect_regions(root: Path, legacy: Path, years=YEARS, notify=print, states=tuple(sorted(UFS)), rounds=(1,2), refresh=False):
    from auditabr.domain import check_scope
    for year in years:
        for uf in states:
            for turn in rounds:
                check_scope(year,turn,uf)
    initialize(root)
    catalog = Catalog(root)
    for year in years:
        if all(temporal_status(year,turn)=="FUTURE" for turn in rounds):
            notify({"year":year,"rounds":rounds,"status":"FUTURE"})
            continue
        target = root/"catalog"/f"{year}.json"
        if refresh:
            catalog.discover(year)
        elif not target.exists():
            previous = legacy/"catalog"/f"{year}.json"
            if previous.exists():
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(previous,target)
            else:
                catalog.discover(year)
        resources = catalog.resources(year)
        captured = {}
        scopes = [tuple(sorted(states))] if year%4==2 else [(uf,) for uf in sorted(states)]
        for capture_states in scopes:
            for kind in ("turnout","votes"):
                source_scope = "BR" if year%4==2 else capture_states[0]
                candidates = [r for r in resources if family(r)==kind and (kind=="turnout" or f"_{source_scope}.zip" in r["url"])]
                if len(candidates)!=1:
                    raise ValueError(f"Recurso ambíguo: {year} {source_scope} {kind}")
                notify({"status":"READING","year":year,"source_scope":source_scope,"family":kind})
                try:
                    result = capture(root,legacy,candidates[0],year,kind,capture_states,refresh)
                    for uf in capture_states:
                        captured[(uf,kind)] = result["assets"]
                    notify({"status":"CAPTURED","year":year,"family":kind,"records":result["projection"]["selected_records"],
                            "transport_bytes":result["source_read"].get("transport_bytes",0)})
                except Exception as exc:
                    failure = {"status":"FAILED","year":year,"uf":source_scope,"family":kind,"reason":str(exc),"at":utcnow()}
                    write_json(root/"jobs"/f"capture-{year}-{source_scope}-{kind}.json",failure)
                    notify(failure)
        if captured:
            manifest = publish_year(root,year,captured,notify,rounds)
            notify({"status":"PUBLISHED","year":year,"snapshot_id":manifest["snapshot_id"]})
