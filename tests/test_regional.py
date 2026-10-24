from pathlib import Path

import pyarrow.parquet as pq
import pytest

from auditabr.acquisition import preserve_asset
from auditabr.domain import UFS, check_scope
from auditabr.pipeline import load_partition
from auditabr.regional import project_stream
from auditabr.storage import SnapshotBuilder
from tests.helpers import synthetic_asset, turnout_rows


def test_projection_keeps_only_requested_regions_and_office(tmp_path):
    records = turnout_rows()
    outside = list(records[0])
    outside[2] = "SP"
    records.append(outside)
    asset = synthetic_asset(tmp_path, records)
    with Path(asset["path"]).open("rb") as stream:
        stats = project_stream(stream,tmp_path/"capture",2022,("MA",))
    data = pq.read_table(tmp_path/"capture"/"MA.parquet").to_pylist()
    assert len(UFS)==16
    assert stats["input_records"]==4
    assert len(data)==2
    assert {r["DS_CARGO"] for r in data}=={"Presidente"}
    assert [r["_SOURCE_ROW"] for r in data]==[2,4]
    with pytest.raises(ValueError,match="Norte/Nordeste"):
        check_scope(2022,uf="SP")


def test_bad_count_row_quarantined_without_losing_other_sections(tmp_path):
    records=turnout_rows()
    records[0][11]=0
    asset=synthetic_asset(tmp_path,records)
    with Path(asset["path"]).open("rb") as stream:
        project_stream(stream,tmp_path/"capture",2022,("MA",))
    projected=preserve_asset(tmp_path,tmp_path/"capture"/"MA.parquet",
        {"id":"SYNTHETIC","dataset_id":"SYNTHETIC","url":"synthetic://fixture"})
    observation={"source_rows":0,"selected_rows":0}
    with SnapshotBuilder(tmp_path,{},[projected],"test",mode="demo") as builder:
        db=builder.connection
        load_partition(tmp_path,db,[projected],2022,1,"MA","turnout","test",observation,quarantine_bad_counts=True)
        assert db.execute("SELECT sum(eligible),sum(absent) FROM section_turnout").fetchone()==(100,10)
        assert observation["quarantined_rows"]==1
        assert db.execute("SELECT count(*) FROM quality_issue").fetchone()[0]==1
        assert db.execute("SELECT status FROM partition_registry").fetchone()[0]=="VALIDATED_WITH_EXCLUSIONS"


def test_retention_keeps_sources_and_current_snapshot(tmp_path):
    from auditabr.maintenance import retain_snapshots
    from auditabr.pipeline import ingest
    from auditabr.storage import reader
    asset=synthetic_asset(tmp_path,turnout_rows())
    first=ingest(tmp_path,[asset],2022,1,"MA","turnout","demo")
    changed=turnout_rows()
    changed[2][10:12]=[80,20]
    asset2=synthetic_asset(tmp_path,changed,name="updated.csv")
    latest=ingest(tmp_path,[asset2],2022,1,"MA","turnout","demo")
    preview=retain_snapshots(tmp_path,keep=1)
    assert preview["snapshots"][0]["status"]=="PLANNED"
    assert (tmp_path/"gold"/f"{first['snapshot_id']}.duckdb").exists()
    result=retain_snapshots(tmp_path,keep=1,apply=True)
    assert result["retained"]==[latest["snapshot_id"]]
    assert Path(asset["path"]).exists()
    with reader(tmp_path) as db:
        assert db.execute("SELECT sum(absent) FROM section_turnout").fetchone()[0]==120
    with pytest.raises(ValueError,match="retenção"), reader(tmp_path,first["snapshot_id"]):
        pass


def test_repeated_regional_batch_does_not_copy_database(tmp_path):
    from auditabr.regional import publish_year
    asset=synthetic_asset(tmp_path,turnout_rows())
    with Path(asset["path"]).open("rb") as stream:
        project_stream(stream,tmp_path/"capture",2022,("MA",))
    projected=preserve_asset(tmp_path,tmp_path/"capture"/"MA.parquet",
        {"id":"SYNTHETIC","dataset_id":"SYNTHETIC","url":"synthetic://fixture"})
    captured={("MA","turnout"):{"MA":projected}}
    first=publish_year(tmp_path,2022,captured,notify=lambda _:None,rounds=(1,),mode="demo")
    second=publish_year(tmp_path,2022,captured,notify=lambda _:None,rounds=(1,),mode="demo")
    assert second["idempotent"]
    assert first["snapshot_id"]==second["snapshot_id"]
    assert len(list((tmp_path/"gold").glob("*.duckdb")))==1
