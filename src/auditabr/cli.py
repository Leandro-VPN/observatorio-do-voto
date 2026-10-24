from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Annotated, cast

import typer

from auditabr import __version__
from auditabr.acquisition import RemoteZipReader, fetch, fetch_member, preserve_asset, profile, safe_members
from auditabr.catalog import Catalog, family
from auditabr.domain import YEARS
from auditabr.logs import ingest_log
from auditabr.pipeline import ingest as run_ingest
from auditabr.queries import Group, Scope, turnout
from auditabr.reporting import create_report, snapshot_diff
from auditabr.storage import current_manifest, initialize, reader, rows
from auditabr.utils import read_json, sha256, storage_root, utcnow, write_json

app = typer.Typer(no_args_is_help=True, help="AUDITA-BR · fontes oficiais, qualidade e pesquisa eleitoral local")


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


@app.callback()
def main(storage: Annotated[Path | None, typer.Option(help="Pasta de dados (padrão: storage)")] = None):
    if storage:
        os.environ["AUDITABR_STORAGE"] = str(storage.resolve())


@app.command()
def init(demo: bool = False):
    """Cria armazenamento vazio e segregado por modo."""
    initialize(storage_root(), "demo" if demo else "official")
    with reader(storage_root()) as db:
        emit({"version": __version__, "storage": str(storage_root()), "tables": len(db.execute("SHOW TABLES").fetchall())})


@app.command()
def discover(year: int = 2022, all_years: bool = False):
    """Descobre metadados CKAN e preserva manifesto (sem baixar bases eleitorais)."""
    catalog = Catalog(storage_root())
    for y in YEARS if all_years else [year]:
        result = catalog.discover(y)
        emit({"year": y, "datasets": len(result["datasets"]), "resources": len(catalog.resources(y)),
              "status": result["status"], "catalog_hash": result["catalog_hash"]})


@app.command()
def resources(year: int = 2022, kind: str | None = None):
    """Lista recursos reais do catálogo local."""
    emit([{k: r.get(k) for k in ("id", "name", "url", "size", "dataset_id")} for r in Catalog(storage_root()).resources(year)
          if kind is None or family(r) == kind])


@app.command("profile")
def profile_command(input: Path | None = None, resource: str | None = None):
    """Inspeciona arquivo local ou índice ZIP remoto sem download integral."""
    if input:
        emit(profile(input))
    elif resource:
        source = Catalog(storage_root()).resource(resource)
        with RemoteZipReader(source["url"], budget=16*1024**2) as remote, zipfile.ZipFile(remote) as archive:
            emit({"resource": resource, "bytes": remote.size,
                  "members": [{"name": i.filename, "bytes": i.file_size, "compressed": i.compress_size} for i in safe_members(archive)]})
    else:
        raise typer.BadParameter("Informe --input ou --resource")


@app.command("fetch")
def fetch_command(resource: str, member: str | None = None, input: Path | None = None, max_mb: int = 512):
    """Baixa/importa fonte catalogada e emite recibo SHA-256."""
    if max_mb <= 0:
        raise typer.BadParameter("max-mb deve ser positivo")
    root = storage_root()
    source = Catalog(root).resource(resource)
    if input:
        result = preserve_asset(root, input, source, {"acquisition": "MANUAL_IMPORT", "origin_verification": "OPERATOR_SUPPLIED"})
    elif member:
        result = fetch_member(root, source, member, max_mb*1024**2)
    else:
        result = fetch(root, source, max_mb*1024**2)
    emit(result)


@app.command("ingest")
def ingest_command(receipt: Annotated[list[Path], typer.Option()], year: int, uf: str, round: int = 1,
                   kind: str = "turnout", demo: bool = False):
    """Valida fontes/partição e publica snapshot atomicamente."""
    result = run_ingest(storage_root(), [read_json(p) for p in receipt], year, round, uf, kind, "demo" if demo else "official")
    emit({"snapshot_id": result["snapshot_id"], "quality": result["quality"], "idempotent": result.get("idempotent", False)})


@app.command("ingest-log")
def ingest_log_command(receipt: Path, year: int, uf: str, municipality: str, zone: str, section: str,
                       round: int = 1, timezone: str | None = None):
    """Ingere log com classificação conservadora e validação geográfica."""
    result = ingest_log(storage_root(), read_json(receipt), year, round, uf, municipality, zone, section, timezone)
    emit({"snapshot_id": result["snapshot_id"], "quality": result["quality"]})


@app.command()
def collect(year: int = 2022, uf: str = "MA", round: int | None = None, refresh: bool = False):
    """Captura compacta de uma UF do Norte/Nordeste, sem manter ZIP/CSV amplo."""
    from auditabr.regional import collect_regions
    failed = False
    def progress(result):
        nonlocal failed
        failed = failed or result["status"] in ("FAILED", "RESOURCE_AMBIGUOUS")
        emit(result)
    collect_regions(storage_root(),Path("storage"),(year,),progress,(uf,),(round,) if round else (1,2),refresh)
    if failed:
        raise typer.Exit(1)


@app.command("collect-regions")
def collect_regional(years: str = ",".join(map(str, YEARS)), refresh: bool = False):
    """Processa os 16 estados; lista de anos separada por vírgulas."""
    from auditabr.regional import collect_regions
    failed = False
    def progress(result):
        nonlocal failed
        failed = failed or result["status"] == "FAILED"
        emit(result)
    collect_regions(storage_root(),Path("storage"),[int(y) for y in years.split(",")],progress,refresh=refresh)
    if failed:
        raise typer.Exit(1)


@app.command()
def validate(snapshot: str | None = None):
    """Confere hashes e invariantes do snapshot publicado."""
    root = storage_root()
    manifest = current_manifest(root, snapshot)
    if not manifest:
        raise typer.BadParameter("Sem snapshot")
    failures = []
    database = root / "gold" / f"{manifest['snapshot_id']}.duckdb"
    if sha256(database) != manifest["database_sha256"]:
        failures.append("Hash do banco divergente")
    for asset in manifest["sources"]:
        if sha256(Path(asset["path"])) != asset["sha256"]:
            failures.append(f"Hash raw divergente: {asset['sha256']}")
    with reader(root, manifest["snapshot_id"]) as db:
        if db.execute("SELECT count(*) FROM section_turnout WHERE eligible != present+absent").fetchone()[0]:
            failures.append("Reconciliação comparecimento")
        totals = rows(db, "SELECT year,round,uf,count(*) sections,sum(eligible)::BIGINT eligible,sum(present)::BIGINT present,sum(absent)::BIGINT absent FROM section_turnout GROUP BY ALL ORDER BY ALL")
    result = {"snapshot_id": manifest["snapshot_id"], "checked_at": utcnow(), "failures": failures, "totals": totals}
    write_json(root / "manifests" / f"validation-{manifest['snapshot_id']}.json", result)
    emit(result)
    if failures:
        raise typer.Exit(1)


@app.command("retain-snapshots")
def retention(keep: int = 2, apply: bool = False):
    """Lista versões físicas antigas; --apply remove após conferir hashes. Capturas permanecem."""
    from auditabr.maintenance import retain_snapshots
    emit(retain_snapshots(storage_root(),keep,apply))


@app.command()
def query(year: int = 2022, round: int = 1, uf: str | None = None, municipality: str | None = None, group_by: str = "uf"):
    """Consulta taxas calculadas por soma de contagens."""
    if group_by not in ("uf", "municipality", "zone", "place", "section"):
        raise typer.BadParameter("group-by inválido")
    emit(turnout(storage_root(), Scope(year=year, round=round, uf=uf, municipality=municipality), cast(Group,group_by)))


@app.command()
def report(year: int = 2022, round: int = 1, uf: str | None = None, municipality: str | None = None,
           snapshot: str | None = None, group_by: str = "municipality"):
    """Exporta CSV/JSON/Parquet/Markdown/HTML e manifesto verificável."""
    result = create_report(storage_root(), Scope(year=year, round=round, uf=uf, municipality=municipality, snapshot=snapshot), group_by)
    emit({"report_id": result["report_id"], "folder": str(storage_root() / "reports" / result["report_id"]), "files": result["files"]})


@app.command()
def diff(previous: str, current: str):
    """Compara alterações entre dois snapshots imutáveis."""
    emit(snapshot_diff(storage_root(), previous, current))


@app.command()
def backup(destination: Path):
    """Copia o armazenamento com snapshots/manifests; não sobrescreve destino."""
    if destination.exists():
        raise typer.BadParameter("Destino deve ser novo")
    root, target = storage_root().resolve(), destination.resolve()
    if target == root or root in target.parents:
        raise typer.BadParameter("Backup deve ficar fora da origem")
    if (root / "writer.lock").exists():
        raise typer.BadParameter("Aguarde a ingestão terminar")
    shutil.copytree(root, target, ignore=shutil.ignore_patterns("cache", "*.staging.duckdb"))
    manifest = current_manifest(root)
    emit({"backup": str(target), "snapshot": manifest and manifest["snapshot_id"]})


@app.command()
def serve(api_port: int = 8000, ui_port: int = 8501, api_only: bool = False):
    """Inicia API/painel em 127.0.0.1. Ctrl+C encerra os dois processos."""
    import uvicorn
    if api_only:
        from auditabr.api import create_app
        uvicorn.run(create_app(storage_root()), host="127.0.0.1", port=api_port)
        return
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "auditabr.api:app", "--host", "127.0.0.1", "--port", str(api_port)])
    ui_file = Path(__file__).with_name("ui.py")
    ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ui_file), "--server.address", "127.0.0.1",
                           "--server.port", str(ui_port), "--server.headless", "true", "--browser.gatherUsageStats", "false"])
    typer.echo(f"Painel: http://127.0.0.1:{ui_port} | API: http://127.0.0.1:{api_port}/docs")
    try:
        ui.wait()
    except KeyboardInterrupt:
        pass
    finally:
        ui.terminate()
        api.terminate()


if __name__ == "__main__":
    app()
