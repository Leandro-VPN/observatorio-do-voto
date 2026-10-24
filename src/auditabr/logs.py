"""Conservative log taxonomy, no identity fields and no candidate linkage."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, time, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

import py7zr
from py7zr.io import BytesIOFactory

from auditabr.acquisition import safe_members
from auditabr.domain import check_scope, election_date, section_id, temporal_status
from auditabr.parsers import normalized
from auditabr.storage import SnapshotBuilder, insert_dicts, reader
from auditabr.utils import digest, write_json

VERSION = "operational-1.0.0"
MAX_LOG = 32 * 1024**2
KINDS = ("BIO_CONFIRMED", "ALT_MANUAL_CONFIRMED", "NO_BIOMETRIC_ENROLLMENT_CONFIRMED",
         "BIOGRAPHIC_ALTERNATIVE_CONFIRMED", "HABILITATION_UNCLASSIFIED", "HABILITATION_CONFLICT")


def read_log(path: Path) -> bytes:
    with path.open("rb") as stream:
        signature = stream.read(8)
    if signature.startswith(b"PK"):
        with zipfile.ZipFile(path) as archive:
            entries = safe_members(archive, max_member=MAX_LOG, max_total=MAX_LOG)
            names = [i.filename for i in entries if PurePosixPath(i.filename).name == "logd.dat"]
            if len(names) != 1:
                raise ValueError("Contêiner sem logd.dat único")
            return archive.read(names[0])
    if signature.startswith(b"7z\xbc\xaf\x27\x1c"):
        with py7zr.SevenZipFile(path) as archive:
            entries = archive.list()
            if len(entries) > 100 or sum(e.uncompressed for e in entries) > MAX_LOG:
                raise ValueError("7z excede limite de extração")
            for item in entries:
                name = item.filename.replace("\\", "/")
                if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or ":" in name or item.is_symlink:
                    raise ValueError("7z contém entrada insegura")
            names = [e.filename for e in entries if PurePosixPath(e.filename).name == "logd.dat"]
            if len(names) != 1:
                raise ValueError("7z sem logd.dat único")
            factory = BytesIOFactory(MAX_LOG)
            archive.extract(targets=names, factory=factory)
            return factory.get(names[0]).read()
    if path.name.lower() == "logd.dat" and path.stat().st_size <= MAX_LOG:
        return path.read_bytes()
    raise ValueError("PARSER_UNSUPPORTED: magic bytes/formato de log desconhecido")


def classify_message(message: str):
    message = normalized(message)
    exact = {
        "O VOTO DO ELEITOR FOI COMPUTADO": "VOTE",
        "AGUARDANDO DIGITACAO DO TITULO": "START",
        "AGUARDANDO DIGITACAO DO IDENTIFICADOR DO ELEITOR": "START",
        "TIPO DE HABILITACAO DO ELEITOR [BIOMETRICA]": "BIO",
        "O ELEITOR NAO POSSUI BIOMETRIA": "NO_ENROLLMENT",
        "SOLICITACAO DE DADO PESSOAL DO ELEITOR PARA HABILITACAO MANUAL": "MANUAL_REQUEST",
        "ANO DE NASCIMENTO DIGITADO E IGUAL AO DO CADASTRO": "BIOGRAPHIC_EVIDENCE",
        # Confirmation phrases are accepted only as state-machine input; raw taxonomy remains unverified
        # until the phrase is present in reviewed official samples/documentation.
        "HABILITACAO MANUAL CONFIRMADA": "MANUAL_APPROVED",
        "HABILITACAO DO ELEITOR CANCELADA": "CANCEL",
        "VOTACAO ENCERRADA": "CLOSE",
        "ENCERRAMENTO DA VOTACAO": "CLOSE",
        "BOLETIM DE URNA GERADO": "BU",
    }
    return exact.get(message, "OTHER")


def cutoff(year: int, round: int, zone: str, rule: str | None, evidence: str | None):
    if not evidence or not rule:
        return None
    if rule == "BRT_17" and year >= 2022:
        return datetime.combine(election_date(year, round), time(17), ZoneInfo("America/Sao_Paulo")).astimezone(timezone.utc)
    if rule == "LOCAL_17":
        return datetime.combine(election_date(year, round), time(17), ZoneInfo(zone)).astimezone(timezone.utc)
    raise ValueError("Regra temporal não validada para o pleito")


def state_machine(events: list[dict]):
    states: dict[str, set[str]] = defaultdict(set)
    output = []
    for event in events:
        state, kind = states[event["device"]], event["kind"]
        if kind in ("START", "CANCEL"):
            state.clear()
        elif kind == "VOTE":
            confirmed = set()
            if "BIO" in state:
                confirmed.add("BIO_CONFIRMED")
            if {"MANUAL_REQUEST", "MANUAL_APPROVED"} <= state:
                confirmed.add("ALT_MANUAL_CONFIRMED")
            if "NO_ENROLLMENT" in state:
                confirmed.add("NO_BIOMETRIC_ENROLLMENT_CONFIRMED")
            classification = next(iter(confirmed)) if len(confirmed) == 1 else "HABILITATION_CONFLICT" if confirmed else "HABILITATION_UNCLASSIFIED"
            output.append({**event, "classification": classification, "reasons": sorted(state)})
            state.clear()
        elif kind != "OTHER":
            state.add(kind)
    return output


def parse_log(data: bytes, year: int, round: int, asset_id: str, *, zone: str | None = None,
              rule: str | None = None, rule_evidence: str | None = None, clock_validated=False,
              taxonomy_validated=False):
    if year not in (2022, 2024, 2026):
        raise ValueError("PARSER_UNSUPPORTED: logs deste ano não foram perfilados")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    day = election_date(year, round)
    events, rejected, excluded = [], [], 0
    identities: dict[str, set[str]] = {}
    previous: dict[str, datetime] = {}
    clock_issue = False
    for line_no, line in enumerate(text.splitlines(), 1):
        fields = line.split("\t")
        if len(fields) < 5:
            rejected.append({"line": line_no, "reason": "FIELDS"})
            continue
        # Extract only geography from technical setup; never persist arbitrary raw messages.
        msg = normalized(fields[4])
        for label, field in [("MUNICIPIO", "municipality"), ("ZONA ELEITORAL", "zone"), ("SECAO ELEITORAL", "section")]:
            if msg.startswith(label + ":"):
                match = re.match(r"\s*(\d+)", msg.split(":", 1)[1])
                if match:
                    identities.setdefault(field, set()).add(match[1])
        try:
            ts = datetime.strptime(fields[0], "%d/%m/%Y %H:%M:%S")
        except ValueError:
            rejected.append({"line": line_no, "reason": "TIMESTAMP"})
            continue
        if ts.date() != day:
            excluded += 1
            continue
        device = hashlib.sha256(fields[2].encode()).hexdigest()[:16]
        if device in previous and ts < previous[device]:
            clock_issue = True
        previous[device] = ts
        kind = classify_message(fields[4]) if fields[3] == "VOTA" else "OTHER"
        events.append({"event_id": digest([asset_id, line_no]), "asset_id": asset_id, "line": line_no,
                       "timestamp_original": fields[0], "timestamp": ts, "device": device, "kind": kind})
    votes = state_machine(events)
    quality = "CLOCK_JUMP" if clock_issue else "TRUSTED" if clock_validated and zone else "UNKNOWN"
    limit = cutoff(year, round, zone, rule, rule_evidence) if zone else None
    reliable = quality == "TRUSTED" and limit is not None and not rejected
    categories = Counter(v["classification"] for v in votes)
    hourly = Counter(v["timestamp"].strftime("%H:00") for v in votes)
    timestamps = [v["timestamp"] for v in votes]
    devices = {v["device"] for v in votes}
    # Multiple devices require reconciliation before trusted temporal rankings.
    if len(devices) > 1:
        reliable = False
        quality = "MULTI_DEVICE_UNRESOLVED"
    after = sum(v["timestamp"].replace(tzinfo=ZoneInfo(zone or "UTC")).astimezone(timezone.utc) > limit for v in votes) if reliable else None
    taxonomy_ok = taxonomy_validated and not rejected
    counts = categories if taxonomy_ok else Counter({"HABILITATION_UNCLASSIFIED": len(votes)})
    metric = {"vote_events": len(votes), "timed_events": len(votes) if reliable else None, "after_cutoff": after,
              "biometric": counts["BIO_CONFIRMED"] if taxonomy_ok else None,
              "manual": counts["ALT_MANUAL_CONFIRMED"] if taxonomy_ok else None,
              "no_enrollment": counts["NO_BIOMETRIC_ENROLLMENT_CONFIRMED"] if taxonomy_ok else None,
              "biographic": counts["BIOGRAPHIC_ALTERNATIVE_CONFIRMED"] if taxonomy_ok else None,
              "unknown": counts["HABILITATION_UNCLASSIFIED"], "conflict": counts["HABILITATION_CONFLICT"],
              "first_vote": min(timestamps).isoformat() if timestamps else None,
              "last_vote": max(timestamps).isoformat() if timestamps else None,
              "closure": next((e["timestamp"].isoformat() for e in reversed(events) if e["kind"] == "CLOSE"), None),
              "bu": next((e["timestamp"].isoformat() for e in reversed(events) if e["kind"] == "BU"), None),
              "clock_quality": quality, "taxonomy_status": "VALIDATED" if taxonomy_ok else "UNVERIFIED",
              "classification_coverage": (len(votes)-counts["HABILITATION_UNCLASSIFIED"]-counts["HABILITATION_CONFLICT"])/len(votes) if votes else None,
              "timezone": zone, "cutoff_utc": limit.isoformat() if limit else None, "multi_device": len(devices)>1,
              "asset_id": asset_id, "hourly": json.dumps(dict(sorted(hourly.items()))),
              "warnings": json.dumps({"rejected": rejected, "excluded_other_days": excluded,
                  "clock_validated": clock_validated, "rule_evidence": rule_evidence,
                  "raw_classification_counts_unverified": dict(categories)}, ensure_ascii=False)}
    return {"metric": metric, "events": votes, "identities": {k: sorted(v) for k,v in identities.items()}}


def ingest_log(root: Path, asset: dict, year: int, round: int, uf: str, municipality: str, zone: str, section: str,
               timezone_id: str | None = None, mode="official"):
    check_scope(year, round, uf)
    if temporal_status(year, round) == "FUTURE":
        raise ValueError("FUTURE: não é permitido publicar logs de pleito futuro")
    municipality, zone, section = municipality.zfill(5), zone.zfill(4), section.zfill(4)
    sid = section_id(year, round, uf, municipality, zone, section)
    parsed = parse_log(read_log(Path(asset["path"])), year, round, asset["sha256"], zone=timezone_id)
    for key, expected in [("municipality", municipality), ("zone", zone), ("section", section)]:
        observed = parsed["identities"].get(key, [])
        if observed and any(int(value) != int(expected) for value in observed):
            raise ValueError(f"Identificação do log diverge: {key}")
    if not parsed["identities"].get("section"):
        raise ValueError("Seção não confirmada no cabeçalho do log")
    metric = {**parsed["metric"], "section_id": sid, "year": year, "round": round, "uf": uf,
              "municipality": municipality, "zone": zone, "section": section, "place": None}
    with reader(root) as db:
        previous = db.execute("SELECT asset_id FROM operational_section_metrics WHERE section_id=?", [sid]).fetchone()
        official = db.execute("SELECT place,present FROM section_turnout WHERE section_id=?", [sid]).fetchone()
    if previous and previous[0] != asset["sha256"]:
        raise ValueError("Já existe outro fragmento para a seção; reconcilie substituição antes de combinar")
    if official:
        metric["place"] = official[0]
    with SnapshotBuilder(root, {"year": year, "round": round, "uf": uf, "family": "logs", "section": sid}, [asset], VERSION, mode) as builder:
        db = builder.connection
        assert db is not None
        db.execute("DELETE FROM operational_section_metrics WHERE section_id=?", [sid])
        insert_dicts(db, "operational_section_metrics", [metric])
        if official and metric["vote_events"] != official[1]:
            issue = {"issue_id": digest([sid, asset["sha256"], "LOG_TURNOUT"]), "section_id": sid,
                     "family": "logs", "severity": "WARNING", "code": "LOG_VS_TURNOUT",
                     "detail": json.dumps({"events": metric["vote_events"], "present": official[1]}), "asset_id": asset["sha256"]}
            db.execute("DELETE FROM quality_issue WHERE issue_id=?", [issue["issue_id"]])
            insert_dicts(db, "quality_issue", [issue])
        count = db.execute("SELECT count(*) FROM operational_section_metrics WHERE year=? AND round=? AND uf=?", [year, round, uf]).fetchone()[0]
        db.execute("INSERT OR REPLACE INTO partition_registry VALUES (?,?,?,?,?,?,?,?)",
                   [year, round, uf, "logs", builder.run_id, json.dumps([asset["sha256"]]), count, "PARTIAL_UNVERIFIED"])
        manifest = builder.publish({"blocking": 0, "log_sections": count, "clock_quality": metric["clock_quality"],
                                    "taxonomy_status": metric["taxonomy_status"]})
    sanitized = [{k: v for k,v in event.items() if k not in ("device",)} for event in parsed["events"]]
    write_json(root / "silver" / "log_events" / f"{asset['sha256']}.json", {"parser": VERSION, "events": sanitized})
    return manifest
