import io
import zipfile

import httpx
import pytest

from auditabr.acquisition import RemoteZipReader, fetch, safe_members
from auditabr.catalog import Catalog, official_url
from auditabr.utils import sha256, write_json


def resource():
    return {"id": "test", "dataset_id": "test-dataset", "url": "https://cdn.tse.jus.br/test.csv"}


def response(code, content, headers):
    return httpx.Response(code, stream=httpx.ByteStream(content), headers=headers)


@pytest.mark.parametrize("url", ["http://cdn.tse.jus.br/file", "https://tse.jus.br.evil.test/file",
                                "https://localhost/file", "https://user:pass@cdn.tse.jus.br/file"])
def test_url_policy(url):
    with pytest.raises(ValueError):
        official_url(url)


@pytest.mark.parametrize("name", ["../bad.csv", "/bad.csv", "C:/bad.csv", "folder/../../bad.csv"])
def test_zip_slip(name):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, "data")
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as archive, pytest.raises(ValueError):
        safe_members(archive)


def test_resume_and_hash(tmp_path):
    folder = tmp_path / "cache" / "test"
    folder.mkdir(parents=True)
    (folder / "download.part").write_bytes(b"abc")
    write_json(folder / "resume.json", {"validator": '"v1"'})

    def handler(request):
        assert request.headers["range"] == "bytes=3-"
        assert request.headers["if-range"] == '"v1"'
        return response(206, b"def", {"etag": '"v1"', "content-range": "bytes 3-5/6"})

    receipt = fetch(tmp_path, resource(), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert receipt["bytes"] == 6
    from pathlib import Path
    assert Path(receipt["path"]).read_bytes() == b"abcdef"
    assert receipt["sha256"] == sha256(Path(receipt["path"]))


def test_range_200_restarts(tmp_path):
    folder = tmp_path / "cache" / "test"
    folder.mkdir(parents=True)
    (folder / "download.part").write_bytes(b"old")
    write_json(folder / "resume.json", {"validator": '"v1"'})
    client = httpx.Client(transport=httpx.MockTransport(lambda r: response(200, b"newdata", {"etag": '"v2"', "content-length": "7"})))
    receipt = fetch(tmp_path, resource(), client=client)
    assert receipt["bytes"] == 7


def test_bad_content_range_quarantines(tmp_path):
    folder = tmp_path / "cache" / "test"
    folder.mkdir(parents=True)
    (folder / "download.part").write_bytes(b"abc")
    write_json(folder / "resume.json", {"validator": '"v1"'})
    client = httpx.Client(transport=httpx.MockTransport(lambda r: response(206, b"def", {"etag": '"v2"', "content-range": "bytes 3-5/6"})))
    with pytest.raises(ValueError):
        fetch(tmp_path, resource(), client=client)
    assert list((tmp_path / "quarantine").glob("*/error.json"))
    assert not list((tmp_path / "raw").glob("*"))


def test_remote_zip_validates_offsets_and_crc():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("sample.csv", "a;b\n1;2\n")
    data = buffer.getvalue()

    def handler(request):
        start, end = map(int, request.headers["range"].removeprefix("bytes=").split("-"))
        return response(206, data[start:end + 1], {"etag": '"stable"', "content-range": f"bytes {start}-{end}/{len(data)}"})

    with RemoteZipReader("https://cdn.tse.jus.br/data.zip", httpx.Client(transport=httpx.MockTransport(handler))) as remote:
        with zipfile.ZipFile(remote) as archive:
            assert archive.read("sample.csv") == b"a;b\n1;2\n"


def test_catalog_pagination(tmp_path):
    def handler(request):
        start = int(request.url.params["start"])
        return httpx.Response(200, json={"success": True, "result": {"count": 3, "results":
            [{"id": str(i)} for i in range(start, min(start + 2, 3))]}})
    catalog = Catalog(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(list(catalog.search("2022", rows=2))) == 3

