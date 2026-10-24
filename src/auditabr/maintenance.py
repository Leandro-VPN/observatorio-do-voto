"""Explicit retention of generated physical snapshots; source captures remain intact."""
from pathlib import Path

from auditabr.storage import current_manifest
from auditabr.utils import read_json, sha256, utcnow, write_json


def retain_snapshots(root: Path, keep=2, apply=False):
    if keep < 1:
        raise ValueError("Conserve ao menos uma versão física")
    if (root/"writer.lock").exists():
        raise ValueError("Aguarde a publicação terminar antes da retenção")
    current = current_manifest(root)
    if not current:
        raise ValueError("Sem versão publicada")
    manifests = [read_json(p) for p in (root/"manifests"/"snapshots").glob("*.json")]
    available = sorted([m for m in manifests if m.get("status")=="PUBLISHED"],key=lambda m:m["published_at"],reverse=True)
    retained = {m["snapshot_id"] for m in available[:keep]} | {current["snapshot_id"]}
    removed = []
    gold = (root/"gold").resolve()
    for manifest in available:
        sid = manifest["snapshot_id"]
        if sid in retained:
            continue
        if len(sid)!=24 or not sid.isalnum():
            raise ValueError("Identidade de snapshot inválida")
        path = (gold/f"{sid}.duckdb").resolve()
        if path.parent != gold:
            raise ValueError("Retenção fora do diretório gold")
        if not path.exists():
            continue
        if sha256(path)!=manifest["database_sha256"]:
            raise ValueError("Snapshot alterado; não será removido automaticamente")
        record = {"snapshot_id":sid,"bytes":path.stat().st_size,"path":str(path)}
        if apply:
            try:
                path.unlink()
            except PermissionError:
                record["status"]="IN_USE_PRESERVED"
                removed.append(record)
                continue
            manifest.update(status="PRUNED_PHYSICAL",pruned_at=utcnow(),
                retention_note="Banco físico removido por economia de espaço; manifesto e capturas selecionadas preservados.")
            write_json(root/"manifests"/"snapshots"/f"{sid}.json",manifest)
        record["status"]="REMOVED" if apply else "PLANNED"
        removed.append(record)
    result={"at":utcnow(),"apply":apply,"keep":keep,"retained":sorted(retained),"snapshots":removed}
    if apply:
        write_json(root/"manifests"/f"retention-{current['snapshot_id']}.json",result)
    return result
