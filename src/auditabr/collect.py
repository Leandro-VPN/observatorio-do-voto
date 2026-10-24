"""Resumable collection plan: BR presidential files, UF mayor files only."""
from __future__ import annotations

import zipfile
from pathlib import Path

from auditabr.acquisition import RemoteZipReader, fetch_member, safe_members
from auditabr.catalog import Catalog, family
from auditabr.domain import check_scope, temporal_status
from auditabr.pipeline import ingest
from auditabr.utils import read_json, write_json


def collect(root: Path, year: int, uf: str, rounds=(1,2), refresh=False):
    check_scope(year,uf=uf)
    catalog=Catalog(root)
    if refresh or not catalog.resources(year):
        catalog.discover(year)
    resources=catalog.resources(year)
    source_scope="BR" if year%4==2 else uf
    for kind in ("turnout","votes"):
        candidates=[r for r in resources if family(r)==kind and
                    (kind=="turnout" or f"_{source_scope}.zip" in r["url"])]
        if len(candidates)!=1:
            yield {"year":year,"uf":uf,"family":kind,"status":"RESOURCE_AMBIGUOUS","count":len(candidates)}
            continue
        resource=candidates[0]
        index=root/"cache"/f"acquired-{year}-{source_scope}-{kind}.json"
        try:
            if index.exists() and not refresh:
                asset=read_json(index)
            else:
                with RemoteZipReader(resource["url"],budget=16*1024**2) as remote,zipfile.ZipFile(remote) as archive:
                    members=[i.filename for i in safe_members(archive) if i.filename.lower().endswith(".csv")
                             and f"_{source_scope}." in i.filename]
                if len(members)!=1:
                    raise ValueError("Membro oficial do recorte não identificado")
                asset=fetch_member(root,resource,members[0],budget=512*1024**2)
                write_json(index,asset)
            yield {"year":year,"uf":uf,"family":kind,"status":"FETCHED","bytes":asset["bytes"],"sha256":asset["sha256"]}
            for round in rounds:
                if temporal_status(year,round)=="FUTURE":
                    yield {"year":year,"round":round,"uf":uf,"family":kind,"status":"FUTURE"}
                    continue
                try:
                    manifest=ingest(root,[asset],year,round,uf,kind)
                    yield {"year":year,"round":round,"uf":uf,"family":kind,"status":"PUBLISHED",
                           "snapshot_id":manifest["snapshot_id"],"idempotent":manifest.get("idempotent",False)}
                except ValueError as exc:
                    state = {"year":year,"round":round,"uf":uf,"family":kind,"status":"NOT_APPLICABLE" if "Nenhuma linha" in str(exc) else "FAILED","reason":str(exc), "asset_id":asset["sha256"]}
                    write_json(root/"coverage"/f"{year}-{round}-{uf}-{kind}.json",state)
                    yield state
        except Exception as exc:
            yield {"year":year,"uf":uf,"family":kind,"status":"FAILED","reason":str(exc)}
