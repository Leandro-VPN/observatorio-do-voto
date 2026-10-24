"""Retire generated pilot data only after its requested scope has a validated replacement."""
import argparse
import json
from pathlib import Path

from auditabr.utils import read_json, sha256, utcnow, write_json

parser = argparse.ArgumentParser()
parser.add_argument("--apply",action="store_true")
args = parser.parse_args()
workspace = Path(__file__).resolve().parents[1]
legacy = (workspace/"storage").resolve()
regional = (workspace/"storage-regional").resolve()
assert legacy.parent==workspace and regional.parent==workspace and legacy!=regional
if (legacy/"writer.lock").exists() or (regional/"writer.lock").exists():
    raise SystemExit("Há escritor ativo; não remover arquivos")
verification = read_json(regional/"manifests"/"regional-validation.json")
current = read_json(regional/"current.json")
assert verification["snapshot_id"]==current["snapshot_id"]
assert not verification["missing_first_round_partitions"]
assert verification["database_hash_ok"] and all(c["equal"] for c in verification["checks"])
assert all(c["ok"] for c in verification["source_hashes"])
parent_hashes = {d["source_read"].get("original_member_sha256")
                 for p in (regional/"captures").glob("*.json") if (d:=read_json(p))}
copied_hashes = {a["sha256"] for a in current["sources"]}
receipts = {Path(a["path"]).resolve():a for p in (legacy/"manifests"/"assets").glob("*.json") if (a:=read_json(p))}
excluded_state_files = {"detalhe_votacao_secao_2014_AC.csv","votacao_secao_2014_AC.csv",
                        "detalhe_votacao_secao_2022_MA.csv","votacao_secao_2022_MA.csv"}
planned = []
for folder in ("raw","silver","gold","cache"):
    directory = (legacy/folder).resolve()
    assert directory.parent==legacy
    for original in directory.rglob("*"):
        if not original.is_file():
            continue
        path=original.resolve()
        if directory not in path.parents:
            raise ValueError("Arquivo resolve fora do diretório gerado")
        if folder=="cache" and path.suffix==".json":
            continue
        if folder=="raw":
            if path not in receipts:
                raise ValueError(f"Raw não reconhecido; preservado: {path}")
            asset=receipts[path]
            if sha256(path)!=asset["sha256"]:
                raise ValueError(f"Raw alterado; preservado: {path}")
            if asset["sha256"] in copied_hashes:
                reason="IDENTICAL_COPY_IN_REGIONAL_STORE"
            elif asset["sha256"] in parent_hashes:
                reason="REQUESTED_RECORDS_PRESERVED_IN_SCOPED_CAPTURE"
            elif path.name in excluded_state_files:
                reason="OLD_STATEWIDE_GENERAL_ELECTION_SCOPE_EXCLUDED"
            else:
                raise ValueError(f"Não comprovada substituição: {path}")
        else:
            reason="GENERATED_PILOT_DERIVATIVE_OR_CACHE_SUPERSEDED"
        planned.append({"path":str(path),"bytes":path.stat().st_size,"reason":reason})
result={"at":utcnow(),"apply":args.apply,"replacement_snapshot":current["snapshot_id"],
        "files":planned,"bytes":sum(p["bytes"] for p in planned),
        "preserved":["source code","original specifications","catalogs","receipts","reports","regional captures"]}
write_json(regional/"manifests"/"pilot-retirement.json",result)
if args.apply:
    for item in planned:
        Path(item["path"]).unlink()
    for folder in ("raw","silver","gold","cache"):
        directory=legacy/folder
        for path in sorted([p for p in directory.rglob("*") if p.is_dir()],key=lambda p:len(p.parts),reverse=True):
            resolved=path.resolve()
            if directory.resolve() not in resolved.parents:
                raise ValueError("Diretório resolve fora do escopo")
            if not any(path.iterdir()):
                path.rmdir()
    for path in [legacy/"current.json",*(legacy/"manifests"/"snapshots").glob("*.json")]:
        manifest=read_json(path)
        manifest.update(status="RETIRED_PILOT",retired_at=utcnow(),replacement_storage=str(regional),
                        retention_note="Arquivos amplos substituídos por capturas Norte/Nordeste; versões físicas do piloto removidas.")
        write_json(path,manifest)
print(json.dumps({"apply":args.apply,"files":len(planned),"bytes":result["bytes"]}),flush=True)
