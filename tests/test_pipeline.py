import pytest

from auditabr.pipeline import ingest
from auditabr.storage import current_manifest, reader
from tests.helpers import synthetic_asset, turnout_rows


def test_rf015_no_double_count_and_idempotency(tmp_path):
    asset = synthetic_asset(tmp_path, turnout_rows())
    first = ingest(tmp_path, [asset], 2022, 1, "MA", "turnout", "demo")
    with reader(tmp_path) as db:
        assert db.execute("SELECT count(*),sum(eligible),sum(absent) FROM section_turnout").fetchone() == (2, 500, 110)
    second = ingest(tmp_path, [asset], 2022, 1, "MA", "turnout", "demo")
    assert second["idempotent"]
    assert first["snapshot_id"] == second["snapshot_id"]


def test_invalid_partition_keeps_previous_snapshot(tmp_path):
    asset = synthetic_asset(tmp_path, turnout_rows())
    first = ingest(tmp_path, [asset], 2022, 1, "MA", "turnout", "demo")
    bad = turnout_rows()
    bad[1][7:9] = ["1", "Presidente"]
    bad[1][10:12] = [299, 101]
    asset2 = synthetic_asset(tmp_path, bad, name="changed.csv")
    with pytest.raises(ValueError, match="divergente"):
        ingest(tmp_path, [asset2], 2022, 1, "MA", "turnout", "demo")
    assert current_manifest(tmp_path)["snapshot_id"] == first["snapshot_id"]


def test_revision_keeps_old_version(tmp_path):
    asset = synthetic_asset(tmp_path, turnout_rows())
    first = ingest(tmp_path, [asset], 2022, 1, "MA", "turnout", "demo")
    revised = turnout_rows()
    revised[2][10:12] = [80, 20]
    asset2 = synthetic_asset(tmp_path, revised, name="revised.csv")
    second = ingest(tmp_path, [asset2], 2022, 1, "MA", "turnout", "demo")
    assert second["parent"] == first["snapshot_id"]
    with reader(tmp_path, first["snapshot_id"]) as db:
        assert db.execute("SELECT sum(absent) FROM section_turnout").fetchone()[0] == 110
    with reader(tmp_path) as db:
        assert db.execute("SELECT sum(absent) FROM section_turnout").fetchone()[0] == 120


def test_future_never_published(tmp_path):
    from datetime import date
    from unittest.mock import patch
    with patch("auditabr.domain.today", return_value=date(2026, 10, 13)), pytest.raises(ValueError, match="FUTURE"):
        ingest(tmp_path, [], 2026, 2, "MA", "turnout")

