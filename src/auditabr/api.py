from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError

from auditabr import __version__
from auditabr.analytics import ALTERNATIVES
from auditabr.catalog import Catalog
from auditabr.domain import UFS, YEARS, election_date, election_id, offices, temporal_status
from auditabr.queries import (
    Group,
    Scope,
    analysis,
    envelope,
    geography,
    historical,
    operational,
    pin_scope,
    turnout,
    votes,
    where,
)
from auditabr.reporting import create_report
from auditabr.storage import current_manifest, reader, rows
from auditabr.utils import digest, read_json, storage_root, utcnow, write_json


class ReportRequest(BaseModel):
    scope: Scope
    group_by: Group = "municipality"


def create_app(root: Path | None = None):
    root = root or storage_root()
    app = FastAPI(title="AUDITA-BR", version=__version__, description="Consulta local de snapshots eleitorais auditáveis")
    prefix = "/api/v1"

    @app.exception_handler(ValueError)
    async def invalid_request(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def admin(authorization: Annotated[str | None, Header()] = None):
        token = os.environ.get("AUDITABR_ADMIN_TOKEN")
        if not token or not authorization or not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(403, "Operação administrativa requer AUDITABR_ADMIN_TOKEN")

    def scope_filter(year: int = 2022, round: int = 1, uf: str | None = None, municipality: str | None = None,
                     zone: str | None = None, place: str | None = None, section: str | None = None,
                     office: Literal["PRESIDENTE", "PREFEITO"] | None = None, snapshot: str | None = None):
        try:
            return pin_scope(root, Scope(year=year, round=round, uf=uf, municipality=municipality, zone=zone, place=place,
                         section=section, office=office, snapshot=snapshot))
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc

    scope_dep = Depends(scope_filter)

    @app.get(prefix + "/health")
    def health():
        manifest = current_manifest(root)
        return {"status": "ok", "version": __version__, "snapshot_id": manifest and manifest["snapshot_id"],
                "scope_ufs": sorted(UFS), "scope_offices": ["PRESIDENTE","PREFEITO"],
                "mode": manifest["mode"] if manifest else "official", "has_published_data": bool(manifest)}

    @app.get(prefix + "/elections")
    def elections():
        return {"data": [{"year": y, "election_id": election_id(y), "offices": offices(y),
            "rounds": [{"round": r, "date": str(election_date(y, r)), "status": temporal_status(y, r)} for r in (1, 2)]} for y in YEARS]}

    @app.get(prefix + "/elections/{eid}/rounds")
    def rounds(eid: str):
        year = next((y for y in YEARS if election_id(y) == eid), None)
        if year is None:
            raise HTTPException(404, "Pleito não encontrado")
        return {"data": [{"round": r, "date": str(election_date(year, r)), "status": temporal_status(year, r)} for r in (1, 2)]}

    @app.get(prefix + "/offices")
    def allowed_offices(year: int = 2022, round: int = 1):
        return {"data": offices(year, round)}

    @app.get(prefix + "/contests")
    def contests(scope: Scope = scope_dep):
        sql, params = where(scope, include_office=True)
        with reader(root, scope.snapshot) as db:
            data = rows(db, f"SELECT DISTINCT year,round,uf,office,CASE WHEN office='PREFEITO' THEN municipality END municipality FROM candidate_vote WHERE {sql} ORDER BY ALL", params)
        return envelope(root, scope, data)

    @app.get(prefix + "/catalog/resources")
    def resources(year: int | None = None, dataset_id: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        data = [r for r in Catalog(root).resources(year) if dataset_id is None or r["dataset_id"] == dataset_id]
        return {"data": data[offset:offset+limit], "pagination": {"offset": offset, "has_more": len(data)>offset+limit}}

    @app.get(prefix + "/catalog/datasets")
    def datasets(year: int | None = None):
        result = {}
        for resource in Catalog(root).resources(year):
            result[resource["dataset_id"]] = {k: resource[k] for k in ("dataset_id", "dataset_name", "year", "page_url", "license")}
        return {"data": list(result.values())}

    @app.get(prefix + "/catalog/snapshots")
    def snapshots():
        data = [m for p in (root / "manifests" / "snapshots").glob("*.json")
                if (m := read_json(p)).get("scope_offices") == ["PRESIDENTE", "PREFEITO"]
                and m.get("status")=="PUBLISHED"]
        return {"data": [{k: m[k] for k in ("snapshot_id", "published_at", "parameters", "mode")} for m in sorted(data, key=lambda m: m["published_at"], reverse=True)]}

    @app.get(prefix + "/catalog/coverage")
    def coverage(scope: Scope = scope_dep):
        with reader(root, scope.snapshot) as db:
            sql = "year=? AND round=?" + (" AND uf=?" if scope.uf else "")
            params = [scope.year, scope.round] + ([scope.uf] if scope.uf else [])
            data = rows(db, f"SELECT * FROM partition_registry WHERE {sql}", params)
        return envelope(root, scope, data)

    @app.get(prefix + "/geography/{level}")
    def geo(level: Literal["states", "municipalities", "zones", "places", "sections"], scope: Scope = scope_dep):
        return geography(root, scope, {"states": "uf", "municipalities": "municipality", "zones": "zone", "places": "place", "sections": "section"}[level])

    @app.get(prefix + "/geography/sections/{sid}")
    def section_detail(sid: str, snapshot: str | None = None):
        with reader(root, snapshot) as db:
            data = rows(db, "SELECT * FROM section_turnout WHERE section_id=?", [sid])
            if not data:
                raise HTTPException(404, "Seção não encontrada no snapshot")
            ops = rows(db, "SELECT * FROM operational_section_metrics WHERE section_id=?", [sid])
            sources = rows(db, "SELECT asset_id,resource_id,dataset_id,source_url,sha256 FROM source_asset WHERE asset_id=?", [data[0]["asset_id"]])
            links = rows(db, "SELECT * FROM historical_section_link WHERE section_a=? OR section_b=?", [sid, sid])
        return {"data": data[0], "operational": ops or None, "sources": sources, "historical_links": links}

    @app.get(prefix + "/metrics/turnout")
    def turnout_route(scope: Scope = scope_dep, group_by: Group = "uf", limit: int = Query(500, ge=1, le=10000), offset: int = Query(0, ge=0)):
        return turnout(root, scope, group_by, limit, offset)

    @app.get(prefix + "/metrics/votes")
    def vote_route(scope: Scope = scope_dep, group_by: Group = "uf", limit: int = Query(500, ge=1, le=10000), offset: int = Query(0, ge=0)):
        return votes(root, scope, group_by, limit, offset)

    @app.get(prefix + "/metrics/times")
    def times(scope: Scope = scope_dep, limit: int = Query(500, ge=1, le=10000), offset: int = Query(0, ge=0)):
        return operational(root, scope, "times", limit, offset)

    @app.get(prefix + "/metrics/habilitation")
    def habilitation(scope: Scope = scope_dep, limit: int = Query(500, ge=1, le=10000), offset: int = Query(0, ge=0)):
        return operational(root, scope, "habilitation", limit, offset)

    @app.get(prefix + "/metrics/historical")
    def history(scope: Scope = scope_dep, years: str = "2012,2016,2020,2024"):
        return historical(root, scope, [int(y) for y in years.split(",")])

    @app.get(prefix + "/metrics/reconciliation")
    def reconciliation(scope: Scope = scope_dep, limit: int = Query(500, ge=1, le=10000), offset: int = Query(0, ge=0)):
        sql, params = where(scope, "s")
        with reader(root, scope.snapshot) as db:
            data = rows(db, f"SELECT q.* FROM quality_issue q JOIN section_turnout s USING(section_id) WHERE {sql} ORDER BY issue_id LIMIT ? OFFSET ?", [*params, limit+1, offset])
        return envelope(root, scope, data[:limit], has_more=len(data)>limit, offset=offset)

    @app.get(prefix + "/analytics/funnel")
    @app.get(prefix + "/metrics/compare-sections")
    def funnel(scope: Scope = scope_dep, limit: int = Query(500, ge=1, le=10000), offset: int = Query(0, ge=0)):
        return analysis(root, scope, limit=limit, offset=offset)

    @app.get(prefix + "/findings")
    def findings(scope: Scope = scope_dep, limit: int = Query(500, ge=1, le=10000), offset: int = Query(0, ge=0)):
        result = analysis(root, scope, limit=limit, offset=offset, signals_only=True)
        result["data"] = [{**r, "finding_id": digest([result["meta"]["snapshot_id"], r["section_id"], r["signal"]])[:24],
                           "alternative_explanations": ALTERNATIVES, "review_status": "UNREVIEWED"}
                          for r in result["data"] if r["signal"]]
        return result

    @app.get(prefix + "/assets/{asset_id}/metadata")
    def asset(asset_id: str, snapshot: str | None = None):
        with reader(root, snapshot) as db:
            data = rows(db, "SELECT asset_id,resource_id,dataset_id,source_url,sha256,size_bytes FROM source_asset WHERE asset_id=?", [asset_id])
        if not data:
            raise HTTPException(404, "Fonte não encontrada")
        return {"data": data[0]}

    @app.post(prefix + "/reports", dependencies=[Depends(admin)])
    def report(request: ReportRequest):
        manifest = create_report(root, request.scope, request.group_by)
        return {"report_id": manifest["report_id"], "status": "COMPLETED"}

    def report_folder(report_id):
        if len(report_id) != 24 or not report_id.isalnum():
            raise HTTPException(422, "ID inválido")
        folder = root / "reports" / report_id
        if not (folder / "manifest.json").exists():
            raise HTTPException(404, "Relatório não encontrado")
        return folder

    @app.get(prefix + "/reports/{report_id}")
    def read_report(report_id: str):
        return read_json(report_folder(report_id) / "manifest.json")

    @app.get(prefix + "/reports/{report_id}/download")
    def download_report(report_id: str, format: Literal["csv", "json", "md", "html", "parquet"] = "json"):
        filename = f"report.{format}" if format in ("md", "html") else f"data.{format}"
        return FileResponse(report_folder(report_id) / filename, filename=filename)

    @app.get(prefix + "/admin/jobs", dependencies=[Depends(admin)])
    def jobs():
        return {"data": [read_json(p) for p in (root / "jobs").glob("*.json")]}

    @app.post(prefix + "/admin/catalog/refresh", dependencies=[Depends(admin)])
    def refresh(year: int, background: BackgroundTasks):
        if year not in YEARS:
            raise HTTPException(422, "Ano inválido")
        job_id = digest([year, utcnow()])[:24]
        path = root / "jobs" / f"{job_id}.json"
        write_json(path, {"status": "QUEUED", "year": year})

        def run():
            try:
                result = Catalog(root).discover(year)
                write_json(path, {"status": "COMPLETED", "datasets": len(result["datasets"])})
            except Exception as exc:
                write_json(path, {"status": "FAILED", "error": str(exc)})
        background.add_task(run)
        return {"job_id": job_id, "status": "QUEUED"}

    return app


app = create_app()
