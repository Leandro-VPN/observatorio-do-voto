"""RF-003..005/053: downloads limitados e ZIP remoto com Range verificado."""
from __future__ import annotations

import io
import re
import shutil
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin

import httpx

from auditabr.catalog import official_url
from auditabr.utils import digest, read_json, sha256, utcnow, write_json

MAX_MEMBER = 2 * 1024**3


def safe_members(archive: zipfile.ZipFile, max_member=MAX_MEMBER, max_total=30 * 1024**3):
    entries, names, total = archive.infolist(), set(), 0
    if len(entries) > 250_000:
        raise ValueError("ZIP: excesso de membros")
    for entry in entries:
        name = entry.filename.replace("\\", "/")
        path = PurePosixPath(name)
        mode = entry.external_attr >> 16
        if (path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name
                or stat.S_ISLNK(mode) or name.casefold() in names or entry.flag_bits & 1):
            raise ValueError("ZIP: nome inseguro, duplicado, symlink ou criptografia")
        names.add(name.casefold())
        total += entry.file_size
        if (entry.file_size > max_member or total > max_total
                or entry.file_size / max(entry.compress_size, 1) > 1000):
            raise ValueError("ZIP: limite de descompressão excedido")
    return entries


def get_response(client, url: str, headers: dict | None = None, stream=False):
    for _ in range(5):
        official_url(url)
        req = client.build_request("GET", url, headers={"Accept-Encoding": "identity", **(headers or {})})
        resp = client.send(req, stream=stream)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            resp.close()
            url = urljoin(url, location)
        else:
            resp.raise_for_status()
            if resp.headers.get("content-encoding", "identity") != "identity":
                resp.close()
                raise ValueError("Encoding de transporte incompatível com offsets")
            return resp
    raise ValueError("Excesso de redirecionamentos")


def validator(headers) -> str | None:
    etag = headers.get("etag")
    return etag if etag and not etag.startswith("W/") else headers.get("last-modified")


class RemoteZipReader(io.RawIOBase):
    """Seekable HTTP with bounded cache. Every read validates identity, 206 and offsets.

    No full-object authenticity claim: downloaded members have their own hash/CRC.
    """
    def __init__(self, url: str, client=None, budget=512 * 1024**2):
        self.url = official_url(url)
        self.client = client or httpx.Client(timeout=90)
        self.owns_client = client is None
        self.budget, self.transferred, self.pos = budget, 0, 0
        resp = get_response(self.client, url, {"Range": "bytes=0-0"}, stream=True)
        try:
            match = re.fullmatch(r"bytes 0-0/(\d+)", resp.headers.get("content-range", ""))
            if resp.status_code != 206 or not match:
                raise ValueError("Servidor não suporta Range validado; use fetch integral")
            self.size = int(match[1])
            self.identity = validator(resp.headers)
            if not self.identity:
                raise ValueError("Sem ETag/Last-Modified para fixar versão do ZIP")
            payload = b"".join(resp.iter_raw())
            if len(payload) != 1:
                raise ValueError("Range inicial inválido")
        finally:
            resp.close()
        self.headers = dict(resp.headers)

    def seekable(self):
        return True

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        if self.pos < 0:
            raise ValueError("Seek negativo")
        return self.pos

    def read(self, n=-1):
        if self.pos >= self.size:
            return b""
        n = min(self.size - self.pos, self.size if n < 0 else n)
        if not n:
            return b""
        if self.transferred + n > self.budget:
            raise ValueError("Orçamento de download seletivo excedido")
        end = self.pos + n - 1
        expected = f"bytes {self.pos}-{end}/{self.size}"
        for attempt in range(3):
            try:
                resp = get_response(self.client, self.url,
                                    {"Range": f"bytes={self.pos}-{end}", "If-Range": self.identity}, stream=True)
                try:
                    if (resp.status_code != 206 or resp.headers.get("content-range") != expected
                            or validator(resp.headers) != self.identity):
                        raise ValueError("Fonte mudou ou Content-Range inválido")
                    chunks, count = [], 0
                    for block in resp.iter_raw():
                        count += len(block)
                        if count > n:
                            raise ValueError("Resposta Range excedeu o solicitado")
                        chunks.append(block)
                    data = b"".join(chunks)
                    if len(data) != n:
                        raise httpx.ReadError("Range truncado")
                    self.pos += n
                    self.transferred += n
                    return data
                finally:
                    resp.close()
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Range falhou")

    def close(self):
        if self.owns_client:
            self.client.close()
        super().close()


def preserve_asset(root: Path, path: Path, resource: dict, extra: dict | None = None) -> dict:
    checksum = sha256(path)
    target = root / "raw" / checksum / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(path, target)
    if sha256(target) != checksum:
        raise ValueError("Raw existente não corresponde ao hash")
    receipt = {"asset_id": checksum, "sha256": checksum, "bytes": target.stat().st_size,
               "path": str(target.resolve()), "resource_id": resource["id"],
               "dataset_id": resource["dataset_id"], "source_url": resource["url"],
               "page_url": resource.get("page_url"), "catalog_hash": resource.get("catalog_hash"),
               "license": resource.get("license"), "retrieved_at": utcnow(), "status": "VERIFIED",
               **(extra or {})}
    destination = root / "manifests" / "assets" / f"{checksum}-{digest(receipt)[:12]}.json"
    write_json(destination, receipt)
    # Cache is disposable, raw is not. Remove only our verified redundant copy.
    resolved = path.resolve()
    cache_root = (root / "cache").resolve()
    if cache_root in resolved.parents and resolved != target.resolve() and sha256(resolved) == checksum:
        resolved.unlink()
    return receipt


def fetch_member(root: Path, resource: dict, member: str, budget=512 * 1024**2) -> dict:
    cache = root / "cache" / digest([resource["id"], member])
    cache.mkdir(parents=True, exist_ok=True)
    part = cache / "member.part"
    with RemoteZipReader(resource["url"], budget=budget) as remote:
        with zipfile.ZipFile(remote) as archive:
            safe_members(archive)
            info = archive.getinfo(member)
            if shutil.disk_usage(root).free < info.file_size * 2 + 64 * 1024**2:
                raise ValueError("Espaço insuficiente para membro ZIP")
            with archive.open(info) as source, part.open("wb") as target:
                shutil.copyfileobj(source, target, 1024**2)
            # zipfile validates the member CRC as the stream reaches EOF.
            path = cache / Path(member.replace("\\", "/")).name
            part.replace(path)
            return preserve_asset(root, path, resource, {"acquisition": "PARTIAL_FETCH", "member": member,
                                  "container_size": remote.size, "http": remote.headers,
                                  "transport_bytes": remote.transferred, "member_crc32": info.CRC,
                                  "container_sha256": None})


def fetch(root: Path, resource: dict, max_bytes=2 * 1024**3, client=None) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    cache = root / "cache" / resource["id"]
    cache.mkdir(parents=True, exist_ok=True)
    part, meta = cache / "download.part", cache / "resume.json"
    owns_client = client is None
    client = client or httpx.Client(timeout=90)
    try:
        for attempt in range(3):
            old = read_json(meta) if meta.exists() else {}
            start = part.stat().st_size if part.exists() and old.get("validator") else 0
            headers = {"Range": f"bytes={start}-", "If-Range": old["validator"]} if start else {}
            try:
                response = get_response(client, resource["url"], headers, stream=True)
                try:
                    append = start > 0 and response.status_code == 206
                    if append:
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
                        if (not match or int(match[1]) != start or int(match[2]) != int(match[3]) - 1
                                or validator(response.headers) != old["validator"]):
                            meta.unlink(missing_ok=True)
                            raise ValueError("Retomada rejeitada: Range ou identidade divergente")
                        total = int(match[3])
                    elif response.status_code == 200:
                        start = 0
                        total = int(response.headers.get("content-length", 0))
                    else:
                        raise ValueError("Resposta HTTP incompatível com download")
                    if total > max_bytes or shutil.disk_usage(root).free < max(total - start, 0) + 64 * 1024**2:
                        raise ValueError("Download excede limite de bytes/espaço")
                    write_json(meta, {"validator": validator(response.headers), "url": resource["url"]})
                    count = start
                    with part.open("ab" if append else "wb") as target:
                        for block in response.iter_raw(1024**2):
                            count += len(block)
                            if count > max_bytes or (total and count > total):
                                raise ValueError("Resposta excede o tamanho permitido")
                            target.write(block)
                    if total and count != total:
                        raise httpx.ReadError("Download truncado")
                    if zipfile.is_zipfile(part):
                        with zipfile.ZipFile(part) as archive:
                            safe_members(archive)
                            if archive.testzip() is not None:
                                raise ValueError("ZIP com CRC inválido")
                    suffix = Path(resource["url"].split("?")[0]).suffix or ".bin"
                    if suffix.lower() == ".zip" and not zipfile.is_zipfile(part):
                        raise ValueError("Conteúdo não é um ZIP íntegro")
                    final = cache / f"source{suffix}"
                    part.replace(final)
                    return preserve_asset(root, final, resource, {"acquisition": "FULL_FETCH", "http": dict(response.headers)})
                finally:
                    response.close()
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
            except ValueError as exc:
                quarantine = root / "quarantine" / digest([resource["id"], utcnow()])
                quarantine.mkdir(parents=True, exist_ok=True)
                if part.exists():
                    part.replace(quarantine / "download.part")
                write_json(quarantine / "error.json", {"resource_id": resource["id"], "error": str(exc)})
                meta.unlink(missing_ok=True)
                raise
    finally:
        if owns_client:
            client.close()
    raise RuntimeError("Download falhou")


def profile(path: Path) -> dict:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            entries = safe_members(archive)
            return {"kind": "ZIP", "members": [{"name": i.filename, "bytes": i.file_size,
                    "compressed": i.compress_size} for i in entries]}
    with path.open("rb") as stream:
        sample = stream.read(65536)
    try:
        text = sample.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        text, encoding = sample.decode("latin-1"), "latin-1"
    header = text.splitlines()[0] if text else ""
    return {"kind": "TEXT", "encoding": encoding, "header": header, "fingerprint": digest(header)}
