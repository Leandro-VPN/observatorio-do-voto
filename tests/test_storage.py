import duckdb

from auditabr.storage import migrate


def test_schema_migration_is_idempotent():
    with duckdb.connect(":memory:") as db:
        migrate(db)
        migrate(db)
        assert db.execute("SELECT count(*) FROM schema_migration").fetchone()[0] == 2
