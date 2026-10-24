"""Catálogo CKAN; nunca gera URLs de arquivos a partir do ano."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from auditabr.domain import YEARS
from auditabr.utils import digest, read_json, utcnow, write_json

API = "https://dadosabertos.tse.jus.br/api/3/action"


class Catalog:
    def __init__(self, root: Path, client: httpx.Client | None = None):
        self.root = root
        self.client = client or httpx.Client(timeout=40, follow_redirects=False)

    def call(self, action: str, **params):
        if action not in {"package_search", "package_show", "resource_show"}:
            raise ValueError("Ação CKAN inválida")
        for attempt in range(3):
            try:
                response = self.client.get(f"{API}/{action}", params=params)
                response.raise_for_status()
                payload = response.json()
                if not payload.get("success"):
                    raise ValueError("CKAN retornou success=false")
                return payload["result"]
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Catálogo indisponível")

    def search(self, query: str, rows: int = 50):
        offset, seen = 0, set()
        while True:
            result = self.call("package_search", q=query, rows=rows, start=offset)
            entries = result["results"]
            if not entries:
                if offset < result["count"]:
                    raise ValueError("Paginação CKAN interrompida")
                break
            fresh = [p for p in entries if p["id"] not in seen]
            if not fresh:
                raise ValueError("CKAN repetiu página; catálogo incompleto")
            for package in fresh:
                seen.add(package["id"])
                yield package
            offset += len(entries)
            if offset >= result["count"]:
                break

    def discover(self, year: int) -> dict:
        if year not in YEARS:
            raise ValueError("Ano fora de escopo")
        packages = {}
        # CKAN searches metadata only. Exact year is checked in the returned slug/title.
        for p in self.search(str(year)):
            if str(year) in f"{p.get('name', '')} {p.get('title', '')}":
                packages[p["id"]] = p
        result: dict[str, Any] = {"year": year, "retrieved_at": utcnow(), "api": API, "status": "DISCOVERED_NOT_FETCHED",
                  "datasets": sorted(packages.values(), key=lambda p: p["name"])}
        result["catalog_hash"] = digest(result)
        destination = self.root / "manifests" / "catalog" / f"{year}-{result['catalog_hash'][:16]}.json"
        write_json(destination, result)
        write_json(self.root / "catalog" / f"{year}.json", result)
        return result

    def resources(self, year: int | None = None) -> list[dict]:
        paths = [self.root / "catalog" / f"{year}.json"] if year else sorted((self.root / "catalog").glob("*.json"))
        output = []
        for path in paths:
            if not path.exists():
                continue
            catalog = read_json(path)
            for dataset in catalog["datasets"]:
                for r in dataset.get("resources", []):
                    output.append({**r, "dataset_id": dataset["id"], "dataset_name": dataset["name"],
                                   "year": catalog["year"], "license": dataset.get("license_title"),
                                   "catalog_hash": catalog["catalog_hash"], "retrieved_at": catalog["retrieved_at"],
                                   "page_url": f"https://dadosabertos.tse.jus.br/dataset/{dataset['name']}"})
        return output

    def resource(self, resource_id: str) -> dict:
        found = [r for r in self.resources() if r["id"] == resource_id]
        if not found:
            raise ValueError("Recurso não catalogado; execute discover primeiro")
        return found[-1]


def family(resource: dict) -> str:
    text = str(resource.get("url", "")).lower()
    for word, kind in [("detalhe_votacao_secao", "turnout"), ("votacao_secao", "votes"),
                       ("consulta_cand", "candidates"), ("eleitorado_local", "places"),
                       ("arqurnatot", "logs"), ("bweb", "bu")]:
        if word in text:
            return kind
    return "other"


def official_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not (host == "tse.jus.br" or host.endswith(".tse.jus.br"))):
        raise ValueError("Apenas HTTPS em domínios oficiais tse.jus.br é permitido")
    return url

