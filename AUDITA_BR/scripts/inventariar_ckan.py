#!/usr/bin/env python3
"""Inventário de metadados (não faz download de bases grandes) da API CKAN do TSE.

Exemplos:
  python scripts/inventariar_ckan.py --year 2022 --out storage/manifests/catalogo_2022.json
  python scripts/inventariar_ckan.py --query "resultados-2026" --query "eleitorado-2026"

Somente domínio TSE de catálogo. Não supõe formatos nem informações futuras.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import random
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://dadosabertos.tse.jus.br/api/3/action"
USER_AGENT = "Auditabr-CatalogInventory/0.1 (+fonte oficial TSE; metadata only)"
FAMILIES = ("resultados", "boletim", "arquivos transmitidos", "comparecimento", "eleitorado", "candidatos")


def get_ckan_json(action: str, params: dict[str, object], timeout: int = 30, attempts: int = 3) -> dict:
    if action not in {"package_search", "package_show", "resource_show"}:
        raise ValueError("Ação CKAN não permitida")
    url = f"{API_BASE}/{action}?{urlencode(params)}"
    last = None
    for attempt in range(attempts):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP inesperado: {resp.status}")
                payload = resp.read(20 * 1024 * 1024 + 1)
                if len(payload) > 20 * 1024 * 1024:
                    raise RuntimeError("Resposta de catálogo excessivamente grande")
                obj = json.loads(payload.decode("utf-8"))
                if not isinstance(obj, dict) or obj.get("success") is not True:
                    raise RuntimeError("CKAN respondeu sem success=true")
                return obj["result"]
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if isinstance(exc, HTTPError) and exc.code not in {429, 500, 502, 503, 504}:
                break
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt + random.random(), 8))
    raise RuntimeError(f"Falha CKAN {action}: {last}")


def discover(query: str, rows: int = 50, max_results: int = 500) -> list[dict]:
    offset = 0
    result: list[dict] = []
    while offset < max_results:
        take = min(rows, max_results - offset)
        payload = get_ckan_json("package_search", {"q": query, "rows": take, "start": offset})
        packages = payload.get("results", [])
        if not isinstance(packages, list):
            raise RuntimeError("Schema inesperado de package_search.results")
        result.extend(packages)
        offset += len(packages)
        total = int(payload.get("count", len(result)))
        if not packages or offset >= total:
            break
    return result


def simplified_resource(resource: dict) -> dict:
    keys = ("id", "name", "description", "format", "url", "size", "created", "last_modified",
            "mimetype", "hash", "resource_type")
    return {k: resource.get(k) for k in keys}


def simplified_package(package: dict) -> dict:
    keys = ("id", "name", "title", "notes", "metadata_created", "metadata_modified",
            "license_id", "license_title", "organization")
    info = {k: package.get(k) for k in keys}
    info["resources"] = [simplified_resource(r) for r in package.get("resources", [])]
    return info


def main() -> int:
    p = argparse.ArgumentParser(description="Descobre fontes no catálogo TSE CKAN, sem baixar arquivos eleitorais")
    p.add_argument("--year", type=int, choices=[2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026])
    p.add_argument("--query", action="append", dest="queries", help="Termo de busca; repetir para vários")
    p.add_argument("--out", type=Path, default=Path("catalogo_tse.json"))
    p.add_argument("--rows", type=int, default=50)
    p.add_argument("--max-results", type=int, default=500)
    args = p.parse_args()

    if not 1 <= args.rows <= 1000 or args.max_results < 1:
        p.error("--rows deve ser 1..1000 e --max-results >= 1")
    queries = args.queries or ([f"{family} {args.year}" for family in FAMILIES]
                               if args.year else ["resultados 2022"])
    packages: dict[str, dict] = {}
    history = []
    try:
        for term in queries:
            found = discover(term, args.rows, args.max_results)
            history.append({"query": term, "returned": len(found)})
            for package in found:
                package_id = package.get("id") or package.get("name")
                if package_id:
                    packages[str(package_id)] = simplified_package(package)
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2

    output = {
        "source": "Tribunal Superior Eleitoral - API CKAN (catalog metadata)",
        "api_base": API_BASE,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "is_election_data": False,
        "downloaded_large_resources": False,
        "query_log": history,
        "dataset_count": len(packages),
        "datasets": sorted(packages.values(), key=lambda d: str(d.get("name") or "")),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temp = args.out.with_suffix(args.out.suffix + ".part")
    temp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(args.out)
    print(f"Catálogo salvo em: {args.out} | datasets encontrados: {len(packages)}")
    print("ATENÇÃO: nenhum arquivo de votação foi descarregado ou validado neste passo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
