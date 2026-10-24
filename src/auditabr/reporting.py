from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from auditabr import __version__
from auditabr.queries import Scope, turnout
from auditabr.storage import current_manifest, reader, rows
from auditabr.utils import digest, sha256, utcnow, write_json


def create_report(root: Path, scope: Scope, group_by="municipality"):
    snapshot = current_manifest(root, scope.snapshot)
    if not snapshot:
        raise ValueError("Não há snapshot publicado")
    scope = scope.model_copy(update={"snapshot": snapshot["snapshot_id"]})
    offset, data = 0, []
    while True:
        result = turnout(root, scope, group_by, 10000, offset)
        data.extend(result["data"])
        if not result["pagination"]["has_more"]:
            break
        offset += 10000
    for item in data:
        item.update(year=scope.year, round=scope.round, snapshot_id=snapshot["snapshot_id"],
                    method_version=result["meta"]["methodology_version"],
                    coverage_status=result["meta"]["source_coverage"]["status"])
    report_id = digest([scope.model_dump(), group_by, __version__])[:24]
    folder = root / "reports" / report_id
    folder.mkdir(parents=True, exist_ok=True)
    result["data"] = data
    write_json(folder / "data.json", result)
    if data:
        with (folder / "data.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            for item in data:
                # Spreadsheet formula injection is prevented in exported text fields.
                writer.writerow({k: "'"+v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for k, v in item.items()})
        pq.write_table(pa.Table.from_pylist(data), folder / "data.parquet", compression="zstd")
    else:
        (folder / "data.csv").write_text("year,round,eligible,present,absent,abstention_rate\n", encoding="utf-8")
        pq.write_table(pa.table({"year": pa.array([], type=pa.int64())}), folder / "data.parquet")
    title = f"AUDITA-BR · {scope.year} · {scope.round}º turno"
    lines = [f"# {title}", "", f"Snapshot: `{snapshot['snapshot_id']}`", f"Modo: {snapshot['mode']}",
             f"Filtro: `{json.dumps(scope.model_dump(), ensure_ascii=False)}`", "",
             "Fórmula: taxa de abstenção = soma de ausentes / soma de aptos. Cada seção é contada uma vez.",
             "Média simples de taxas de seção é uma medida diferente.", "",
             "Cobertura: " + json.dumps(result["meta"]["source_coverage"], ensure_ascii=False), "",
             *result["meta"]["limitations"], "", "## Fontes do snapshot"]
    for asset in snapshot["sources"]:
        lines.append(f"- {asset['source_url']} · recurso {asset['resource_id']} · SHA-256 `{asset['sha256']}`")
    lines += ["", "Os arquivos CSV/JSON/Parquet contêm os dados deste relatório.", "",
              f"Reprodução: auditabr report --year {scope.year} --round {scope.round} --snapshot {snapshot['snapshot_id']}" +
              (f" --uf {scope.uf}" if scope.uf else "") + (f" --municipality {scope.municipality}" if scope.municipality else "")]
    markdown = "\n".join(lines)
    (folder / "report.md").write_text(markdown, encoding="utf-8")
    table = ""
    if data:
        headers = list(data[0])
        table = "<table><thead><tr>"+"".join(f"<th>{html.escape(k)}</th>" for k in headers)+"</tr></thead><tbody>"
        for item in data:
            table += "<tr>"+"".join(f"<td>{html.escape(str(item[k]))}</td>" for k in headers)+"</tr>"
        table += "</tbody></table>"
    document = '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>'+html.escape(title)+"</title>"
    document += "<style>body{font:15px system-ui;margin:40px;color:#173c40}pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #cbd5d5}</style>"
    document += "<h1>"+html.escape(title)+"</h1><pre>"+html.escape(markdown)+"</pre>"+table+"</html>"
    (folder / "report.html").write_text(document, encoding="utf-8")
    manifest = {"report_id": report_id, "created_at": utcnow(), "snapshot_id": snapshot["snapshot_id"],
                "parameters": scope.model_dump(), "group_by": group_by, "version": __version__,
                "sources": snapshot["sources"], "meta": result["meta"],
                "files": {p.name: sha256(p) for p in folder.iterdir() if p.name != "manifest.json"}}
    write_json(folder / "manifest.json", manifest)
    return manifest


def snapshot_diff(root: Path, previous: str, current: str):
    output: dict[str, Any] = {"previous": previous, "current": current, "changes": []}
    with reader(root, previous) as left, reader(root, current) as right:
        a = {r["section_id"]: r for r in rows(left, "SELECT section_id,eligible,present,absent FROM section_turnout")}
        b = {r["section_id"]: r for r in rows(right, "SELECT section_id,eligible,present,absent FROM section_turnout")}
    for key in sorted(a.keys() | b.keys()):
        if a.get(key) != b.get(key):
            output["changes"].append({"section_id": key, "before": a.get(key), "after": b.get(key)})
    return output
