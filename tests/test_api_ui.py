from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auditabr.api import create_app
from auditabr.pipeline import ingest
from auditabr.queries import Scope
from auditabr.reporting import create_report
from tests.helpers import synthetic_asset, turnout_rows


@pytest.fixture
def populated(tmp_path):
    asset=synthetic_asset(tmp_path,turnout_rows())
    ingest(tmp_path,[asset],2022,1,"MA","turnout","demo")
    return tmp_path


def test_api_contract_and_invalid_filters(populated):
    client=TestClient(create_app(populated))
    result=client.get("/api/v1/metrics/turnout?year=2022&uf=MA").json()
    assert result["data"][0]["eligible"] == 500
    assert result["meta"]["mode"] == "demo"
    assert client.get("/api/v1/metrics/votes?office=VEREADOR").status_code == 422
    assert client.get("/api/v1/metrics/turnout?uf=SP").status_code == 422
    assert client.get("/api/v1/metrics/turnout?municipality=00001").status_code == 422
    assert client.get("/api/v1/metrics/votes?year=2018&round=2&office=SENADOR").status_code == 422
    result=client.get("/api/v1/metrics/times?year=2022&uf=MA").json()
    assert result["data"] == []
    assert result["meta"]["availability_status"] == "MISSING"
    assert client.post("/api/v1/reports",json={"scope":{"year":2022}}).status_code == 403


def test_report_all_formats_and_snapshot(populated):
    result=create_report(populated,Scope(year=2022,uf="MA"))
    assert set(result["files"]) == {"data.csv","data.json","data.parquet","report.md","report.html"}
    assert result["snapshot_id"]
    assert result["sources"][0]["sha256"]


def test_aggregate_labels_and_fixed_snapshot(populated):
    from auditabr.queries import pin_scope, turnout
    pinned = pin_scope(populated, Scope(year=2022, uf="MA"))
    result = turnout(populated, pinned)
    assert "municipality_name" not in result["data"][0]
    assert "place_name" not in result["data"][0]
    revised = turnout_rows()
    revised[2][10:12] = [80, 20]
    asset = synthetic_asset(populated, revised, name="revised.csv")
    ingest(populated, [asset], 2022, 1, "MA", "turnout", "demo")
    assert turnout(populated, pinned)["data"][0]["absent"] == 110
    assert turnout(populated, Scope(year=2022, uf="MA"))["data"][0]["absent"] == 120


def test_excluded_office_never_persisted(populated):
    from auditabr.storage import reader
    data = turnout_rows()
    data[0][7:9] = ["5", "Senador"]
    data[1][7:9] = ["3", "Governador"]
    asset = synthetic_asset(populated, data, name="mixed.csv")
    ingest(populated, [asset], 2022, 1, "MA", "turnout", "demo")
    with reader(populated) as db:
        assert db.execute("SELECT DISTINCT office FROM contest_vote_summary").fetchall() == [("PRESIDENTE",)]
        assert db.execute("SELECT count(*) FROM section_turnout").fetchone()[0] == 1


def test_ui_pages_with_fixture(populated,monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("AUDITABR_STORAGE",str(populated))
    path=Path(__file__).parents[1]/"src"/"auditabr"/"ui.py"
    app=AppTest.from_file(str(path),default_timeout=30).run()
    assert not app.exception
    for page in ["Geografia","Resultados","Abstenção","Horários","Habilitação","Histórico","Cruzamentos","Casos","Fontes e qualidade","Metodologia"]:
        app.radio[0].set_value(page).run()
        assert not app.exception, f"Página {page}: {app.exception}"
